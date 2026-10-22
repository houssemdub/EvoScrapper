import asyncio
import re
import time
from typing import List, Optional
from urllib.parse import quote_plus

from core.aggregator import deduplicate_torrents
from core.anime_offset import AnimeOffsetEngine
from core.cache import cache
from core.client import http_client
from core.debrid.manager import get_debrid_manager
from models.stream import StreamItem, StreamResolveResponse
from models.torrent import TorrentItem
from providers.torrents import TORRENT_PROVIDERS
from scrappers.nyaa import get_nyaa_scraper
from scrappers.web_cdn import get_web_cdn_scraper


DEFAULT_ANIME_TRACKERS = [
    "http://nyaa.tracker.wf:7777/announce",
    "http://anidex.moe:6969/announce",
    "http://tracker.anirena.com:80/announce",
    "udp://tracker.uw0.xyz:6969/announce",
    "http://share.camoe.cn:8080/announce",
    "http://t.nyaatracker.com:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.bittor.pw:1337/announce",
]

PROVIDER_MEDIA_CAPABILITIES = {
    "movie": {"yts", "thepiratebay", "rutor", "torrentgalaxy", "torlock", "1337x", "comando", "bludv"},
    "series": {"eztv", "thepiratebay", "rutor", "torrentgalaxy", "torlock", "1337x", "comando", "bludv"},
    "anime": {"nyaa", "tokyotosho", "subsplease", "thepiratebay", "1337x", "torrentgalaxy"},
}


def get_capable_providers(media_type: str):
    caps = PROVIDER_MEDIA_CAPABILITIES.get(media_type, set(TORRENT_PROVIDERS.keys()))
    return [p for name, p in TORRENT_PROVIDERS.items() if name in caps]


def parse_size_to_bytes(size_str: str) -> int:
    """Converts human readable size strings like '252.22 MB' or '1.11 GB' to integer bytes."""
    m = re.match(r"([\d\.]+)\s*([KMGT]?B)", (size_str or "").strip(), re.I)
    if not m:
        return 0
    val = float(m.group(1))
    unit = m.group(2).upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    return int(val * multipliers.get(unit, 1))


def compute_stream_score(item: TorrentItem, is_exact_ep: bool = False) -> float:
    """
    Computes a Torrentio-style quality and health score for ranking streams.
    """
    score = 0.0
    res = (item.metadata.resolution or "").lower()
    if "2160" in res or "4k" in res or "uhd" in res:
        score += 100.0
    elif "1080" in res:
        score += 70.0
    elif "720" in res:
        score += 40.0
    else:
        score += 15.0

    src = (item.metadata.source or "").lower()
    raw = item.title.lower()
    if "remux" in raw or "remux" in src:
        score += 35.0
    elif "bluray" in src or "bdrip" in src:
        score += 25.0
    elif "web-dl" in src or "webdl" in src:
        score += 20.0
    elif "webrip" in src:
        score += 15.0
    elif "hdtv" in src:
        score += 5.0
    elif "cam" in raw or "hdcam" in raw:
        score -= 150.0

    # HDR / Dolby Vision
    hdr_list = item.metadata.hdr or []
    if "dv" in raw or "dolby vision" in raw or "Dolby Vision" in hdr_list or "DV" in hdr_list:
        score += 15.0
    elif "hdr" in raw or len(hdr_list) > 0:
        score += 10.0

    # Audio
    if "atmos" in raw or "truehd" in raw:
        score += 15.0
    elif "dts" in raw:
        score += 10.0
    elif "5.1" in raw or "ddp" in raw or "ac3" in raw:
        score += 5.0

    # Codec bonus (AV1 / HEVC x265 efficiency)
    if "hevc" in raw or "x265" in raw:
        score += 8.0
    elif "av1" in raw:
        score += 10.0

    # Swarm health bonus
    score += min(item.seeders, 200) * 0.4

    if is_exact_ep:
        score += 40.0

    return score


def extract_stream_badge(item: TorrentItem) -> str:
    """Builds a concise badge name like 'EvoStream 4K REMUX' or '1337x 1080p'."""
    provider = item.sources[0] if item.sources else "P2P"
    res = item.metadata.resolution or "1080p"
    src = item.metadata.source or ""
    raw = item.title.lower()
    
    tag = res
    if "remux" in raw:
        tag += " REMUX"
    elif src and src.lower() != "unknown":
        tag += f" {src}"

    return f"[{provider}] {tag}"


ALLOWED_TITLE_EXTRAS = {
    "the", "a", "an", "tv", "series", "season", "seasons", "complete", "batch",
    "dual", "audio", "multi", "sub", "subs", "dub", "dubbed", "ita", "fra", "ger", "eng",
    "uncensored", "uncut", "remastered", "bdrip", "webrip", "webdl", "web", "dl", "10bit",
    "vol", "volume", "part", "pt", "ep", "episode", "episodes",
    "ova", "ovas", "oad", "movie", "movies", "film", "films", "special", "specials",
    "ost", "soundtrack", "music", "raws", "raw", "bd", "bluray", "blu", "ray", "hd", "sd",
    "remux", "proper", "repack", "unrated", "extended", "director", "directors", "cut",
    "2006", "2007", "2008", "2009", "2010", "2011", "2012", "2013", "2014",
    "2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026"
}


def parse_torrentio_stream(s: dict, season: Optional[int] = None, episode: Optional[int] = None) -> Optional[StreamItem]:
    """
    Parses a Torrentio Stremio V3 stream object into a rich StreamItem
    with exact file_idx, seeds, size, codecs, and multi-tracker magnet URL.
    """
    info_hash = (s.get("infoHash") or "").lower().strip()
    if not info_hash or len(info_hash) != 40:
        return None

    raw_title = s.get("title") or s.get("name") or "Torrentio Stream"
    lines = [l.strip() for l in raw_title.split("\n") if l.strip()]
    release_title = lines[0] if lines else "Torrent Release"

    meta_line = ""
    for l in lines:
        if "👤" in l or "💾" in l or "⚙️" in l:
            meta_line = l
            break

    seeds = 0
    m_seeds = re.search(r"👤\s*(\d+)", meta_line)
    if m_seeds:
        seeds = int(m_seeds.group(1))

    size_str = "Unknown"
    m_size = re.search(r"💾\s*([\d\.]+\s*[KMGT]?B)", meta_line, re.I)
    if m_size:
        size_str = m_size.group(1)

    provider = "Torrentio"
    m_prov = re.search(r"⚙️\s*([^\n\r]+)", meta_line)
    if m_prov:
        provider = m_prov.group(1).strip()

    filename = s.get("behaviorHints", {}).get("filename")
    if not filename and len(lines) > 1 and "👤" not in lines[1]:
        filename = lines[1].split("/")[-1].strip()

    name_lines = (s.get("name") or "").split("\n")
    quality = name_lines[1].strip() if len(name_lines) > 1 else "1080p"

    # Detect resolution
    res = quality if quality in ("4k", "2160p", "1080p", "720p", "480p") else None
    if not res:
        rm = re.search(r"\b(2160p|4k|1080p|720p|480p)\b", raw_title, re.I)
        res = rm.group(1).lower() if rm else "1080p"

    # Detect codec
    codec = None
    if re.search(r"\b(hevc|x265|h265)\b", raw_title, re.I):
        codec = "HEVC"
    elif re.search(r"\b(av1)\b", raw_title, re.I):
        codec = "AV1"
    elif re.search(r"\b(x264|h264)\b", raw_title, re.I):
        codec = "H.264"

    # Audio & HDR
    hdr_tag = None
    if re.search(r"\b(dolby vision|dv)\b", raw_title, re.I):
        hdr_tag = "Dolby Vision"
    elif re.search(r"\b(hdr10\+|hdr)\b", raw_title, re.I):
        hdr_tag = "HDR"

    audio_tag = None
    if re.search(r"\b(atmos|truehd)\b", raw_title, re.I):
        audio_tag = "Dolby Atmos"
    elif re.search(r"\b(dts)\b", raw_title, re.I):
        audio_tag = "DTS"
    elif re.search(r"\b(5\.1|ddp|ac3)\b", raw_title, re.I):
        audio_tag = "5.1 Surround"
    elif re.search(r"\b(dual[- ]audio|multi[- ]audio)\b", raw_title, re.I):
        audio_tag = "Dual-Audio"

    file_idx = s.get("fileIdx", 0)
    try:
        file_idx = int(file_idx) if file_idx is not None else 0
    except (ValueError, TypeError):
        file_idx = 0

    # Build comprehensive magnet link containing all source trackers
    trackers = []
    for src in s.get("sources", []):
        if isinstance(src, str) and src.startswith("tracker:"):
            trackers.append(src[8:])
    for tr in DEFAULT_ANIME_TRACKERS:
        if tr not in trackers:
            trackers.append(tr)

    tr_params = "".join(f"&tr={quote_plus(tr)}" for tr in trackers)
    dn_param = f"&dn={quote_plus(release_title)}"
    magnet = f"magnet:?xt=urn:btih:{info_hash}{dn_param}{tr_params}"

    ep_query = ""
    if season is not None:
        ep_query += f"&season={season}"
    if episode is not None:
        ep_query += f"&episode={episode}"
    stream_url = f"/api/v1/stream/play?info_hash={info_hash}&file_idx={file_idx}{ep_query}"

    badge_codec = f" {codec}" if codec else ""
    badge_name = f"[{provider}] {quality}{badge_codec}"
    full_title = f"{release_title} | {filename}" if (filename and filename != release_title) else release_title

    # Compute ranking score
    base_score = 50.0
    if "2160" in quality or "4k" in quality:
        base_score += 100.0
    elif "1080" in quality:
        base_score += 70.0
    elif "720" in quality:
        base_score += 40.0
    else:
        base_score += 20.0

    raw_lower = release_title.lower()
    if "remux" in raw_lower:
        base_score += 35.0
    elif "bluray" in raw_lower or "bdrip" in raw_lower:
        base_score += 25.0

    if hdr_tag:
        base_score += 10.0
    if audio_tag:
        base_score += 10.0
    if codec in ("HEVC", "AV1"):
        base_score += 8.0

    base_score += min(seeds, 200) * 0.4
    if episode is not None:
        base_score += 40.0

    return StreamItem(
        name=badge_name,
        title=full_title,
        info_hash=info_hash,
        file_idx=file_idx,
        quality=quality,
        resolution=res,
        codec=codec,
        audio=audio_tag,
        hdr=hdr_tag,
        seeds=seeds,
        peers=0,
        size=size_str,
        size_bytes=parse_size_to_bytes(size_str),
        tracker=provider,
        magnet=magnet,
        stream_url=stream_url,
        season=season,
        episode=episode,
        score=round(base_score, 1),
    )


async def fetch_torrentio_streams(
    imdb_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    media_type: str = "movie",
) -> List[StreamItem]:
    """
    Fetches real-time multi-tracker streams directly from Torrentio.
    """
    if not imdb_id or not imdb_id.startswith("tt"):
        return []

    is_episodic = bool(season is not None and episode is not None)
    target_type = "series" if (is_episodic or media_type in ("series", "anime")) else "movie"
    target_id = f"{imdb_id}:{season}:{episode}" if is_episodic else imdb_id

    endpoint = f"https://torrentio.strem.fun/stream/{target_type}/{target_id}.json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    try:
        data = await http_client.get_json(endpoint, timeout=8.0, headers=headers)
        if not isinstance(data, dict):
            return []

        raw_streams = data.get("streams", [])
        results: List[StreamItem] = []
        for s in raw_streams:
            if isinstance(s, dict):
                item = parse_torrentio_stream(s, season=season, episode=episode)
                if item:
                    results.append(item)
        return results
    except Exception as e:
        print(f"[StreamResolver] Torrentio fetch warning: {e}")
        return []


def is_same_show_title(target_title: str, release_title: str) -> bool:
    """
    Ensures release belongs to the requested show and is NOT a different spin-off/sequel.
    E.g. Target: 'Fairy Tail' vs Release: 'Fairy Tail: 100 Years Quest S01E08' -> False
    """
    clean_target = re.sub(r"[^\w\s]", " ", target_title.lower()).split()
    target_words = set(clean_target)

    # Strip leading release group brackets [GroupName] or (GroupName)
    clean_release = re.sub(r"^[\[\(].*?[\]\)]\s*", "", release_title.lower())
    clean_release = re.sub(r"[^\w\s]", " ", clean_release)

    # Cut off at season/episode/resolution/source indicators
    cutoff_match = re.search(
        r"\b(s\d+e\d+|s\d+|e\d+|season\s*\d+|ep\s*\d+|episode\s*\d+|\d{3,4}p|4k|2160p|bdrip|webrip|web\s*dl|x264|x265|hevc|h264|flac|aac)\b",
        clean_release,
    )
    if cutoff_match:
        title_part = clean_release[: cutoff_match.start()].strip()
    else:
        title_part = clean_release.strip()

    release_words = title_part.split()

    # All target words must be present in release title
    for tw in clean_target:
        if tw not in release_words:
            return False

    # Check if release title contains extra franchise-differentiating words
    for rw in release_words:
        if rw not in target_words and rw not in ALLOWED_TITLE_EXTRAS and not rw.isdigit():
            return False

    return True


def matches_target_episode(title: str, season: int, episode: int) -> bool:
    """Verifies that a release title actually contains the requested episode or season pack."""
    t = title.lower().replace(".", " ").replace("_", " ")

    # 1. Check exact SxxExx (e.g. S01E08 or S1E8)
    ep_pattern = rf"\bs0?{season}\s*e0?{episode}\b"
    if re.search(ep_pattern, t):
        return True

    # 2. Check anime absolute episode format (e.g. " - 08 " or " 08 " or " ep 08 ")
    if episode not in (720, 1080, 2160):
        # Ensure it doesn't match a different season (e.g. S02E08 when looking for S01E08)
        other_season = re.search(r"\bs0?([2-9]|\d{2,})\b", t)
        if not other_season or season > 1:
            if re.search(rf"\b(?:ep|episode|e)?\s*0*{episode}\b", t):
                # Ensure it doesn't match a different episode number in SxxExx
                other_ep = re.search(r"\bs0?\d+\s*e0?(\d+)\b", t)
                if not other_ep or int(other_ep.group(1)) == episode:
                    return True

    # 3. Check complete season packs: e.g. "season 1", "s01", "season 1-8"
    season_pack = rf"\b(season\s*0?{season}|s0?{season}\b(?!e\d)|seasons?\s*1\s*[-–~8])"
    if re.search(season_pack, t):
        # Ensure it doesn't match a DIFFERENT specific episode (e.g. S01E02 when looking for S01E08)
        other_ep = re.search(r"\bs0?\d+\s*e0?(\d+)\b", t)
        if other_ep and int(other_ep.group(1)) != episode:
            return False
        return True

    return False


async def resolve_streams(
    title: str,
    imdb_id: Optional[str] = None,
    year: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    media_type: str = "movie",
) -> StreamResolveResponse:
    """
    Torrentio-grade multi-tracker stream resolver.
    Queries Torrentio and all local torrent providers in parallel, ranks streams by
    quality, codec, seeds, and maps episode target files with full multi-tracker announces.
    """
    start_time = time.time()
    clean_title = re.sub(r"[^a-zA-Z0-9\s]", " ", title).strip()

    cache_key = f"streams:resolve:{clean_title}:{imdb_id or ''}:{season or ''}:{episode or ''}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # Auto-resolve IMDb ID if missing
    if not imdb_id or not imdb_id.startswith("tt"):
        try:
            from core.discover import search_catalog
            disc_results = await search_catalog(clean_title, media_type=media_type)
            if disc_results:
                for it in disc_results:
                    if it.id.startswith("tt"):
                        imdb_id = it.id
                        break
        except Exception as e:
            print(f"[StreamResolver] Auto IMDb ID resolution notice: {e}")

    # Build targeted search query list for local scrapers
    queries: List[str] = []
    is_episodic = bool(season is not None and episode is not None)

    if is_episodic:
        queries.append(f"{clean_title} S{season:02d}E{episode:02d}")
        if media_type == "anime":
            anime_queries = AnimeOffsetEngine.get_search_queries(clean_title, season, episode)
            queries.extend(anime_queries)
        queries.append(f"{clean_title} S{season:02d}")
    else:
        if year:
            queries.append(f"{clean_title} {year}")
        queries.append(clean_title)
        if imdb_id:
            queries.append(imdb_id)

    # Deduplicate queries while preserving priority
    seen_q = set()
    targeted_queries: List[str] = []
    for q in queries:
        qk = q.strip().lower()
        if qk and qk not in seen_q:
            seen_q.add(qk)
            targeted_queries.append(q.strip())

    # Dispatch searches across capable providers with bounded concurrency
    scraper_semaphore = asyncio.Semaphore(10)

    async def _bounded_search(provider, q):
        async with scraper_semaphore:
            try:
                return await provider.search(q, limit=25)
            except Exception:
                return []

    capable_providers = get_capable_providers(media_type)
    tasks = []
    for q in targeted_queries[:3]:
        for p in capable_providers:
            tasks.append(_bounded_search(p, q))
        if media_type == "anime":
            tasks.append(_bounded_search(get_nyaa_scraper(), q))

    # Add Torrentio fast multi-tracker stream task
    torrentio_task = None
    if imdb_id and imdb_id.startswith("tt"):
        torrentio_task = asyncio.create_task(
            fetch_torrentio_streams(
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                media_type=media_type,
            )
        )

    # Add Web CDN scraper task if IMDb ID is available
    cdn_task = None
    if imdb_id:
        cdn_task = asyncio.create_task(
            get_web_cdn_scraper().get_streams(
                imdb_id=imdb_id,
                media_type=media_type,
                season=season,
                episode=episode,
            )
        )

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    raw_results: List[TorrentItem] = []
    for r in gathered:
        if isinstance(r, list):
            raw_results.extend(r)

    # Deduplicate local scraper torrents by info_hash
    deduped = deduplicate_torrents(raw_results)

    scored_streams: List[StreamItem] = []
    seen_hashes = set()

    # 1. Harvest Torrentio streams first (highest seed accuracy, exact fileIdx, full 27+ tracker announce)
    if torrentio_task:
        try:
            t_streams = await torrentio_task
            for s in t_streams:
                h = s.info_hash.lower()
                if h not in seen_hashes:
                    # Filter out conflicting spin-offs or sequels if present
                    if not is_same_show_title(clean_title, s.title):
                        continue
                    seen_hashes.add(h)
                    scored_streams.append(s)
        except Exception as e:
            print(f"[StreamResolver] Torrentio harvest warning: {e}")

    # 2. Filter and score local scraper streams
    for item in deduped:
        if not item.info_hash:
            continue
        h = item.info_hash.lower()
        if h in seen_hashes:
            continue

        # Reject conflicting spin-offs, sequels, and other franchises
        if not is_same_show_title(clean_title, item.title):
            continue

        is_exact = False
        if is_episodic:
            if not matches_target_episode(item.title, season, episode):
                continue
            is_exact = bool(re.search(rf"\bs0?{season}e0?{episode}\b", item.title.lower()))

        score = compute_stream_score(item, is_exact_ep=is_exact)

        # Detect audio and HDR
        raw_t = item.title.lower()
        hdr_tag = ", ".join(item.metadata.hdr) if item.metadata.hdr else None
        if not hdr_tag:
            if "dv" in raw_t or "dolby vision" in raw_t:
                hdr_tag = "Dolby Vision"
            elif "hdr" in raw_t:
                hdr_tag = "HDR"

        audio_tag = None
        if "atmos" in raw_t or "truehd" in raw_t:
            audio_tag = "Dolby Atmos"
        elif "dts" in raw_t:
            audio_tag = "DTS"
        elif "5.1" in raw_t or "ddp" in raw_t or "ac3" in raw_t:
            audio_tag = "5.1 Surround"
        elif "aac" in raw_t:
            audio_tag = "AAC Stereo"

        ep_query = ""
        if season is not None:
            ep_query += f"&season={season}"
        if episode is not None:
            ep_query += f"&episode={episode}"
        stream_url = f"/api/v1/stream/play?info_hash={item.info_hash}&file_idx=0{ep_query}"

        # Inject robust tracker list into local magnet
        local_magnet = item.magnet_uri
        if local_magnet and "&tr=" not in local_magnet:
            extra_tr = "".join(f"&tr={quote_plus(tr)}" for tr in DEFAULT_ANIME_TRACKERS)
            local_magnet = f"{local_magnet}{extra_tr}"

        seen_hashes.add(h)
        scored_streams.append(
            StreamItem(
                name=extract_stream_badge(item),
                title=item.title,
                info_hash=item.info_hash,
                file_idx=0,
                quality=item.metadata.resolution or "1080p",
                resolution=item.metadata.resolution,
                codec=item.metadata.codec,
                audio=audio_tag,
                hdr=hdr_tag,
                seeds=item.seeders,
                peers=item.leechers,
                size=item.size_formatted,
                size_bytes=item.size_bytes,
                tracker=item.sources[0] if item.sources else "Torrentio",
                magnet=local_magnet,
                stream_url=stream_url,
                season=season,
                episode=episode,
                score=round(score, 1),
            )
        )

    # 3. Check Debrid cache availability for candidate streams
    debrid_mgr = get_debrid_manager()
    if debrid_mgr.active_providers and scored_streams:
        candidate_hashes = [s.info_hash for s in scored_streams[:35]]
        try:
            cache_map = await debrid_mgr.check_cache(candidate_hashes)
            for s in scored_streams:
                h_low = s.info_hash.lower()
                for prov_name, hash_dict in cache_map.items():
                    if hash_dict.get(h_low):
                        s.is_debrid_cached = True
                        s.debrid_provider = prov_name.capitalize()
                        s.name = f"[⚡ {s.debrid_provider.upper()} CACHED] {s.name}"
                        s.score += 150.0  # Promote instant cloud streams
                        break
        except Exception as e:
            print(f"[StreamResolver] Debrid cache check warning: {e}")

    # 4. Add Web CDN streams if resolved
    if cdn_task:
        try:
            cdn_streams = await cdn_task
            for cdn_item in cdn_streams:
                scored_streams.append(
                    StreamItem(
                        name=cdn_item["name"],
                        title=cdn_item["title"],
                        info_hash=cdn_item["info_hash"],
                        file_idx=0,
                        quality=cdn_item["quality"]["resolution"],
                        resolution=cdn_item["quality"]["resolution"],
                        codec=cdn_item["quality"]["codec"],
                        audio=cdn_item["quality"]["audio"],
                        hdr=None,
                        seeds=cdn_item["seeds"],
                        peers=0,
                        size=cdn_item["size_str"],
                        size_bytes=0,
                        tracker=cdn_item["tracker"],
                        magnet=None,
                        stream_url=cdn_item.get("embed_url"),
                        score=cdn_item["score"],
                        is_cdn=True,
                        embed_url=cdn_item.get("embed_url"),
                    )
                )
        except Exception as e:
            print(f"[StreamResolver] Web CDN stream warning: {e}")

    # 5. Sort streams by quality score descending
    scored_streams.sort(key=lambda s: (s.score, s.seeds), reverse=True)

    elapsed_ms = round((time.time() - start_time) * 1000, 1)
    response = StreamResolveResponse(
        streams=scored_streams,
        total=len(scored_streams),
        imdb_id=imdb_id,
        title=title,
        season=season,
        episode=episode,
        resolved_time_ms=elapsed_ms,
    )

    if scored_streams:
        await cache.set(cache_key, response, ttl=1800)  # 30 min cache

    return response
