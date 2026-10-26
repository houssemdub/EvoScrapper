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
                lowLatencyMode: true,
                backBufferLength: 90
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
                    videoEl.play().catch(() => {});
                });
            } catch (err) {
                console.warn('[P2PPlayer] HLS attach failed, falling back to direct src:', err);
                videoEl.src = streamUrl;
                videoEl.load();
                videoEl.play().catch(() => {});
            }
        } else {
            // Direct Native HTTP Stream (Transmuxed MP4 or Byte-Range 206)
            videoEl.pause();
            videoEl.src = streamUrl;
            videoEl.load();
            videoEl.play().catch(() => {});
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
}

window.evoP2PPlayer = new EvoP2PPlayerManager();
