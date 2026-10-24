import asyncio
import re
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from core.cache import cache
from core.client import http_client
from core.security import validate_outbound_proxy_url, verify_api_key
from models.subtitle import SubtitleItem, SubtitleSearchResponse
from providers.subtitles import SUBTITLE_PROVIDERS

router = APIRouter(prefix="/api/v1/subtitles", tags=["Subtitles"], dependencies=[Depends(verify_api_key)])


def clean_title_for_catalog(title: str) -> str:
    """Extracts base show/movie name from torrent release title for catalog search."""
    # If title has a batch pipeline divider '|', examine the file segment first
    raw = title.split("|")[-1] if "|" in title else title
    s = re.sub(r"^\[[^\]]+\]\s*", "", raw)  # remove release group e.g. [SubsPlease]
    s = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", s)  # remove tags in brackets/parens
    s = re.sub(r"\b(19\d\d|20\d\d)\b.*$", "", s)
    s = re.sub(r"(?:-|\bS\d+|\bE\d+|\bEp\s*\d+|\bEpisode\s*\d+|1080p|720p|480p|4k|x264|x265|hevc|web-?dl|bluray).*$", "", s, flags=re.I)
    cleaned = s.replace(".", " ").replace("_", " ").strip()
    if not cleaned and "|" in title:
        raw = title.split("|")[0]
        s = re.sub(r"^\[[^\]]+\]\s*", "", raw)
        s = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", s)
        s = re.sub(r"\b(19\d\d|20\d\d)\b.*$", "", s)
        s = re.sub(r"(?:-|\bS\d+|\bE\d+|\bEp\s*\d+|\bEpisode\s*\d+|1080p|720p|480p|4k|x264|x265|hevc|web-?dl|bluray).*$", "", s, flags=re.I)
        cleaned = s.replace(".", " ").replace("_", " ").strip()
    return cleaned


async def resolve_imdb_id(query: str, is_series: bool = False) -> Optional[str]:
    """Resolves media title to IMDb ID using zero-auth Cinemeta catalog."""
    if not query:
        return None
    match = re.search(r"tt\d+", query, re.IGNORECASE)
    if match:
        return match.group(0)

    # First attempt with cleaned title, candidate segments for batch torrents, and raw query
    cleaned = clean_title_for_catalog(query)
    candidates = [cleaned]
    if "|" in query:
        for seg in query.split("|"):
            c_seg = clean_title_for_catalog(seg)
            if c_seg and c_seg not in candidates:
                candidates.append(c_seg)
    if query.strip() not in candidates:
        candidates.append(query.strip())
    cat_types = ["series", "movie"] if is_series else ["movie", "series"]

    for cand in candidates:
        if not cand:
            continue
        for cat_type in cat_types:
            try:
                endpoint = f"https://v3-cinemeta.strem.io/catalog/{cat_type}/top/search={cand}.json"
                data = await http_client.get_json(endpoint, timeout=3.5)
                metas = data.get("metas") or []
                if metas:
                    cand_lower = cand.lower()
                    for m in metas:
                        if m.get("name", "").strip().lower() == cand_lower:
                            return m.get("imdb_id")
                    return metas[0].get("imdb_id")
            except Exception:
                pass
    return None


LANG_ALIASES = {
    "en": {"en", "eng", "english"},
    "es": {"es", "spa", "spanish", "espanol", "castellano"},
    "fr": {"fr", "fre", "fra", "french", "francais"},
    "ar": {"ar", "ara", "arabic"},
    "de": {"de", "ger", "deu", "german", "deutsch"},
    "it": {"it", "ita", "italian", "italiano"},
    "pt": {"pt", "por", "portuguese", "portugues"},
    "ru": {"ru", "rus", "russian"},
    "ja": {"ja", "jpn", "japanese"},
    "ko": {"ko", "kor", "korean"},
    "zh": {"zh", "chi", "zho", "chinese"},
    "hi": {"hi", "hin", "hindi"},
    "tr": {"tr", "tur", "turkish"},
}


def matches_target_language(item_lang_code: str, item_language: str, target: str) -> bool:
    target_clean = (target or "").lower().strip()
    if target_clean in ("all", "any", "*", ""):
        return True

    code = (item_lang_code or "").lower().strip()
    name = (item_language or "").lower().strip()

    aliases = LANG_ALIASES.get(target_clean)
    if aliases:
        if code in aliases or name in aliases:
            return True
        for a in aliases:
            if len(a) > 3 and a in name:
                return True
        return False

    return code == target_clean or name == target_clean or (code and code[:2] == target_clean)


@router.get("/hash-search")
async def search_subtitles_by_file_hash(
    movie_hash: str = Query(..., description="64-bit hexadecimal OpenSubtitles movie hash"),
    file_size: int = Query(..., description="Total size in bytes"),
    lang: str = Query("en", description="Subtitle language code"),
):
    """
    Frame-perfect subtitle search using OpenSubtitles 64-bit binary checksum.
    Guarantees 0ms audio/subtitle drift.
    """
    from core.hash_matcher import search_subtitles_by_hash
    results = await search_subtitles_by_hash(movie_hash=movie_hash, file_size=file_size, lang=lang)
    return {"movie_hash": movie_hash, "file_size": file_size, "subtitles": results}


@router.get("/search", response_model=SubtitleSearchResponse)
async def search_subtitles(
    query: Optional[str] = Query(None, description="Movie or series title"),
    imdb_id: Optional[str] = Query(None, description="IMDb ID (tt0816692)"),
    season: Optional[int] = Query(None, description="TV Season number"),
    episode: Optional[int] = Query(None, description="TV Episode number"),
    language: Optional[str] = Query(None, description="Language filter (e.g. en, es, fr)"),
    info_hash: Optional[str] = Query(None, description="BitTorrent info hash for exact torrent subtitle demuxing"),
    provider: str = Query("all", description="Target provider or 'all'"),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Search synchronized subtitles across multi-tier providers.
    Supports movies and episodic TV series lookups.
    """
    if not query and not imdb_id and not info_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'query', 'imdb_id', or 'info_hash' must be specified.",
        )

    # Discard non-IMDb format ids (such as 'kitsu:4502' or 'tmdb:123')
    if imdb_id and not re.match(r"^tt\d+$", str(imdb_id).strip(), re.I):
        imdb_id = None

    # Automatically resolve IMDb ID from title if missing or non-IMDb
    if not imdb_id and query:
        is_ser = bool(season or episode)
        imdb_id = await resolve_imdb_id(query, is_series=is_ser)

    provider_name = str(getattr(provider, "default", provider) or "all").lower()
    limit_val = int(getattr(limit, "default", limit) or 50)
    cache_key = f"sub_search:{provider_name}:{query}:{imdb_id}:{season}:{episode}:{language}:{info_hash}:{limit_val}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    start = time.time()
    all_results: List[SubtitleItem] = []

    if provider_name != "all":
        p = SUBTITLE_PROVIDERS.get(provider_name)
        if p:
            all_results = await p.search(
                query=query or "",
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                language=language or "en",
                info_hash=info_hash,
                limit=limit_val,
            )
    else:
        tasks = [
            p.search(
                query=query or "",
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                language=language or "all",
                info_hash=info_hash,
                limit=limit_val,
            )
            for p in SUBTITLE_PROVIDERS.values()
        ]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for r in gathered:
            if isinstance(r, list):
                all_results.extend(r)

    # Filter language only if an explicit specific language was requested (not 'all' or empty)
    if language and language.lower() not in ("all", "any", "*", ""):
        all_results = [
            s for s in all_results
            if matches_target_language(s.lang_code, s.language, language)
        ]

    final_results = all_results[:limit_val]
    elapsed = round(time.time() - start, 3)

    response = SubtitleSearchResponse(
        query=query,
        imdb_id=imdb_id,
        total=len(final_results),
        time_taken=elapsed,
        data=final_results,
    )
    await cache.set(cache_key, response, ttl=1800)
    return response


@router.get("/by-hash", response_model=SubtitleSearchResponse)
async def search_by_hash(
    info_hash: Optional[str] = Query(None, description="BitTorrent 40-char SHA1 infoHash (AnimeTosho sync)"),
    video_hash: Optional[str] = Query(None, description="OpenSubtitles 16-char video hash"),
    video_size: Optional[int] = Query(None, description="Binary video file size in bytes"),
    imdb_id: Optional[str] = Query(None, description="Associated IMDb ID"),
):
    """
    Search exact-sync subtitles using BitTorrent infoHash (Anime softsubs)
    or OpenSubtitles 64-bit binary video hash.
    """
    start = time.time()
    results: List[SubtitleItem] = []

    if info_hash:
        atosho = SUBTITLE_PROVIDERS.get("animetosho")
        if atosho:
            results = await atosho.search("", info_hash=info_hash)

    elif video_hash and video_size:
        opensubs = SUBTITLE_PROVIDERS.get("opensubtitles")
        if opensubs:
            results = await opensubs.search(
                "", imdb_id=imdb_id, video_hash=video_hash, video_size=video_size
            )

    elapsed = round(time.time() - start, 3)
    return SubtitleSearchResponse(
        query=info_hash or video_hash,
        imdb_id=imdb_id,
        total=len(results),
        time_taken=elapsed,
        data=results,
    )


@router.api_route("/download", methods=["GET", "HEAD"])
async def proxy_download(request: Request, url: str = Query(..., description="Upstream subtitle download URL")):
    """
    Reverse proxy download endpoint.
    Bypasses anti-hotlinking headers (Referer requirements on Addic7ed, YIFY, etc.).
    """
    if request.method == "HEAD":
        return Response(status_code=200, headers={"Content-Type": "application/x-subrip"})

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        if "yify" in url:
            headers["Referer"] = "https://yifysubtitles.ch/"
        elif "addic7ed" in url:
            headers["Referer"] = "https://www.addic7ed.com/"

        client = await http_client.get_httpx_client()
        target_url = url
        if target_url.startswith("/"):
            base_url = str(request.base_url).rstrip("/")
            target_url = f"{base_url}{target_url}"
        validate_outbound_proxy_url(target_url)
        resp = await client.get(target_url, headers=headers)
        if resp.status_code >= 400 and len(resp.content) < 50:
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "application/octet-stream")
        content_disposition = resp.headers.get("content-disposition", 'attachment; filename="subtitle.srt"')

        return Response(
            content=resp.content,
            media_type=content_type,
            headers={"Content-Disposition": content_disposition},
        )
    except HTTPException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch subtitle from upstream provider: {str(e)}",
        )


def ass_to_webvtt(ass_text: str, offset_seconds: float = 0.0) -> str:
    """Converts Advanced SubStation Alpha (.ass / .ssa) anime subtitles to WebVTT."""
    text = ass_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out_lines = ["WEBVTT", ""]

    def parse_ass_time(t_str: str) -> float:
        parts = t_str.strip().split(":")
        if len(parts) == 3:
            try:
                h = float(parts[0])
                m = float(parts[1])
                s = float(parts[2])
                return h * 3600.0 + m * 60.0 + s
            except Exception:
                pass
        return 0.0

    def format_vtt_time(sec: float) -> str:
        sec = max(0.0, sec)
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

    in_events = False
    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith("[Events]"):
            in_events = True
            continue
        elif trimmed.startswith("[") and in_events:
            in_events = False
            continue

        if in_events and trimmed.startswith("Dialogue:"):
            # Standard format: Dialogue: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
            payload = trimmed[9:].strip()
            parts = payload.split(",", 9)
            if len(parts) >= 10:
                start_sec = parse_ass_time(parts[1]) + offset_seconds
                end_sec = parse_ass_time(parts[2]) + offset_seconds
                if end_sec <= start_sec:
                    continue

                dialogue = parts[9]
                # Strip ASS override tags {\pos(...) }, {\an8}, {\b1}, etc.
                dialogue = re.sub(r"\{[^}]*\}", "", dialogue)
                # Normalize line breaks and spaces
                dialogue = re.sub(r"\\[nN]", "\n", dialogue)
                dialogue = dialogue.replace(r"\h", " ")
                dialogue = re.sub(r"<[^>]*>", "", dialogue).strip()

                if dialogue:
                    out_lines.append(f"{format_vtt_time(start_sec)} --> {format_vtt_time(end_sec)}")
                    out_lines.append(dialogue)
                    out_lines.append("")

    return "\n".join(out_lines) + "\n"


def srt_to_webvtt(srt_text: str, offset_seconds: float = 0.0) -> str:
    """Converts SRT subtitle string to WebVTT format, applying optional time shift."""
    text = srt_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    out_lines = ["WEBVTT", ""]
    time_pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")

    def shift_time(h, m, s, ms, delta):
        total_sec = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0 + delta
        if total_sec < 0:
            total_sec = 0.0
        nh = int(total_sec // 3600)
        nm = int((total_sec % 3600) // 60)
        ns = int(total_sec % 60)
        nms = int(round((total_sec - int(total_sec)) * 1000))
        return f"{nh:02d}:{nm:02d}:{ns:02d}.{nms:03d}"

    for line in lines:
        m = time_pattern.search(line)
        if m:
            h1, m1, s1, ms1, h2, m2, s2, ms2 = m.groups()
            t1 = shift_time(h1, m1, s1, ms1, offset_seconds)
            t2 = shift_time(h2, m2, s2, ms2, offset_seconds)
            out_lines.append(f"{t1} --> {t2}")
        else:
            out_lines.append(line)

    return "\n".join(out_lines) + "\n"


def select_zip_subtitle_member(namelist: List[str], target_lang: str = "en") -> Optional[str]:
    """
    Selects the most suitable subtitle file from a ZIP archive.
    Prioritizes filenames matching the target language or language aliases.
    """
    valid_members = [n for n in namelist if n.lower().endswith((".srt", ".vtt", ".ass", ".ssa"))]
    if not valid_members:
        return None

    clean_target = (target_lang or "en").lower().strip()
    aliases = LANG_ALIASES.get(clean_target, {clean_target})

    for m in valid_members:
        m_low = m.lower()
        if any(a in m_low for a in aliases):
            return m

    # Fallback to English if target wasn't found
    if clean_target != "en":
        for m in valid_members:
            m_low = m.lower()
            if any(a in m_low for a in LANG_ALIASES.get("en", {"en", "eng", "english"})):
                return m

    return valid_members[0]


@router.api_route("/vtt", methods=["GET", "HEAD"])
async def proxy_subtitle_vtt(
    request: Request,
    url: str = Query(..., description="Upstream subtitle download or proxy URL"),
    offset: float = Query(0.0, description="Optional time offset in seconds (+/-)"),
):
    """
    Downloads any upstream subtitle (SRT, VTT, ASS, SSA, or ZIP archive),
    extracts the text, applies optional time offset, converts to WebVTT,
    and serves with proper MIME text/vtt; charset=utf-8 with CORS headers.
    """
    if request.method == "HEAD":
        return Response(
            status_code=200,
            media_type="text/vtt; charset=utf-8",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
                "Content-Type": "text/vtt; charset=utf-8",
            },
        )
    import io
    import zipfile
    try:
        import charset_normalizer
    except ImportError:
        charset_normalizer = None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "*/*",
        }
        if "yify" in url:
            headers["Referer"] = "https://yifysubtitles.ch/"
        elif "addic7ed" in url:
            headers["Referer"] = "https://www.addic7ed.com/"

        client = await http_client.get_httpx_client()
        target_url = url
        if target_url.startswith("/"):
            base_url = str(request.base_url).rstrip("/")
            target_url = f"{base_url}{target_url}"
        validate_outbound_proxy_url(target_url)
        resp = await client.get(target_url, headers=headers)
        if resp.status_code >= 400 and len(resp.content) < 50:
            resp.raise_for_status()
        raw = resp.content

        # Handle ZIP archives (YIFY / OpenSubtitles / SubSource / AnimeTosho)
        if raw.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                chosen = select_zip_subtitle_member(z.namelist(), target_lang="en")
                if chosen:
                    raw = z.read(chosen)

        # Decode using charset_normalizer for flawless multilingual accents (Arabic, Cyrillic, etc.)
        if charset_normalizer:
            match = charset_normalizer.from_bytes(raw).best()
            text = str(match) if match else raw.decode("utf-8", errors="replace")
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")

        # Automatically detect and convert ASS/SSA vs SRT to WebVTT
        is_ass = "[Script Info]" in text or "[Events]" in text or "Dialogue:" in text or url.lower().endswith((".ass", ".ssa"))
        if is_ass:
            vtt_content = ass_to_webvtt(text, offset_seconds=offset)
        else:
            vtt_content = srt_to_webvtt(text, offset_seconds=offset)

        return Response(
            content=vtt_content,
            media_type="text/vtt; charset=utf-8",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "public, max-age=86400",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to process subtitle to WebVTT: {str(e)}",
        )

