import re
from typing import Optional, Tuple
from core.cache import cache
from core.client import http_client
from models.media import MediaDetails


def clean_title_and_extract_meta(raw_title: str) -> Tuple[str, Optional[int], bool]:
    """
    Cleans raw torrent release titles by removing scene tags, resolution,
    codecs, audio types, and release groups, returning:
    (clean_title, year, is_series)
    """
    if not raw_title:
        return "", None, False

    t = raw_title.strip()

    # Handle composite batch release titles separated by '|' (e.g. "Series Batch | Episode File.mkv")
    if "|" in t:
        parts = [p.strip() for p in t.split("|") if p.strip()]
        t = parts[-1] if len(parts) > 1 else parts[0]

    # 1. Check if IMDb ID is already present
    match_imdb = re.search(r"\b(tt\d+)\b", t, re.IGNORECASE)
    if match_imdb:
        return match_imdb.group(1), None, False

    # 2. Strip leading uploader/tracker brackets e.g. [YTS.MX], [Erai-raws]
    t = re.sub(r"^\s*\[[^\]]+\]\s*", "", t)

    # 3. Detect if it's an episodic TV series
    is_series = bool(re.search(r"\b(s\d\d?e\d\d?|s\d\d?|season\s*\d+|complete\s*series)\b", t, re.IGNORECASE))

    # 4. Extract 4-digit release year
    year: Optional[int] = None
    year_matches = list(re.finditer(r"\b(19\d\d|20\d\d)\b", t))
    if year_matches:
        # If title starts with a year (e.g. 1917, 2001, 2012) and has a subsequent year, use the subsequent year as release year
        if year_matches[0].start() == 0 and len(year_matches) > 1:
            year = int(year_matches[-1].group(1))
        elif year_matches[0].start() > 0:
            year = int(year_matches[0].group(1))

    # 5. Replace dots, underscores, and multiple spaces
    t = t.replace(".", " ").replace("_", " ")

    # 6. Truncate before scene tags, quality, codec, or season markers
    pattern = r"\b(19\d\d|20\d\d|2160p|1080p|720p|480p|uhd|remux|bluray|bdrip|web-?dl|webrip|hdtv|hevc|x265|x264|dvdrip|s\d\d?e\d\d?|s\d\d?|season\s*\d+|complete|french|truefrench|multi|ita|ger|spa)\b"
    clean = t.strip()
    for cut_match in re.finditer(pattern, t, re.IGNORECASE):
        # Never truncate at index 0 (which would wipe titles starting with numbers/tags like 1917, 2001, 2012)
        if cut_match.start() > 0:
            clean = t[:cut_match.start()].strip()
            break

    # 7. Strip trailing hyphens, brackets, colons
    clean = re.sub(r"[\(\[\{\-\:\s]+$", "", clean).strip()

    # If clean title became empty, fallback to raw title without dots
    if not clean:
        clean = raw_title.replace(".", " ").strip()

    return clean, year, is_series


async def fetch_media_details(
    query: Optional[str] = None,
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
) -> Optional[MediaDetails]:
    """
    Resolves rich movie / series metadata, HD poster jacket, backdrop artwork,
    IMDb rating, runtime, director, cast, plot, and trailer video.
    Queries Cinemeta open catalog and IMDb suggestion APIs with zero API keys required.
    """
    if not query and not imdb_id:
        return None

    # Check cache first (24 hour TTL)
    cache_key = f"media_meta:{imdb_id or ''}:{query or ''}:{year or ''}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    clean_title = ""
    is_series = False

    # Check if query itself is an IMDb ID
    if query and query.strip().lower().startswith("tt") and len(query.strip()) >= 7:
        imdb_id = query.strip().lower()

    if not imdb_id and query:
        clean_title, extracted_year, is_series = clean_title_and_extract_meta(query)
        if not year and extracted_year:
            year = extracted_year

        # Step 1: Query Cinemeta catalog search
        cat_type = "series" if is_series else "movie"
        try:
            endpoint = f"https://v3-cinemeta.strem.io/catalog/{cat_type}/top/search={clean_title}.json"
            data = await http_client.get_json(endpoint, timeout=10.0)
            metas = data.get("metas") or []
            if metas:
                # Match title / year if possible
                best_match = metas[0]
                for m in metas:
                    if str(m.get("year")) == str(year):
                        best_match = m
                        break
                imdb_id = best_match.get("imdb_id")
        except Exception:
            pass

        # Step 2: Fallback to IMDb direct suggestion API
        if not imdb_id:
            try:
                slug = re.sub(r"[^a-zA-Z0-9\s]", "", clean_title).strip().lower().replace(" ", "_")
                if slug:
                    endpoint = f"https://v3.sg.media-imdb.com/suggestion/x/{slug}.json"
                    data = await http_client.get_json(endpoint, timeout=8.0)
                    entries = data.get("d") or []
                    for it in entries:
                        entry_id = it.get("id") or ""
                        if entry_id.startswith("tt"):
                            entry_year = it.get("y")
                            if year and entry_year and abs(int(entry_year) - int(year)) <= 1:
                                imdb_id = entry_id
                                break
                            elif not imdb_id:
                                imdb_id = entry_id
            except Exception:
                pass

    if not imdb_id:
        return None

    # Step 3: Fetch full rich metadata from Cinemeta using the resolved IMDb ID
    media_data: Optional[MediaDetails] = None
    for target_cat in (["series", "movie"] if is_series else ["movie", "series"]):
        try:
            url = f"https://v3-cinemeta.strem.io/meta/{target_cat}/{imdb_id}.json"
            res = await http_client.get_json(url, timeout=10.0)
            meta = res.get("meta")
            if meta:
                trailers = meta.get("trailers") or []
                trailer_key = trailers[0].get("source") if trailers else None
                trailer_url = f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else None
                trailer_embed = f"https://www.youtube-nocookie.com/embed/{trailer_key}" if trailer_key else None

                director = meta.get("director")
                if isinstance(director, list):
                    director = ", ".join(director[:2]) if director else None

                cast_list = meta.get("cast") or []
                if isinstance(cast_list, list):
                    cast_list = cast_list[:5]

                poster_url = meta.get("poster")
                # Ensure medium/large poster sizing if metahub
                if poster_url and "poster/small/" in poster_url:
                    poster_url = poster_url.replace("poster/small/", "poster/medium/")

                backdrop_url = meta.get("background")

                media_data = MediaDetails(
                    title=meta.get("name") or clean_title or "Unknown Media",
                    year=str(meta.get("year")) if meta.get("year") else (str(year) if year else None),
                    imdb_id=imdb_id,
                    type=meta.get("type") or target_cat,
                    poster_url=poster_url,
                    backdrop_url=backdrop_url,
                    rating=str(meta.get("imdbRating")) if meta.get("imdbRating") else None,
                    runtime=meta.get("runtime"),
                    genres=meta.get("genres") or [],
                    plot=meta.get("description"),
                    director=director,
                    cast=cast_list,
                    trailer_url=trailer_url,
                    trailer_embed=trailer_embed,
                    source="cinemeta",
                )
                break
        except Exception:
            continue

    # Fallback to basic IMDb info if Cinemeta full meta failed
    if not media_data and imdb_id:
        media_data = MediaDetails(
            title=clean_title or query or imdb_id,
            year=str(year) if year else None,
            imdb_id=imdb_id,
            type="series" if is_series else "movie",
            source="imdb_basic",
        )

    if media_data:
        await cache.set(cache_key, media_data, ttl=86400)

    return media_data
