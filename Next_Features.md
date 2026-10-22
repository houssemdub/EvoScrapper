# 🚀 EvoScrapper — Next Features & Roadmap

A comprehensive, categorized inventory of upcoming features, enhancements, and superpowers designed to make EvoScrapper the ultimate streaming and media discovery platform — surpassing Netflix, Stremio, and traditional streaming services.

---

## 📑 Table of Contents
1. [In-Browser Player Experience (Netflix & Prime-Grade)](#1-in-browser-player-experience)
2. [Binge-Watching & Series Flow](#2-binge-watching--series-flow)
3. [Watch History, Resume & Cloud Sync](#3-watch-history-resume--cloud-sync)
4. [Subtitles & Audio Superpowers](#4-subtitles--audio-superpowers)
5. [Torrent Swarm & Streaming Engine](#5-torrent-swarm--streaming-engine)
6. [Casting & External Hardware](#6-casting--external-hardware)
7. [Discovery, Recommendations & Metadata](#7-discovery-recommendations--metadata)
8. [Offline Downloads & Library Management](#8-offline-downloads--library-management)
9. [Stremio Addon Ecosystem & Extensibility](#9-stremio-addon-ecosystem--extensibility)
10. [UI Polish, Theming & Accessibility](#10-ui-polish-theming--accessibility)

---

## 1. In-Browser Player Experience

- [x] **Thumbnail Hover Scrubbing (Trickplay / Storyboard Preview)**
  - Hovering anywhere along the timeline seekbar displays a live video thumbnail preview frame of that exact second (via WebVTT sprites or rapid keyframe extraction).
  - Enables instant visual seeking directly to key scenes, dialogue, or action sequences.

- [x] **Picture-in-Picture (PiP) Mode**
  - Dedicated PiP button allowing users to pop the video into a floating always-on-top desktop window while continuing to browse torrents, search catalogs, or use other desktop applications. Auto-PiP on tab change. Shortcut: <kbd>P</kbd>.

- [x] **Ambient Glow Lighting (Ambilight Mode)**
  - Dynamically extracts edge colors of current video frames in real time using a low-overhead Canvas worker and casts a subtle, immersive ambient glow on the player backdrop (similar to YouTube / Philips Hue).

- [x] **Dynamic Range Compression / Night Dialogue Mode**
  - 1-click audio compressor filter (`acompressor` / Web Audio DynamicsCompressorNode + speech gain boost) that boosts quiet whispering dialogue while attenuating loud explosions and gunfire, perfect for late-night viewing without headphone fatigue. Shortcut: <kbd>N</kbd>.

- [x] **Variable Playback Speed with Pitch Preservation**
  - Smooth speed controls: `0.5x`, `0.75x`, `1.0x`, `1.25x`, `1.5x`, `1.75x`, `2.0x` with Web Audio API pitch correction.
  - Quick hotkeys (<kbd>[</kbd> and <kbd>]</kbd>) to speed up or slow down on the fly.

- [x] **Aspect Ratio & Zoom Controls**
  - Fit modes: `Contain (Default)`, `Cover / Crop`, `16:9`, `21:9 Ultrawide`, `4:3 Classic`, and `Stretch`.
  - Removes black bars on ultrawide monitors (21:9 / 32:9) or mobile aspect ratios. Shortcut: <kbd>A</kbd>.

- [x] **Audio Delay & Sync Calibration Slider**
  - Manual micro-adjustment slider ($\pm 5.0\text{s}$ in 50ms increments via Web Audio DelayNode) to correct out-of-sync audio on poorly mastered releases.

- [x] **Keyboard Shortcut Cheat Sheet Modal**
  - Pressing <kbd>?</kbd> pops up a sleek modal showing all available hotkeys (<kbd>Space</kbd>, <kbd>←</kbd>/<kbd>→</kbd>, <kbd>J</kbd>/<kbd>K</kbd>/<kbd>L</kbd>, <kbd>M</kbd>, <kbd>F</kbd>, <kbd>P</kbd>, <kbd>[</kbd>/<kbd>]</kbd>, <kbd>A</kbd>, <kbd>N</kbd>, <kbd>C</kbd>, <kbd>S</kbd>, <kbd>E</kbd>, <kbd>V</kbd>, <kbd>D</kbd>, <kbd>Esc</kbd>).

---

## 2. Binge-Watching & Series Flow

- [x] **Skip Intro & Skip Outro / Credits Button**
  - Detects opening and ending themes and presents a smooth Netflix-style **"Skip Intro"** (+85s) and **"Skip Credits"** (+150s) floating button.

- [x] **Auto-Play Next Episode with Binge Countdown**
  - When reaching the final 25-30 seconds of an episode, displays a countdown card: *"Next Episode starting in 10s... [Play Now] [Cancel]"*.
  - Seamlessly queues and plays the next episode without requiring the user to return to the catalog.

- [x] **Next Episode Pre-Warming (Zero-Second Buffer Gap)**
  - While the current episode is in its final 3 minutes, EvoScrapper automatically initializes the next episode's torrent swarm in the background via `/api/v1/stream/warm`.
  - When the countdown finishes, playback starts instantly with 0ms buffering.

- [x] **In-Player Episode Selector Drawer**
  - Slide-out episode list drawer accessible directly within the active video player, allowing episode switching without closing the player or losing context. Shortcut: <kbd>E</kbd>.

- [x] **Season Auto-Progression**
  - Automatically transitions to Season $N+1$, Episode 1 when the final episode of Season $N$ completes.

---

## 3. Watch History, Resume & Cloud Sync

- [x] **"Continue Watching" Dynamic Shelf**
  - Dedicated front-page row showing recently watched titles with visual progress bars (e.g., `Fight Club — 45m left`).
  - Single-click resume directly at the exact saved second (`currentTime`).

- [x] **Episode Watched Badges & Checkmarks**
  - Visual green checkmarks on episode cards ($\ge 85\%$ watched) to track watched vs. unwatched content.

- [x] **Trakt.tv Two-Way Scrobbling & Sync**
  - Real-time tracking of watch progress, episode completion, and watch state storage across reloads.

- [x] **"My List" / Bookmarks & Favorites Shelf**
  - 1-click bookmarking of movies, series, and anime with dedicated "My List" carousel on Discover page.

---

## 4. Subtitles & Audio Superpowers

- [x] **In-Player Subtitle Search & Downloader**
  - Real-time subtitle search engine queried directly from the player HUD across OpenSubtitles, Gestdown, Subdl, and YIFY Subtitles.
  - Instantly downloads, converts, and applies subtitles with zero page reloads.

- [x] **Dual / Secondary Subtitles (Language Learning Mode)**
  - Renders two subtitle tracks simultaneously: one at the bottom (target language) and one at the top (native language via `#player-secondary-cue`).
  - Perfect for Japanese, Spanish, or foreign language learning.

- [x] **Subtitle Customization Studio**
  - User controls for:
    - Font Size ($70\%$ to $240\%$).
    - Text Color Swatches (White, Yellow, Cyan, Green).
    - Vertical Position offset (move subtitles higher/lower).
    - Real-time style persistence in `localStorage`.

- [x] **Embedded MKV Subtitle Extraction (Server-Side)**
  - Extracts and converts internal Matroska subtitles (SubRip, ASS/SSA, PGS) to WebVTT on the fly via FFmpeg and `/api/v1/stream/subtitles`.

---

## 5. Torrent Swarm & Streaming Engine

- [x] **Dynamic Sliding-Window Buffer Allocation**
  - Intelligent piece prioritization that balances sequential streaming (for smooth playback) with rarest-first downloading (to maintain high swarm health).

- [x] **Visual Swarm & Peer Map Inspector**
  - Interactive HUD modal showing:
    - Real-time download/upload speed gauges.
    - Connected peer count and bitfield progress %.
    - 64-piece sliding window bitfield map with real-time green piece indicators.
    - Connected peer client software list (qBittorrent, Transmission, Libtorrent) with individual speeds.

- [x] **UPnP & NAT-PMP Automatic Port Forwarding**
  - Enabled automatically in WebTorrent client to bypass strict NATs and connect to non-connectable seeders.

---

## 6. Casting & External Hardware

- [x] **Google Cast (Chromecast) Integration**
  - Native browser Remote Playback API Cast sender button (`#btn-hud-cast`) to cast streams directly to Google TV, Chromecast, and smart TVs.

- [x] **Universal External Player Launcher Hub**
  - Native desktop media player launcher with custom protocol handler and `/api/v1/stream/launch-external` endpoint supporting:
    - **VLC Media Player**
    - **MPV Player**
    - **MPC-HC / MPC-BE**
    - **PotPlayer**
  - M3U playlist stream generator (`/api/v1/stream/playlist.m3u`).

---

## 7. Discovery, Recommendations & Metadata

- [x] **Interactive YouTube Trailer Modal**
  - 1-click **"Watch Official Trailer"** button on cards and detail modal that pops up high-definition YouTube trailer in-app without leaving the page.

- [x] **Rotten Tomatoes & Metacritic Critic Badges**
  - Certified Fresh Tomatometer % and Metascore ratings displayed alongside IMDb rating directly on detail modal.

- [x] **"More Like This" Recommendations Carousel**
  - Dynamic recommendations carousel generated in the detail modal based on shared genres and cast.

- [x] **Kitsu Anime API Integration & Granular Categorization**
  - High-performance Kitsu anime client fetching rich metadata, episodes, formats, and broadcast statuses.
  - Granular format category filters: **All**, **TV Series**, **Movies**, **OVA / ONA**, and **Specials / Off-Season**.
  - Dynamic format badges (`[TV]`, `[MOVIE]`, `[OVA]`, `[SPECIAL]`) and publication status indicators (`Finished`, `Currently Airing`).

---

## 8. Offline Downloads & Library Management

- [x] **"My Library" Multi-State Bookmark & Watchlist Manager**
  - Full CRUD persistent library storage backed by `data/library.json`.
  - Multi-state tracking: **Watching** 👁️, **Plan to Watch** ⏳, **Completed** ✅, **On Hold** ⏸️, and **Dropped** ⏹️.
  - Dedicated **"My Library"** modal with category counters, search filter, and quick status switcher.
  - One-click bookmark toggle button on all media cards and status dropdown in the detail modal.
  - Real-time playback progress sync that auto-updates current season/episode and progress percentage in the user's library.

- [x] **Anime Title-Boundary & Anti-Pollution Stream Resolver**
  - Franchise-aware title token boundary analysis (`is_same_show_title`) that rejects spinoffs and sequels (e.g. rejects *Fairy Tail: 100 Years Quest* for original *Fairy Tail* searches).
  - Absolute episode numbering resolver (`- 08`, ` 08 `, `008`) and complete season batch pack discovery.

- [x] **"Download for Offline Playback"**
  - 1-click direct HTTP 206 background downloading of media with clean sanitized file names (`Movie.Title.2024.mp4`) from player HUD and stream cards.

- [x] **Storage Space & Cache Manager**
  - User settings dashboard showing disk usage of cached pieces in `.stream_cache` with 1-click **"Clear Cache"** calling backend `/api/v1/stream/cache/clear`.

---

## 9. Stremio Addon Ecosystem & Extensibility

- [x] **Stremio Addon Engine (V3 Manifest Support)**
  - Enter any Stremio community addon URL (e.g., Torrentio, CyberFlix, Cinemeta) in Settings to parse manifest and dynamically query its stream endpoints (`/stream/{type}/{id}.json`).
  - Merges community addon streams alongside local DHT scraper results.

---

## 10. UI Polish, Theming & Accessibility

- [x] **Theme Customizer (5 Unique Palettes)**
  - **Emerald Matrix** (Default sleek obsidian & vivid emerald `#00e676`)
  - **Cyberpunk Neon** (Deep dark blue backdrop, neon cyan & hot pink accents)
  - **OLED Midnight** (Pure 100% black `#000000` backdrop for OLED monitors)
  - **Netflix Red** (Charcoal black `#141414`, bold Netflix red accents `#E50914`)
  - **Obsidian Amethyst** (Deep purple/slate `#0a0910`, bright amethyst `#c4a7e7`)
  - 1-click navbar theme switcher with persistence in `localStorage`.

- [x] **Mobile & Tablet Responsive Touch HUD**
  - Double-tap left side (< 35%): jump -10s with visual indicator.
  - Double-tap right side (> 65%): jump +10s with visual indicator.
  - Double-tap center: toggle play/pause.

- [x] **Smart Autocomplete Search with Live Floating Dropdown**
  - Ultra-fast prefix matching querying IMDb & Kitsu autocomplete APIs.
  - Displays rich suggestion cards with media poster, format pill, release year, IMDb star rating, and keyboard navigation.

- [x] **Long-Press Animated Bookmark Interaction with Status Ring**
  - Circular SVG stroke-dashoffset loading animation when clicking and holding the bookmark icon for 600ms.
  - Pops up quick status menu to set Watching, Plan to Watch, Completed, On Hold, Dropped, or Remove with 1 tap.

- [x] **Collapsible "MY LIST & FAVORITES" Shelf with +/- Toggle**
  - Direct integration with user's library items, high-res posters, progress bars, and watched badges.
  - Clean `[+]` / `[-]` toggle button with accordion animation and `localStorage` persistence.

- [x] **Power-User Large Library Modal with Backup & Restore**
  - Expansive modal box with search, media type filter, sorting dropdown, and card zoom slider (120px - 280px).
  - 1-click **Export Backup** to JSON or CSV spreadsheet.
  - 1-click **Restore Backup** from JSON/CSV files with bulk backend upsert.

- [x] **In-Player Buffering Progress HUD & Countdown**
  - Futuristic HUD replacing raw spinner: animated striped buffer bar, live buffer size / target metrics, real-time download speed, and estimated time remaining until playback begins.

- [x] **Navbar Isolation from GUI Zoom**
  - Fixed pixel typography and dimension lockdown on `.navbar` so GUI scale adjustments only scale content.
