/**
 * p2p-player.js — High-Performance Native P2P Streaming Engine for EvoScrapper
 * Integrates WebRTC P2P Media Loader mesh + Hls.js with zero DOM-wrapping clutter.
 * Guarantees 100% black background, ultra-fast video load, and native player HUD sync.
 */

class EvoP2PPlayerManager {
    constructor() {
        this.hls = null;
        this.p2pEngine = null;
        this.p2pBytes = 0;
        this.httpBytes = 0;
        this.peerCount = 0;
    }

    resetMetrics() {
        this.p2pBytes = 0;
        this.httpBytes = 0;
        this.peerCount = 0;
        this.updateHud();
    }

    updateHud() {
        const peersEl = document.getElementById('p2p-peers-count');
        const ratioEl = document.getElementById('p2p-ratio');
        const swarmStat = document.getElementById('player-swarm-stat');
        if (peersEl) {
            peersEl.innerHTML = `${this.peerCount} ${this.peerCount === 1 ? 'Peer' : 'Peers'}`;
        }
        const total = this.p2pBytes + this.httpBytes;
        const ratio = total > 0 ? Math.round((this.p2pBytes / total) * 100) : 0;
        if (ratioEl) {
            if (total > 0) {
                ratioEl.textContent = `P2P Mesh: ${ratio}% (${(this.p2pBytes / 1024 / 1024).toFixed(1)}MB)`;
            } else {
                ratioEl.textContent = 'P2P Ready';
            }
        }
        if (swarmStat) {
            if (this.peerCount > 0) {
                swarmStat.innerHTML = `<i class="fa-solid fa-circle-nodes text-green"></i> WebRTC Mesh Active: ${this.peerCount} peers (${ratio}% P2P)`;
            }
        }
    }

    setupPlayer(videoElementId, streamUrl, isHls = false) {
        this.resetMetrics();
        const videoEl = document.getElementById(videoElementId);
        if (!videoEl) return null;

        // Force rock-solid black background on video viewport
        videoEl.style.backgroundColor = '#000000';
        videoEl.style.display = 'block';

        // Cleanup existing HLS / P2P instances
        if (this.hls) {
            try { this.hls.destroy(); } catch (_) {}
            this.hls = null;
        }
        if (this.p2pEngine) {
            try { this.p2pEngine.destroy(); } catch (_) {}
            this.p2pEngine = null;
        }

        let p2pMeshEnabled = true;
        try {
            const s = JSON.parse(localStorage.getItem('evo_advanced_settings') || '{}');
            if (s.p2p_mesh_enabled === false) p2pMeshEnabled = false;
        } catch (_) {}

        // ── P2P HLS Mesh Mode ───────────────────────────────────────────────────
        const p2pSupported = typeof p2pml !== 'undefined' && p2pml.hlsjs && p2pml.hlsjs.Engine && p2pml.hlsjs.Engine.isSupported();
        const hlsSupported = typeof Hls !== 'undefined' && Hls.isSupported();

        if (isHls && (p2pSupported || hlsSupported)) {
            let hlsConfig = {
                debug: false,
                enableWorker: true,
                lowLatencyMode: false, // VOD from a local source: LL-HLS scheduling hurts more than it helps
                backBufferLength: 90,
                // Deep VOD buffering for a fast local origin (streamer daemon / debrid CDN)
                maxBufferLength: 90,
                maxMaxBufferLength: 600,
                maxBufferSize: 256 * 1000 * 1000,
                maxFragLookUpTolerance: 0.25,
                abrEwmaDefaultEstimate: 5_000_000
            };

            if (p2pMeshEnabled && p2pSupported) {
                try {
                    this.p2pEngine = new p2pml.hlsjs.Engine({
                        segments: {
                            swarmId: streamUrl.split('?')[0],
                            forwardSegmentCount: 15
                        },
                        loader: {
                            trackerAnnounce: [
                                'wss://tracker.openwebtorrent.com',
                                'wss://tracker.btorrent.xyz',
                                'wss://tracker.webtorrent.dev'
                            ],
                            rtcConfig: {
                                iceServers: [
                                    { urls: 'stun:stun.l.google.com:19302' },
                                    { urls: 'stun:global.stun.twilio.com:3478' }
                                ]
                            }
                        }
                    });

                    this.p2pEngine.on(p2pml.core.Events.PieceBytesDownloaded, (method, bytes) => {
                        if (method === 'p2p') {
                            this.p2pBytes += bytes;
                        } else {
                            this.httpBytes += bytes;
                        }
                        this.updateHud();
                    });

                    this.p2pEngine.on(p2pml.core.Events.PeerConnect, () => {
                        this.peerCount++;
                        this.updateHud();
                    });

                    this.p2pEngine.on(p2pml.core.Events.PeerClose, () => {
                        this.peerCount = Math.max(0, this.peerCount - 1);
                        this.updateHud();
                    });

                    hlsConfig = {
                        ...hlsConfig,
                        loader: this.p2pEngine.createLoaderClass()
                    };
                } catch (e) {
                    console.warn('[P2PPlayer] Engine fallback to standard Hls.js:', e);
                }
            }

            try {
                this.hls = new Hls(hlsConfig);
                if (this.p2pEngine) {
                    p2pml.hlsjs.initHlsJsPlayer(this.hls);
                }
                this.hls.loadSource(streamUrl);
                this.hls.attachMedia(videoEl);
                this.hls.on(Hls.Events.MANIFEST_PARSED, () => {
                    this.safePlayWithBufferGate(videoEl);
                });
            } catch (err) {
                console.warn('[P2PPlayer] HLS attach failed, falling back to direct src:', err);
                videoEl.src = streamUrl;
                videoEl.load();
                this.safePlayWithBufferGate(videoEl);
            }
        } else {
            // Direct Native HTTP Stream (Transmuxed MP4 or Byte-Range 206)
            videoEl.pause();
            videoEl.src = streamUrl;
            videoEl.load();
            this.safePlayWithBufferGate(videoEl);
            this.peerCount = 0;
            const ratioEl = document.getElementById('p2p-ratio');
            if (ratioEl) ratioEl.textContent = streamUrl.includes('/transmux') ? 'Live Transmux (Stereo AAC)' : 'Direct Stream (Range 206)';
        }

        return videoEl;
    }

    destroy() {
        if (this.hls) {
            try { this.hls.destroy(); } catch (_) {}
            this.hls = null;
        }
        if (this.p2pEngine) {
            try { this.p2pEngine.destroy(); } catch (_) {}
            this.p2pEngine = null;
        }
        this.resetMetrics();
    }

    safePlayWithBufferGate(videoEl) {
        return safePlayWithBufferGate(videoEl);
    }

    alignTextTracks(videoEl, startOffset = 0, userSubDelay = 0) {
        return alignTextTracks(videoEl, startOffset, userSubDelay);
    }
}

/**
 * Non-blocking startup & post-seek buffer gate:
 * Holds automatic playback until video.buffered has at least 3.0s ahead of currentTime,
 * readyState >= 4 (HAVE_ENOUGH_DATA), or 4000ms safety timeout after canplay.
 * On release, if currentTime is between 0 and 1.5s, briefly resyncs decoder clock.
 */
function safePlayWithBufferGate(videoEl) {
    if (!videoEl) return;
    let gateReleased = false;

    const releaseGate = () => {
        if (gateReleased) return;
        gateReleased = true;
        cleanup();
        try {
            if (videoEl.currentTime > 0 && videoEl.currentTime < 1.5) {
                videoEl.currentTime = videoEl.currentTime;
            }
        } catch (_) {}
        videoEl.play().catch(() => {});
    };

    const checkBuffer = () => {
        if (gateReleased) return;
        if (videoEl.readyState >= 4) {
            releaseGate();
            return;
        }
        try {
            const cur = videoEl.currentTime || 0;
            const b = videoEl.buffered;
            if (b && b.length > 0) {
                for (let i = 0; i < b.length; i++) {
                    if (b.start(i) <= cur + 0.2 && b.end(i) >= cur) {
                        if (b.end(i) - cur >= 3.0) {
                            releaseGate();
                            return;
                        }
                    }
                }
            }
        } catch (_) {}
    };

    let safetyTimeout = null;
    let checkInterval = null;

    const onCanPlay = () => {
        checkBuffer();
        if (!gateReleased && !safetyTimeout) {
            safetyTimeout = setTimeout(() => {
                releaseGate();
            }, 4000);
        }
    };

    const cleanup = () => {
        if (safetyTimeout) {
            clearTimeout(safetyTimeout);
            safetyTimeout = null;
        }
        if (checkInterval) {
            clearInterval(checkInterval);
            checkInterval = null;
        }
        videoEl.removeEventListener('progress', checkBuffer);
        videoEl.removeEventListener('canplay', onCanPlay);
        videoEl.removeEventListener('canplaythrough', releaseGate);
        videoEl.removeEventListener('playing', cleanup);
    };

    videoEl.addEventListener('progress', checkBuffer);
    videoEl.addEventListener('canplay', onCanPlay);
    videoEl.addEventListener('canplaythrough', releaseGate);
    videoEl.addEventListener('playing', cleanup);

    checkInterval = setInterval(checkBuffer, 100);
    checkBuffer();

    setTimeout(() => {
        if (!gateReleased) releaseGate();
    }, 4500);
}

/**
 * Shifts native HTML5 TextTrack VTTCues by server-side start offset and user delay
 * so native player rendering stays sample-accurate both at 0:00 and after seeking.
 */
function alignTextTracks(videoEl, startOffset = 0, userSubDelay = 0) {
    if (!videoEl || !videoEl.textTracks) return;
    const offset = Number(startOffset) || 0;
    const delay = Number(userSubDelay) || 0;
    for (let i = 0; i < videoEl.textTracks.length; i++) {
        const track = videoEl.textTracks[i];
        if (!track || !track.cues) continue;
        for (let j = 0; j < track.cues.length; j++) {
            const cue = track.cues[j];
            if (cue._origStart === undefined) cue._origStart = cue.startTime;
            if (cue._origEnd === undefined) cue._origEnd = cue.endTime;
            cue.startTime = Math.max(0, cue._origStart - offset + delay);
            cue.endTime = Math.max(0, cue._origEnd - offset + delay);
        }
    }
}

if (typeof window !== 'undefined') {
    window.safePlayWithBufferGate = safePlayWithBufferGate;
    window.alignTextTracks = alignTextTracks;
    window.evoP2PPlayer = new EvoP2PPlayerManager();
}
