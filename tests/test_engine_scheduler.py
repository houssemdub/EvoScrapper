import os
import shutil
import subprocess
import textwrap

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js binary not found on system")


def run_node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "--input-type=module"],
        input=textwrap.dedent(script),
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
    )


def assert_ok(result: subprocess.CompletedProcess):
    assert result.returncode == 0, (
        f"Node script failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_reader_release_is_idempotent_across_end_close_and_error():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        const stream = engine.createReadStream(torrent, file, { start: 0 });
        check(sess.activeReaders === 1, `expected 1 active reader, got ${sess.activeReaders}`);
        check(sess.readers.size === 1, `expected 1 tracked reader, got ${sess.readers.size}`);

        stream.emit('end');
        stream.emit('close');
        stream.emit('error', new Error('late failure'));

        check(sess.activeReaders === 0, `reader leak after release: ${sess.activeReaders}`);
        check(sess.readers.size === 0, `tracked reader leak after release: ${sess.readers.size}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_concurrent_readers_keep_independent_cursors_and_windows():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        const far = engine.createReadStream(torrent, file, { start: 500 * 1024 * 1024 });
        const near = engine.createReadStream(torrent, file, { start: 50 * 1024 * 1024 });
        check(sess.activeReaders === 2, `expected 2 active readers, got ${sess.activeReaders}`);

        const readers = Array.from(sess.readers.values());
        const farReader = readers.find(reader => reader.cursorByte === 500 * 1024 * 1024);
        const nearReader = readers.find(reader => reader.cursorByte === 50 * 1024 * 1024);
        check(farReader && nearReader, `missing reader state: ${JSON.stringify(readers.map(r => r.cursorByte))}`);

        calls.select.length = 0;
        engine.applySlidingWindow(torrent, file, undefined, {}, far);

        const urgent = calls.select.filter(call => call.priority === 3);
        const farUrgent = urgent.some(call => call.start === 500 && call.end > call.start);
        const nearUrgent = urgent.some(call => call.start === 50 && call.end > call.start);
        check(farUrgent, `missing priority-3 window for far reader: ${JSON.stringify(calls.select)}`);
        check(nearUrgent, `missing priority-3 window for near reader: ${JSON.stringify(calls.select)}`);

        const cursors = Array.from(sess.readers.values()).map(reader => reader.cursorPiece);
        check(cursors.includes(500) && cursors.includes(50), `bad cursors: ${cursors}`);

        far.emit('data', Buffer.alloc(4096));
        check(farReader.cursorByte === 500 * 1024 * 1024 + 4096, `far cursor did not advance: ${farReader.cursorByte}`);
        check(nearReader.cursorByte === 50 * 1024 * 1024, `near cursor was polluted: ${nearReader.cursorByte}`);

        far.emit('end');
        far.emit('close');
        check(sess.activeReaders === 1, `expected 1 reader after release, got ${sess.activeReaders}`);
        check(sess.readers.size === 1, `expected 1 tracked reader after release, got ${sess.readers.size}`);

        near.emit('end');
        check(sess.activeReaders === 0, `expected 0 readers, got ${sess.activeReaders}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_priority_tiers_do_not_collapse_in_webtorrent_selections():
    result = run_node(
        """
        import {
            makeEngine, makeTorrent, makeFile, installSession,
            mergeSelections, selectionList, check
        } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        installSession(engine, torrent);

        engine.applySlidingWindow(torrent, file, 0, { avgBitrateBps: 8000000 });

        const merged = selectionList(mergeSelections(calls.select));
        const priorities = new Set(merged.map(item => item.priority));
        check(priorities.has(3), `missing priority 3: ${JSON.stringify(merged)}`);
        check(priorities.has(2), `missing priority 2 (tiers collapsed): ${JSON.stringify(merged)}`);

        const urgent = merged.find(item => item.priority === 3 && item.start === 0);
        const buffer = merged.find(item => item.priority === 2);
        check(urgent, `missing urgent range: ${JSON.stringify(merged)}`);
        check(buffer, `missing buffer range: ${JSON.stringify(merged)}`);
        check(buffer.start > urgent.end + 1,
            `priority tiers are adjacent and would merge: urgent=${JSON.stringify(urgent)} buffer=${JSON.stringify(buffer)}`);

        const urgentOnly = merged.filter(item => item.priority === 3 && item.start === 0)[0];
        check(urgentOnly.end <= 48, `urgent tier is unbounded: ${JSON.stringify(urgentOnly)}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_bitrate_and_buffer_size_scale_priority_two_window():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        function bufferEnd(bitrate, bufferMb) {
            const engine = makeEngine();
            const { torrent, calls } = makeTorrent();
            const file = makeFile();
            installSession(engine, torrent);
            engine.applySlidingWindow(torrent, file, 100 * 1024 * 1024, {
                avgBitrateBps: bitrate,
                bufferMb
            });
            const buffer = calls.select.filter(call => call.priority === 2).pop();
            return buffer ? buffer.end : 0;
        }

        const low = bufferEnd(2000000, 200);
        const high = bufferEnd(20000000, 200);
        const small = bufferEnd(8000000, 50);
        const large = bufferEnd(8000000, 800);

        check(high > low, `bitrate did not scale buffer: low=${low} high=${high}`);
        check(large > small, `bufferMb did not scale buffer: small=${small} large=${large}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_starvation_contracts_priority_two_window():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent, { healthState: 'healthy' });

        engine.applySlidingWindow(torrent, file, 0, { avgBitrateBps: 8000000 });
        const healthyEnd = calls.select.filter(call => call.priority === 2).pop().end;

        sess.healthState = 'starved';
        torrent.bitfield = { get: () => false };
        torrent.downloadSpeed = 0;
        calls.select.length = 0;
        engine.applySlidingWindow(torrent, file, 0, { avgBitrateBps: 8000000 });
        const starvedEnd = calls.select.filter(call => call.priority === 2).pop().end;

        check(starvedEnd < healthyEnd,
            `starvation did not contract buffer: healthy=${healthyEnd} starved=${starvedEnd}`);
        check(starvedEnd > 0, 'starved buffer window disappeared entirely');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_backward_seek_retains_tail_and_records_seek():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        const stream = engine.createReadStream(torrent, file, { start: 50 * 1024 * 1024 });
        const reader = Array.from(sess.readers.values())[0];
        check(reader, 'reader was not registered');
        check(reader.lastCursorPiece === 50, `expected cursor piece 50, got ${reader.lastCursorPiece}`);

        calls.select.length = 0;
        reader.cursorByte = 20 * 1024 * 1024;
        engine.applySlidingWindow(torrent, file, undefined, {}, reader);

        check(reader.cursorPiece === 20, `cursor did not move backward: ${reader.cursorPiece}`);
        check(reader.backwardSeeks === 1, `backward seek was not counted: ${reader.backwardSeeks}`);

        const urgent = calls.select.find(call => call.priority === 3 && call.start === 20);
        const tail = calls.select.find(call => call.priority === 1 && call.end === 18);
        check(urgent, `missing backward urgent window: ${JSON.stringify(calls.select)}`);
        check(tail, `missing retention tail before cursor: ${JSON.stringify(calls.select)}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_stale_critical_flags_outside_urgent_window_are_cleared():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent } = makeTorrent();
        const file = makeFile();
        installSession(engine, torrent);

        torrent._critical[3] = true;
        torrent._critical[5] = true;
        torrent._critical[2000] = true;
        torrent.bitfield = { get: (index) => index === 5 };

        engine.applySlidingWindow(torrent, file, 0, { avgBitrateBps: 8000000 });

        check(torrent._critical[5] === false, 'verified critical flag was not cleared');
        check(torrent._critical[2000] === false, 'distant stale critical flag was not cleared');
        check(torrent._critical[3] === true, 'near-cursor critical flag was cleared');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_tiny_files_and_offset_files_produce_valid_ranges():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile(0, 1);
        installSession(engine, torrent);

        engine.applySlidingWindow(torrent, file, 0, { avgBitrateBps: 8000000 });
        check(calls.select.length > 0, 'no selections for a single-piece file');
        check(calls.select.every(call => call.start <= call.end), `invalid range: ${JSON.stringify(calls.select)}`);
        check(calls.select.every(call => call.start >= 0 && call.end === 0), `out-of-bounds range: ${JSON.stringify(calls.select)}`);

        const offsetResult = makeTorrent();
        const offsetFile = makeFile(100 * 1024 * 1024, 1);
        installSession(engine, offsetResult.torrent, { torrent: offsetResult.torrent });
        engine.applySlidingWindow(offsetResult.torrent, offsetFile, 0, { avgBitrateBps: 8000000 });
        check(offsetResult.calls.select.length > 0, 'no selections for offset single-piece file');
        check(offsetResult.calls.select.every(call => call.start <= call.end), `invalid offset range: ${JSON.stringify(offsetResult.calls.select)}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_idle_cleanup_waits_for_reader_release():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const removed = [];
        const client = {
            remove(torrent, opts, cb) {
                removed.push({ torrent, opts });
                cb();
            }
        };
        const engine = makeEngine(client);
        const { torrent } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent, { lastActive: Date.now() - 60000 });

        const stream = engine.createReadStream(torrent, file, { start: 0 });
        engine.cleanupIdleSessions(0);
        check(removed.length === 0, 'session was evicted while a reader was still active');

        stream.emit('end');
        stream.emit('close');
        sess.lastActive = Date.now() - 60000;
        engine.cleanupIdleSessions(0);

        check(removed.length === 1, `idle session was not evicted after release: ${removed.length}`);
        check(!engine.sessions.has(torrent.infoHash), 'idle session remained registered');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_stalled_urgent_requests_are_reassigned_without_choking():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const realNow = Date.now;
        let now = realNow();
        Date.now = () => now;

        function wire({ speed, pieces, requests = [], type = 'tcp' }) {
            const cancels = [];
            let chokes = 0;
            return {
                cancels,
                get chokes() { return chokes; },
                type,
                destroyed: false,
                peerChoking: false,
                requests,
                downloadSpeed: () => speed,
                cancel: (index, offset, length) => cancels.push({ index, offset, length }),
                choke: () => { chokes += 1; },
                peerPieces: { get: (index) => pieces.includes(index) }
            };
        }

        function starvedTorrent(wires) {
            const torrent = makeTorrent().torrent;
            torrent.wires = wires;
            torrent.numPeers = wires.length;
            torrent.downloadSpeed = 0;
            torrent.bitfield = { get: () => false };
            return torrent;
        }

        // Slow wire holding an urgent request; one healthy alternative exists.
        {
            const engine = makeEngine();
            const stalled = wire({ speed: 100, pieces: [2], requests: [{ piece: 2, offset: 0, length: 16384 }] });
            const healthy = wire({ speed: 500000, pieces: [2] });
            const torrent = starvedTorrent([stalled, healthy]);
            const file = makeFile();
            installSession(engine, torrent, { healthState: 'starved' });

            const offset = 2 * torrent.pieceLength;
            let health = engine.checkBufferHealth(torrent, file, offset);
            check(health.health_state === 'starved', `expected starved, got ${health.health_state}`);
            check(stalled.cancels.length === 0, 'request was cancelled before the stall threshold');

            now += 9000;
            health = engine.checkBufferHealth(torrent, file, offset);
            check(health.health_state === 'starved', `expected starved, got ${health.health_state}`);
            check(stalled.cancels.length === 1, `expected one cancellation, got ${stalled.cancels.length}`);
            check(stalled.cancels[0].index === 2, `wrong piece cancelled: ${JSON.stringify(stalled.cancels[0])}`);

            engine.checkBufferHealth(torrent, file, offset);
            check(stalled.cancels.length === 1, 'cooldown did not prevent another cancellation');
            check(stalled.chokes === 0 && healthy.chokes === 0, 'choke() must not be used for download recovery');
        }

        // No alternative wire: keep waiting instead of cancelling into the void.
        {
            const engine = makeEngine();
            const stalled = wire({ speed: 100, pieces: [2], requests: [{ piece: 2, offset: 0, length: 16384 }] });
            const torrent = starvedTorrent([stalled]);
            const file = makeFile();
            installSession(engine, torrent, { healthState: 'starved' });

            const offset = 2 * torrent.pieceLength;
            engine.checkBufferHealth(torrent, file, offset);
            now += 9000;
            engine.checkBufferHealth(torrent, file, offset);
            check(stalled.cancels.length === 0, `cancelled without an alternative: ${stalled.cancels.length}`);
        }

        // A wire making progress is left alone.
        {
            const engine = makeEngine();
            const fast = wire({ speed: 200000, pieces: [2], requests: [{ piece: 2, offset: 0, length: 16384 }] });
            const healthy = wire({ speed: 600000, pieces: [2] });
            const torrent = starvedTorrent([fast, healthy]);
            const file = makeFile();
            installSession(engine, torrent, { healthState: 'starved' });

            const offset = 2 * torrent.pieceLength;
            engine.checkBufferHealth(torrent, file, offset);
            now += 9000;
            engine.checkBufferHealth(torrent, file, offset);
            check(fast.cancels.length === 0, `progressing wire was cancelled: ${fast.cancels.length}`);
        }

        // Reassignment is bounded to two urgent requests per recovery window.
        {
            const engine = makeEngine();
            const requests = [2, 3, 4, 5].map(index => ({ piece: index, offset: 0, length: 16384 }));
            const stalled = wire({ speed: 100, pieces: [2, 3, 4, 5], requests });
            const healthyA = wire({ speed: 500000, pieces: [2, 3, 4, 5] });
            const healthyB = wire({ speed: 500000, pieces: [2, 3, 4, 5] });
            const torrent = starvedTorrent([stalled, healthyA, healthyB]);
            const file = makeFile();
            installSession(engine, torrent, { healthState: 'starved' });

            const offset = 2 * torrent.pieceLength;
            engine.checkBufferHealth(torrent, file, offset);
            now += 9000;
            engine.checkBufferHealth(torrent, file, offset);
            check(stalled.cancels.length === 2, `expected bounded 2 cancellations, got ${stalled.cancels.length}`);
        }

        Date.now = realNow;
        process.exit(0);
        """
    )
    assert_ok(result)


def test_session_metadata_derives_bitrate_and_scales_windows():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile(0, 4 * 1024 * 1024 * 1024); // 4 GiB
        const sess = installSession(engine, torrent);

        const derived = engine.setSessionMetadata(torrent.infoHash, {
            durationSeconds: 2400,
            fileLength: file.length
        });
        const expectedBitrate = Math.round(file.length * 8 / 2400);
        check(derived && derived.avg_bitrate_bps === expectedBitrate,
            `derived bitrate wrong: ${derived && derived.avg_bitrate_bps} != ${expectedBitrate}`);
        check(derived.duration_seconds === 2400, `duration not stored: ${derived.duration_seconds}`);
        check(sess.avg_bitrate_bps === expectedBitrate, `session bitrate not updated: ${sess.avg_bitrate_bps}`);
        check(sess.duration_seconds === 2400, `session duration not stored: ${sess.duration_seconds}`);

        // Scheduler must now use the session bitrate, not the 8 Mbps fallback.
        engine.applySlidingWindow(torrent, file, 0, {});
        const pieceLength = torrent.pieceLength;
        const bytesPerSec = expectedBitrate / 8;
        const expectedBuffer = Math.min(128, Math.max(8, Math.ceil(60 * bytesPerSec / pieceLength)));
        const buffer = calls.select.filter(call => call.priority === 2).pop();
        check(buffer, 'no priority-2 buffer tier after metadata update');
        check(buffer.end - buffer.start + 1 === expectedBuffer,
            `buffer tier not scaled by derived bitrate: ${buffer.end - buffer.start + 1} != ${expectedBuffer}`);
        check(buffer.end - buffer.start + 1 > 60, `derived bitrate window did not exceed 8 Mbps baseline: ${buffer.end - buffer.start + 1}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_session_metadata_prefers_explicit_bitrate_and_ignores_invalid_input():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        const explicit = engine.setSessionMetadata(torrent.infoHash, {
            durationSeconds: 1800,
            avgBitrateBps: 8000000,
            fileLength: 4 * 1024 * 1024 * 1024
        });
        check(explicit.avg_bitrate_bps === 8000000,
            `explicit bitrate was overridden by derived value: ${explicit.avg_bitrate_bps}`);
        check(explicit.duration_seconds === 1800, `explicit-call duration missing: ${explicit.duration_seconds}`);

        const before = sess.avg_bitrate_bps;
        const beforeDuration = sess.duration_seconds;
        const rejected = engine.setSessionMetadata(torrent.infoHash, {
            durationSeconds: -5,
            avgBitrateBps: NaN,
            fileLength: -1
        });
        check(rejected.avg_bitrate_bps === before, `invalid input changed bitrate: ${rejected.avg_bitrate_bps}`);
        check(rejected.duration_seconds === beforeDuration, `invalid input changed duration: ${rejected.duration_seconds}`);

        const unknown = engine.setSessionMetadata('b'.repeat(40), { durationSeconds: 60, fileLength: 1000 });
        check(unknown === null, `metadata was stored for an unknown session: ${JSON.stringify(unknown)}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_file_metadata_does_not_clobber_measured_bitrate():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent } = makeTorrent();
        const file = makeFile(0, 4 * 1024 * 1024 * 1024);
        const sess = installSession(engine, torrent);

        engine.setSessionMetadata(torrent.infoHash, { durationSeconds: 2400, fileLength: file.length });
        const expectedBitrate = Math.round(file.length * 8 / 2400);

        const info = await engine.getFileMetadata(torrent, file);
        check(info.avg_bitrate_bps === expectedBitrate,
            `file metadata lost measured bitrate: ${info.avg_bitrate_bps} != ${expectedBitrate}`);
        check(info.duration_seconds === 2400, `file metadata lost duration: ${info.duration_seconds}`);
        check(sess.avg_bitrate_bps === expectedBitrate,
            `getFileMetadata downgraded session bitrate to the 8 Mbps default: ${sess.avg_bitrate_bps}`);

        // First call before any measurement keeps the documented default.
        const freshEngine = makeEngine();
        const freshTorrent = makeTorrent().torrent;
        const freshInfo = await freshEngine.getFileMetadata(freshTorrent, makeFile());
        check(freshInfo.avg_bitrate_bps === 8000000, `default bitrate vanished: ${freshInfo.avg_bitrate_bps}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_server_js_exposes_metadata_and_window_plumbing():
    server_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "server.js"))
    with open(server_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "engine.setSessionMetadata(" in content, "server.js never feeds measured metadata into the engine"
    assert "query.has('duration')" in content, "/warm does not accept a duration parameter"
    assert "query.has('bitrate_bps')" in content, "/warm does not accept a bitrate parameter"
    assert "metadataOnly" in content, "/window does not support metadata-only updates (would reset reader windows)"
    assert "avg_bitrate_bps" in content, "daemon routes do not report the effective session bitrate"


def test_peer_cache_writes_are_debounced_not_synchronous():
    result = run_node(
        """
        import fs from 'node:fs';
        import os from 'node:os';
        import path from 'node:path';

        const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'evo-peers-'));
        process.env.EVO_STREAM_CACHE_DIR = tmp;
        process.env.EVO_PEER_CACHE_FLUSH_MS = '40';
        process.env.EVO_ENGINE_NO_DEFAULT = '1';

        const { TorrentEngine } = await import('./streamer/torrent_engine.js');
        const check = (condition, message) => {
            if (!condition) {
                console.error(message);
                process.exit(1);
            }
        };
        const engine = new TorrentEngine({ client: {}, idleSweep: false });
        const hash = 'a'.repeat(40);
        const peersFile = path.join(tmp, 'peers.json');

        check(!fs.existsSync(peersFile), 'peers.json existed before any save');

        // Simulate a burst of wire events: none of these may touch the disk.
        for (let i = 0; i < 20; i++) {
            engine.saveCachedPeers(hash, [`10.0.0.${i}:5000`]);
        }
        check(!fs.existsSync(peersFile), 'saveCachedPeers wrote to disk synchronously (debounce violated)');

        // In-memory reads must observe pending peers before the flush.
        check(engine.loadCachedPeers(hash).length === 20,
            `in-memory peer view wrong: ${engine.loadCachedPeers(hash).length}`);

        // After the debounce window exactly one write lands with every peer.
        await new Promise(resolve => setTimeout(resolve, 150));
        check(fs.existsSync(peersFile), 'debounced flush never wrote peers.json');
        check(JSON.parse(fs.readFileSync(peersFile, 'utf-8'))[hash].length === 20,
            'flushed peer set is incomplete');

        // A post-flush save re-arms the debounce instead of writing immediately.
        engine.saveCachedPeers(hash, ['10.0.0.99:5000']);
        check(JSON.parse(fs.readFileSync(peersFile, 'utf-8'))[hash].length === 20,
            're-dirty save wrote synchronously');
        await new Promise(resolve => setTimeout(resolve, 150));
        check(JSON.parse(fs.readFileSync(peersFile, 'utf-8'))[hash].length === 21,
            'second debounce window did not persist the new peer');

        // Manual flush forces an immediate write.
        engine.saveCachedPeers(hash, ['10.0.1.5:5000']);
        check(engine.flushPeerCache() === true, 'manual flush reported no write');
        check(JSON.parse(fs.readFileSync(peersFile, 'utf-8'))[hash].length === 22,
            'manual flush lost peers');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_stream_serving_merges_small_piece_chunks():
    result = run_node(
        """
        import fs from 'node:fs';
        import os from 'node:os';
        import path from 'node:path';
        import { Readable } from 'node:stream';

        const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'evo-merge-'));
        process.env.EVO_STREAM_CACHE_DIR = tmp;
        process.env.EVO_ENGINE_NO_DEFAULT = '1';
        process.env.EVO_STREAM_MERGE_BYTES = '262144'; // 16 x 16 KB

        const { makeEngine, makeTorrent, installSession, check } = await import('./tests/node/engine_harness.mjs');

        const CHUNKS = 100;
        const CHUNK_SIZE = 16384;
        const MERGE = 262144;

        function chunkyFile() {
            return {
                offset: 0,
                length: CHUNKS * CHUNK_SIZE,
                createReadStream() {
                    return Readable.from((async function* () {
                        for (let i = 0; i < CHUNKS; i++) yield Buffer.alloc(CHUNK_SIZE, 1);
                    })());
                }
            };
        }

        const engine = makeEngine();
        const { torrent } = makeTorrent();
        const sess = installSession(engine, torrent);

        // Full consumption: 100 x 16 KB must arrive as 6 full batches + a
        // 4-chunk tail, with byte totals and telemetry preserved.
        const served = engine.createReadStream(torrent, chunkyFile(), { start: 0 });
        const chunks = [];
        served.on('data', c => chunks.push(c));
        await new Promise((resolve, reject) => {
            served.on('end', resolve);
            served.on('error', reject);
        });

        check(chunks.length === 7, `expected 7 merged writes, got ${chunks.length}`);
        check(chunks.slice(0, -1).every(c => c.length === MERGE), 'non-final chunks are not full merge batches');
        check(chunks[chunks.length - 1].length === 4 * CHUNK_SIZE,
            `final partial batch wrong: ${chunks[chunks.length - 1].length}`);
        const total = chunks.reduce((n, c) => n + c.length, 0);
        check(total === CHUNKS * CHUNK_SIZE, `byte total drifted: ${total}`);
        check(sess.bytesServed === total, `served-byte telemetry drifted: ${sess.bytesServed}`);
        check(sess.readers.size === 0, 'reader not released after merged stream ended');

        // Aborting the response mid-flight must tear down the piece stream
        // and release the reader.
        const served2 = engine.createReadStream(torrent, chunkyFile(), { start: 0 });
        served2.on('data', () => {});
        served2.destroy();
        await new Promise(resolve => served2.once('close', resolve));
        check(sess.readers.size === 0, 'reader not released after merged stream abort');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_swarm_pause_resume_hysteresis():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        // 120 verified contiguous pieces at 8 Mbps / 1 MB pieces = 120 s ahead.
        torrent.bitfield = { get: (i) => i <= 120 };
        engine.checkBufferHealth(torrent, file, 0);
        check(sess.swarmPaused === true, `deep buffer did not pause swarm: ${sess.swarmPaused}`);

        calls.select.length = 0;
        engine.applySlidingWindow(torrent, file, 0, {});
        check(calls.select.some(c => c.priority === 3), 'paused window lost its urgent tier');
        const prio2 = calls.select.filter(c => c.priority === 2);
        check(prio2.length === 0, `lookahead tier still active while paused: ${JSON.stringify(prio2)}`);

        // Inside the hysteresis band (60-90 s) the swarm must stay paused.
        torrent.bitfield = { get: (i) => i <= 75 };
        engine.checkBufferHealth(torrent, file, 0);
        check(sess.swarmPaused === true, `hysteresis band flapped the pause state: ${sess.swarmPaused}`);

        // Draining below the resume threshold un-pauses.
        torrent.bitfield = { get: () => false };
        torrent.downloadSpeed = 0;
        engine.checkBufferHealth(torrent, file, 0);
        check(sess.swarmPaused === false, `drained buffer did not resume: ${sess.swarmPaused}`);

        calls.select.length = 0;
        engine.applySlidingWindow(torrent, file, 0, {});
        check(calls.select.some(c => c.priority === 2), 'lookahead tier did not return after resume');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_download_shaping_halves_lookahead():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        function bufferCount(emaSpeed) {
            const engine = makeEngine();
            const { torrent, calls } = makeTorrent();
            const file = makeFile();
            const sess = installSession(engine, torrent, { emaSpeed });
            torrent.bitfield = { get: (i) => i <= 80 }; // 80 s ahead: deep but below pause threshold
            engine.checkBufferHealth(torrent, file, 0);
            calls.select.length = 0;
            engine.applySlidingWindow(torrent, file, 0, {});
            const tier = calls.select.filter(c => c.priority === 2).pop();
            return tier ? tier.end - tier.start + 1 : 0;
        }

        const full = bufferCount(0);
        const shaped = bufferCount(4000000); // 4 MB/s EMA vs 1 MB/s playback rate

        check(full > 0, 'baseline lookahead tier missing');
        check(shaped > 0 && shaped < full, `shaping did not shrink lookahead: full=${full} shaped=${shaped}`);
        check(full % shaped === 0 && full / shaped >= 2, `shrink factor too small: ${full}/${shaped}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_stage_seconds_extends_urgent_window():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        installSession(engine, torrent);

        engine.applySlidingWindow(torrent, file, 0, {});
        const baseline = calls.select.filter(c => c.priority === 3 && c.start === 0).pop();
        check(baseline && baseline.end === 20, `baseline urgent window wrong: ${JSON.stringify(baseline)}`);

        calls.select.length = 0;
        engine.applySlidingWindow(torrent, file, 0, { stageSeconds: 120 });
        const staged = calls.select.filter(c => c.priority === 3 && c.start === 0).pop();
        // 120 s at decimal 8 Mbps = 120e6 bytes = ceil(/1 MiB) = 115 pieces.
        check(staged && staged.end === 115, `staged urgent window wrong: ${JSON.stringify(staged)}`);
        check(staged.end <= 191, `staged urgent window unbounded: ${JSON.stringify(staged)}`);
        process.exit(0);
        """
    )
    assert_ok(result)


def test_status_reports_pause_state_and_peer_reinjection():
    result = run_node(
        """
        import fs from 'node:fs';
        import os from 'node:os';
        import path from 'node:path';

        const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'evo-reinject-'));
        process.env.EVO_STREAM_CACHE_DIR = tmp;
        process.env.EVO_ENGINE_NO_DEFAULT = '1';

        const { TorrentEngine } = await import('./streamer/torrent_engine.js');
        const check = (condition, message) => {
            if (!condition) { console.error(message); process.exit(1); }
        };
        const engine = new TorrentEngine({ client: {}, idleSweep: false });
        const hash = 'a'.repeat(40);
        engine.saveCachedPeers(hash, ['1.2.3.4:5000', '5.6.7.8:6000']);

        const added = [];
        const torrent = {
            infoHash: hash,
            numPeers: 1,
            wires: [{ remoteAddress: '1.2.3.4', remotePort: 5000 }],
            addPeer(peer) { added.push(peer); }
        };
        engine.sessions.set(hash, { torrent, lastActive: Date.now(), swarmPaused: true, sourceStats: new Map([['tracker', { found: 3, uniq: new Set(['1.2.3.4:5000']) }]]) });

        engine._reinjectCachedPeers();
        check(added.length === 1 && added[0] === '5.6.7.8:6000',
            `re-injection added wrong peers: ${JSON.stringify(added)}`);

        const status = engine.getStatus();
        const sess = status.sessions[0];
        check(sess.swarm_paused === true, 'status did not expose swarm_paused');
        check(sess.source_stats && sess.source_stats.tracker && sess.source_stats.tracker.found === 3,
            `status did not expose per-source stats: ${JSON.stringify(sess.source_stats)}`);

        // A healthy swarm is left alone (and the first session is now healthy too).
        engine.sessions.get(hash).torrent.numPeers = 10;
        const busy = { infoHash: 'b'.repeat(40), numPeers: 10, wires: [], addPeer(peer) { added.push(peer); } };
        engine.sessions.set('b'.repeat(40), { torrent: busy, lastActive: Date.now() });
        engine._reinjectCachedPeers();
        check(added.length === 1, 're-injection touched a healthy swarm');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_seek_hints_create_low_priority_warm_ranges():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        engine.setSeekHints(torrent.infoHash, [1800, -5, NaN, 1800, 3600]);
        check(JSON.stringify(sess.seekHints) === '[1800,3600]', `hints not sanitized: ${JSON.stringify(sess.seekHints)}`);

        calls.select.length = 0;
        engine.applySlidingWindow(torrent, file, 0, {});
        // 1800 s at decimal 8 Mbps = 1.7166e9 bytes -> piece 1716; span clips to 64.
        const hint1 = calls.select.find(c => c.priority === 1 && c.start === 1652);
        const hint2 = calls.select.find(c => c.priority === 1 && c.start === 3369);
        check(hint1, `missing priority-1 range around hint 1: ${JSON.stringify(calls.select)}`);
        check(hint2, `missing priority-1 range around hint 2: ${JSON.stringify(calls.select)}`);
        check(hint1.end === 1780, `hint span wrong: ${JSON.stringify(hint1)}`);

        // Unknown session is rejected.
        check(engine.setSeekHints('b'.repeat(40), [100]) === null, 'hints stored for unknown session');
        process.exit(0);
        """
    )
    assert_ok(result)


def test_reader_metrics_capture_first_byte_and_served_bytes():
    result = run_node(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent } = makeTorrent();
        const file = makeFile();
        const sess = installSession(engine, torrent);

        const stream = engine.createReadStream(torrent, file, { start: 0 });
        stream.emit('data', Buffer.alloc(1024));
        stream.emit('data', Buffer.alloc(2048));

        check(sess.bytesServed === 3072, `unexpected served bytes: ${sess.bytesServed}`);
        check(typeof sess.firstByteMs === 'number' && sess.firstByteMs >= 0, `missing first-byte metric: ${sess.firstByteMs}`);

        const status = engine.getStatus();
        check(status.sessions.length === 1, 'session missing from status');
        check(status.sessions[0].readers === 1, `status reader count wrong: ${status.sessions[0].readers}`);
        check(status.sessions[0].bytes_served === 3072, `status served bytes wrong: ${status.sessions[0].bytes_served}`);
        process.exit(0);
        """
    )
    assert_ok(result)
