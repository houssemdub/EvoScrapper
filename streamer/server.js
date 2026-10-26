/**
 * streamer/server.js — Micro-Daemon HTTP Streaming Server for EvoScrapper (ESM)
 * Integrates WebTorrent sliding window piece engine, RFC 7233 Range Streaming,
 * and graceful client disconnection handling.
 */

import http from 'node:http';
import { URL } from 'node:url';
import path from 'node:path';
import events from 'node:events';
import engine from './torrent_engine.js';

events.defaultMaxListeners = 100;

const PORT = process.env.STREAM_PORT || 8889;

function getMime(filename) {
    const ext = path.extname(filename || '').toLowerCase();
    switch (ext) {
        case '.mp4': return 'video/mp4';
        case '.mkv': return 'video/x-matroska';
        case '.webm': return 'video/webm';
        case '.avi': return 'video/x-msvideo';
        case '.mov': return 'video/quicktime';
        case '.ts': return 'video/mp2t';
        case '.m3u8': return 'application/vnd.apple.mpegurl';
        case '.vtt': return 'text/vtt';
        case '.srt': return 'text/plain';
        default: return 'application/octet-stream';
    }
}

const VIDEO_EXT = new Set(['.mp4', '.mkv', '.webm', '.avi', '.mov', '.ts', '.m4v', '.wmv']);

function cleanNameForMatching(filename) {
    if (!filename) return '';
    return filename
        .replace(/\b(?:480p|720p|1080p|1440p|2160p|4k|uhd|fhd|hd)\b/gi, ' ')
        .replace(/\b(?:x264|x265|h264|h265|hevc|av1|xvid|divx|10bit|8bit)\b/gi, ' ')
        .replace(/\b(?:aac|ac3|dts|eac3|flac|mp3|opus|truehd|atmos)\b/gi, ' ')
        .replace(/[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]/g, ' ')
        .replace(/\b(?:19|20)\d{2}\b/g, ' ')
        .replace(/\b(?:repack|proper|internal|bluray|bdrip|webrip|web-dl|webdl|hdtv)\b/gi, ' ');
}

function isBonusOrNonEpisode(filepath, requestedSeason = null) {
    const norm = (filepath || '').replace(/\\/g, '/').toLowerCase();
    const basename = path.basename(norm);

    if (/\b(sample|trailer|preview|extras?|bonus|featurette|promo)\b/i.test(basename)) return true;
    if (/[\\/](?:sample|trailer|preview|extras?|bonus|featurette|promo)[\\/]/i.test(norm)) return true;

    // Reject themes / music / OP / ED
    if (/\b(op\s*\d+|ed\s*\d+|ncop\s*\d*|nced\s*\d*|opening\s*\d*|ending\s*\d*|creditless)\b/i.test(basename)) return true;
    if (/[\\/](?:op\s*and\s*ed|openings?|endings?|ost|soundtrack|music)[\\/]/i.test(norm)) return true;

    // Movies: only reject if requestedSeason is not 0 / Movie
    const isMovie = /[\\/](?:movies?|films?)[\\/]/i.test(norm) || /\b(?:movie|film)\s*\d+\b/i.test(basename);
    if (isMovie && requestedSeason !== 0 && requestedSeason !== 'movie') return true;

    // OVAs / Specials: only reject if requestedSeason is not 0 / OVA / Special
    const isOva = /[\\/](?:specials?|ova|oad)[\\/]/i.test(norm) ||
                  /[\[\(](?:special|sp|ova|oad)[\]\)]/i.test(basename) ||
                  /\b(?:ova|oad|sp)\s*0*\d+\b/i.test(basename) ||
                  /\bspecial\s+0*\d+\b/i.test(basename);
    if (isOva && requestedSeason !== 0 && requestedSeason !== 'ova') return true;

    return false;
}

function extractSeasonFromPath(filepath) {
    const norm = (filepath || '').replace(/\\/g, '/');
    const parts = norm.split('/');
    // Check directory components from immediate parent backwards
    for (let i = parts.length - 2; i >= 0; i--) {
        const p = parts[i];
        const m = p.match(/\b(?:season|series|staffel|s)\s*0*(\d+)\b/i);
        if (m) return parseInt(m[1], 10);
        if (/\b(?:specials?|ova|oad)\b/i.test(p)) return 0;
    }
    // Check filename
    const filename = parts[parts.length - 1];
    const fm = filename.match(/\b[sS]0*(\d+)[eE]\d+\b|\b0*(\d+)x\d+\b/);
    if (fm) return parseInt(fm[1] || fm[2], 10);
    const sm = filename.match(/\b(?:season|s)\s*0*(\d+)\b/i);
    if (sm) return parseInt(sm[1], 10);
    if (/\b(?:special|sp|ova|oad)\s*0*\d*\b/i.test(filename)) return 0;
    return null;
}

function scoreFileForEpisode(file, targetSeason, targetEp, seasonFilesSorted) {
    const filepath = file.path || file.name || '';
    const normPath = filepath.replace(/\\/g, '/');
    const filename = path.basename(normPath);
    const parsedName = path.parse(filename).name;
    const clean = cleanNameForMatching(parsedName);

    const fileSeason = extractSeasonFromPath(filepath);

    // If season is requested and file has a known season that differs -> reject
    if (targetSeason !== null && fileSeason !== null && targetSeason !== fileSeason) {
        return -10000;
    }

    let score = 0;

    // Direct Season Match
    if (targetSeason !== null && fileSeason === targetSeason) {
        score += 300;
    }

    // 1. Check exact standard SxxExx or 1x01
    if (targetSeason !== null) {
        const sPattern = new RegExp(`\\b(?:s0*${targetSeason}[ ._-]*e0*${targetEp}|0*${targetSeason}x0*${targetEp})\\b`, 'i');
        if (sPattern.test(filename) || sPattern.test(normPath)) {
            score += 1000;
        }
    }

    // 2. Check explicit Ep / Episode prefix
    const epPrefixPattern = new RegExp(`\\b(?:ep|episode|e)[ ._-]*0*${targetEp}\\b`, 'i');
    if (epPrefixPattern.test(filename)) {
        score += 500;
    }

    // 3. Check standalone episode number in cleaned filename
    // e.g. 'Fairy Tail - 001 - The Fairy Tail'
    const epPadded2 = targetEp < 10 ? `0${targetEp}` : `${targetEp}`;
    const epPadded3 = targetEp < 10 ? `00${targetEp}` : (targetEp < 100 ? `0${targetEp}` : `${targetEp}`);
    const standaloneRegex = new RegExp(`(?:^|[ \\-_.\\[\\(])(?:0*${targetEp}|${epPadded2}|${epPadded3})(?:[ \\-_.\\]\\)]|$)`, 'i');

    if (standaloneRegex.test(clean)) {
        score += 400;
    }

    // 4. Sequential index in season folder:
    // If files are grouped by season, does this file correspond to the ep-th file in that season?
    if (seasonFilesSorted && seasonFilesSorted.length > 0) {
        const idxInSeason = seasonFilesSorted.findIndex(f => (f.path || f.name) === (file.path || file.name));
        if (idxInSeason !== -1 && idxInSeason === (targetEp - 1)) {
            score += 350;
        }
    }

    return score;
}

function pickVideoFile(files, requestedIdx = null, season = null, episode = null) {
    if (!files || files.length === 0) return null;

    // 1. Explicit valid index requested:
    // If an exact non-zero index was specified (e.g. pre-resolved by Torrentio like fileIdx 39 or 438),
    // directly return the requested file if valid and not a bonus clip.
    const numIdx = (requestedIdx !== null && requestedIdx !== undefined && !isNaN(requestedIdx)) ? parseInt(requestedIdx, 10) : null;
    if (numIdx !== null && numIdx > 0 && numIdx < files.length) {
        const direct = files[numIdx];
        if (direct && VIDEO_EXT.has(path.extname(direct.name || direct.path || '').toLowerCase()) && !isBonusOrNonEpisode(direct.path || direct.name, season)) {
            return direct;
        }
    }

    const videoFiles = files.filter(f => VIDEO_EXT.has(path.extname(f.name || f.path || '').toLowerCase()));
    const validFiles = videoFiles.filter(f => !isBonusOrNonEpisode(f.path || f.name, season));
    const pool = validFiles.length > 0 ? validFiles : (videoFiles.length > 0 ? videoFiles : files);
    if (pool.length === 1) return pool[0];

    // 2. Episode / Season matching (TV Series & Anime) when file_idx was 0 or omitted
    if (episode !== null && episode !== undefined && !isNaN(episode)) {
        const epNum = parseInt(episode, 10);
        const sNum = (season !== null && season !== undefined && !isNaN(season)) ? parseInt(season, 10) : null;

        // Group valid files by season
        const seasonMap = new Map();
        for (const f of pool) {
            const sn = extractSeasonFromPath(f.path || f.name);
            if (sn !== null) {
                if (!seasonMap.has(sn)) seasonMap.set(sn, []);
                seasonMap.get(sn).push(f);
            }
        }
        for (const [sKey, fList] of seasonMap.entries()) {
            fList.sort((a, b) => (a.name || a.path || '').localeCompare(b.name || b.path || '', undefined, { numeric: true, sensitivity: 'base' }));
        }

        const sFiles = (sNum !== null && seasonMap.has(sNum)) ? seasonMap.get(sNum) : null;

        let best = null;
        let bestScore = -1;

        for (const f of pool) {
            const sc = scoreFileForEpisode(f, sNum, epNum, sFiles);
            if (sc > bestScore) {
                bestScore = sc;
                best = f;
            }
        }

        if (best && bestScore > 0) {
            return best;
        }

        // Natural sort fallback within season if season found
        if (sFiles && sFiles.length > 0) {
            if (epNum >= 1 && epNum <= sFiles.length) {
                return sFiles[epNum - 1];
            }
        }
    }

    // 3. Fallback to requested index if present
    if (numIdx !== null && numIdx >= 0 && numIdx < files.length) {
        return files[numIdx];
    }

    // 4. Movie default: largest non-sample video file
    return pool.slice().sort((a, b) => (b.length || 0) - (a.length || 0))[0];
}

const server = http.createServer(async (req, res) => {
    // Enable CORS for web UI access
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, HEAD, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Range, Content-Type, Authorization');

    if (req.method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
    }

    const parsedUrl = new URL(req.url, `http://localhost:${PORT}`);
    const pathname = parsedUrl.pathname;
    const query = parsedUrl.searchParams;

    // ── Health Check ───────────────────────────────────────────────────────────
    if (pathname === '/health') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ status: 'ok', engine: 'webtorrent-v3', port: PORT }));
        return;
    }

    // ── Status & Swarm Metrics ─────────────────────────────────────────────────
    if (pathname === '/status') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(engine.getStatus()));
        return;
    }

    // ── List Torrent Files ─────────────────────────────────────────────────────
    if (pathname === '/files') {
        const infoHash = query.get('info_hash') || query.get('hash');
        const magnet = query.get('magnet');

        if (!infoHash && !magnet) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Missing info_hash or magnet parameter' }));
            return;
        }

        if (infoHash && infoHash.startsWith('cdn_')) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Web CDN is not a torrent' }));
            return;
        }

        try {
            const torrent = await engine.addTorrent(infoHash, magnet);
            const files = torrent.files.map((f, i) => ({
                idx: i,
                name: f.name,
                path: f.path,
                length: f.length
            }));
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ info_hash: torrent.infoHash, name: torrent.name, files }));
        } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: err.message }));
        }
        return;
    }

    // ── Pre-Warm Torrent Swarm ─────────────────────────────────────────────────
    if (pathname === '/warm') {
        const infoHash = query.get('info_hash') || query.get('hash');
        const magnet = query.get('magnet');
        const requestedIdx = query.has('file_idx') ? parseInt(query.get('file_idx'), 10) : null;
        const season = query.has('season') ? parseInt(query.get('season'), 10) : null;
        const episode = query.has('episode') ? parseInt(query.get('episode'), 10) : null;

        if (!infoHash && !magnet) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Missing info_hash or magnet' }));
            return;
        }

        if (infoHash && infoHash.startsWith('cdn_')) {
            res.writeHead(400, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Web CDN is not a torrent' }));
            return;
        }

        try {
            const torrent = await engine.addTorrent(infoHash, magnet);
            const targetFile = pickVideoFile(torrent.files, requestedIdx, season, episode);
            if (targetFile) {
                engine.applySlidingWindow(torrent, targetFile, 0);
            }
            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({
                status: 'warmed',
                info_hash: torrent.infoHash,
                file: targetFile ? targetFile.name : null,
                file_idx: targetFile ? torrent.files.indexOf(targetFile) : null,
                file_path: targetFile ? targetFile.path : null,
                peers: torrent.numPeers
            }));
        } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: err.message }));
        }
        return;
    }

    // ── HTTP Range Streaming ───────────────────────────────────────────────────
    if (pathname === '/stream') {
        const infoHash = query.get('info_hash') || query.get('hash');
        const magnet = query.get('magnet');
        const requestedIdx = query.has('file_idx') ? parseInt(query.get('file_idx'), 10) : null;
        const season = query.has('season') ? parseInt(query.get('season'), 10) : null;
        const episode = query.has('episode') ? parseInt(query.get('episode'), 10) : null;

        if (!infoHash && !magnet) {
            res.writeHead(400, { 'Content-Type': 'text/plain' });
            res.end('Missing info_hash or magnet parameter');
            return;
        }

        if (infoHash && infoHash.startsWith('cdn_')) {
            res.writeHead(400, { 'Content-Type': 'text/plain' });
            res.end('Web CDN is not a torrent');
            return;
        }

        try {
            const torrent = await engine.addTorrent(infoHash, magnet);
            engine.cleanupOtherSessions(torrent.infoHash);
            const targetFile = pickVideoFile(torrent.files, requestedIdx, season, episode);

            if (!targetFile) {
                res.writeHead(404, { 'Content-Type': 'text/plain' });
                res.end('No playable media file located in torrent');
                return;
            }

            const total = targetFile.length;
            const mime = getMime(targetFile.name);
            const range = req.headers.range;
            const fileIdx = torrent.files.indexOf(targetFile);
            const evoHeaders = {
                'X-EvoStream-File': encodeURIComponent(targetFile.name || ''),
                'X-EvoStream-Path': encodeURIComponent(targetFile.path || ''),
                'X-EvoStream-Idx': String(fileIdx >= 0 ? fileIdx : 0),
            };

            if (range) {
                const parts = range.replace(/bytes=/, '').split('-');
                const start = parseInt(parts[0], 10);
                const end = parts[1] ? parseInt(parts[1], 10) : total - 1;
                const chunksize = (end - start) + 1;

                res.writeHead(206, {
                    'Content-Range': `bytes ${start}-${end}/${total}`,
                    'Accept-Ranges': 'bytes',
                    'Content-Length': chunksize,
                    'Content-Type': mime,
                    ...evoHeaders,
                });

                const stream = engine.createReadStream(torrent, targetFile, { start, end });
                stream.on('error', (err) => {
                    if (isHarmlessCloseError(err)) return;
                    console.error('[StreamServer] ReadStream range error:', err.message);
                });
                stream.pipe(res);

                req.on('close', () => {
                    try { stream.destroy(); } catch (_) {}
                });
            } else {
                res.writeHead(200, {
                    'Content-Length': total,
                    'Accept-Ranges': 'bytes',
                    'Content-Type': mime,
                    ...evoHeaders,
                });

                const stream = engine.createReadStream(torrent, targetFile);
                stream.on('error', (err) => {
                    if (isHarmlessCloseError(err)) return;
                    console.error('[StreamServer] ReadStream error:', err.message);
                });
                stream.pipe(res);

                req.on('close', () => {
                    try { stream.destroy(); } catch (_) {}
                });
            }
        } catch (err) {
            console.error('[StreamServer] Streaming error:', err.message);
            if (!res.headersSent) {
                res.writeHead(500, { 'Content-Type': 'text/plain' });
                res.end(`Streaming Error: ${err.message}`);
            }
        }
        return;
    }

    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
});

function isHarmlessCloseError(err) {
    if (!err) return false;
    const msg = String(err.message || '').toLowerCase();
    const code = String(err.code || '');
    return code === 'PREMATURE_CLOSE' ||
           code === 'ERR_STREAM_PREMATURE_CLOSE' ||
           msg.includes('closed') ||
           msg.includes('close called') ||
           msg.includes('user-initiated abort') ||
           msg.includes('abort');
}

process.on('uncaughtException', (err) => {
    if (isHarmlessCloseError(err)) return;
    console.error('[StreamServer] Process uncaught exception:', err.message);
});

process.on('unhandledRejection', (reason) => {
    if (isHarmlessCloseError(reason)) return;
    console.error('[StreamServer] Process unhandled rejection:', reason);
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`[StreamServer] WebTorrent micro-daemon listening on http://127.0.0.1:${PORT}`);
});
