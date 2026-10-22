import os
import re
from typing import Optional
from models.torrent import QualityMetadata


def parse_release_title(title: str) -> QualityMetadata:
    """
    Parses a torrent or release title to extract structured metadata:
    resolution, source, video codec, audio profile, HDR/DV, and release group.
    Preserves versioned tokens like H.264, H.265, 5.1, 7.1, and DDP5.1 intact.
    """
    if not title:
        return QualityMetadata()

    # Strip only standard video container extensions at the end of title
    base_title = re.sub(r"\.(mkv|mp4|avi|webm|ts|mov|m4v)$", "", title.strip(), flags=re.IGNORECASE)

    # Normalized version replaces separators with spaces
    normalized = re.sub(r"[\._\s]+", " ", base_title)

    # 1. Resolution
    resolution: Optional[str] = None
    if re.search(r"\b(2160p|4k|uhd)\b", normalized, re.IGNORECASE):
        resolution = "2160p"
    elif re.search(r"\b(1080p|fhd)\b", normalized, re.IGNORECASE):
        resolution = "1080p"
    elif re.search(r"\b(720p|hd)\b", normalized, re.IGNORECASE):
        resolution = "720p"
    elif re.search(r"\b(480p|sd|576p)\b", normalized, re.IGNORECASE):
        resolution = "480p"

    # 2. Source / Quality
    source: Optional[str] = None
    if re.search(r"\b(remux)\b", normalized, re.IGNORECASE):
        source = "REMUX"
    elif re.search(r"\b(bluray|bdrip|brrip)\b", normalized, re.IGNORECASE):
        source = "BluRay"
    elif re.search(r"\b(web-?dl)\b", normalized, re.IGNORECASE):
        source = "WEB-DL"
    elif re.search(r"\b(webrip|web)\b", normalized, re.IGNORECASE):
        source = "WEBRip"
    elif re.search(r"\b(hdtv|pdtv|dsr)\b", normalized, re.IGNORECASE):
        source = "HDTV"
    elif re.search(r"\b(cam|camrip|ts|telesync|hdts)\b", normalized, re.IGNORECASE):
        source = "CAM"

    # 3. Codec - check both base_title (for literal dot like h.264) and normalized
    codec: Optional[str] = None
    if re.search(r"\b(hevc|x265|h\.?265|h\s*265)\b", base_title, re.IGNORECASE):
        codec = "HEVC"
    elif re.search(r"\b(av1)\b", normalized, re.IGNORECASE):
        codec = "AV1"
    elif re.search(r"\b(x264|h\.?264|h\s*264|avc)\b", base_title, re.IGNORECASE):
        codec = "x264"
    elif re.search(r"\b(vp9)\b", normalized, re.IGNORECASE):
        codec = "VP9"
    elif re.search(r"\b(xvid|divx)\b", normalized, re.IGNORECASE):
        codec = "XviD"

    # 4. Audio Matrix (PTT Specification) - check base_title to preserve dot in 5.1 / 7.1
    audio: Optional[str] = None
    if re.search(r"\b(atmos|dolby\s*atmos)\b", normalized, re.IGNORECASE):
        audio = "Atmos"
    elif re.search(r"\b(truehd|true-hd)\b", normalized, re.IGNORECASE):
        audio = "TrueHD"
    elif re.search(r"\b(dts-hd\s*ma|dts-hd|dts-ma)\b", normalized, re.IGNORECASE):
        audio = "DTS-HD MA"
    elif re.search(r"\b(dts:x|dtsx)\b", normalized, re.IGNORECASE):
        audio = "DTS:X"
    elif re.search(r"\b(ddp\s*7\.?1|dd\+\s*7\.?1|eac3\s*7\.?1)\b", base_title, re.IGNORECASE):
        audio = "DDP7.1"
    elif re.search(r"\b(ddp\s*5\.?1|dd\+\s*5\.?1|eac3\s*5\.?1|eac-3|ddp)\b", base_title, re.IGNORECASE):
        audio = "DDP5.1"
    elif re.search(r"\b(dts|dts\s*5\.?1)\b", base_title, re.IGNORECASE):
        audio = "DTS"
    elif re.search(r"\b(ac3\s*5\.?1|dd\s*5\.?1|5\.1)\b", base_title, re.IGNORECASE):
        audio = "5.1"
    elif re.search(r"\b(7\.1)\b", base_title, re.IGNORECASE):
        audio = "7.1"
    elif re.search(r"\b(flac)\b", normalized, re.IGNORECASE):
        audio = "FLAC"
    elif re.search(r"\b(opus)\b", normalized, re.IGNORECASE):
        audio = "Opus"
    elif re.search(r"\b(aac|mp3|2\.0|stereo)\b", base_title, re.IGNORECASE):
        audio = "Stereo/AAC"

    # 5. HDR / Visual Matrix (PTT Specification)
    hdr = []
    if re.search(r"\b(dv|dovi|dolby\s*vision)\b", normalized, re.IGNORECASE):
        hdr.append("DV")
    if re.search(r"\b(hdr10\+|hdr10plus)\b", normalized, re.IGNORECASE):
        hdr.append("HDR10+")
    elif re.search(r"\b(hdr10|hdr)\b", normalized, re.IGNORECASE):
        hdr.append("HDR")
    if re.search(r"\b(hlg)\b", normalized, re.IGNORECASE):
        hdr.append("HLG")

    # 6. Release Group (bracket [Group] or trailing -Group)
    group: Optional[str] = None
    bracket_match = re.search(r"^\[([a-zA-Z0-9_-]+)\]", title)
    if bracket_match:
        group = bracket_match.group(1)
    else:
        dash_match = re.search(r"-([a-zA-Z0-9]+)(?:\[.*?\])?$", base_title.strip())
        if dash_match and len(dash_match.group(1)) <= 15:
            group = dash_match.group(1)

    return QualityMetadata(
        resolution=resolution,
        source=source,
        codec=codec,
        audio=audio,
        hdr=hdr,
        group=group,
    )


def format_bytes(size: int) -> str:
    """Formats bytes into a readable string like '1.45 GB'."""
    if not size or size <= 0:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def parse_size_str(size_str: str) -> int:
    """Parses size strings like '1.45 GB', '850 MB' into integer bytes."""
    if not size_str:
        return 0
    size_str = size_str.strip().replace(",", "")
    match = re.match(r"^([\d.]+)\s*([a-zA-Z]+)", size_str)
    if not match:
        return 0
    val = float(match.group(1))
    unit = match.group(2).upper()
    multiplier = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024 ** 2,
        "MIB": 1024 ** 2,
        "GB": 1024 ** 3,
        "GIB": 1024 ** 3,
        "TB": 1024 ** 4,
        "TIB": 1024 ** 4,
    }
    return int(val * multiplier.get(unit, 1))
