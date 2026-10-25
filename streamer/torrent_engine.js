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

class TorrentEngine {
    constructor() {
        this.client = new WebTorrent({
            torrentPort: 50000,
            dhtPort: 50001,
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

    applySlidingWindow(torrent, file, byteOffset = 0) {
        if (!torrent || !torrent.pieces || !torrent.pieceLength || !file) return;
        const pieceLength = torrent.pieceLength;

        // Select the active file pieces at base priority 1 without deselecting other in-flight pieces
        try {
            if (typeof file.select === 'function') file.select(1);
        } catch (_) {}

        const fileStartPiece = Math.floor(file.offset / pieceLength);
        const fileEndPiece = Math.floor((file.offset + file.length - 1) / pieceLength);
        const totalPieces = Math.max(1, fileEndPiece - fileStartPiece + 1);

        // 1. Critical initial container header / moov atom / EBML headers:
        // Prioritize first 4 pieces (up to ~8MB) at critical priority 3 so the player/FFmpeg gets container headers in milliseconds.
        const criticalCount = Math.max(2, Math.min(4, Math.ceil(totalPieces * 0.02)));
        const headerEnd = Math.min(fileStartPiece + criticalCount - 1, fileEndPiece);
        torrent.select(fileStartPiece, headerEnd, 3);
        if (typeof torrent.critical === 'function') {
            try { torrent.critical(fileStartPiece, Math.min(fileStartPiece + 1, fileEndPiece)); } catch (_) {}
        }

        // 2. Container index / seek tables / cues: Last 2 pieces at priority 3
        const indexPieceCount = Math.min(2, totalPieces);
        const indexStart = Math.max(fileStartPiece, fileEndPiece - indexPieceCount + 1);
        torrent.select(indexStart, fileEndPiece, 3);

        // 3. Multi-Tier Concurrent Sliding Window around playback cursor (byteOffset):
        // - Tier 1 (Immediate Horizon): Current playback piece + 8 pieces ahead at Priority 3 (instant seek & play, zero stall)
        // - Tier 2 (Multi-Peer Horizon): Next 32 pieces ahead at Priority 2 (distributes parallel piece requests across multiple swarm wires)
        // - Tier 3 (Predictive Reservoir): Next 64 pieces ahead at Priority 1 (deep background buffer to saturate swarm throughput)
        const currentPiece = Math.floor((file.offset + byteOffset) / pieceLength);
        if (currentPiece <= fileEndPiece) {
            const cursorPiece = Math.max(fileStartPiece, currentPiece);
            const immediateWindow = 8;
            const immediateEnd = Math.min(fileEndPiece, cursorPiece + immediateWindow);
            torrent.select(cursorPiece, immediateEnd, 3);

            // Activate WebTorrent native CRITICAL hotswap for the immediate next 3 pieces
            if (typeof torrent.critical === 'function') {
                try { torrent.critical(cursorPiece, Math.min(fileEndPiece, cursorPiece + 3)); } catch (_) {}
            }

            const bufferPieces = 32;
            const multiPeerHorizon = bufferPieces;
            const multiPeerEnd = Math.min(fileEndPiece, immediateEnd + multiPeerHorizon);
            if (multiPeerEnd > immediateEnd) {
                torrent.select(immediateEnd + 1, multiPeerEnd, 2);
            }

            const backgroundHorizon = 64;
            const reservoirEnd = Math.min(fileEndPiece, multiPeerEnd + backgroundHorizon);
            if (reservoirEnd > multiPeerEnd) {
                torrent.select(multiPeerEnd + 1, reservoirEnd, 1);
            }
        }
    }

    createReadStream(torrent, file, opts = {}) {
        const start = opts.start || 0;
        this.applySlidingWindow(torrent, file, start);
        const stream = file.createReadStream(opts);
        const hash = this.canonicalHash(torrent.infoHash);
        const pieceLength = torrent.pieceLength || (1024 * 1024);
        const slideThreshold = pieceLength * 2;
        let currentOffset = start;
        let bytesSinceWindowSlide = 0;

        if (hash) {
            const sess = this.sessions.get(hash);
            if (sess) {
                sess.lastActive = Date.now();
                stream.on('data', (chunk) => {
                    sess.lastActive = Date.now();
                    const len = chunk ? chunk.length : 0;
                    currentOffset += len;
                    bytesSinceWindowSlide += len;
                    if (bytesSinceWindowSlide >= slideThreshold) {
                        bytesSinceWindowSlide = 0;
                        this.applySlidingWindow(torrent, file, currentOffset);
                    }
                });
            }
        }
        return stream;
    }

    cleanupIdleSessions(idleTimeoutMs = 30 * 60 * 1000) {
        const now = Date.now();
        for (const [hash, sess] of this.sessions.entries()) {
            if (now - sess.lastActive > idleTimeoutMs) {
                console.log(`[TorrentEngine] Reclaiming idle session and purging piece store: ${hash}`);
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
