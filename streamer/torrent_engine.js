/**
 * torrent_engine.js — Next-Gen WebTorrent Streaming Engine (ESM)
 * Inspired by webtorrent-master (sliding piece windows, critical range prioritization,
 * dynamic peer management, and idle teardown).
 */

import events from 'node:events';
events.defaultMaxListeners = 100;
import WebTorrent from 'webtorrent';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const CACHE_DIR = path.resolve(__dirname, '../.stream_cache');
if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });

// ── Ultra-Expanded Public Trackers ──────────────────────────────────────────
const DEFAULT_TRACKERS = [
    'udp://tracker.opentrackr.org:1337/announce',
    'udp://open.demonii.com:1337/announce',
    'udp://tracker.openbittorrent.com:6969/announce',
    'udp://tracker.torrent.eu.org:451/announce',
    'udp://explodie.org:6969/announce',
    'udp://exodus.desync.com:6969/announce',
    'udp://open.stealth.si:80/announce',
    'udp://tracker.tiny-vps.com:6969/announce',
    'udp://tracker.internetwarriors.net:1337/announce',
    'udp://9.rarbg.to:2920/announce',
    'udp://tracker.cyberia.is:6969/announce',
    'udp://tracker.moeking.me:6969/announce',
    'udp://p4p.arenabg.com:1337/announce',
    'udp://tracker.dler.org:6969/announce',
    'udp://opentracker.i2p.rocks:6969/announce',
    'udp://open.tracker.cl:1337/announce',
    'udp://tracker.filemail.com:6969/announce',
    'udp://tracker.bitsearch.to:1337/announce',
    'http://tracker.opentrackr.org:1337/announce',
    'wss://tracker.openwebtorrent.com',
    'wss://tracker.btorrent.xyz',
    'wss://tracker.webtorrent.dev',
    'wss://tracker.files.fm:7073/announce'
];

const TORRENT_PORT = parseInt(process.env.TORRENT_PORT || '50000', 10);
const DHT_PORT = parseInt(process.env.DHT_PORT || '50001', 10);
const MAX_ACTIVE_TORRENTS = parseInt(process.env.MAX_ACTIVE_TORRENTS || '3', 10);

class TorrentEngine {
    constructor() {
        this.client = new WebTorrent({
            torrentPort: TORRENT_PORT,
            dhtPort: DHT_PORT,
            maxConns: 200,
            dht: true,
            tracker: true,
            utp: true,
            lsd: true,
            natUpnp: true,
            natPmp: true
        });

        this.client.on('error', (err) => {
            console.error('[WebTorrent] Global client error:', err.message);
        });

        // Map<hash, { torrent, lastActive: number, files: Array }>
        this.sessions = new Map();

        // In-flight metadata resolutions to prevent duplicate client.add race conditions
        this.inFlight = new Map();

        // Background idle sweep every 60 seconds
        setInterval(() => this.cleanupIdleSessions(), 60 * 1000).unref();
    }

    canonicalHash(magnetOrHash) {
        let s = (magnetOrHash || '').trim();
        if (s.startsWith('cdn_')) return null;
        if (s.startsWith('magnet:?')) {
            const m = s.match(/xt=urn:btih:([0-9a-fA-F]{40})/i);
            if (m) return m[1].toLowerCase();
            const m32 = s.match(/xt=urn:btih:([2-7A-Za-z]{32})/i);
            if (m32) {
                const b32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
                const str = m32[1].toUpperCase();
                let bits = '';
                for (let c of str) bits += b32.indexOf(c).toString(2).padStart(5, '0');
                let hex = '';
                for (let i = 0; i + 4 <= bits.length; i += 4) hex += parseInt(bits.slice(i, i + 4), 2).toString(16);
                return hex.toLowerCase();
            }
        }
        if (/^[0-9a-f]{40}$/i.test(s)) return s.toLowerCase();
        return null;
    }

    buildMagnet(target, explicitMagnet) {
        const hash = this.canonicalHash(explicitMagnet || target);
        if (!hash) {
            throw new Error(`Invalid torrent hash or identifier: "${target}"`);
        }
        const trackers = new Set(DEFAULT_TRACKERS);

        for (const src of [target, explicitMagnet]) {
            if (src && src.startsWith('magnet:?')) {
                const matches = src.matchAll(/&tr=([^&]+)/g);
                for (const m of matches) {
                    try {
                        const decoded = decodeURIComponent(m[1]);
                        if (decoded) trackers.add(decoded);
                    } catch (_) {}
                }
            }
        }

        const trs = Array.from(trackers).map(t => `&tr=${encodeURIComponent(t)}`).join('');
        return {
            hash,
            magnet: `magnet:?xt=urn:btih:${hash}${trs}`,
            trackers: Array.from(trackers)
        };
    }

    enforceSessionCapacity() {
        if (this.sessions.size < MAX_ACTIVE_TORRENTS) return;
        // Evict only the least recently active session that has NO active readers
        let oldestHash = null;
        let oldestTime = Infinity;
        for (const [hash, sess] of this.sessions.entries()) {
            if ((sess.activeReaders || 0) === 0 && sess.lastActive < oldestTime) {
                oldestTime = sess.lastActive;
                oldestHash = hash;
            }
        }
        if (oldestHash) {
            console.log(`[TorrentEngine] Session limit (${MAX_ACTIVE_TORRENTS}) reached. Evicting idle session: ${oldestHash}`);
            const sess = this.sessions.get(oldestHash);
            try {
                this.client?.remove(sess.torrent, { destroyStore: false }, () => {});
            } catch (_) {}
            this.sessions.delete(oldestHash);
        }
    }

    async addTorrent(target, explicitMagnet = null) {
        const { hash, magnet } = this.buildMagnet(target, explicitMagnet);

        // 1. Return cached ready session if available
        if (this.sessions.has(hash)) {
            const sess = this.sessions.get(hash);
            sess.lastActive = Date.now();
            if (sess.torrent && sess.torrent.ready) {
                return sess.torrent;
            }
        }

        // 2. Await in-flight resolution if another request is already resolving metadata
        if (this.inFlight.has(hash)) {
            return await this.inFlight.get(hash);
        }

        this.enforceSessionCapacity();

        // 3. Check if WebTorrent client already has this torrent instance (MUST await in WebTorrent 3.x)
        let existing = null;
        if (this.client) {
            try {
                existing = await this.client.get(hash);
            } catch (_) {}
        }

        if (existing) {
            const entry = {
                torrent: existing,
                lastActive: Date.now(),
                activeReaders: 0,
                files: (existing.files || []).map((f, i) => ({
                    idx: i,
                    name: f.name,
                    path: f.path,
                    length: f.length
                }))
            };
            this.sessions.set(hash, entry);

            if (existing.ready && existing.files && existing.files.length > 0) {
                return existing;
            }

            const waitReady = new Promise((resolve, reject) => {
                const timer = setTimeout(() => {
                    if (!existing.ready) reject(new Error('Metadata timeout: Unable to fetch torrent metadata within 25s'));
                }, 25000);
                existing.once('ready', () => {
                    clearTimeout(timer);
                    entry.files = (existing.files || []).map((f, i) => ({
                        idx: i,
                        name: f.name,
                        path: f.path,
                        length: f.length
                    }));
                    resolve(existing);
                });
                existing.once('error', (err) => {
                    clearTimeout(timer);
                    reject(err);
                });
            });

            this.inFlight.set(hash, waitReady);
            try {
                return await waitReady;
            } finally {
                this.inFlight.delete(hash);
            }
        }

        // 4. Fresh torrent addition with in-flight lock to prevent duplicate add errors
        const addPromise = new Promise((resolve, reject) => {
            const torrentOpts = {
                path: CACHE_DIR,
                announce: DEFAULT_TRACKERS,
                deselect: true,
                strategy: 'sequential',
                maxWebConns: 50,
                storeCacheSlots: 500
            };

            let settled = false;
            let torrent = null;
            const startTime = Date.now();
            let timerId = null;

            const checkTimeout = () => {
                if (settled || this.sessions.has(hash)) return;
                const elapsed = Date.now() - startTime;
                // If peers are connected and exchanging metadata, give extra time (up to 120s for giant anime batches)
                if (torrent && torrent.numPeers > 0 && elapsed < 120000) {
                    timerId = setTimeout(checkTimeout, 10000);
                    return;
                }
                if (elapsed >= 90000 && !settled) {
                    settled = true;
                    if (torrent) {
                        try {
                            this.client.remove(torrent, { destroyStore: false }, () => {});
                        } catch (_) {}
                    }
                    reject(new Error(`Swarm metadata timeout: Unable to fetch torrent metadata within ${Math.round(elapsed / 1000)}s for hash ${hash}`));
                } else if (!settled) {
                    timerId = setTimeout(checkTimeout, 10000);
                }
            };
            timerId = setTimeout(checkTimeout, 30000);

            const cachedTorrentFile = path.join(CACHE_DIR, `${hash}.torrent`);
            const targetSource = fs.existsSync(cachedTorrentFile) ? cachedTorrentFile : magnet;

            try {
                torrent = this.client.add(targetSource, torrentOpts);
            } catch (err) {
                clearTimeout(timerId);
                return reject(err);
            }

            const onReady = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timerId);

                // Cache .torrent metadata to disk for instant zero-latency future loading
                try {
                    const torrentFilePath = path.join(CACHE_DIR, `${hash}.torrent`);
                    if (!fs.existsSync(torrentFilePath) && torrent.torrentFile) {
                        fs.writeFile(torrentFilePath, torrent.torrentFile, () => {});
                    }
                } catch (_) {}

                const entry = {
                    torrent,
                    lastActive: Date.now(),
                    activeReaders: 0,
                    files: (torrent.files || []).map((f, i) => ({
                        idx: i,
                        name: f.name,
                        path: f.path,
                        length: f.length
                    }))
                };
                this.sessions.set(hash, entry);
                resolve(torrent);
            };

            if (torrent.ready) {
                onReady();
            } else {
                torrent.once('ready', onReady);
            }

            torrent.on('error', (err) => {
                console.error(`[TorrentEngine] Torrent error (${hash}):`, err.message);
                if (!settled && !this.sessions.has(hash)) {
                    settled = true;
                    if (timerId) clearTimeout(timerId);
                    if (torrent) {
                        try {
                            this.client.remove(torrent, { destroyStore: true }, () => {});
                        } catch (_) {}
                    }
                    reject(err);
                }
            });
        });

        this.inFlight.set(hash, addPromise);
        try {
            return await addPromise;
        } finally {
            this.inFlight.delete(hash);
        }
    }

    async getFileMetadata(torrent, file) {
        const hash = this.canonicalHash(torrent.infoHash);
        const sess = hash ? this.sessions.get(hash) : null;
        if (sess && sess.fileInfo) return sess.fileInfo;

        const info = {
            hash: torrent.infoHash,
            name: file ? file.name : torrent.name,
            length: file ? file.length : torrent.length,
            duration_seconds: 0,
            avg_bitrate_bps: 8000000
        };

        if (sess) {
            sess.fileInfo = info;
            sess.avg_bitrate_bps = info.avg_bitrate_bps;
        }
        return info;
    }

    applySlidingWindow(torrent, file, byteOffset = 0, opts = {}) {
        if (!torrent || !torrent.pieces || !torrent.pieceLength || !file) return;
        const pieceLength = torrent.pieceLength;

        // Clear ONLY verified pieces, NEVER blanket-fill false (protects FileIterator critical pieces)
        if (torrent._critical && Array.isArray(torrent._critical) && torrent.bitfield) {
            for (let i = 0; i < torrent._critical.length; i++) {
                if (torrent._critical[i] && torrent.bitfield.get(i)) {
                    torrent._critical[i] = false;
                }
            }
        }

        const hash = this.canonicalHash(torrent.infoHash);
        const sess = hash ? this.sessions.get(hash) : null;
        const avgBitrateBps = (opts.avgBitrateBps || (sess && sess.avg_bitrate_bps) || 8000000);
        const bufferMultiplier = opts.bufferMb ? Math.max(0.5, Math.min(4.0, opts.bufferMb / 200)) : 1.0;

        // Stremio-grade sequential engine: avoid file.select(1) on whole file
        // which causes 185 peers to disperse bandwidth randomly across all 500+ pieces.
        const fileStartPiece = Math.floor(file.offset / pieceLength);
        const fileEndPiece = Math.floor((file.offset + file.length - 1) / pieceLength);
        const totalPieces = Math.max(1, fileEndPiece - fileStartPiece + 1);

        // 1. Critical initial container header / moov atom / EBML headers:
        const criticalCount = Math.max(2, Math.min(4, Math.ceil(totalPieces * 0.02)));
        const headerEnd = Math.min(fileStartPiece + criticalCount - 1, fileEndPiece);
        torrent.select(fileStartPiece, headerEnd, 3);
        if (typeof torrent.critical === 'function') {
            try { torrent.critical(fileStartPiece, Math.min(fileStartPiece + 2, fileEndPiece)); } catch (_) {}
        }

        // 2. Container index / seek tables / cues: Last 2 pieces at priority 3
        const indexPieceCount = Math.min(2, totalPieces);
        const indexStart = Math.max(fileStartPiece, fileEndPiece - indexPieceCount + 1);
        torrent.select(indexStart, fileEndPiece, 3);

        // 3. Time/Bitrate-Adaptive Sliding Window [Phase 2]
        // Target windows in seconds:
        // - criticalSec = 20s ahead at Priority 3 + critical()
        // - bufferSec   = 90s * bufferMultiplier at Priority 2
        // - horizonSec  = 240s * bufferMultiplier at Priority 1
        const bytesPerSec = avgBitrateBps / 8;
        const criticalPieces = Math.max(4, Math.min(64, Math.ceil((20 * bytesPerSec) / pieceLength)));
        const bufferPieces = Math.max(8, Math.min(128, Math.ceil((90 * bufferMultiplier * bytesPerSec) / pieceLength)));
        const horizonPieces = Math.max(16, Math.min(256, Math.ceil((240 * bufferMultiplier * bytesPerSec) / pieceLength)));

        const currentPiece = Math.floor((file.offset + byteOffset) / pieceLength);
        if (currentPiece <= fileEndPiece) {
            const cursorPiece = Math.max(fileStartPiece, currentPiece);

            // 2.5 [STRM-MED-05] Backward-seek starvation: maintain a retention tail of 10 pieces behind cursor
            const deselectEnd = cursorPiece - 1 - 10;
            if (deselectEnd >= fileStartPiece + criticalCount) {
                try {
                    torrent.deselect(fileStartPiece + criticalCount, deselectEnd, false);
                } catch (_) {}
            }

            // Detect backwards seek: if new cursor is behind previous cursor, immediately re-select range
            if (sess && sess.lastCursorPiece !== undefined && cursorPiece < sess.lastCursorPiece) {
                const reselectStart = Math.max(fileStartPiece, cursorPiece - 2);
                const reselectEnd = Math.min(fileEndPiece, cursorPiece + criticalCount);
                torrent.select(reselectStart, reselectEnd, 3);
                if (typeof torrent.critical === 'function') {
                    try { torrent.critical(reselectStart, reselectEnd); } catch (_) {}
                }
            }
            if (sess) {
                sess.lastCursorPiece = cursorPiece;
            }

            // Tier 1: Immediate Start (Priority 3 + Critical)
            const immediateWindow = criticalPieces;
            const immediateEnd = Math.min(fileEndPiece, cursorPiece + immediateWindow);
            torrent.select(cursorPiece, immediateEnd, 3);
            if (typeof torrent.critical === 'function') {
                try { torrent.critical(cursorPiece, Math.min(fileEndPiece, cursorPiece + 3)); } catch (_) {}
            }

            // Tier 2: Multi-Peer Horizon (Priority 2)
            const multiPeerEnd = Math.min(fileEndPiece, immediateEnd + bufferPieces);
            if (multiPeerEnd > immediateEnd) {
                torrent.select(immediateEnd + 1, multiPeerEnd, 2);
            }

            // Tier 3: Lookahead Buffer Reservoir (Priority 1)
            const reservoirEnd = Math.min(fileEndPiece, multiPeerEnd + horizonPieces);
            if (reservoirEnd > multiPeerEnd) {
                torrent.select(multiPeerEnd + 1, reservoirEnd, 1);
            }

            // Deselect distant unneeded pieces
            if (reservoirEnd < fileEndPiece) {
                try {
                    torrent.deselect(reservoirEnd + 1, fileEndPiece, false);
                } catch (_) {}
            }
        }
        this.checkBufferHealth(torrent, file, byteOffset);
    }

    checkBufferHealth(torrent, file, byteOffset = 0) {
        if (!torrent || !file) return null;
        const hash = this.canonicalHash(torrent.infoHash);
        const sess = hash ? this.sessions.get(hash) : null;
        if (!sess) return null;

        const pieceLength = torrent.pieceLength || (1024 * 1024);
        const avgBitrateBps = (sess && sess.avg_bitrate_bps) || 8000000;
        const bytesPerSec = avgBitrateBps / 8;

        const currentSpeed = torrent.downloadSpeed || 0;
        sess.emaSpeed = sess.emaSpeed ? (0.3 * currentSpeed + 0.7 * sess.emaSpeed) : currentSpeed;

        const cursorPiece = Math.floor((file.offset + byteOffset) / pieceLength);
        const fileEndPiece = Math.floor((file.offset + file.length - 1) / pieceLength);

        let verifiedPiecesAhead = 0;
        if (torrent.bitfield) {
            const checkLimit = Math.min(fileEndPiece, cursorPiece + 64);
            for (let i = cursorPiece; i <= checkLimit; i++) {
                if (torrent.bitfield.get(i)) {
                    verifiedPiecesAhead++;
                } else {
                    break;
                }
            }
        }

        const downloadedBytesAhead = verifiedPiecesAhead * pieceLength;
        const secondsAhead = (downloadedBytesAhead * 8) / avgBitrateBps;
        const deficitRatio = bytesPerSec / Math.max(1000, sess.emaSpeed);

        let healthState = 'healthy';
        if (secondsAhead < 2 || (torrent.numPeers === 0 && verifiedPiecesAhead === 0)) {
            healthState = 'starved';
        } else if (secondsAhead < 5 && deficitRatio > 1.2) {
            healthState = 'deficit';
        }

        sess.healthState = healthState;
        sess.secondsAhead = Math.round(secondsAhead * 10) / 10;
        sess.deficitRatio = Math.round(deficitRatio * 100) / 100;

        if (healthState === 'deficit' || healthState === 'starved') {
            const criticalEnd = Math.min(fileEndPiece, cursorPiece + 3);
            torrent.select(cursorPiece, criticalEnd, 3);
            if (typeof torrent.critical === 'function') {
                try { torrent.critical(cursorPiece, criticalEnd); } catch (_) {}
            }

            if (Array.isArray(torrent.wires)) {
                const now = Date.now();
                for (const wire of torrent.wires) {
                    if (wire.downloaded === 0 && wire.connected && (now - (wire.lastActive || now)) > 3000) {
                        try {
                            if (typeof wire.choke === 'function') wire.choke();
                        } catch (_) {}
                    }
                }
            }
        }

        return {
            hash: torrent.infoHash,
            health_state: healthState,
            seconds_ahead: sess.secondsAhead,
            deficit_ratio: sess.deficitRatio,
            speed_bps: Math.round(sess.emaSpeed * 8),
            num_peers: torrent.numPeers || 0,
            unchoked_peers: (torrent.wires || []).filter(w => !w.peerChoking).length
        };
    }

    createReadStream(torrent, file, opts = {}) {
        const start = opts.start || 0;
        this.applySlidingWindow(torrent, file, start, opts);
        const stream = file.createReadStream(opts);
        const hash = this.canonicalHash(torrent.infoHash);
        let currentOffset = start;

        if (hash) {
            const sess = this.sessions.get(hash);
            if (sess) {
                sess.lastActive = Date.now();
                sess.activeReaders = (sess.activeReaders || 0) + 1;

                // 2.3 1-second interval sliding window trigger
                const slideTimer = setInterval(() => {
                    this.applySlidingWindow(torrent, file, currentOffset, opts);
                }, 1000);

                // Immediate slide on peer connection/unchoke
                const wireListener = () => {
                    this.applySlidingWindow(torrent, file, currentOffset, opts);
                };
                torrent.on('wire', wireListener);

                const releaseReader = () => {
                    clearInterval(slideTimer);
                    torrent.removeListener('wire', wireListener);
                    if (sess.activeReaders > 0) sess.activeReaders--;
                    sess.lastActive = Date.now();
                };
                stream.once('close', releaseReader);
                stream.once('end', releaseReader);
                stream.once('error', releaseReader);

                stream.on('data', (chunk) => {
                    sess.lastActive = Date.now();
                    const len = chunk ? chunk.length : 0;
                    currentOffset += len;
                });
            }
        }
        return stream;
    }

    forceEvictSession(targetHash, destroyStore = false) {
        if (!targetHash) return;
        const normActive = String(targetHash).toLowerCase();
        const sess = this.sessions.get(normActive);
        if (sess) {
            console.log(`[TorrentEngine] Evicting session ${normActive} (destroyStore=${destroyStore})`);
            try {
                this.client?.remove(sess.torrent, { destroyStore }, () => {});
            } catch (_) {}
            this.sessions.delete(normActive);
        }
    }

    cleanupOtherSessions(activeHash) {
        // Deprecated: No longer called on request path to protect concurrent playback
    }

    cleanupIdleSessions(idleTimeoutMs = 5 * 60 * 1000) {
        const now = Date.now();
        for (const [hash, sess] of this.sessions.entries()) {
            if ((sess.activeReaders || 0) === 0 && now - sess.lastActive > idleTimeoutMs) {
                console.log(`[TorrentEngine] Reclaiming idle session: ${hash}`);
                try {
                    this.client?.remove(sess.torrent, { destroyStore: true }, () => {});
                } catch (_) {}
                this.sessions.delete(hash);
            }
        }
    }

    getStatus() {
        const active = [];
        for (const [hash, sess] of this.sessions.entries()) {
            const t = sess.torrent;
            if (!t) continue;
            let piece_map = '';
            if (t.pieces && t.pieces.length > 0) {
                const totalPieces = t.pieces.length;
                const sampleSize = Math.min(64, totalPieces);
                for (let i = 0; i < sampleSize; i++) {
                    const idx = Math.floor((i / sampleSize) * totalPieces);
                    piece_map += t.pieces[idx] ? '1' : '0';
                }
            }

            const peers_list = (t.wires || []).slice(0, 12).map(w => {
                let clientName = 'Peer';
                if (w.extendedHandshake && w.extendedHandshake.v) {
                    clientName = String(w.extendedHandshake.v).slice(0, 20);
                } else if (w.type) {
                    clientName = w.type;
                }
                const downSpeed = typeof w.downloadSpeed === 'function' ? (w.downloadSpeed() / 1024).toFixed(0) : 0;
                const upSpeed = typeof w.uploadSpeed === 'function' ? (w.uploadSpeed() / 1024).toFixed(0) : 0;
                return {
                    client: clientName,
                    type: w.type || 'tcp',
                    downSpeed: `${downSpeed} KB/s`,
                    upSpeed: `${upSpeed} KB/s`
                };
            });

            active.push({
                info_hash: hash,
                name: t.name,
                progress: (t.progress * 100).toFixed(1) + '%',
                buffer_pct: (t.progress * 100).toFixed(1),
                downloadSpeed: (t.downloadSpeed / 1024 / 1024).toFixed(2) + ' MB/s',
                download_speed: t.downloadSpeed,
                uploadSpeed: (t.uploadSpeed / 1024 / 1024).toFixed(2) + ' MB/s',
                upload_speed: t.uploadSpeed,
                numPeers: t.numPeers,
                peers: t.numPeers,
                downloaded: (t.downloaded / 1024 / 1024).toFixed(1) + ' MB',
                total: (t.length / 1024 / 1024).toFixed(1) + ' MB',
                pieces_downloaded: t.pieces ? t.pieces.filter(Boolean).length : 0,
                pieces_total: t.pieces ? t.pieces.length : 0,
                piece_map: piece_map,
                peers_list: peers_list,
                health_state: sess.healthState || 'healthy',
                seconds_ahead: sess.secondsAhead || 0,
                deficit_ratio: sess.deficitRatio || 0,
                lastActiveSecAgo: Math.round((Date.now() - sess.lastActive) / 1000)
            });
        }
        return {
            status: 'online',
            engine: 'webtorrent-v3',
            clientDownloadSpeed: ((this.client?.downloadSpeed || 0) / 1024 / 1024).toFixed(2) + ' MB/s',
            clientUploadSpeed: ((this.client?.uploadSpeed || 0) / 1024 / 1024).toFixed(2) + ' MB/s',
            active_torrents: this.sessions.size,
            sessions: active
        };
    }
}

export default new TorrentEngine();
