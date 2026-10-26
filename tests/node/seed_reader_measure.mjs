// Deterministic loopback seed -> reader measurement for the streaming engine.
//
// A seeded file is served from a local WebTorrent client (no DHT, trackers,
// LSD, UPnP, or uTP) and the reader is connected explicitly to the seeder's
// TCP port. Only loopback traffic is involved, so the metrics are repeatable
// and suitable for regression assertions.
//
// Emits one line: EVO_METRICS <json>

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { TorrentEngine, WebTorrent } from './engine_harness.mjs';

const METRICS_PREFIX = 'EVO_METRICS ';
const TIMEOUT_MS = Number(process.env.EVO_MEASURE_TIMEOUT_MS || 60000);
const FILE_BYTES = Number(process.env.EVO_MEASURE_BYTES || 8 * 1024 * 1024);
const CACHE_DIR = process.env.EVO_STREAM_CACHE_DIR;

if (!CACHE_DIR) {
    console.error('EVO_STREAM_CACHE_DIR must point at a disposable directory');
    process.exit(2);
}

function fail(message) {
    throw new Error(message);
}

function withTimeout(promise, ms, label) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
        Promise.resolve(promise).then(
            value => {
                clearTimeout(timer);
                resolve(value);
            },
            err => {
                clearTimeout(timer);
                reject(err);
            }
        );
    });
}

function eventOnce(emitter, event, ms, label) {
    return withTimeout(new Promise((resolve, reject) => {
        const onEvent = (...args) => {
            cleanup();
            resolve(args);
        };
        const onError = (err) => {
            cleanup();
            reject(err);
        };
        function cleanup() {
            emitter.removeListener(event, onEvent);
            emitter.removeListener('error', onError);
        }
        emitter.once(event, onEvent);
        emitter.once('error', onError);
    }), ms, label);
}

function waitFor(predicate, ms, label) {
    const deadline = Date.now() + ms;
    return new Promise((resolve, reject) => {
        const poll = () => {
            if (predicate()) return resolve();
            if (Date.now() >= deadline) return reject(new Error(`${label} timed out after ${ms}ms`));
            setTimeout(poll, 25);
        };
        poll();
    });
}

function createLocalClient() {
    return new WebTorrent({
        dht: false,
        tracker: false,
        lsd: false,
        natUpnp: false,
        natPmp: false,
        utp: false,
        torrentPort: 0,
        maxConns: 20
    });
}

function contiguousVerified(torrent, cursorPiece, maxPieces) {
    const end = Math.min(torrent.pieces.length - 1, cursorPiece + maxPieces - 1);
    let count = 0;
    for (let index = cursorPiece; index <= end; index++) {
        if (!torrent.bitfield.get(index)) break;
        count += 1;
    }
    return count;
}

function lookaheadScanPieces(pieceLength, bitrate) {
    const bytesPerSec = bitrate / 8;
    return Math.max(64, Math.min(4096, Math.ceil((120 * bytesPerSec) / pieceLength)));
}

function destroyClient(client) {
    return new Promise((resolve) => {
        if (!client || client.destroyed) return resolve();
        const timer = setTimeout(resolve, 5000);
        timer.unref?.();
        try {
            client.destroy(() => {
                clearTimeout(timer);
                resolve();
            });
        } catch (_) {
            clearTimeout(timer);
            resolve();
        }
    });
}

const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'evo-measure-'));
const seedDir = path.join(workDir, 'seed');
fs.mkdirSync(seedDir);

const seedPath = path.join(seedDir, 'sample.bin');
const payload = Buffer.allocUnsafe(FILE_BYTES);
for (let index = 0; index < payload.length; index++) {
    payload[index] = (index * 31 + (index >> 8)) & 0xff;
}
fs.writeFileSync(seedPath, payload);

const seeder = createLocalClient();
let readerClient = null;
let engine = null;
let stream = null;

try {
    if (!seeder.listening) {
        await eventOnce(seeder, 'listening', TIMEOUT_MS, 'seeder listening');
    }
    const address = seeder.address();
    if (!address || !address.port) fail('seeder did not expose a TCP port');
    const peerAddr = `127.0.0.1:${address.port}`;

    const seeding = new Promise((resolve, reject) => {
        const torrent = seeder.seed(seedPath, { announce: [] }, resolve);
        torrent.once('error', reject);
    });
    const seedTorrent = await withTimeout(seeding, TIMEOUT_MS, 'seeding');
    if (seedTorrent.length !== FILE_BYTES) {
        fail(`seed length mismatch: ${seedTorrent.length} != ${FILE_BYTES}`);
    }

    readerClient = createLocalClient();
    engine = new TorrentEngine({ client: readerClient, idleSweep: false });

    // Peers must be attached at the `infoHash` event: it fires before peer
    // discovery starts and before `addPeer()` is legal.
    readerClient.on('add', (torrent) => {
        torrent.once('infoHash', () => {
            if (torrent.infoHash === seedTorrent.infoHash) {
                torrent.addPeer(peerAddr);
            }
        });
    });

    const addStartedAt = Date.now();
    const readerTorrent = await withTimeout(
        engine.addTorrent(seedTorrent.infoHash),
        TIMEOUT_MS,
        'metadata'
    );
    const metadataWallMs = Date.now() - addStartedAt;

    const file = readerTorrent.files && readerTorrent.files[0];
    if (!file) fail('reader torrent exposed no files');
    await engine.getFileMetadata(readerTorrent, file);

    const sess = engine.sessions.get(engine.canonicalHash(readerTorrent.infoHash));
    if (!sess) fail('engine did not register a session for the reader');
    if (typeof sess.metadataMs !== 'number') fail(`missing engine metadata metric: ${sess.metadataMs}`);
    if (sess.metadataMs > metadataWallMs + 50) {
        fail(`engine metadata metric ${sess.metadataMs}ms exceeds wall time ${metadataWallMs}ms`);
    }

    const streamStartedAt = Date.now();
    stream = engine.createReadStream(readerTorrent, file, { start: 0 });
    const [firstChunk] = await eventOnce(stream, 'data', TIMEOUT_MS, 'first byte');
    stream.pause();
    const firstByteAt = Date.now();

    if (!firstChunk || firstChunk.length === 0) fail('first data event carried no bytes');
    const cursorPiece = Math.floor(file.offset / readerTorrent.pieceLength);
    if (!readerTorrent.bitfield.get(cursorPiece)) {
        fail('first readable byte arrived before its piece was verified');
    }
    if (typeof sess.firstByteMs !== 'number') fail(`missing engine first-byte metric: ${sess.firstByteMs}`);
    if (Math.abs(sess.firstByteMs - (firstByteAt - streamStartedAt)) > 250) {
        fail(`first-byte metric drift: engine=${sess.firstByteMs} observed=${firstByteAt - streamStartedAt}`);
    }

    await waitFor(
        () => readerTorrent.done || contiguousVerified(readerTorrent, cursorPiece, 4) >= 4,
        15000,
        'verified lookahead'
    );

    const health = engine.checkBufferHealth(readerTorrent, file, 0);
    if (!health) fail('buffer health did not return a reading');

    const bitrate = sess.avg_bitrate_bps || 8000000;
    const scanPieces = lookaheadScanPieces(readerTorrent.pieceLength, bitrate);
    if (health.scan_pieces !== scanPieces) {
        fail(`scan window mismatch: reported=${health.scan_pieces} expected=${scanPieces}`);
    }
    const pieces = contiguousVerified(readerTorrent, cursorPiece, scanPieces);
    if (pieces !== health.verified_pieces_ahead) {
        fail(`verified-piece mismatch: reported=${health.verified_pieces_ahead} actual=${pieces}`);
    }
    const expectedSecondsAhead = Math.round(
        ((pieces * readerTorrent.pieceLength * 8) / bitrate) * 10
    ) / 10;
    if (health.seconds_ahead !== expectedSecondsAhead) {
        fail(`seconds_ahead mismatch: reported=${health.seconds_ahead} expected=${expectedSecondsAhead}`);
    }
    if (pieces < 1) fail('no contiguous verified pieces were observed');
    if (!(health.seconds_ahead > 0)) fail(`seconds_ahead was not positive: ${health.seconds_ahead}`);

    const metrics = {
        metadata_ms: metadataWallMs,
        engine_metadata_ms: sess.metadataMs,
        first_byte_ms: sess.firstByteMs,
        first_byte_after_metadata_ms: firstByteAt - (addStartedAt + metadataWallMs),
        seconds_ahead: health.seconds_ahead,
        contiguous_pieces: pieces,
        scan_pieces: health.scan_pieces,
        piece_length: readerTorrent.pieceLength,
        file_bytes: file.length,
        health_state: health.health_state,
        readers: sess.activeReaders,
        bytes_served: sess.bytesServed || 0
    };

    const status = engine.getStatus();
    const statusSession = status.sessions.find(item => item.info_hash === readerTorrent.infoHash);
    if (!statusSession) fail('session missing from engine status');
    if (statusSession.metadata_ms !== sess.metadataMs) fail('status metadata metric mismatch');
    if (statusSession.first_byte_ms !== sess.firstByteMs) fail('status first-byte metric mismatch');
    metrics.status_bytes_served = statusSession.bytes_served;

    if (metrics.bytes_served < firstChunk.length) {
        fail(`served byte metric is too small: ${metrics.bytes_served}`);
    }

    console.log(METRICS_PREFIX + JSON.stringify(metrics));
} catch (err) {
    console.error(err && err.stack ? err.stack : String(err));
    process.exitCode = 1;
} finally {
    try { stream?.destroy(); } catch (_) {}
    await destroyClient(readerClient);
    await destroyClient(seeder);
    try { fs.rmSync(workDir, { recursive: true, force: true }); } catch (_) {}
    try { fs.rmSync(CACHE_DIR, { recursive: true, force: true }); } catch (_) {}
}

process.exit(process.exitCode || 0);
