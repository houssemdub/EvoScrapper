import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.title_parser import format_bytes, parse_release_title, parse_size_str


def test_title_parser_complete():
    raw = "Dune.Part.Two.2024.2160p.UHD.Remux.HEVC.DV.Atmos.TrueHD.7.1-FraMeSToR"
    meta = parse_release_title(raw)
    assert meta.resolution == "2160p"
    assert meta.source == "REMUX"
    assert meta.codec == "HEVC"
    assert meta.audio == "Atmos"
    assert "DV" in meta.hdr
    assert meta.group == "FraMeSToR"


def test_title_parser_anime():
    raw = "[Erai-raws] Sousou no Frieren - 01 [1080p CR WEBRip HEVC AAC]"
    meta = parse_release_title(raw)
    assert meta.resolution == "1080p"
    assert meta.source == "WEBRip"
    assert meta.codec == "HEVC"
    assert meta.group == "Erai-raws"


def test_size_parsing():
    assert parse_size_str("1.5 GB") == int(1.5 * 1024 ** 3)
    assert parse_size_str("500 MB") == 500 * 1024 ** 2
    assert parse_size_str("2.5 TB") == int(2.5 * 1024 ** 4)
    assert format_bytes(1024 ** 3) == "1.00 GB"
    assert format_bytes(500 * 1024) == "500.00 KB"


if __name__ == "__main__":
    test_title_parser_complete()
    test_title_parser_anime()
    test_size_parsing()
    print("[+] All title parser tests passed!")
