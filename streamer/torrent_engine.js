/**
 * torrent_engine.js — Next-Gen WebTorrent Streaming Engine (ESM)
 * Inspired by webtorrent-master (sliding piece windows, critical range prioritization,
 * dynamic peer management, and idle teardown).
 */

import events from 'node:events';
events.defaultMaxListeners = 100;
import { Readable } from 'node:stream';
import WebTorrent from 'webtorrent';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const CACHE_DIR = path.resolve(process.env.EVO_STREAM_CACHE_DIR || path.resolve(__dirname, '../.stream_cache'));
if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
const PEER_CACHE_FILE = path.join(CACHE_DIR, 'peers.json');
const DHT_TABLE_FILE = path.join(CACHE_DIR, 'dht_table.json');

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
const OFFLINE_MODE = /^(1|true|yes)$/i.test(process.env.EVO_ENGINE_OFFLINE || '');

const SLIDE_INTERVAL_MS = parseInt(process.env.EVO_SLIDE_INTERVAL_MS || '1000', 10);
const RETENTION_PIECES = 10;
const URGENT_SECONDS = 20;
const BUFFER_SECONDS = 60;
const URGENT_MIN_PIECES = 4;
const URGENT_MAX_PIECES = 48;
const BUFFER_MIN_PIECES = 8;
const BUFFER_MAX_PIECES = 128;
const LOOKAHEAD_SCAN_SECONDS = 120;
const LOOKAHEAD_SCAN_PIECES_MIN = 64;
const LOOKAHEAD_SCAN_PIECES_MAX = 4096;
const STALL_RECOVERY_WINDOW_PIECES = 8;
const STALL_RECOVERY_AFTER_MS = 8000;
const STALL_RECOVERY_COOLDOWN_MS = 8000;
const STALL_RECOVERY_MAX_CANCELS = 2;
const STALL_RECOVERY_MIN_WIRE_SPEED_BPS = 1024;
const PEER_CACHE_FLUSH_MS = Math.max(0, parseInt(process.env.EVO_PEER_CACHE_FLUSH_MS || '15000', 10));
// Swarm pause hysteresis (stremio swarm_paused equivalent): stop requesting
// lookahead pieces once the buffer is deep, resume when it drains.
const SWARM_PAUSE_ABOVE_SECONDS = 90;
const SWARM_RESUME_BELOW_SECONDS = 60;
// Download shaping multipliers over measured playback rate (bytes/sec).
const SHAPE_SOFT_MULT = 2.0;
const SHAPE_HARD_MULT = 4.0;
// Piece streams yield ~16 KB iterator chunks. Serving those straight into an
// HTTP response costs a pipe iteration and socket write per chunk; merging
// into large batches cuts that overhead by two orders of magnitude.
const STREAM_MERGE_BYTES = Math.max(0, parseInt(process.env.EVO_STREAM_MERGE_BYTES || '1048576', 10));

async function* _mergeChunks(source, targetBytes) {
    try {
        let pending = null;
        let pendingLen = 0;
        for await (const chunk of source) {
            if (!chunk || chunk.length === 0) continue;
            if (pending === null) {
                pending = chunk;
                pendingLen = chunk.length;
            } else {
                pending = Buffer.concat([pending, chunk]);
                pendingLen += chunk.length;
            }
            if (pendingLen >= targetBytes) {
                yield pending;
                pending = null;
                pendingLen = 0;
            }
        }
        if (pending !== null) yield pending;
    } finally {
        if (source && typeof source.destroy === 'function' && !source.destroyed) {
            source.destroy();
        }
    }
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function positiveNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) && num > 0 ? num : fallback;
}

class TorrentEngine {
    constructor(options = {}) {
        if (options.client !== undefined) {
            this.client = options.client;
        } else {
            this.client = new WebTorrent(options.clientOptions || {
                torrentPort: TORRENT_PORT,
                dhtPort: DHT_PORT,
                maxConns: OFFLINE_MODE ? 8 : 200,
                // NEXT.md 3.4: restore the DHT routing table saved on a
                // previous run for near-instant non-tracker peer discovery.
                dht: OFFLINE_MODE ? false : { nodes: this._loadDhtTable() },
                tracker: !OFFLINE_MODE,
                utp: !OFFLINE_MODE,
                lsd: !OFFLINE_MODE,
                natUpnp: !OFFLINE_MODE,
                natPmp: !OFFLINE_MODE
            });
            this.client.on('error', (err) => {
                console.error('[WebTorrent] Global client error:', err.message);
            });
        }

        // Map<hash, { torrent, lastActive: number, files: Array, readers: Map }>
        this.sessions = new Map();

        // In-flight metadata resolutions to prevent duplicate client.add race conditions
        this.inFlight = new Map();

        // Monotonic id source for read-stream readers
        this._readerSeq = 0;

        // Peer cache is kept in memory and flushed to disk on a debounce;
        // per-wire-event synchronous writes would stall the streaming loop.
        this._peerCache = null;
        this._peerCacheDirty = false;
        this._peerCacheFlushTimer = null;

        // Background idle sweep every 60 seconds; peer re-injection runs on a
        // slower cadence to re-contact known-good peers on live sessions.
        if (options.idleSweep !== false) {
            this._idleSweepTimer = setInterval(() => this.cleanupIdleSessions(), 60 * 1000);
            this._idleSweepTimer.unref?.();
            this._peerReinjectTimer = setInterval(() => this._reinjectCachedPeers(), 120 * 1000);
            this._peerReinjectTimer.unref?.();
            this._dhtSaveTimer = setInterval(() => this._saveDhtTable(), 300 * 1000);
            this._dhtSaveTimer.unref?.();
        }
    }

    _loadDhtTable() {
        try {
            if (fs.existsSync(DHT_TABLE_FILE)) {
                const nodes = JSON.parse(fs.readFileSync(DHT_TABLE_FILE, 'utf-8'));
                if (Array.isArray(nodes)) {
                    return nodes.filter(n => n && typeof n.host === 'string' && Number.isFinite(n.port)).slice(0, 200);
                }
            }
        } catch (_) {}
        return [];
    }

    _saveDhtTable() {
        try {
            const dht = this.client && this.client.dht;
            if (!dht || typeof dht.toArray !== 'function') return;
            const nodes = dht.toArray();
            if (!Array.isArray(nodes) || nodes.length === 0) return;
            fs.writeFileSync(DHT_TABLE_FILE, JSON.stringify(nodes.slice(0, 200)), 'utf-8');
        } catch (_) {}
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

    _loadPeerCache() {
        if (this._peerCache !== null) return this._peerCache;
        let data = {};
        try {
            if (fs.existsSync(PEER_CACHE_FILE)) {
                try { data = JSON.parse(fs.readFileSync(PEER_CACHE_FILE, 'utf-8')); } catch (_) {}
            }
        } catch (_) {}
        if (!data || typeof data !== 'object' || Array.isArray(data)) data = {};
        this._peerCache = data;
        return this._peerCache;
    }

    loadCachedPeers(hash) {
        const data = this._loadPeerCache();
        return Array.isArray(data[hash]) ? data[hash] : [];
    }

    saveCachedPeers(hash, peers) {
        try {
            const data = this._loadPeerCache();
            const existing = new Set(data[hash] || []);
            for (const p of peers) {
                if (p && typeof p === 'string') existing.add(p);
            }
            data[hash] = Array.from(existing).slice(-100);
            this._peerCacheDirty = true;
            this._schedulePeerCacheFlush();
        } catch (_) {}
    }

    _schedulePeerCacheFlush() {
        if (this._peerCacheFlushTimer || !this._peerCacheDirty) return;
        this._peerCacheFlushTimer = setTimeout(() => {
            this._peerCacheFlushTimer = null;
            this.flushPeerCache();
        }, PEER_CACHE_FLUSH_MS);
        this._peerCacheFlushTimer.unref?.();
    }

    flushPeerCache() {
        if (this._peerCacheFlushTimer) {
            clearTimeout(this._peerCacheFlushTimer);
            this._peerCacheFlushTimer = null;
        }
        if (!this._peerCacheDirty || this._peerCache === null) return false;
        try {
            fs.writeFileSync(PEER_CACHE_FILE, JSON.stringify(this._peerCache, null, 2), 'utf-8');
            this._peerCacheDirty = false;
            return true;
        } catch (_) {
            return false;
        }
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
        const requestStartedAt = Date.now();

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
                readers: new Map(),
                metadataMs: existing.ready ? 0 : undefined,
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
                    entry.metadataMs = Date.now() - requestStartedAt;
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
            const storeSlots = parseInt(process.env.EVO_STORE_CACHE_SLOTS || '128', 10);
            const maxWebConns = parseInt(process.env.EVO_MAX_WEB_CONNS || '50', 10);
            const torrentOpts = {
                path: CACHE_DIR,
                announce: DEFAULT_TRACKERS,
                deselect: true,
                strategy: 'sequential',
                maxWebConns: maxWebConns,
                storeCacheSlots: storeSlots
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
                const cachedPeers = this.loadCachedPeers(hash);
                if (cachedPeers.length > 0 && typeof torrent.addPeer === 'function') {
                    for (const peer of cachedPeers) {
                        try { torrent.addPeer(peer); } catch (_) {}
                    }
                }
                torrent.on('wire', (wire) => {
                    if (wire.remoteAddress && wire.remotePort) {
                        this.saveCachedPeers(hash, [`${wire.remoteAddress}:${wire.remotePort}`]);
                    }
                    // T0.6: per-source accounting (stremio Statistics.sources
                    // equivalent) — how many peers each discovery surface yields.
                    const entry = this.sessions.get(hash);
                    if (entry) {
                        if (!(entry.sourceStats instanceof Map)) entry.sourceStats = new Map();
                        const key = wire.type === 'webSeed' ? 'webseed'
                            : (wire.peerId && wire._tracker !== undefined) ? 'tracker'
                                : 'dht';
                        const stats = entry.sourceStats.get(key) || { found: 0, uniq: new Set() };
                        stats.found += 1;
                        if (wire.remoteAddress) stats.uniq.add(`${wire.remoteAddress}:${wire.remotePort}`);
                        entry.sourceStats.set(key, stats);
                    }
                });
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
                    readers: new Map(),
                    metadataMs: Date.now() - requestStartedAt,
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
            duration_seconds: (sess && sess.duration_seconds) || 0,
            avg_bitrate_bps: (sess && sess.avg_bitrate_bps) || 8000000
        };

        if (sess) {
            sess.fileInfo = info;
        }
        return info;
    }

    /**
     * P1: stores crowd-sourced seek hotspots (seconds within the file) for a
     * session. The scheduler pre-selects low-priority pieces around them so
     * statistically-likely seeks land on already-buffered data.
     */
    setSeekHints(targetHash, targets) {
        const hash = this.canonicalHash(targetHash);
        if (!hash) return null;
        const sess = this.sessions.get(hash);
        if (!sess) return null;
        const clean = Array.from(new Set(
            (Array.isArray(targets) ? targets : [])
                .map(t => Number(t))
                .filter(t => Number.isFinite(t) && t > 0)
        )).sort((a, b) => a - b).slice(0, 4);
        sess.seekHints = clean;
        return { seek_hints: sess.seekHints };
    }

    /**
     * Feeds measured media metadata (from ffprobe) into a live session so the
     * sliding window, buffer-health watchdog, and lookahead scans are sized by
     * the real bitrate instead of the 8 Mbps fallback.
     * Explicit avgBitrateBps wins; otherwise bitrate derives from fileLength/duration.
     */
    setSessionMetadata(targetHash, metadata = {}) {
        const hash = this.canonicalHash(targetHash);
        if (!hash) return null;
        const sess = this.sessions.get(hash);
        if (!sess) return null;

        const durationSeconds = Number(metadata.durationSeconds);
        const explicitBitrate = Number(metadata.avgBitrateBps);
        const fileLength = Number(metadata.fileLength);

        let derivedBitrate = 0;
        if (Number.isFinite(durationSeconds) && durationSeconds > 0 &&
            Number.isFinite(fileLength) && fileLength > 0) {
            derivedBitrate = Math.round((fileLength * 8) / durationSeconds);
        }

        const effectiveBitrate = (Number.isFinite(explicitBitrate) && explicitBitrate > 0)
            ? Math.round(explicitBitrate)
            : derivedBitrate;

        if (effectiveBitrate > 0) sess.avg_bitrate_bps = effectiveBitrate;
        if (Number.isFinite(durationSeconds) && durationSeconds > 0) sess.duration_seconds = durationSeconds;

        if (sess.fileInfo) {
            if (sess.duration_seconds > 0) sess.fileInfo.duration_seconds = sess.duration_seconds;
            if (sess.avg_bitrate_bps > 0) sess.fileInfo.avg_bitrate_bps = sess.avg_bitrate_bps;
        }

        return {
            duration_seconds: sess.duration_seconds || 0,
            avg_bitrate_bps: sess.avg_bitrate_bps || 8000000
        };
    }

    _pieceBounds(file, pieceLength) {
        const safePieceLength = positiveNumber(pieceLength, 256 * 1024);
        const fileOffset = Math.max(0, Number(file?.offset) || 0);
        const fileLength = positiveNumber(file?.length, 1);
        const fileStartPiece = Math.floor(fileOffset / safePieceLength);
        const fileEndPiece = Math.floor((fileOffset + fileLength - 1) / safePieceLength);
        return {
            fileStartPiece,
            fileEndPiece,
            totalPieces: Math.max(1, fileEndPiece - fileStartPiece + 1)
        };
    }

    _buildReaderIntervals(fileStartPiece, fileEndPiece, cursorPiece, opts = {}, sess = null) {
        const pieceLength = positiveNumber(opts.pieceLength, 256 * 1024);
        const avgBitrateBps = positiveNumber(
            opts.avgBitrateBps || (sess && sess.avg_bitrate_bps),
            8000000
        );
        const bytesPerSec = avgBitrateBps / 8;
        const bufferMultiplier = opts.bufferMb
            ? clamp(Number(opts.bufferMb) / 200, 0.5, 4.0)
            : 1.0;
        const contraction = sess?.healthState === 'starved'
            ? 0.35
            : sess?.healthState === 'deficit'
                ? 0.7
                : 1.0;

        const urgentPieces = clamp(
            Math.ceil((URGENT_SECONDS * bytesPerSec) / pieceLength),
            URGENT_MIN_PIECES,
            URGENT_MAX_PIECES
        );
        // Deep staging (P6): a warm-up call may extend the urgent window to
        // cover the opening seconds of the next episode with real bytes.
        const stageSeconds = positiveNumber(opts.stageSeconds, 0);
        const stagedUrgentPieces = stageSeconds > 0
            ? clamp(Math.ceil((stageSeconds * bytesPerSec) / pieceLength), urgentPieces, URGENT_MAX_PIECES * 4)
            : 0;
        const effectiveUrgentPieces = Math.max(urgentPieces, stagedUrgentPieces);

        // Swarm pause (T0.1) and download shaping (T0.5) suppress the
        // lookahead tier entirely or halve it once the buffer is deep and the
        // swarm is racing far ahead of playback rate.
        let shapeDivisor = 1;
        if (sess?.swarmPaused || sess?.shapeLevel === 2) {
            shapeDivisor = Infinity;
        } else if (sess?.shapeLevel === 1) {
            shapeDivisor = 2;
        }

        const bufferPieces = shapeDivisor === Infinity
            ? 0
            : Math.ceil(clamp(
                Math.ceil((BUFFER_SECONDS * bufferMultiplier * contraction * bytesPerSec) / pieceLength),
                BUFFER_MIN_PIECES,
                BUFFER_MAX_PIECES
            ) / shapeDivisor);

        const urgentEnd = Math.min(fileEndPiece, cursorPiece + effectiveUrgentPieces);
        const intervals = [{ start: cursorPiece, end: urgentEnd, priority: 3 }];
        const urgentRanges = [{ start: cursorPiece, end: urgentEnd }];

        // Leave one unselected piece between tiers. Adjacent selections are
        // concatenated by WebTorrent and inherit the highest priority, which
        // would turn the entire lookahead into a priority-3 free-for-all.
        // The one-piece gap remains covered by the FileIterator's priority-1
        // stream selection and becomes urgent as the cursor advances.
        const bufferStart = urgentEnd + 2;
        if (bufferPieces > 0 && bufferStart <= fileEndPiece) {
            intervals.push({
                start: bufferStart,
                end: Math.min(fileEndPiece, bufferStart + bufferPieces - 1),
                priority: 2
            });
        }

        const retentionEnd = cursorPiece - 2;
        const retentionStart = Math.max(fileStartPiece, cursorPiece - RETENTION_PIECES);
        if (retentionEnd >= retentionStart) {
            intervals.push({ start: retentionStart, end: retentionEnd, priority: 1 });
        }

        return { intervals, urgentRanges };
    }

    _normalizeIntervals(intervals, fileStartPiece, fileEndPiece) {
        const clipped = intervals
            .map(item => ({
                start: Math.max(fileStartPiece, Math.floor(item.start)),
                end: Math.min(fileEndPiece, Math.floor(item.end)),
                priority: item.priority
            }))
            .filter(item => item.start <= item.end)
            .sort((a, b) => a.start - b.start || b.priority - a.priority);

        const out = [];
        for (const item of clipped) {
            let current = item;
            while (true) {
                const last = out[out.length - 1];
                if (!last) {
                    out.push(current);
                    break;
                }
                if (current.start <= last.end) {
                    last.end = Math.max(last.end, current.end);
                    last.priority = Math.max(last.priority, current.priority);
                    break;
                }
                if (current.start !== last.end + 1) {
                    out.push(current);
                    break;
                }
                if (current.priority === last.priority) {
                    last.end = current.end;
                    break;
                }
                if (current.priority < last.priority) {
                    // Trim the lower-priority tier's leading piece so the
                    // selection stays separate. The stream selection still
                    // covers it until the cursor advances.
                    current = { ...current, start: current.start + 1 };
                    if (current.start > current.end) break;
                    continue;
                }
                last.end -= 1;
                if (last.start > last.end) out.pop();
            }
        }
        return out;
    }

    _collectSchedule(torrent, file, opts, readers) {
        if (!torrent || !torrent.pieces || !torrent.pieceLength || !file) return null;

        const bounds = this._pieceBounds(file, torrent.pieceLength);
        const { fileStartPiece, fileEndPiece, totalPieces } = bounds;
        const hash = this.canonicalHash(torrent.infoHash);
        const sess = hash ? this.sessions.get(hash) : null;
        const pieceLength = positiveNumber(torrent.pieceLength, 256 * 1024);

        const headerPieces = clamp(Math.ceil(totalPieces * 0.02), 2, 8);
        const indexPieces = Math.min(2, totalPieces);
        const intervals = [
            {
                start: fileStartPiece,
                end: Math.min(fileEndPiece, fileStartPiece + headerPieces - 1),
                priority: 3
            },
            {
                start: Math.max(fileStartPiece, fileEndPiece - indexPieces + 1),
                end: fileEndPiece,
                priority: 3
            }
        ];

        const urgentRanges = [];
        const readerCursors = [];

        // P1 collective seek forecasting: pre-select pieces around seek
        // hotspots gossiped from the mesh, at low priority so real playback
        // always wins the bandwidth race. Hints are in seconds of the file.
        if (sess && Array.isArray(sess.seekHints) && sess.seekHints.length > 0) {
            const hintBytesPerSec = positiveNumber(sess.avg_bitrate_bps, 8000000) / 8;
            const spanPieces = clamp(
                Math.ceil((120 * hintBytesPerSec) / pieceLength),
                2,
                64
            );
            for (const hintSeconds of sess.seekHints) {
                const hintByte = Math.max(0, hintSeconds * hintBytesPerSec);
                const hintPiece = clamp(
                    fileStartPiece + Math.floor(hintByte / pieceLength),
                    fileStartPiece,
                    fileEndPiece
                );
                intervals.push({
                    start: Math.max(fileStartPiece, hintPiece - spanPieces),
                    end: Math.min(fileEndPiece, hintPiece + spanPieces),
                    priority: 1
                });
            }
        }

        for (const reader of readers) {
            const cursorByte = Math.max(0, Number(reader.cursorByte) || 0);
            const cursorPiece = clamp(
                Math.floor((file.offset + cursorByte) / pieceLength),
                fileStartPiece,
                fileEndPiece
            );
            if (!reader.transient) {
                if (reader.lastCursorPiece !== undefined && cursorPiece < reader.lastCursorPiece) {
                    reader.backwardSeeks = (reader.backwardSeeks || 0) + 1;
                }
                reader.lastCursorPiece = cursorPiece;
                reader.cursorPiece = cursorPiece;
            }
            // P1 impact metric: when seek hints exist, count whether this
            // seek landed inside a pre-warmed hint window.
            if (sess && Array.isArray(sess.seekHints) && sess.seekHints.length > 0
                && (reader.transientSeek === true
                    || (!reader.transient && reader.lastCursorPiece !== undefined && cursorPiece !== reader.lastCursorPiece))) {
                if (!sess.hintStats) sess.hintStats = { seeks: 0, hits: 0 };
                sess.hintStats.seeks += 1;
                const hintBytesPerSec = positiveNumber(sess.avg_bitrate_bps, 8000000) / 8;
                const hintSpan = clamp(Math.ceil((120 * hintBytesPerSec) / pieceLength), 2, 64);
                const nearHint = sess.seekHints.some(h => {
                    const hintPiece = clamp(
                        fileStartPiece + Math.floor(Math.max(0, h * hintBytesPerSec) / pieceLength),
                        fileStartPiece,
                        fileEndPiece
                    );
                    return Math.abs(cursorPiece - hintPiece) <= hintSpan;
                });
                if (nearHint) sess.hintStats.hits += 1;
            }

            readerCursors.push(cursorPiece);
            const readerSchedule = this._buildReaderIntervals(
                fileStartPiece,
                fileEndPiece,
                cursorPiece,
                { ...opts, pieceLength },
                sess
            );
            intervals.push(...readerSchedule.intervals);
            urgentRanges.push(...readerSchedule.urgentRanges);
        }

        return {
            fileStartPiece,
            fileEndPiece,
            intervals: this._normalizeIntervals(intervals, fileStartPiece, fileEndPiece),
            urgentRanges,
            readerCursors,
            readers,
            sess
        };
    }

    _clearStaleCritical(torrent, urgentRanges) {
        if (!torrent._critical || !Array.isArray(torrent._critical)) return;
        for (const key in torrent._critical) {
            if (!torrent._critical[key]) continue;
            const index = Number(key);
            if (!Number.isInteger(index)) continue;
            const isUrgent = urgentRanges.some(r => index >= r.start && index <= r.end);
            const isVerified = torrent.bitfield && torrent.bitfield.get(index);
            if (isVerified || !isUrgent) {
                torrent._critical[index] = false;
            }
        }
    }

    applySlidingWindow(torrent, file, byteOffset = undefined, opts = {}, reader = null) {
        const hasOffset = Number.isFinite(byteOffset) && byteOffset >= 0;
        if (reader && hasOffset) reader.cursorByte = byteOffset;

        const hash = this.canonicalHash(torrent?.infoHash);
        const sess = hash ? this.sessions.get(hash) : null;
        let readers;
        if (reader) {
            readers = sess && sess.readers instanceof Map && sess.readers.size > 0
                ? Array.from(sess.readers.values())
                : [reader];
        } else if (hasOffset) {
            // Legacy warm-up call: emphasis only, no reader registration.
            // transientSeek marks this as an actual seek for the P1 metric.
            readers = [{ cursorByte: byteOffset, transient: true, transientSeek: true }];
        } else if (sess && sess.readers instanceof Map && sess.readers.size > 0) {
            readers = Array.from(sess.readers.values());
        } else {
            readers = [{ cursorByte: 0, transient: true, transientSeek: false }];
        }

        const schedule = this._collectSchedule(torrent, file, opts, readers);
        if (!schedule) return;

        this._clearStaleCritical(torrent, schedule.urgentRanges);

        // Drop every non-stream selection we own before re-adding the tiers.
        // Stream selections created by FileIterator are untouched and keep
        // covering the whole read range at priority 1.
        try {
            torrent.deselect(schedule.fileStartPiece, schedule.fileEndPiece);
        } catch (_) {}
        for (const interval of schedule.intervals) {
            try {
                torrent.select(interval.start, interval.end, interval.priority);
            } catch (_) {}
        }

        // FileIterator flags the three pieces it is about to read as critical.
        // Mirror that for the near edge of each reader's urgent window so
        // request pipelining starts as soon as bytes become available.
        for (const range of schedule.urgentRanges) {
            if (typeof torrent.critical === 'function') {
                try {
                    torrent.critical(range.start, Math.min(range.end, range.start + 7));
                } catch (_) {}
            }
        }

        // Container seek tables (MP4 moov, MKV cues) often live at the tail of
        // the file. Keep the final index pieces critical so probing and seeking
        // do not have to wait for the whole download to reach them.
        const indexPieces = Math.min(2, schedule.fileEndPiece - schedule.fileStartPiece + 1);
        if (indexPieces > 0 && typeof torrent.critical === 'function') {
            try {
                torrent.critical(schedule.fileEndPiece - indexPieces + 1, schedule.fileEndPiece);
            } catch (_) {}
        }

        const pieceLength = positiveNumber(torrent.pieceLength, 256 * 1024);
        const primaryPiece = reader && Number.isInteger(reader.cursorPiece)
            ? reader.cursorPiece
            : schedule.readerCursors[schedule.readerCursors.length - 1];
        const cursorByte = Number.isInteger(primaryPiece)
            ? Math.max(0, primaryPiece * pieceLength - (file.offset || 0))
            : 0;
        this.checkBufferHealth(torrent, file, cursorByte);
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
        const scanPieces = clamp(
            Math.ceil((LOOKAHEAD_SCAN_SECONDS * bytesPerSec) / pieceLength),
            LOOKAHEAD_SCAN_PIECES_MIN,
            LOOKAHEAD_SCAN_PIECES_MAX
        );
        if (torrent.bitfield) {
            const checkLimit = Math.min(fileEndPiece, cursorPiece + scanPieces - 1);
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

        // Swarm pause/resume hysteresis (T0.1, stremio `swarm_paused`): with a
        // deep buffer the lookahead tier stops requesting entirely; it resumes
        // only after the buffer drains past the lower threshold, so the state
        // cannot flap at the boundary.
        if (secondsAhead >= SWARM_PAUSE_ABOVE_SECONDS) {
            sess.swarmPaused = true;
        } else if (secondsAhead < SWARM_RESUME_BELOW_SECONDS) {
            sess.swarmPaused = false;
        }

        // Download shaping (T0.5, stremio `swarm_cap`): when the swarm is
        // racing far ahead of the consumption rate, halve the lookahead tier
        // (level 1) or pause it (level 2 via hysteresis above). Never applied
        // while starved/deficit — recovery always gets full bandwidth.
        if (sess.emaSpeed > bytesPerSec * SHAPE_SOFT_MULT && secondsAhead > BUFFER_SECONDS) {
            sess.shapeLevel = Math.max(sess.shapeLevel || 0, 1);
        } else if (secondsAhead <= SWARM_RESUME_BELOW_SECONDS) {
            sess.shapeLevel = 0;
        }

        sess.healthState = healthState;
        sess.secondsAhead = Math.round(secondsAhead * 10) / 10;
        sess.deficitRatio = Math.round(deficitRatio * 100) / 100;

        if (healthState === 'deficit' || healthState === 'starved') {
            const criticalEnd = Math.min(fileEndPiece, cursorPiece + 3);
            if (typeof torrent.critical === 'function') {
                try { torrent.critical(cursorPiece, criticalEnd); } catch (_) {}
            }
        }

        // Stalled swarm recovery: WebTorrent's hotswap only moves a block when
        // a faster wire asks for the same piece. Nudge it by cancelling a
        // small number of long-pending requests on genuinely slow wires, but
        // only when another unchoked wire already has those pieces. `choke()`
        // is upload-side back-pressure, not a download remedy, so it is never
        // used here. The per-session cooldown keeps this bounded.
        if (healthState === 'starved') {
            this._recoverStalledRequests(torrent, sess, cursorPiece, fileEndPiece);
        }

        return {
            hash: torrent.infoHash,
            health_state: healthState,
            seconds_ahead: sess.secondsAhead,
            verified_pieces_ahead: verifiedPiecesAhead,
            scan_pieces: scanPieces,
            deficit_ratio: sess.deficitRatio,
            speed_bps: Math.round(sess.emaSpeed * 8),
            num_peers: torrent.numPeers || 0,
            unchoked_peers: (torrent.wires || []).filter(w => !w.peerChoking).length
        };
    }

    _recoverStalledRequests(torrent, sess, cursorPiece, fileEndPiece) {
        if (!Array.isArray(torrent.wires) || torrent.wires.length < 2) return 0;
        if (!(sess.stalledRequests instanceof Map)) sess.stalledRequests = new Map();

        const now = Date.now();
        if (now - (sess.lastStallRecoveryAt || 0) < STALL_RECOVERY_COOLDOWN_MS) return 0;

        const presentWires = new Set(torrent.wires);
        for (const [wire, tracked] of sess.stalledRequests) {
            if (!presentWires.has(wire) || wire.destroyed) sess.stalledRequests.delete(wire);
        }

        const urgentStart = cursorPiece;
        const urgentEnd = Math.min(fileEndPiece, cursorPiece + STALL_RECOVERY_WINDOW_PIECES - 1);
        let cancels = 0;

        for (const wire of torrent.wires) {
            if (cancels >= STALL_RECOVERY_MAX_CANCELS) break;
            if (!wire || wire.destroyed || wire.peerChoking || wire.type === 'webSeed') continue;
            if (!Array.isArray(wire.requests) || wire.requests.length === 0) continue;
            if (typeof wire.downloadSpeed !== 'function' || typeof wire.cancel !== 'function') continue;
            if (wire.downloadSpeed() >= STALL_RECOVERY_MIN_WIRE_SPEED_BPS) continue;

            let tracked = sess.stalledRequests.get(wire);
            if (!tracked) {
                tracked = new Map();
                sess.stalledRequests.set(wire, tracked);
            }

            const presentKeys = new Set();
            for (const request of wire.requests) {
                if (cancels >= STALL_RECOVERY_MAX_CANCELS) break;
                const index = request && request.piece;
                if (!Number.isInteger(index) || index < urgentStart || index > urgentEnd) continue;

                const key = `${index}:${request.offset}:${request.length}`;
                presentKeys.add(key);

                const firstSeen = tracked.get(key);
                if (firstSeen === undefined) {
                    tracked.set(key, now);
                    continue;
                }
                if (now - firstSeen < STALL_RECOVERY_AFTER_MS) continue;

                const hasAlternative = torrent.wires.some(other => {
                    if (!other || other === wire || other.destroyed || other.peerChoking) return false;
                    if (!other.peerPieces || typeof other.peerPieces.get !== 'function') return false;
                    if (!other.peerPieces.get(index)) return false;
                    if (typeof other.downloadSpeed !== 'function') return true;
                    return other.downloadSpeed() >= STALL_RECOVERY_MIN_WIRE_SPEED_BPS ||
                        !Array.isArray(other.requests) || other.requests.length === 0;
                });
                if (!hasAlternative) continue;

                try {
                    wire.cancel(index, request.offset, request.length);
                    cancels += 1;
                } catch (_) {}
                tracked.delete(key);
            }

            for (const key of tracked.keys()) {
                if (!presentKeys.has(key)) tracked.delete(key);
            }
            if (tracked.size === 0) sess.stalledRequests.delete(wire);
        }

        if (cancels > 0) sess.lastStallRecoveryAt = now;
        return cancels;
    }

    createReadStream(torrent, file, opts = {}) {
        const start = Math.max(0, Number(opts.start) || 0);
        const hash = this.canonicalHash(torrent?.infoHash);
        const sess = hash ? this.sessions.get(hash) : null;
        const reader = {
            id: `${Date.now().toString(36)}-${(++this._readerSeq).toString(36)}`,
            cursorByte: start,
            lastCursorPiece: undefined,
            released: false,
            slideTimer: null,
            wireListener: null
        };

        if (sess) {
            if (!(sess.readers instanceof Map)) sess.readers = new Map();
            sess.readers.set(reader.id, reader);
            sess.activeReaders = sess.readers.size;
            sess.lastActive = Date.now();
            if (sess.streamStartedAt === undefined) sess.streamStartedAt = Date.now();
        }

        this.applySlidingWindow(torrent, file, start, opts, reader);

        let stream = file.createReadStream(opts);
        if (STREAM_MERGE_BYTES > 0 && opts.mergeChunks !== false) {
            stream = Readable.from(_mergeChunks(stream, STREAM_MERGE_BYTES), { highWaterMark: 4 });
        }

        if (sess) {
            reader.slideTimer = setInterval(() => {
                this.applySlidingWindow(torrent, file, undefined, opts, reader);
            }, SLIDE_INTERVAL_MS);
            reader.slideTimer.unref?.();

            reader.wireListener = () => {
                this.applySlidingWindow(torrent, file, undefined, opts, reader);
            };
            torrent.on('wire', reader.wireListener);

            const releaseReader = () => {
                if (reader.released) return;
                reader.released = true;

                clearInterval(reader.slideTimer);
                reader.slideTimer = null;
                if (reader.wireListener) {
                    torrent.removeListener('wire', reader.wireListener);
                    reader.wireListener = null;
                }

                if (sess.readers instanceof Map) {
                    sess.readers.delete(reader.id);
                    sess.activeReaders = sess.readers.size;
                } else if (sess.activeReaders > 0) {
                    sess.activeReaders -= 1;
                }
                sess.lastActive = Date.now();

                // Rebuild the selection set for the readers that remain so a
                // finished range request cannot leave another reader stranded.
                if (sess.readers instanceof Map && sess.readers.size > 0) {
                    this.applySlidingWindow(torrent, file, undefined, opts);
                }
            };
            stream.once('close', releaseReader);
            stream.once('end', releaseReader);
            stream.once('error', releaseReader);

            stream.on('data', (chunk) => {
                sess.lastActive = Date.now();
                reader.cursorByte += chunk ? chunk.length : 0;
                if (sess.firstByteAt === undefined) {
                    sess.firstByteAt = Date.now();
                    if (sess.streamStartedAt !== undefined) {
                        sess.firstByteMs = sess.firstByteAt - sess.streamStartedAt;
                    }
                }
                sess.bytesServed = (sess.bytesServed || 0) + (chunk ? chunk.length : 0);
            });
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

    /**
     * T0.6: periodically re-add known-good cached peers to live sessions whose
     * swarm is thinning, so discovery does not depend solely on fresh announce
     * rounds (stremio peer_search re-queries its sources on a cadence).
     */
    _reinjectCachedPeers(minPeers = 4) {
        for (const [hash, sess] of this.sessions.entries()) {
            const torrent = sess.torrent;
            if (!torrent || typeof torrent.addPeer !== 'function') continue;
            if ((torrent.numPeers || 0) >= minPeers) continue;
            const connected = new Set((torrent.wires || [])
                .filter(w => w.remoteAddress && w.remotePort)
                .map(w => `${w.remoteAddress}:${w.remotePort}`));
            for (const peer of this.loadCachedPeers(hash)) {
                if (connected.has(peer)) continue;
                try { torrent.addPeer(peer); } catch (_) {}
            }
        }
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

            const source_stats = {};
            if (sess.sourceStats instanceof Map) {
                for (const [key, stats] of sess.sourceStats.entries()) {
                    source_stats[key] = { found: stats.found, uniq: stats.uniq.size };
                }
            }

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
                swarm_paused: Boolean(sess.swarmPaused),
                source_stats: source_stats,
                hint_stats: sess.hintStats ? {
                    seeks: sess.hintStats.seeks,
                    hits: sess.hintStats.hits,
                    hit_rate: sess.hintStats.seeks > 0 ? Math.round(sess.hintStats.hits / sess.hintStats.seeks * 100) : null
                } : null,
                duration_seconds: sess.duration_seconds || null,
                avg_bitrate_bps: sess.avg_bitrate_bps || null,
                readers: sess.readers instanceof Map ? sess.readers.size : (sess.activeReaders || 0),
                metadata_ms: sess.metadataMs ?? null,
                first_byte_ms: sess.firstByteMs ?? null,
                bytes_served: sess.bytesServed || 0,
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

export { TorrentEngine };
export default process.env.EVO_ENGINE_NO_DEFAULT === '1' ? null : new TorrentEngine();
