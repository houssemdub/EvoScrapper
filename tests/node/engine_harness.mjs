// Shared execution harness for torrent_engine scheduler tests.
// Importing this module must not start the default WebTorrent client.
process.env.EVO_ENGINE_NO_DEFAULT = '1';

import events from 'node:events';

const { TorrentEngine } = await import('../../streamer/torrent_engine.js');
const { Selections } = await import('../../streamer/node_modules/webtorrent/lib/selections.js');
const { default: WebTorrent } = await import('../../streamer/node_modules/webtorrent/index.js');

export { TorrentEngine, Selections, WebTorrent };

export class FakeStream extends events.EventEmitter {
    destroy() {
        this.emit('close');
    }
}

export function makeTorrent(overrides = {}) {
    const calls = { select: [], deselect: [], critical: [] };
    const torrent = {
        infoHash: 'a'.repeat(40),
        pieceLength: 1024 * 1024,
        pieces: new Array(4096).fill(null),
        bitfield: { get: () => false },
        downloadSpeed: 0,
        numPeers: 4,
        wires: [],
        _critical: [],
        select(start, end, priority) {
            calls.select.push({ start, end, priority });
        },
        deselect(start, end) {
            calls.deselect.push({ start, end });
        },
        critical(start, end) {
            calls.critical.push({ start, end });
        },
        on() {},
        removeListener() {},
        ...overrides
    };
    return { torrent, calls };
}

export function makeFile(offset = 0, length = 4096 * 1024 * 1024) {
    const streams = [];
    return {
        offset,
        length,
        streams,
        createReadStream() {
            const stream = new FakeStream();
            streams.push(stream);
            return stream;
        }
    };
}

export function makeEngine(client = null) {
    return new TorrentEngine({ client, idleSweep: false });
}

export function installSession(engine, torrent, overrides = {}) {
    const sess = {
        torrent,
        lastActive: Date.now(),
        activeReaders: 0,
        readers: new Map(),
        avg_bitrate_bps: 8000000,
        ...overrides
    };
    engine.sessions.set(torrent.infoHash.toLowerCase(), sess);
    return sess;
}

export function check(condition, message, code = 1) {
    if (!condition) {
        console.error(message);
        process.exit(code);
    }
}

export function priorityRanges(calls, priority) {
    return calls.filter(call => call.priority === priority);
}

export function mergeSelections(calls) {
    const selections = new Selections();
    for (const call of calls) {
        selections.insert({ from: call.start, to: call.end, priority: call.priority });
    }
    return selections;
}

export function selectionList(selections) {
    const result = [];
    for (const item of selections) {
        result.push({ start: item.from, end: item.to, priority: item.priority });
    }
    return result;
}
