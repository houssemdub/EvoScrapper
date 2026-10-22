import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.aggregator import deduplicate_torrents, filter_torrents
from models.torrent import QualityMetadata, TorrentItem


def test_deduplication():
    item1 = TorrentItem(
        id="hash1",
        title="Avatar.2009.1080p.BluRay.x264",
        info_hash="aabbccddeeff11223344aabbccddeeff11223344",
        magnet_uri="magnet:?xt=urn:btih:aabbccddeeff11223344aabbccddeeff11223344",
        size_bytes=1000,
        size_formatted="1 GB",
        seeders=50,
        leechers=5,
        category="movies",
        provider="yts",
        sources=["yts"],
        metadata=QualityMetadata(resolution="1080p", source="BluRay"),
    )

    item2 = TorrentItem(
        id="hash1_dup",
        title="Avatar (2009) [1080p] [BluRay]",
        info_hash="aabbccddeeff11223344aabbccddeeff11223344",
        magnet_uri="magnet:?xt=urn:btih:aabbccddeeff11223344aabbccddeeff11223344",
        size_bytes=1000,
        size_formatted="1 GB",
        seeders=120,  # Higher seed count
        leechers=10,
        category="movies",
        provider="thepiratebay",
        sources=["thepiratebay"],
        metadata=QualityMetadata(resolution="1080p"),
    )

    item3 = TorrentItem(
        id="hash2",
        title="Avatar.Way.of.Water.2022.2160p",
        info_hash="1122334455667788990011223344556677889900",
        magnet_uri="magnet:?xt=urn:btih:1122334455667788990011223344556677889900",
        size_bytes=2000,
        size_formatted="2 GB",
        seeders=20,
        leechers=1,
        category="movies",
        provider="yts",
        sources=["yts"],
        metadata=QualityMetadata(resolution="2160p"),
    )

    deduped = deduplicate_torrents([item1, item2, item3])
    assert len(deduped) == 2
    # The duplicate item should be merged with highest seeders (120) and both sources
    matched = next(x for x in deduped if x.info_hash == "aabbccddeeff11223344aabbccddeeff11223344")
    assert matched.seeders == 120
    assert set(matched.sources) == {"yts", "thepiratebay"}

    # Test filtering by resolution
    only_4k = filter_torrents(deduped, resolution="2160p")
    assert len(only_4k) == 1
    assert only_4k[0].metadata.resolution == "2160p"


if __name__ == "__main__":
    test_deduplication()
    print("[+] Aggregator deduplication & filtering tests passed!")
