/**
 * torrent_engine.js — Next-Gen WebTorrent Streaming Engine (ESM)
 * Inspired by webtorrent-master (sliding piece windows, critical range prioritization,
 * dynamic peer management, and idle teardown).
 */

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
    'wss://tracker.openwebtorrent.com',
    'wss://tracker.btorrent.xyz',
    'wss://tracker.webtorrent.dev'
];

class TorrentEngine {
    constructor() {
        this.client = new WebTorrent({
            maxConns: 120,
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
        try {
            existing = await this.client.get(hash);
        } catch (_) {}

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
                storeCacheSlots: 100
            };

            let settled = false;
            let torrent = null;
            const timeoutTimer = setTimeout(() => {
                if (!settled && !this.sessions.has(hash)) {
                    settled = true;
                    if (torrent) {
                        try {
                            this.client.remove(torrent, { destroyStore: true }, () => {});
                        } catch (_) {}
                    }
                    reject(new Error(`Swarm metadata timeout: Unable to fetch torrent metadata within 30s for hash ${hash}`));
                }
            }, 30000);

            try {
                torrent = this.client.add(magnet, torrentOpts);
            } catch (err) {
                clearTimeout(timeoutTimer);
                return reject(err);
            }

            const onReady = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timeoutTimer);
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
                    clearTimeout(timeoutTimer);
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

        // Select the active file pieces at base priority 1 without calling torrent.deselect(),
        // preventing cancellation of in-flight piece requests on all connected peers.
        try {
            if (typeof file.select === 'function') file.select(1);
        } catch (_) {}

        const fileStartPiece = Math.floor(file.offset / pieceLength);
        const fileEndPiece = Math.floor((file.offset + file.length - 1) / pieceLength);

        // Container header (EBML / MOOV): First 5 pieces get critical priority (3)
        const headerEnd = Math.min(fileStartPiece + 4, fileEndPiece);
        torrent.select(fileStartPiece, headerEnd, 3);

        // Container index / cues (MKV Cues / seek tables): Last 3 pieces get critical priority (3)
        const indexStart = Math.max(fileStartPiece, fileEndPiece - 2);
        torrent.select(indexStart, fileEndPiece, 3);

        // Sliding forward buffer around current byte offset:
        // - Immediate next 4 pieces: Critical priority 3 (instant frame decoding)
        // - Next 40MB forward buffer: High priority 2 (smooth continuous playback cache)
        const currentPiece = Math.floor((file.offset + byteOffset) / pieceLength);
        if (currentPiece <= fileEndPiece) {
            const immediateEnd = Math.min(fileEndPiece, currentPiece + 3);
            torrent.select(currentPiece, immediateEnd, 3);

            const bufferBytes = 40 * 1024 * 1024;
            const bufferPieces = Math.ceil(bufferBytes / pieceLength);
            const bufferEnd = Math.min(fileEndPiece, currentPiece + bufferPieces);
            if (bufferEnd > immediateEnd) {
                torrent.select(immediateEnd + 1, bufferEnd, 2);
            }
        }
    }

    createReadStream(torrent, file, opts = {}) {
        const start = opts.start || 0;
        this.applySlidingWindow(torrent, file, start);
        const stream = file.createReadStream(opts);
        const hash = this.canonicalHash(torrent.infoHash);
        if (hash) {
            const sess = this.sessions.get(hash);
            if (sess) {
                sess.lastActive = Date.now();
                stream.on('data', () => { sess.lastActive = Date.now(); });
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
                    this.client.remove(sess.torrent, { destroyStore: true }, () => {});
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
            clientDownloadSpeed: (this.client.downloadSpeed / 1024 / 1024).toFixed(2) + ' MB/s',
            clientUploadSpeed: (this.client.uploadSpeed / 1024 / 1024).toFixed(2) + ' MB/s',
            active_torrents: this.sessions.size,
            sessions: active
        };
    }
}

export default new TorrentEngine();
