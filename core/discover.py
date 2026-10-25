import asyncio
import re
from typing import Dict, List, Optional
from core.anime_client import AnimeClient
from core.cache import cache
from core.client import http_client
from models.discover import (
    DiscoverCatalogResponse,
    DiscoverDetail,
    DiscoverItem,
    EpisodeItem,
    SeasonInfo,
)


def _normalize_poster(poster_url: Optional[str]) -> Optional[str]:
    """Upgrades metahub small thumbnails to medium/large posters."""
    if not poster_url:
        return None
    if "poster/small/" in poster_url:
        return poster_url.replace("poster/small/", "poster/medium/")
    return poster_url


def _filter_and_sort_items(
    items: List[DiscoverItem],
    min_rating: Optional[float] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    sort: Optional[str] = "popular",
) -> List[DiscoverItem]:
    """Filters and sorts catalog items according to criteria."""
    res = list(items)
    if min_rating is not None:
        def _match_rating(it: DiscoverItem) -> bool:
            if not it.rating:
                return False
            try:
                return float(it.rating) >= float(min_rating)
            except (ValueError, TypeError):
                return False
        res = [it for it in res if _match_rating(it)]

    if year_from is not None or year_to is not None:
        def _match_year(it: DiscoverItem) -> bool:
            if not it.year:
                return False
            try:
                m = re.search(r"\b(19\d\d|20\d\d)\b", str(it.year))
                if not m:
                    return False
                y = int(m.group(1))
                if year_from is not None and y < year_from:
                    return False
                if year_to is not None and y > year_to:
                    return False
                return True
            except (ValueError, TypeError):
                return False
        res = [it for it in res if _match_year(it)]

    if sort:
        s = sort.lower().strip()
        if s == "rating_desc":
            def _get_rating(it):
                try:
                    return float(it.rating or 0)
                except (ValueError, TypeError):
                    return 0.0
            res.sort(key=_get_rating, reverse=True)
        elif s == "rating_asc":
            def _get_rating(it):
                try:
                    return float(it.rating or 0)
                except (ValueError, TypeError):
                    return 0.0
            res.sort(key=_get_rating)
        elif s == "year_desc":
            def _get_year(it):
                try:
                    m = re.search(r"\b(19\d\d|20\d\d)\b", str(it.year or ""))
                    return int(m.group(1)) if m else 0
                except (ValueError, TypeError):
                    return 0
            res.sort(key=_get_year, reverse=True)
        elif s == "year_asc":
            def _get_year(it):
                try:
                    m = re.search(r"\b(19\d\d|20\d\d)\b", str(it.year or ""))
                    return int(m.group(1)) if m else 9999
                except (ValueError, TypeError):
                    return 9999
            res.sort(key=_get_year)
        elif s == "title_asc":
            res.sort(key=lambda it: (it.title or "").lower())

    return res


async def fetch_catalog(
    media_type: str = "movie",
    catalog: str = "top",
    genre: Optional[str] = None,
    page: int = 1,
    min_rating: Optional[float] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    sort: Optional[str] = "popular",
) -> DiscoverCatalogResponse:
    """
    Fetches curated visual catalogs for movies, TV series, or anime.
    Supports catalog feeds (top, trending, new) and genre/category filtering.
    Backed by tiered caching (6 hours).
    """
    cache_key = f"discover:catalog:{media_type}:{catalog}:{genre or 'all'}:{page}:{min_rating}:{year_from}:{year_to}:{sort}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    items: List[DiscoverItem] = []

    # If media_type is anime and a specific category (all, tv, movie, ova, special) is specified:
    anime_cats = {"all", "tv", "movie", "ova", "ona", "special", "specials", "off-season"}
    if media_type == "anime" and genre and genre.lower() in anime_cats:
        kitsu_items = await AnimeClient.fetch_anime_category(category=genre.lower(), page=page)
        if kitsu_items:
            items = list(kitsu_items)

    if not items:
        # Normalize anime to series with animation genre if requested
        actual_type = "series" if media_type == "anime" else media_type
        actual_genre = "Animation" if media_type == "anime" and not genre else genre

        # Cinemeta endpoint construction
        base_catalog = "top"
        genre_param = f"/genre={actual_genre}" if actual_genre and actual_genre.lower() != "all" else ""
        
        # Calculate skip offset for pagination (48 items per page on Cinemeta)
        skip_param = f"/skip={(page - 1) * 48}" if page > 1 else ""
        
        endpoint = f"https://v3-cinemeta.strem.io/catalog/{actual_type}/{base_catalog}{genre_param}{skip_param}.json"

        try:
            data = await http_client.get_json(endpoint, timeout=4.5)
            raw_metas = (data.get("metas") or []) if isinstance(data, dict) else []

            for m in raw_metas:
                imdb_id = m.get("imdb_id") or m.get("id")
                if not imdb_id or not str(imdb_id).startswith("tt"):
                    continue

                trailers = m.get("trailers") or []
                trailer_key = trailers[0].get("source") if trailers else None
                trailer_url = f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else None

                # Detect if it's anime when under anime catalog or tagged Animation
                item_genres = m.get("genres") or m.get("genre") or []
                if isinstance(item_genres, str):
                    item_genres = [item_genres]

                inferred_type = media_type
                if media_type == "anime":
                    inferred_type = "anime"
                elif m.get("type"):
                    inferred_type = m.get("type")

                items.append(
                    DiscoverItem(
                        id=str(imdb_id),
                        title=m.get("name") or "Unknown Title",
                        type=inferred_type,
                        year=str(m.get("year")) if m.get("year") else None,
                        poster=_normalize_poster(m.get("poster")),
                        backdrop=m.get("background"),
                        rating=str(m.get("imdbRating")) if m.get("imdbRating") else None,
                        genres=item_genres,
                        description=m.get("description"),
                        trailer=trailer_url,
                    )
                )
        except Exception:
            pass

        # Fallback to local curated seeds if upstream catalog had an issue
        if not items and page == 1:
            items = _get_fallback_catalog(media_type, actual_genre)

    # Apply filters and sort order
    filtered_items = _filter_and_sort_items(
        items,
        min_rating=min_rating,
        year_from=year_from,
        year_to=year_to,
        sort=sort,
    )

    response = DiscoverCatalogResponse(
        items=filtered_items,
        total=len(filtered_items),
        type=media_type,
        catalog=catalog,
        genre=genre,
    )

    if filtered_items:
        await cache.set(cache_key, response, ttl=21600)  # 6 hour TTL

    return response


async def fetch_recommendations(
    media_type: str,
    imdb_id: str,
    limit: int = 12,
) -> List[DiscoverItem]:
    """
    Fetches curated content recommendations ("More Like This") for a movie, series, or anime.
    Uses genre-affinity matching against the catalog and filters out the query item itself.
    """
    if not imdb_id:
        return []

    cache_key = f"discover:recommendations:{media_type}:{imdb_id}:{limit}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    detail = await fetch_discover_detail(media_type=media_type, imdb_id=imdb_id)
    recs: List[DiscoverItem] = []
    first_genre = None
    if detail and detail.genres:
        first_genre = detail.genres[0]

    # First attempt: same media type and primary genre
    if first_genre:
        cat_resp = await fetch_catalog(media_type=media_type, catalog="top", genre=first_genre, page=1)
        for it in cat_resp.items:
            if it.id != imdb_id and not any(r.id == it.id for r in recs):
                recs.append(it)
                if len(recs) >= limit:
                    break

    # Second attempt: top catalog for this media type if still need more
    if len(recs) < limit:
        top_resp = await fetch_catalog(media_type=media_type, catalog="top", genre=None, page=1)
        for it in top_resp.items:
            if it.id != imdb_id and not any(r.id == it.id for r in recs):
                recs.append(it)
                if len(recs) >= limit:
                    break

    recs = recs[:limit]
    if recs:
        await cache.set(cache_key, recs, ttl=21600)  # 6 hour TTL

    return recs


async def fetch_discover_detail(
    media_type: str,
    imdb_id: str,
    bypass_cache: bool = False,
) -> Optional[DiscoverDetail]:
    """
    Fetches full title metadata, high-res posters, cast, crew, and complete
    season & episode trees for episodic television and anime.
    """
    if not imdb_id:
        return None

    if imdb_id.startswith("kitsu:"):
        return await AnimeClient.fetch_kitsu_detail(imdb_id)

    if not imdb_id.startswith("tt"):
        return None

    cache_key = f"discover:detail:{media_type}:{imdb_id}"
    if not bypass_cache:
        cached = await cache.get(cache_key)
        if cached:
            # Detect and invalidate corrupted entries (e.g. series cached as 0-episode movies)
            if media_type in ("series", "anime") and (getattr(cached, "type", "") == "movie" and not getattr(cached, "seasons", None)):
                pass
            else:
                return cached

    # Determine query priority
    # For episodic television and anime, query series first with generous timeout
    if media_type in ("series", "anime"):
        types_to_try = ["series", "movie"]
    elif media_type == "movie":
        types_to_try = ["movie", "series"]
    else:
        types_to_try = ["series", "movie"]

    detail: Optional[DiscoverDetail] = None
    for target_type in types_to_try:
        try:
            url = f"https://v3-cinemeta.strem.io/meta/{target_type}/{imdb_id}.json"
            # Retry once with generous timeout for large manifests (e.g. 300+ episode anime)
            res = None
            for attempt in range(2):
                try:
                    res = await http_client.get_json(url, timeout=8.0)
                    break
                except Exception:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    raise

            meta = (res.get("meta") or {}) if isinstance(res, dict) else {}
            if not meta:
                continue

            raw_videos = meta.get("videos") or []

            # If caller explicitly asked for series or anime, reject a movie fallback with 0 episodes
            if media_type in ("series", "anime") and target_type == "movie" and not raw_videos:
                continue

            trailers = meta.get("trailers") or []
            trailer_key = trailers[0].get("source") if trailers else None
            trailer_url = f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else None

            director = meta.get("director")
            if isinstance(director, list):
                director = ", ".join(director[:2]) if director else None

            cast_list = meta.get("cast") or []
            if isinstance(cast_list, list):
                cast_list = cast_list[:6]

            # Parse Season and Episode Tree
            seasons_map: Dict[int, List[EpisodeItem]] = {}
            total_eps = 0

            for v in raw_videos:
                s_num = v.get("season", 1)
                e_num = v.get("episode") or v.get("number") or 1
                ep_id = v.get("id") or f"{imdb_id}:{s_num}:{e_num}"
                
                ep_item = EpisodeItem(
                    id=str(ep_id),
                    season=int(s_num),
                    episode=int(e_num),
                    title=v.get("name") or v.get("title") or f"Episode {e_num}",
                    released=v.get("released") or v.get("firstAired"),
                    overview=v.get("overview") or v.get("description"),
                    thumbnail=v.get("thumbnail"),
                )
                if s_num not in seasons_map:
                    seasons_map[s_num] = []
                seasons_map[s_num].append(ep_item)
                total_eps += 1

            # Format sorted season list
            seasons_list: List[SeasonInfo] = []
            for s_num in sorted(seasons_map.keys()):
                # Sort episodes within season
                sorted_eps = sorted(seasons_map[s_num], key=lambda x: x.episode)
                seasons_list.append(SeasonInfo(season_number=s_num, episodes=sorted_eps))

            inferred_type = media_type
            if media_type == "anime":
                inferred_type = "anime"
            elif seasons_list or raw_videos:
                inferred_type = "series"
            elif meta.get("type"):
                inferred_type = meta.get("type")

            detail = DiscoverDetail(
                id=imdb_id,
                title=meta.get("name") or "Unknown Title",
                type=inferred_type,
                year=str(meta.get("year")) if meta.get("year") else None,
                poster=_normalize_poster(meta.get("poster")),
                backdrop=meta.get("background"),
                rating=str(meta.get("imdbRating")) if meta.get("imdbRating") else None,
                genres=meta.get("genres") or [],
                description=meta.get("description"),
                trailer=trailer_url,
                runtime=meta.get("runtime"),
                director=director,
                cast=cast_list,
                seasons=seasons_list,
                total_episodes=total_eps,
            )
            break
        except Exception:
            continue

    if detail:
        await cache.set(cache_key, detail, ttl=86400)  # 24 hours

    return detail


async def search_catalog(
    query: str,
    media_type: Optional[str] = None,
) -> List[DiscoverItem]:
    """
    Searches the Discover catalog by title or keyword.
    """
    if not query or len(query.strip()) < 2:
        return []

    clean_q = query.strip()
    cache_key = f"discover:search:{clean_q}:{media_type or 'all'}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    items: List[DiscoverItem] = []
    if media_type == "anime":
        types_to_search = ["series", "movie"]
    elif media_type in ("movie", "series"):
        types_to_search = [media_type]
    else:
        types_to_search = ["series", "movie"]

    seen_ids = set()
    for t in types_to_search:
        try:
            endpoint = f"https://v3-cinemeta.strem.io/catalog/{t}/top/search={clean_q}.json"
            res = await http_client.get_json(endpoint, timeout=4.5)
            metas = (res.get("metas") or []) if isinstance(res, dict) else []
            for m in metas:
                imdb_id = m.get("imdb_id") or m.get("id")
                if not imdb_id or not str(imdb_id).startswith("tt"):
                    continue
                if str(imdb_id) in seen_ids:
                    continue
                seen_ids.add(str(imdb_id))

                item_type = m.get("type") or t
                if media_type == "anime":
                    item_type = "anime"

                items.append(
                    DiscoverItem(
                        id=str(imdb_id),
                        title=m.get("name") or clean_q,
                        type=item_type,
                        year=str(m.get("year")) if m.get("year") else None,
                        poster=_normalize_poster(m.get("poster")),
                        backdrop=m.get("background"),
                        rating=str(m.get("imdbRating")) if m.get("imdbRating") else None,
                        genres=m.get("genres") or [],
                        description=m.get("description"),
                    )
                )
        except Exception:
            pass

    # Fallback to IMDb suggestions if Cinemeta search had no results
    if not items:
        try:
            slug = re.sub(r"[^a-zA-Z0-9\s]", "", clean_q).strip().lower().replace(" ", "_")
            if slug:
                endpoint = f"https://v3.sg.media-imdb.com/suggestion/x/{slug}.json"
                data = await http_client.get_json(endpoint, timeout=3.5)
                entries = (data.get("d") or []) if isinstance(data, dict) else []
                for it in entries:
                    entry_id = it.get("id") or ""
                    if entry_id.startswith("tt") and entry_id not in seen_ids:
                        seen_ids.add(entry_id)
                        img = it.get("i", {}).get("imageUrl") if isinstance(it.get("i"), dict) else None
                        inferred = "anime" if media_type == "anime" else ("movie" if it.get("q") == "feature" else "series")
                        items.append(
                            DiscoverItem(
                                id=entry_id,
                                title=it.get("l") or clean_q,
                                type=inferred,
                                year=str(it.get("y")) if it.get("y") else None,
                                poster=img,
                                description=f"Starring: {it.get('s', '')}",
                            )
                        )
        except Exception:
            pass

    if items:
        await cache.set(cache_key, items, ttl=3600)  # 1 hour

    return items


async def get_discover_suggestions(
    query: str,
    media_type: str = "all",
    limit: int = 8,
) -> List[DiscoverItem]:
    """
    Returns instant search suggestions matching title prefixes and keywords,
    complete with posters, release year, and format.
    """
    clean_q = (query or "").strip()
    if len(clean_q) < 2:
        return []

    cache_key = f"discover:suggestions:{clean_q.lower()}:{media_type}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    suggestions: List[DiscoverItem] = []
    seen_ids = set()

    # 1. If media_type is anime or all, query Kitsu search
    if media_type in ("anime", "all"):
        try:
            anime_results = await AnimeClient.search_anime(clean_q)
            for it in (anime_results or [])[:limit]:
                if it.id not in seen_ids:
                    seen_ids.add(it.id)
                    suggestions.append(it)
        except Exception:
            pass

    # 2. Query IMDb low-latency autocomplete suggestions API
    try:
        slug = re.sub(r"[^a-zA-Z0-9\s]", "", clean_q).strip().lower().replace(" ", "_")
        if slug:
            endpoint = f"https://v3.sg.media-imdb.com/suggestion/x/{slug}.json"
            data = await http_client.get_json(endpoint, timeout=2.5)
            entries = (data.get("d") or []) if isinstance(data, dict) else []
            for it in entries:
                entry_id = it.get("id") or ""
                if not entry_id.startswith("tt") or entry_id in seen_ids:
                    continue
                seen_ids.add(entry_id)

                q_type = (it.get("q") or "").lower()
                if "series" in q_type or "tv" in q_type:
                    inferred_type = "series"
                else:
                    inferred_type = "movie"

                if media_type != "all" and media_type != "anime" and inferred_type != media_type:
                    continue

                img_url = None
                img_obj = it.get("i")
                if isinstance(img_obj, dict) and img_obj.get("imageUrl"):
                    img_url = img_obj.get("imageUrl")
                elif entry_id.startswith("tt"):
                    img_url = f"https://images.metahub.space/poster/small/{entry_id}/img"

                title = it.get("l") or clean_q
                year = str(it.get("y")) if it.get("y") else None
                starring = it.get("s", "")

                suggestions.append(
                    DiscoverItem(
                        id=entry_id,
                        title=title,
                        type=inferred_type,
                        year=year,
                        poster=img_url,
                        description=f"Starring: {starring}" if starring else None,
                    )
                )
                if len(suggestions) >= limit:
                    break
    except Exception:
        pass

    # 3. Fallback to seeds if empty
    if not suggestions:
        seeds = _get_fallback_catalog("all", None)
        for s in seeds:
            if clean_q.lower() in s.title.lower() and s.id not in seen_ids:
                seen_ids.add(s.id)
                suggestions.append(s)

    suggestions = suggestions[:limit]
    if suggestions:
        await cache.set(cache_key, suggestions, ttl=3600)

    return suggestions


def _get_fallback_catalog(media_type: str, genre: Optional[str]) -> List[DiscoverItem]:
    """Curated high-rating seed catalog to guarantee an immediate rich UI even offline."""
    seeds = [
        DiscoverItem(
            id="tt15239678",
            title="Dune: Part Two",
            type="movie",
            year="2024",
            poster="https://images.metahub.space/poster/medium/tt15239678/img",
            backdrop="https://images.metahub.space/background/medium/tt15239678/img",
            rating="8.6",
            genres=["Action", "Adventure", "Sci-Fi"],
            description="Paul Atreides unites with Chani and the Fremen while seeking revenge against the conspirators who destroyed his family.",
        ),
        DiscoverItem(
            id="tt2788316",
            title="Shōgun",
            type="series",
            year="2024",
            poster="https://images.metahub.space/poster/medium/tt2788316/img",
            backdrop="https://images.metahub.space/background/medium/tt2788316/img",
            rating="8.7",
            genres=["Adventure", "Drama", "History"],
            description="When a mysterious European ship is found marooned in a nearby fishing village, Lord Yoshii Toranaga discovers secrets that could tip the scales of power.",
        ),
        DiscoverItem(
            id="tt12637874",
            title="Fallout",
            type="series",
            year="2024",
            poster="https://images.metahub.space/poster/medium/tt12637874/img",
            backdrop="https://images.metahub.space/background/medium/tt12637874/img",
            rating="8.4",
            genres=["Action", "Adventure", "Drama", "Sci-Fi"],
            description="In a future, post-apocalyptic Los Angeles brought about by nuclear decimation, citizens must live in underground bunkers to protect themselves from radiation, mutants and bandits.",
        ),
        DiscoverItem(
            id="tt9335498",
            title="Demon Slayer: Kimetsu no Yaiba",
            type="anime",
            year="2019",
            poster="https://images.metahub.space/poster/medium/tt9335498/img",
            backdrop="https://images.metahub.space/background/medium/tt9335498/img",
            rating="8.7",
            genres=["Animation", "Action", "Adventure", "Fantasy"],
            description="A family is attacked by demons and only two members survive - Tanjiro and his sister Nezuko, who is turning into a demon slowly.",
        ),
        DiscoverItem(
            id="tt15398776",
            title="Oppenheimer",
            type="movie",
            year="2023",
            poster="https://images.metahub.space/poster/medium/tt15398776/img",
            backdrop="https://images.metahub.space/background/medium/tt15398776/img",
            rating="8.9",
            genres=["Biography", "Drama", "History"],
            description="The story of American scientist J. Robert Oppenheimer and his role in the development of the atomic bomb.",
        ),
        DiscoverItem(
            id="tt0944947",
            title="Game of Thrones",
            type="series",
            year="2011",
            poster="https://images.metahub.space/poster/medium/tt0944947/img",
            backdrop="https://images.metahub.space/background/medium/tt0944947/img",
            rating="9.2",
            genres=["Action", "Adventure", "Drama", "Fantasy"],
            description="Nine noble families fight for control over the lands of Westeros, while an ancient enemy returns after being dormant for millennia.",
        ),
        DiscoverItem(
            id="kitsu:11",
            title="Naruto",
            type="anime",
            year="2002",
            poster="https://media.kitsu.app/anime/poster_images/11/medium.jpg",
            backdrop="https://media.kitsu.app/anime/cover_images/11/large.jpg",
            rating="7.9",
            genres=["Animation", "Action", "Adventure", "Fantasy"],
            description="Moments prior to Naruto Uzumaki's birth, a huge demon known as the Kyuubi attacked Konohagakure.",
        ),
        DiscoverItem(
            id="kitsu:7442",
            title="Attack on Titan",
            type="anime",
            year="2013",
            poster="https://media.kitsu.app/anime/poster_images/7442/medium.jpg",
            backdrop="https://media.kitsu.app/anime/cover_images/7442/large.jpg",
            rating="8.5",
            genres=["Animation", "Action", "Drama", "Fantasy"],
            description="Centuries ago, mankind was slaughtered to near extinction by monstrous humanoid creatures called Titans.",
        ),
    ]
    if media_type == "movie":
        return [s for s in seeds if s.type == "movie"]
    if media_type == "series":
        return [s for s in seeds if s.type == "series"]
    if media_type == "anime":
        return [s for s in seeds if s.type == "anime"]
    return seeds
