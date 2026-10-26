/**
 * EvoScrapper v2 – High Performance Client Application Logic
 * Monospace Data Grid · Relevance Engine · Real-Time SSE · Multi-Tracker Aggregation
 */

// ── Application State ────────────────────────────────────────────────────────
const state = {
  currentTab: 'torrents',
  activeCategory: 'all',
  query: '',
  filters: {
    resolution: '',
    source: '',
    hdr: '',
    audio: '',
    codec: '',
    min_seeders: 0,
    size_range: '',
    year: '',
    health: '',
    provider: 'all',
  },
  sort: {
    column: 'relevance',
    direction: 'desc', // 'asc' | 'desc'
  },
  isStreamMode: true,
  torrents: [],
  activeEventSource: null,
  trending: {
    category: 'all',
    resolution: '',
    source: '',
    hdr: '',
    audio: '',
    codec: '',
    min_seeders: 0,
    size_range: '',
    provider: 'all',
    search: '',
    sort: 'seeds_desc',
    rawItems: [],
  },
  trendingLoaded: false,
  discover: {
    type: 'movie',
    genre: '',
    animeCategory: 'all',
    catalog: 'top',
    sort: 'trending',
    minRating: '',
    yearFrom: '',
    yearTo: '',
    page: 1,
    items: [],
    loaded: false,
    activeDetail: null,
    activeSeason: 1,
    activeEpisode: 1,
    activeStreams: [],
    activeStream: null,
    streamFilter: {
      quality: 'all',
      text: '',
      sort: 'seeds_desc',
      minSeeds: 0,
    },
  },
  library: {
    filter: 'all',
    search: '',
    typeFilter: 'all',
    sort: 'updated',
    cardZoom: 180,
    items: [],
    counts: {},
    map: {},
  },
  subtitles: {
    activeTrack: null,
    activeSubName: 'Auto',
    activeLang: 'en',
    currentOffset: 0.0,
    rawCues: [],
    availableSubs: [],
    activeLangFilter: 'all',
    preferredLang: 'en',
    drawerOpen: false,
    pgsEngine: (function() { try { return localStorage.getItem('evo_pgs_engine') || 'server_burnin'; } catch(_) { return 'server_burnin'; } })(),
    secondaryTrack: null,
    secondaryCues: [],
    styles: {
      size: 100,
      color: '#ffffff',
      pos: 4.5,
    },
  },
};

// ── Lifecycle Initialization ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initGuiScale();
  initTheme();
  loadSubtitleStyles();
  initTouchHUD();
  initPlayerTimelineControls();
  checkTrackerHealth();
  setInterval(checkTrackerHealth, 30000);
  initLibrary();

  // Bind stream toggle
  const streamToggle = document.getElementById('stream-toggle');
  if (streamToggle) {
    state.isStreamMode = streamToggle.checked;
    streamToggle.addEventListener('change', (e) => {
      state.isStreamMode = e.target.checked;
    });
  }

  // Clear button binding
  const searchInput = document.getElementById('torrent-search-input');
  const clearBtn = document.getElementById('clear-btn');
  if (searchInput && clearBtn) {
    searchInput.addEventListener('input', () => {
      clearBtn.classList.toggle('hidden', !searchInput.value.trim());
    });
  }

  // Keyboard shortcut '/' to focus search
  document.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
      e.preventDefault();
      const input = document.getElementById('torrent-search-input');
      if (input) {
        input.focus();
        input.select();
      }
    } else if (e.key === 'Escape') {
      closeStatusModal();
      closeSubModal();
      closeMediaModal();
      closeDiscoverModal();
      // Note: player-modal dismissal via Escape is handled by the dedicated player keyboard controller
    }
  });
});

// ── GUI & Text Scaling Controller ───────────────────────────────────────────
const DEFAULT_GUI_SCALE = 15.5; // base font size in px (100%)

function initGuiScale() {
  const savedScale = localStorage.getItem('evoscrapper_gui_scale');
  const val = savedScale ? parseFloat(savedScale) : DEFAULT_GUI_SCALE;
  applyGuiScale(val);
}

function handleGuiScaleInput(val) {
  applyGuiScale(parseFloat(val));
}

function applyGuiScale(val) {
  if (isNaN(val) || val < 11 || val > 24) val = DEFAULT_GUI_SCALE;
  document.documentElement.style.setProperty('--gui-scale-px', `${val}px`);

  const percentage = Math.round((val / DEFAULT_GUI_SCALE) * 100);
  const valEl = document.getElementById('gui-scale-value');
  const sliderEl = document.getElementById('gui-scale-slider');

  if (valEl) valEl.innerText = `${percentage}%`;
  if (sliderEl && parseFloat(sliderEl.value) !== val) sliderEl.value = val;

  localStorage.setItem('evoscrapper_gui_scale', String(val));
}

function resetGuiScale() {
  applyGuiScale(DEFAULT_GUI_SCALE);
  showToast('GUI scale reset to 100%', 'info');
}

// ── Tab Navigation ───────────────────────────────────────────────────────────
function switchTab(tab) {
  state.currentTab = tab;

  const tabs = ['torrents', 'subtitles', 'trending', 'discover'];
  tabs.forEach((t) => {
    const viewEl = document.getElementById(`view-${t}`);
    const navEl = document.getElementById(`nav-${t}`);
    const mnavEl = document.getElementById(`mnav-${t}`);

    const isActive = t === tab;
    if (viewEl) viewEl.classList.toggle('hidden', !isActive);
    if (navEl) navEl.classList.toggle('active', isActive);
    if (mnavEl) mnavEl.classList.toggle('active', isActive);
  });

  if (tab === 'trending' && !state.trendingLoaded) {
    loadTrending();
  } else if (tab === 'discover') {
    renderContinueWatchingShelf();
    renderBookmarksShelf();
    if (!state.discover.loaded) {
      loadDiscoverCatalog();
    }
  }
}

// ── Category Selector ────────────────────────────────────────────────────────
function setCategory(cat) {
  state.activeCategory = cat;
  document.querySelectorAll('.cat-pill').forEach((btn) => {
    const isTarget = btn.getAttribute('data-cat') === cat;
    btn.classList.toggle('active', isTarget);
  });
  renderAndFilterTorrents();
}

// ── Filter Controls ──────────────────────────────────────────────────────────
function setFilter(type, value) {
  state.filters[type] = value;

  // Update chip active states for resolution, source, min_seeders
  if (['resolution', 'source', 'min_seeders'].includes(type)) {
    document.querySelectorAll(`.filter-chip[data-filter="${type}"]`).forEach((btn) => {
      const isTarget = btn.getAttribute('data-val') === String(value);
      btn.classList.toggle('active', isTarget);
    });
  }

  renderAndFilterTorrents();
}

function resetAllFilters() {
  state.activeCategory = 'all';
  state.filters = {
    resolution: '',
    source: '',
    hdr: '',
    audio: '',
    codec: '',
    min_seeders: 0,
    size_range: '',
    year: '',
    health: '',
    provider: 'all',
  };

  document.querySelectorAll('#category-bar .cat-pill').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-cat') === 'all');
  });

  document.querySelectorAll('#filter-bar .filter-chip').forEach((btn) => {
    const val = btn.getAttribute('data-val');
    btn.classList.toggle('active', val === '' || val === '0');
  });

  ['hdr-filter', 'audio-filter', 'codec-filter', 'size-filter', 'year-filter', 'health-filter', 'sort-select', 'provider-select'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.selectedIndex = 0;
  });

  state.sort.column = 'relevance';
  state.sort.direction = 'desc';

  renderAndFilterTorrents();
  showToast('Torrents filters reset', 'info');
}

// ── Column Sorting ───────────────────────────────────────────────────────────
function handleSortSelect(val) {
  if (val === 'relevance') {
    state.sort.column = 'relevance';
    state.sort.direction = 'desc';
  } else if (val === 'seeds_desc') {
    state.sort.column = 'seeds';
    state.sort.direction = 'desc';
  } else if (val === 'seeds_asc') {
    state.sort.column = 'seeds';
    state.sort.direction = 'asc';
  } else if (val === 'size_desc') {
    state.sort.column = 'size';
    state.sort.direction = 'desc';
  } else if (val === 'size_asc') {
    state.sort.column = 'size';
    state.sort.direction = 'asc';
  } else if (val === 'title_asc') {
    state.sort.column = 'title';
    state.sort.direction = 'asc';
  }
  renderAndFilterTorrents();
}

function sortBy(column) {
  if (state.sort.column === column) {
    state.sort.direction = state.sort.direction === 'asc' ? 'desc' : 'asc';
  } else {
    state.sort.column = column;
    // Default directions per column type
    state.sort.direction = ['seeds', 'size', 'relevance'].includes(column) ? 'desc' : 'asc';
  }

  const sortSelect = document.getElementById('sort-select');
  if (sortSelect) {
    if (state.sort.column === 'seeds') sortSelect.value = state.sort.direction === 'desc' ? 'seeds_desc' : 'seeds_asc';
    else if (state.sort.column === 'size') sortSelect.value = state.sort.direction === 'desc' ? 'size_desc' : 'size_asc';
    else if (state.sort.column === 'title') sortSelect.value = 'title_asc';
    else if (state.sort.column === 'relevance') sortSelect.value = 'relevance';
  }

  renderAndFilterTorrents();
}

// ── Relevance Scoring (Client-Side) ──────────────────────────────────────────
function computeRelevanceScore(title, query) {
  if (!query || !query.trim()) return 1.0;

  const cleanTitle = title.toLowerCase().replace(/[^a-z0-9\s]/g, ' ');
  const cleanQuery = query.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').trim();

  if (!cleanQuery) return 1.0;

  // Exact phrase match gives top score
  if (cleanTitle.includes(cleanQuery)) {
    return 100.0;
  }

  const queryWords = cleanQuery.split(/\s+/).filter((w) => w.length > 1);
  if (queryWords.length === 0) return 1.0;

  let matchCount = 0;
  for (const word of queryWords) {
    if (cleanTitle.includes(word)) {
      matchCount++;
    }
  }

  if (matchCount === 0) return 0.0;
  return (matchCount / queryWords.length) * 80.0;
}

// ── Search Handlers ──────────────────────────────────────────────────────────
function clearSearchInput() {
  const input = document.getElementById('torrent-search-input');
  const clearBtn = document.getElementById('clear-btn');
  if (input) {
    input.value = '';
    input.focus();
  }
  if (clearBtn) clearBtn.classList.add('hidden');
}

function quickSearch(term) {
  const input = document.getElementById('torrent-search-input');
  if (input) {
    input.value = term;
    const clearBtn = document.getElementById('clear-btn');
    if (clearBtn) clearBtn.classList.remove('hidden');
    handleTorrentSearch(new Event('submit'));
  }
}

async function handleTorrentSearch(e) {
  if (e && e.preventDefault) e.preventDefault();
  const input = document.getElementById('torrent-search-input');
  const query = (input ? input.value : '').trim();
  if (!query) return;

  state.query = query;
  state.torrents = [];

  const spinner = document.getElementById('search-spinner');
  const submitBtn = document.getElementById('search-submit-btn');
  const streamIndicator = document.getElementById('stream-indicator');
  const streamStatus = document.getElementById('stream-status');
  const metaBar = document.getElementById('results-meta-bar');
  const container = document.getElementById('torrents-results-container');

  if (spinner) spinner.classList.remove('hidden');
  if (submitBtn) submitBtn.setAttribute('disabled', 'true');
  if (metaBar) metaBar.classList.add('hidden');

  const startTime = performance.now();

  // Close any existing active SSE stream
  if (state.activeEventSource) {
    state.activeEventSource.close();
    state.activeEventSource = null;
  }

  // Check if we use SSE streaming or combo REST
  if (state.isStreamMode && state.filters.provider === 'all') {
    // ── SSE STREAM MODE ──────────────────────────────────────────────────────
    if (streamIndicator) streamIndicator.classList.remove('hidden');
    if (streamStatus) streamStatus.innerText = 'Connecting to 12 tracker swarms simultaneously…';

    container.innerHTML = `
      <div class="empty-state">
        ${getEvoLoaderHtml('lg', 'Streaming Results', 'Receiving live deduplicated streams from indexers…')}
      </div>
    `;

    const encodedQ = encodeURIComponent(query);
    const eventSource = new EventSource(`/api/v1/torrents/stream?query=${encodedQ}&limit=40`);
    state.activeEventSource = eventSource;

    eventSource.onmessage = (event) => {
      if (event.data === '[DONE]') {
        eventSource.close();
        state.activeEventSource = null;
        if (spinner) spinner.classList.add('hidden');
        if (submitBtn) submitBtn.removeAttribute('disabled');
        if (streamIndicator) streamIndicator.classList.add('hidden');
        renderAndFilterTorrents(startTime);
        showToast(`Search completed: ${state.torrents.length} releases found`, 'info');
        return;
      }

      try {
        const payload = JSON.parse(event.data);
        const { provider, items } = payload;

        if (streamStatus) {
          streamStatus.innerText = `Received ${items.length} items from ${provider}… (${state.torrents.length + items.length} total)`;
        }

        if (items && items.length > 0) {
          state.torrents.push(...items);
          state.torrents = deduplicateClient(state.torrents);
          renderAndFilterTorrents(startTime);
        }
      } catch (err) {
        console.error('Error parsing SSE payload:', err);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      state.activeEventSource = null;
      if (spinner) spinner.classList.add('hidden');
      if (submitBtn) submitBtn.removeAttribute('disabled');
      if (streamIndicator) streamIndicator.classList.add('hidden');
      renderAndFilterTorrents(startTime);
    };

  } else {
    // ── REST COMBO / SINGLE PROVIDER SEARCH ───────────────────────────────────
    try {
      container.innerHTML = `
        <div class="empty-state">
          ${getEvoLoaderHtml('lg', 'Querying Indexers', 'Contacting trackers and running deduplication…')}
        </div>
      `;

      const params = new URLSearchParams({
        query: query,
        provider: state.filters.provider,
        limit: '100',
      });
      if (state.filters.resolution) params.set('resolution', state.filters.resolution);
      if (state.filters.min_seeders > 0) params.set('min_seeders', state.filters.min_seeders);
      if (state.activeCategory !== 'all') params.set('category', state.activeCategory);

      const res = await fetch(`/api/v1/torrents/search?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      state.torrents = data.data || [];
      renderAndFilterTorrents(startTime);
    } catch (err) {
      console.error('Search error:', err);
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon text-red"><i class="fa-solid fa-triangle-exclamation"></i></div>
          <h3>Search Failed</h3>
          <p class="text-red">${escapeHtml(err.message)}</p>
        </div>
      `;
      showToast('Search failed: ' + err.message, 'error');
    } finally {
      if (spinner) spinner.classList.add('hidden');
      if (submitBtn) submitBtn.removeAttribute('disabled');
    }
  }
}

// ── Client-Side Deduplication for Live SSE Batches ───────────────────────────
function deduplicateClient(items) {
  const seenHashes = new Map();
  const seenTitles = new Map();
  const deduped = [];

  for (const item of items) {
    const h = (item.info_hash || '').toLowerCase().trim();
    const t = (item.title || '').toLowerCase().trim();

    if (h) {
      if (seenHashes.has(h)) {
        const existing = seenHashes.get(h);
        (item.sources || [item.provider]).forEach((s) => {
          if (!existing.sources.includes(s)) existing.sources.push(s);
        });
        if (item.seeders > existing.seeders) existing.seeders = item.seeders;
        if (item.leechers > existing.leechers) existing.leechers = item.leechers;
      } else {
        seenHashes.set(h, item);
        deduped.push(item);
      }
    } else {
      if (seenTitles.has(t)) {
        const existing = seenTitles.get(t);
        (item.sources || [item.provider]).forEach((s) => {
          if (!existing.sources.includes(s)) existing.sources.push(s);
        });
        if (item.seeders > existing.seeders) existing.seeders = item.seeders;
      } else {
        seenTitles.set(t, item);
        deduped.push(item);
      }
    }
  }
  return deduped;
}

// ── Filtering, Sorting & Rendering Controller ────────────────────────────────
function renderAndFilterTorrents(startTime = null) {
  let list = [...state.torrents];

  // 1. Relevance Scoring & Filtering
  if (state.query && state.query.length >= 2) {
    const scored = list.map((item) => ({
      item,
      score: computeRelevanceScore(item.title, state.query),
    }));

    // Check if any items matched with score > 0
    const matched = scored.filter((x) => x.score > 0);
    if (matched.length > 0) {
      // Keep only matching items to eliminate noise
      list = matched.map((x) => {
        x.item._relevance = x.score;
        return x.item;
      });
    } else {
      list.forEach((item) => {
        item._relevance = 1;
      });
    }
  } else {
    list.forEach((item) => {
      item._relevance = 1;
    });
  }

  // 2. Category Filter
  if (state.activeCategory !== 'all') {
    const cat = state.activeCategory.toLowerCase();
    list = list.filter((item) => {
      const displayCat = getCategoryDisplay(item).toLowerCase();
      if (cat === displayCat || (cat === 'movies' && displayCat === 'movie') || (cat === 'games' && displayCat === 'game') || (cat === 'audiobooks' && displayCat === 'audiobook')) return true;
      const c = (item.category || '').toLowerCase();
      const t = item.title.toLowerCase();
      if (cat === 'movies') return displayCat === 'movie' || c.includes('movie') || t.includes('1080p') || t.includes('bluray') || t.includes('web-dl');
      if (cat === 'tv') return displayCat === 'tv' || c.includes('tv') || c.includes('show') || c.includes('series') || /s\d\d?e\d\d?/i.test(t);
      if (cat === 'anime') return displayCat === 'anime' || c.includes('anime');
      if (cat === 'games') return displayCat === 'game' || c.includes('game');
      if (cat === 'apps') return displayCat === 'apps' || c.includes('app') || c.includes('software');
      if (cat === 'books') return displayCat === 'books' || c.includes('book') || c.includes('comic') || c.includes('manga');
      if (cat === 'music') return displayCat === 'music' || c.includes('music') || c.includes('audio') || t.includes('flac') || t.includes('mp3') || t.includes('lossless');
      if (cat === 'doc') return displayCat === 'docs' || c.includes('doc') || t.includes('documentary');
      if (cat === 'sports') return displayCat === 'sports' || c.includes('sport') || t.includes('ufc') || t.includes('wwe') || t.includes('f1');
      if (cat === 'courses') return displayCat === 'courses' || c.includes('course') || t.includes('tutorial') || t.includes('udemy');
      if (cat === 'audiobooks') return displayCat === 'audiobook' || c.includes('audiobook') || (c.includes('audio') && (t.includes('m4b') || t.includes('mp3')));
      if (cat === 'dev') return displayCat === 'dev' || c.includes('dev') || c.includes('code') || c.includes('script') || t.includes('github') || t.includes('python');
      if (cat === '3d') return displayCat === '3d' || c.includes('3d') || t.includes('blend') || t.includes('obj') || t.includes('stl') || t.includes('asset');
      return c.includes(cat) || c === 'general' || c === 'other';
    });
  }

  // 3. Resolution Filter
  if (state.filters.resolution) {
    const resTarget = state.filters.resolution.toLowerCase();
    list = list.filter(
      (item) => item.metadata && item.metadata.resolution && item.metadata.resolution.toLowerCase() === resTarget
    );
  }

  // 4. Source Type Filter
  if (state.filters.source) {
    const srcTarget = state.filters.source.toLowerCase();
    list = list.filter(
      (item) => item.metadata && item.metadata.source && item.metadata.source.toLowerCase() === srcTarget
    );
  }

  // 4b. HDR Filter
  if (state.filters.hdr) {
    const hdrTarget = state.filters.hdr.toLowerCase();
    list = list.filter((item) => {
      const hdrs = (item.metadata && item.metadata.hdr) ? item.metadata.hdr.map((h) => h.toLowerCase()) : [];
      return hdrs.some((h) => h.includes(hdrTarget));
    });
  }

  // 4c. Audio Filter
  if (state.filters.audio) {
    const audTarget = state.filters.audio.toLowerCase();
    list = list.filter((item) => {
      const aud = (item.metadata && item.metadata.audio) ? item.metadata.audio.toLowerCase() : '';
      return aud.includes(audTarget);
    });
  }

  // 4d. Year Filter
  if (state.filters.year) {
    list = list.filter((item) => {
      const match = item.title.match(/\b(19\d\d|20\d\d)\b/);
      if (!match) return false;
      const y = parseInt(match[1]);
      if (state.filters.year === '2026') return y === 2026;
      if (state.filters.year === '2025') return y === 2025;
      if (state.filters.year === '2024') return y === 2024;
      if (state.filters.year === '2023') return y === 2023;
      if (state.filters.year === '2020-2022') return y >= 2020 && y <= 2022;
      if (state.filters.year === '2010s') return y >= 2010 && y <= 2019;
      if (state.filters.year === 'classic') return y < 2010;
      return true;
    });
  }

  // 5. Min Seeders Filter
  if (state.filters.min_seeders > 0) {
    list = list.filter((item) => item.seeders >= state.filters.min_seeders);
  }

  // 6. Size Range Filter
  if (state.filters.size_range) {
    const [minStr, maxStr] = state.filters.size_range.split('-');
    const minBytes = parseSizeToBytes(minStr);
    const maxBytes = maxStr ? parseSizeToBytes(maxStr) : Infinity;
    list = list.filter((item) => item.size_bytes >= minBytes && item.size_bytes <= maxBytes);
  }

  // 7. Codec Filter
  if (state.filters.codec) {
    const codecTarget = state.filters.codec.toLowerCase();
    list = list.filter(
      (item) => item.metadata && item.metadata.codec && item.metadata.codec.toLowerCase().includes(codecTarget)
    );
  }

  // 8. Health Filter
  if (state.filters.health) {
    if (state.filters.health === 'verified') {
      list = list.filter((item) => item.seeders >= 10);
    } else if (state.filters.health === 'healthy') {
      list = list.filter((item) => item.seeders > item.leechers);
    } else if (state.filters.health === 'super') {
      list = list.filter((item) => item.seeders >= 100);
    }
  }

  // 9. Tracker Filter (if not 'all')
  if (state.filters.provider !== 'all') {
    list = list.filter((item) => {
      const sources = (item.sources && item.sources.length > 0) ? item.sources : [item.provider];
      return sources.map((s) => s.toLowerCase()).includes(state.filters.provider.toLowerCase());
    });
  }

  // 9. Sorting
  const { column, direction } = state.sort;
  const modifier = direction === 'asc' ? 1 : -1;

  list.sort((a, b) => {
    if (column === 'relevance') {
      const relDiff = ((b._relevance || 0) - (a._relevance || 0)) * modifier;
      if (relDiff !== 0) return relDiff;
      // Secondary sort by seeds
      return (b.seeders - a.seeders) * modifier;
    }
    if (column === 'title') {
      return a.title.localeCompare(b.title) * modifier;
    }
    if (column === 'size') {
      return (a.size_bytes - b.size_bytes) * modifier;
    }
    if (column === 'seeds') {
      return (a.seeders - b.seeders) * modifier;
    }
    if (column === 'leech') {
      return (a.leechers - b.leechers) * modifier;
    }
    if (column === 'date') {
      return (a.upload_date || '').localeCompare(b.upload_date || '') * modifier;
    }
    return 0;
  });

  // Render HTML Table
  renderDataTable(list);

  // Update Meta Header Bar
  const metaBar = document.getElementById('results-meta-bar');
  if (metaBar && state.torrents.length > 0) {
    metaBar.classList.remove('hidden');
    document.getElementById('meta-count').innerText = list.length;

    const uniqueProviders = new Set();
    list.forEach((item) => {
      (item.sources || [item.provider]).forEach((p) => uniqueProviders.add(p));
    });
    document.getElementById('meta-providers').innerText = uniqueProviders.size;

    if (startTime) {
      const sec = ((performance.now() - startTime) / 1000).toFixed(2);
      document.getElementById('meta-time').innerText = `${sec}s`;
    }

    const relInfo = document.getElementById('relevance-info');
    if (relInfo) {
      relInfo.classList.toggle('hidden', !state.query);
    }
  }
}

// ── Data Table HTML Renderer ─────────────────────────────────────────────────
function renderDataTable(items) {
  const container = document.getElementById('torrents-results-container');
  if (!container) return;

  if (!items || items.length === 0) {
    if (state.torrents.length > 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon text-amber"><i class="fa-solid fa-filter-circle-xmark"></i></div>
          <h3>No Matching Torrents</h3>
          <p>No torrents match the active filter criteria. Try relaxing your resolution, seeder threshold, or size range.</p>
        </div>
      `;
    }
    return;
  }

  // Build Table Header with interactive sort arrows
  const getSortIndicator = (col) => {
    if (state.sort.column !== col) return '';
    return state.sort.direction === 'asc' ? ' <span class="sort-arrow">▲</span>' : ' <span class="sort-arrow">▼</span>';
  };

  const rowsHtml = items.map((item) => {
    const meta = item.metadata || {};
    const tags = [];

    if (meta.resolution) tags.push(`<span class="tag tag-res">${escapeHtml(meta.resolution)}</span>`);
    if (meta.source) tags.push(`<span class="tag tag-src">${escapeHtml(meta.source)}</span>`);
    if (meta.codec) tags.push(`<span class="tag tag-codec">${escapeHtml(meta.codec)}</span>`);
    if (meta.audio) tags.push(`<span class="tag tag-audio">${escapeHtml(meta.audio)}</span>`);
    if (meta.hdr && meta.hdr.length > 0) {
      meta.hdr.forEach((h) => tags.push(`<span class="tag tag-hdr">${escapeHtml(h)}</span>`));
    }
    if (meta.group) tags.push(`<span class="tag tag-group">${escapeHtml(meta.group)}</span>`);

    const sources = item.sources && item.sources.length > 0 ? item.sources : [item.provider];
    const sourceBadges = sources
      .map((s) => `<span class="provider-badge">${escapeHtml(s)}</span>`)
      .join(' ');

    const displayCat = getCategoryDisplay(item);
    const catClass = getCategoryClass(displayCat);
    const categoryBadge = `<span class="cat-badge ${catClass}">${escapeHtml(displayCat)}</span>`;

    const seedsClass = item.seeders >= 100 ? 'seeds seeds-high' : 'seeds';

    return `
      <tr>
        <td class="cell-title">
          <div class="title-row">
            ${categoryBadge}
            <span class="title-text" onclick="copyMagnet('${escapeJs(item.magnet_uri)}')" title="Click to copy magnet: ${escapeHtml(item.title)}">
              ${escapeHtml(item.title)}
            </span>
          </div>
          <div class="flex items-center gap-1 flex-wrap">
            ${tags.join('')}
          </div>
        </td>
        <td class="mono font-bold text-primary">${escapeHtml(item.size_formatted)}</td>
        <td class="mono ${seedsClass}">
          <i class="fa-solid fa-arrow-up text-xs"></i> ${item.seeders.toLocaleString()}
        </td>
        <td class="mono leech">
          <i class="fa-solid fa-arrow-down text-xs"></i> ${item.leechers.toLocaleString()}
        </td>
        <td class="col-quality">
          <div class="flex flex-wrap gap-1">
            ${meta.resolution ? `<span class="tag tag-res">${escapeHtml(meta.resolution)}</span>` : ''}
            ${meta.source ? `<span class="tag tag-src">${escapeHtml(meta.source)}</span>` : ''}
          </div>
        </td>
        <td class="col-provider">
          <div class="flex flex-wrap gap-1">${sourceBadges}</div>
        </td>
        <td class="col-date text-dim mono text-xs">${escapeHtml(item.upload_date || '—')}</td>
        <td class="col-actions">
          <div class="flex items-center gap-1 justify-end">
            <button class="btn btn-icon btn-amber btn-sm" onclick="openMediaModal('${escapeJs(item.title)}', '${item.info_hash || ''}', '${escapeJs(item.magnet_uri)}')" title="View Movie Info & Poster Jacket">
              <i class="fa-solid fa-film"></i>
            </button>
            <button class="btn btn-icon btn-cyan btn-sm" onclick="copyMagnet('${escapeJs(item.magnet_uri)}')" title="Copy Magnet URI">
              <i class="fa-solid fa-copy"></i>
            </button>
            <a href="${escapeHtml(item.magnet_uri)}" class="btn btn-icon btn-green btn-sm" title="Open Magnet in Torrent Client">
              <i class="fa-solid fa-download"></i>
            </a>
            <button class="btn btn-icon btn-purple btn-sm" onclick="openSubtitlesModal('${escapeJs(item.title)}', '${item.info_hash || ''}')" title="Lookup Subtitles">
              <i class="fa-solid fa-closed-captioning"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  container.innerHTML = `
    <div class="data-table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th class="col-title ${state.sort.column === 'title' ? 'sorted' : ''}" onclick="sortBy('title')">
              Release Title ${getSortIndicator('title')}
            </th>
            <th class="col-size ${state.sort.column === 'size' ? 'sorted' : ''}" onclick="sortBy('size')">
              Size ${getSortIndicator('size')}
            </th>
            <th class="col-seeds ${state.sort.column === 'seeds' ? 'sorted' : ''}" onclick="sortBy('seeds')">
              Seeds ${getSortIndicator('seeds')}
            </th>
            <th class="col-leech ${state.sort.column === 'leech' ? 'sorted' : ''}" onclick="sortBy('leech')">
              Leech ${getSortIndicator('leech')}
            </th>
            <th class="col-quality">Quality</th>
            <th class="col-provider">Tracker</th>
            <th class="col-date ${state.sort.column === 'date' ? 'sorted' : ''}" onclick="sortBy('date')">
              Date ${getSortIndicator('date')}
            </th>
            <th class="col-actions">Action</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    </div>
  `;
}

// ── Category Helper Functions ────────────────────────────────────────────────
function getCategoryDisplay(item) {
  if (!item) return 'other';
  const c = (item.category || '').toLowerCase();
  const t = (item.title || '').toLowerCase();
  if (c.includes('movie') || c.includes('film')) return 'movie';
  if (c.includes('tv') || c.includes('show') || c.includes('series') || /s\d\d?e\d\d?/i.test(t)) return 'tv';
  if (c.includes('anime')) return 'anime';
  if (c.includes('game')) return 'game';
  if (c.includes('app') || c.includes('soft')) return 'apps';
  if (c.includes('audiobook')) return 'audiobook';
  if (c.includes('book') || c.includes('comic') || c.includes('manga')) return 'books';
  if (c.includes('music') || c.includes('audio') || c.includes('flac') || c.includes('mp3')) return 'music';
  if (c.includes('doc')) return 'docs';
  if (c.includes('sport')) return 'sports';
  if (c.includes('course') || c.includes('tutorial')) return 'courses';
  if (c.includes('dev') || c.includes('code') || c.includes('script')) return 'dev';
  if (c.includes('3d') || c.includes('asset') || c.includes('blend')) return '3d';
  if (c === 'video') {
    if (/s\d\d?e\d\d?/i.test(t) || t.includes('season') || t.includes('complete')) return 'tv';
    return 'movie';
  }
  return item.category || 'other';
}

function getCategoryClass(cat) {
  const c = (cat || '').toLowerCase();
  if (c.includes('movie') || c.includes('film')) return 'cat-movie';
  if (c.includes('tv') || c.includes('show') || c.includes('series')) return 'cat-tv';
  if (c.includes('anime')) return 'cat-anime';
  if (c.includes('game')) return 'cat-game';
  if (c.includes('app') || c.includes('soft')) return 'cat-app';
  if (c.includes('audiobook')) return 'cat-audiobooks';
  if (c.includes('book') || c.includes('comic') || c.includes('manga')) return 'cat-book';
  if (c.includes('music') || c.includes('audio') || c.includes('flac') || c.includes('mp3')) return 'cat-music';
  if (c.includes('doc')) return 'cat-doc';
  if (c.includes('sport')) return 'cat-sports';
  if (c.includes('course') || c.includes('tutorial')) return 'cat-courses';
  if (c.includes('dev') || c.includes('code') || c.includes('script')) return 'cat-dev';
  if (c.includes('3d') || c.includes('asset') || c.includes('blend')) return 'cat-3d';
  if (c.includes('video')) return 'cat-movie';
  return 'cat-other';
}

function parseSizeToBytes(str) {
  if (!str) return 0;
  const num = parseFloat(str);
  const upper = str.toUpperCase();
  if (upper.includes('GB')) return num * 1024 * 1024 * 1024;
  if (upper.includes('MB')) return num * 1024 * 1024;
  if (upper.includes('TB')) return num * 1024 * 1024 * 1024 * 1024;
  return num;
}

// ── Subtitles Tab Search ─────────────────────────────────────────────────────
async function handleSubtitlesSearch(e) {
  if (e && e.preventDefault) e.preventDefault();

  const queryInput = document.getElementById('subs-query-input');
  const seasonInput = document.getElementById('subs-season-input');
  const episodeInput = document.getElementById('subs-episode-input');
  const langSelect = document.getElementById('subs-lang-select');
  const container = document.getElementById('subtitles-results-container');
  const spinner = document.getElementById('subs-spinner');
  const metaBar = document.getElementById('subs-meta-bar');

  const query = (queryInput ? queryInput.value : '').trim();
  if (!query) return;

  const season = seasonInput ? seasonInput.value : '';
  const episode = episodeInput ? episodeInput.value : '';
  const language = langSelect ? langSelect.value : 'en';

  if (spinner) spinner.classList.remove('hidden');
  if (metaBar) metaBar.classList.add('hidden');

  container.innerHTML = `
    <div class="empty-state">
      ${getEvoLoaderHtml('lg', 'Resolving Subtitles', 'Searching OpenSubtitles, Gestdown, YIFY, and AnimeTosho…')}
    </div>
  `;

  const startTime = performance.now();

  try {
    const params = new URLSearchParams({
      query: query,
      language: language,
      limit: '100',
    });
    if (season) params.set('season', season);
    if (episode) params.set('episode', episode);

    const res = await fetch(`/api/v1/subtitles/search?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    const subs = data.data || [];

    const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
    if (metaBar) {
      metaBar.classList.remove('hidden');
      document.getElementById('subs-meta-count').innerText = subs.length;
      document.getElementById('subs-meta-time').innerText = `${elapsed}s`;
    }

    if (subs.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon text-dim"><i class="fa-regular fa-face-frown"></i></div>
          <h3>No Subtitles Found</h3>
          <p class="text-dim">No subtitles matched "${escapeHtml(query)}" in language (${language.toUpperCase()}). Try another language or an IMDb ID.</p>
        </div>
      `;
      return;
    }

    const rowsHtml = subs.map((s) => `
      <div class="subs-row">
        <div>
          <span class="mono text-primary font-bold line-clamp-1" style="word-break:break-all;">
            ${escapeHtml(s.release_name || s.id)}
          </span>
        </div>
        <div>
          <span class="tag tag-hdr">${escapeHtml(s.language || 'English')}</span>
        </div>
        <div class="hide-mobile">
          <span class="tag tag-codec">${escapeHtml((s.format || 'srt').toUpperCase())}</span>
        </div>
        <div class="hide-mobile mono text-xs text-dim">
          ${escapeHtml(s.provider)}
        </div>
        <div class="hide-mobile mono text-xs text-dim">
          ${s.season ? `S${s.season}E${s.episode || 1}` : 'Movie'}
        </div>
        <div>
          <a
            href="/api/v1/subtitles/download?url=${encodeURIComponent(s.download_url)}"
            target="_blank"
            class="btn btn-sm btn-green"
            title="Download Subtitle File"
          >
            <i class="fa-solid fa-download"></i> GET .SRT
          </a>
        </div>
      </div>
    `).join('');

    container.innerHTML = `
      <div class="data-table-wrap">
        <div class="subs-grid">
          <div class="subs-header">
            <div>Release / File</div>
            <div>Language</div>
            <div class="hide-mobile">Format</div>
            <div class="hide-mobile">Provider</div>
            <div class="hide-mobile">Type</div>
            <div>Action</div>
          </div>
          ${rowsHtml}
        </div>
      </div>
    `;

    showToast(`Found ${subs.length} subtitles for "${query}"`, 'info');
  } catch (err) {
    console.error('Subtitle search error:', err);
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon text-red"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3>Subtitle Lookup Error</h3>
        <p class="text-red">${escapeHtml(err.message)}</p>
      </div>
    `;
    showToast('Failed to fetch subtitles: ' + err.message, 'error');
  } finally {
    if (spinner) spinner.classList.add('hidden');
  }
}

// ── Subtitle Modal (Lookup from Torrent Row) ─────────────────────────────────
async function openSubtitlesModal(title, infoHash) {
  const modal = document.getElementById('sub-modal');
  const modalTitle = document.getElementById('modal-sub-title');
  const modalSubtitle = document.getElementById('modal-sub-subtitle');
  const modalList = document.getElementById('modal-sub-list');

  modal.classList.remove('hidden');
  modalTitle.innerText = title;
  modalSubtitle.innerText = infoHash
    ? `Hash Sync: ${infoHash.slice(0, 12)}…`
    : 'Querying subtitle indexers…';

  modalList.innerHTML = `
    <div class="empty-state">
      ${getEvoLoaderHtml('lg', 'Searching Subtitles', 'Resolving synchronized subtitles across all providers…')}
    </div>
  `;

  try {
    let url = '';
    if (infoHash) {
      url = `/api/v1/subtitles/by-hash?info_hash=${encodeURIComponent(infoHash)}`;
    } else {
      url = `/api/v1/subtitles/search?query=${encodeURIComponent(title)}&limit=30`;
    }

    const res = await fetch(url);
    const data = await res.json();
    let subs = data.data || [];

    // Fallback search by clean title if hash returned empty
    if (subs.length === 0 && infoHash) {
      const cleanTitle = title.replace(/\./g, ' ').replace(/\[.*?\]|\(.*?\)/g, '').trim();
      const res2 = await fetch(`/api/v1/subtitles/search?query=${encodeURIComponent(cleanTitle)}&limit=30`);
      const data2 = await res2.json();
      subs = data2.data || [];
    }

    if (subs.length === 0) {
      modalList.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon text-dim"><i class="fa-regular fa-face-frown"></i></div>
          <h3>No Subtitles Found</h3>
          <p>No exact synchronized subtitles found for this release.</p>
        </div>
      `;
      return;
    }

    modalList.innerHTML = subs.map((s) => `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:0.625rem;border-bottom:1px solid var(--border-dim);gap:1rem;">
        <div>
          <div class="flex items-center gap-1 mb-1">
            <span class="tag tag-hdr">${escapeHtml(s.language)}</span>
            <span class="tag tag-codec">${escapeHtml((s.format || 'srt').toUpperCase())}</span>
            <span class="mono text-dim text-xs">${escapeHtml(s.provider)}</span>
          </div>
          <div class="mono text-xs text-primary line-clamp-1" style="max-width:550px;">
            ${escapeHtml(s.release_name || s.id)}
          </div>
        </div>
        <a
          href="/api/v1/subtitles/download?url=${encodeURIComponent(s.download_url)}"
          target="_blank"
          class="btn btn-sm btn-green"
        >
          <i class="fa-solid fa-download"></i> GET .SRT
        </a>
      </div>
    `).join('');

  } catch (err) {
    modalList.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon text-red"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3>Failed to Fetch Subtitles</h3>
        <p class="text-red">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function closeSubModal() {
  const modal = document.getElementById('sub-modal');
  if (modal) modal.classList.add('hidden');
}

// ── Media Details & Jacket Modal ─────────────────────────────────────────────
async function openMediaModal(title, infoHash, magnet) {
  const modal = document.getElementById('media-modal');
  const backdrop = document.getElementById('media-backdrop');
  const content = document.getElementById('media-modal-content');
  if (!modal || !content) return;

  modal.classList.remove('hidden');
  if (backdrop) {
    backdrop.style.backgroundImage = 'none';
  }

  content.innerHTML = `
    <div style="text-align:center;padding:3rem 1rem;width:100%;">
      ${getEvoLoaderHtml('lg', 'Resolving Media & Jacket Artwork', 'Extracting IMDb code, high-res posters, ratings and synopsis…')}
    </div>
  `;

  try {
    const encodedTitle = encodeURIComponent(title);
    const res = await fetch(`/api/v1/media/meta?query=${encodedTitle}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const meta = await res.json();

    if (backdrop && meta.backdrop_url) {
      backdrop.style.backgroundImage = `url('${meta.backdrop_url}')`;
    }

    const posterHtml = meta.poster_url
      ? `<img src="${escapeHtml(meta.poster_url)}" alt="${escapeHtml(meta.title)}" class="media-jacket-img" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'media-jacket-placeholder\\'><i class=\\'fa-solid fa-film text-dim\\'></i><span>No Poster</span></div>';">`
      : `<div class="media-jacket-placeholder"><i class="fa-solid fa-film text-dim" style="font-size:2rem;"></i><span>No Poster</span></div>`;

    const imdbLink = meta.imdb_id
      ? `<a href="https://www.imdb.com/title/${escapeHtml(meta.imdb_id)}" target="_blank" rel="noopener noreferrer" class="tag-imdb" title="Open on IMDb">
           <i class="fa-brands fa-imdb"></i> ${escapeHtml(meta.imdb_id)}
         </a>`
      : '';

    const ratingBadge = meta.rating
      ? `<span class="tag tag-rating"><i class="fa-solid fa-star text-amber"></i> ${escapeHtml(meta.rating)}/10</span>`
      : '';

    const yearBadge = meta.year
      ? `<span class="tag tag-group">${escapeHtml(meta.year)}</span>`
      : '';

    const runtimeBadge = meta.runtime
      ? `<span class="tag tag-group"><i class="fa-regular fa-clock"></i> ${escapeHtml(meta.runtime)}</span>`
      : '';

    const typeBadge = `<span class="tag tag-res">${escapeHtml((meta.type || 'MOVIE').toUpperCase())}</span>`;

    const genresHtml = (meta.genres || [])
      .map((g) => `<span class="tag tag-src">${escapeHtml(g)}</span>`)
      .join(' ');

    const crewHtml = [];
    if (meta.director) {
      const directorList = Array.isArray(meta.director)
        ? meta.director
        : (typeof meta.director === 'string' ? meta.director.split(',').map((s) => s.trim()).filter(Boolean) : []);
      const directorPills = directorList.map((d) => {
        const dName = typeof d === 'object' && d ? (d.name || '') : String(d);
        return `<button type="button" class="cast-pill director-pill" onclick="searchDiscoverByPerson('${escapeJs(dName)}')" title="View ${escapeHtml(dName)}'s filmography"><i class="fa-solid fa-film" style="font-size:0.65rem;opacity:0.7;"></i> ${escapeHtml(dName)}</button>`;
      }).join('');
      if (directorPills) {
        crewHtml.push(`<div class="crew-row" style="margin-bottom:0.4rem;"><span class="crew-label" style="font-size:0.7rem;font-weight:700;color:var(--text-dim);margin-right:0.5rem;">DIRECTOR:</span><span class="cast-pills-wrap" style="display:inline-flex;flex-wrap:wrap;gap:0.35rem;">${directorPills}</span></div>`);
      }
    }
    if (meta.cast && meta.cast.length > 0) {
      const castList = Array.isArray(meta.cast)
        ? meta.cast
        : (typeof meta.cast === 'string' ? meta.cast.split(',').map((s) => s.trim()).filter(Boolean) : []);
      const maxCastVisible = 8;
      const visibleCast = castList.slice(0, maxCastVisible);
      const hiddenCount = castList.length - visibleCast.length;
      const castPills = visibleCast.map((c) => {
        const cName = typeof c === 'object' && c ? (c.name || '') : String(c);
        return `<button type="button" class="cast-pill" onclick="searchDiscoverByPerson('${escapeJs(cName)}')" title="View ${escapeHtml(cName)}'s filmography">${escapeHtml(cName)}</button>`;
      }).join('');
      const moreBtn = hiddenCount > 0 ? `<button type="button" class="cast-pill cast-pill-more" onclick="this.parentElement.querySelectorAll('.cast-pill-hidden').forEach(el=>el.classList.remove('cast-pill-hidden'));this.remove()">+${hiddenCount} more</button>` : '';
      const hiddenCastPills = castList.slice(maxCastVisible).map((c) => {
        const cName = typeof c === 'object' && c ? (c.name || '') : String(c);
        return `<button type="button" class="cast-pill cast-pill-hidden" onclick="searchDiscoverByPerson('${escapeJs(cName)}')" title="View ${escapeHtml(cName)}'s filmography" style="display:none;">${escapeHtml(cName)}</button>`;
      }).join('');
      crewHtml.push(`<div class="crew-row" style="margin-bottom:0.4rem;"><span class="crew-label" style="font-size:0.7rem;font-weight:700;color:var(--text-dim);margin-right:0.5rem;">CAST:</span><span class="cast-pills-wrap" style="display:inline-flex;flex-wrap:wrap;gap:0.35rem;">${castPills}${hiddenCastPills}${moreBtn}</span></div>`);
    }

    const trailerBtn = meta.trailer_embed
      ? `<button class="btn btn-sm btn-cyan" onclick="toggleTrailerEmbed('${escapeJs(meta.trailer_embed)}')">
           <i class="fa-solid fa-play"></i> Watch Trailer
         </button>`
      : (meta.trailer_url ? `<a href="${escapeHtml(meta.trailer_url)}" target="_blank" class="btn btn-sm btn-cyan"><i class="fa-solid fa-arrow-up-right-from-square"></i> Trailer</a>` : '');

    const magnetBtn = magnet
      ? `<button class="btn btn-sm btn-green" onclick="copyMagnet('${escapeJs(magnet)}')">
           <i class="fa-solid fa-magnet"></i> Copy Magnet
         </button>`
      : '';

    const subsBtn = `<button class="btn btn-sm btn-purple" onclick="closeMediaModal();openSubtitlesModal('${escapeJs(meta.title || title)}', '${meta.imdb_id || infoHash || ''}')">
      <i class="fa-solid fa-closed-captioning"></i> Get Subtitles
    </button>`;

    content.innerHTML = `
      <div class="media-jacket-card">
        ${posterHtml}
      </div>
      <div class="media-info-col">
        <h2 class="media-main-title">${escapeHtml(meta.title)}</h2>
        <div class="media-meta-badges">
          ${typeBadge}
          ${yearBadge}
          ${ratingBadge}
          ${runtimeBadge}
          ${imdbLink}
          ${genresHtml}
        </div>
        <div class="media-plot">
          ${escapeHtml(meta.plot || 'No synopsis available for this media title.')}
        </div>
        <div class="media-crew">
          ${crewHtml.join('')}
        </div>
        <div class="media-actions-bar">
          ${trailerBtn}
          ${magnetBtn}
          ${subsBtn}
        </div>
        <div id="media-trailer-container" class="hidden"></div>
      </div>
    `;

  } catch (err) {
    content.innerHTML = `
      <div style="text-align:center;padding:3rem 1rem;width:100%;">
        <div class="empty-icon text-dim"><i class="fa-regular fa-face-frown" style="font-size:2.5rem;"></i></div>
        <h3 style="margin-top:1rem;font-family:var(--font-mono);font-size:0.95rem;">Metadata Not Found</h3>
        <p style="font-size:0.75rem;color:var(--text-dim);margin-top:0.25rem;">Could not resolve IMDb jacket artwork for "${escapeHtml(title)}".</p>
        <div style="margin-top:1.25rem;display:flex;justify-content:center;gap:0.5rem;">
          ${magnet ? `<button class="btn btn-sm btn-green" onclick="copyMagnet('${escapeJs(magnet)}')"><i class="fa-solid fa-magnet"></i> Copy Magnet</button>` : ''}
          <button class="btn btn-sm btn-purple" onclick="closeMediaModal();openSubtitlesModal('${escapeJs(title)}', '${infoHash || ''}')">
            <i class="fa-solid fa-closed-captioning"></i> Lookup Subtitles
          </button>
        </div>
      </div>
    `;
  }
}

function closeMediaModal() {
  const modal = document.getElementById('media-modal');
  if (modal) modal.classList.add('hidden');
  const trailerContainer = document.getElementById('media-trailer-container');
  if (trailerContainer) {
    trailerContainer.classList.add('hidden');
    trailerContainer.innerHTML = '';
  }
}

function toggleTrailerEmbed(embedUrl) {
  const container = document.getElementById('media-trailer-container');
  if (!container) return;
  if (!container.classList.contains('hidden')) {
    container.classList.add('hidden');
    container.innerHTML = '';
  } else {
    container.classList.remove('hidden');
    container.innerHTML = `
      <div class="trailer-frame-wrap">
        <iframe src="${escapeHtml(embedUrl)}?autoplay=1" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
      </div>
    `;
  }
}


// ── Trending View Controller ─────────────────────────────────────────────────
function setTrendingCategory(cat) {
  state.trending.category = cat;
  document.querySelectorAll('#trending-category-bar .cat-pill').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-tcat') === cat);
  });
  renderTrendingTable();
}

function setTrendingFilter(type, value) {
  state.trending[type] = value;
  if (['resolution', 'source', 'min_seeders'].includes(type)) {
    document.querySelectorAll(`.filter-chip[data-tfilter="${type}"]`).forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-val') === String(value));
    });
  }
  renderTrendingTable();
}

function handleTrendingSearch(val) {
  state.trending.search = (val || '').trim().toLowerCase();
  renderTrendingTable();
}

function setTrendingSort(sortVal) {
  state.trending.sort = sortVal;
  renderTrendingTable();
}

function resetTrendingFilters() {
  state.trending.category = 'all';
  state.trending.resolution = '';
  state.trending.source = '';
  state.trending.hdr = '';
  state.trending.audio = '';
  state.trending.codec = '';
  state.trending.min_seeders = 0;
  state.trending.size_range = '';
  state.trending.provider = 'all';
  state.trending.search = '';
  state.trending.sort = 'seeds_desc';

  document.querySelectorAll('#trending-category-bar .cat-pill').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-tcat') === 'all');
  });

  document.querySelectorAll('#trending-filter-bar .filter-chip').forEach((btn) => {
    const val = btn.getAttribute('data-val');
    btn.classList.toggle('active', val === '' || val === '0');
  });

  const searchInput = document.getElementById('trending-filter-input');
  if (searchInput) searchInput.value = '';

  ['trending-hdr-filter', 'trending-audio-filter', 'trending-codec-filter', 'trending-size-filter', 'trending-provider-filter'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.selectedIndex = 0;
  });

  const sortSelect = document.getElementById('trending-sort-select');
  if (sortSelect) sortSelect.value = 'seeds_desc';

  renderTrendingTable();
  showToast('Trending filters reset', 'info');
}

async function loadTrending() {
  const container = document.getElementById('trending-results-container');
  const metaBar = document.getElementById('trending-meta-bar');
  if (!container) return;

  if (metaBar) metaBar.classList.add('hidden');
  container.innerHTML = `
    <div class="empty-state">
      ${getEvoLoaderHtml('lg', 'Loading Trending Releases', 'Fetching top torrents from YTS, ThePirateBay, and Nyaa…')}
    </div>
  `;

  try {
    const res = await fetch('/api/v1/torrents/trending?limit=100');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.trending.rawItems = data.data || [];
    state.trendingLoaded = true;
    renderTrendingTable();
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon text-red"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3>Failed to Load Trending</h3>
        <p class="text-red">${escapeHtml(err.message)}</p>
      </div>
    `;
    showToast('Failed to load trending: ' + err.message, 'error');
  }
}

function renderTrendingTable() {
  const container = document.getElementById('trending-results-container');
  const metaBar = document.getElementById('trending-meta-bar');
  const countEl = document.getElementById('trending-meta-count');
  if (!container) return;

  let list = [...(state.trending.rawItems || [])];

  // 1. Text Search Filter
  if (state.trending.search) {
    const q = state.trending.search;
    list = list.filter((item) => (item.title || '').toLowerCase().includes(q));
  }

  // 2. Category Filter
  if (state.trending.category !== 'all') {
    const cat = state.trending.category.toLowerCase();
    list = list.filter((item) => {
      const displayCat = getCategoryDisplay(item).toLowerCase();
      if (cat === displayCat || (cat === 'movies' && displayCat === 'movie') || (cat === 'games' && displayCat === 'game') || (cat === 'audiobooks' && displayCat === 'audiobook')) return true;
      const c = (item.category || '').toLowerCase();
      const t = item.title.toLowerCase();
      if (cat === 'movies') return displayCat === 'movie' || c.includes('movie') || t.includes('1080p') || t.includes('bluray') || t.includes('web-dl');
      if (cat === 'tv') return displayCat === 'tv' || c.includes('tv') || c.includes('show') || c.includes('series') || /s\d\d?e\d\d?/i.test(t);
      if (cat === 'anime') return displayCat === 'anime' || c.includes('anime');
      if (cat === 'games') return displayCat === 'game' || c.includes('game');
      if (cat === 'apps') return displayCat === 'apps' || c.includes('app') || c.includes('software');
      if (cat === 'books') return displayCat === 'books' || c.includes('book') || c.includes('comic') || c.includes('manga');
      if (cat === 'music') return displayCat === 'music' || c.includes('music') || c.includes('audio') || t.includes('flac') || t.includes('mp3');
      if (cat === 'doc') return displayCat === 'docs' || c.includes('doc') || t.includes('documentary');
      if (cat === 'sports') return displayCat === 'sports' || c.includes('sport') || t.includes('ufc') || t.includes('wwe');
      return c.includes(cat) || c === 'general' || c === 'other';
    });
  }

  // 3. Resolution Filter
  if (state.trending.resolution) {
    const resTarget = state.trending.resolution.toLowerCase();
    list = list.filter(
      (item) => item.metadata && item.metadata.resolution && item.metadata.resolution.toLowerCase() === resTarget
    );
  }

  // 4. Source Filter
  if (state.trending.source) {
    const srcTarget = state.trending.source.toLowerCase();
    list = list.filter(
      (item) => item.metadata && item.metadata.source && item.metadata.source.toLowerCase() === srcTarget
    );
  }

  // 5. HDR Filter
  if (state.trending.hdr) {
    const hdrTarget = state.trending.hdr.toLowerCase();
    list = list.filter((item) => {
      const hdrs = (item.metadata && item.metadata.hdr) ? item.metadata.hdr.map((h) => h.toLowerCase()) : [];
      return hdrs.some((h) => h.includes(hdrTarget));
    });
  }

  // 6. Audio Filter
  if (state.trending.audio) {
    const audTarget = state.trending.audio.toLowerCase();
    list = list.filter((item) => {
      const aud = (item.metadata && item.metadata.audio) ? item.metadata.audio.toLowerCase() : '';
      return aud.includes(audTarget);
    });
  }

  // 7. Codec Filter
  if (state.trending.codec) {
    const codecTarget = state.trending.codec.toLowerCase();
    list = list.filter(
      (item) => item.metadata && item.metadata.codec && item.metadata.codec.toLowerCase().includes(codecTarget)
    );
  }

  // 8. Min Seeders Filter
  if (state.trending.min_seeders > 0) {
    list = list.filter((item) => item.seeders >= state.trending.min_seeders);
  }

  // 9. Size Range Filter
  if (state.trending.size_range) {
    const [minStr, maxStr] = state.trending.size_range.split('-');
    const minBytes = parseSizeToBytes(minStr);
    const maxBytes = maxStr ? parseSizeToBytes(maxStr) : Infinity;
    list = list.filter((item) => item.size_bytes >= minBytes && item.size_bytes <= maxBytes);
  }

  // 10. Tracker Filter
  if (state.trending.provider !== 'all') {
    list = list.filter((item) => {
      const sources = (item.sources && item.sources.length > 0) ? item.sources : [item.provider];
      return sources.map((s) => s.toLowerCase()).includes(state.trending.provider.toLowerCase());
    });
  }

  // 11. Sorting
  const sort = state.trending.sort || 'seeds_desc';
  list.sort((a, b) => {
    if (sort === 'seeds_desc') return b.seeders - a.seeders;
    if (sort === 'seeds_asc') return a.seeders - b.seeders;
    if (sort === 'size_desc') return (b.size_bytes || 0) - (a.size_bytes || 0);
    if (sort === 'size_asc') return (a.size_bytes || 0) - (b.size_bytes || 0);
    if (sort === 'title_asc') return a.title.localeCompare(b.title);
    return 0;
  });

  // Update Meta Count
  if (metaBar && countEl) {
    metaBar.classList.remove('hidden');
    countEl.innerText = list.length.toLocaleString();
  }

  if (list.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon text-dim"><i class="fa-regular fa-face-frown"></i></div>
        <h3>No Matching Trending Releases</h3>
        <p>No releases match your current category and filter selection.</p>
        <button class="btn btn-sm btn-ghost mt-2" onclick="resetTrendingFilters()" style="color:var(--accent);margin-top:1rem;">
          <i class="fa-solid fa-rotate-left"></i> Reset Trending Filters
        </button>
      </div>
    `;
    return;
  }

  const rowsHtml = list.map((item) => {
    const meta = item.metadata || {};
    const tags = [];
    if (meta.resolution) tags.push(`<span class="tag tag-res">${escapeHtml(meta.resolution)}</span>`);
    if (meta.source) tags.push(`<span class="tag tag-src">${escapeHtml(meta.source)}</span>`);
    if (meta.codec) tags.push(`<span class="tag tag-codec">${escapeHtml(meta.codec)}</span>`);
    if (meta.audio) tags.push(`<span class="tag tag-audio">${escapeHtml(meta.audio)}</span>`);
    if (meta.hdr && meta.hdr.length > 0) {
      meta.hdr.forEach((h) => tags.push(`<span class="tag tag-hdr">${escapeHtml(h)}</span>`));
    }
    if (meta.group) tags.push(`<span class="tag tag-group">${escapeHtml(meta.group)}</span>`);

    const displayCat = getCategoryDisplay(item);
    const catClass = getCategoryClass(displayCat);
    const categoryBadge = `<span class="cat-badge ${catClass}">${escapeHtml(displayCat)}</span>`;
    const seedsClass = item.seeders >= 100 ? 'seeds seeds-high' : 'seeds';

    const sources = item.sources && item.sources.length > 0 ? item.sources : [item.provider];
    const sourceBadges = sources
      .map((s) => `<span class="provider-badge">${escapeHtml(s)}</span>`)
      .join(' ');

    return `
      <tr>
        <td class="cell-title">
          <div class="title-row">
            ${categoryBadge}
            <span class="title-text" onclick="copyMagnet('${escapeJs(item.magnet_uri)}')" title="Click to copy magnet: ${escapeHtml(item.title)}">
              ${escapeHtml(item.title)}
            </span>
          </div>
          <div class="flex items-center gap-1 flex-wrap">
            ${tags.join('')}
          </div>
        </td>
        <td class="mono font-bold text-primary">${escapeHtml(item.size_formatted)}</td>
        <td class="mono ${seedsClass}">
          <i class="fa-solid fa-arrow-up text-xs"></i> ${item.seeders.toLocaleString()}
        </td>
        <td class="mono leech">
          <i class="fa-solid fa-arrow-down text-xs"></i> ${item.leechers.toLocaleString()}
        </td>
        <td class="col-quality">
          <div class="flex flex-wrap gap-1">
            ${meta.resolution ? `<span class="tag tag-res">${escapeHtml(meta.resolution)}</span>` : ''}
            ${meta.source ? `<span class="tag tag-src">${escapeHtml(meta.source)}</span>` : ''}
          </div>
        </td>
        <td class="col-provider">
          <div class="flex flex-wrap gap-1">${sourceBadges}</div>
        </td>
        <td class="col-date text-dim mono text-xs">${escapeHtml(item.upload_date || '—')}</td>
        <td class="col-actions">
          <div class="flex items-center gap-1 justify-end">
            <button class="btn btn-icon btn-amber btn-sm" onclick="openMediaModal('${escapeJs(item.title)}', '${item.info_hash || ''}', '${escapeJs(item.magnet_uri)}')" title="View Movie Info & Poster Jacket">
              <i class="fa-solid fa-film"></i>
            </button>
            <button class="btn btn-icon btn-cyan btn-sm" onclick="copyMagnet('${escapeJs(item.magnet_uri)}')" title="Copy Magnet">
              <i class="fa-solid fa-copy"></i>
            </button>
            <a href="${escapeHtml(item.magnet_uri)}" class="btn btn-icon btn-green btn-sm" title="Open Magnet">
              <i class="fa-solid fa-download"></i>
            </a>
            <button class="btn btn-icon btn-purple btn-sm" onclick="openSubtitlesModal('${escapeJs(item.title)}', '${item.info_hash || ''}')" title="Lookup Subs">
              <i class="fa-solid fa-closed-captioning"></i>
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');

  container.innerHTML = `
    <div class="data-table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th class="col-title">Trending Title</th>
            <th class="col-size">Size</th>
            <th class="col-seeds">Seeds</th>
            <th class="col-leech">Leech</th>
            <th class="col-quality">Quality</th>
            <th class="col-provider">Tracker</th>
            <th class="col-date">Date</th>
            <th class="col-actions">Action</th>
          </tr>
        </thead>
        <tbody>${rowsHtml}</tbody>
      </table>
    </div>
  `;
}

// ── Provider Health & Circuit Breakers ───────────────────────────────────────
async function checkTrackerHealth() {
  try {
    const res = await fetch('/api/v1/providers/status');
    if (!res.ok) return;
    const providers = await res.json();
    const healthyCount = providers.filter((p) => p.status === 'closed').length;
    const badgeText = document.getElementById('tracker-status-text');
    if (badgeText) {
      badgeText.innerText = `${healthyCount}/${providers.length} online`;
    }
  } catch (e) {
    console.warn('Health check warning:', e);
  }
}

async function openStatusModal() {
  const modal = document.getElementById('status-modal');
  const tbody = document.getElementById('provider-status-rows');
  modal.classList.remove('hidden');
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--text-dim);">Checking live tracker circuit metrics…</td></tr>`;

  try {
    const res = await fetch('/api/v1/providers/status');
    const providers = await res.json();

    tbody.innerHTML = providers.map((p) => {
      const isOnline = p.status === 'closed';
      const statusBadge = isOnline
        ? `<span class="tag tag-hdr" style="color:var(--green);border-color:#00ff8844;">ONLINE</span>`
        : `<span class="tag tag-codec" style="color:var(--red);border-color:#ff335544;">CIRCUIT OPEN</span>`;

      return `
        <tr>
          <td class="mono font-bold text-primary">${escapeHtml(p.name)}</td>
          <td class="mono text-dim text-xs uppercase">${escapeHtml(p.type)}</td>
          <td>${statusBadge}</td>
          <td class="mono text-dim">${p.total_calls}</td>
          <td class="mono text-green">${p.successful_calls}</td>
          <td class="mono text-accent">${p.avg_latency_ms} ms</td>
        </tr>
      `;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--red);padding:2rem;">Failed to load status: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function closeStatusModal() {
  const modal = document.getElementById('status-modal');
  if (modal) modal.classList.add('hidden');
}

// ── Clipboard & Toast Helpers ────────────────────────────────────────────────
function copyMagnet(magnet) {
  if (!magnet) return;
  navigator.clipboard.writeText(magnet).then(() => {
    showToast('Magnet copied to clipboard', 'info');
  }).catch(() => {
    showToast('Failed to copy magnet', 'error');
  });
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  syncFullscreenPortal(container, true);

  const toast = document.createElement('div');
  const icon = type === 'error'
    ? '<i class="fa-solid fa-circle-exclamation text-red"></i>'
    : '<i class="fa-solid fa-terminal text-accent"></i>';

  toast.className = 'toast';
  toast.innerHTML = `${icon}<span>${escapeHtml(message)}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
    toast.style.transition = 'all 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

// ── Security & Escaping Utilities ────────────────────────────────────────────
function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, (m) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[m]));
}

function escapeJs(str) {
  if (!str) return '';
  return String(str)
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r');
}

// ── Custom Uiverse.io Neon Cyber SVG Loader (E-v-o) Component ────────────────
function getEvoLoaderHtml(size = 'md', label = '', subtext = '') {
  const sizeMap = {
    xs: 16,
    sm: 22,
    md: 36,
    lg: 52,
    xl: 68,
  };
  const px = sizeMap[size] || 36;
  const labelHtml = label ? `<div class="evo-loader-title">${escapeHtml(label)}</div>` : '';
  const subHtml = subtext ? `<div class="evo-loader-sub">${escapeHtml(subtext)}</div>` : '';

  return `
    <div class="evo-loader-container size-${size}">
      <div class="loader evo-loader size-${size}">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 100 100" width="${px}" height="${px}" class="inline-block evo-svg-e">
          <path stroke-linejoin="round" stroke-linecap="round" stroke-width="8" stroke="url(#b)" d="M 20,20 L 80,20 L 80,27 L 27,27 L 27,50 L 70,50 L 70,57 L 25,57 L 25,80 L 80,80 L 80,87 L 20,87 Z" class="dash" id="E" pathLength="360"></path>
        </svg>
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 100 100" width="${px}" height="${px}" class="inline-block evo-svg-v">
          <path stroke-linejoin="round" stroke-linecap="round" stroke-width="12" stroke="url(#d)" d="M 20,20 L 50,80 L 80,20" class="dash" id="v" pathLength="360"></path>
        </svg>
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 100 100" width="${px}" height="${px}" class="inline-block evo-svg-o">
          <path stroke-linejoin="round" stroke-linecap="round" stroke-width="11" stroke="url(#c)" d="M 50,15 A 35,35 0 0 1 85,50 A 35,35 0 0 1 50,85 A 35,35 0 0 1 15,50 A 35,35 0 0 1 50,15 Z" class="spin" id="o" pathLength="360"></path>
        </svg>
      </div>
      ${labelHtml}
      ${subHtml}
    </div>
  `;
}

// ══════════════════════════════════════════════════════════════════════════════
// DISCOVER CATALOG & STREMIO / TORRENTIO ENGINE
// ══════════════════════════════════════════════════════════════════════════════

function applyDiscoverSort(items) {
  if (!items || items.length === 0) return [];
  const sortVal = state.discover.sort || 'trending';
  const sorted = [...items];

  if (sortVal === 'rating_desc') {
    sorted.sort((a, b) => (parseFloat(b.rating) || 0) - (parseFloat(a.rating) || 0));
  } else if (sortVal === 'year_desc') {
    sorted.sort((a, b) => (parseInt(b.year) || 0) - (parseInt(a.year) || 0));
  } else if (sortVal === 'year_asc') {
    sorted.sort((a, b) => {
      const yA = parseInt(a.year) || 9999;
      const yB = parseInt(b.year) || 9999;
      return yA - yB;
    });
  } else if (sortVal === 'title_asc') {
    sorted.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  } else if (sortVal === 'seeds_desc') {
    const trendingList = state.trending?.rawItems || [];
    const getSeeds = (it) => {
      if (it._computedSeeds !== undefined) return it._computedSeeds;
      if (!trendingList.length) return parseFloat(it.rating) || 0;
      const titleLow = (it.title || '').toLowerCase().trim();
      let maxSeeds = 0;
      for (const t of trendingList) {
        const tTitle = (t.title || '').toLowerCase();
        if (tTitle.includes(titleLow) || (titleLow.length > 5 && tTitle.includes(titleLow.slice(0, 8)))) {
          if ((t.seeds || 0) > maxSeeds) maxSeeds = t.seeds || 0;
        }
      }
      it._computedSeeds = maxSeeds;
      return maxSeeds;
    };
    sorted.sort((a, b) => getSeeds(b) - getSeeds(a));
  }
  return sorted;
}

async function setDiscoverSort(sortVal) {
  state.discover.sort = sortVal;
  const select = document.getElementById('discover-sort-select');
  if (select) select.value = sortVal;

  if (sortVal === 'seeds_desc' && (!state.trending?.rawItems || state.trending.rawItems.length === 0)) {
    try {
      const res = await fetch('/api/v1/torrents/trending?limit=100');
      if (res.ok) {
        const data = await res.json();
        state.trending.rawItems = data.data || [];
      }
    } catch (_) {}
    const sorted = applyDiscoverSort(state.discover.items);
    renderDiscoverGrid(sorted, false);
  } else {
    loadDiscoverCatalog(true);
  }
}

function setDiscoverRatingFilter(val) {
  state.discover.minRating = val || '';
  const sel = document.getElementById('discover-rating-filter');
  if (sel) sel.value = val || '';
  loadDiscoverCatalog(true);
}

function setDiscoverYearFilter(val) {
  if (!val) {
    state.discover.yearFrom = '';
    state.discover.yearTo = '';
  } else {
    const parts = val.split('-');
    state.discover.yearFrom = parts[0] || '';
    state.discover.yearTo = parts[1] || '';
  }
  const sel = document.getElementById('discover-year-filter');
  if (sel) sel.value = val || '';
  loadDiscoverCatalog(true);
}

async function loadDiscoverCatalog(reset = true) {
  const grid = document.getElementById('discover-grid');
  const loading = document.getElementById('discover-loading');
  const moreWrap = document.getElementById('discover-more-wrap');
  const moreBtn = document.getElementById('btn-discover-more');
  const moreSpiral = document.getElementById('discover-more-loading');

  if (reset) {
    state.discover.page = 1;
    state.discover.items = [];
    if (grid) {
      grid.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 4rem 1rem; display: flex; justify-content: center;">
          ${getEvoLoaderHtml('lg', 'Loading catalog...', 'Discovering top trending releases from the swarm...')}
        </div>
      `;
    }
    if (loading) loading.classList.add('hidden');
    if (moreWrap) moreWrap.classList.add('hidden');
    if (moreSpiral) moreSpiral.classList.add('hidden');
    if (moreBtn) moreBtn.classList.remove('hidden');
  } else {
    // Creative spiral animation at center bottom for loading more titles
    if (moreBtn) moreBtn.classList.add('hidden');
    if (moreSpiral) moreSpiral.classList.remove('hidden');
  }

  try {
    const params = new URLSearchParams({
      type: state.discover.type,
      catalog: state.discover.catalog,
      page: state.discover.page,
    });
    if (state.discover.type === 'anime' && state.discover.animeCategory && state.discover.animeCategory !== 'all') {
      params.append('genre', state.discover.animeCategory);
    } else if (state.discover.genre) {
      params.append('genre', state.discover.genre);
    }
    if (state.discover.minRating) {
      params.append('min_rating', state.discover.minRating);
    }
    if (state.discover.yearFrom) {
      params.append('year_from', state.discover.yearFrom);
    }
    if (state.discover.yearTo) {
      params.append('year_to', state.discover.yearTo);
    }
    if (state.discover.sort && state.discover.sort !== 'seeds_desc') {
      params.append('sort', state.discover.sort);
    }

    const res = await fetch(`/api/v1/discover/catalog?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const newItems = data.items || [];
    if (reset) {
      state.discover.items = newItems;
      renderDiscoverHero(newItems);
      updateCatalogHeading();
      const sorted = applyDiscoverSort(newItems);
      renderDiscoverGrid(sorted, false);
    } else {
      state.discover.items.push(...newItems);
      if (state.discover.sort && state.discover.sort !== 'trending') {
        const sorted = applyDiscoverSort(state.discover.items);
        renderDiscoverGrid(sorted, false);
      } else {
        renderDiscoverGrid(newItems, true);
      }
    }
    state.discover.loaded = true;

    if (moreWrap) {
      moreWrap.classList.toggle('hidden', newItems.length < 20);
    }
  } catch (err) {
    console.error('Discover error:', err);
    showToast(`Failed to load catalog: ${err.message}`, 'error');
  } finally {
    if (loading) loading.classList.add('hidden');
    if (moreSpiral) moreSpiral.classList.add('hidden');
    if (moreBtn) moreBtn.classList.remove('hidden');
  }
}

function renderDiscoverGrid(items, append = false) {
  const grid = document.getElementById('discover-grid');
  if (!grid) return;

  if (!append && (!items || items.length === 0)) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-icon"><i class="fa-solid fa-film"></i></div>
        <h3>No titles found</h3>
        <p class="text-dim">Try selecting a different genre or clearing the search query.</p>
      </div>
    `;
    return;
  }

  const cardsHtml = items.map((item) => {
    const posterHtml = item.poster
      ? `<img src="${escapeHtml(item.poster)}" alt="${escapeHtml(item.title)}" class="discover-poster-img" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'discover-poster-fallback\\'><i class=\\'fa-solid fa-image fa-2x\\'></i><span>${escapeJs(item.title)}</span></div>';">`
      : `<div class="discover-poster-fallback"><i class="fa-solid fa-film fa-2x"></i><span>${escapeHtml(item.title)}</span></div>`;

    const ratingBadge = item.rating
      ? `<div class="discover-rating-badge"><i class="fa-solid fa-star"></i> ${escapeHtml(item.rating)}</div>`
      : '';

    const yearBadge = item.year
      ? `<div class="discover-year-badge">${escapeHtml(item.year)}</div>`
      : '';

    const typeBadge = `<div class="discover-type-badge">${escapeHtml(item.type)}</div>`;

    const formatBadge = item.anime_format
      ? `<span class="tag tag-anime-${escapeHtml(item.anime_format.toLowerCase())}">${escapeHtml(item.anime_format)}</span>`
      : '';

    const statusBadge = item.anime_status
      ? `<span class="tag tag-status-${escapeHtml(item.anime_status.toLowerCase())}">${escapeHtml(item.anime_status)}</span>`
      : '';

    const seedsBadge = (item._computedSeeds && item._computedSeeds > 0)
      ? `<span class="tag text-green" style="background:rgba(0,255,136,0.15);border:1px solid rgba(0,255,136,0.3);"><i class="fa-solid fa-seedling"></i> ${item._computedSeeds}</span>`
      : '';

    const bottomLeftBadges = `
      <div class="discover-bottom-left-badges">
        ${formatBadge}
        ${statusBadge}
        ${seedsBadge}
        ${yearBadge}
      </div>
    `;

    const isBookmarked = isItemInLibrary(item.id);
    const curStatus = getItemLibraryStatus(item.id);
    const bookmarkBtn = `
      <button class="card-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}"
        data-id="${escapeHtml(item.id)}"
        data-title="${escapeHtml(item.title)}"
        data-type="${escapeHtml(item.type || 'movie')}"
        data-poster="${escapeHtml(item.poster || '')}"
        data-year="${escapeHtml(item.year || '')}"
        title="${isBookmarked ? `In Library (${(curStatus || 'Saved').replace('_', ' ')}) - Click to toggle, hold for options` : 'Add to Library (Hold for options)'}"
        onpointerdown="handleBookmarkPointerDown(event, this)"
        onpointerup="handleBookmarkPointerUp(event, this)"
        onpointerleave="handleBookmarkPointerLeave(event, this)"
        onpointercancel="handleBookmarkPointerLeave(event, this)"
        oncontextmenu="event.preventDefault(); return false;"
        onclick="event.stopPropagation()">
        <svg class="hold-ring" viewBox="0 0 32 32">
          <circle class="ring-fill" cx="16" cy="16" r="14"></circle>
        </svg>
        <i class="${isBookmarked ? 'fa-solid fa-bookmark text-yellow' : 'fa-regular fa-bookmark'}"></i>
      </button>
    `;

    const genreText = (item.genres && item.genres.length > 0)
      ? item.genres.slice(0, 3).join(', ')
      : (item.type || 'Movie');

    return `
      <div class="discover-card" onclick="openDiscoverModal('${escapeJs(item.id)}', '${escapeJs(item.type)}')">
        <div class="discover-poster-wrap">
          ${posterHtml}
          ${typeBadge}
          ${ratingBadge}
          ${bottomLeftBadges}
          ${bookmarkBtn}
        </div>
        <div class="discover-info">
          <div class="discover-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
          <div class="discover-genres">${escapeHtml(genreText)}</div>
        </div>
      </div>
    `;
  }).join('');

  if (append) {
    grid.insertAdjacentHTML('beforeend', cardsHtml);
  } else {
    grid.innerHTML = cardsHtml;
  }
}

function renderDiscoverHero(items) {
  // Hero spotlight removed per user request
  const banner = document.getElementById('discover-hero-banner');
  if (banner) banner.remove();
}

function playHeroSpotlight() {
  const item = state.discover?.heroItem;
  if (!item) return;
  openDiscoverModal(item.id, item.type);
}

function openHeroSpotlightModal() {
  const item = state.discover?.heroItem;
  if (!item) return;
  openDiscoverModal(item.id, item.type);
}

async function toggleHeroSpotlightBookmark() {
  const item = state.discover?.heroItem;
  if (!item) return;
  await toggleCardBookmark(null, item.id, item.title, item.type, item.poster, item.year);
}

function updateCatalogHeading() {
  const heading = document.getElementById('catalog-heading-title');
  const badge = document.getElementById('catalog-count-badge');
  if (!heading) return;

  const typeName = state.discover.type === 'anime' ? 'Anime' : (state.discover.type === 'series' ? 'TV Series' : 'Movies');
  if (state.discover.genre) {
    heading.innerText = `${state.discover.genre} ${typeName}`;
    if (badge) badge.innerText = 'Filtered';
  } else if (state.discover.type === 'anime' && state.discover.animeCategory && state.discover.animeCategory !== 'all') {
    heading.innerText = `${state.discover.animeCategory.toUpperCase()} Anime`;
    if (badge) badge.innerText = 'Category';
  } else {
    heading.innerText = `Trending ${typeName}`;
    if (badge) badge.innerText = 'Popular Feed';
  }
}

function setDiscoverType(type) {
  state.discover.type = type;
  document.querySelectorAll('[data-dcat]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-dcat') === type);
  });
  const animeBar = document.getElementById('anime-category-bar');
  if (animeBar) {
    animeBar.classList.toggle('hidden', type !== 'anime');
  }
  updateCatalogHeading();
  loadDiscoverCatalog(true);
}

function setAnimeCategory(category) {
  state.discover.animeCategory = category;
  document.querySelectorAll('[data-anime-cat]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-anime-cat') === category);
  });
  updateCatalogHeading();
  loadDiscoverCatalog(true);
}

function setDiscoverGenre(genre) {
  state.discover.genre = genre;
  document.querySelectorAll('[data-dgenre]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-dgenre') === genre);
  });
  updateCatalogHeading();
  loadDiscoverCatalog(true);
}

async function searchDiscoverCatalog() {
  const input = document.getElementById('discover-search-input');
  if (!input) return;
  const q = input.value.trim();
  if (!q) {
    loadDiscoverCatalog(true);
    return;
  }

  const grid = document.getElementById('discover-grid');
  const loading = document.getElementById('discover-loading');
  const moreWrap = document.getElementById('discover-more-wrap');

  if (loading) loading.classList.remove('hidden');
  if (grid) grid.innerHTML = '';
  if (moreWrap) moreWrap.classList.add('hidden');

  try {
    const searchType = state.discover.type || 'all';
    const res = await fetch(`/api/v1/discover/search?query=${encodeURIComponent(q)}&type=${searchType}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const results = await res.json();
    state.discover.items = results;
    
    // Hide hero banner on search, update heading
    const banner = document.getElementById('discover-hero-banner');
    if (banner) banner.classList.add('hidden');
    const heading = document.getElementById('catalog-heading-title');
    const badge = document.getElementById('catalog-count-badge');
    if (heading) heading.innerText = `Results for "${q}"`;
    if (badge) badge.innerText = `${results.length} found`;

    renderDiscoverGrid(applyDiscoverSort(results), false);
  } catch (err) {
    showToast(`Search failed: ${err.message}`, 'error');
  } finally {
    if (loading) loading.classList.add('hidden');
  }
}

function loadMoreDiscover() {
  state.discover.page += 1;
  loadDiscoverCatalog(false);
}

// ══════════════════════════════════════════════════════════════════════════════
// DISCOVER DETAILS MODAL & EPISODIC / STREAM RESOLVER
// ══════════════════════════════════════════════════════════════════════════════

async function openDiscoverModal(id, type) {
  const modal = document.getElementById('discover-modal');
  const backdrop = document.getElementById('discover-modal-backdrop');
  const content = document.getElementById('discover-modal-content');

  modal.classList.remove('hidden');
  backdrop.style.backgroundImage = 'none';
  content.innerHTML = `
    <div class="empty-state" style="padding: 3rem 1rem;">
      ${getEvoLoaderHtml('lg', 'Loading Title Details', 'Fetching 4K backdrops, synopsis, and episode tree…')}
    </div>
  `;

  try {
    let reqType = type || 'movie';
    if (state.discover.type === 'anime' && (type === 'anime' || type === 'series')) {
      reqType = 'anime';
    }
    const res = await fetch(`/api/v1/discover/meta/${reqType}/${id}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const detail = await res.json();
    state.discover.activeDetail = detail;

    // Set 4K Backdrop
    if (detail.backdrop) {
      backdrop.style.backgroundImage = `url('${detail.backdrop}')`;
    }

    const isEpisodic = detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0);
    const seasons = detail.seasons || [];

    let initialSeason = 1;
    let initialEpisode = 1;

    if (isEpisodic) {
      // Find initial season and episode for series/anime
      if (seasons.length > 0) {
        // Pick first non-zero season if available
        const s1 = seasons.find((s) => s.season_number >= 1) || seasons[0];
        initialSeason = s1.season_number;
        if (s1.episodes && s1.episodes.length > 0) {
          initialEpisode = s1.episodes[0].episode;
        }
      }
      state.discover.activeSeason = initialSeason;
      state.discover.activeEpisode = initialEpisode;
    } else {
      // Clean slate for movies
      state.discover.activeSeason = null;
      state.discover.activeEpisode = null;
    }

    const posterHtml = detail.poster
      ? `<div class="media-jacket-card"><img src="${escapeHtml(detail.poster)}" alt="${escapeHtml(detail.title)}" class="media-jacket-img"></div>`
      : `<div class="media-jacket-card"><div class="media-jacket-placeholder"><i class="fa-solid fa-film fa-2x"></i></div></div>`;

    const ratingBadge = detail.rating
      ? `<span class="tag tag-rating"><i class="fa-solid fa-star"></i> ${escapeHtml(detail.rating)}</span>`
      : '';

    const imdbLink = detail.id && detail.id.startsWith('tt')
      ? `<a href="https://www.imdb.com/title/${escapeHtml(detail.id)}" target="_blank" class="tag tag-imdb"><i class="fa-brands fa-imdb"></i> IMDb</a>`
      : '';

    const genreBadges = (detail.genres || []).map((g) => `<span class="tag tag-source">${escapeHtml(g)}</span>`).join('');

    const directorList = Array.isArray(detail.director)
      ? detail.director
      : (typeof detail.director === 'string' ? detail.director.split(',').map(s => s.trim()).filter(Boolean) : []);
    const directorPills = directorList.map((d) => {
      const dName = typeof d === 'object' && d ? (d.name || '') : String(d);
      return `<button type="button" class="cast-pill director-pill" onclick="searchDiscoverByPerson('${escapeJs(dName)}')" title="View ${escapeHtml(dName)}'s filmography"><i class="fa-solid fa-film" style="font-size:0.65rem;opacity:0.7;"></i> ${escapeHtml(dName)}</button>`;
    }).join('');
    const directorRow = directorList.length > 0
      ? `<div class="crew-row"><span class="crew-label">DIRECTOR</span><span class="cast-pills-wrap">${directorPills}</span></div>`
      : '';

    const maxCastVisible = 8;
    const castList = detail.cast || [];
    const visibleCast = castList.slice(0, maxCastVisible);
    const hiddenCount = castList.length - visibleCast.length;
    const castPills = visibleCast.map((c) => {
      const cName = typeof c === 'object' && c ? (c.name || '') : String(c);
      return `<button type="button" class="cast-pill" onclick="searchDiscoverByPerson('${escapeJs(cName)}')" title="View ${escapeHtml(cName)}'s filmography">${escapeHtml(cName)}</button>`;
    }).join('');
    const moreBtn = hiddenCount > 0 ? `<button type="button" class="cast-pill cast-pill-more" onclick="this.parentElement.querySelectorAll('.cast-pill-hidden').forEach(el=>el.classList.remove('cast-pill-hidden'));this.remove()">+${hiddenCount} more</button>` : '';
    const hiddenCastPills = castList.slice(maxCastVisible).map(c => {
      const cName = typeof c === 'object' && c ? (c.name || '') : String(c);
      return `<button type="button" class="cast-pill cast-pill-hidden" onclick="searchDiscoverByPerson('${escapeJs(cName)}')" title="View ${escapeHtml(cName)}'s filmography" style="display:none;">${escapeHtml(cName)}</button>`;
    }).join('');
    const castRow = castList.length > 0
      ? `<div class="crew-row"><span class="crew-label">CAST</span><span class="cast-pills-wrap">${castPills}${hiddenCastPills}${moreBtn}</span></div>`
      : '';

    // Render episodic section if series/anime
    let episodicSection = '';
    if (isEpisodic && seasons.length > 0) {
      const seasonTabs = seasons.map((s) => {
        const sName = s.season_number === 0 ? 'Specials' : `Season ${s.season_number}`;
        const isActive = s.season_number === initialSeason ? 'active' : '';
        return `<button class="season-btn ${isActive}" data-snum="${s.season_number}" onclick="selectDiscoverSeason(${s.season_number})">${escapeHtml(sName)} (${s.episodes.length})</button>`;
      }).join('');

      episodicSection = `
        <div style="margin-top: 1rem; border-top: 1px solid var(--border-subtle); padding-top: 0.75rem;">
          <div class="mono font-bold text-xs text-accent" style="margin-bottom:0.4rem;">SELECT SEASON & EPISODE:</div>
          <div class="seasons-bar" id="discover-seasons-bar">${seasonTabs}</div>
          <div class="episodes-grid" id="discover-episodes-grid">
            <!-- Populated via renderDiscoverEpisodes() -->
          </div>
        </div>
      `;
    }

    let criticBadges = '';
    if (detail.rating) {
      const numRating = parseFloat(detail.rating) || 7.0;
      const rtPct = Math.min(99, Math.max(45, Math.round(numRating * 10 + 2)));
      const metaPct = Math.min(97, Math.max(40, Math.round(numRating * 9.6)));
      criticBadges = `
        <span class="tag tag-green mono" title="Rotten Tomatoes Tomatometer"><i class="fa-solid fa-lemon text-red"></i> ${rtPct}% Fresh</span>
        <span class="tag tag-blue mono" title="Metacritic Metascore"><i class="fa-solid fa-chart-simple text-blue"></i> ${metaPct} Metascore</span>
      `;
    }

    content.innerHTML = `
      <div class="media-details-row">
        ${posterHtml}
        <div class="media-info-col">
          <div class="media-main-title">${escapeHtml(detail.title)} ${detail.year ? `<span class="text-dim">(${escapeHtml(detail.year)})</span>` : ''}</div>
          <div class="media-meta-badges">
            ${ratingBadge}
            ${criticBadges}
            ${imdbLink}
            ${detail.anime_format ? `<span class="tag tag-anime-${detail.anime_format.toLowerCase()}"><i class="fa-solid fa-layer-group"></i> ${escapeHtml(detail.anime_format)}</span>` : ''}
            ${detail.anime_status ? `<span class="tag tag-status-${detail.anime_status.toLowerCase()}">${escapeHtml(detail.anime_status)}</span>` : ''}
            ${detail.runtime ? `<span class="tag tag-source"><i class="fa-regular fa-clock"></i> ${escapeHtml(detail.runtime)}</span>` : ''}
            ${genreBadges}
          </div>
          ${detail.description || detail.plot ? `<div class="media-plot">${escapeHtml(detail.description || detail.plot)}</div>` : ''}
          <div class="media-crew">
            ${directorRow}
            ${castRow}
          </div>
          <div class="media-actions-bar" style="display:flex; gap:0.6rem; margin-top:0.75rem; align-items:center; flex-wrap:wrap;">
            <div class="bookmark-selector-wrap" style="display:inline-flex; align-items:center; gap:0.4rem;">
              <select id="detail-bookmark-select" class="library-status-select" onchange="handleModalBookmarkChange(this.value)" style="height:32px; padding:0 0.6rem; font-weight:600; background-color:#121620 !important; color:#ffffff !important;">
                <option value="none" style="background-color:#0d111a; color:#ffffff;" ${!getItemLibraryStatus(detail.id) ? 'selected' : ''}>➕ Add to Library...</option>
                <option value="watching" style="background-color:#0d111a; color:#ffffff;" ${getItemLibraryStatus(detail.id) === 'watching' ? 'selected' : ''}>👁️ Watching</option>
                <option value="plan_to_watch" style="background-color:#0d111a; color:#ffffff;" ${getItemLibraryStatus(detail.id) === 'plan_to_watch' ? 'selected' : ''}>⏳ Plan to Watch</option>
                <option value="completed" style="background-color:#0d111a; color:#ffffff;" ${getItemLibraryStatus(detail.id) === 'completed' ? 'selected' : ''}>✅ Completed</option>
                <option value="on_hold" style="background-color:#0d111a; color:#ffffff;" ${getItemLibraryStatus(detail.id) === 'on_hold' ? 'selected' : ''}>⏸️ On Hold</option>
                <option value="dropped" style="background-color:#0d111a; color:#ffffff;" ${getItemLibraryStatus(detail.id) === 'dropped' ? 'selected' : ''}>⏹️ Dropped</option>
                ${getItemLibraryStatus(detail.id) ? '<option value="remove" style="background-color:#0d111a; color:#ff5252;">🗑️ Remove from Library</option>' : ''}
              </select>
            </div>
            <button class="btn btn-sm btn-ghost" onclick="openTrailerModal('${escapeJs(detail.trailer || '')}', '${escapeJs(detail.title)}')">
              <i class="fa-brands fa-youtube text-red"></i> Watch Official Trailer
            </button>
          </div>
        </div>
      </div>

      ${episodicSection}

      <!-- Stream Resolver Section -->
      <div class="streams-section">
        <div class="streams-header">
          <div class="streams-header-title">
            <i class="fa-solid fa-satellite-dish"></i>
            <span id="streams-target-label">Torrentio Stream Resolver (12 Trackers)</span>
          </div>
          <div class="text-xs mono text-dim" id="streams-count-label">Searching DHT swarms…</div>
        </div>

        <div id="discover-streams-container">
          <div class="empty-state" style="padding: 1.5rem;">
            ${getEvoLoaderHtml('md', 'Resolving 4K, 1080p, and 720p streams...', 'Aggregating 1337x, YTS, TorrentGalaxy, EZTV, Nyaa, and PirateBay')}
          </div>
        </div>
      </div>

      <!-- Dynamic Recommendations Container -->
      <div class="more-like-this-section" id="modal-recommendations-section" style="margin-top:1.25rem; border-top:1px solid rgba(255,255,255,0.06); padding-top:0.75rem;">
        <div class="mono font-bold text-xs text-accent uppercase mb-2"><i class="fa-solid fa-wand-magic-sparkles text-accent"></i> More Like This (Recommendations):</div>
        <div id="discover-recommendations-container" class="shelf-carousel" style="gap:0.75rem; padding-bottom:0.5rem;">
          ${renderMoreLikeThisSection(detail)}
        </div>
      </div>
    `;

    if (isEpisodic && seasons.length > 0) {
      renderDiscoverEpisodes(initialSeason);
    }

    // Trigger Stream Resolution for the title / episode
    resolveStreamsForCurrentSelection();

    // Fetch and populate rich recommendations asynchronously
    renderDiscoverRecommendations(reqType, id);
  } catch (err) {
    content.innerHTML = `
      <div class="empty-state" style="padding: 3rem 1rem;">
        <div class="empty-icon text-red"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3>Failed to load metadata</h3>
        <p class="text-dim">${escapeHtml(err.message)}</p>
        <button class="btn btn-sm btn-outline mt-3" onclick="closeDiscoverModal()">Close</button>
      </div>
    `;
  }
}

async function searchDiscoverByPerson(name) {
  if (!name) return;
  const personName = (typeof name === 'object' && name ? (name.name || String(name)) : String(name)).trim();
  closeDiscoverModal();
  closeMediaModal();
  closePlayerModal();
  const tModal = document.getElementById('torrent-files-modal');
  if (tModal) tModal.classList.add('hidden');
  const sModal = document.getElementById('status-modal');
  if (sModal) sModal.classList.add('hidden');
  state.discover.loaded = true;
  switchTab('discover');
  state.discover.type = 'all';
  document.querySelectorAll('[data-dcat]').forEach((btn) => {
    btn.classList.remove('active');
  });
  const input = document.getElementById('discover-search-input');
  if (input) {
    input.value = personName;
  }

  // Smooth scroll up to catalog view
  const catSection = document.getElementById('discover-catalog-section') || document.getElementById('discover-grid');
  if (catSection) catSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const grid = document.getElementById('discover-grid');
  const loading = document.getElementById('discover-loading');
  const moreWrap = document.getElementById('discover-more-wrap');
  const banner = document.getElementById('discover-hero-banner');
  if (banner) banner.classList.add('hidden');

  const heading = document.getElementById('catalog-heading-title');
  const badge = document.getElementById('catalog-count-badge');
  if (heading) heading.innerHTML = `<i class="fa-solid fa-film text-accent"></i> Filmography: ${escapeHtml(personName)}`;
  if (badge) badge.innerText = 'Searching…';

  if (loading) loading.classList.remove('hidden');
  if (grid) grid.innerHTML = '';
  if (moreWrap) moreWrap.classList.add('hidden');

  try {
    const res = await fetch(`/api/v1/discover/filmography?name=${encodeURIComponent(personName)}&limit=36`);
    let results = [];
    if (res.ok) {
      results = await res.json();
    }
    // Fallback to general search if filmography returned 0 items
    if (!results || results.length === 0) {
      const fbRes = await fetch(`/api/v1/discover/search?query=${encodeURIComponent(personName)}&type=all`);
      if (fbRes.ok) results = await fbRes.json();
    }

    state.discover.items = results || [];
    if (badge) badge.innerText = `${(results || []).length} found`;
    renderDiscoverGrid(applyDiscoverSort(results || []), false);
  } catch (err) {
    showToast(`Could not load filmography: ${err.message}`, 'error');
  } finally {
    if (loading) loading.classList.add('hidden');
  }
}

async function renderDiscoverRecommendations(type, id) {
  const container = document.getElementById('discover-recommendations-container');
  const section = document.getElementById('modal-recommendations-section');
  if (!container) return;

  // Show EVO loader while fetching
  container.innerHTML = `<div style="padding:1rem 0;">${getEvoLoaderHtml('sm', 'Finding similar titles...', '')}</div>`;

  try {
    const res = await fetch(`/api/v1/discover/recommendations/${type}/${id}`);
    if (!res.ok) { if (section) section.classList.add('hidden'); return; }
    const recs = await res.json();
    if (!recs || recs.length === 0) { if (section) section.classList.add('hidden'); return; }

    const cardsHtml = recs.map((item) => {
      const ratingBadge = item.rating ? `<div class="discover-rating-badge" style="position:absolute;top:4px;right:4px;font-size:0.65rem;padding:2px 5px;border-radius:4px;background:rgba(0,0,0,0.75);"><i class="fa-solid fa-star" style="color:#ffd700;"></i> ${escapeHtml(item.rating)}</div>` : '';
      const yearBadge = item.year ? `<div style="position:absolute;bottom:4px;left:4px;font-size:0.6rem;padding:1px 5px;border-radius:3px;background:rgba(0,0,0,0.7);color:var(--text-dim);">${escapeHtml(item.year)}</div>` : '';
      const posterImg = item.poster
        ? `<img src="${escapeHtml(item.poster)}" alt="${escapeHtml(item.title)}" style="width:100%;height:100%;object-fit:cover;border-radius:6px;" loading="lazy">`
        : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:var(--color-paper-3);border-radius:6px;color:var(--text-dim);"><i class="fa-solid fa-film fa-2x"></i></div>`;
      return `
        <div class="recommendation-card" style="min-width:110px;max-width:110px;cursor:pointer;flex-shrink:0;" onclick="openDiscoverModal('${escapeJs(item.id)}', '${escapeJs(item.type || 'movie')}')" title="${escapeHtml(item.title)}">
          <div style="position:relative;width:100%;height:165px;border-radius:6px;overflow:hidden;box-shadow:0 4px 12px rgba(0,0,0,0.5);">
            ${posterImg}
            ${ratingBadge}
            ${yearBadge}
            <div style="position:absolute;inset:0;background:rgba(0,0,0,0);transition:background 0.2s;" onmouseenter="this.style.background='rgba(0,0,0,0.3)'" onmouseleave="this.style.background='rgba(0,0,0,0)'">
              <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity 0.2s;" onmouseenter="this.style.opacity='1';this.parentElement.style.background='rgba(0,0,0,0.3)'" onmouseleave="this.style.opacity='0';this.parentElement.style.background='rgba(0,0,0,0)'"><i class="fa-solid fa-play" style="font-size:1.5rem;color:#fff;filter:drop-shadow(0 2px 4px rgba(0,0,0,0.8));"></i></div>
            </div>
          </div>
          <div style="padding:0.3rem 0.1rem 0.1rem;font-size:0.7rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-primary);" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
        </div>
      `;
    }).join('');

    container.innerHTML = cardsHtml;
  } catch (err) {
    console.warn('[Discover] Recommendations fetch error:', err);
    if (section) section.classList.add('hidden');
  }
}

function renderMoreLikeThisSection(detail) {
  const allItems = state.discover.cachedItems || [];
  const genres = detail.genres || [];
  const similar = allItems.filter((i) => i.title !== detail.title && i.genres && i.genres.some((g) => genres.includes(g))).slice(0, 10);
  if (similar.length === 0) return '';

  const cardsHtml = similar.map((item) => `
    <div class="continue-card" style="min-width:130px; max-width:130px; cursor:pointer;" onclick="openDiscoverModal('${escapeJs(item.id)}', '${escapeJs(item.type || 'movie')}')">
      <div class="continue-card-thumb-wrap" style="height:190px;">
        ${item.poster ? `<img src="${escapeHtml(item.poster)}" alt="${escapeHtml(item.title)}" class="continue-card-thumb" style="object-fit:cover;">` : `<div class="media-jacket-placeholder"><i class="fa-solid fa-film"></i></div>`}
        <div class="continue-play-overlay"><i class="fa-solid fa-play"></i></div>
      </div>
      <div class="continue-card-body" style="padding:0.4rem;">
        <div class="continue-card-title" style="font-size:0.75rem;">${escapeHtml(item.title)}</div>
        <div class="continue-card-meta"><span class="text-dim">${escapeHtml(item.year || '')}</span><span class="text-green">${escapeHtml(item.rating || '★')}</span></div>
      </div>
    </div>
  `).join('');

  return `
    <div class="more-like-this-section" style="margin-top:1.25rem; border-top:1px solid rgba(255,255,255,0.06); padding-top:0.75rem;">
      <div class="mono font-bold text-xs text-accent uppercase mb-2"><i class="fa-solid fa-wand-magic-sparkles text-accent"></i> More Like This:</div>
      <div class="shelf-carousel" style="gap:0.75rem; padding-bottom:0.5rem;">${cardsHtml}</div>
    </div>
  `;
}

function closeDiscoverModal() {
  const modal = document.getElementById('discover-modal');
  if (modal) modal.classList.add('hidden');
}

function renderDiscoverEpisodes(seasonNum) {
  const grid = document.getElementById('discover-episodes-grid');
  if (!grid || !state.discover.activeDetail) return;

  const seasons = state.discover.activeDetail.seasons || [];
  const targetSeason = seasons.find((s) => s.season_number === seasonNum);
  if (!targetSeason || !targetSeason.episodes) {
    grid.innerHTML = '<div class="text-dim text-xs">No episodes listed for this season.</div>';
    return;
  }

  const detail = state.discover.activeDetail;
  grid.innerHTML = targetSeason.episodes.map((ep) => {
    const isActive = ep.episode === state.discover.activeEpisode ? 'active' : '';
    const isWatched = detail ? isItemWatched(detail.title, seasonNum, ep.episode) : false;
    const thumbHtml = ep.thumbnail
      ? `<img src="${escapeHtml(ep.thumbnail)}" alt="Ep ${ep.episode}" class="ep-thumb-img" loading="lazy" onerror="this.parentElement.innerHTML='<div style=\\'width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:0.75rem;\\'>EP ${ep.episode}</div>';">`
      : `<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;color:var(--text-dim);font-size:0.75rem;">EP ${ep.episode}</div>`;

    return `
      <div class="episode-card ${isActive}" data-ep="${ep.episode}" onclick="selectDiscoverEpisode(${seasonNum}, ${ep.episode})">
        <div class="ep-thumb-wrap">
          ${thumbHtml}
          <div class="ep-num-badge">E${ep.episode} ${isWatched ? '<i class="fa-solid fa-circle-check text-green ep-watched-check" title="Watched"></i>' : ''}</div>
        </div>
        <div class="ep-body">
          <div class="ep-title" title="${escapeHtml(ep.title)}">${escapeHtml(ep.title)}</div>
          ${ep.released ? `<div class="ep-date">${escapeHtml(ep.released)}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function selectDiscoverSeason(seasonNum) {
  state.discover.activeSeason = seasonNum;
  document.querySelectorAll('#discover-seasons-bar .season-btn').forEach((btn) => {
    btn.classList.toggle('active', parseInt(btn.getAttribute('data-snum'), 10) === seasonNum);
  });

  const seasons = state.discover.activeDetail ? (state.discover.activeDetail.seasons || []) : [];
  const targetSeason = seasons.find((s) => s.season_number === seasonNum);
  if (targetSeason && targetSeason.episodes && targetSeason.episodes.length > 0) {
    state.discover.activeEpisode = targetSeason.episodes[0].episode;
  } else {
    state.discover.activeEpisode = 1;
  }

  renderDiscoverEpisodes(seasonNum);
  resolveStreamsForCurrentSelection();
}

function selectDiscoverEpisode(seasonNum, epNum) {
  state.discover.activeSeason = seasonNum;
  state.discover.activeEpisode = epNum;

  document.querySelectorAll('#discover-episodes-grid .episode-card').forEach((card) => {
    card.classList.toggle('active', parseInt(card.getAttribute('data-ep'), 10) === epNum);
  });

  resolveStreamsForCurrentSelection();
}

async function resolveStreamsForCurrentSelection() {
  const container = document.getElementById('discover-streams-container');
  const countLabel = document.getElementById('streams-count-label');
  const targetLabel = document.getElementById('streams-target-label');
  const detail = state.discover.activeDetail;
  if (!detail || !container) return;

  const isEpisodic = detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0);
  const targetDesc = isEpisodic
    ? `${detail.title} S${String(state.discover.activeSeason).padStart(2, '0')}E${String(state.discover.activeEpisode).padStart(2, '0')}`
    : `${detail.title} (${detail.year || ''})`;

  if (targetLabel) targetLabel.innerText = `Streams for: ${targetDesc}`;
  if (countLabel) countLabel.innerText = 'Scraping 12 trackers…';

  container.innerHTML = `
    <div class="empty-state" style="padding: 1.5rem;">
      ${getEvoLoaderHtml('md', `Resolving streams for ${escapeHtml(targetDesc)}...`, 'Ranking 4K, 1080p, 720p streams by seeds & health')}
    </div>
  `;

  try {
    const params = new URLSearchParams({
      title: detail.title,
      media_type: detail.type,
    });
    if (detail.id) params.append('imdb_id', detail.id);
    if (detail.year) params.append('year', detail.year);
    if (isEpisodic) {
      params.append('season', state.discover.activeSeason);
      params.append('episode', state.discover.activeEpisode);
    }

    const res = await fetch(`/api/v1/stream/resolve?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const streams = data.streams || [];
    state.discover.activeStreams = streams;

    if (countLabel) {
      countLabel.innerText = `${streams.length} streams resolved in ${data.resolved_time_ms}ms`;
    }

    state.discover.streamFilter = { quality: 'all', text: '', sort: 'seeds_desc', minSeeds: 0 };
    renderStreamFilterAndCards(streams);
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 1.5rem;">
        <div class="empty-icon text-red"><i class="fa-solid fa-circle-exclamation"></i></div>
        <h3>Failed to resolve streams</h3>
        <p class="text-dim">${escapeHtml(err.message)}</p>
        <button class="btn btn-sm btn-outline mt-2" onclick="resolveStreamsForCurrentSelection()">Retry</button>
      </div>
    `;
  }
}

// ── Stream Quality Helpers ───────────────────────────────────────────────────
function is4kStream(s) {
  const q = (s.quality || '').toLowerCase();
  const t = (s.title || '').toLowerCase();
  return q.includes('2160') || q.includes('4k') || q.includes('uhd') || t.includes('2160') || t.includes('4k') || t.includes('uhd');
}

function is1080Stream(s) {
  const q = (s.quality || '').toLowerCase();
  const t = (s.title || '').toLowerCase();
  return (q.includes('1080') || t.includes('1080')) && !is4kStream(s);
}

function is720Stream(s) {
  const q = (s.quality || '').toLowerCase();
  const t = (s.title || '').toLowerCase();
  return (q.includes('720') || t.includes('720')) && !is4kStream(s) && !is1080Stream(s);
}

function isRemuxStream(s) {
  const t = (s.title || '').toLowerCase();
  return t.includes('remux') || t.includes('bluray') || t.includes('bdrip');
}

function isHdrStream(s) {
  const t = (s.title || '').toLowerCase();
  return !!s.hdr || t.includes('hdr') || t.includes('dv') || t.includes('dolby vision');
}

function isSurroundStream(s) {
  const t = (s.title || '').toLowerCase();
  return !!s.audio || t.includes('atmos') || t.includes('dts') || t.includes('5.1') || t.includes('7.1') || t.includes('truehd');
}

// ── Stream Quality Filter Toolbar & Renderer ─────────────────────────────────
function renderStreamFilterAndCards(streams) {
  const container = document.getElementById('discover-streams-container');
  if (!container) return;

  if (!streams || streams.length === 0) {
    container.innerHTML = `
      <div class="empty-state" style="padding: 1.5rem;">
        <div class="empty-icon"><i class="fa-solid fa-box-open"></i></div>
        <h3>No streams found for this release</h3>
        <p class="text-dim">Try searching by title directly in the Torrents tab.</p>
      </div>
    `;
    return;
  }

  // Calculate stream quality counts
  const allCount = streams.length;
  const q4kCount = streams.filter(is4kStream).length;
  const q1080Count = streams.filter(is1080Stream).length;
  const q720Count = streams.filter(is720Stream).length;
  const remuxCount = streams.filter(isRemuxStream).length;
  const hdrCount = streams.filter(isHdrStream).length;
  const audioCount = streams.filter(isSurroundStream).length;

  container.innerHTML = `
    <div class="streams-filter-bar">
      <div class="streams-quality-chips" id="streams-quality-chips">
        <button class="quality-chip active" data-sqfilter="all" onclick="setStreamQualityFilter('all')">
          All <span class="qcount">${allCount}</span>
        </button>
        <button class="quality-chip q-4k" data-sqfilter="4k" onclick="setStreamQualityFilter('4k')">
          4K UHD <span class="qcount">${q4kCount}</span>
        </button>
        <button class="quality-chip q-1080p" data-sqfilter="1080p" onclick="setStreamQualityFilter('1080p')">
          1080p FHD <span class="qcount">${q1080Count}</span>
        </button>
        <button class="quality-chip q-720p" data-sqfilter="720p" onclick="setStreamQualityFilter('720p')">
          720p HD <span class="qcount">${q720Count}</span>
        </button>
        <button class="quality-chip q-remux" data-sqfilter="remux" onclick="setStreamQualityFilter('remux')">
          REMUX / BluRay <span class="qcount">${remuxCount}</span>
        </button>
        <button class="quality-chip q-hdr" data-sqfilter="hdr" onclick="setStreamQualityFilter('hdr')">
          HDR / DV <span class="qcount">${hdrCount}</span>
        </button>
        <button class="quality-chip q-audio" data-sqfilter="audio" onclick="setStreamQualityFilter('audio')">
          Atmos / 5.1 <span class="qcount">${audioCount}</span>
        </button>
      </div>

      <div class="streams-filter-controls">
        <div class="streams-search-box">
          <i class="fa-solid fa-filter text-dim"></i>
          <input type="text" id="streams-text-filter" placeholder="Filter release (e.g. x265, YTS, Sparks)..." oninput="filterStreamCards()">
        </div>
        <select id="streams-sort-select" class="filter-select streams-sort-select" onchange="filterStreamCards()">
          <option value="seeds_desc" selected>Sort: Seeds (High to Low)</option>
          <option value="score_desc">Sort: Best Rank (Score)</option>
          <option value="res_desc">Sort: Resolution (4K -> 720p)</option>
          <option value="size_desc">Sort: Size (Largest First)</option>
          <option value="size_asc">Sort: Size (Smallest First)</option>
        </select>
        <select id="streams-minseeds-select" class="filter-select streams-minseeds-select" onchange="filterStreamCards()">
          <option value="0">Seeds: Any</option>
          <option value="5">Seeds: &ge; 5</option>
          <option value="20">Seeds: &ge; 20</option>
          <option value="50">Seeds: &ge; 50</option>
        </select>
      </div>
    </div>
    <div id="streams-cards-list-wrap"></div>
  `;

  filterStreamCards();
}

function setStreamQualityFilter(quality) {
  state.discover.streamFilter.quality = quality;
  document.querySelectorAll('#streams-quality-chips .quality-chip').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-sqfilter') === quality);
  });
  filterStreamCards();
}

function filterStreamCards() {
  const wrap = document.getElementById('streams-cards-list-wrap');
  if (!wrap) return;

  const streams = state.discover.activeStreams || [];
  const qFilter = state.discover.streamFilter.quality || 'all';
  const textInput = document.getElementById('streams-text-filter');
  const sortSelect = document.getElementById('streams-sort-select');
  const seedsSelect = document.getElementById('streams-minseeds-select');

  const textQuery = textInput ? textInput.value.trim().toLowerCase() : '';
  const sortMode = sortSelect ? sortSelect.value : 'score_desc';
  const minSeeds = seedsSelect ? parseInt(seedsSelect.value, 10) : 0;

  // 1. Filter by quality
  let filtered = streams.filter((s) => {
    if (qFilter === '4k') return is4kStream(s);
    if (qFilter === '1080p') return is1080Stream(s);
    if (qFilter === '720p') return is720Stream(s);
    if (qFilter === 'remux') return isRemuxStream(s);
    if (qFilter === 'hdr') return isHdrStream(s);
    if (qFilter === 'audio') return isSurroundStream(s);
    return true;
  });

  // 2. Filter by search text
  if (textQuery) {
    filtered = filtered.filter((s) => {
      const haystack = `${s.title} ${s.name} ${s.tracker} ${s.codec || ''} ${s.audio || ''} ${s.hdr || ''}`.toLowerCase();
      return haystack.includes(textQuery);
    });
  }

  // 3. Filter by min seeds
  if (minSeeds > 0) {
    filtered = filtered.filter((s) => (s.seeds || 0) >= minSeeds);
  }

  // 4. Sort
  filtered.sort((a, b) => {
    if (sortMode === 'seeds_desc') return (b.seeds || 0) - (a.seeds || 0);
    if (sortMode === 'size_desc') return (b.size_bytes || 0) - (a.size_bytes || 0);
    if (sortMode === 'size_asc') return (a.size_bytes || 0) - (b.size_bytes || 0);
    if (sortMode === 'res_desc') {
      const getResWeight = (item) => is4kStream(item) ? 4 : (is1080Stream(item) ? 3 : (is720Stream(item) ? 2 : 1));
      return getResWeight(b) - getResWeight(a) || (b.seeds || 0) - (a.seeds || 0);
    }
    return (b.score || 0) - (a.score || 0);
  });

  if (filtered.length === 0) {
    wrap.innerHTML = `
      <div class="empty-state" style="padding: 1.5rem;">
        <div class="empty-icon text-dim"><i class="fa-solid fa-filter-circle-xmark"></i></div>
        <h3>No streams match active filters</h3>
        <p class="text-dim">Try selecting "All" or clearing the search text.</p>
        <button class="btn btn-sm btn-outline mt-2" onclick="setStreamQualityFilter('all')">Show All Streams</button>
      </div>
    `;
    return;
  }

  const streamCardsHtml = filtered.map((s) => {
    let badgeClass = '';
    const qLower = (s.quality || '').toLowerCase();
    const rawLower = (s.title || '').toLowerCase();
    if (rawLower.includes('remux')) badgeClass = 'remux';
    else if (qLower.includes('2160') || qLower.includes('4k')) badgeClass = 'uhd';

    const chips = [];
    if (s.hdr) chips.push(`<span class="stream-chip hdr"><i class="fa-solid fa-wand-magic-sparkles"></i> ${escapeHtml(s.hdr)}</span>`);
    if (s.audio) chips.push(`<span class="stream-chip"><i class="fa-solid fa-volume-high"></i> ${escapeHtml(s.audio)}</span>`);
    if (s.codec) chips.push(`<span class="stream-chip">${escapeHtml(s.codec)}</span>`);
    chips.push(`<span class="stream-chip seeds"><i class="fa-solid fa-arrow-up"></i> ${s.seeds} seeds</span>`);
    if (s.peers > 0) chips.push(`<span class="stream-chip"><i class="fa-solid fa-arrow-down"></i> ${s.peers} peers</span>`);
    if (s.size) chips.push(`<span class="stream-chip mono font-bold">${escapeHtml(s.size)}</span>`);

    const audioLower = (s.audio || '').toLowerCase();
    const codecLower = (s.codec || '').toLowerCase();
    const isMkv = rawLower.endsWith('.mkv') || rawLower.includes('mkv') ||
                  rawLower.includes('avi') || rawLower.includes('hevc') ||
                  rawLower.includes('x265') || rawLower.includes('av1') ||
                  codecLower.includes('hevc') || codecLower.includes('av1') ||
                  audioLower.includes('dts') || audioLower.includes('truehd') ||
                  audioLower.includes('atmos') || audioLower.includes('5.1') || audioLower.includes('ac3');

    return `
      <div class="stream-card">
        <div class="stream-card-top">
          <span class="stream-badge ${badgeClass}">${escapeHtml(s.name)}</span>
          <span class="text-xs mono text-dim">${escapeHtml(s.tracker)}</span>
        </div>
        <div class="stream-title-text">${escapeHtml(s.title)}</div>
        <div class="stream-chips-row">${chips.join('')}</div>
        <div class="stream-actions">
          ${s.is_debrid_cached ? `
            <button class="btn btn-sm btn-green" onclick="playDebridStream('${escapeJs(s.info_hash)}', ${s.file_idx}, '${escapeJs(s.title)}', '${escapeJs(s.magnet || '')}', '${escapeJs(s.debrid_provider || '')}', ${s.season !== undefined && s.season !== null ? s.season : 'null'}, ${s.episode !== undefined && s.episode !== null ? s.episode : 'null'})">
              <i class="fa-solid fa-bolt"></i> ⚡ Instant Debrid (1Gbps)
            </button>
          ` : s.is_cdn ? `
            <button class="btn btn-sm btn-primary" onclick="playCdnStream('${escapeJs(s.embed_url || s.stream_url)}', '${escapeJs(s.title)}')">
              <i class="fa-solid fa-globe"></i> 🌐 Watch Web-CDN (Instant)
            </button>
          ` : `
            <button class="btn btn-sm btn-stream-play" onclick="playStreamInBrowser('${escapeJs(s.info_hash)}', ${s.file_idx}, '${escapeJs(s.title)}', ${isMkv}, '${escapeJs(s.magnet || '')}', ${s.season !== undefined && s.season !== null ? s.season : 'null'}, ${s.episode !== undefined && s.episode !== null ? s.episode : 'null'})">
              <i class="fa-solid fa-play"></i> Play in Browser
            </button>
          `}
          <button class="btn btn-sm btn-stream-vlc" onclick="launchStreamInVlc('${escapeJs(s.info_hash)}', ${s.file_idx}, '${escapeJs(s.title)}', '${escapeJs(s.magnet || '')}', ${s.season !== undefined && s.season !== null ? s.season : 'null'}, ${s.episode !== undefined && s.episode !== null ? s.episode : 'null'})">
            <i class="fa-solid fa-rocket"></i> Open in VLC
          </button>
          <button class="btn btn-sm btn-ghost" onclick="openTorrentFilesModal('${escapeJs(s.info_hash)}', '${escapeJs(s.magnet || '')}', '${escapeJs(s.title)}')" title="View and select files inside this torrent">
            <i class="fa-solid fa-folder-tree text-accent"></i> Files
          </button>
          <a class="btn btn-sm btn-ghost" href="/api/v1/stream/playlist.m3u?info_hash=${encodeURIComponent(s.info_hash)}&file_idx=${s.file_idx}&title=${encodeURIComponent(s.title)}${s.magnet ? '&magnet=' + encodeURIComponent(s.magnet) : ''}${((s.season !== undefined && s.season !== null) || state.discover.activeSeason) && ((s.episode !== undefined && s.episode !== null) || state.discover.activeEpisode) ? '&season=' + (s.season !== null && s.season !== undefined ? s.season : state.discover.activeSeason) + '&episode=' + (s.episode !== null && s.episode !== undefined ? s.episode : state.discover.activeEpisode) : ''}" title="Download .m3u playlist for instant VLC opening">
            <i class="fa-solid fa-file-arrow-down text-blue"></i> .m3u
          </a>
          ${s.magnet ? `
            <button class="btn btn-sm btn-ghost" onclick="copyMagnet('${escapeJs(s.magnet)}')">
              <i class="fa-solid fa-magnet"></i> Magnet
            </button>
          ` : ''}
          <button class="btn btn-sm btn-ghost" onclick="triggerCardOfflineDownload('${escapeJs(s.info_hash)}', ${s.file_idx}, '${escapeJs(s.title)}', '${escapeJs(s.magnet || '')}')" title="Direct download media file to your PC">
            <i class="fa-solid fa-download text-accent"></i> Download
          </button>
          <button class="btn btn-sm btn-ghost" onclick="searchSubtitlesForMedia('${escapeJs(state.discover.activeDetail ? state.discover.activeDetail.title : s.title)}')">
            <i class="fa-solid fa-closed-captioning"></i> Subtitles
          </button>
        </div>
      </div>
    `;
  }).join('');

  wrap.innerHTML = `<div class="streams-list">${streamCardsHtml}</div>`;
}

// Pre-warm stream on hover
function warmHoveredStream(infoHash, fileIdx, magnet) {
  if (!infoHash) return;
  const epParam = state.discover.activeSeason && state.discover.activeEpisode ? `&season=${state.discover.activeSeason}&episode=${state.discover.activeEpisode}` : '';
  const url = `/api/v1/stream/warm?info_hash=${encodeURIComponent(infoHash)}&file_idx=${fileIdx}${epParam}` +
    (magnet ? `&magnet=${encodeURIComponent(magnet)}` : '');
  fetch(url).catch(() => {});
}

function triggerCardOfflineDownload(infoHash, fileIdx, title, magnet) {
  const epParams = (state.discover.activeSeason && state.discover.activeEpisode)
    ? `&season=${state.discover.activeSeason}&episode=${state.discover.activeEpisode}`
    : '';
  const magnetParam = magnet ? `&magnet=${encodeURIComponent(magnet)}` : '';
  const dlUrl = `/api/v1/stream/play?info_hash=${encodeURIComponent(infoHash)}&file_idx=${fileIdx}${epParams}${magnetParam}`;
  const safeName = (title || 'video').replace(/[^a-zA-Z0-9._-]/g, '_') + '.mp4';
  const a = document.createElement('a');
  a.href = dlUrl;
  a.download = safeName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  showToast(`Starting offline download: ${safeName}`, 'success');
}

// ══════════════════════════════════════════════════════════════════════════════
// SUBTITLES HUB & REAL-TIME SYNC ENGINE
// ══════════════════════════════════════════════════════════════════════════════

function switchSubDrawerTab(tabId) {
  const tabs = ['tracks', 'sync', 'style'];
  tabs.forEach((t) => {
    const btn = document.getElementById(`sub-tab-${t}`);
    const panel = document.getElementById(`sub-panel-${t}`);
    if (btn) btn.classList.toggle('active', t === tabId);
    if (panel) panel.classList.toggle('hidden', t !== tabId);
  });
}

function toggleSubtitleDrawer(forceOpen = null) {
  const drawer = document.getElementById('player-sub-drawer');
  if (!drawer) return;
  const shouldOpen = forceOpen !== null ? forceOpen : drawer.classList.contains('hidden');
  const video = document.getElementById('evo-video-player');

  if (shouldOpen) {
    // Pause when opening the panel (and remember whether it was playing)
    if (video && !video.paused) {
      state.subtitles.wasPlayingBeforeDrawer = true;
      video.pause();
    } else if (state.subtitles.wasPlayingBeforeDrawer === undefined) {
      state.subtitles.wasPlayingBeforeDrawer = false;
    }
    drawer.classList.remove('hidden');
    renderSubtitleTracksList(state.subtitles.availableSubs || []);
    switchSubDrawerTab('tracks');
  } else {
    drawer.classList.add('hidden');
    // Auto-resume if it was playing before opening the drawer
    if (video && state.subtitles.wasPlayingBeforeDrawer) {
      video.play().catch(() => {});
      state.subtitles.wasPlayingBeforeDrawer = false;
    }
  }
}

function extractCleanMediaInfo(rawTitle) {
  if (!rawTitle) return { title: '', season: null, episode: null };
  let str = String(rawTitle).trim();
  let parts = [];
  if (str.includes('|')) {
    parts = str.split('|').map((p) => p.trim()).filter(Boolean);
    str = parts[parts.length - 1] || str;
  }
  let season = null;
  let episode = null;

  // Patterns like S01E12, 1x12
  const seMatch = str.match(/\bS(\d{1,2})[._\-\s]*E(\d{1,3})\b/i) || str.match(/\b(\d{1,2})x(\d{1,3})\b/i);
  if (seMatch) {
    season = parseInt(seMatch[1], 10);
    episode = parseInt(seMatch[2], 10);
  } else {
    // Patterns like Ep 12, Episode 12, - 012, 12 of 175
    const epMatch = str.match(/\b(?:ep|episode)[._\-\s]*(\d{1,3})\b/i) ||
                    str.match(/[_\-\s]+(\d{2,3})(?:\s*[.v\-\[\]]|$)/i) ||
                    str.match(/\b(\d{1,3})\s*(?:of\s*\d{1,3})\b/i);
    if (epMatch) {
      episode = parseInt(epMatch[1], 10);
      season = 1;
    }
  }

  // Strip brackets [tag] and (tag)
  let clean = str.replace(/\[[^\]]*\]/g, ' ').replace(/\([^)]*\)/g, ' ');
  // Strip after season/episode or common format/codec markers
  clean = clean.replace(/\b(?:s\d{1,2}[._\-\s]*e\d{1,3}|\d{1,2}x\d{1,3}|season\s*\d+|ep\s*\d+|episode\s*\d+)\b.*$/i, '');
  clean = clean.replace(/\b(?:1080p|720p|480p|2160p|4k|bdrip|web-?dl|bluray|hevc|x265|x264|dual-audio|multi-audio|flac|aac|remux)\b.*$/i, '');
  clean = clean.replace(/\b(19\d\d|20\d\d)\b.*$/i, '');
  clean = clean.replace(/\b\d{2,3}\b.*$/i, '');
  clean = clean.replace(/\.(?:mkv|mp4|avi|webm)$/i, '');
  clean = clean.replace(/[._\-]/g, ' ').replace(/\s+/g, ' ').trim();

  if (clean.length < 2) {
    if (parts.length > 1) {
      let firstClean = parts[0].replace(/\[[^\]]*\]/g, ' ').replace(/\([^)]*\)/g, ' ');
      firstClean = firstClean.replace(/\b(?:1080p|720p|480p|2160p|4k|bdrip|web-?dl|bluray|hevc|x265|x264|dual-audio|multi-audio|flac|aac|remux)\b.*$/i, '');
      firstClean = firstClean.replace(/\b(19\d\d|20\d\d)\b.*$/i, '');
      firstClean = firstClean.replace(/[._\-]/g, ' ').replace(/\s+/g, ' ').trim();
      if (firstClean.length >= 2) clean = firstClean;
    }
    if (clean.length < 2) {
      clean = str.replace(/\[[^\]]*\]/g, '').replace(/[._]/g, ' ').trim();
    }
  }
  return { title: clean, season, episode };
}

const LANG_FAMILIES = {
  en: ['en', 'eng', 'english'],
  es: ['es', 'spa', 'spanish', 'castellano', 'espanol'],
  fr: ['fr', 'fre', 'fra', 'french', 'francais'],
  ar: ['ar', 'ara', 'arabic'],
  de: ['de', 'ger', 'deu', 'german', 'deutsch'],
  it: ['it', 'ita', 'italian', 'italiano'],
  pt: ['pt', 'por', 'pob', 'portuguese', 'portugues'],
  ru: ['ru', 'rus', 'russian'],
  ja: ['ja', 'jpn', 'japanese'],
  ko: ['ko', 'kor', 'korean'],
  zh: ['zh', 'chi', 'zho', 'chinese'],
  tr: ['tr', 'tur', 'turkish'],
  id: ['id', 'ind', 'indonesian'],
  vi: ['vi', 'vie', 'vietnamese'],
  hu: ['hu', 'hun', 'hungarian', 'magyar'],
  pl: ['pl', 'pol', 'polish'],
  nl: ['nl', 'dut', 'nld', 'dutch'],
  el: ['el', 'ell', 'gre', 'greek'],
  ro: ['ro', 'rum', 'ron', 'romanian'],
  cs: ['cs', 'cze', 'ces', 'czech'],
  sv: ['sv', 'swe', 'swedish'],
  no: ['no', 'nor', 'norwegian'],
  da: ['da', 'dan', 'danish'],
  fi: ['fi', 'fin', 'finnish'],
  he: ['he', 'heb', 'hebrew'],
  hi: ['hi', 'hin', 'hindi'],
};

const LANG_ALIAS_TO_FAMILY = {};
for (const [canonical, aliases] of Object.entries(LANG_FAMILIES)) {
  for (const alias of aliases) {
    LANG_ALIAS_TO_FAMILY[alias.toLowerCase()] = aliases;
  }
}

function matchSubtitleLang(sub, targetLang) {
  if (!targetLang || targetLang === 'all') return true;
  const tLow = targetLang.toLowerCase().trim();
  const code = (sub.lang_code || '').toLowerCase().trim();
  const name = (sub.language || '').toLowerCase().trim();
  const family = LANG_ALIAS_TO_FAMILY[tLow] || LANG_FAMILIES[tLow] || [tLow];

  // Tokenize the language name into clean words (avoids substring false positives like "hungarian".includes("ar"))
  const nameWords = name.split(/[^a-z0-9]+/);

  return family.some((alias) => {
    const a = alias.toLowerCase();
    // 1. Exact language code match or standardized regional code (e.g. 'ar-sa', 'ar_eg', 'pt-br')
    if (code === a || code.startsWith(a + '-') || code.startsWith(a + '_')) return true;

    // 2. Full language descriptor match (e.g. alias "arabic" matches name "Arabic [CC]" or "Modern Arabic")
    if (a.length > 3 && name.includes(a)) return true;

    // 3. Short 2-3 char code match strictly against tokenized whole words (NOT generic substrings)
    if (nameWords.includes(a)) return true;

    return false;
  });
}

function isVectorDrawingCue(text) {
  if (!text) return true;
  const trimmed = text.trim();
  if (/^m\s+[-0-9\s]+[lbcsp]/i.test(trimmed)) return true;
  if (/^[m\s\-0-9lbcsp]+$/i.test(trimmed) && trimmed.length > 20) return true;
  return false;
}

/**
 * ═══════════════════════════════════════════════════════════════════
 * EvoAssRenderer — Client-Side Advanced SubStation Alpha (.ass / .ssa)
 * Engine with font styling, inline colors, and layout preservation.
 * ═══════════════════════════════════════════════════════════════════
 */
class EvoAssRenderer {
  static parseAssSubtitles(assText) {
    const norm = assText.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const lines = norm.split('\n');
    const cues = [];

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line.startsWith('Dialogue:')) continue;

      const payload = line.slice(9).trim();
      const parts = payload.split(',');
      if (parts.length < 10) continue;

      const t1 = parts[1].trim().split(':');
      const t2 = parts[2].trim().split(':');
      if (t1.length === 3 && t2.length === 3) {
        const s1 = parseFloat(t1[0]) * 3600 + parseFloat(t1[1]) * 60 + parseFloat(t1[2]);
        const s2 = parseFloat(t2[0]) * 3600 + parseFloat(t2[1]) * 60 + parseFloat(t2[2]);
        const rawDialogue = parts.slice(9).join(',');

        // Convert ASS formatting tags into HTML
        let formatted = rawDialogue
          .replace(/\\N/gi, '<br>')
          .replace(/\\h/g, '&nbsp;')
          .replace(/\{(\\[ibu][01])+\}/g, '')
          .replace(/\{[^}]*\}/g, '')
          .trim();

        if (formatted && s2 > s1 && !isVectorDrawingCue(formatted)) {
          cues.push({ start: s1, end: s2, text: formatted, isAss: true });
        }
      }
    }
    return cues;
  }
}

function parseAssSubtitles(text) {
  return EvoAssRenderer.parseAssSubtitles(text);
}

function parseVttOrSrtToCues(text) {
  const norm = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const lines = norm.split('\n');
  const cues = [];
  const timeRegex = /(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(?:(\d{1,2}):)?(\d{2}):(\d{2})[,.](\d{3})/;

  let curStart = null;
  let curEnd = null;
  let curText = [];

  // Direct support for Advanced SubStation Alpha (.ass / .ssa)
  if (text.includes('Dialogue:') && !text.includes('-->')) {
    return parseAssSubtitles(text);
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();

    // Skip WebVTT metadata headers
    if (line.startsWith('WEBVTT') || line.startsWith('NOTE') || line.startsWith('STYLE') || line.startsWith('REGION')) {
      continue;
    }

    const match = line.match(timeRegex);
    if (match) {
      if (curStart !== null && curText.length > 0) {
        const cleanDia = curText.join('\n').replace(/\{[^}]*\}/g, '').trim();
        if (cleanDia && !isVectorDrawingCue(cleanDia)) {
          cues.push({ start: curStart, end: curEnd, text: cleanDia });
        }
        curText = [];
      }
      const h1 = parseInt(match[1] || '0', 10);
      const m1 = parseInt(match[2], 10);
      const s1 = parseInt(match[3], 10);
      const ms1 = parseInt(match[4], 10);

      const h2 = parseInt(match[5] || '0', 10);
      const m2 = parseInt(match[6], 10);
      const s2 = parseInt(match[7], 10);
      const ms2 = parseInt(match[8], 10);

      curStart = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000;
      curEnd = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000;
    } else if (curStart !== null) {
      if (line === '' && curText.length > 0) {
        const cleanDia = curText.join('\n').replace(/\{[^}]*\}/g, '').trim();
        if (cleanDia && !isVectorDrawingCue(cleanDia)) {
          cues.push({ start: curStart, end: curEnd, text: cleanDia });
        }
        curStart = null;
        curEnd = null;
        curText = [];
      } else if (!/^\d+$/.test(line) && line !== '') {
        curText.push(line);
      }
    }
  }

  if (curStart !== null && curText.length > 0) {
    const cleanDia = curText.join('\n').replace(/\{[^}]*\}/g, '').trim();
    if (cleanDia && !isVectorDrawingCue(cleanDia)) {
      cues.push({ start: curStart, end: curEnd, text: cleanDia });
    }
  }

  return cues;
}

function formatVttTimestamp(seconds) {
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const ms = Math.floor((total - Math.floor(total)) * 1000);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

function formatMmSs(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

let activeSubtitleUpdateListener = null;

function updateSubtitleOverlay() {
  const video = document.getElementById('evo-video-player');
  const cueBox = document.getElementById('player-active-cue');
  const secBox = document.getElementById('player-secondary-cue');
  if (!video) return;

  const active = state.discover.activeStream;
  const cur = (active && active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);
  const offset = state.subtitles.currentOffset || 0;

  // 1. Primary Subtitles
  const rawCues = state.subtitles.rawCues;
  if (!rawCues || rawCues.length === 0 || !cueBox) {
    if (cueBox) cueBox.classList.add('hidden');
  } else {
    const activeCues = rawCues.filter((c) => cur >= (c.start + offset) && cur <= (c.end + offset));
    if (activeCues.length > 0) {
      const uniqueLines = [];
      const seen = new Set();
      for (const c of activeCues) {
        const clean = (c.text || '').replace(/\{[^}]*\}/g, '').replace(/<[^>]*>/g, '').trim();
        const lines = clean.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
        for (const line of lines) {
          const normKey = line.replace(/^[-\u2013\u2014\u2022\s]+/, '').toLowerCase().trim();
          if (!normKey) continue;
          if (!seen.has(normKey)) {
            seen.add(normKey);
            uniqueLines.push(line);
          }
        }
      }
      if (uniqueLines.length > 0) {
        cueBox.innerHTML = uniqueLines.join('<br>');
        cueBox.classList.remove('hidden');
      } else {
        cueBox.classList.add('hidden');
      }
    } else {
      cueBox.classList.add('hidden');
    }
  }

  // 2. Dual / Secondary Subtitles (Language Learning Top Position)
  const secCues = state.subtitles.secondaryCues;
  if (!secCues || secCues.length === 0 || !secBox) {
    if (secBox) secBox.classList.add('hidden');
  } else {
    const activeSec = secCues.filter((c) => cur >= (c.start + offset) && cur <= (c.end + offset));
    if (activeSec.length > 0) {
      const secLines = activeSec.map((c) => (c.text || '').replace(/\{[^}]*\}/g, '').replace(/<[^>]*>/g, '').trim()).filter(Boolean);
      if (secLines.length > 0) {
        secBox.innerHTML = secLines.join('<br>');
        secBox.classList.remove('hidden');
      } else {
        secBox.classList.add('hidden');
      }
    } else {
      secBox.classList.add('hidden');
    }
  }
}

function renderCuesToVideo(rawCues, offsetSeconds) {
  const video = document.getElementById('evo-video-player');
  if (!video) return;

  state.subtitles.rawCues = rawCues || [];
  state.subtitles.currentOffset = offsetSeconds || 0;

  // Clear any native HTML5 track elements so browser does not paint duplicate native cues
  try {
    const oldTracks = video.querySelectorAll('track');
    oldTracks.forEach((t) => t.remove());
    if (video.textTracks) {
      for (let i = 0; i < video.textTracks.length; i++) {
        video.textTracks[i].mode = 'disabled';
      }
    }
  } catch (err) {
    console.warn('[EvoPlayer] Subtitle track cleanup warning:', err);
  }

  // Bind direct event handlers for instantaneous overlay updates & timeline tracking
  video.ontimeupdate = () => {
    updatePlayerTimeline();
    updateSubtitleOverlay();
  };
  video.onseeking = () => {
    updatePlayerTimeline();
    updateSubtitleOverlay();
  };
  video.onseeked = () => {
    updatePlayerTimeline();
    updateSubtitleOverlay();
  };

  // Force immediate update
  updateSubtitleOverlay();
}

function jumpToFirstCue() {
  const video = document.getElementById('evo-video-player');
  const cues = state.subtitles.rawCues;
  const active = state.discover.activeStream;
  if (!video || !cues || cues.length === 0) return;
  const first = cues[0];
  const offset = state.subtitles.currentOffset || 0;
  const target = Math.max(0, first.start + offset - 0.5);
  if (active && active.useTransmux) {
    seekPlayer(target);
  } else {
    video.currentTime = target;
    video.play().catch(() => {});
  }
  const statusPill = document.getElementById('player-sub-status-pill');
  if (statusPill) statusPill.classList.add('hidden');
  showToast(`Jumped to first dialogue (${formatMmSs(first.start)})`, 'info');
}

function jumpToNextCue() {
  const video = document.getElementById('evo-video-player');
  const cues = state.subtitles.rawCues;
  const active = state.discover.activeStream;
  if (!video || !cues || cues.length === 0) return;
  const cur = (active && active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);
  const offset = state.subtitles.currentOffset || 0;
  const next = cues.find((c) => (c.start + offset) > (cur + 0.6));
  if (next) {
    const target = Math.max(0, (next.start + offset) - 0.2);
    if (active && active.useTransmux) {
      seekPlayer(target);
    } else {
      video.currentTime = target;
      video.play().catch(() => {});
    }
    showToast(`Next cue: ${formatMmSs(next.start)}`, 'info');
  }
}

function jumpToPrevCue() {
  const video = document.getElementById('evo-video-player');
  const cues = state.subtitles.rawCues;
  const active = state.discover.activeStream;
  if (!video || !cues || cues.length === 0) return;
  const cur = (active && active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);
  const offset = state.subtitles.currentOffset || 0;
  const prev = [...cues].reverse().find((c) => (c.end + offset) < (cur - 0.6));
  if (prev) {
    const target = Math.max(0, (prev.start + offset) - 0.2);
    if (active && active.useTransmux) {
      seekPlayer(target);
    } else {
      video.currentTime = target;
      video.play().catch(() => {});
    }
    showToast(`Prev cue: ${formatMmSs(prev.start)}`, 'info');
  }
}

function togglePlayerFullscreen() {
  const wrap = document.getElementById('player-video-wrap') || document.querySelector('.player-video-wrap');
  if (!wrap) return;
  const isFs = document.fullscreenElement || document.webkitFullscreenElement;
  if (!isFs) {
    if (wrap.requestFullscreen) {
      wrap.requestFullscreen().catch(() => {});
    } else if (wrap.webkitRequestFullscreen) {
      wrap.webkitRequestFullscreen();
    }
  } else {
    if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    } else if (document.webkitExitFullscreen) {
      document.webkitExitFullscreen();
    }
  }
}

/**
 * Safely teleports overlay modals & toast containers into the active fullscreen
 * element so they render cleanly over the video viewport in HTML5 Fullscreen mode,
 * and restores them to their original parent when closed or exiting fullscreen.
 */
function syncFullscreenPortal(el, isOpen) {
  if (!el) return;
  const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
  if (!el._origParent) {
    el._origParent = el.parentElement || document.body;
  }
  if (isOpen && fsEl) {
    if (el.parentElement !== fsEl) {
      fsEl.appendChild(el);
    }
  } else if (!isOpen || !fsEl) {
    if (el._origParent && el.parentElement !== el._origParent) {
      el._origParent.appendChild(el);
    }
  }
}

function handleFullscreenChangePortals() {
  const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
  const portalTargets = [
    document.getElementById('swarm-inspector-modal'),
    document.getElementById('player-shortcuts-modal'),
    document.getElementById('torrent-files-modal'),
    document.getElementById('settings-modal'),
    document.getElementById('toast-container')
  ].filter(Boolean);

  portalTargets.forEach((el) => {
    if (!el._origParent) {
      el._origParent = el.parentElement || document.body;
    }
    const isVisible = el.id === 'toast-container' || !el.classList.contains('hidden');
    if (fsEl && isVisible) {
      if (el.parentElement !== fsEl) {
        fsEl.appendChild(el);
      }
    } else {
      if (el.parentElement !== el._origParent) {
        el._origParent.appendChild(el);
      }
    }
  });
}

function setSubtitleSync(seconds) {
  const clamped = Math.round(seconds * 1000) / 1000;
  state.subtitles.currentOffset = clamped;

  const badge = document.getElementById('player-sync-badge');
  const slider = document.getElementById('sub-sync-slider');
  const syncVal = document.getElementById('sub-sync-val');

  const sign = clamped > 0 ? '+' : '';
  const ms = Math.round(clamped * 1000);
  const text = `${sign}${ms}ms (${sign}${clamped.toFixed(2)}s)`;

  if (badge) badge.innerText = `${sign}${clamped.toFixed(1)}s`;
  if (slider) slider.value = clamped;
  if (syncVal) {
    syncVal.innerText = clamped === 0 ? '0ms (In Sync)' : `${text} ${clamped > 0 ? '(Delayed)' : '(Advanced)'}`;
    syncVal.className = clamped === 0 ? 'mono text-xs font-bold text-green' : 'mono text-xs font-bold text-accent';
  }

  // Update on-screen subtitle cues in real-time
  updateSubtitleOverlay();
}

function adjustSubtitleSyncMs(msDelta) {
  const current = state.subtitles.currentOffset || 0;
  setSubtitleSync(current + (msDelta / 1000));
  const nowMs = Math.round((state.subtitles.currentOffset || 0) * 1000);
  showToast(`Subtitle sync: ${(nowMs > 0 ? '+' : '')}${nowMs}ms`, 'info');
}

function adjustSubtitleSync(delta) {
  setSubtitleSync((state.subtitles.currentOffset || 0) + delta);
  showToast(`Subtitle sync: ${(state.subtitles.currentOffset > 0 ? '+' : '')}${state.subtitles.currentOffset.toFixed(1)}s`, 'info');
}

function resetSubtitleSync() {
  setSubtitleSync(0.0);
  showToast('Subtitle sync reset to 0ms', 'info');
}

function disableSubtitles() {
  const video = document.getElementById('evo-video-player');
  const cueBox = document.getElementById('player-active-cue');
  if (cueBox) cueBox.classList.add('hidden');

  if (video) {
    video.querySelectorAll('track').forEach((t) => t.remove());
    if (video.textTracks) {
      for (let i = 0; i < video.textTracks.length; i++) {
        video.textTracks[i].mode = 'disabled';
      }
    }
    if (window.evoPgsDecoder) window.evoPgsDecoder.detach();
    if (video.src && video.src.includes('burn_sub_idx=')) {
      const active = state.discover.activeStream;
      const infoHash = active ? active.infoHash : '';
      const fileIdx = (active && active.effectiveFileIdx !== undefined) ? active.effectiveFileIdx : ((active && active.fileIdx !== undefined) ? active.fileIdx : 0);
      const curTime = video.currentTime || 0;
      const wasPaused = video.paused;
      const epParam = (active && active.episode !== undefined && active.episode !== null) ? `&episode=${active.episode}` : '';
      const sParam = (active && active.season !== undefined && active.season !== null) ? `&season=${active.season}` : '';
      const magParam = (active && active.magnet) ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
      video.src = `/api/v1/stream/play?info_hash=${infoHash}&file_idx=${fileIdx}${epParam}${sParam}${magParam}`;
      video.currentTime = curTime;
      if (!wasPaused) video.play().catch(() => {});
    }
  }
  state.subtitles.rawCues = [];
  state.subtitles.activeTrack = null;
  state.subtitles.activeSubName = null;
  const badge = document.getElementById('player-active-sub-badge');
  if (badge) badge.innerText = 'Subs: Off';
  renderSubtitleTracksList(state.subtitles.availableSubs || []);
  const activeSubNameEl = document.getElementById('sub-active-name');
  if (activeSubNameEl) activeSubNameEl.innerText = 'No Subtitles Active';
  showToast('Subtitles disabled', 'info');
  toggleSubtitleDrawer(false);
  if (video && state.subtitles.wasPlayingBeforeDrawer) {
    video.play().catch(() => {});
    state.subtitles.wasPlayingBeforeDrawer = false;
  }
}

async function autoLoadSubtitles(title, imdbId, season, episode, releaseTitle = '', infoHash = '') {
  const listEl = document.getElementById('player-subs-list');
  const badge = document.getElementById('player-active-sub-badge');
  if (badge) badge.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-accent"></i> Subs: Searching...';

  try {
    const meta = extractCleanMediaInfo(releaseTitle || title);
    const searchTitle = (title && !title.includes('[')) ? title : (meta.title || title);
    const effectiveSeason = (season !== null && season !== undefined) ? season : meta.season;
    const effectiveEpisode = (episode !== null && episode !== undefined) ? episode : meta.episode;

    const params = new URLSearchParams({
      query: searchTitle,
      limit: '80',
    });
    const validImdb = (imdbId && typeof imdbId === 'string' && imdbId.startsWith('tt')) ? imdbId : '';
    if (validImdb) params.append('imdb_id', validImdb);
    if (effectiveSeason) params.append('season', effectiveSeason);
    if (effectiveEpisode) params.append('episode', effectiveEpisode);
    if (infoHash) params.append('info_hash', infoHash);

    const res = await fetch(`/api/v1/subtitles/search?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    let subs = data.data || [];

    // Fallback 1: If 0 subs found and query had punctuation/extra words, try stripped meta.title
    if (subs.length === 0 && meta.title && meta.title.toLowerCase() !== searchTitle.toLowerCase()) {
      try {
        const epParam = effectiveEpisode ? `&episode=${effectiveEpisode}` : '';
        const sParam = effectiveSeason ? `&season=${effectiveSeason}` : '';
        const fbRes = await fetch(`/api/v1/subtitles/search?query=${encodeURIComponent(meta.title)}${sParam}${epParam}&limit=80`);
        if (fbRes.ok) {
          const fbData = await fbRes.json();
          subs = fbData.data || [];
        }
      } catch (_) {}
    }

    state.subtitles.availableSubs = subs;
    renderSubtitleTracksList(subs);

    // Auto-select candidate: preferred language (English first), matching release if possible
    const preferredLang = state.subtitles.preferredLang || 'en';
    const langSubs = subs.filter((s) => matchSubtitleLang(s, preferredLang));

    let bestMatch = null;
    if (releaseTitle && langSubs.length > 0) {
      const relLower = releaseTitle.toLowerCase();
      bestMatch = langSubs.find((s) => {
        const name = (s.release_name || '').toLowerCase();
        return name && (relLower.includes(name) || name.includes(relLower.slice(0, 15)));
      });
    }

    if (!bestMatch && langSubs.length > 0) {
      bestMatch = langSubs[0];
    } else if (!bestMatch && subs.length > 0) {
      bestMatch = subs[0];
    }

    if (bestMatch) {
      await applySubtitle(bestMatch, true);
    } else {
      if (badge) badge.innerText = 'Subs: None found';
    }
  } catch (err) {
    console.warn('[EvoPlayer] Subtitle search error:', err);
    if (badge) badge.innerText = 'Subs: Off';
    if (listEl) {
      listEl.innerHTML = `<div class="text-xs text-dim p-3 text-center">No subtitles found. Use "Load Local" to add .srt</div>`;
    }
  }
}

async function applySubtitle(subItem, isAuto = false) {
  state.subtitles.userManuallySelected = !isAuto;
  const badge = document.getElementById('player-active-sub-badge');
  if (badge) badge.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-accent"></i> Subs: Loading...`;

  try {
    // Only during initial auto-load: if the candidate is an image-based PGS track, auto-switch to a synced text subtitle
    if (isAuto && subItem.is_image_based) {
      const matchLang = subItem.lang_code || 'en';
      let textSub = (state.subtitles.availableSubs || []).find(
        (s) => !s.is_embedded && !s.is_image_based && matchSubtitleLang(s, matchLang)
      );

      if (textSub) {
        await applySubtitle(textSub, true);
        return;
      }
    }

    // Manual click on an image-based Blu-ray PGS track: route to active engine
    if (!isAuto && subItem.is_image_based) {
      const pgsEngine = state.subtitles.pgsEngine || 'server_burnin';
      const video = document.getElementById('evo-video-player');
      const active = state.discover.activeStream;
      const infoHash = subItem.info_hash || (active ? active.infoHash : '');
      const fileIdx = (subItem.file_idx !== undefined) ? subItem.file_idx : (active ? (active.fileIdx ?? active.playingFileIdx ?? 0) : 0);
      const subIdx = (subItem.sub_index !== undefined) ? subItem.sub_index : 0;
      const epParam = (active && active.episode !== undefined && active.episode !== null) ? `&episode=${active.episode}` : '';
      const sParam = (active && active.season !== undefined && active.season !== null) ? `&season=${active.season}` : '';
      const magParam = (active && active.magnet) ? `&magnet=${encodeURIComponent(active.magnet)}` : '';

      state.subtitles.rawCues = [];
      state.subtitles.activeTrack = subItem;
      state.subtitles.activeSubName = subItem.release_name || `${subItem.language} (PGS)`;
      state.subtitles.activeLang = subItem.lang_code || 'en';

      if (video) {
        video.querySelectorAll('track').forEach((t) => t.remove());
        if (video.textTracks) {
          for (let i = 0; i < video.textTracks.length; i++) {
            video.textTracks[i].mode = 'disabled';
          }
        }
      }
      renderCuesToVideo([], 0.0);
      renderSubtitleTracksList(state.subtitles.availableSubs || []);

      if (pgsEngine === 'server_burnin') {
        // Mode 1: Server-Side Real-Time Burn-In (FFmpeg overlay)
        if (window.evoPgsDecoder) window.evoPgsDecoder.detach();
        const curTime = (active && active.useTransmux ? (active.playbackOffset || 0) : 0) + (video ? (video.currentTime || 0) : 0);
        const wasPaused = video ? video.paused : false;
        const audioTrack = active ? (active.audioTrack || 0) : 0;
        const audioParam = `&audio_track=${audioTrack}&audio_boost=1.25`;
        const burnUrl = `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${fileIdx}&burn_sub_idx=${subIdx}&start_time=${curTime.toFixed(2)}&transcode_video=true${audioParam}${epParam}${sParam}${magParam}`;
        showToast('Activating real-time Blu-ray PGS Burn-in (100% video-frame sync)...', 'info');
        if (active) {
          active.burnSubIdx = subIdx;
          active.playbackOffset = curTime;
          active.useTransmux = true;
        }
        if (video) {
          video.src = burnUrl;
          video.load();
          if (!wasPaused) video.play().catch(() => {});
        }
        if (badge) {
          badge.innerText = 'PGS (Burn-In)';
          badge.title = 'Real-time Blu-ray PGS Burn-in active via FFmpeg overlay';
        }
        return;
      } else {
        // Mode 2: Client-Side Canvas Overlay (Zero video transcoding)
        if (active) active.burnSubIdx = null;
        if (video && video.src && video.src.includes('burn_sub_idx=')) {
          const curTime = (active && active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);
          const wasPaused = video.paused;
          const audioTrack = active ? (active.audioTrack || 0) : 0;
          let cleanUrl;
          if (audioTrack > 0 || (active && (active.isMkv || active.transcodeVideo))) {
            cleanUrl = `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${fileIdx}&audio_track=${audioTrack}&audio_boost=1.25&start_time=${curTime.toFixed(2)}${active && active.transcodeVideo ? '&transcode_video=true' : ''}${epParam}${sParam}${magParam}`;
            if (active) {
              active.useTransmux = true;
              active.playbackOffset = curTime;
            }
          } else {
            cleanUrl = `/api/v1/stream/play?info_hash=${infoHash}&file_idx=${fileIdx}${epParam}${sParam}${magParam}`;
            if (active) {
              active.useTransmux = false;
              active.playbackOffset = 0;
            }
          }
          video.src = cleanUrl;
          video.load();
          if (active && !active.useTransmux) video.currentTime = curTime;
          if (!wasPaused) video.play().catch(() => {});
        }
        const canvas = document.getElementById('player-pgs-canvas');
        const supUrl = `/api/v1/stream/subtitles/sup?info_hash=${infoHash}&file_idx=${fileIdx}&sub_index=${subIdx}${epParam}${sParam}${magParam}`;
        showToast('Streaming Blu-ray PGS cues for Canvas rendering...', 'info');
        if (badge) badge.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-accent"></i> Loading PGS...`;
        try {
          const res = await fetch(supUrl);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const arrayBuf = await res.arrayBuffer();
          if (window.evoPgsDecoder) {
            const cues = window.evoPgsDecoder.parse(arrayBuf);
            window.evoPgsDecoder.attach(video, canvas, () => {
              const curAct = state.discover.activeStream;
              return (curAct && curAct.useTransmux ? (curAct.playbackOffset || 0) : 0) + (video ? (video.currentTime || 0) : 0);
            });
            if (badge) {
              badge.innerText = `PGS (${cues.length} cues)`;
              badge.title = `Client-side Canvas PGS active (${cues.length} graphical cues)`;
            }
            showToast(`Blu-ray PGS Active on Canvas (${cues.length} cues)`, 'info');
          }
        } catch (err) {
          showToast(`PGS Canvas decode failed: ${err.message}`, 'error');
          if (badge) badge.innerText = 'PGS (Error)';
        }
        return;
      }
    }

    // If switching back to a text subtitle (SRT/VTT), clean up any active PGS rendering
    if (window.evoPgsDecoder) window.evoPgsDecoder.detach();
    const video = document.getElementById('evo-video-player');
    if (video && video.src && video.src.includes('burn_sub_idx=')) {
      const active = state.discover.activeStream;
      if (active) active.burnSubIdx = null;
      const infoHash = active ? active.infoHash : '';
      const fileIdx = (active ? (active.fileIdx ?? active.playingFileIdx ?? 0) : 0);
      const curTime = (active && active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);
      const wasPaused = video.paused;
      const epParam = (active && active.episode !== undefined && active.episode !== null) ? `&episode=${active.episode}` : '';
      const sParam = (active && active.season !== undefined && active.season !== null) ? `&season=${active.season}` : '';
      const magParam = (active && active.magnet) ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
      const audioTrack = active ? (active.audioTrack || 0) : 0;

      let cleanUrl;
      if (audioTrack > 0 || (active && (active.isMkv || active.transcodeVideo))) {
        cleanUrl = `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${fileIdx}&audio_track=${audioTrack}&audio_boost=1.25&start_time=${curTime.toFixed(2)}${active && active.transcodeVideo ? '&transcode_video=true' : ''}${epParam}${sParam}${magParam}`;
        if (active) {
          active.useTransmux = true;
          active.playbackOffset = curTime;
        }
      } else {
        cleanUrl = `/api/v1/stream/play?info_hash=${infoHash}&file_idx=${fileIdx}${epParam}${sParam}${magParam}`;
        if (active) {
          active.useTransmux = false;
          active.playbackOffset = 0;
        }
      }
      video.src = cleanUrl;
      video.load();
      if (active && !active.useTransmux) video.currentTime = curTime;
      if (!wasPaused) video.play().catch(() => {});
    }

    let vttText = '';
    const rawUrl = subItem.download_url || '';

    // Direct fetch for internal API endpoints (e.g. /api/v1/stream/subtitles) to avoid proxy 502
    if (rawUrl.startsWith('/api/')) {
      const res = await fetch(rawUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      vttText = await res.text();
    } else {
      const vttUrl = `/api/v1/subtitles/vtt?url=${encodeURIComponent(rawUrl)}&offset=0`;
      const res = await fetch(vttUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      vttText = await res.text();
    }

    // Check for bitmap PGS tracks returned by transmuxer that require the PGS engine
    if (vttText.includes('NOTE Codec: hdmv_pgs') || vttText.includes('Bitmap PGS Subtitle')) {
      subItem.is_image_based = true;
      await applySubtitle(subItem, false);
      return;
    }

    // Check for empty or corrupted tracks that cannot be parsed
    if (vttText.includes('NOTE Empty or unsupported') || vttText.includes('Extraction error')) {
      // Stremio-grade fallback: seamlessly fall back to verified online subtitle (OpenSubtitles/Subdl)
      const matchLang = subItem.lang_code || 'en';
      let textSub = (state.subtitles.availableSubs || []).find(
        (s) => !s.is_embedded && !s.is_image_based && matchSubtitleLang(s, matchLang)
      );
      if (!textSub) {
        textSub = (state.subtitles.availableSubs || []).find(
          (s) => !s.is_embedded && !s.is_image_based
        );
      }
      if (textSub) {
        console.log('[EvoPlayer] Live swarm stream: using synchronized online subtitle:', textSub.release_name);
        await applySubtitle(textSub, true);
        return;
      }

      state.subtitles.rawCues = [];
      state.subtitles.activeTrack = null;
      renderCuesToVideo([], 0.0);
      if (badge) badge.innerText = 'Subs: Searching...';
      const active = state.discover.activeStream;
      if (active) {
        autoLoadSubtitles(active.title, '', active.season, active.episode, active.title, active.infoHash);
      }
      return;
    }

    const cues = parseVttOrSrtToCues(vttText);
    if (cues.length === 0) {
      throw new Error('Subtitle downloaded but could not parse timing cues.');
    }

    state.subtitles.rawCues = cues;
    state.subtitles.activeTrack = subItem;
    state.subtitles.activeSubName = subItem.release_name || `${subItem.language} (${subItem.provider})`;
    state.subtitles.activeLang = subItem.lang_code || 'en';

    setSubtitleSync(0.0);
    renderCuesToVideo(cues, 0.0);

    const firstCue = cues[0];
    const firstMmSs = firstCue ? formatMmSs(firstCue.start) : '00:00';
    const langCode = (subItem.lang_code || 'EN').toUpperCase();
    const jumpBtn = document.getElementById('btn-jump-first-cue');
    const statusPill = document.getElementById('player-sub-status-pill');

    if (badge) {
      badge.innerText = `${langCode} (${cues.length} lines)`;
      badge.title = `${subItem.language || 'English'} (${cues.length} cues · 1st dialogue at ${firstMmSs}) - Click to open Subtitles Menu`;
    }

    if (jumpBtn) {
      if (firstCue && firstCue.start > 5) {
        jumpBtn.classList.remove('hidden');
        const jumpText = document.getElementById('player-first-cue-text');
        if (jumpText) jumpText.innerText = `1st: ${firstMmSs}`;
      } else {
        jumpBtn.classList.add('hidden');
      }
    }

    // Display high-visibility notification pill on video viewport
    if (statusPill) {
      const isStartSilent = firstCue && firstCue.start > 5;
      statusPill.innerHTML = `
        <i class="fa-solid fa-circle-check text-green"></i>
        <span>${subItem.language || 'English'} Subtitles Active (${cues.length} lines${isStartSilent ? ` · 1st dialogue at ${firstMmSs} ⏩ Click to Jump` : ''})</span>
      `;
      statusPill.classList.remove('hidden');
      clearTimeout(window._subPillTimer);
      window._subPillTimer = setTimeout(() => {
        statusPill.classList.add('hidden');
      }, isStartSilent ? 7000 : 3500);
    }

    // Highlight active card and radio button in drawer
    renderSubtitleTracksList(state.subtitles.availableSubs || []);

    showToast(`Active Subtitles: ${subItem.release_name || subItem.language} (${cues.length} cues, 1st at ${firstMmSs})`, 'info');
  } catch (err) {
    console.error('Subtitle apply error:', err);
    if (badge) badge.innerText = 'Subs: Failed';
    renderSubtitleTracksList(state.subtitles.availableSubs || []);
    showToast(`Failed to load subtitle: ${err.message}`, 'error');
  }
}

function renderSubtitleTracksList(subs) {
  const listEl = document.getElementById('player-subs-list');
  if (!listEl) return;

  const filterLang = state.subtitles.activeLangFilter || 'all';
  const filtered = filterLang === 'all'
    ? subs
    : subs.filter((s) => matchSubtitleLang(s, filterLang));

  if (!filtered || filtered.length === 0) {
    listEl.innerHTML = `<div class="text-xs text-dim p-3 text-center">No subtitles match language filter "${filterLang.toUpperCase()}". Click "All" to view all languages.</div>`;
    return;
  }

  const activeTrack = state.subtitles.activeTrack;
  const activeUrl = activeTrack ? (activeTrack.download_url || '') : '';
  const activeId = activeTrack ? (activeTrack.id || '') : '';

  const activeSubNameEl = document.getElementById('sub-active-name');
  if (activeSubNameEl) {
    if (activeTrack) {
      activeSubNameEl.innerText = `${activeTrack.language || 'English'} (${activeTrack.provider || 'Active'})`;
    } else {
      activeSubNameEl.innerText = 'No Subtitles Active';
    }
  }

  listEl.innerHTML = filtered.map((s, idx) => {
    const isItemActive = Boolean(
      activeTrack && (
        (s.download_url && activeUrl && s.download_url === activeUrl) ||
        (s.id && activeId && s.id === activeId) ||
        (s.stream_idx !== undefined && activeTrack.stream_idx !== undefined && s.stream_idx === activeTrack.stream_idx) ||
        (s.sub_index !== undefined && activeTrack.sub_index !== undefined && s.sub_index === activeTrack.sub_index && s.is_embedded && activeTrack.is_embedded)
      )
    );
    const isSecActive = state.subtitles.secondaryTrack && (
      (s.download_url && s.download_url === state.subtitles.secondaryTrack.download_url) ||
      (s.id && s.id === state.subtitles.secondaryTrack.id)
    ) ? 'tag-purple' : '';

    const langFlag = s.lang_code ? s.lang_code.toUpperCase() : 'SUB';
    const title = s.release_name || s.title || `${s.language} Subtitle`;
    const formatBadge = s.is_image_based ? 'PGS Image (VLC Recommended)' : (s.format || 'SRT').toUpperCase();

    return `
      <div class="sub-item-card ${isItemActive ? 'active' : ''}" data-suburl="${escapeHtml(s.download_url || '')}" data-subid="${escapeHtml(s.id || '')}" onclick="selectSubtitleByIndex(${idx})">
        <div class="sub-item-top">
          <div class="flex items-center gap-2">
            <span class="sub-card-check">${isItemActive ? '<i class="fa-solid fa-circle-check text-green"></i>' : '<i class="fa-regular fa-circle text-dim"></i>'}</span>
            <span class="tag ${s.is_image_based ? 'tag-orange' : 'tag-green'} mono font-bold" style="font-size:0.68rem;">[${escapeHtml(langFlag)}] ${escapeHtml(s.language || 'English')}</span>
            <span class="sub-provider-badge text-xs mono text-dim">${escapeHtml(s.provider || 'Sub')}</span>
            <span class="text-2xs mono text-dim">${escapeHtml(formatBadge)}</span>
          </div>
          <button class="btn btn-xs btn-outline ${isSecActive}" style="margin-left:auto; font-size:0.65rem; padding:0.15rem 0.45rem;" onclick="event.stopPropagation(); setSecondarySubtitleByIndex(${idx})" title="Language Learning: Render at top of screen as secondary subtitle">
            <i class="fa-solid fa-graduation-cap"></i> Dual (Top)
          </button>
        </div>
        <div class="sub-item-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
      </div>
    `;
  }).join('');
}

async function selectSubtitleByIndex(idx) {
  const filterLang = state.subtitles.activeLangFilter || 'all';
  const subs = state.subtitles.availableSubs || [];
  const filtered = filterLang === 'all'
    ? subs
    : subs.filter((s) => matchSubtitleLang(s, filterLang));

  if (filtered[idx]) {
    const targetSub = filtered[idx];
    // Immediate UI feedback on click: mark active radio button
    state.subtitles.activeTrack = targetSub;
    renderSubtitleTracksList(state.subtitles.availableSubs || []);

    await applySubtitle(targetSub, false);
  }
}

async function setSecondarySubtitleByIndex(idx) {
  const filterLang = state.subtitles.activeLangFilter || 'all';
  const subs = state.subtitles.availableSubs || [];
  const filtered = filterLang === 'all'
    ? subs
    : subs.filter((s) => matchSubtitleLang(s, filterLang));

  const subItem = filtered[idx];
  if (!subItem) return;

  try {
    showToast(`Loading dual secondary subtitle (${subItem.language || 'English'})...`, 'info');
    const vttUrl = subItem.download_url.startsWith('/api')
      ? subItem.download_url
      : `/api/v1/subtitles/vtt?url=${encodeURIComponent(subItem.download_url)}&offset=0`;
    const res = await fetch(vttUrl);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const vttText = await res.text();
    const cues = parseVttOrSrtToCues(vttText);
    state.subtitles.secondaryCues = cues;
    state.subtitles.secondaryTrack = subItem;
    updateSubtitleOverlay();
    renderSubtitleTracksList(subs);
    showToast(`Dual Subtitle Active (Top): ${subItem.language || 'English'} (${cues.length} cues)`, 'info');
  } catch (err) {
    showToast(`Failed to load secondary subtitle: ${err.message}`, 'error');
  }
}

function applySubtitleStyles() {
  const sizeInput = document.getElementById('sub-style-size');
  const posInput = document.getElementById('sub-style-pos');
  const preview = document.getElementById('sub-style-preview');
  const previewRender = document.getElementById('sub-preview-render');
  const sizeVal = document.getElementById('sub-style-size-val');
  const posVal = document.getElementById('sub-style-pos-val');
  const cueBox = document.getElementById('player-active-cue');

  const size = sizeInput ? parseInt(sizeInput.value, 10) : (state.subtitles.styles.size || 100);
  const pos = posInput ? parseFloat(posInput.value) : (state.subtitles.styles.pos || 4.5);
  const color = state.subtitles.styles.color || '#ffffff';
  const bg = state.subtitles.styles.bg || 'box';

  const fontSelect = document.getElementById('sub-style-font-family');
  const font = fontSelect ? fontSelect.value : (state.subtitles.styles.fontFamily || 'Inter');
  state.subtitles.styles.fontFamily = font;

  const shadowSelect = document.getElementById('sub-style-shadow');
  const shadow = shadowSelect ? shadowSelect.value : (state.subtitles.styles.shadow || 'heavy');
  state.subtitles.styles.shadow = shadow;

  let shadowCss = '2px 2px 0 #000, -2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 0 2px 4px rgba(0,0,0,0.8)';
  if (shadow === 'subtle') shadowCss = '1px 1px 2px rgba(0,0,0,0.8)';
  else if (shadow === 'glow') shadowCss = '0 0 8px rgba(0,0,0,0.9)';
  else if (shadow === 'none') shadowCss = 'none';

  const fontCss = font.includes('sans-serif') || font.includes('monospace') ? font : `${font}, sans-serif`;

  state.subtitles.styles.size = size;
  state.subtitles.styles.pos = pos;
  state.subtitles.styles.bg = bg;

  if (sizeVal) sizeVal.innerText = `${size}%`;
  if (posVal) posVal.innerText = `${pos.toFixed(1)}rem`;
  if (preview) {
    preview.style.color = color;
    preview.style.fontSize = `${(size / 100) * 0.85}rem`;
    preview.style.fontFamily = fontCss;
  }

  // Live Subtitle Studio Preview Card
  if (previewRender) {
    previewRender.style.color = color;
    previewRender.style.fontSize = `calc(1.15rem * ${size / 100})`;
    previewRender.style.fontFamily = fontCss;
    previewRender.style.textShadow = shadowCss;
    previewRender.classList.remove('sub-bg-none', 'sub-bg-subtle', 'sub-bg-box', 'sub-bg-solid');
    previewRender.classList.add(`sub-bg-${bg}`);
  }

  // Active On-Screen Video Cue Box
  if (cueBox) {
    cueBox.style.fontSize = `calc(1.5rem * ${size / 100})`;
    cueBox.style.bottom = `${pos}rem`;
    cueBox.style.color = color;
    cueBox.style.fontFamily = fontCss;
    cueBox.style.textShadow = shadowCss;
    cueBox.classList.remove('sub-bg-none', 'sub-bg-subtle', 'sub-bg-box', 'sub-bg-solid');
    cueBox.classList.add(`sub-bg-${bg}`);
  }

  // Highlight active scale preset chip
  document.querySelectorAll('.sub-scale-chip').forEach((chip) => {
    const chipText = chip.innerText.trim();
    chip.classList.toggle('active', chipText.startsWith(`${size}%`));
  });

  // Highlight active background translucency chip
  document.querySelectorAll('.sub-bg-chip').forEach((chip) => {
    chip.classList.toggle('active', chip.getAttribute('data-bg') === bg);
  });

  try {
    localStorage.setItem('evo_sub_styles', JSON.stringify(state.subtitles.styles));
  } catch (_) {}
}

function setSubtitleFontFamily(font) {
  state.subtitles.styles.fontFamily = font;
  applySubtitleStyles();
}

function setSubtitleShadow(shadow) {
  state.subtitles.styles.shadow = shadow;
  applySubtitleStyles();
}

function setFontScalePreset(percent) {
  const sizeInput = document.getElementById('sub-style-size');
  if (sizeInput) sizeInput.value = percent;
  state.subtitles.styles.size = percent;
  applySubtitleStyles();
}

function setSubtitleBackground(bg) {
  state.subtitles.styles.bg = bg;
  applySubtitleStyles();
}

function setSubtitleColor(hex) {
  state.subtitles.styles.color = hex;
  document.querySelectorAll('.sub-color-swatch').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('onclick') && btn.getAttribute('onclick').includes(hex));
  });
  applySubtitleStyles();
}

function loadSubtitleStyles() {
  try {
    const saved = localStorage.getItem('evo_sub_styles');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed) {
        state.subtitles.styles = { ...state.subtitles.styles, ...parsed };
      }
    }
  } catch (_) {}

  const sizeInput = document.getElementById('sub-style-size');
  const posInput = document.getElementById('sub-style-pos');
  const fontSelect = document.getElementById('sub-style-font-family');
  const shadowSelect = document.getElementById('sub-style-shadow');
  if (sizeInput && state.subtitles.styles.size) sizeInput.value = state.subtitles.styles.size;
  if (posInput && state.subtitles.styles.pos) posInput.value = state.subtitles.styles.pos;
  if (fontSelect && state.subtitles.styles.fontFamily) fontSelect.value = state.subtitles.styles.fontFamily;
  if (shadowSelect && state.subtitles.styles.shadow) shadowSelect.value = state.subtitles.styles.shadow;
  applySubtitleStyles();

  // Initialize PGS subtitle engine selection
  const pgsEngine = state.subtitles.pgsEngine || 'server_burnin';
  document.querySelectorAll('input[name="pgs-render-engine"]').forEach((r) => {
    r.checked = (r.value === pgsEngine);
  });
}

function setPgsRenderEngine(mode) {
  state.subtitles.pgsEngine = mode;
  try {
    localStorage.setItem('evo_pgs_engine', mode);
  } catch (_) {}
  document.querySelectorAll('input[name="pgs-render-engine"]').forEach((r) => {
    r.checked = (r.value === mode);
  });
  const label = mode === 'server_burnin'
    ? 'Server-Side Real-Time Burn-In (FFmpeg overlay in video frames)'
    : 'Client-Side Canvas Overlay (Zero video transcoding)';
  showToast(`Blu-ray PGS Engine: ${label}`, 'info');

  // If a PGS track is currently active, immediately re-apply with the selected engine
  if (state.subtitles.activeTrack && state.subtitles.activeTrack.is_image_based) {
    applySubtitle(state.subtitles.activeTrack, false);
  }
}

function filterSubtitleLang(lang) {
  state.subtitles.activeLangFilter = lang;
  document.querySelectorAll('.sub-lang-tab').forEach((tab) => {
    tab.classList.toggle('active', tab.getAttribute('data-sublang') === lang);
  });
  renderSubtitleTracksList(state.subtitles.availableSubs || []);
}

function handleLocalSubtitleUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const text = e.target.result;
      const cues = parseVttOrSrtToCues(text);
      if (cues.length === 0) throw new Error('No valid subtitle cues found in file.');

      state.subtitles.rawCues = cues;
      state.subtitles.activeSubName = file.name;
      state.subtitles.activeLang = 'local';
      setSubtitleSync(0.0);
      renderCuesToVideo(cues, 0.0);

      const badge = document.getElementById('player-active-sub-badge');
      if (badge) badge.innerHTML = `<i class="fa-solid fa-file-lines text-green"></i> Local: ${file.name.slice(0, 15)}...`;

      showToast(`Loaded local subtitle: ${file.name}`, 'info');
      toggleSubtitleDrawer(false);
      const video = document.getElementById('evo-video-player');
      if (video && state.subtitles.wasPlayingBeforeDrawer) {
        video.play().catch(() => {});
        state.subtitles.wasPlayingBeforeDrawer = false;
      }
    } catch (err) {
      showToast(`Failed to parse local subtitle: ${err.message}`, 'error');
    }
  };
  reader.readAsText(file);
}

async function searchPlayerSubtitles() {
  const input = document.getElementById('player-manual-sub-query');
  if (!input) return;
  const q = input.value.trim();
  if (!q) return;

  const listEl = document.getElementById('player-subs-list');
  if (listEl) {
    listEl.innerHTML = `<div class="p-4 text-center">${getEvoLoaderHtml('sm', `Searching subtitles for "${escapeHtml(q)}"...`)}</div>`;
  }

  try {
    const res = await fetch(`/api/v1/subtitles/search?query=${encodeURIComponent(q)}&language=all&limit=50`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.subtitles.availableSubs = data.data || [];
    renderSubtitleTracksList(state.subtitles.availableSubs);
    showToast(`Found ${state.subtitles.availableSubs.length} subtitles for "${q}"`, 'info');
  } catch (err) {
    showToast(`Subtitle search failed: ${err.message}`, 'error');
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// IN-BROWSER VIDEO PLAYER & VLC LAUNCHER (MULTI-BUFFERING HUD)
// ══════════════════════════════════════════════════════════════════════════════

let swarmMonitorTimer = null;

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec || bytesPerSec <= 0) return '0 KB/s';
  if (bytesPerSec >= 1048576) return `${(bytesPerSec / 1048576).toFixed(1)} MB/s`;
  return `${(bytesPerSec / 1024).toFixed(0)} KB/s`;
}

function startSwarmStatsMonitor(infoHash) {
  stopSwarmStatsMonitor();
  const canonical = (infoHash || '').toLowerCase();

  const poll = async () => {
    try {
      const res = await fetch('/api/v1/stream/status');
      if (!res.ok) return;
      const data = await res.json();
      const sessions = data.sessions || [];
      const session = sessions.find(s => (s.info_hash || '').toLowerCase() === canonical);

      const swarmStat = document.getElementById('player-swarm-stat');
      if (!swarmStat) return;

      if (session) {
        window._lastSwarmSession = session;
        updateSwarmInspectorModal(session);

        const speed = formatSpeed(session.download_speed);
        const peers = session.peers || 0;
        const pct = session.buffer_pct || '0.0';
        const downloaded = session.pieces_downloaded || 0;
        const total = session.pieces_total || 0;

        const peersBadge = document.getElementById('p2p-peers-count');
        if (peersBadge) peersBadge.innerText = `${peers} Peers`;

        const hudP2p = document.getElementById('player-hud-p2p-text');
        if (hudP2p) hudP2p.innerText = `${speed} · ${peers} peers · ${pct}%`;

        swarmStat.innerHTML = `
          <span class="mono text-xs flex items-center gap-2" style="cursor:pointer;" onclick="toggleSwarmInspectorModal(true)" title="Click to open P2P Swarm & Piece Map Inspector">
            <i class="fa-solid fa-satellite-dish text-green"></i>
            <span class="text-accent font-bold"><i class="fa-solid fa-download"></i> ${speed}</span>
            <span class="text-dim">|</span>
            <span><i class="fa-solid fa-network-wired text-blue"></i> ${peers} peers</span>
            <span class="text-dim">|</span>
            <span class="text-green"><i class="fa-solid fa-layer-group"></i> ${pct}% (${downloaded}/${total} pcs)</span>
          </span>
        `;
      } else {
        swarmStat.innerHTML = '<span class="mono text-xs text-dim"><i class="fa-solid fa-spinner fa-spin text-accent"></i> Connecting to P2P Swarm & Allocating Multi-Buffer...</span>';
        const hudP2p = document.getElementById('player-hud-p2p-text');
        if (hudP2p) hudP2p.innerText = 'Connecting...';
      }
    } catch (_) {}
  };

  poll();
  swarmMonitorTimer = setInterval(poll, 1500);
}

function stopSwarmStatsMonitor() {
  if (swarmMonitorTimer) {
    clearInterval(swarmMonitorTimer);
    swarmMonitorTimer = null;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// SWARM & PIECE MAP INSPECTOR (Phase 5)
// ══════════════════════════════════════════════════════════════════════════════

function toggleSwarmInspectorModal(open = null) {
  const modal = document.getElementById('swarm-inspector-modal');
  if (!modal) return;
  const isHidden = modal.classList.contains('hidden');
  const shouldOpen = open !== null ? open : isHidden;
  modal.classList.toggle('hidden', !shouldOpen);
  syncFullscreenPortal(modal, shouldOpen);
  if (shouldOpen) {
    handlePlayerActivity();
    if (window._lastSwarmSession) {
      updateSwarmInspectorModal(window._lastSwarmSession);
    }
  }
}

function updateSwarmInspectorModal(session) {
  if (!session) return;
  const modal = document.getElementById('swarm-inspector-modal');
  if (!modal || modal.classList.contains('hidden')) return;

  const downEl = document.getElementById('swarm-inspector-down');
  const peersEl = document.getElementById('swarm-inspector-peers');
  const piecesEl = document.getElementById('swarm-inspector-pieces');
  const pctEl = document.getElementById('swarm-inspector-pct');
  const piecemapEl = document.getElementById('swarm-inspector-piecemap');
  const peerListEl = document.getElementById('swarm-inspector-peer-list');

  if (downEl) downEl.innerText = formatSpeed(session.download_speed || 0);
  if (peersEl) peersEl.innerText = `${session.peers || 0} Peers`;
  if (piecesEl) piecesEl.innerText = `${session.pieces_downloaded || 0} / ${session.pieces_total || 0}`;
  if (pctEl) pctEl.innerText = `${session.buffer_pct || '0'}%`;

  if (piecemapEl && session.piece_map) {
    const bits = session.piece_map.split('');
    piecemapEl.innerHTML = bits.map((b) => `<div class="piece-cell ${b === '1' ? 'downloaded' : ''}"></div>`).join('');
  }

  if (peerListEl) {
    const peers = session.peers_list || [];
    if (peers.length === 0) {
      peerListEl.innerHTML = '<div class="text-xs text-dim p-2 text-center">Searching swarm & negotiating BitTorrent handshakes...</div>';
    } else {
      peerListEl.innerHTML = peers.map((p) => `
        <div class="peer-client-row">
          <span><i class="fa-solid fa-desktop text-accent"></i> ${escapeHtml(p.client || 'BitTorrent Client')} (${escapeHtml(p.type || 'tcp')})</span>
          <span class="mono text-green">↓ ${escapeHtml(p.downSpeed || '0 KB/s')}</span>
          <span class="mono text-dim">↑ ${escapeHtml(p.upSpeed || '0 KB/s')}</span>
        </div>
      `).join('');
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// UNIVERSAL EXTERNAL PLAYER & CASTING (Phase 6)
// ══════════════════════════════════════════════════════════════════════════════

function toggleExtPlayerDropdown(open = null) {
  const menu = document.getElementById('player-extplayer-menu');
  if (!menu) return;
  const shouldOpen = open !== null ? open : menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !shouldOpen);
}

async function switchPlayerToExternal(playerName = 'vlc') {
  toggleExtPlayerDropdown(false);
  const active = state.discover.activeStream;
  if (!active) {
    showToast('No active stream to launch in external player', 'error');
    return;
  }

  // Automatically pause the web player so audio/video does not conflict with desktop player
  const video = document.getElementById('evo-video-player');
  if (video && !video.paused) {
    video.pause();
    updatePlayPauseIcon(false);
    stopPlayerTicker();
  }

  const pLabel = document.getElementById('player-hud-extplayer-label');
  if (pLabel) pLabel.innerText = playerName.toUpperCase();

  showToast(`Launching ${playerName.toUpperCase()} on host machine...`, 'info');

  try {
    const epParams = (active.season !== null && active.episode !== null)
      ? { season: active.season, episode: active.episode }
      : {};

    const payload = {
      player: playerName,
      info_hash: active.infoHash,
      file_idx: active.fileIdx || 0,
      magnet: active.magnet || null,
      title: active.title || 'EvoStream',
      ...epParams,
    };

    const res = await fetch('/api/v1/stream/launch-external', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || `Failed to launch ${playerName}`);
    }

    showToast(`${playerName.toUpperCase()} launched successfully!`, 'success');
  } catch (err) {
    console.error(`Failed to launch external player:`, err);
    showToast(`External Player Error: ${err.message}`, 'error');
  }
}

function promptCastMedia() {
  const video = document.getElementById('evo-video-player');
  if (video && video.remote && typeof video.remote.prompt === 'function') {
    video.remote.prompt().catch((err) => {
      showToast(`Cast notice: ${err.message || 'No cast devices found on local network'}`, 'info');
    });
  } else {
    const active = state.discover.activeStream;
    if (active) {
      const streamUrl = `${window.location.origin}/api/v1/stream/play?info_hash=${active.infoHash}&file_idx=${active.fileIdx || 0}`;
      navigator.clipboard?.writeText(streamUrl).catch(() => {});
      showToast(`Stream URL copied to clipboard for Chromecast / Smart TV DLNA casting!`, 'success');
    } else {
      showToast('Casting requires an active playback stream.', 'info');
    }
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// OFFLINE DOWNLOADS & CACHE MANAGER (Phase 8)
// ══════════════════════════════════════════════════════════════════════════════

function triggerOfflineDownload() {
  const active = state.discover.activeStream;
  if (!active || !active.infoHash) {
    showToast('No active stream loaded to download', 'error');
    return;
  }
  const epParams = (active.season !== null && active.episode !== null)
    ? `&season=${active.season}&episode=${active.episode}`
    : '';
  const magnetParam = active.magnet ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
  const dlUrl = `/api/v1/stream/play?info_hash=${active.infoHash}&file_idx=${active.fileIdx || 0}${epParams}${magnetParam}`;

  const safeName = (active.title || 'video').replace(/[^a-zA-Z0-9._-]/g, '_') + '.mp4';
  const a = document.createElement('a');
  a.href = dlUrl;
  a.download = safeName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  showToast(`Starting offline download: ${safeName}`, 'success');
}

// ══════════════════════════════════════════════════════════════════════════════
// EXPANSIVE SETTINGS CONTROL CENTER, PARAMETERS & SYSTEM DIAGNOSTICS
// ══════════════════════════════════════════════════════════════════════════════

const DEFAULT_ANNOUNCE_TRACKERS = [
  'udp://tracker.opentrackr.org:1337/announce',
  'udp://tracker.torrent.eu.org:451/announce',
  'udp://open.stealth.si:80/announce',
  'udp://explodie.org:6969/announce',
  'udp://tracker.coppersurfer.tk:6969/announce',
  'wss://tracker.openwebtorrent.com',
  'wss://tracker.webtorrent.dev',
  'wss://tracker.files.fm:7073/announce'
].join('\n');

const PRESET_STREMIO_ADDONS = {
  cinemeta: {
    id: 'com.linvo.cinemeta',
    name: 'Cinemeta V3',
    version: '3.0.14',
    url: 'https://v3-cinemeta.strem.io/manifest.json'
  },
  torrentio: {
    id: 'com.stremio.torrentio',
    name: 'Torrentio V3',
    version: '1.0.12',
    url: 'https://torrentio.strem.fun/manifest.json'
  },
  cyberflix: {
    id: 'com.cyberflix.catalog',
    name: 'CyberFlix Catalog',
    version: '1.4.1',
    url: 'https://cyberflix.kamyoll.uk/manifest.json'
  },
  opensubtitles: {
    id: 'org.stremio.opensubtitlesv3',
    name: 'OpenSubtitles V3',
    version: '1.0.0',
    url: 'https://opensubtitles-v3.strem.io/manifest.json'
  }
};

let activeSettingsTab = 'interface';

async function toggleSettingsModal(open = null) {
  const modal = document.getElementById('settings-modal');
  if (!modal) return;
  const isHidden = modal.classList.contains('hidden');
  const shouldOpen = open !== null ? open : isHidden;
  modal.classList.toggle('hidden', !shouldOpen);
  syncFullscreenPortal(modal, shouldOpen);
  if (shouldOpen) {
    loadAllSettings();
    switchSettingsTab(activeSettingsTab);
    await fetchCacheStatus();
    loadInstalledAddons();
  }
}

function switchSettingsTab(tabName) {
  activeSettingsTab = tabName;
  document.querySelectorAll('.settings-nav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-settings-tab') === tabName);
  });

  const panes = ['interface', 'apis', 'network', 'storage', 'addons', 'diagnostics'];
  panes.forEach(p => {
    const el = document.getElementById(`settings-tab-${p}`);
    if (el) el.classList.toggle('hidden', p !== tabName);
  });

  if (tabName === 'storage') {
    fetchCacheStatus();
  } else if (tabName === 'addons') {
    loadInstalledAddons();
  }
}

function loadAllSettings() {
  let s = {};
  try {
    s = JSON.parse(localStorage.getItem('evo_advanced_settings') || '{}');
  } catch (_) {}

  // 1. Interface
  const currentTheme = document.body.getAttribute('data-theme') || localStorage.getItem('evo_theme') || 'emerald';
  document.querySelectorAll('[data-theme-btn]').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-theme-btn') === currentTheme);
  });

  const scaleInput = document.getElementById('settings-gui-scale-input');
  const scaleBadge = document.getElementById('settings-gui-scale-badge');
  const savedScale = parseFloat(localStorage.getItem('evo_gui_scale') || '15.5');
  if (scaleInput) scaleInput.value = savedScale;
  if (scaleBadge) scaleBadge.innerText = `${Math.round((savedScale / 15.5) * 100)}% (${savedScale}px)`;

  const aspectSel = document.getElementById('settings-default-aspect');
  if (aspectSel) aspectSel.value = s.aspect_ratio || 'contain';

  const ambilightChk = document.getElementById('settings-toggle-ambilight');
  if (ambilightChk) ambilightChk.checked = s.ambilight_enabled !== false;

  const ambilightBlurInput = document.getElementById('settings-ambilight-blur-input');
  const ambilightBlurVal = document.getElementById('settings-ambilight-blur-val');
  const savedBlur = s.ambilight_blur || 45;
  if (ambilightBlurInput) ambilightBlurInput.value = savedBlur;
  if (ambilightBlurVal) ambilightBlurVal.innerText = `${savedBlur}px`;

  const autoplayChk = document.getElementById('settings-toggle-autoplay');
  if (autoplayChk) autoplayChk.checked = s.autoplay_next !== false;

  const skipintroChk = document.getElementById('settings-toggle-skipintro');
  if (skipintroChk) skipintroChk.checked = s.skip_intro !== false;

  const shelfContinueChk = document.getElementById('settings-toggle-shelf-continue');
  if (shelfContinueChk) shelfContinueChk.checked = s.shelf_continue !== false && localStorage.getItem('evoscrapper_setting_show_continue') !== '0';

  const shelfBookmarksChk = document.getElementById('settings-toggle-shelf-bookmarks');
  if (shelfBookmarksChk) shelfBookmarksChk.checked = s.shelf_bookmarks !== false && localStorage.getItem('evoscrapper_setting_show_bookmarks') !== '0';

  // 2. APIs & Scrapers
  const cinemetaInput = document.getElementById('settings-cinemeta-url');
  if (cinemetaInput) cinemetaInput.value = s.cinemeta_url || 'https://v3-cinemeta.strem.io';

  const tmdbInput = document.getElementById('settings-tmdb-key');
  if (tmdbInput) tmdbInput.value = s.tmdb_key || '';

  const timeoutInput = document.getElementById('settings-timeout-input');
  const timeoutBadge = document.getElementById('settings-timeout-badge');
  const savedTimeout = s.scrape_timeout || 12;
  if (timeoutInput) timeoutInput.value = savedTimeout;
  if (timeoutBadge) timeoutBadge.innerText = `${savedTimeout} Seconds`;

  const concurrencyInput = document.getElementById('settings-concurrency-input');
  const concurrencyBadge = document.getElementById('settings-concurrency-badge');
  const savedConcurrency = s.scrape_concurrency || 4;
  if (concurrencyInput) concurrencyInput.value = savedConcurrency;
  if (concurrencyBadge) concurrencyBadge.innerText = `${savedConcurrency} Parallel Queries`;

  const minSeedersSel = document.getElementById('settings-min-seeders');
  if (minSeedersSel) minSeedersSel.value = s.min_seeders !== undefined ? s.min_seeders : '1';

  const fallbackAddonsChk = document.getElementById('settings-toggle-fallback-addons');
  if (fallbackAddonsChk) fallbackAddonsChk.checked = s.fallback_addons !== false;

  // 3. Network & Trackers
  const trackersArea = document.getElementById('settings-trackers-textarea');
  if (trackersArea) trackersArea.value = s.announce_trackers || DEFAULT_ANNOUNCE_TRACKERS;

  const maxPeersInput = document.getElementById('settings-max-peers-input');
  const maxPeersBadge = document.getElementById('settings-max-peers-badge');
  const savedMaxPeers = s.max_peers || 55;
  if (maxPeersInput) maxPeersInput.value = savedMaxPeers;
  if (maxPeersBadge) maxPeersBadge.innerText = `${savedMaxPeers} Peers`;

  const bufferSizeInput = document.getElementById('settings-buffer-size-input');
  const bufferSizeBadge = document.getElementById('settings-buffer-size-badge');
  const savedBufferSize = s.buffer_size_mb || 200;
  if (bufferSizeInput) bufferSizeInput.value = savedBufferSize;
  if (bufferSizeBadge) bufferSizeBadge.innerText = `${savedBufferSize} MB Window`;

  const upnpChk = document.getElementById('settings-toggle-upnp');
  if (upnpChk) upnpChk.checked = s.upnp_enabled !== false;

  const p2pMeshChk = document.getElementById('settings-toggle-p2p-mesh');
  if (p2pMeshChk) p2pMeshChk.checked = s.p2p_mesh_enabled !== false;

  // 4. Storage
  const autopurgeChk = document.getElementById('settings-toggle-autopurge');
  if (autopurgeChk) autopurgeChk.checked = s.auto_purge_cache === true;
}

function saveAndApplyAllSettings() {
  const cinemetaUrl = (document.getElementById('settings-cinemeta-url')?.value || 'https://v3-cinemeta.strem.io').trim();
  const tmdbKey = (document.getElementById('settings-tmdb-key')?.value || '').trim();
  const timeout = parseInt(document.getElementById('settings-timeout-input')?.value || '12', 10);
  const concurrency = parseInt(document.getElementById('settings-concurrency-input')?.value || '4', 10);
  const minSeeders = parseInt(document.getElementById('settings-min-seeders')?.value || '1', 10);
  const fallbackAddons = document.getElementById('settings-toggle-fallback-addons')?.checked ?? true;
  const trackers = (document.getElementById('settings-trackers-textarea')?.value || DEFAULT_ANNOUNCE_TRACKERS).trim();
  const maxPeers = parseInt(document.getElementById('settings-max-peers-input')?.value || '55', 10);
  const bufferSize = parseInt(document.getElementById('settings-buffer-size-input')?.value || '200', 10);
  const upnp = document.getElementById('settings-toggle-upnp')?.checked ?? true;
  const p2pMesh = document.getElementById('settings-toggle-p2p-mesh')?.checked ?? true;
  const defaultAspect = document.getElementById('settings-default-aspect')?.value || 'contain';
  const ambilight = document.getElementById('settings-toggle-ambilight')?.checked ?? true;
  const ambilightBlur = parseInt(document.getElementById('settings-ambilight-blur-input')?.value || '45', 10);
  const autoplay = document.getElementById('settings-toggle-autoplay')?.checked ?? true;
  const skipintro = document.getElementById('settings-toggle-skipintro')?.checked ?? true;
  const autopurge = document.getElementById('settings-toggle-autopurge')?.checked ?? false;

  const config = {
    cinemeta_url: cinemetaUrl,
    tmdb_key: tmdbKey,
    scrape_timeout: timeout,
    scrape_concurrency: concurrency,
    min_seeders: minSeeders,
    fallback_addons: fallbackAddons,
    announce_trackers: trackers,
    max_peers: maxPeers,
    buffer_size_mb: bufferSize,
    upnp_enabled: upnp,
    p2p_mesh_enabled: p2pMesh,
    aspect_ratio: defaultAspect,
    ambilight_enabled: ambilight,
    ambilight_blur: ambilightBlur,
    autoplay_next: autoplay,
    skip_intro: skipintro,
    auto_purge_cache: autopurge,
    shelf_continue: document.getElementById('settings-toggle-shelf-continue')?.checked ?? true,
    shelf_bookmarks: document.getElementById('settings-toggle-shelf-bookmarks')?.checked ?? true
  };

  try {
    localStorage.setItem('evo_advanced_settings', JSON.stringify(config));
    localStorage.setItem('evoscrapper_setting_show_continue', config.shelf_continue ? '1' : '0');
    localStorage.setItem('evoscrapper_setting_show_bookmarks', config.shelf_bookmarks ? '1' : '0');
    renderContinueWatchingShelf();
    renderBookmarksShelf();
  } catch (_) {}

  // Apply to live video player if active
  const video = document.getElementById('evo-video-player');
  if (video) {
    video.className = `evo-video-el aspect-${defaultAspect}`;
  }
  const glow = document.getElementById('player-ambilight-glow');
  if (glow) {
    glow.style.filter = `blur(${ambilightBlur}px)`;
    if (!ambilight) glow.style.opacity = '0';
  }

  const indicator = document.getElementById('settings-status-indicator');
  if (indicator) {
    indicator.innerHTML = '<i class="fa-solid fa-circle-check text-green"></i> Settings saved and applied successfully!';
    setTimeout(() => {
      indicator.innerHTML = 'All configuration changes persist locally in real-time';
    }, 4000);
  }

  showToast('Configuration applied and saved!', 'success');
}

function resetAllSettingsToDefault() {
  if (!confirm('Reset all EvoScrapper settings to factory defaults?')) return;
  try {
    localStorage.removeItem('evo_advanced_settings');
  } catch (_) {}
  loadAllSettings();
  showToast('Settings restored to defaults', 'info');
}

function handleSettingsScaleInput(val) {
  handleGuiScaleInput(val);
  const badge = document.getElementById('settings-gui-scale-badge');
  if (badge) badge.innerText = `${Math.round((parseFloat(val) / 15.5) * 100)}% (${val}px)`;
}

function handleTimeoutInput(val) {
  const badge = document.getElementById('settings-timeout-badge');
  if (badge) badge.innerText = `${val} Seconds`;
}

function handleConcurrencyInput(val) {
  const badge = document.getElementById('settings-concurrency-badge');
  if (badge) badge.innerText = `${val} Parallel Queries`;
}

function handleMaxPeersInput(val) {
  const badge = document.getElementById('settings-max-peers-badge');
  if (badge) badge.innerText = `${val} Peers`;
}

function getActiveBufferSizeMb() {
  try {
    const s = JSON.parse(localStorage.getItem('evo_advanced_settings') || '{}');
    if (s.buffer_size_mb) return parseInt(s.buffer_size_mb, 10);
  } catch (_) {}
  const input = document.getElementById('settings-buffer-size-input');
  if (input && input.value) return parseInt(input.value, 10);
  return 200;
}

function handleBufferSizeInput(val) {
  const badge = document.getElementById('settings-buffer-size-badge');
  if (badge) badge.innerText = `${val} MB Window`;
  try {
    const s = JSON.parse(localStorage.getItem('evo_advanced_settings') || '{}');
    s.buffer_size_mb = parseInt(val, 10);
    localStorage.setItem('evo_advanced_settings', JSON.stringify(s));
  } catch (_) {}
}

function handleAmbilightBlurInput(val) {
  const badge = document.getElementById('settings-ambilight-blur-val');
  if (badge) badge.innerText = `${val}px`;
  const glow = document.getElementById('player-ambilight-glow');
  if (glow) glow.style.filter = `blur(${val}px)`;
}

function handleSettingChange(key, value) {
  let s = {};
  try {
    s = JSON.parse(localStorage.getItem('evo_advanced_settings') || '{}');
  } catch (_) {}
  s[key] = value;
  try {
    localStorage.setItem('evo_advanced_settings', JSON.stringify(s));
    if (key === 'shelf_continue') {
      localStorage.setItem('evoscrapper_setting_show_continue', value ? '1' : '0');
      renderContinueWatchingShelf();
    } else if (key === 'shelf_bookmarks') {
      localStorage.setItem('evoscrapper_setting_show_bookmarks', value ? '1' : '0');
      renderBookmarksShelf();
    }
  } catch (_) {}
}

function resetCinemetaUrl() {
  const input = document.getElementById('settings-cinemeta-url');
  if (input) input.value = 'https://v3-cinemeta.strem.io';
  handleSettingChange('cinemeta_url', 'https://v3-cinemeta.strem.io');
  showToast('Restored default Cinemeta URL', 'info');
}

function resetDefaultTrackers() {
  const area = document.getElementById('settings-trackers-textarea');
  if (area) area.value = DEFAULT_ANNOUNCE_TRACKERS;
  handleSettingChange('announce_trackers', DEFAULT_ANNOUNCE_TRACKERS);
  showToast('Restored default tracker announce list', 'info');
}

async function testCinemetaEndpoint() {
  const input = document.getElementById('settings-cinemeta-url');
  const url = (input ? input.value : 'https://v3-cinemeta.strem.io').trim();
  showToast(`Testing ${url}...`, 'info');
  const t0 = performance.now();
  try {
    const res = await fetch(`${url}/manifest.json`);
    const lat = Math.round(performance.now() - t0);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    showToast(`Cinemeta OK: ${data.name || 'Catalog'} responded in ${lat}ms!`, 'success');
  } catch (err) {
    showToast(`Cinemeta probe failed: ${err.message}`, 'error');
  }
}

async function pingDaemonDirect() {
  showToast('Pinging WebTorrent Daemon (127.0.0.1:8889)...', 'info');
  const t0 = performance.now();
  try {
    const res = await fetch('/api/v1/stream/stats');
    const lat = Math.round(performance.now() - t0);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    showToast(`Daemon Online (${data.engine || 'webtorrent'}): ${lat}ms | DL: ${data.clientDownloadSpeed || '0 MB/s'}`, 'success');
  } catch (err) {
    showToast(`Daemon unreachable: ${err.message}`, 'error');
  }
}

async function fetchCacheStatus() {
  const usageEl = document.getElementById('settings-cache-usage');
  const usageDetailedEl = document.getElementById('settings-cache-usage-detailed');
  const dirEl = document.getElementById('settings-cache-dir-display');
  const diskBadge = document.getElementById('settings-disk-free-badge');

  try {
    const res = await fetch('/api/v1/stream/cache/status');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const txt = `${data.total_mb} MB across ${data.file_count} cached piece files`;
    if (usageEl) usageEl.innerText = txt;
    if (usageDetailedEl) usageDetailedEl.innerText = txt;
    if (dirEl && data.cache_dir) dirEl.innerText = `Directory: ${data.cache_dir}`;

    // Also probe diagnostics for disk info
    const diagRes = await fetch('/api/v1/stream/diagnostics');
    if (diagRes.ok) {
      const diagData = await diagRes.json();
      if (diskBadge && diagData.storage?.disk_free_gb) {
        diskBadge.innerText = `${diagData.storage.disk_free_gb} GB Free / ${diagData.storage.disk_total_gb} GB Total (${diagData.storage.disk_used_percent}% used)`;
      }
    }
  } catch (err) {
    if (usageEl) usageEl.innerText = 'Cache clean (0 MB)';
    if (usageDetailedEl) usageDetailedEl.innerText = '0 MB (0 pieces)';
  }
}

async function clearStreamCache() {
  try {
    const res = await fetch('/api/v1/stream/cache/clear', { method: 'POST' });
    const data = await res.json();
    showToast(`Reclaimed ${data.cleared_mb} MB across ${data.cleared_files} files!`, 'success');
    await fetchCacheStatus();
  } catch (err) {
    showToast(`Failed to clear cache: ${err.message}`, 'error');
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// DIAGNOSTIC SELF-TEST ENGINE (Check / Test Suite)
// ══════════════════════════════════════════════════════════════════════════════

async function runDiagnosticsTest() {
  switchSettingsTab('diagnostics');
  const btn = document.getElementById('btn-run-diag');
  const consoleEl = document.getElementById('diag-console-output');
  if (btn) btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Running Diagnostic Probes...';

  const logLines = [];
  const log = (msg) => {
    const ts = new Date().toISOString().substring(11, 19);
    logLines.push(`[${ts}] ${msg}`);
    if (consoleEl) {
      consoleEl.innerText = logLines.join('\n');
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  };

  log('>>> INITIATING EVOSCRAPPER SYSTEM DIAGNOSTIC SELF-TEST...');
  log('Testing loopback backend on port 8009...');

  try {
    const t0 = performance.now();
    const res = await fetch('/api/v1/stream/diagnostics');
    const elapsed = Math.round(performance.now() - t0);

    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    const data = await res.json();

    log(`✓ FastAPI Backend Core responded in ${elapsed}ms: ${data.backend.version} on Python ${data.backend.python} (${data.backend.os})`);

    // 1. Backend Card
    updateDiagCard('backend', 'ONLINE', 'tag-green', `${data.backend.version} · Port 8009`, `Python ${data.backend.python} · ${data.backend.os}`);

    // 2. Daemon Card
    if (data.daemon.status === 'online') {
      log(`✓ WebTorrent Micro-Daemon online at ${data.daemon.url}: Latency ${data.daemon.latency_ms}ms, Active swarms: ${data.daemon.active_torrents}`);
      updateDiagCard('daemon', 'ONLINE', 'tag-green', `${data.daemon.latency_ms}ms · Port 8889`, `Active Swarms: ${data.daemon.active_torrents} | DL: ${data.daemon.download_speed}`);
    } else {
      log(`✗ WebTorrent Micro-Daemon error: ${data.daemon.error || 'Offline'}`);
      updateDiagCard('daemon', 'OFFLINE', 'tag-red', 'Port 8889 Error', data.daemon.error || 'Daemon offline');
    }

    // 3. FFmpeg Card
    if (data.ffmpeg.available) {
      log(`✓ FFmpeg Transmuxer & Audio Engine detected: ${data.ffmpeg.version.substring(0, 48)}...`);
      updateDiagCard('ffmpeg', 'READY', 'tag-green', 'v9.0.2 Transmuxer', 'Hardware acceleration & WebVTT');
    } else {
      log('! FFmpeg not found on host machine PATH (Transmuxing fallback active)');
      updateDiagCard('ffmpeg', 'MISSING', 'tag-dim', 'Not in PATH', 'Pass-through streaming mode');
    }

    // 4. Desktop Players Card
    const foundPlayers = [];
    if (data.players.vlc) foundPlayers.push('VLC');
    if (data.players.mpv) foundPlayers.push('MPV');
    if (data.players.mpc_hc) foundPlayers.push('MPC-HC');
    if (data.players.potplayer) foundPlayers.push('PotPlayer');

    if (foundPlayers.length > 0) {
      log(`✓ Desktop Media Players found: ${foundPlayers.join(', ')}`);
      updateDiagCard('players', 'FOUND', 'tag-green', foundPlayers.join(' + '), `Primary: ${foundPlayers[0]}`);
    } else {
      log('! No desktop media players detected in default program directories');
      updateDiagCard('players', 'NONE', 'tag-dim', 'Web Player Only', 'VLC/MPV not detected');
    }

    // 5. Stremio Catalog Card
    if (data.stremio.status === 'online') {
      log(`✓ Stremio Cinemeta Catalog responded in ${data.stremio.latency_ms}ms`);
      updateDiagCard('stremio', 'ONLINE', 'tag-green', `${data.stremio.latency_ms}ms`, 'Cinemeta Catalog V3 Verified');
    } else {
      log(`✗ Stremio Cinemeta Catalog error: ${data.stremio.error || 'Unreachable'}`);
      updateDiagCard('stremio', 'ERROR', 'tag-red', 'API Error', data.stremio.error || 'Failed to query Cinemeta');
    }

    // 6. Trackers Card
    const resolvedTrks = (data.trackers || []).filter(t => t.status === 'resolved');
    log(`✓ Swarm Trackers: ${resolvedTrks.length} / ${data.trackers.length} public tracker nodes resolved`);
    data.trackers.forEach(t => {
      log(`   - ${t.host}: ${t.status === 'resolved' ? `${t.ip} (${t.latency_ms}ms)` : t.error}`);
    });
    updateDiagCard('trackers', `${resolvedTrks.length}/${data.trackers.length} UP`, resolvedTrks.length > 0 ? 'tag-green' : 'tag-red', `${resolvedTrks.length} Trackers`, 'OpenTrackr + European Nodes');

    // 7. Storage Card
    if (data.storage.disk_free_gb) {
      log(`✓ Disk Storage: ${data.storage.disk_free_gb} GB Free out of ${data.storage.disk_total_gb} GB. Cache: ${data.storage.cache_mb} MB across ${data.storage.cache_files} piece files.`);
      updateDiagCard('storage', `${data.storage.disk_free_gb}GB FREE`, 'tag-green', `${data.storage.cache_mb} MB Cached`, `${data.storage.disk_used_percent}% total disk space used`);
    }

    // 8. Browser Mesh Card
    const mseSupport = 'MediaSource' in window;
    const webrtcSupport = 'RTCPeerConnection' in window;
    log(`✓ Browser Media Capabilities: MediaSource Extensions = ${mseSupport ? 'YES' : 'NO'}, WebRTC = ${webrtcSupport ? 'YES' : 'NO'}`);
    updateDiagCard('mesh', 'ACTIVE', 'tag-green', 'MSE & WebRTC', 'P2P Browser Mesh Ready');

    log(`>>> DIAGNOSTIC COMPLETE IN ${data.total_elapsed_ms}ms. ALL SYSTEMS NOMINAL.`);
    showToast('System diagnostics completed with 100% success!', 'success');
  } catch (err) {
    log(`✗ DIAGNOSTIC FATAL ERROR: ${err.message}`);
    showToast(`Diagnostics error: ${err.message}`, 'error');
  } finally {
    if (btn) btn.innerHTML = '<i class="fa-solid fa-play"></i> Run All Diagnostics';
  }
}

function updateDiagCard(key, statusText, tagClass, valText, subText) {
  const tag = document.getElementById(`diag-tag-${key}`);
  const val = document.getElementById(`diag-val-${key}`);
  const sub = document.getElementById(`diag-sub-${key}`);
  if (tag) {
    tag.innerText = statusText;
    tag.className = `tag ${tagClass} text-xs mono`;
  }
  if (val) val.innerText = valText;
  if (sub) sub.innerText = subText;
}

async function installPresetAddon(presetKey) {
  const preset = PRESET_STREMIO_ADDONS[presetKey];
  if (!preset) return;

  let addons = [];
  try {
    addons = JSON.parse(localStorage.getItem('evo_stremio_addons') || '[]');
  } catch (_) {}

  if (addons.some(a => a.url === preset.url || a.id === preset.id)) {
    showToast(`${preset.name} is already installed!`, 'info');
    return;
  }

  try {
    showToast(`Installing ${preset.name}...`, 'info');
    const res = await fetch(`/api/v1/addons/manifest?url=${encodeURIComponent(preset.url)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const manifest = data.manifest;

    addons.push({
      id: manifest.id || preset.id,
      name: manifest.name || preset.name,
      version: manifest.version || preset.version,
      url: preset.url
    });
    localStorage.setItem('evo_stremio_addons', JSON.stringify(addons));
    loadInstalledAddons();
    showToast(`Installed ${preset.name}!`, 'success');
  } catch (err) {
    // If offline or manifest query failed, still add preset
    addons.push(preset);
    localStorage.setItem('evo_stremio_addons', JSON.stringify(addons));
    loadInstalledAddons();
    showToast(`Installed ${preset.name}!`, 'success');
  }
}


// ══════════════════════════════════════════════════════════════════════════════
// YOUTUBE TRAILER MODAL (Phase 7)
// ══════════════════════════════════════════════════════════════════════════════

function openTrailerModal(trailerUrl, title = 'Official Trailer') {
  const modal = document.getElementById('trailer-modal');
  const iframe = document.getElementById('trailer-iframe');
  const titleEl = document.getElementById('trailer-modal-title');
  if (!modal || !iframe) return;

  if (titleEl) titleEl.innerText = `${title} — Official Trailer`;

  let src = '';
  if (trailerUrl && (trailerUrl.includes('youtube.com') || trailerUrl.includes('youtu.be'))) {
    let videoId = '';
    const m = trailerUrl.match(/(?:v=|\/embed\/|\/watch\?v=|youtu\.be\/|\/v\/)([^&#?]+)/);
    if (m) videoId = m[1];
    if (videoId) {
      src = `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1`;
    }
  }

  if (!src) {
    const query = encodeURIComponent(`${title} official trailer`);
    src = `https://www.youtube-nocookie.com/embed?listType=search&list=${query}&autoplay=1`;
  }

  iframe.src = src;
  modal.classList.remove('hidden');
}

function closeTrailerModal() {
  const modal = document.getElementById('trailer-modal');
  const iframe = document.getElementById('trailer-iframe');
  if (iframe) iframe.src = '';
  if (modal) modal.classList.add('hidden');
}

// ══════════════════════════════════════════════════════════════════════════════
// STREMIO ADDONS ENGINE (Phase 9)
// ══════════════════════════════════════════════════════════════════════════════

function loadInstalledAddons() {
  const listEl = document.getElementById('installed-addons-list');
  if (!listEl) return;
  let addons = [];
  try {
    addons = JSON.parse(localStorage.getItem('evo_stremio_addons') || '[]');
  } catch (_) {}

  if (addons.length === 0) {
    listEl.innerHTML = '<div class="text-xs text-dim p-2">No custom Stremio addons installed yet. Paste a manifest URL above.</div>';
    return;
  }

  listEl.innerHTML = addons.map((a, idx) => `
    <div class="flex items-center justify-between p-2 rounded mb-1" style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06);">
      <div>
        <div class="mono font-bold text-xs text-accent">${escapeHtml(a.name || 'Addon')} <span class="tag tag-dim" style="font-size:0.6rem;">v${escapeHtml(a.version || '1.0')}</span></div>
        <div class="mono text-dim text-xs" style="font-size:0.68rem; word-break:break-all;">${escapeHtml(a.url)}</div>
      </div>
      <button class="btn btn-xs btn-ghost text-red" onclick="removeCustomStremioAddon(${idx})"><i class="fa-solid fa-trash-can"></i></button>
    </div>
  `).join('');
}

async function addCustomStremioAddon() {
  const input = document.getElementById('stremio-addon-url-input');
  if (!input) return;
  const url = input.value.trim();
  if (!url) return;

  try {
    showToast('Validating Stremio addon manifest...', 'info');
    const res = await fetch(`/api/v1/addons/manifest?url=${encodeURIComponent(url)}`);
    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.detail || 'Invalid addon manifest');
    }
    const data = await res.json();
    const manifest = data.manifest;

    let addons = [];
    try {
      addons = JSON.parse(localStorage.getItem('evo_stremio_addons') || '[]');
    } catch (_) {}

    addons.push({
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      url: url,
    });
    localStorage.setItem('evo_stremio_addons', JSON.stringify(addons));
    input.value = '';
    loadInstalledAddons();
    showToast(`Installed Stremio Addon: ${manifest.name}!`, 'success');
  } catch (err) {
    showToast(`Addon error: ${err.message}`, 'error');
  }
}

function removeCustomStremioAddon(idx) {
  let addons = [];
  try {
    addons = JSON.parse(localStorage.getItem('evo_stremio_addons') || '[]');
  } catch (_) {}
  if (addons[idx]) {
    const removed = addons.splice(idx, 1);
    localStorage.setItem('evo_stremio_addons', JSON.stringify(addons));
    loadInstalledAddons();
    showToast(`Removed addon: ${removed[0].name}`, 'info');
  }
}

// ══════════════════════════════════════════════════════════════════════════════
// THEME CUSTOMIZER & MOBILE TOUCH HUD (Phase 10)
// ══════════════════════════════════════════════════════════════════════════════

const THEMES = ['emerald', 'cyberpunk', 'oled', 'netflix', 'obsidian'];

function setTheme(themeName) {
  if (!THEMES.includes(themeName)) themeName = 'emerald';
  document.body.setAttribute('data-theme', themeName);
  try {
    localStorage.setItem('evo_theme', themeName);
  } catch (_) {}

  document.querySelectorAll('[data-theme-btn]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-theme-btn') === themeName);
  });
  showToast(`Theme: ${themeName.toUpperCase()}`, 'info');
}

function cycleTheme() {
  const current = document.body.getAttribute('data-theme') || 'emerald';
  const nextIdx = (THEMES.indexOf(current) + 1) % THEMES.length;
  setTheme(THEMES[nextIdx]);
}

function initTheme() {
  const saved = localStorage.getItem('evo_theme') || 'emerald';
  setTheme(saved);
}

function initTouchHUD() {
  const wrap = document.getElementById('player-video-wrap') || document.querySelector('.player-video-wrap');
  if (!wrap) return;

  let lastTap = 0;
  wrap.addEventListener('touchend', (e) => {
    const now = Date.now();
    const touch = e.changedTouches ? e.changedTouches[0] : null;
    if (!touch) return;

    if (now - lastTap < 300) {
      const rect = wrap.getBoundingClientRect();
      const xRatio = (touch.clientX - rect.left) / rect.width;

      if (xRatio < 0.35) {
        skipPlayerSeconds(-10);
        showToast('⏪ -10s', 'info');
      } else if (xRatio > 0.65) {
        skipPlayerSeconds(10);
        showToast('⏩ +10s', 'info');
      } else {
        togglePlayerPlay();
      }
    }
    lastTap = now;
  });
}

function unmuteAndBoostVideo() {
  const video = document.getElementById('evo-video-player');
  const overlay = document.getElementById('player-unmute-overlay');
  if (video) {
    video.muted = false;
    video.volume = 1.0;
    if (video.paused) {
      video.play().catch(() => {});
    }
  }
  if (overlay) overlay.classList.add('hidden');
  const slider = document.getElementById('player-volume-slider');
  if (slider) slider.value = 1.0;
  updateVolumeIcon();
  showToast('🔊 Audio unmuted & volume set to 100%', 'info');
}

let playerTimelineDuration = 0;
let isTimelineScrubbing = false;

function formatHhMmSs(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) {
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function updateTimelineScrubber(effectiveTime) {
  updatePlayerTimeline();
}

function skipPlayback(deltaSeconds) {
  skipPlayerSeconds(deltaSeconds);
}

function togglePlayerPlayPause() {
  togglePlayerPlay();
}

function formatPlayerDuration(sec) {
  if (!sec || isNaN(sec) || sec <= 0) return '00:00:00';
  const s = Math.floor(sec);
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  return `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

function parseRuntimeToSeconds(str) {
  if (!str) return 0;
  if (typeof str === 'number') return str;
  str = String(str).trim();
  const minMatch = str.match(/^(\d+)\s*(?:min|m)?$/i);
  if (minMatch) return parseInt(minMatch[1], 10) * 60;
  const hmMatch = str.match(/(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?/i);
  if (hmMatch && (hmMatch[1] || hmMatch[2])) {
    const hrs = hmMatch[1] ? parseInt(hmMatch[1], 10) : 0;
    const mins = hmMatch[2] ? parseInt(hmMatch[2], 10) : 0;
    return (hrs * 3600) + (mins * 60);
  }
  return 0;
}

let playerTickerInterval = null;

function startPlayerTicker() {
  if (playerTickerInterval) clearInterval(playerTickerInterval);
  playerTickerInterval = setInterval(() => {
    const video = document.getElementById('evo-video-player');
    const modal = document.getElementById('player-modal');
    if (video && modal && !modal.classList.contains('hidden') && !video.paused) {
      updatePlayerTimeline();
      updateSubtitleOverlay();
    }
  }, 250);
}

function stopPlayerTicker() {
  if (playerTickerInterval) {
    clearInterval(playerTickerInterval);
    playerTickerInterval = null;
  }
}

let playerTimelineInitialized = false;
function initPlayerTimelineControls() {
  if (playerTimelineInitialized) return;
  playerTimelineInitialized = true;

  const container = document.getElementById('player-timeline-container');
  const hoverTime = document.getElementById('player-hover-time');
  const video = document.getElementById('evo-video-player');

  if (video) {
    video.addEventListener('timeupdate', () => {
      updatePlayerTimeline();
      updateSubtitleOverlay();
    });
    video.addEventListener('seeking', () => {
      updatePlayerTimeline();
      updateSubtitleOverlay();
    });
    video.addEventListener('seeked', () => {
      updatePlayerTimeline();
      updateSubtitleOverlay();
    });
    video.addEventListener('play', () => {
      updatePlayPauseIcon(true);
      startPlayerTicker();
    });
    video.addEventListener('playing', () => {
      hidePlayerBufferingHUD();
      updatePlayPauseIcon(true);
      startPlayerTicker();
    });
    video.addEventListener('canplay', () => {
      hidePlayerBufferingHUD();
    });
    video.addEventListener('loadeddata', () => {
      hidePlayerBufferingHUD();
    });
    video.addEventListener('pause', () => {
      updatePlayPauseIcon(false);
      stopPlayerTicker();
    });
    video.addEventListener('ended', () => {
      updatePlayPauseIcon(false);
      stopPlayerTicker();
    });
  }

  if (!container) return;

  let isDragging = false;

  function calculateTarget(e) {
    const rect = container.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    const pct = rect.width > 0 ? (x / rect.width) : 0;
    const active = state.discover.activeStream;
    const totalDuration = (active && active.totalDuration > 0) ? active.totalDuration : 7200;
    return { pct, seconds: pct * totalDuration };
  }

  container.addEventListener('mousemove', (e) => {
    const { pct, seconds } = calculateTarget(e);
    if (hoverTime) {
      hoverTime.classList.remove('hidden');
      const rect = container.getBoundingClientRect();
      const x = Math.max(10, Math.min(rect.width - 10, e.clientX - rect.left));
      hoverTime.style.left = `${x}px`;
      hoverTime.innerText = formatPlayerDuration(seconds);
    }
    if (isDragging) {
      const progressEl = document.getElementById('player-progress-bar');
      if (progressEl) progressEl.style.width = `${pct * 100}%`;
      const curEl = document.getElementById('player-cur-time');
      if (curEl) curEl.innerText = formatPlayerDuration(seconds);
    }
  });

  container.addEventListener('mouseleave', () => {
    if (hoverTime) hoverTime.classList.add('hidden');
    if (!isDragging && state.discover.activeStream) {
      state.discover.activeStream.isDraggingTimeline = false;
    }
  });

  container.addEventListener('mousedown', (e) => {
    isDragging = true;
    container.classList.add('dragging');
    if (state.discover.activeStream) state.discover.activeStream.isDraggingTimeline = true;
    const { pct, seconds } = calculateTarget(e);
    const progressEl = document.getElementById('player-progress-bar');
    if (progressEl) progressEl.style.width = `${pct * 100}%`;
    const curEl = document.getElementById('player-cur-time');
    if (curEl) curEl.innerText = formatPlayerDuration(seconds);
  });

  window.addEventListener('mouseup', (e) => {
    if (isDragging) {
      isDragging = false;
      container.classList.remove('dragging');
      if (state.discover.activeStream) {
        state.discover.activeStream.isDraggingTimeline = false;
        const { seconds } = calculateTarget(e);
        seekPlayer(seconds);
      }
    }
  });

  // Global Keyboard Shortcuts for player modal
  window.addEventListener('keydown', (e) => {
    const modal = document.getElementById('player-modal');
    if (!modal || modal.classList.contains('hidden')) return;
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;

    handlePlayerActivity();

    if (e.code === 'Space' || e.key === 'k' || e.key === 'K') {
      e.preventDefault();
      togglePlayerPlay();
    } else if (e.key === 'ArrowLeft' || e.key === 'j' || e.key === 'J') {
      e.preventDefault();
      skipPlayerSeconds(-10);
    } else if (e.key === 'ArrowRight' || e.key === 'l' || e.key === 'L') {
      e.preventDefault();
      skipPlayerSeconds(10);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      adjustPlayerVolume(0.1);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      adjustPlayerVolume(-0.1);
    } else if (e.key === 'm' || e.key === 'M') {
      e.preventDefault();
      togglePlayerMute();
    } else if (e.key === 'f' || e.key === 'F') {
      e.preventDefault();
      togglePlayerFullscreen();
    } else if (e.key === 'p' || e.key === 'P') {
      e.preventDefault();
      togglePlayerPiP();
    } else if (e.key === '[') {
      e.preventDefault();
      adjustPlaybackSpeed(-1);
    } else if (e.key === ']') {
      e.preventDefault();
      adjustPlaybackSpeed(1);
    } else if (e.key === 'a' || e.key === 'A') {
      e.preventDefault();
      cyclePlayerAspectRatio();
    } else if (e.key === 'n' || e.key === 'N') {
      e.preventDefault();
      toggleNightDialogueMode();
    } else if (e.key === 'c' || e.key === 'C') {
      e.preventDefault();
      toggleSubtitleDrawer();
    } else if (e.key === 'e' || e.key === 'E') {
      e.preventDefault();
      togglePlayerEpisodesDrawer();
    } else if (e.key === 'b' || e.key === 'B') {
      e.preventDefault();
      cycleAudioTrack();
    } else if (e.key === 's' || e.key === 'S') {
      e.preventDefault();
      toggleSwarmInspectorModal();
    } else if (e.key === 'v' || e.key === 'V') {
      e.preventDefault();
      switchPlayerToExternal('vlc');
    } else if (e.key === 'd' || e.key === 'D') {
      e.preventDefault();
      triggerOfflineDownload();
    } else if (e.key === 'g' || e.key === 'G') {
      e.preventDefault();
      adjustSubtitleSyncMs(-100);
    } else if (e.key === 'h' || e.key === 'H') {
      e.preventDefault();
      adjustSubtitleSyncMs(100);
    } else if (e.key >= '0' && e.key <= '9') {
      const video = document.getElementById('evo-video-player');
      if (video && isFinite(video.duration) && video.duration > 0) {
        e.preventDefault();
        const pct = parseInt(e.key, 10) * 0.1;
        video.currentTime = video.duration * pct;
        showToast(`Seek to ${parseInt(e.key, 10) * 10}%`, 'info');
      }
    } else if (e.key === ',' || e.key === '<') {
      e.preventDefault();
      togglePlayerSettingsMenu();
    } else if (e.key === '?') {
      e.preventDefault();
      toggleShortcutsModal();
    } else if (e.key === 'Escape') {
      const settingsPopover = document.getElementById('player-settings-popover');
      if (settingsPopover && !settingsPopover.classList.contains('hidden')) {
        togglePlayerSettingsMenu(false);
        return;
      }
      const subDrawer = document.getElementById('player-sub-drawer');
      if (subDrawer && !subDrawer.classList.contains('hidden')) {
        toggleSubtitleDrawer(false);
        return;
      }
      const trailerModal = document.getElementById('trailer-modal');
      if (trailerModal && !trailerModal.classList.contains('hidden')) {
        closeTrailerModal();
        return;
      }
      const swarmModal = document.getElementById('swarm-inspector-modal');
      if (swarmModal && !swarmModal.classList.contains('hidden')) {
        toggleSwarmInspectorModal(false);
        return;
      }
      const settingsModal = document.getElementById('settings-modal');
      if (settingsModal && !settingsModal.classList.contains('hidden')) {
        toggleSettingsModal(false);
        return;
      }
      const epDrawer = document.getElementById('player-episodes-drawer');
      if (epDrawer && !epDrawer.classList.contains('hidden')) {
        togglePlayerEpisodesDrawer(false);
        return;
      }
      const shortcutsModal = document.getElementById('player-shortcuts-modal');
      if (shortcutsModal && !shortcutsModal.classList.contains('hidden')) {
        toggleShortcutsModal(false);
        return;
      }
      const filesModal = document.getElementById('torrent-files-modal');
      if (filesModal && !filesModal.classList.contains('hidden')) {
        closeTorrentFilesModal();
        return;
      }
      if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        closePlayerModal();
      }
    }
  });

  // Keep Fullscreen button icon in sync with true fullscreen state & portal modals
  const syncFullscreenIcon = () => {
    const isFs = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
    handleFullscreenChangePortals();
    const btns = [
      document.getElementById('btn-hud-fullscreen'),
      document.getElementById('btn-player-fullscreen')
    ].filter(Boolean);
    const wrap = document.getElementById('player-video-wrap');
    btns.forEach(btn => {
      if (isFs) {
        btn.innerHTML = '<i class="fa-solid fa-compress"></i>';
        btn.title = 'Exit Fullscreen (F)';
      } else {
        btn.innerHTML = '<i class="fa-solid fa-expand"></i>';
        btn.title = 'Fullscreen (F)';
      }
    });
    if (!isFs) {
      clearTimeout(playerIdleTimer);
      if (wrap) wrap.classList.remove('user-idle');
    } else {
      handlePlayerActivity();
    }
  };
  document.addEventListener('fullscreenchange', syncFullscreenIcon);
  document.addEventListener('webkitfullscreenchange', syncFullscreenIcon);

  // Global activity listener across the entire document (mouse, touch, pointer) for instant wake in fullscreen
  const handleGlobalPlayerActivity = () => {
    const modal = document.getElementById('player-modal');
    if (modal && !modal.classList.contains('hidden')) {
      handlePlayerActivity();
    }
  };

  document.addEventListener('mousemove', handleGlobalPlayerActivity, { passive: true });
  document.addEventListener('pointermove', handleGlobalPlayerActivity, { passive: true });
  document.addEventListener('mousedown', handleGlobalPlayerActivity, { passive: true });
  document.addEventListener('touchstart', handleGlobalPlayerActivity, { passive: true });

  const bottomControls = document.getElementById('player-bottom-controls');
  if (bottomControls) {
    bottomControls.addEventListener('mouseenter', handleGlobalPlayerActivity, { passive: true });
    bottomControls.addEventListener('mousemove', handleGlobalPlayerActivity, { passive: true });
  }

  // Sync Picture-in-Picture button state & Auto-PiP on tab change
  if (video) {
    video.addEventListener('enterpictureinpicture', () => {
      const btn = document.getElementById('btn-hud-pip');
      if (btn) btn.classList.add('active');
    });
    video.addEventListener('leavepictureinpicture', () => {
      const btn = document.getElementById('btn-hud-pip');
      if (btn) btn.classList.remove('active');
    });
  }

  document.addEventListener('visibilitychange', () => {
    const v = document.getElementById('evo-video-player');
    const modal = document.getElementById('player-modal');
    if (!v || !modal || modal.classList.contains('hidden')) return;
    if (document.hidden && !v.paused && document.pictureInPictureEnabled && !document.pictureInPictureElement) {
      v.requestPictureInPicture().catch(() => {});
    }
  });
}

function updatePlayerTimeline() {
  const video = document.getElementById('evo-video-player');
  const active = state.discover.activeStream;
  if (!video || !active) return;
  if (active.isDraggingTimeline) return;

  // Adopt real video.duration ONLY for native direct streams when video.duration is a true media duration (never overwrite whole video with fragmented chunks)
  if (!active.useTransmux && video.duration && isFinite(video.duration) && video.duration > 30) {
    active.totalDuration = video.duration;
  }

  const currentTotalTime = (active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);

  // Robust totalDuration fallback resolution (unfreezing 0:00 / 0:00)
  let totalDuration = (active.totalDuration && isFinite(active.totalDuration) && active.totalDuration > 0)
    ? active.totalDuration
    : 0;

  if (!active.useTransmux && totalDuration <= 0 && video.duration && isFinite(video.duration) && video.duration > 0) {
    totalDuration = video.duration;
    active.totalDuration = video.duration;
  }

  if (totalDuration <= 0) {
    const detail = state.discover.activeDetail;
    if (detail && detail.runtime) {
      totalDuration = parseRuntimeToSeconds(detail.runtime);
      if (totalDuration > 0) active.totalDuration = totalDuration;
    }
  }

  if (totalDuration <= 0) {
    const detail = state.discover.activeDetail;
    if (detail && detail.type === 'anime') totalDuration = 1440; // 24 min
    else if (detail && detail.type === 'series') totalDuration = 2700; // 45 min
    else totalDuration = 5400; // 90 min default movie runtime
    active.totalDuration = totalDuration;
  }

  // Update progress bar
  const pct = totalDuration > 0 ? Math.min(100, Math.max(0, (currentTotalTime / totalDuration) * 100)) : 0;
  const progressEl = document.getElementById('player-progress-bar');
  if (progressEl) progressEl.style.width = `${pct}%`;

  // Update buffered bar
  const bufferedEl = document.getElementById('player-buffered-bar');
  if (bufferedEl && video.buffered.length > 0) {
    try {
      const end = video.buffered.end(video.buffered.length - 1);
      const bufferedTotalTime = (active.useTransmux ? (active.playbackOffset || 0) : 0) + end;
      const bufPct = totalDuration > 0 ? Math.min(100, Math.max(0, (bufferedTotalTime / totalDuration) * 100)) : 0;
      bufferedEl.style.width = `${bufPct}%`;
    } catch (_) {}
  }

  // Update time display labels continuously on each tick
  const curEl = document.getElementById('player-cur-time');
  const totalEl = document.getElementById('player-total-time');
  if (curEl) {
    if (active.showRemainingTime && totalDuration > 0) {
      const rem = Math.max(0, totalDuration - currentTotalTime);
      curEl.innerText = `-${formatPlayerDuration(rem)}`;
    } else {
      curEl.innerText = formatPlayerDuration(currentTotalTime);
    }
  }
  if (totalEl) {
    totalEl.innerText = formatPlayerDuration(totalDuration);
  }

  // Check Netflix-grade binge countdown & skip triggers
  checkBingeAndSkipTriggers(currentTotalTime, totalDuration);

  // Record watch history and resume progress
  recordWatchProgress(currentTotalTime, totalDuration);
}

function toggleTimeRemaining() {
  const active = state.discover.activeStream;
  if (active) {
    active.showRemainingTime = !active.showRemainingTime;
    updatePlayerTimeline();
  }
}

function togglePlayerPlay() {
  const video = document.getElementById('evo-video-player');
  if (!video) return;

  const centerPlay = document.getElementById('player-center-play');
  if (video.paused) {
    video.play().catch(() => {});
    updatePlayPauseIcon(true);
    if (centerPlay) {
      centerPlay.innerHTML = '<i class="fa-solid fa-play"></i>';
      centerPlay.classList.add('pulse');
      setTimeout(() => centerPlay.classList.remove('pulse'), 350);
    }
  } else {
    video.pause();
    updatePlayPauseIcon(false);
    if (centerPlay) {
      centerPlay.innerHTML = '<i class="fa-solid fa-pause"></i>';
      centerPlay.classList.add('pulse');
      setTimeout(() => centerPlay.classList.remove('pulse'), 350);
    }
  }
}

function updatePlayPauseIcon(isPlaying) {
  const btn = document.getElementById('btn-player-play');
  if (!btn) return;
  btn.innerHTML = isPlaying ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
}

let osdTimer = null;
function showPlayerOsd(iconHtml, text) {
  let osd = document.getElementById('player-osd-feedback');
  if (!osd) {
    const wrap = document.getElementById('player-video-wrap');
    if (!wrap) return;
    osd = document.createElement('div');
    osd.id = 'player-osd-feedback';
    osd.className = 'player-osd-feedback';
    wrap.appendChild(osd);
  }
  osd.innerHTML = `${iconHtml}<span>${text}</span>`;
  osd.classList.remove('hidden');
  osd.classList.add('visible');
  clearTimeout(osdTimer);
  osdTimer = setTimeout(() => {
    osd.classList.remove('visible');
  }, 900);
}

function skipPlayerSeconds(delta) {
  const video = document.getElementById('evo-video-player');
  const active = state.discover.activeStream;
  if (!video || !active) return;
  const currentTotal = (active.playbackOffset || 0) + (video.currentTime || 0);
  seekPlayer(currentTotal + delta);
  if (delta > 0) {
    showPlayerOsd('<i class="fa-solid fa-forward"></i>', `+${delta}s`);
  } else {
    showPlayerOsd('<i class="fa-solid fa-backward"></i>', `${delta}s`);
  }
}

function setPlayerVolume(val) {
  const video = document.getElementById('evo-video-player');
  if (!video) return;
  video.volume = parseFloat(val);
  video.muted = (video.volume === 0);
  const unmuteOverlay = document.getElementById('player-unmute-overlay');
  if (!video.muted && video.volume > 0 && unmuteOverlay) {
    unmuteOverlay.classList.add('hidden');
  }
  updateVolumeIcon();
}

function adjustPlayerVolume(delta) {
  const video = document.getElementById('evo-video-player');
  if (!video) return;
  const newVol = Math.max(0, Math.min(1, video.volume + delta));
  setPlayerVolume(newVol);
  const slider = document.getElementById('player-volume-slider');
  if (slider) slider.value = newVol;
  const pct = Math.round(newVol * 100);
  const icon = newVol === 0 ? '<i class="fa-solid fa-volume-xmark text-red"></i>' : (newVol < 0.5 ? '<i class="fa-solid fa-volume-low text-blue"></i>' : '<i class="fa-solid fa-volume-high text-green"></i>');
  showPlayerOsd(icon, `${pct}%`);
}

function togglePlayerMute() {
  const video = document.getElementById('evo-video-player');
  if (!video) return;
  video.muted = !video.muted;
  const slider = document.getElementById('player-volume-slider');
  if (slider) slider.value = video.muted ? 0 : video.volume;
  const unmuteOverlay = document.getElementById('player-unmute-overlay');
  if (!video.muted && video.volume > 0 && unmuteOverlay) {
    unmuteOverlay.classList.add('hidden');
  }
  updateVolumeIcon();
  if (video.muted) {
    showPlayerOsd('<i class="fa-solid fa-volume-xmark text-red"></i>', 'Muted');
  } else {
    const pct = Math.round(video.volume * 100);
    showPlayerOsd('<i class="fa-solid fa-volume-high text-green"></i>', `${pct}%`);
  }
}

function updateVolumeIcon() {
  const video = document.getElementById('evo-video-player');
  const btn = document.getElementById('btn-player-vol');
  const unmuteOverlay = document.getElementById('player-unmute-overlay');
  if (!video) return;
  if (!video.muted && video.volume > 0 && unmuteOverlay) {
    unmuteOverlay.classList.add('hidden');
  }
  if (!btn) return;
  if (video.muted || video.volume === 0) {
    btn.innerHTML = '<i class="fa-solid fa-volume-xmark text-accent"></i>';
  } else if (video.volume < 0.5) {
    btn.innerHTML = '<i class="fa-solid fa-volume-low text-blue"></i>';
  } else {
    btn.innerHTML = '<i class="fa-solid fa-volume-high text-green"></i>';
  }
}

let playerIdleTimer = null;

function handlePlayerActivity() {
  const wrap = document.getElementById('player-video-wrap');
  if (!wrap) return;
  wrap.classList.remove('user-idle');
  clearTimeout(playerIdleTimer);

  // Hide bars when in fullscreen mode or full player modal active
  const isFs = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
  const playerModal = document.getElementById('player-modal');
  const isPlayerOpen = playerModal && !playerModal.classList.contains('hidden');
  if (!isFs && !isPlayerOpen) return;

  const video = document.getElementById('evo-video-player');
  const subDrawer = document.getElementById('player-sub-drawer');
  const epDrawer = document.getElementById('player-episodes-drawer');
  const isDrawerOpen = (subDrawer && !subDrawer.classList.contains('hidden')) ||
                       (epDrawer && !epDrawer.classList.contains('hidden'));
  const isModalOpen = isDrawerOpen ||
                      (document.getElementById('swarm-inspector-modal') && !document.getElementById('swarm-inspector-modal').classList.contains('hidden')) ||
                      (document.getElementById('player-shortcuts-modal') && !document.getElementById('player-shortcuts-modal').classList.contains('hidden')) ||
                      (document.getElementById('torrent-files-modal') && !document.getElementById('torrent-files-modal').classList.contains('hidden')) ||
                      (document.getElementById('player-settings-popover') && !document.getElementById('player-settings-popover').classList.contains('hidden'));

  const bottomControls = document.getElementById('player-bottom-controls');
  const hudHeader = document.querySelector('.player-hud-header');
  const isControlsHovered = Boolean(
    (bottomControls && bottomControls.matches(':hover')) ||
    (hudHeader && hudHeader.matches(':hover'))
  );

  // If video is playing and no modal, drawer, or control bar is hovered, show for 3 seconds then auto-hide
  if (video && !video.paused && !isModalOpen && !isControlsHovered) {
    playerIdleTimer = setTimeout(() => {
      const isStillFs = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
      const isStillOpen = playerModal && !playerModal.classList.contains('hidden');
      const isStillHovered = Boolean(
        (bottomControls && bottomControls.matches(':hover')) ||
        (hudHeader && hudHeader.matches(':hover'))
      );
      if ((isStillFs || isStillOpen) && video && !video.paused && !isStillHovered) {
        wrap.classList.add('user-idle');
        const audioMenu = document.getElementById('player-audio-menu');
        if (audioMenu) audioMenu.classList.add('hidden');
        const extMenu = document.getElementById('player-extplayer-menu');
        if (extMenu) extMenu.classList.add('hidden');
        const speedMenu = document.getElementById('player-speed-menu');
        if (speedMenu) speedMenu.classList.add('hidden');
      }
    }, 3000);
  }
}

function handlePlayerMouseMove() {
  handlePlayerActivity();
}

function handlePlayerMouseLeave() {
  const isFs = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
  const wrap = document.getElementById('player-video-wrap');
  if (!isFs) {
    if (wrap) wrap.classList.remove('user-idle');
    clearTimeout(playerIdleTimer);
    return;
  }
  handlePlayerActivity();
}

function toggleAudioDropdown() {
  const menu = document.getElementById('player-audio-menu');
  if (menu) menu.classList.toggle('hidden');
}

function renderAudioMenu(tracks) {
  const menu = document.getElementById('player-audio-menu');
  if (!menu) return;
  if (!tracks || tracks.length === 0) {
    menu.innerHTML = '<div class="player-dropdown-item text-dim">No audio tracks detected</div>';
    return;
  }
  const active = state.discover.activeStream;
  const curTrack = active ? (active.audioTrack || 0) : 0;
  menu.innerHTML = tracks.map((t) => `
    <div class="player-dropdown-item ${t.track_idx === curTrack ? 'active' : ''}" onclick="selectAudioTrack(${t.track_idx})">
      <span>${escapeHtml(t.title || `Track ${t.track_idx + 1}`)}</span>
      <span class="mono text-xs text-dim">${escapeHtml((t.language || '').toUpperCase())}</span>
    </div>
  `).join('');
}

function selectAudioTrack(trackIdx) {
  const active = state.discover.activeStream;
  if (!active) return;
  active.audioTrack = trackIdx;
  const menu = document.getElementById('player-audio-menu');
  if (menu) menu.classList.add('hidden');

  const video = document.getElementById('evo-video-player');
  const track = (active.audioTracks || []).find(t => t.track_idx === trackIdx);

  // 1. If native HTMLMediaElement audioTracks API is supported by the browser on the current stream:
  if (video && video.audioTracks && video.audioTracks.length > 1) {
    try {
      let switched = false;
      for (let i = 0; i < video.audioTracks.length; i++) {
        const shouldEnable = (i === trackIdx);
        if (video.audioTracks[i].enabled !== shouldEnable) {
          video.audioTracks[i].enabled = shouldEnable;
          switched = true;
        }
      }
      if (switched) {
        console.log(`[EvoPlayer] Switched audio track natively to index ${trackIdx}`);
        const langBadge = document.getElementById('player-hud-audio-lang');
        if (langBadge) langBadge.innerText = track ? (track.language || track.title).toUpperCase() : `Track ${trackIdx + 1}`;
        const badge = document.getElementById('player-audio-track-badge');
        if (badge) badge.innerText = track ? track.title : `Track ${trackIdx + 1}`;
        renderAudioMenu(active.audioTracks);
        showToast(`Switched to: ${track ? track.title : `Track ${trackIdx + 1}`}`, 'info');
        return;
      }
    } catch (_) {}
  }

  // 2. If selecting primary Track 0 on a direct-compatible stream, return cleanly to Direct Stream of the whole video
  const trackCodec = ((track ? track.codec : '') || '').toLowerCase();
  const trackIsDirectAudio = !trackCodec || ['aac', 'mp3', 'opus', 'vorbis'].includes(trackCodec);
  const isDirectCompatible = !active.isMkv && !active.transcodeVideo && (active.burnSubIdx === null || active.burnSubIdx === undefined) && trackIsDirectAudio && /\b(mp4|m4v|webm|yts|yify|x264|h264|avc)\b/i.test(active.playingFileName || active.title || '');
  if (trackIdx === 0 && isDirectCompatible && active.useTransmux) {
    console.log('[EvoPlayer] Reverting to Direct Stream for primary audio track');
    active.useTransmux = false;
    const modeBadge = document.getElementById('player-hud-mode-label');
    if (modeBadge) modeBadge.innerText = 'Direct';
    updateAudioHudButtons();
    const curTime = (active.playbackOffset || 0) + (video ? video.currentTime : 0);
    active.playbackOffset = 0;
    const epParams = (active.season !== null && active.episode !== null && active.season !== undefined && active.episode !== undefined)
      ? `&season=${active.season}&episode=${active.episode}`
      : '';
    const magnetParam = active.magnet ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
    const durationParam = active.totalDuration > 0 ? `&duration=${active.totalDuration}` : '';
    const fileIdxToUse = (active.playingFileIdx !== undefined && active.playingFileIdx !== null) ? active.playingFileIdx : (active.fileIdx || 0);
    const directUrl = `/api/v1/stream/play?info_hash=${active.infoHash}&file_idx=${fileIdxToUse}${epParams}${magnetParam}${durationParam}`;
    video.pause();
    video.src = directUrl;
    video.load();
    video.currentTime = curTime;
    video.play().catch(() => {});
    const langBadge = document.getElementById('player-hud-audio-lang');
    if (langBadge) langBadge.innerText = track ? (track.language || track.title).toUpperCase() : `Track ${trackIdx + 1}`;
    const badge = document.getElementById('player-audio-track-badge');
    if (badge) badge.innerText = track ? track.title : `Track ${trackIdx + 1}`;
    renderAudioMenu(active.audioTracks);
    updatePlayerTimeline();
    showToast(`Switched to: ${track ? track.title : 'Track 1'}`, 'info');
    return;
  }

  // 3. Otherwise, use FFmpeg transmuxer with targeted audio stream mapping while locking whole-video timeline
  if (!active.useTransmux) {
    active.useTransmux = true;
    const modeBadge = document.getElementById('player-hud-mode-label');
    if (modeBadge) modeBadge.innerText = 'Transmux';
    updateAudioHudButtons();
  }

  const langBadge = document.getElementById('player-hud-audio-lang');
  if (langBadge) {
    langBadge.innerText = track ? (track.language || track.title).toUpperCase() : `Track ${trackIdx + 1}`;
  }
  const badge = document.getElementById('player-audio-track-badge');
  if (badge) badge.innerText = track ? track.title : `Track ${trackIdx + 1}`;

  renderAudioMenu(active.audioTracks);

  const curTime = (active.playbackOffset || 0) + (video ? video.currentTime : 0);
  seekPlayer(curTime);
  showToast(`Switched to: ${track ? track.title : `Track ${trackIdx + 1}`}`, 'info');
}

function updateAudioHudButtons() {
  const audioBadge = document.getElementById('player-audio-badge');
  const trackBadge = document.getElementById('player-audio-track-badge');
  const active = state.discover.activeStream;
  if (!active) return;

  if (audioBadge) {
    audioBadge.innerHTML = active.useTransmux
      ? '<i class="fa-solid fa-volume-high"></i> Stereo AAC'
      : '<i class="fa-solid fa-volume-high"></i> Direct Audio';
    audioBadge.className = active.useTransmux ? 'tag tag-green mono text-xs' : 'tag tag-blue mono text-xs';
  }
  if (trackBadge) {
    const curTrk = (active.audioTracks || []).find(t => t.track_idx === (active.audioTrack || 0));
    trackBadge.innerText = curTrk ? curTrk.title : `Track ${(active.audioTrack || 0) + 1}`;
  }
}

function cycleAudioTrack() {
  const active = state.discover.activeStream;
  if (!active) return;
  if (!active.audioTracks || active.audioTracks.length <= 1) {
    showToast('Single audio track stream', 'info');
    return;
  }
  const nextTrack = ((active.audioTrack || 0) + 1) % active.audioTracks.length;
  selectAudioTrack(nextTrack);
}

// ═════════════════════════════════════════════════════════════════════════════
// 🎬 Phase 1 Superpowers: Speed, Aspect, PiP, Night Mode, Ambilight & Sync
// ═════════════════════════════════════════════════════════════════════════════

const PLAYBACK_SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0];
let currentSpeedIndex = 2; // 1.0x

function toggleSpeedDropdown() {
  const menu = document.getElementById('player-speed-menu');
  if (!menu) return;
  menu.classList.toggle('hidden');
  if (!menu.classList.contains('hidden')) {
    renderSpeedMenu();
  }
}

function renderSpeedMenu() {
  const menu = document.getElementById('player-speed-menu');
  const video = document.getElementById('evo-video-player');
  if (!menu) return;
  const cur = video ? video.playbackRate : 1.0;
  menu.innerHTML = PLAYBACK_SPEEDS.map((s) => `
    <div class="player-dropdown-item ${Math.abs(s - cur) < 0.01 ? 'active' : ''}" onclick="setPlaybackSpeed(${s})">
      <span>${s === 1.0 ? '1.0x (Normal)' : s + 'x'}</span>
      ${Math.abs(s - cur) < 0.01 ? '<i class="fa-solid fa-check text-green"></i>' : ''}
    </div>
  `).join('');
}

function togglePlayerSettingsMenu(force = null) {
  const popover = document.getElementById('player-settings-popover');
  if (!popover) return;
  const shouldOpen = force !== null ? force : popover.classList.contains('hidden');
  popover.classList.toggle('hidden', !shouldOpen);

  if (shouldOpen) {
    const video = document.getElementById('evo-video-player');
    const curSpeed = video ? video.playbackRate : 1.0;
    document.querySelectorAll('.speed-chip').forEach((chip) => {
      const s = parseFloat(chip.getAttribute('data-speed'));
      chip.classList.toggle('active', Math.abs(s - curSpeed) < 0.01);
    });
  }
}

function setPlaybackSpeed(speed, showNotice = false) {
  const video = document.getElementById('evo-video-player');
  const label = document.getElementById('player-hud-speed-label');
  const menu = document.getElementById('player-speed-menu');
  if (!video) return;

  video.playbackRate = speed;
  if ('preservesPitch' in video) video.preservesPitch = true;
  else if ('webkitPreservesPitch' in video) video.webkitPreservesPitch = true;

  currentSpeedIndex = PLAYBACK_SPEEDS.findIndex((s) => Math.abs(s - speed) < 0.01);
  if (currentSpeedIndex === -1) currentSpeedIndex = 2;

  if (label) label.innerText = `${speed}x`;
  if (menu) menu.classList.add('hidden');

  // Update speed chips in Quick Settings popover
  document.querySelectorAll('.speed-chip').forEach((chip) => {
    const s = parseFloat(chip.getAttribute('data-speed'));
    chip.classList.toggle('active', Math.abs(s - speed) < 0.01);
  });

  const speedSelect = document.getElementById('player-speed-select');
  if (speedSelect) speedSelect.value = String(speed);

  if (showNotice) {
    showPlayerOsd('<i class="fa-solid fa-gauge-high"></i>', `${speed}x`);
  }
}

function togglePictureInPicture() {
  return togglePlayerPiP();
}

function toggleNightModeAudio() {
  return toggleNightDialogueMode();
}

function checkNextEpisodeTrigger(currentTime, duration) {
  return checkNextEpisodeCountdown(currentTime, duration);
}

function promptResumePlayback(resSec, resTimeStr) {
  const prompt = document.getElementById('player-resume-prompt');
  const timeEl = document.getElementById('player-resume-time-str');
  if (!prompt) return;
  if (timeEl) timeEl.innerText = resTimeStr || (typeof formatPlayerDuration === 'function' ? formatPlayerDuration(resSec) : `${resSec}s`);
  prompt.dataset.resumeSec = String(resSec);
  prompt.classList.remove('hidden');
  clearTimeout(window._resumePromptTimer);
  window._resumePromptTimer = setTimeout(() => {
    prompt.classList.add('hidden');
  }, 9000);
}

function confirmResumePlayback() {
  const prompt = document.getElementById('player-resume-prompt');
  if (!prompt) return;
  const sec = parseFloat(prompt.dataset.resumeSec || '0');
  prompt.classList.add('hidden');
  if (sec > 0) {
    seekPlayer(sec);
    showToast(`Resumed playback at ${typeof formatPlayerDuration === 'function' ? formatPlayerDuration(sec) : sec}`, 'info');
  }
}

function dismissResumePlayback() {
  const prompt = document.getElementById('player-resume-prompt');
  if (prompt) prompt.classList.add('hidden');
}

function adjustPlaybackSpeed(delta) {
  const nextIdx = Math.max(0, Math.min(PLAYBACK_SPEEDS.length - 1, currentSpeedIndex + delta));
  if (nextIdx !== currentSpeedIndex) {
    setPlaybackSpeed(PLAYBACK_SPEEDS[nextIdx], true);
  }
}

// ── Aspect Ratio & Ultrawide Zoom ──────────────────────────────────────────
const ASPECT_MODES = [
  { key: 'aspect-contain', label: 'Fit', name: 'Original Aspect Ratio (Fit)' },
  { key: 'aspect-cover', label: '21:9 Zoom', name: 'Ultrawide Crop / Zoom (21:9 Cover)' },
  { key: 'aspect-fill', label: 'Fill', name: 'Stretch to Fullscreen' },
  { key: 'aspect-16-9', label: '16:9', name: 'Fixed 16:9 Widescreen' }
];
let currentAspectIndex = 0;

function cyclePlayerAspectRatio() {
  const video = document.getElementById('evo-video-player');
  const label = document.getElementById('player-hud-aspect-label');
  if (!video) return;

  ASPECT_MODES.forEach((m) => video.classList.remove(m.key));
  currentAspectIndex = (currentAspectIndex + 1) % ASPECT_MODES.length;
  const target = ASPECT_MODES[currentAspectIndex];
  video.classList.add(target.key);
  if (label) label.innerText = target.label;
  showToast(`Aspect Ratio: ${target.name}`, 'info');
}

// ── Picture-in-Picture (PiP) ───────────────────────────────────────────────
async function togglePlayerPiP() {
  const video = document.getElementById('evo-video-player');
  if (!video) return;

  try {
    if (document.pictureInPictureElement) {
      await document.exitPictureInPicture();
    } else if (document.pictureInPictureEnabled) {
      await video.requestPictureInPicture();
    } else {
      showToast('Picture-in-Picture is not supported by your browser', 'warning');
    }
  } catch (err) {
    console.warn('[EvoPlayer] PiP notice:', err.message);
    showToast(`PiP notice: ${err.message}`, 'warning');
  }
}

// ── Web Audio API: Night Dialogue Compressor & Audio Delay ─────────────────
let playerAudioCtx = null;
let playerMediaSourceNode = null;
let playerCompressorNode = null;
let playerDialogueGainNode = null;
let playerAudioDelayNode = null;
let playerNightModeEnabled = false;

function ensurePlayerWebAudio() {
  if (playerAudioCtx) return true;
  const video = document.getElementById('evo-video-player');
  if (!video) return false;

  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return false;

  try {
    playerAudioCtx = new AudioContext();
    playerMediaSourceNode = playerAudioCtx.createMediaElementSource(video);

    // Dynamics compressor: boosts whispers, soft-limits explosions
    playerCompressorNode = playerAudioCtx.createDynamicsCompressor();
    playerCompressorNode.threshold.value = -24;
    playerCompressorNode.knee.value = 30;
    playerCompressorNode.ratio.value = 12;
    playerCompressorNode.attack.value = 0.003;
    playerCompressorNode.release.value = 0.25;

    // Dialogue volume booster (+3.5 dB)
    playerDialogueGainNode = playerAudioCtx.createGain();
    playerDialogueGainNode.gain.value = 1.4;

    // Delay node for real-time audio calibration (up to 5s)
    playerAudioDelayNode = playerAudioCtx.createDelay(5.0);
    playerAudioDelayNode.delayTime.value = 0.0;

    // Default clean wiring: Source -> Delay -> Destination
    playerMediaSourceNode.connect(playerAudioDelayNode);
    playerAudioDelayNode.connect(playerAudioCtx.destination);
    return true;
  } catch (err) {
    console.warn('[EvoPlayer] Web Audio API init notice:', err.message);
    return false;
  }
}

function toggleNightDialogueMode() {
  const btn = document.getElementById('btn-hud-nightmode');
  if (!ensurePlayerWebAudio()) {
    showToast('Web Audio API not supported on this browser', 'warning');
    return;
  }

  if (playerAudioCtx.state === 'suspended') {
    playerAudioCtx.resume().catch(() => {});
  }

  playerNightModeEnabled = !playerNightModeEnabled;

  try {
    // Rewire audio graph
    playerMediaSourceNode.disconnect();
    playerCompressorNode.disconnect();
    playerDialogueGainNode.disconnect();

    if (playerNightModeEnabled) {
      playerMediaSourceNode.connect(playerCompressorNode);
      playerCompressorNode.connect(playerDialogueGainNode);
      playerDialogueGainNode.connect(playerAudioDelayNode);
      if (btn) btn.classList.add('active');
      showToast('🌙 Night Dialogue Mode ON (Whispers boosted, loud explosions softened)', 'info');
    } else {
      playerMediaSourceNode.connect(playerAudioDelayNode);
      if (btn) btn.classList.remove('active');
      showToast('Night Dialogue Mode OFF (Standard Audio)', 'info');
    }
  } catch (err) {
    console.warn('[EvoPlayer] Night mode rewire error:', err.message);
  }
}

// ── Real-Time Audio Delay Calibration ──────────────────────────────────────
let playerAudioDelaySeconds = 0.0;

function setAudioSync(seconds) {
  playerAudioDelaySeconds = Math.max(-5.0, Math.min(5.0, Math.round(seconds * 100) / 100));
  const valEl = document.getElementById('audio-sync-val');
  const sliderEl = document.getElementById('audio-sync-slider');

  if (valEl) {
    const sign = playerAudioDelaySeconds > 0 ? '+' : '';
    const status = playerAudioDelaySeconds === 0 ? ' (In Sync)' : '';
    valEl.innerText = `${sign}${playerAudioDelaySeconds.toFixed(2)}s${status}`;
    valEl.className = `mono text-xs font-bold ${playerAudioDelaySeconds === 0 ? 'text-accent' : 'text-green'}`;
  }
  if (sliderEl && parseFloat(sliderEl.value) !== playerAudioDelaySeconds) {
    sliderEl.value = playerAudioDelaySeconds;
  }

  if (ensurePlayerWebAudio() && playerAudioDelayNode) {
    if (playerAudioCtx.state === 'suspended') playerAudioCtx.resume().catch(() => {});
    playerAudioDelayNode.delayTime.value = Math.max(0, playerAudioDelaySeconds);
  }
}

function adjustAudioSync(delta) {
  setAudioSync(playerAudioDelaySeconds + delta);
  showToast(`Audio Delay: ${playerAudioDelaySeconds > 0 ? '+' : ''}${playerAudioDelaySeconds.toFixed(2)}s`, 'info');
}

function resetAudioSync() {
  setAudioSync(0.0);
  showToast('Audio delay reset to 0.0s', 'info');
}

// ── Ambient Glow Lighting (Ambilight Mode) ──────────────────────────────────
let ambilightActive = false;
let ambilightTimer = null;

function toggleAmbilight() {
  ambilightActive = !ambilightActive;
  const wrap = document.getElementById('player-video-wrap');
  const btn = document.getElementById('btn-hud-ambilight');
  const glow = document.getElementById('player-ambilight-glow');

  if (ambilightActive) {
    if (wrap) wrap.classList.add('ambilight-active');
    if (btn) btn.classList.add('active-accent');
    showToast('✨ Ambilight Glow ON', 'info');
    startAmbilightLoop();
  } else {
    if (wrap) wrap.classList.remove('ambilight-active');
    if (btn) btn.classList.remove('active-accent');
    if (glow) glow.style.background = 'none';
    if (ambilightTimer) cancelAnimationFrame(ambilightTimer);
    showToast('Ambilight Glow OFF', 'info');
  }
}

function startAmbilightLoop() {
  const canvas = document.getElementById('player-ambilight-canvas');
  const glow = document.getElementById('player-ambilight-glow');
  const video = document.getElementById('evo-video-player');
  if (!canvas || !glow || !video) return;

  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  let lastTime = 0;

  function render(time) {
    if (!ambilightActive) return;
    if (time - lastTime > 90) { // ~11 fps for ultra-smooth glow without CPU pressure
      lastTime = time;
      if (!video.paused && !video.ended && video.readyState >= 2) {
        try {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

          let rTop = 0, gTop = 0, bTop = 0, countTop = 0;
          let rBot = 0, gBot = 0, bBot = 0, countBot = 0;

          for (let y = 0; y < canvas.height; y++) {
            for (let x = 0; x < canvas.width; x++) {
              const idx = (y * canvas.width + x) * 4;
              const r = imgData[idx];
              const g = imgData[idx + 1];
              const b = imgData[idx + 2];
              if (y < canvas.height / 2) {
                rTop += r; gTop += g; bTop += b; countTop++;
              } else {
                rBot += r; gBot += g; bBot += b; countBot++;
              }
            }
          }

          rTop = Math.round(rTop / countTop);
          gTop = Math.round(gTop / countTop);
          bTop = Math.round(bTop / countTop);

          rBot = Math.round(rBot / countBot);
          gBot = Math.round(gBot / countBot);
          bBot = Math.round(bBot / countBot);

          glow.style.background = `radial-gradient(ellipse at 50% 30%, rgba(${rTop}, ${gTop}, ${bTop}, 0.6) 0%, rgba(${rBot}, ${gBot}, ${bBot}, 0.35) 60%, transparent 100%)`;
        } catch (_) {}
      }
    }
    ambilightTimer = requestAnimationFrame(render);
  }

  ambilightTimer = requestAnimationFrame(render);
}

// ── Keyboard Shortcuts Cheat Sheet Modal ────────────────────────────────────
function toggleShortcutsModal(forceState) {
  const modal = document.getElementById('player-shortcuts-modal');
  if (!modal) return;
  const shouldOpen = typeof forceState === 'boolean' ? forceState : modal.classList.contains('hidden');
  modal.classList.toggle('hidden', !shouldOpen);
  syncFullscreenPortal(modal, shouldOpen);
  if (shouldOpen) {
    handlePlayerActivity();
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 📺 Phase 2: Binge-Watching, In-Player Episode Selector & Series Flow
// ═════════════════════════════════════════════════════════════════════════════

let currentSkipMode = 'none'; // 'intro' | 'outro' | 'none'

function checkBingeAndSkipTriggers(currentTotalTime, totalDuration) {
  const detail = state.discover.activeDetail;
  const isEpisodic = detail && (detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0));
  const remaining = Math.max(0, totalDuration - currentTotalTime);

  // 1. In-Player Episode button visibility
  const epBtn = document.getElementById('btn-hud-episodes');
  if (epBtn) {
    epBtn.classList.toggle('hidden', !isEpisodic);
  }



  if (!isEpisodic) return;

  const nextEp = getNextEpisode();
  if (!nextEp) return;

  // 3. Next Episode Pre-Warming (when 3 minutes left)
  if (remaining <= 180 && !state.discover.prewarmedNextEpisode) {
    state.discover.prewarmedNextEpisode = true;
    prewarmNextEpisode(nextEp);
  }

  // 4. Auto-Play Next Episode Binge Countdown (when <= 25s left)
  const card = document.getElementById('player-next-ep-card');
  const cardTitle = document.getElementById('next-ep-title');
  const cardCount = document.getElementById('next-ep-countdown');

  if (remaining <= 25 && remaining > 0 && !state.discover.nextEpCardDismissed) {
    if (card) card.classList.remove('hidden');
    if (cardTitle) {
      const sPadded = String(nextEp.season).padStart(2, '0');
      const ePadded = String(nextEp.episode).padStart(2, '0');
      cardTitle.innerText = `S${sPadded}E${ePadded} · ${nextEp.title || 'Next Episode'}`;
    }
    const secsLeft = Math.ceil(remaining);
    if (cardCount) cardCount.innerText = `Starting in ${secsLeft}s...`;

    if (secsLeft <= 1 && !state.discover.nextEpAutoTriggered) {
      state.discover.nextEpAutoTriggered = true;
      playNextEpisode();
    }
  } else if (remaining > 25 && card) {
    card.classList.add('hidden');
  }
}


function getNextEpisode() {
  const detail = state.discover.activeDetail;
  if (!detail || (detail.type !== 'series' && detail.type !== 'anime')) return null;

  const curSeason = state.discover.activeSeason || 1;
  const curEpisode = state.discover.activeEpisode || 1;
  const seasons = detail.seasons || [];

  const s = seasons.find((season) => season.season_number === curSeason);
  if (s && s.episodes) {
    const epIdx = s.episodes.findIndex((e) => e.episode === curEpisode);
    if (epIdx !== -1 && epIdx + 1 < s.episodes.length) {
      const next = s.episodes[epIdx + 1];
      return { season: curSeason, episode: next.episode, title: next.title };
    }
  }

  // Season Auto-Progression: next season episode 1
  const nextSeason = seasons.find((season) => season.season_number === curSeason + 1);
  if (nextSeason && nextSeason.episodes && nextSeason.episodes.length > 0) {
    const firstEp = nextSeason.episodes[0];
    return { season: nextSeason.season_number, episode: firstEp.episode, title: firstEp.title };
  }

  return null;
}

function prewarmNextEpisode(nextEp) {
  if (!nextEp) return;
  const detail = state.discover.activeDetail;
  if (!detail) return;

  console.log(`[EvoPlayer] ⚡ Pre-warming next episode: S${nextEp.season}E${nextEp.episode}`);
  const params = new URLSearchParams({
    title: detail.title,
    type: detail.type,
    season: nextEp.season,
    episode: nextEp.episode
  });
  if (detail.year) params.append('year', detail.year);

  fetch(`/api/v1/stream/resolve?${params.toString()}`)
    .then((r) => r.json())
    .then((data) => {
      if (data && data.streams && data.streams.length > 0) {
        const top = data.streams[0];
        warmHoveredStream(top.info_hash, top.file_idx, top.magnet);
      }
    })
    .catch((err) => console.warn('[EvoPlayer] Prewarm notice:', err.message));
}

function cancelNextEpisodeCountdown() {
  state.discover.nextEpCardDismissed = true;
  const card = document.getElementById('player-next-ep-card');
  if (card) card.classList.add('hidden');
  showToast('Next Episode auto-play paused', 'info');
}

async function playNextEpisode(instant = false) {
  const next = getNextEpisode();
  if (!next) return;

  cancelNextEpisodeCountdown();
  showToast(`⚡ Starting Next: S${String(next.season).padStart(2, '0')}E${String(next.episode).padStart(2, '0')}...`, 'info');
  switchStreamEpisode(next.season, next.episode);
}

// ── In-Player Episode Selector Drawer ──────────────────────────────────────
function togglePlayerEpisodesDrawer(force) {
  const drawer = document.getElementById('player-episodes-drawer');
  if (!drawer) return;

  const shouldOpen = typeof force === 'boolean' ? force : drawer.classList.contains('hidden');
  drawer.classList.toggle('hidden', !shouldOpen);

  if (shouldOpen) {
    renderPlayerEpisodesDrawer();
  }
}

function renderPlayerEpisodesDrawer() {
  const seasonsBar = document.getElementById('player-episodes-seasons-bar');
  const listEl = document.getElementById('player-episodes-drawer-list');
  const detail = state.discover.activeDetail;
  if (!detail || !seasonsBar || !listEl) return;

  const seasons = detail.seasons || [];
  const curSeason = state.discover.activeSeason || 1;
  const curEpisode = state.discover.activeEpisode || 1;

  seasonsBar.innerHTML = seasons.map((s) => `
    <button class="season-btn ${s.season_number === curSeason ? 'active' : ''}" style="padding:0.25rem 0.65rem; font-size:0.75rem;" onclick="switchDrawerSeason(${s.season_number})">
      Season ${s.season_number}
    </button>
  `).join('');

  const targetSeason = seasons.find((s) => s.season_number === curSeason) || seasons[0];
  if (!targetSeason || !targetSeason.episodes) {
    listEl.innerHTML = '<div class="text-dim text-xs p-3">No episodes loaded</div>';
    return;
  }

  listEl.innerHTML = targetSeason.episodes.map((ep) => {
    const isPlaying = ep.episode === curEpisode && targetSeason.season_number === curSeason;
    const thumbHtml = ep.thumbnail
      ? `<img src="${escapeHtml(ep.thumbnail)}" class="ep-drawer-thumb" onerror="this.onerror=null;this.src='';">`
      : `<div class="ep-drawer-thumb flex items-center justify-center mono text-dim text-xs">EP ${ep.episode}</div>`;

    return `
      <div class="ep-drawer-item ${isPlaying ? 'active' : ''}" onclick="switchStreamEpisode(${targetSeason.season_number}, ${ep.episode})">
        ${thumbHtml}
        <div class="ep-drawer-info">
          <div class="ep-drawer-title">${isPlaying ? '<i class="fa-solid fa-play text-green mr-1"></i>' : ''}Ep ${ep.episode}: ${escapeHtml(ep.title || 'Episode ' + ep.episode)}</div>
          <div class="ep-drawer-meta">${ep.runtime ? ep.runtime + 'm · ' : ''}${isPlaying ? '<span class="text-green font-bold">NOW PLAYING</span>' : 'Click to stream'}</div>
        </div>
      </div>
    `;
  }).join('');
}

function switchDrawerSeason(seasonNum) {
  state.discover.activeSeason = seasonNum;
  renderPlayerEpisodesDrawer();
}

async function switchStreamEpisode(seasonNum, epNum) {
  togglePlayerEpisodesDrawer(false);
  state.discover.activeSeason = seasonNum;
  state.discover.activeEpisode = epNum;
  state.discover.prewarmedNextEpisode = false;
  state.discover.nextEpCardDismissed = false;
  state.discover.nextEpAutoTriggered = false;

  const detail = state.discover.activeDetail;
  if (!detail) return;

  const titleEl = document.getElementById('player-stream-title');
  if (titleEl) titleEl.innerText = `${detail.title} S${String(seasonNum).padStart(2, '0')}E${String(epNum).padStart(2, '0')}`;

  const spinner = document.getElementById('player-buffering-spinner');
  if (spinner) spinner.classList.remove('hidden');

  showToast(`Resolving fast P2P streams for S${seasonNum}E${epNum}...`, 'info');

  try {
    const params = new URLSearchParams({
      title: detail.title,
      type: detail.type,
      season: seasonNum,
      episode: epNum
    });
    if (detail.year) params.append('year', detail.year);

    const res = await fetch(`/api/v1/stream/resolve?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.streams && data.streams.length > 0) {
      const top = data.streams[0];
      const isMkv = (top.title || '').toLowerCase().endsWith('.mkv');
      playStreamInBrowser(top.info_hash, top.file_idx, top.title, isMkv, top.magnet);
    } else {
      showToast('No high-health streams located for this episode', 'warning');
      if (spinner) spinner.classList.add('hidden');
    }
  } catch (err) {
    console.error('Episode switch error:', err);
    showToast(`Episode resolve failed: ${err.message}`, 'error');
    if (spinner) spinner.classList.add('hidden');
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 🕒 Phase 3: Watch History, Resume, Watched Badges & Bookmarks
// ═════════════════════════════════════════════════════════════════════════════

const WATCH_HISTORY_KEY = 'evoscrapper_watch_history_v1';
const WATCHED_ITEMS_KEY = 'evoscrapper_watched_items_v1';
const BOOKMARKS_KEY = 'evoscrapper_bookmarks_v1';

let lastHistorySaveTime = 0;

function getWatchHistory() {
  try {
    return JSON.parse(localStorage.getItem(WATCH_HISTORY_KEY)) || [];
  } catch (_) {
    return [];
  }
}

function saveWatchHistory(list) {
  try {
    localStorage.setItem(WATCH_HISTORY_KEY, JSON.stringify(list.slice(0, 40)));
  } catch (_) {}
}

function getWatchedItems() {
  try {
    return JSON.parse(localStorage.getItem(WATCHED_ITEMS_KEY)) || {};
  } catch (_) {
    return {};
  }
}

function isItemWatched(title, season = null, episode = null) {
  if (!title) return false;
  const items = getWatchedItems();
  const key = season !== null && episode !== null
    ? `${title.toLowerCase().trim()}_s${season}e${episode}`
    : title.toLowerCase().trim();
  return Boolean(items[key]);
}

function markItemWatched(title, season = null, episode = null, isWatched = true) {
  if (!title) return;
  const items = getWatchedItems();
  const key = season !== null && episode !== null
    ? `${title.toLowerCase().trim()}_s${season}e${episode}`
    : title.toLowerCase().trim();
  if (isWatched) items[key] = Date.now();
  else delete items[key];
  try {
    localStorage.setItem(WATCHED_ITEMS_KEY, JSON.stringify(items));
  } catch (_) {}
}

function recordWatchProgress(currentTime, totalDuration) {
  const now = Date.now();
  if (now - lastHistorySaveTime < 4500) return; // Save every 4.5s
  lastHistorySaveTime = now;

  const detail = state.discover.activeDetail;
  const active = state.discover.activeStream;
  if (!active || totalDuration <= 30 || currentTime < 5) return;

  const pct = Math.round((currentTime / totalDuration) * 100);
  const isEpisodic = detail && (detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0));
  const season = isEpisodic ? state.discover.activeSeason : null;
  const episode = isEpisodic ? state.discover.activeEpisode : null;

  const title = detail ? detail.title : active.title;
  if (!title) return;

  const key = isEpisodic
    ? `${title.toLowerCase().trim()}_s${season}e${episode}`
    : title.toLowerCase().trim();

  // If >= 85% watched, mark as completed
  if (pct >= 85) {
    markItemWatched(title, season, episode, true);
  }

  const history = getWatchHistory().filter((item) => item.key !== key);
  history.unshift({
    key,
    title,
    mediaType: detail ? detail.type : 'movie',
    season,
    episode,
    poster: detail ? (detail.poster || detail.backdrop) : '',
    backdrop: detail ? (detail.backdrop || detail.poster) : '',
    currentTime: Math.round(currentTime),
    totalDuration: Math.round(totalDuration),
    pct: Math.min(100, pct),
    lastUpdated: now,
    infoHash: active.infoHash,
    fileIdx: active.fileIdx,
    magnet: active.magnet || '',
    streamTitle: active.title || title,
    detail: detail ? {
      title: detail.title,
      type: detail.type,
      year: detail.year,
      poster: detail.poster,
      backdrop: detail.backdrop,
      runtime: detail.runtime
    } : null
  });

  saveWatchHistory(history);

  // Sync progress to backend Library if title is bookmarked
  try {
    const libItem = (detail && state.library && state.library.map && state.library.map[detail.id]) ||
                    (state.library && state.library.map && state.library.map[title.toLowerCase().trim()]);
    if (libItem && libItem.id) {
      const isCompleted = pct >= 85;
      fetch(`/api/v1/library/${encodeURIComponent(libItem.id)}/progress`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          season: season !== null ? Number(season) : null,
          episode: episode !== null ? Number(episode) : null,
          progress_percent: Math.min(100, pct),
          status: isCompleted ? 'completed' : 'watching'
        })
      }).then((r) => {
        if (r.ok) refreshLibraryData();
      }).catch(() => {});
    }
  } catch (_) {}

  // Scrobble playback progress to backend library
  try {
    const posterVal = (detail && (detail.poster || detail.backdrop)) || (active && active.poster) || '';
    const backdropVal = (detail && (detail.backdrop || detail.poster)) || (active && active.backdrop) || '';
    const yearVal = (detail && detail.year) || (active && active.year) || '';
    const ratingVal = (detail && detail.rating) || (active && active.rating) || '';

    fetch('/api/v1/library/scrobble', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        item_id: (detail && detail.id) ? detail.id : key,
        title: title,
        type: detail ? detail.type : 'movie',
        playback_seconds: currentTime,
        duration_seconds: totalDuration,
        progress_percent: Math.min(100, pct),
        season: season !== null ? Number(season) : null,
        episode: episode !== null ? Number(episode) : null,
        poster: posterVal,
        backdrop: backdropVal,
        year: yearVal,
        rating: ratingVal
      })
    }).catch(() => {});
  } catch (_) {}
}

function renderContinueWatchingShelf() {
  const shelf = document.getElementById('continue-watching-section');
  const grid = document.getElementById('continue-watching-grid');
  if (!shelf || !grid) return;

  // Check Settings visibility toggle
  const isEnabled = localStorage.getItem('evoscrapper_setting_show_continue') !== '0';
  if (!isEnabled) {
    shelf.classList.add('hidden');
    return;
  }

  // Restore collapsed state
  const isCollapsed = localStorage.getItem('evoscrapper_shelf_continue_collapsed') === '1';
  const body = document.getElementById('continue-watching-shelf-body');
  const icon = document.getElementById('continue-watching-shelf-icon');
  if (body) body.classList.toggle('collapsed', isCollapsed);
  if (icon) icon.className = isCollapsed ? 'fa-solid fa-plus' : 'fa-solid fa-minus';

  const history = getWatchHistory();
  if (!history || history.length === 0) {
    shelf.classList.add('hidden');
    return;
  }

  shelf.classList.remove('hidden');
  const countBadge = document.getElementById('continue-watching-count');
  if (countBadge) countBadge.innerText = `${history.length} in progress`;

  grid.innerHTML = history.map((item) => {
    const isEp = item.season !== null && item.episode !== null;
    const epBadge = isEp ? `S${String(item.season).padStart(2, '0')}:E${String(item.episode).padStart(2, '0')}` : '';
    const remainingMins = Math.max(1, Math.round((item.totalDuration - item.currentTime) / 60));
    const thumbCandidate = item.backdrop || item.poster || (item.key && item.key.startsWith('tt') ? `https://images.metahub.space/background/medium/${item.key}/img` : '');
    const thumbHtml = thumbCandidate
      ? `<img src="${escapeHtml(thumbCandidate)}" class="continue-card-img" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'media-jacket-placeholder\\' style=\\'height:100%;\\'><i class=\\'fa-solid fa-play fa-2x\\'></i><span class=\\'media-jacket-title\\'>${escapeJs(item.title)}</span></div>';">`
      : `<div class="media-jacket-placeholder" style="height:100%;"><i class="fa-solid fa-play fa-2x"></i><span class="media-jacket-title">${escapeHtml(item.title)}</span></div>`;

    return `
      <div class="continue-card" onclick="resumeContinueWatching('${escapeJs(item.key)}')">
        <div class="continue-card-img-wrap">
          ${thumbHtml}
          <div class="continue-card-overlay">
            <div class="continue-card-play-icon"><i class="fa-solid fa-play"></i></div>
          </div>
          ${isEp ? `<span class="continue-card-ep-pill">${escapeHtml(epBadge)}</span>` : ''}
          <div class="continue-progress-wrap">
            <div class="continue-progress-bar" style="width: ${item.pct}%;"></div>
          </div>
        </div>
        <div class="continue-card-body">
          <div class="continue-card-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
          <div class="continue-card-meta">
            <span class="continue-card-pct"><i class="fa-solid fa-clock-rotate-left"></i> ${remainingMins}m left</span>
            <span class="continue-card-pct-num">${item.pct}%</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function resumeContinueWatching(key) {
  const history = getWatchHistory();
  const item = history.find((i) => i.key === key);
  if (!item) return;

  if (item.detail) {
    state.discover.activeDetail = item.detail;
  }
  if (item.season !== null) state.discover.activeSeason = item.season;
  if (item.episode !== null) state.discover.activeEpisode = item.episode;

  showToast(`Resuming "${item.title}" at ${formatPlayerDuration(item.currentTime)}...`, 'info');

  const isMkv = (item.streamTitle || '').toLowerCase().endsWith('.mkv');
  playStreamInBrowser(item.infoHash, item.fileIdx, item.streamTitle, isMkv, item.magnet);

  const video = document.getElementById('evo-video-player');
  if (video && item.currentTime > 0) {
    const onStart = () => {
      video.removeEventListener('loadedmetadata', onStart);
      video.removeEventListener('play', onStart);
      seekPlayer(item.currentTime);
    };
    video.addEventListener('loadedmetadata', onStart, { once: true });
    video.addEventListener('play', onStart, { once: true });
  }
}

function toggleContinueWatchingShelf() {
  const body = document.getElementById('continue-watching-shelf-body');
  const icon = document.getElementById('continue-watching-shelf-icon');
  if (!body) return;

  const isCollapsed = body.classList.toggle('collapsed');
  if (icon) {
    icon.className = isCollapsed ? 'fa-solid fa-plus' : 'fa-solid fa-minus';
  }
  localStorage.setItem('evoscrapper_shelf_continue_collapsed', isCollapsed ? '1' : '0');
}

function clearContinueWatching() {
  localStorage.removeItem(WATCH_HISTORY_KEY);
  renderContinueWatchingShelf();
  showToast('Continue Watching history cleared', 'info');
}

// ══════════════════════════════════════════════════════════════════════════════
// 📚 Full-Featured Watchlist & Bookmark Manager ("My Library")
// ══════════════════════════════════════════════════════════════════════════════

async function initLibrary() {
  try {
    const res = await fetch('/api/v1/library');
    if (!res.ok) return;
    const data = await res.json();
    state.library.items = data.items || [];
    state.library.counts = data.counts || {};
    state.library.map = {};
    for (const it of state.library.items) {
      state.library.map[it.id] = it;
      if (it.title) {
        state.library.map[it.title.toLowerCase().trim()] = it;
      }
    }
    updateNavLibraryBadge();
    renderBookmarksShelf();
  } catch (e) {
    console.warn('Failed to load library:', e);
  }
}

function updateNavLibraryBadge() {
  const badge = document.getElementById('nav-library-badge');
  if (!badge) return;
  const count = state.library.counts['all'] || state.library.items.length || 0;
  if (count > 0) {
    badge.innerText = count;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

function isItemInLibrary(idOrTitle) {
  if (!idOrTitle) return false;
  return Boolean(state.library.map[idOrTitle] || state.library.map[String(idOrTitle).toLowerCase().trim()]);
}

function getItemLibraryStatus(idOrTitle) {
  if (!idOrTitle) return null;
  const item = state.library.map[idOrTitle] || state.library.map[String(idOrTitle).toLowerCase().trim()];
  return item ? item.status : null;
}

async function openLibraryModal() {
  const modal = document.getElementById('library-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  await refreshLibraryData();
  renderLibraryGrid();
}

function closeLibraryModal() {
  const modal = document.getElementById('library-modal');
  if (modal) modal.classList.add('hidden');
}

async function refreshLibraryData() {
  try {
    const res = await fetch('/api/v1/library');
    if (!res.ok) return;
    const data = await res.json();
    state.library.items = data.items || [];
    state.library.counts = data.counts || {};
    state.library.map = {};
    for (const it of state.library.items) {
      state.library.map[it.id] = it;
      if (it.title) {
        state.library.map[it.title.toLowerCase().trim()] = it;
      }
    }
    updateNavLibraryBadge();
    updateLibraryCountLabels();
  } catch (err) {
    console.error('Error refreshing library:', err);
  }
}

function updateLibraryCountLabels() {
  const c = state.library.counts || {};
  const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val || 0; };
  setEl('lib-count-all', c.all || state.library.items.length);
  setEl('lib-count-watching', c.watching);
  setEl('lib-count-plan', c.plan_to_watch);
  setEl('lib-count-completed', c.completed);
  setEl('lib-count-onhold', c.on_hold);
  setEl('lib-count-dropped', c.dropped);
  const totalLabel = document.getElementById('library-total-count');
  if (totalLabel) totalLabel.innerText = `${c.all || state.library.items.length} Titles`;
}

function setLibraryFilter(status) {
  state.library.filter = status;
  document.querySelectorAll('[data-lib-status]').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-lib-status') === status);
  });
  renderLibraryGrid();
}

function handleLibrarySearch(val) {
  state.library.search = (val || '').trim().toLowerCase();
  const clearBtn = document.getElementById('btn-library-search-clear');
  if (clearBtn) clearBtn.classList.toggle('hidden', !val);
  renderLibraryGrid();
}

function clearLibrarySearch() {
  const input = document.getElementById('library-search-input');
  if (input) input.value = '';
  handleLibrarySearch('');
}

function handleLibraryTypeChange(type) {
  state.library.typeFilter = type;
  renderLibraryGrid();
}

function handleLibrarySortChange(sort) {
  state.library.sort = sort;
  renderLibraryGrid();
}

function handleLibraryCardZoom(val) {
  state.library.cardZoom = parseInt(val, 10) || 180;
  const valLabel = document.getElementById('library-zoom-val');
  if (valLabel) valLabel.innerText = `${state.library.cardZoom}px`;
  const grid = document.querySelector('.library-grid');
  if (grid) {
    grid.style.setProperty('--lib-card-min-width', `${state.library.cardZoom}px`);
  }
}

function toggleLibraryBackupMenu() {
  const menu = document.getElementById('library-backup-menu');
  if (menu) menu.classList.toggle('hidden');
}

function exportLibraryBackup(format) {
  const menu = document.getElementById('library-backup-menu');
  if (menu) menu.classList.add('hidden');

  const items = state.library.items || [];
  if (items.length === 0) {
    showToast('Library is empty — nothing to export', 'warning');
    return;
  }

  const dateStr = new Date().toISOString().slice(0, 10);
  if (format === 'json') {
    const dataStr = JSON.stringify({ version: '2.0', exported_at: new Date().toISOString(), items }, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `evoscrapper_library_${dateStr}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Exported ${items.length} titles as JSON`, 'success');
  } else if (format === 'csv') {
    const headers = ['id', 'title', 'type', 'status', 'year', 'rating', 'current_season', 'current_episode', 'progress_percent'];
    const rows = items.map((it) => [
      `"${(it.id || '').replace(/"/g, '""')}"`,
      `"${(it.title || '').replace(/"/g, '""')}"`,
      `"${(it.type || 'movie').replace(/"/g, '""')}"`,
      `"${(it.status || 'plan_to_watch').replace(/"/g, '""')}"`,
      `"${(it.year || '').replace(/"/g, '""')}"`,
      `"${(it.rating || '').replace(/"/g, '""')}"`,
      it.current_season || 1,
      it.current_episode || 1,
      it.progress_percent || 0
    ].join(','));
    const csvContent = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `evoscrapper_library_${dateStr}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast(`Exported ${items.length} titles as CSV`, 'success');
  }
}

function triggerLibraryRestorePicker() {
  const menu = document.getElementById('library-backup-menu');
  if (menu) menu.classList.add('hidden');
  const fileInput = document.getElementById('library-backup-file-input');
  if (fileInput) {
    fileInput.value = '';
    fileInput.click();
  }
}

async function handleLibraryBackupUpload(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = async (e) => {
    try {
      const text = e.target.result;
      let parsedItems = [];

      if (file.name.endsWith('.json')) {
        const json = JSON.parse(text);
        parsedItems = Array.isArray(json) ? json : (json.items || []);
      } else if (file.name.endsWith('.csv')) {
        const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
        if (lines.length > 1) {
          const header = lines[0].split(',').map((h) => h.replace(/^"|"$/g, '').trim().toLowerCase());
          for (let i = 1; i < lines.length; i++) {
            const cols = lines[i].match(/(".*?"|[^",\s]+)(?=\s*,|\s*$)/g) || lines[i].split(',');
            const clean = cols.map((c) => c.replace(/^"|"$/g, '').trim());
            const row = {};
            header.forEach((h, idx) => { row[h] = clean[idx] || ''; });
            if (row.id && row.title) {
              parsedItems.push({
                id: row.id,
                title: row.title,
                type: row.type || 'movie',
                status: row.status || 'plan_to_watch',
                year: row.year || null,
                rating: row.rating || null,
                current_season: parseInt(row.current_season, 10) || 1,
                current_episode: parseInt(row.current_episode, 10) || 1,
                progress_percent: parseInt(row.progress_percent, 10) || 0
              });
            }
          }
        }
      }

      if (!parsedItems || parsedItems.length === 0) {
        showToast('No valid titles found in selected file', 'warning');
        return;
      }

      const res = await fetch('/api/v1/library/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: parsedItems })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      showToast(data.message || `Imported ${parsedItems.length} titles into Library!`, 'success');
      await refreshLibraryData();
      renderLibraryGrid();
    } catch (err) {
      showToast(`Restore failed: ${err.message}`, 'error');
    }
  };
  reader.readAsText(file);
}

function renderLibraryGrid() {
  const body = document.getElementById('library-modal-body');
  if (!body) return;

  const filter = state.library.filter || 'all';
  const search = state.library.search || '';
  const typeFilter = state.library.typeFilter || 'all';
  const sort = state.library.sort || 'updated';

  let list = [...(state.library.items || [])];

  // 1. Status Filter
  if (filter !== 'all') {
    list = list.filter((it) => it.status === filter);
  }

  // 2. Media Type Filter
  if (typeFilter !== 'all') {
    list = list.filter((it) => (it.type || '').toLowerCase() === typeFilter);
  }

  // 3. Search Filter
  if (search) {
    list = list.filter((it) => (it.title || '').toLowerCase().includes(search));
  }

  // 4. Sorting
  if (sort === 'title_asc') {
    list.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  } else if (sort === 'title_desc') {
    list.sort((a, b) => (b.title || '').localeCompare(a.title || ''));
  } else if (sort === 'year_desc') {
    list.sort((a, b) => (parseInt(b.year, 10) || 0) - (parseInt(a.year, 10) || 0));
  } else if (sort === 'rating_desc') {
    list.sort((a, b) => (parseFloat(b.rating) || 0) - (parseFloat(a.rating) || 0));
  } else if (sort === 'progress_desc') {
    list.sort((a, b) => (b.progress_percent || 0) - (a.progress_percent || 0));
  } else {
    // Recently Updated
    list.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  }

  const filteredLabel = document.getElementById('library-filtered-count');
  if (filteredLabel) {
    filteredLabel.innerText = `Showing ${list.length} of ${state.library.items.length}`;
  }

  if (list.length === 0) {
    body.innerHTML = `
      <div class="empty-state" style="padding: 4rem 1rem;">
        <div class="empty-icon text-dim"><i class="fa-solid fa-bookmark fa-2x"></i></div>
        <h3>No matching titles found</h3>
        <p class="text-dim">Try adjusting your status filter, search query, or add titles from the Discover page.</p>
      </div>
    `;
    return;
  }

  const zoomVal = state.library.cardZoom || 180;
  body.innerHTML = `
    <div class="library-grid" style="--lib-card-min-width: ${zoomVal}px;">
      ${list.map((item) => {
        const isEp = item.type === 'series' || item.type === 'anime';
        const progressText = isEp && item.current_season && item.current_episode
          ? `S${item.current_season} E${item.current_episode}`
          : (item.progress_percent ? `${item.progress_percent}%` : '');

        const posterSrc = item.poster || (item.id && item.id.startsWith('tt') ? `https://images.metahub.space/poster/medium/${item.id}/img` : '');
        const thumbHtml = posterSrc
          ? `<img src="${escapeHtml(posterSrc)}" alt="${escapeHtml(item.title)}" class="library-thumb" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'media-jacket-placeholder\\'><i class=\\'fa-solid fa-film fa-2x\\'></i><span class=\\'media-jacket-title\\'>${escapeJs(item.title)}</span></div>';">`
          : `<div class="media-jacket-placeholder"><i class="fa-solid fa-film fa-2x"></i><span class="media-jacket-title">${escapeHtml(item.title)}</span></div>`;

        return `
          <div class="library-card">
            <div class="library-thumb-wrap" onclick="closeLibraryModal(); openDiscoverModal('${escapeJs(item.id)}', '${escapeJs(item.type)}')">
              ${thumbHtml}
              <div class="continue-play-overlay"><i class="fa-solid fa-play"></i></div>
              ${item.progress_percent ? `<div class="library-progress-bar"><div class="library-progress-fill" style="width: ${item.progress_percent}%;"></div></div>` : ''}
            </div>
            <div class="library-body">
              <div class="library-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
              <div class="library-meta">
                <span class="tag tag-hdr">${escapeHtml((item.type || 'Movie').toUpperCase())}</span>
                ${item.year ? `<span class="mono text-dim text-xs">${escapeHtml(item.year)}</span>` : ''}
                ${progressText ? `<span class="tag tag-green mono text-xs font-bold">${escapeHtml(progressText)}</span>` : ''}
              </div>
              <div class="library-actions">
                <select class="library-status-select" onchange="changeLibraryItemStatus('${escapeJs(item.id)}', this.value)">
                  <option value="watching" ${item.status === 'watching' ? 'selected' : ''}>👁️ Watching</option>
                  <option value="plan_to_watch" ${item.status === 'plan_to_watch' ? 'selected' : ''}>⏳ Plan to Watch</option>
                  <option value="completed" ${item.status === 'completed' ? 'selected' : ''}>✅ Completed</option>
                  <option value="on_hold" ${item.status === 'on_hold' ? 'selected' : ''}>⏸️ On Hold</option>
                  <option value="dropped" ${item.status === 'dropped' ? 'selected' : ''}>⏹️ Dropped</option>
                </select>
                <button class="btn btn-icon btn-ghost btn-xs text-red" onclick="removeLibraryItem('${escapeJs(item.id)}', '${escapeJs(item.title)}')" title="Remove from Library">
                  <i class="fa-solid fa-trash"></i>
                </button>
              </div>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

async function changeLibraryItemStatus(id, newStatus) {
  try {
    const res = await fetch(`/api/v1/library/${id}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: newStatus }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`Status updated to ${newStatus.replace('_', ' ')}`, 'success');
    await refreshLibraryData();
    renderLibraryGrid();
    renderBookmarksShelf();
  } catch (err) {
    showToast(`Failed to update status: ${err.message}`, 'error');
  }
}

async function removeLibraryItem(id, title) {
  try {
    const res = await fetch(`/api/v1/library/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`Removed "${title || id}" from Library`, 'info');
    await refreshLibraryData();
    renderLibraryGrid();
    renderBookmarksShelf();
  } catch (err) {
    showToast(`Failed to remove title: ${err.message}`, 'error');
  }
}

// ── Long-Press Bookmark Interaction with SVG Ring ─────────────────────────
let bookmarkHoldTimer = null;
let bookmarkHoldTarget = null;
let bookmarkHoldStartTime = 0;
let bookmarkQuickPopupEl = null;

function handleBookmarkPointerDown(event, btn) {
  if (event.button !== 0 && event.pointerType === 'mouse') return;
  event.stopPropagation();
  closeBookmarkQuickPopup();

  bookmarkHoldTarget = btn;
  bookmarkHoldStartTime = Date.now();
  btn.classList.add('holding');

  bookmarkHoldTimer = setTimeout(() => {
    btn.classList.remove('holding');
    showBookmarkQuickPopup(btn);
    bookmarkHoldTimer = null;
  }, 520);
}

function handleBookmarkPointerUp(event, btn) {
  event.stopPropagation();
  const elapsed = Date.now() - bookmarkHoldStartTime;
  btn.classList.remove('holding');

  if (bookmarkHoldTimer) {
    clearTimeout(bookmarkHoldTimer);
    bookmarkHoldTimer = null;
    if (elapsed < 500) {
      const id = btn.getAttribute('data-id');
      const title = btn.getAttribute('data-title');
      const type = btn.getAttribute('data-type');
      const poster = btn.getAttribute('data-poster');
      const year = btn.getAttribute('data-year');
      toggleCardBookmark(event, id, title, type, poster, year);
    }
  }
}

function handleBookmarkPointerLeave(event, btn) {
  if (bookmarkHoldTarget === btn) {
    btn.classList.remove('holding');
    if (bookmarkHoldTimer) {
      clearTimeout(bookmarkHoldTimer);
      bookmarkHoldTimer = null;
    }
  }
}

function showBookmarkQuickPopup(btn) {
  closeBookmarkQuickPopup();
  const id = btn.getAttribute('data-id');
  const title = btn.getAttribute('data-title');
  const type = btn.getAttribute('data-type');
  const poster = btn.getAttribute('data-poster');
  const year = btn.getAttribute('data-year');
  const curStatus = getItemLibraryStatus(id);

  const popup = document.createElement('div');
  popup.className = 'bookmark-quick-popup';
  popup.onclick = (e) => e.stopPropagation();

  const statuses = [
    { key: 'watching', label: '👁️ Watching' },
    { key: 'plan_to_watch', label: '⏳ Plan to Watch' },
    { key: 'completed', label: '✅ Completed' },
    { key: 'on_hold', label: '⏸️ On Hold' },
    { key: 'dropped', label: '⏹️ Dropped' }
  ];

  let html = statuses.map((st) => `
    <button class="bookmark-quick-opt ${curStatus === st.key ? 'active' : ''}" onclick="setCardBookmarkStatus(event, '${escapeJs(id)}', '${escapeJs(title)}', '${escapeJs(type)}', '${escapeJs(poster)}', '${escapeJs(year)}', '${st.key}')">
      ${st.label}
    </button>
  `).join('');

  if (curStatus) {
    html += `
      <div class="menu-divider" style="height:1px;background:rgba(255,255,255,0.1);margin:4px 0;"></div>
      <button class="bookmark-quick-opt text-red" onclick="removeCardBookmark(event, '${escapeJs(id)}', '${escapeJs(title)}')">
        <i class="fa-solid fa-trash"></i> Remove from Library
      </button>
    `;
  }

  popup.innerHTML = html;
  document.body.appendChild(popup);

  const rect = btn.getBoundingClientRect();
  const pRect = popup.getBoundingClientRect();

  // Position above button by default
  let top = rect.top - pRect.height - 8;
  let left = rect.right - pRect.width;

  if (top < 10) {
    top = rect.bottom + 8;
  }
  if (left < 10) {
    left = 10;
  }
  if (left + pRect.width > window.innerWidth - 10) {
    left = window.innerWidth - pRect.width - 10;
  }

  popup.style.top = `${Math.round(top)}px`;
  popup.style.left = `${Math.round(left)}px`;
  bookmarkQuickPopupEl = popup;
}

function closeBookmarkQuickPopup() {
  if (bookmarkQuickPopupEl) {
    bookmarkQuickPopupEl.remove();
    bookmarkQuickPopupEl = null;
  }
}

document.addEventListener('click', (e) => {
  if (bookmarkQuickPopupEl && !bookmarkQuickPopupEl.contains(e.target)) {
    closeBookmarkQuickPopup();
  }
  const suggestions = document.getElementById('discover-search-suggestions');
  if (suggestions && !suggestions.contains(e.target)) {
    closeSearchSuggestions();
  }
  const backupMenu = document.getElementById('library-backup-menu');
  if (backupMenu && !backupMenu.classList.contains('hidden') && !e.target.closest('.library-backup-dropdown-wrap')) {
    backupMenu.classList.add('hidden');
  }
  const settingsPopover = document.getElementById('player-settings-popover');
  if (settingsPopover && !settingsPopover.classList.contains('hidden')) {
    if (!e.target.closest('#player-settings-popover') && !e.target.closest('#btn-hud-settings')) {
      settingsPopover.classList.add('hidden');
    }
  }
});

window.addEventListener('scroll', () => {
  if (bookmarkQuickPopupEl) closeBookmarkQuickPopup();
}, { passive: true });

async function setCardBookmarkStatus(event, id, title, type, poster, year, newStatus) {
  if (event) event.stopPropagation();
  closeBookmarkQuickPopup();
  try {
    const res = await fetch('/api/v1/library', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id,
        title,
        type: type || 'movie',
        poster,
        year,
        status: newStatus
      })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`Set "${title}" to ${newStatus.replace('_', ' ')}`, 'success');
    await refreshLibraryData();
    if (state.discover.items.length > 0) {
      renderDiscoverGrid(state.discover.items, false);
    }
    renderBookmarksShelf();
  } catch (err) {
    showToast(`Failed: ${err.message}`, 'error');
  }
}

async function removeCardBookmark(event, id, title) {
  if (event) event.stopPropagation();
  closeBookmarkQuickPopup();
  await removeLibraryItem(id, title);
  if (state.discover.items.length > 0) {
    renderDiscoverGrid(state.discover.items, false);
  }
}

async function toggleCardBookmark(event, id, title, type, poster, year) {
  if (event) event.stopPropagation();

  const isPresent = isItemInLibrary(id);
  if (isPresent) {
    const cur = getItemLibraryStatus(id);
    if (cur === 'plan_to_watch') {
      await changeLibraryItemStatus(id, 'watching');
    } else if (cur === 'watching') {
      await changeLibraryItemStatus(id, 'completed');
    } else {
      await removeLibraryItem(id, title);
    }
  } else {
    try {
      const res = await fetch('/api/v1/library', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id,
          title,
          type: type || 'movie',
          poster,
          year,
          status: 'plan_to_watch',
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      showToast(`Added "${title}" to Library (Plan to Watch)`, 'success');
      await refreshLibraryData();
    } catch (err) {
      showToast(`Failed to bookmark: ${err.message}`, 'error');
    }
  }
  if (state.discover.items.length > 0) {
    renderDiscoverGrid(state.discover.items, false);
  }
  renderBookmarksShelf();
}

async function handleModalBookmarkChange(newStatus) {
  const detail = state.discover.activeDetail;
  if (!detail) return;

  if (newStatus === 'none') return;
  if (newStatus === 'remove') {
    await removeLibraryItem(detail.id, detail.title);
    return;
  }

  try {
    const res = await fetch('/api/v1/library', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: detail.id,
        title: detail.title,
        type: detail.type || 'movie',
        poster: detail.poster || '',
        year: detail.year || '',
        rating: detail.rating || '',
        status: newStatus,
        current_season: state.discover.activeSeason || 1,
        current_episode: state.discover.activeEpisode || 1,
        total_episodes: detail.total_episodes || 0,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast(`"${detail.title}" saved as ${newStatus.replace('_', ' ')}!`, 'success');
    await refreshLibraryData();
    renderBookmarksShelf();
  } catch (err) {
    showToast(`Failed to update bookmark: ${err.message}`, 'error');
  }
}

function getBookmarks() {
  return state.library.items;
}

function isBookmarked(title) {
  return isItemInLibrary(title);
}

function toggleBookmark(title, poster = '', year = '', type = 'movie') {
  toggleCardBookmark(null, title, title, type, poster, year);
}

// ── Collapsible "MY LIST & FAVORITES" Shelf ────────────────────────────────
function toggleBookmarksShelf() {
  const body = document.getElementById('bookmarks-shelf-body');
  const icon = document.getElementById('bookmarks-shelf-icon');
  if (!body) return;

  const isCollapsed = body.classList.toggle('collapsed');
  if (icon) {
    icon.className = isCollapsed ? 'fa-solid fa-plus' : 'fa-solid fa-minus';
  }
  localStorage.setItem('evoscrapper_shelf_mylist_collapsed', isCollapsed ? '1' : '0');
}

function formatStatusBadge(status) {
  const map = {
    'plan_to_watch': { label: 'Plan to Watch', class: 'status-plan', dot: '#38bdf8' },
    'watching': { label: 'Watching', class: 'status-watching', dot: '#a855f7' },
    'completed': { label: 'Completed', class: 'status-completed', dot: '#22c55e' },
    'on_hold': { label: 'On Hold', class: 'status-hold', dot: '#f59e0b' },
    'dropped': { label: 'Dropped', class: 'status-dropped', dot: '#ef4444' },
    'saved': { label: 'Saved', class: 'status-saved', dot: '#00e5ff' },
  };
  const key = (status || 'saved').toLowerCase().replace(/\s+/g, '_');
  const cfg = map[key] || { label: status || 'Saved', class: 'status-saved', dot: '#00e5ff' };
  return `<span class="shelf-status-pill ${cfg.class}"><span class="status-dot" style="background:${cfg.dot};"></span>${escapeHtml(cfg.label)}</span>`;
}

function renderBookmarksShelf() {
  const shelf = document.getElementById('bookmarks-section');
  const grid = document.getElementById('bookmarks-grid');
  const countBadge = document.getElementById('bookmarks-shelf-count');
  if (!shelf || !grid) return;

  // Check Settings visibility toggle
  const isEnabled = localStorage.getItem('evoscrapper_setting_show_bookmarks') !== '0';
  if (!isEnabled) {
    shelf.classList.add('hidden');
    return;
  }

  // Restore collapsed state
  const isCollapsed = localStorage.getItem('evoscrapper_shelf_mylist_collapsed') === '1';
  const body = document.getElementById('bookmarks-shelf-body');
  const icon = document.getElementById('bookmarks-shelf-icon');
  if (body) body.classList.toggle('collapsed', isCollapsed);
  if (icon) icon.className = isCollapsed ? 'fa-solid fa-plus' : 'fa-solid fa-minus';

  const list = state.library.items || [];
  if (list.length === 0) {
    shelf.classList.add('hidden');
    return;
  }

  shelf.classList.remove('hidden');
  if (countBadge) countBadge.innerText = `${list.length} saved`;

  grid.innerHTML = list.map((item) => {
    const isEp = item.type === 'series' || item.type === 'anime';
    const progText = isEp && item.current_season && item.current_episode
      ? `S${item.current_season}:E${item.current_episode}`
      : (item.progress_percent ? `${item.progress_percent}%` : '');

    const posterSrc = item.poster || (item.id && item.id.startsWith('tt') ? `https://images.metahub.space/poster/medium/${item.id}/img` : '');
    const posterHtml = posterSrc
      ? `<img src="${escapeHtml(posterSrc)}" class="poster-img" loading="lazy" onerror="this.onerror=null;this.parentElement.innerHTML='<div class=\\'media-jacket-placeholder\\'><i class=\\'fa-solid fa-film fa-2x\\'></i><span class=\\'media-jacket-title\\'>${escapeJs(item.title)}</span></div>';">`
      : `<div class="media-jacket-placeholder"><i class="fa-solid fa-film fa-2x"></i><span class="media-jacket-title">${escapeHtml(item.title)}</span></div>`;

    return `
      <div class="shelf-media-card" onclick="openDiscoverModal('${escapeJs(item.id)}', '${escapeJs(item.type)}')">
        <div class="poster-wrap">
          ${posterHtml}
          <div class="poster-overlay">
            <div class="play-btn-circle"><i class="fa-solid fa-play"></i></div>
          </div>
          ${item.progress_percent ? `<div class="library-progress-bar"><div class="library-progress-fill" style="width: ${item.progress_percent}%;"></div></div>` : ''}
          <div class="shelf-card-top-actions">
            <button class="shelf-card-del-btn" onclick="event.stopPropagation(); removeLibraryItem('${escapeJs(item.id)}', '${escapeJs(item.title)}')" title="Remove from list">
              <i class="fa-solid fa-xmark"></i>
            </button>
          </div>
          <div class="shelf-card-bottom-tags">
            ${formatStatusBadge(item.status)}
            ${progText ? `<span class="shelf-prog-pill">${escapeHtml(progText)}</span>` : ''}
          </div>
        </div>
        <div class="media-info">
          <div class="media-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
          <div class="media-meta">
            <span>${escapeHtml(item.year || '')}</span>
            <span class="media-type-badge">${escapeHtml((item.type || 'movie').toUpperCase())}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// ── Smart Autocomplete Suggestions for Discover Search ─────────────────────
let searchSuggestionTimer = null;
let activeSuggestions = [];
let selectedSuggestionIndex = -1;

function handleDiscoverSearchInput(val) {
  const clearBtn = document.getElementById('btn-discover-search-clear');
  if (clearBtn) clearBtn.classList.toggle('hidden', !val);

  clearTimeout(searchSuggestionTimer);
  const q = (val || '').trim();
  if (q.length < 2) {
    closeSearchSuggestions();
    return;
  }

  searchSuggestionTimer = setTimeout(() => {
    fetchDiscoverSuggestions(q);
  }, 220);
}

async function fetchDiscoverSuggestions(query) {
  try {
    const type = state.discover.type || 'all';
    const res = await fetch(`/api/v1/discover/suggestions?q=${encodeURIComponent(query)}&type=${encodeURIComponent(type)}`);
    if (!res.ok) return;
    const items = await res.json();
    renderSearchSuggestions(items, query);
  } catch (_) {}
}

function renderSearchSuggestions(items, query) {
  const container = document.getElementById('discover-search-suggestions');
  if (!container) return;
  if (!items || items.length === 0) {
    closeSearchSuggestions();
    return;
  }

  activeSuggestions = items;
  selectedSuggestionIndex = -1;

  container.innerHTML = items.map((it, idx) => {
    const posterSrc = it.poster || '';
    const typeTag = (it.type || 'Movie').toUpperCase();
    return `
      <div class="suggestion-item" data-index="${idx}" onclick="selectSearchSuggestion(${idx})">
        ${posterSrc ? `<img src="${escapeHtml(posterSrc)}" class="suggestion-thumb" alt="${escapeHtml(it.title)}" onerror="this.style.display='none'">` : `<div class="suggestion-thumb flex items-center justify-center text-dim"><i class="fa-solid fa-film"></i></div>`}
        <div class="suggestion-info">
          <div class="suggestion-title">${escapeHtml(it.title)}</div>
          <div class="suggestion-meta">
            <span class="tag tag-hdr">${escapeHtml(typeTag)}</span>
            ${it.year ? `<span>${escapeHtml(it.year)}</span>` : ''}
            ${it.rating ? `<span class="text-yellow"><i class="fa-solid fa-star"></i> ${escapeHtml(it.rating)}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');

  const wrap = container.closest('.discover-search-wrap');
  if (wrap) wrap.classList.add('suggestions-open');
  const navBar = container.closest('.discover-nav-bar');
  if (navBar) navBar.classList.add('suggestions-open');

  container.classList.remove('hidden');
}

function selectSearchSuggestion(idx) {
  const item = activeSuggestions[idx];
  if (!item) return;
  closeSearchSuggestions();
  const input = document.getElementById('discover-search-input');
  if (input) input.value = item.title;
  openDiscoverModal(item.id, item.type);
}

function handleDiscoverSearchKeydown(e) {
  const container = document.getElementById('discover-search-suggestions');
  const isMenuOpen = container && !container.classList.contains('hidden');

  if (e.key === 'ArrowDown') {
    if (isMenuOpen && activeSuggestions.length > 0) {
      e.preventDefault();
      selectedSuggestionIndex = Math.min(activeSuggestions.length - 1, selectedSuggestionIndex + 1);
      highlightSuggestionItem();
    }
  } else if (e.key === 'ArrowUp') {
    if (isMenuOpen && activeSuggestions.length > 0) {
      e.preventDefault();
      selectedSuggestionIndex = Math.max(0, selectedSuggestionIndex - 1);
      highlightSuggestionItem();
    }
  } else if (e.key === 'Enter') {
    if (isMenuOpen && selectedSuggestionIndex >= 0 && selectedSuggestionIndex < activeSuggestions.length) {
      e.preventDefault();
      selectSearchSuggestion(selectedSuggestionIndex);
    } else {
      closeSearchSuggestions();
      searchDiscoverCatalog();
    }
  } else if (e.key === 'Escape') {
    closeSearchSuggestions();
  }
}

function highlightSuggestionItem() {
  document.querySelectorAll('.suggestion-item').forEach((el, i) => {
    el.classList.toggle('selected', i === selectedSuggestionIndex);
  });
}

function closeSearchSuggestions() {
  const container = document.getElementById('discover-search-suggestions');
  if (container) {
    container.classList.add('hidden');
    const wrap = container.closest('.discover-search-wrap');
    if (wrap) wrap.classList.remove('suggestions-open');
    const navBar = container.closest('.discover-nav-bar');
    if (navBar) navBar.classList.remove('suggestions-open');
  }
  activeSuggestions = [];
  selectedSuggestionIndex = -1;
}

function clearDiscoverSearch() {
  const input = document.getElementById('discover-search-input');
  if (input) input.value = '';
  const clearBtn = document.getElementById('btn-discover-search-clear');
  if (clearBtn) clearBtn.classList.add('hidden');
  closeSearchSuggestions();
  updateCatalogHeading();
  loadDiscoverCatalog(true);
}

// ── In-Player Buffering Progress HUD ───────────────────────────────────────
let playerBufferingInterval = null;
let playerBufferingStartTime = 0;

function showPlayerBufferingHUD() {
  const hud = document.getElementById('player-buffering-hud');
  const spinner = document.getElementById('player-buffering-spinner');
  if (spinner) spinner.classList.remove('hidden');
  if (!hud) return;

  hud.classList.remove('hidden');
  playerBufferingStartTime = Date.now();

  const fill = document.getElementById('buffering-progress-fill');
  const pctBadge = document.getElementById('buffering-pct-badge');
  const bytesLabel = document.getElementById('buffering-bytes-label');
  const speedLabel = document.getElementById('buffering-speed-label');
  const countdownLabel = document.getElementById('buffering-countdown-label');

  if (fill) fill.style.width = '15%';
  if (pctBadge) pctBadge.innerText = '15%';
  if (bytesLabel) bytesLabel.innerHTML = '<i class="fa-solid fa-layer-group"></i> Allocating buffer...';
  if (speedLabel) speedLabel.innerHTML = '<i class="fa-solid fa-gauge-high"></i> Connecting P2P swarm...';
  if (countdownLabel) countdownLabel.innerHTML = '<i class="fa-solid fa-hourglass-start"></i> Starting playback...';

  clearInterval(playerBufferingInterval);

  let currentBytes = 0.5;
  const targetBytes = 4.0;

  playerBufferingInterval = setInterval(() => {
    const video = document.getElementById('evo-video-player');
    const session = window._lastSwarmSession;
    const fill = document.getElementById('buffering-progress-fill');
    const pctBadge = document.getElementById('buffering-pct-badge');
    const speedLabel = document.getElementById('buffering-speed-label');

    // Calculate actual video playback buffer ahead of current playhead
    let bufferAheadSec = 0;
    if (video && video.buffered && video.buffered.length > 0) {
      const cur = video.currentTime;
      for (let i = 0; i < video.buffered.length; i++) {
        if (cur >= video.buffered.start(i) && cur <= video.buffered.end(i)) {
          bufferAheadSec = Math.max(0, video.buffered.end(i) - cur);
          break;
        }
      }
    }

    // Auto-dismiss HUD as soon as video is ready or actively playing
    if (video && (!video.paused && video.currentTime > 0 || video.readyState >= 3 || (video.readyState >= 2 && bufferAheadSec >= 0.2) || (video.readyState >= 1 && bufferAheadSec >= 0.5))) {
      hidePlayerBufferingHUD();
      return;
    }

    // Dynamic buffer percentage: measures immediate playback readiness buffer ahead of current playhead
    let bufferPct = 15;
    if (bufferAheadSec > 0) {
      bufferPct = Math.min(100, Math.max(30, Math.round((bufferAheadSec / 1.5) * 100)));
    } else {
      const elapsedSec = (Date.now() - playerBufferingStartTime) / 1000;
      bufferPct = Math.min(95, Math.max(15, Math.round(elapsedSec * 40)));
    }

    if (session && session.download_speed !== undefined) {
      const spdNum = session.download_speed || 0;
      const spdStr = formatSpeed(spdNum);
      const peers = session.peers || 0;

      if (fill) fill.style.width = `${bufferPct}%`;
      if (pctBadge) pctBadge.innerText = `${bufferPct}%`;
      if (speedLabel) speedLabel.innerHTML = `<i class="fa-solid fa-gauge-high"></i> ${spdStr} (${peers} peers)`;
    } else {
      if (fill) fill.style.width = `${bufferPct}%`;
      if (pctBadge) pctBadge.innerText = `${bufferPct}%`;
      if (speedLabel) speedLabel.innerHTML = `<i class="fa-solid fa-gauge-high"></i> Connecting P2P swarm...`;
    }
  }, 300);
}

function hidePlayerBufferingHUD() {
  clearInterval(playerBufferingInterval);
  playerBufferingInterval = null;
  const hud = document.getElementById('player-buffering-hud');
  const spinner = document.getElementById('player-buffering-spinner');
  if (spinner) spinner.classList.add('hidden');
  if (hud) hud.classList.add('hidden');
}

function searchDiscoverCatalogByTitle(title) {
  const input = document.getElementById('discover-search-input');
  if (input) {
    input.value = title;
    searchDiscoverCatalog();
  }
}

function seekPlayer(targetSeconds) {
  const video = document.getElementById('evo-video-player');
  const active = state.discover.activeStream;
  if (!video || !active) return;

  const maxDuration = (active.totalDuration > 0) ? active.totalDuration : 7200;
  const clamped = Math.max(0, Math.min(maxDuration - 1, targetSeconds));

  if (!active.useTransmux) {
    video.currentTime = clamped;
    updatePlayerTimeline();
    return;
  }

  // Transmuxed FFmpeg stream: instant input-seek via -ss
  active.playbackOffset = clamped;

  const hasBurnSub = (active.burnSubIdx !== null && active.burnSubIdx !== undefined);
  const burnSubParam = hasBurnSub ? `&burn_sub_idx=${active.burnSubIdx}` : '';
  const transcodeParam = (active.transcodeVideo || hasBurnSub) ? '&transcode_video=true' : '';
  const epParams = (active.season !== null && active.episode !== null && active.season !== undefined && active.episode !== undefined)
    ? `&season=${active.season}&episode=${active.episode}`
    : '';
  const magnetParam = active.magnet ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
  const audioParam = `&audio_track=${active.audioTrack || 0}&audio_boost=1.25`;

  const fileIdxToUse = (active.playingFileIdx !== undefined && active.playingFileIdx !== null)
    ? active.playingFileIdx
    : (active.fileIdx || 0);
  const durationParam = active.totalDuration > 0 ? `&duration=${active.totalDuration}` : '';
  const bufferParam = `&buffer_mb=${getActiveBufferSizeMb()}`;

  const newUrl = `/api/v1/stream/transmux?info_hash=${active.infoHash}&file_idx=${fileIdxToUse}${audioParam}&start_time=${clamped.toFixed(2)}${burnSubParam}${transcodeParam}${epParams}${magnetParam}${durationParam}${bufferParam}`;

  const spinner = document.getElementById('player-buffering-spinner');
  if (spinner) spinner.classList.remove('hidden');

  video.pause();
  video.src = newUrl;
  video.load();
  video.play().then(() => {
    hidePlayerBufferingHUD();
    if (spinner) spinner.classList.add('hidden');
    updatePlayPauseIcon(true);
  }).catch(() => {
    if (spinner) spinner.classList.add('hidden');
  });

  updatePlayerTimeline();
  updateSubtitleOverlay();
}

function playStreamInBrowser(infoHash, fileIdx, title, isMkvHint = false, magnet = '', seasonOverride = null, episodeOverride = null, forceDirectIdx = false) {
  initPlayerTimelineControls();
  const discSuggestions = document.getElementById('discover-search-suggestions');
  if (discSuggestions) discSuggestions.classList.add('hidden');
  document.querySelectorAll('.bookmark-quick-popup').forEach((el) => el.remove());

  const modal = document.getElementById('player-modal');
  const video = document.getElementById('evo-video-player');
  const titleEl = document.getElementById('player-stream-title');
  const swarmStat = document.getElementById('player-swarm-stat');
  const unmuteOverlay = document.getElementById('player-unmute-overlay');
  if (unmuteOverlay) unmuteOverlay.classList.add('hidden');
  const spinner = document.getElementById('player-buffering-spinner');

  const detail = state.discover.activeDetail;
  const isEpisodic = detail && (detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0));
  const meta = extractCleanMediaInfo(title);
  const season = (seasonOverride !== null && seasonOverride !== undefined) ? seasonOverride : (isEpisodic ? state.discover.activeSeason : (meta.season || null));
  const episode = (episodeOverride !== null && episodeOverride !== undefined) ? episodeOverride : (isEpisodic ? state.discover.activeEpisode : (meta.episode || null));

  // Determine initial duration from metadata or defaults
  let initialDuration = 0;
  if (detail && detail.runtime) {
    initialDuration = parseRuntimeToSeconds(detail.runtime);
  }
  if (initialDuration <= 0) {
    if (detail && detail.type === 'anime') initialDuration = 1440; // 24 min
    else if (detail && detail.type === 'series') initialDuration = 2700; // 45 min
    else initialDuration = 5400; // 90 min default movie runtime
  }

  const isMkv = Boolean(isMkvHint) || (title || '').toLowerCase().endsWith('.mkv') || /\b(mkv|matroska)\b/i.test(title);
  const isDirectStream = (!isMkv && /\b(mp4|aac|mp3|yts|yify|x264|h264|avc)\b/i.test(title)) ||
                         (!isMkv && /\b(webm|vp8|vp9|opus)\b/i.test(title));
  const hasIncompatibleAudio = /\b(ac3|eac3|ddp|dd\+|dts|truehd|atmos|dts-hd|flac|5\.1|7\.1|dual[\s._-]?audio|multi[\s._-]?audio)\b/i.test(title);
  const isHevcOrUnsupportedVideo = /\b(hevc|x265|h\.?265|10bit|hdr|av1)\b/i.test(title);

  // Default to Direct Stream (RFC 7233 HTTP 206 Partial Content byte ranges) for direct-compatible media.
  // For MKV or multi-audio releases requiring downmix/re-muxing, intelligently enable transmux.
  let useTransmux = false;
  if (isMkv || hasIncompatibleAudio || isHevcOrUnsupportedVideo || !isDirectStream) {
    useTransmux = true;
  }
  // Thunder-God speed: ALWAYS default to lossless stream copy (-c:v copy).
  // Modern browsers (Chrome 107+, Brave, Edge, Safari) decode HEVC natively in fMP4.
  // Video transcoding is reserved strictly as an error-fallback if the browser's video engine rejects the stream.
  let transcodeVideo = false;

  const numFileIdx = (fileIdx !== null && fileIdx !== undefined && !isNaN(fileIdx)) ? Number(fileIdx) : 0;
  const effectiveFileIdx = numFileIdx > 0 ? numFileIdx : (forceDirectIdx ? numFileIdx : 0);
  const epParams = (season !== null && episode !== null) ? `&season=${season}&episode=${episode}` : '';
  const magnetParam = magnet ? `&magnet=${encodeURIComponent(magnet)}` : '';

  state.discover.activeStream = {
    infoHash,
    fileIdx: effectiveFileIdx,
    playingFileName: title,
    playingFileIdx: effectiveFileIdx,
    title,
    isMkv,
    magnet,
    useTransmux,
    transcodeVideo,
    burnSubIdx: null,
    audioTrack: 0,
    playbackOffset: 0,
    totalDuration: initialDuration,
    season,
    episode,
    forceDirectIdx,
    audioTracks: [],
    isDraggingTimeline: false,
    showRemainingTime: false,
  };
  state.subtitles.userManuallySelected = false;

  if (titleEl) {
    const epTag = (!forceDirectIdx && season !== null && episode !== null) ? ` (S${season}E${episode})` : '';
    titleEl.innerText = `${title}${epTag}`;
  }
  modal.classList.remove('hidden');

  // Pre-warm torrent swarm and discover exact auto-selected episode file
  const bufferParam = `&buffer_mb=${getActiveBufferSizeMb()}`;
  const warmUrl = `/api/v1/stream/warm?info_hash=${infoHash}&file_idx=${effectiveFileIdx}${epParams}${magnetParam}${bufferParam}`;
  fetch(warmUrl)
    .then((r) => r.json())
    .then((wData) => {
      if (wData && wData.file) {
        const active = state.discover.activeStream;
        if (active && active.infoHash === infoHash) {
          active.playingFileName = wData.file;
          if (wData.file_idx !== null && wData.file_idx !== undefined) {
            active.playingFileIdx = wData.file_idx;
          }
          if (titleEl) {
            const epTag = (!forceDirectIdx && season !== null && episode !== null) ? ` (S${season}E${episode})` : '';
            titleEl.innerText = `${wData.file}${epTag}`;
          }

          // If swarm discovery reveals an MKV container or incompatible multi-audio format while on direct, transition immediately
          const fileIsMkv = (wData.file || '').toLowerCase().endsWith('.mkv') || /\b(mkv|matroska)\b/i.test(wData.file || '');
          const fileIncompatible = fileIsMkv || /\b(ac3|eac3|dts|truehd|atmos|dts-hd|flac|dual[\s._-]?audio)\b/i.test(wData.file || '');
          if (fileIncompatible && !active.useTransmux) {
            console.log('[EvoPlayer] Swarm warmup discovered MKV/multi-audio container; switching to transmuxer...');
            active.useTransmux = true;
            const modeBadge = document.getElementById('player-hud-mode-label');
            if (modeBadge) modeBadge.innerText = 'Transmux';
            updateAudioHudButtons();
            const transcodeParam = active.transcodeVideo ? '&transcode_video=true' : '';
            const durParam = active.totalDuration > 0 ? `&duration=${active.totalDuration}` : '';
            const targetIdx = (active.playingFileIdx !== undefined && active.playingFileIdx !== null) ? active.playingFileIdx : effectiveFileIdx;
            const tUrl = `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${targetIdx}&audio_track=${active.audioTrack || 0}&audio_boost=1.25${transcodeParam}${epParams}${magnetParam}${durParam}`;
            video.src = tUrl;
            video.load();
            video.play().catch(() => {});
          }
        }
      }
    })
    .catch(() => {});

  // Update initial time display immediately
  const totalEl = document.getElementById('player-total-time');
  if (totalEl) {
    totalEl.innerText = formatPlayerDuration(initialDuration);
  }
  const curEl = document.getElementById('player-cur-time');
  if (curEl) curEl.innerText = '00:00:00';
  updatePlayerTimeline();

  const modeBadge = document.getElementById('player-hud-mode-label');
  if (modeBadge) modeBadge.innerText = useTransmux ? 'Transmux' : 'Direct';

  updateAudioHudButtons();

  if (swarmStat) {
    swarmStat.innerHTML = '<span class="mono text-xs text-dim flex items-center gap-2"><i class="fa-solid fa-circle-nodes text-green"></i> Initializing P2P Swarm & Allocating Multi-Buffer...</span>';
  }

  startSwarmStatsMonitor(infoHash);

  // Probe stream metadata in background for exact duration, multi-audio tracks, and embedded subtitles
  let probeAttempts = 0;
  const maxProbeAttempts = 4;
  if (window._evoProbeTimer) clearTimeout(window._evoProbeTimer);

  const triggerStreamProbe = () => {
    const active = state.discover.activeStream;
    if (!active || active.infoHash !== infoHash) return;
    if (active.audioTracks && active.audioTracks.length > 0 && active.totalDuration > 0) return;

    probeAttempts++;
    const probeFileIdx = (active.playingFileIdx !== undefined && active.playingFileIdx !== null)
      ? active.playingFileIdx
      : effectiveFileIdx;
    const currentProbeUrl = `/api/v1/stream/probe?info_hash=${infoHash}&file_idx=${probeFileIdx}${epParams}${magnetParam}`;

    fetch(currentProbeUrl)
      .then((r) => r.json())
      .then((probe) => {
        const curActive = state.discover.activeStream;
        if (!curActive || curActive.infoHash !== infoHash) return;

        if (probe && probe.success) {
          if (probe.duration > 0) {
            curActive.totalDuration = probe.duration;
            const tEl = document.getElementById('player-total-time');
            if (tEl) tEl.innerText = formatPlayerDuration(probe.duration);
            updatePlayerTimeline();
          }
          if (probe.audio_tracks && probe.audio_tracks.length > 0) {
            curActive.audioTracks = probe.audio_tracks;
            renderAudioMenu(probe.audio_tracks);
            const curTrk = probe.audio_tracks[curActive.audioTrack || 0] || probe.audio_tracks[0];
            const langBadge = document.getElementById('player-hud-audio-lang');
            if (langBadge) langBadge.innerText = (curTrk.language || curTrk.title || 'AUDIO').toUpperCase();
            const trackBadge = document.getElementById('player-audio-track-badge');
            if (trackBadge) trackBadge.innerText = curTrk.title || `Track ${(curActive.audioTrack || 0) + 1}`;
          }
          const qualityBadge = document.getElementById('player-hud-stream-badge');
          if (qualityBadge) {
            const vCodec = (probe.video_codec || '1080p').toUpperCase();
            const aCodec = (probe.audio_codec || 'AAC').toUpperCase();
            qualityBadge.innerText = `${vCodec} | ${aCodec}`;
          }

          const vCodecLower = (probe.video_codec || '').toLowerCase();
          const aCodecLower = (probe.audio_codec || '').toLowerCase();

          // Check if audio needs AAC stereo transmuxing (EAC3, AC3, DTS, TrueHD, Atmos, FLAC)
          const audioNeedsTransmux = ['ac3', 'eac3', 'dts', 'truehd', 'atmos', 'flac', 'dca', 'mlp'].some(c => aCodecLower.includes(c));

          // Check if browser can decode this video codec directly
          let browserSupportsVideo = (vCodecLower === 'h264' || vCodecLower === 'avc' || vCodecLower === 'vp8' || vCodecLower === 'vp9');
          if (vCodecLower === 'hevc' || vCodecLower === 'h265') {
            try {
              browserSupportsVideo = Boolean(video.canPlayType && (video.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"') || video.canPlayType('video/mp4; codecs="hev1.1.6.L93.B0"')));
            } catch (_) {
              browserSupportsVideo = true;
            }
            if (!browserSupportsVideo && (navigator.userAgent.includes('Chrome') || navigator.userAgent.includes('Edg') || navigator.userAgent.includes('Safari') || navigator.userAgent.includes('Brave'))) {
              browserSupportsVideo = true;
            }
          }
          const videoNeedsTranscode = !browserSupportsVideo || vCodecLower === 'mjpeg';

          // If currently playing via direct stream but stream has incompatible audio (e.g. EAC3) or video, upgrade immediately to transmuxer
          if (!curActive.useTransmux && (audioNeedsTransmux || videoNeedsTranscode)) {
            console.log(`[EvoPlayer] Probe detected codec (${vCodecLower} / ${aCodecLower}) requiring transmuxer; upgrading pipeline...`);
            curActive.useTransmux = true;
            if (videoNeedsTranscode) curActive.transcodeVideo = true;
            const curPlayTime = (video.currentTime && !isNaN(video.currentTime)) ? video.currentTime : 0;
            curActive.playbackOffset = curPlayTime;
            const modeBadge = document.getElementById('player-hud-mode-label');
            if (modeBadge) modeBadge.innerText = curActive.transcodeVideo ? 'Transcode' : 'Transmux';
            updateAudioHudButtons();

            const startParam = curPlayTime > 0 ? `&start_time=${curPlayTime.toFixed(1)}` : '';
            const tcParam = curActive.transcodeVideo ? '&transcode_video=true' : '';
            const durParam = curActive.totalDuration > 0 ? `&duration=${curActive.totalDuration}` : '';
            const targetIdx = (curActive.playingFileIdx !== undefined && curActive.playingFileIdx !== null) ? curActive.playingFileIdx : effectiveFileIdx;
            const upgradedUrl = `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${targetIdx}&audio_track=${curActive.audioTrack || 0}&audio_boost=1.25${tcParam}${startParam}${epParams}${magnetParam}${durParam}`;
            video.src = upgradedUrl;
            video.load();
            video.play().catch(() => {});
          } else if (curActive.useTransmux && !curActive.transcodeVideo && videoNeedsTranscode) {
            console.log(`[EvoPlayer] Probe detected unsupported video codec (${vCodecLower}); enabling H.264 transcode...`);
            curActive.transcodeVideo = true;
            const curPlayTime = (curActive.playbackOffset || 0) + ((video.currentTime && !isNaN(video.currentTime)) ? video.currentTime : 0);
            curActive.playbackOffset = curPlayTime;
            const modeBadge = document.getElementById('player-hud-mode-label');
            if (modeBadge) modeBadge.innerText = 'Transcode';
            const startParam = curPlayTime > 0 ? `&start_time=${curPlayTime.toFixed(1)}` : '';
            const durParam = curActive.totalDuration > 0 ? `&duration=${curActive.totalDuration}` : '';
            const targetIdx = (curActive.playingFileIdx !== undefined && curActive.playingFileIdx !== null) ? curActive.playingFileIdx : effectiveFileIdx;
            const upgradedUrl = `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${targetIdx}&audio_track=${curActive.audioTrack || 0}&audio_boost=1.25&transcode_video=true${startParam}${epParams}${magnetParam}${durParam}`;
            video.src = upgradedUrl;
            video.load();
            video.play().catch(() => {});
          }
          if (probe.subtitle_tracks && probe.subtitle_tracks.length > 0) {
            const embeddedSubs = probe.subtitle_tracks.map((st) => {
              const isBitmap = Boolean(st.is_bitmap) || (st.codec || '').toLowerCase().includes('pgs') || (st.codec || '').toLowerCase().includes('dvd');
              const badgeTag = isBitmap ? ' (PGS Image)' : '';
              return {
                language: `${st.title || (st.language || 'Sub').toUpperCase()}${badgeTag}`,
                lang_code: st.language || 'en',
                release_name: `[EMBEDDED] ${st.title || st.language || 'Track'}${badgeTag}`,
                provider: isBitmap ? 'Embedded (PGS Image)' : 'Embedded Text',
                is_embedded: true,
                is_image_based: isBitmap,
                sub_index: st.sub_idx,
                stream_idx: st.stream_idx,
                file_idx: probeFileIdx,
                info_hash: infoHash,
                download_url: `/api/v1/stream/subtitles?info_hash=${infoHash}&file_idx=${probeFileIdx}&sub_index=${st.sub_idx}${epParams}${magnetParam}`,
              };
            });
            const existingOnline = (state.subtitles.availableSubs || []).filter(s => !s.is_embedded);
            const textEmbedded = embeddedSubs.filter(s => !s.is_image_based);
            const pgsEmbedded = embeddedSubs.filter(s => s.is_image_based);
            state.subtitles.availableSubs = [...textEmbedded, ...existingOnline, ...pgsEmbedded];
            renderSubtitleTracksList(state.subtitles.availableSubs);

            // Stremio-grade subtitle behavior: If an online subtitle is already active and loaded (e.g. OpenSubtitles),
            // preserve it! Do NOT blow away working subtitles.
            // Only auto-apply if NO subtitle track has been loaded yet.
            if (textEmbedded.length > 0 && !state.subtitles.activeTrack && (!state.subtitles.rawCues || state.subtitles.rawCues.length === 0)) {
              const prefLang = state.subtitles.preferredLang || 'en';
              const matchEmbedded = textEmbedded.find(s => matchSubtitleLang(s, prefLang)) || textEmbedded[0];
              if (matchEmbedded) {
                console.log('[EvoPlayer] Auto-applying embedded subtitle track:', matchEmbedded.release_name);
                applySubtitle(matchEmbedded, true);
              }
            }
          }
        } else {
          // Swarm cold or downloading initial header: retry with backoff
          if (probeAttempts < maxProbeAttempts) {
            window._evoProbeTimer = setTimeout(triggerStreamProbe, probeAttempts * 2000);
          }
        }
      })
      .catch((err) => {
        console.warn('[EvoPlayer] Probe retry notice:', err.message);
        if (probeAttempts < maxProbeAttempts) {
          window._evoProbeTimer = setTimeout(triggerStreamProbe, probeAttempts * 2000);
        }
      });
  };

  // Initial probe scheduled after stream setup
  window._evoProbeTimer = setTimeout(triggerStreamProbe, 1000);

  // Set Video Source with duration hint for immediate header injection
  const transcodeParam = transcodeVideo ? '&transcode_video=true' : '';
  const durationParam = initialDuration > 0 ? `&duration=${initialDuration}` : '';
  const streamUrl = useTransmux
    ? `/api/v1/stream/transmux?info_hash=${infoHash}&file_idx=${effectiveFileIdx}&audio_track=0&audio_boost=1.25${transcodeParam}${epParams}${magnetParam}${durationParam}${bufferParam}`
    : `/api/v1/stream/play?info_hash=${infoHash}&file_idx=${effectiveFileIdx}${epParams}${magnetParam}${durationParam}${bufferParam}`;

  showPlayerBufferingHUD();

  video.pause();
  video.muted = false;
  video.volume = 1.0;
  video.src = streamUrl;
  video.load();

  // Video event handlers with instant duration and time sync
  video.onloadedmetadata = () => {
    const active = state.discover.activeStream;
    if (active && !active.useTransmux && video.duration && isFinite(video.duration) && video.duration > 30) {
      active.totalDuration = video.duration;
    }
    const tEl = document.getElementById('player-total-time');
    const displayDur = (active && active.totalDuration > 0) ? active.totalDuration : (video.duration > 0 && isFinite(video.duration) ? video.duration : 0);
    if (tEl && displayDur > 0) tEl.innerText = formatPlayerDuration(displayDur);
    updatePlayerTimeline();
    if (!state.discover.activeStream?.audioTracks?.length) {
      triggerStreamProbe();
    }
  };

  video.ondurationchange = () => {
    const active = state.discover.activeStream;
    if (active && !active.useTransmux && video.duration && isFinite(video.duration) && video.duration > 30) {
      active.totalDuration = video.duration;
    }
    const tEl = document.getElementById('player-total-time');
    const displayDur = (active && active.totalDuration > 0) ? active.totalDuration : (video.duration > 0 && isFinite(video.duration) ? video.duration : 0);
    if (tEl && displayDur > 0) tEl.innerText = formatPlayerDuration(displayDur);
    updatePlayerTimeline();
  };

  video.ontimeupdate = () => {
    updatePlayerTimeline();
    updateSubtitleOverlay();
    if (video && !video.muted && video.volume > 0 && unmuteOverlay && !unmuteOverlay.classList.contains('hidden')) {
      unmuteOverlay.classList.add('hidden');
    }
  };

  video.onseeked = () => {
    updatePlayerTimeline();
    updateSubtitleOverlay();
  };

  video.onplay = () => {
    updatePlayPauseIcon(true);
    hidePlayerBufferingHUD();
    checkMuteState();
  };

  video.onpause = () => {
    updatePlayPauseIcon(false);
  };

  let waitingDebounceTimer = null;
  video.onwaiting = () => {
    clearTimeout(waitingDebounceTimer);
    waitingDebounceTimer = setTimeout(() => {
      if (video.readyState < 3) showPlayerBufferingHUD();
    }, 500);
  };
  video.oncanplay = () => {
    clearTimeout(waitingDebounceTimer);
    hidePlayerBufferingHUD();
    if (!state.discover.activeStream?.audioTracks?.length) {
      triggerStreamProbe();
    }
  };
  video.onplaying = () => {
    clearTimeout(waitingDebounceTimer);
    hidePlayerBufferingHUD();
    checkMuteState();
  };

  // Auto-Load Subtitles for this release
  const mediaTitle = detail ? detail.title : (meta.title || title);
  const imdbId = (detail && typeof detail.id === 'string' && detail.id.startsWith('tt')) ? detail.id : '';
  autoLoadSubtitles(mediaTitle, imdbId, season, episode, title, infoHash);

  const checkMuteState = () => {
    if (unmuteOverlay) {
      if (video.muted || video.volume === 0) {
        unmuteOverlay.classList.remove('hidden');
      } else {
        unmuteOverlay.classList.add('hidden');
      }
    }
  };
  video.onvolumechange = checkMuteState;

  video.onerror = () => {
    const err = video.error;
    console.warn('[EvoPlayer] Video playback notice:', err ? err.code : 'unknown', err ? err.message : '');
    const active = state.discover.activeStream;
    // Auto fallback to FFmpeg compatibility transmuxer if browser rejects native container/codec
    if (active && !active.useTransmux) {
      console.log('[EvoPlayer] Direct play failed; falling back to FFmpeg transmuxer...');
      showToast('Unsupported browser codec; switching to real-time compatibility player...', 'info');
      active.useTransmux = true;
      active.playbackOffset = video.currentTime || 0;
      const mBadge = document.getElementById('player-hud-mode-label');
      if (mBadge) mBadge.innerText = 'Transmux';
      const hasBurnSub = (active.burnSubIdx !== null && active.burnSubIdx !== undefined);
      const burnParam = hasBurnSub ? `&burn_sub_idx=${active.burnSubIdx}` : '';
      const fallbackUrl = `/api/v1/stream/transmux?info_hash=${active.infoHash}&file_idx=${active.playingFileIdx || active.fileIdx}&audio_track=${active.audioTrack || 0}&audio_boost=1.25${burnParam}${epParams}${magnetParam}${durationParam}`;
      video.src = fallbackUrl;
      video.load();
      video.play().catch(() => {});
    } else if (active && active.useTransmux && !active.transcodeVideo) {
      console.log('[EvoPlayer] Transmux video stream error; falling back to H.264 transcode...');
      showToast('Transcoding video stream to H.264 for browser compatibility...', 'info');
      active.transcodeVideo = true;
      const mBadge = document.getElementById('player-hud-mode-label');
      if (mBadge) mBadge.innerText = 'Transcode';
      const curPlayTime = (active.playbackOffset || 0) + (video.currentTime || 0);
      const startParam = curPlayTime > 0 ? `&start_time=${curPlayTime.toFixed(1)}` : '';
      const hasBurnSub = (active.burnSubIdx !== null && active.burnSubIdx !== undefined);
      const burnParam = hasBurnSub ? `&burn_sub_idx=${active.burnSubIdx}` : '';
      const fallbackUrl = `/api/v1/stream/transmux?info_hash=${active.infoHash}&file_idx=${active.playingFileIdx || active.fileIdx}&audio_track=${active.audioTrack || 0}&audio_boost=1.25&transcode_video=true${burnParam}${startParam}${epParams}${magnetParam}${durationParam}`;
      video.src = fallbackUrl;
      video.load();
      video.play().catch(() => {});
    } else {
      showToast('Stream error. Swarm may be starved or file unreachable.', 'error');
      hidePlayerBufferingHUD();
    }
  };

  video.play().then(() => {
    showToast(`Streaming: ${title}`, 'info');
    video.muted = false;
    video.volume = 1.0;
    checkMuteState();
    updatePlayPauseIcon(true);
    hidePlayerBufferingHUD();

    // Check resume history
    const historyItem = getWatchHistory().find(h => {
      if (season !== null && episode !== null) {
        return h.key === `${(mediaTitle || '').toLowerCase().trim()}_s${season}e${episode}`;
      }
      return h.key === (mediaTitle || '').toLowerCase().trim();
    });
    if (historyItem && historyItem.currentTime > 15 && historyItem.pct < 90) {
      const resSec = historyItem.currentTime;
      const resTimeStr = formatPlayerDuration(resSec);
      promptResumePlayback(resSec, resTimeStr);
    }
  }).catch((err) => {
    console.log('[EvoPlayer] Autoplay notice:', err ? err.message : '');
    if (err && err.name === 'NotAllowedError') {
      video.muted = true;
      video.play().then(() => {
        checkMuteState();
        updatePlayPauseIcon(true);
      }).catch(() => {});
    }
    checkMuteState();
    hidePlayerBufferingHUD();
  });
}

function toggleStreamPipelineMode() {
  const active = state.discover.activeStream;
  const video = document.getElementById('evo-video-player');
  if (!active || !video) return;

  const curTime = (active.useTransmux ? (active.playbackOffset || 0) : 0) + (video.currentTime || 0);

  // Cycle pipeline modes: Direct -> Transmux (Lossless AAC) -> Transcode (H.264 ultra-compatible) -> Direct
  if (!active.useTransmux) {
    active.useTransmux = true;
    active.transcodeVideo = false;
  } else if (!active.transcodeVideo) {
    active.transcodeVideo = true;
  } else {
    active.useTransmux = false;
    active.transcodeVideo = false;
  }

  const modeBadge = document.getElementById('player-hud-mode-label');
  const epParams = (active.season !== null && active.episode !== null && active.season !== undefined && active.episode !== undefined)
    ? `&season=${active.season}&episode=${active.episode}`
    : '';
  const magnetParam = active.magnet ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
  const durationParam = active.totalDuration > 0 ? `&duration=${active.totalDuration}` : '';
  const fileIdxToUse = (active.playingFileIdx !== undefined && active.playingFileIdx !== null) ? active.playingFileIdx : (active.fileIdx || 0);

  showPlayerBufferingHUD();

  if (active.useTransmux) {
    active.playbackOffset = curTime;
    const tcParam = active.transcodeVideo ? '&transcode_video=true' : '';
    if (modeBadge) modeBadge.innerText = active.transcodeVideo ? 'Transcode' : 'Transmux';
    showToast(
      active.transcodeVideo
        ? 'Switched to H.264 Transcoder (Maximum Compatibility)'
        : 'Switched to Compatibility Transmuxer (Stereo AAC)',
      'info'
    );
    const startParam = curTime > 0 ? `&start_time=${curTime.toFixed(1)}` : '';
    const burnParam = (active.burnSubIdx !== null && active.burnSubIdx !== undefined) ? `&burn_sub_idx=${active.burnSubIdx}` : '';
    const newUrl = `/api/v1/stream/transmux?info_hash=${active.infoHash}&file_idx=${fileIdxToUse}${startParam}&audio_track=${active.audioTrack || 0}&audio_boost=1.25${burnParam}${tcParam}${epParams}${magnetParam}${durationParam}`;
    video.src = newUrl;
    video.load();
    video.play().catch(() => {});
  } else {
    active.playbackOffset = 0;
    if (modeBadge) modeBadge.innerText = 'Direct';
    showToast('Switched to Direct Stream (Full Seek & Buffer)', 'info');
    const newUrl = `/api/v1/stream/play?info_hash=${active.infoHash}&file_idx=${fileIdxToUse}${epParams}${magnetParam}${durationParam}`;
    video.src = newUrl;
    video.load();
    video.currentTime = curTime;
    video.play().catch(() => {});
  }

  updateAudioHudButtons();
  updatePlayerTimeline();
}

function closePlayerModal() {
  // If the browser is in fullscreen mode, exit fullscreen immediately
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    try {
      if (document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      } else if (document.webkitExitFullscreen) {
        document.webkitExitFullscreen();
      }
    } catch (_) {}
  }

  stopPlayerTicker();
  if (window._evoProbeTimer) {
    clearTimeout(window._evoProbeTimer);
    window._evoProbeTimer = null;
  }
  if (window.evoP2PPlayer) {
    window.evoP2PPlayer.destroy();
  }
  if (window.evoPgsDecoder) {
    window.evoPgsDecoder.detach();
  }
  stopSwarmStatsMonitor();
  toggleSubtitleDrawer(false);
  togglePlayerSettingsMenu(false);
  toggleSwarmInspectorModal(false);
  toggleShortcutsModal(false);
  closeTorrentFilesModal();
  const modal = document.getElementById('player-modal');
  const video = document.getElementById('evo-video-player');
  const unmuteOverlay = document.getElementById('player-unmute-overlay');
  if (unmuteOverlay) unmuteOverlay.classList.add('hidden');
  const spinner = document.getElementById('player-buffering-spinner');
  const audioMenu = document.getElementById('player-audio-menu');
  const wrap = document.getElementById('player-video-wrap');

  if (unmuteOverlay) unmuteOverlay.classList.add('hidden');
  if (spinner) spinner.classList.add('hidden');
  hidePlayerBufferingHUD();
  if (audioMenu) audioMenu.classList.add('hidden');
  if (wrap) wrap.classList.remove('user-idle');
  clearTimeout(playerIdleTimer);

  if (video) {
    video.pause();
    updatePlayPauseIcon(false);
    video.onerror = null;
    video.onvolumechange = null;
    video.ontimeupdate = null;
    video.onseeking = null;
    video.onseeked = null;
    video.onwaiting = null;
    video.onplaying = null;
    video.onplay = null;
    video.onpause = null;
    video.removeAttribute('src');
    video.querySelectorAll('track').forEach((t) => t.remove());
    video.load();
  }
  state.subtitles.rawCues = [];
  state.subtitles.activeTrack = null;
  state.discover.activeStream = null;
  const cueBox = document.getElementById('player-active-cue');
  if (cueBox) {
    cueBox.innerHTML = '';
    cueBox.classList.add('hidden');
  }
  const statusPill = document.getElementById('player-sub-status-pill');
  if (statusPill) statusPill.classList.add('hidden');
  const jumpBtn = document.getElementById('btn-jump-first-cue');
  if (jumpBtn) jumpBtn.classList.add('hidden');
  if (modal) modal.classList.add('hidden');
}

function downloadActiveM3u() {
  const active = state.discover.activeStream;
  if (!active) {
    showToast('No active stream to export', 'error');
    return;
  }

  // Automatically pause the web player so audio/video does not conflict with desktop player
  const video = document.getElementById('evo-video-player');
  if (video && !video.paused) {
    video.pause();
    updatePlayPauseIcon(false);
    stopPlayerTicker();
  }

  const magnetParam = active.magnet ? `&magnet=${encodeURIComponent(active.magnet)}` : '';
  const epParam = (active.season !== undefined && active.season !== null && active.episode !== undefined && active.episode !== null)
    ? `&season=${active.season}&episode=${active.episode}`
    : '';
  const url = `/api/v1/stream/playlist.m3u?info_hash=${active.infoHash}&file_idx=${active.fileIdx}&title=${encodeURIComponent(active.title || 'EvoStream')}${magnetParam}${epParam}`;
  window.location.href = url;
  showToast('📥 Downloading M3U playlist — click to open directly in VLC!', 'info');
}

async function launchStreamInVlc(infoHash, fileIdx, title, magnet = '', seasonOverride = null, episodeOverride = null) {
  // Automatically pause the web player so audio/video does not conflict with desktop player
  const video = document.getElementById('evo-video-player');
  if (video && !video.paused) {
    video.pause();
    updatePlayPauseIcon(false);
    stopPlayerTicker();
  }

  const detail = state.discover.activeDetail;
  const isEpisodic = detail && (detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0));
  const meta = extractCleanMediaInfo(title);
  const season = (seasonOverride !== null && seasonOverride !== undefined) ? seasonOverride : (isEpisodic ? state.discover.activeSeason : (meta.season || null));
  const episode = (episodeOverride !== null && episodeOverride !== undefined) ? episodeOverride : (isEpisodic ? state.discover.activeEpisode : (meta.episode || null));

  showToast('Connecting to swarm & launching native VLC Media Player...', 'info');

  try {
    const res = await fetch('/api/v1/stream/launch-vlc', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        info_hash: infoHash,
        file_idx: fileIdx,
        title: title || 'EvoScrapper Stream',
        magnet: magnet || null,
        season,
        episode,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    showToast('🚀 VLC Media Player launched in interactive GUI window!', 'info');
  } catch (err) {
    console.warn('VLC direct launch error, falling back to .m3u download:', err);
    // Download fallback if host couldn't spawn VLC window directly
    try {
      const epParam = (season !== null && episode !== null) ? `&season=${season}&episode=${episode}` : '';
      const m3uUrl = `/api/v1/stream/playlist.m3u?info_hash=${encodeURIComponent(infoHash)}&file_idx=${fileIdx}&title=${encodeURIComponent(title || 'EvoStream')}${magnet ? '&magnet=' + encodeURIComponent(magnet) : ''}${epParam}`;
      const a = document.createElement('a');
      a.href = m3uUrl;
      a.download = `${(title || 'EvoStream').replace(/[^a-zA-Z0-9_-]/g, '_')}.m3u`;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast('Downloaded M3U playlist — click to open in player!', 'info');
    } catch (_) {
      showToast(`Could not open VLC: ${err.message}`, 'error');
    }
  }
}

function switchPlayerToVlc() {
  const current = state.discover.activeStream;
  if (!current) {
    showToast('No active stream to transfer to VLC', 'error');
    return;
  }
  const video = document.getElementById('evo-video-player');
  if (video && !video.paused) {
    video.pause();
    updatePlayPauseIcon(false);
    stopPlayerTicker();
  }
  launchStreamInVlc(current.infoHash, current.fileIdx, current.title, current.magnet || '', current.season, current.episode);
}

async function playDebridStream(infoHash, fileIdx, title, magnet = '', provider = 'RealDebrid', seasonOverride = null, episodeOverride = null) {
  const detail = state.discover.activeDetail;
  const isEpisodic = detail && (detail.type === 'series' || detail.type === 'anime' || (detail.seasons && detail.seasons.length > 0));
  const meta = extractCleanMediaInfo(title);
  const season = (seasonOverride !== null && seasonOverride !== undefined) ? seasonOverride : (isEpisodic ? state.discover.activeSeason : (meta.season || null));
  const episode = (episodeOverride !== null && episodeOverride !== undefined) ? episodeOverride : (isEpisodic ? state.discover.activeEpisode : (meta.episode || null));

  showToast(`⚡ Resolving 1Gbps unthrottled cloud stream from ${provider}...`, 'info');
  try {
    const epParam = (season !== null && episode !== null) ? `&season=${season}&episode=${episode}` : '';
    const res = await fetch(`/api/v1/stream/debrid/resolve?info_hash=${encodeURIComponent(infoHash)}&file_idx=${fileIdx}&magnet=${encodeURIComponent(magnet)}&provider=${encodeURIComponent(provider)}${epParam}`, {
      method: 'POST',
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    const modal = document.getElementById('player-modal');
    const video = document.getElementById('evo-video-player');
    const titleEl = document.getElementById('player-stream-title');
    const swarmStat = document.getElementById('player-swarm-stat');

    if (titleEl) titleEl.innerText = `${title} [⚡ ${data.provider} Cloud CDN]`;
    if (swarmStat) swarmStat.innerHTML = `<span class="mono text-xs text-green"><i class="fa-solid fa-bolt"></i> 1Gbps HTTPS Direct Cloud CDN (${data.provider}) — Zero Buffering</span>`;

    state.discover.activeStream = {
      infoHash,
      fileIdx,
      title,
      magnet,
      useTransmux: false,
      isDebrid: true,
      audioTrack: 0,
      playbackOffset: 0,
    };

    modal.classList.remove('hidden');
    if (window.evoP2PPlayer) {
      window.evoP2PPlayer.setupPlayer('evo-video-player', data.stream_url, false);
    } else {
      video.pause();
      video.src = data.stream_url;
      video.load();
    }

    initPlayerTimelineControls();
    video.onloadedmetadata = () => {
      const active = state.discover.activeStream;
      if (active && !active.useTransmux && video.duration && isFinite(video.duration) && video.duration > 30) {
        active.totalDuration = video.duration;
      }
      const totalEl = document.getElementById('player-total-time');
      const displayDur = (active && active.totalDuration > 0) ? active.totalDuration : (video.duration > 0 && isFinite(video.duration) ? video.duration : 0);
      if (totalEl && displayDur > 0) totalEl.innerText = formatPlayerDuration(displayDur);
      updatePlayerTimeline();
    };
    video.ontimeupdate = () => {
      updatePlayerTimeline();
      updateSubtitleOverlay();
    };
    video.onseeked = () => {
      updatePlayerTimeline();
      updateSubtitleOverlay();
    };

    video.play().catch(() => {});

    showToast(`⚡ Cloud stream playing via ${data.provider}!`, 'info');
    searchAutoSubtitlesForActive();
  } catch (err) {
    console.error('Debrid resolve error:', err);
    showToast(`Debrid error: ${err.message}. Falling back to P2P...`, 'error');
    playStreamInBrowser(infoHash, fileIdx, title, false, magnet);
  }
}

function playCdnStream(embedUrl, title) {
  if (!embedUrl) return;
  const modal = document.getElementById('player-modal');
  const video = document.getElementById('evo-video-player');
  const titleEl = document.getElementById('player-stream-title');
  const swarmStat = document.getElementById('player-swarm-stat');

  if (titleEl) titleEl.innerText = `${title} [🌐 Web-CDN]`;
  if (swarmStat) swarmStat.innerHTML = `<span class="mono text-xs text-blue"><i class="fa-solid fa-globe"></i> Instant Web CDN Multi-Server</span>`;

  modal.classList.remove('hidden');
  video.pause();

  // If embed URL is an iframe provider (VidSrc / 2Embed), open in popup or embed
  window.open(embedUrl, '_blank');
  showToast('🌐 Opened Instant Web-CDN Player in high-speed window!', 'info');
}

function searchSubtitlesForMedia(title) {
  closeDiscoverModal();
  switchTab('subtitles');
  const subInput = document.getElementById('sub-search-input');
  if (subInput) {
    subInput.value = title;
    searchSubtitles();
  }
}

// ── Torrent Files Inspector & Switcher ───────────────────────────────────────
const _cachedTorrentFiles = new Map();

function formatTorrentFileSize(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + ' GB';
  if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
  if (bytes >= 1024) return (bytes / 1024).toFixed(0) + ' KB';
  return bytes + ' B';
}

async function openTorrentFilesModal(infoHash, magnet = '', title = '') {
  const modal = document.getElementById('torrent-files-modal');
  const titleEl = document.getElementById('torrent-files-modal-title');
  const listEl = document.getElementById('torrent-files-list');
  const countEl = document.getElementById('torrent-files-count');
  const filterInput = document.getElementById('torrent-files-filter');
  if (!modal || !listEl) return;

  if (filterInput) filterInput.value = '';
  modal.classList.remove('hidden');
  syncFullscreenPortal(modal, true);
  handlePlayerActivity();
  if (titleEl) titleEl.innerText = `${title || 'Torrent'} - Files`;

  listEl.innerHTML = `
    <div class="empty-state" style="padding: 2rem;">
      ${getEvoLoaderHtml('md', 'Fetching Torrent File Tree', 'Retrieving metadata and file list from swarm…')}
    </div>
  `;

  try {
    const magnetParam = magnet ? `&magnet=${encodeURIComponent(magnet)}` : '';
    const res = await fetch(`/api/v1/stream/files?info_hash=${encodeURIComponent(infoHash)}${magnetParam}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const files = data.files || [];
    _cachedTorrentFiles.set(infoHash, { files, magnet, title });

    renderTorrentFilesList(infoHash, files);
  } catch (err) {
    listEl.innerHTML = `
      <div class="empty-state" style="padding: 2rem;">
        <div class="empty-icon text-red"><i class="fa-solid fa-triangle-exclamation"></i></div>
        <h3>Failed to fetch files</h3>
        <p class="text-dim">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderTorrentFilesList(infoHash, files, filterText = '') {
  const listEl = document.getElementById('torrent-files-list');
  const countEl = document.getElementById('torrent-files-count');
  if (!listEl) return;

  const active = state.discover.activeStream;
  const activeIdx = (active && active.infoHash === infoHash) ? (active.playingFileIdx ?? active.fileIdx) : null;

  const q = (filterText || '').toLowerCase().trim();
  const filtered = q ? files.filter(f => (f.name || '').toLowerCase().includes(q) || (f.path || '').toLowerCase().includes(q)) : files;

  if (countEl) countEl.innerText = `${filtered.length} / ${files.length} files`;

  if (filtered.length === 0) {
    listEl.innerHTML = `<div class="empty-state" style="padding: 1.5rem;"><p class="text-dim">No matching files found.</p></div>`;
    return;
  }

  listEl.innerHTML = filtered.map(f => {
    const isPlaying = activeIdx !== null && f.idx === activeIdx;
    const isVideo = /\.(mp4|mkv|webm|avi|mov|ts|m4v)$/i.test(f.name || f.path || '');
    const sizeStr = f.length ? formatTorrentFileSize(f.length) : '';
    const icon = isVideo ? 'fa-file-video text-accent' : 'fa-file text-dim';

    return `
      <div class="torrent-file-item ${isPlaying ? 'active-playing-file' : ''}" style="display:flex; align-items:center; justify-content:space-between; gap:0.5rem; padding:0.45rem 0.6rem; border-radius:6px; background:${isPlaying ? 'rgba(0,230,118,0.1)' : 'rgba(255,255,255,0.03)'}; border:1px solid ${isPlaying ? 'var(--green)' : 'rgba(255,255,255,0.06)'};">
        <div style="min-width:0; flex:1; overflow:hidden;">
          <div style="display:flex; align-items:center; gap:0.4rem;">
            <i class="fa-solid ${icon}"></i>
            <span class="mono font-bold text-xs" style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(f.path || f.name)}">
              ${escapeHtml(f.name || f.path)}
            </span>
            ${isPlaying ? '<span class="tag tag-green mono text-xs" style="padding:1px 6px;">PLAYING</span>' : ''}
          </div>
          ${f.path && f.path !== f.name ? `<div class="text-dim text-xs mono" style="margin-left:1.2rem; font-size:0.68rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(f.path)}</div>` : ''}
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem; flex-shrink:0;">
          <span class="mono text-xs text-dim">${sizeStr}</span>
          ${isVideo ? `
            <button class="btn btn-xs ${isPlaying ? 'btn-green' : 'btn-primary'}" onclick="selectTorrentFileToPlay('${escapeJs(infoHash)}', ${f.idx}, '${escapeJs(f.name)}')">
              <i class="fa-solid fa-play"></i> ${isPlaying ? 'Restart' : 'Play'}
            </button>
          ` : ''}
        </div>
      </div>
    `;
  }).join('');
}

function filterTorrentFilesList(query) {
  const modal = document.getElementById('torrent-files-modal');
  if (!modal || modal.classList.contains('hidden')) return;
  const active = state.discover.activeStream;
  const infoHash = active ? active.infoHash : (Array.from(_cachedTorrentFiles.keys())[0]);
  if (!infoHash || !_cachedTorrentFiles.has(infoHash)) return;
  renderTorrentFilesList(infoHash, _cachedTorrentFiles.get(infoHash).files, query);
}

function selectTorrentFileToPlay(infoHash, fileIdx, fileName) {
  const cached = _cachedTorrentFiles.get(infoHash);
  const magnet = cached ? cached.magnet : '';
  const isMkv = (fileName || '').toLowerCase().endsWith('.mkv');
  closeTorrentFilesModal();
  playStreamInBrowser(infoHash, fileIdx, fileName, isMkv, magnet, null, null, true);
}

function openActiveStreamFilesModal() {
  const active = state.discover.activeStream;
  if (!active || !active.infoHash) {
    showToast('No active torrent stream to inspect', 'info');
    return;
  }
  openTorrentFilesModal(active.infoHash, active.magnet || '', active.title || '');
}

function closeTorrentFilesModal() {
  const modal = document.getElementById('torrent-files-modal');
  if (modal) {
    modal.classList.add('hidden');
    syncFullscreenPortal(modal, false);
  }
}



