import re
from typing import Dict, List, Optional
from models.torrent import TorrentItem


def deduplicate_torrents(items: List[TorrentItem]) -> List[TorrentItem]:
    """
    De-duplicates torrent results by SHA-1 infoHash (or title fallback).
    Merges seeder counts, sources list, and retains richest metadata.
    """
    seen_hashes: Dict[str, TorrentItem] = {}
    seen_titles: Dict[str, TorrentItem] = {}
    uniques: List[TorrentItem] = []

    for item in items:
        h = (item.info_hash or "").lower().strip()
        t = item.title.lower().strip()

        if h:
            if h in seen_hashes:
                existing = seen_hashes[h]
                # Merge sources
                for s in item.sources:
                    if s not in existing.sources:
                        existing.sources.append(s)
                # Keep highest seeders
                if item.seeders > existing.seeders:
                    existing.seeders = item.seeders
                if item.leechers > existing.leechers:
                    existing.leechers = item.leechers
                # Enrich metadata if missing
                if not existing.metadata.resolution and item.metadata.resolution:
                    existing.metadata.resolution = item.metadata.resolution
                if not existing.metadata.source and item.metadata.source:
                    existing.metadata.source = item.metadata.source
            else:
                seen_hashes[h] = item
                uniques.append(item)
        else:
            if t in seen_titles:
                existing = seen_titles[t]
                for s in item.sources:
                    if s not in existing.sources:
                        existing.sources.append(s)
                if item.seeders > existing.seeders:
                    existing.seeders = item.seeders
            else:
                seen_titles[t] = item
                uniques.append(item)

    # Sort final results by seeders descending by default
    uniques.sort(key=lambda x: x.seeders, reverse=True)
    return uniques


def score_relevance(title: str, query: str) -> float:
    """
    Calculates relevance of a release title to the user's query.
    Returns 0.0 if there is zero overlap.
    """
    if not query:
        return 1.0

    clean_title = re.sub(r"[^a-zA-Z0-9\s]", " ", title).lower()
    clean_query = re.sub(r"[^a-zA-Z0-9\s]", " ", query).lower().strip()

    if not clean_query:
        return 1.0

    # Exact phrase match gives top score
    if clean_query in clean_title:
        return 100.0

    words = [w for w in clean_query.split() if len(w) > 1]
    if not words:
        words = clean_query.split()
    if not words:
        return 1.0

    matches = sum(1 for w in words if w in clean_title)
    if matches == 0:
        return 0.0

    fraction = matches / len(words)
    return fraction * 80.0


def rank_torrents_by_relevance(items: List[TorrentItem], query: str) -> List[TorrentItem]:
    """
    Filters out completely unrelated torrents and sorts by relevance score + seeders bonus.
    """
    if not query or len(query.strip()) < 2:
        return items

    scored = []
    unrelated = []
    for item in items:
        sc = score_relevance(item.title, query)
        if sc > 0:
            # Composite rank: relevance weight + logarithmic seeders weight
            rank = (sc * 1000) + min(item.seeders, 500)
            scored.append((rank, item))
        else:
            unrelated.append(item)

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [x[1] for x in scored]

    # If we found relevant items, return them. Otherwise fall back to all items.
    return ranked if ranked else items


def filter_torrents(
    items: List[TorrentItem],
    resolution: Optional[str] = None,
    min_seeders: int = 0,
    category: Optional[str] = None,
    source: Optional[str] = None,
    codec: Optional[str] = None,
    query: Optional[str] = None,
) -> List[TorrentItem]:
    """Applies client-specified filters across aggregated torrent items."""
    filtered = items

    # Apply relevance ranking first if query is provided
    if query:
        filtered = rank_torrents_by_relevance(filtered, query)

    if min_seeders > 0:
        filtered = [x for x in filtered if x.seeders >= min_seeders]

    if resolution and isinstance(resolution, str):
        res_target = resolution.lower().strip()
        filtered = [
            x for x in filtered
            if x.metadata.resolution and x.metadata.resolution.lower() == res_target
        ]

    if source and isinstance(source, str):
        src_target = source.lower().strip()
        filtered = [
            x for x in filtered
            if x.metadata.source and x.metadata.source.lower() == src_target
        ]

    if codec and isinstance(codec, str):
        codec_target = codec.lower().strip()
        filtered = [
            x for x in filtered
            if x.metadata.codec and codec_target in x.metadata.codec.lower()
        ]

    if category and isinstance(category, str) and category.lower() != "all":
        cat_target = category.lower().strip()
        filtered = [
            x for x in filtered
            if cat_target in x.category.lower() or x.category.lower() == "general"
        ]

    return filtered
