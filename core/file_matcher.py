import os
import re
from typing import Any, Dict, List, Optional, Union

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".ts", ".m4v", ".wmv"}


def is_bonus_or_non_episode(filepath: str, requested_season: Optional[int] = None) -> bool:
    """Returns True if the file is an extra, sample, OP/ED theme, or unrelated media."""
    norm = (filepath or "").replace("\\", "/").lower()
    basename = os.path.basename(norm)

    if re.search(r"\b(sample|trailer|preview|extras?|bonus|featurette|promo)\b", basename):
        return True
    if re.search(r"[\\/](?:sample|trailer|preview|extras?|bonus|featurette|promo)[\\/]", norm):
        return True

    # Reject anime themes / music videos / OP / ED
    if re.search(r"\b(op\s*\d+|ed\s*\d+|ncop\s*\d*|nced\s*\d*|opening\s*\d*|ending\s*\d*|creditless)\b", basename):
        return True
    if re.search(r"[\\/](?:op\s*and\s*ed|openings?|endings?|ost|soundtrack|music)[\\/]", norm):
        return True

    # Movies (unless season 0 or requested as movie)
    is_movie = bool(re.search(r"[\\/](?:movies?|films?)[\\/]", norm) or re.search(r"\b(?:movie|film)\s*\d+\b", basename))
    if is_movie and requested_season not in (0, None):
        return True

    # OVAs / Specials (unless requested as season 0)
    is_ova = bool(
        re.search(r"[\\/](?:specials?|ova|oad)[\\/]", norm)
        or re.search(r"[\[\(](?:special|sp|ova|oad)[\]\)]", basename)
        or re.search(r"\b(?:ova|oad|sp)\s*0*\d+\b", basename)
        or re.search(r"\bspecial\s+0*\d+\b", basename)
    )
    if is_ova and requested_season != 0:
        return True

    return False


def extract_season_from_path(filepath: str) -> Optional[int]:
    """Extracts the season number from folder hierarchy or filename."""
    norm = (filepath or "").replace("\\", "/")
    parts = norm.split("/")

    # Check directory components from parent backwards
    for p in reversed(parts[:-1]):
        m = re.search(r"\b(?:season|series|staffel|s)\s*0*(\d+)\b", p, re.IGNORECASE)
        if m:
            return int(m.group(1))
        if re.search(r"\b(?:specials?|ova|oad)\b", p, re.IGNORECASE):
            return 0

    # Check filename
    filename = parts[-1] if parts else ""
    fm = re.search(r"\b[sS]0*(\d+)[eE]\d+\b|\b0*(\d+)x\d+\b", filename)
    if fm:
        return int(fm.group(1) or fm.group(2))
    sm = re.search(r"\b(?:season|s)\s*0*(\d+)\b", filename, re.IGNORECASE)
    if sm:
        return int(sm.group(1))
    if re.search(r"\b(?:special|sp|ova|oad)\s*0*\d*\b", filename, re.IGNORECASE):
        return 0

    return None


def clean_name_for_matching(filename: str) -> str:
    """Removes video resolution, codecs, audio, and years to avoid false number matches."""
    if not filename:
        return ""
    cleaned = filename
    cleaned = re.sub(r"\b(?:480p|720p|1080p|1440p|2160p|4k|uhd|fhd|hd)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:x264|x265|h264|h265|hevc|av1|xvid|divx|10bit|8bit)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:aac|ac3|dts|eac3|flac|mp3|opus|truehd|atmos)\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]", " ", cleaned)
    cleaned = re.sub(r"\b(?:19|20)\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\b(?:repack|proper|internal|bluray|bdrip|webrip|web-dl|webdl|hdtv)\b", " ", cleaned, flags=re.I)
    return cleaned


def score_file_for_episode(
    filepath: str,
    target_season: Optional[int],
    target_ep: int,
    idx_in_season: Optional[int] = None,
) -> float:
    """Scores how well a file matches the target season and episode."""
    norm_path = filepath.replace("\\", "/")
    filename = os.path.basename(norm_path)
    base_name, _ = os.path.splitext(filename)
    clean = clean_name_for_matching(base_name)

    file_season = extract_season_from_path(norm_path)

    # Disqualify if file belongs to a differing known season
    if target_season is not None and file_season is not None and target_season != file_season:
        return -10000.0

    score = 0.0

    # Direct season match bonus
    if target_season is not None and file_season == target_season:
        score += 300.0

    # 1. Exact SxxExx or 1x01 pattern
    if target_season is not None:
        s_pattern = rf"\b(?:s0*{target_season}[ ._-]*e0*{target_ep}|0*{target_season}x0*{target_ep})\b"
        if re.search(s_pattern, filename, re.IGNORECASE) or re.search(s_pattern, norm_path, re.IGNORECASE):
            score += 1000.0

    # 2. Explicit Ep / Episode prefix
    ep_prefix = rf"\b(?:ep|episode|e)[ ._-]*0*{target_ep}\b"
    if re.search(ep_prefix, filename, re.IGNORECASE):
        score += 500.0

    # 3. Standalone episode number in cleaned filename
    ep_p2 = f"{target_ep:02d}"
    ep_p3 = f"{target_ep:03d}"
    standalone_re = rf"(?:^|[\s\-_.\(\[])(?:0*{target_ep}|{ep_p2}|{ep_p3})(?=[\s\-_.\)\]]|$)"
    if re.search(standalone_re, clean, re.IGNORECASE):
        score += 400.0

    # 4. Sequential index in season folder
    if idx_in_season is not None and idx_in_season == (target_ep - 1):
        score += 350.0

    return score


def select_target_file(
    files: List[Union[Dict[str, Any], str]],
    season: Optional[int] = None,
    episode: Optional[int] = None,
    requested_idx: Optional[int] = None,
) -> Optional[int]:
    """
    Selects the best matching file index inside a torrent for the requested episode/season.
    Returns the integer index in the input files list, or None if files is empty.
    """
    if not files:
        return None

    file_entries = []
    for i, f in enumerate(files):
        if isinstance(f, dict):
            p = f.get("path") or f.get("name") or ""
            sz = f.get("length") or f.get("bytes") or 0
        else:
            p = str(f)
            sz = 0
        ext = os.path.splitext(p)[1].lower()
        file_entries.append({"idx": i, "path": p, "ext": ext, "size": sz})

    video_files = [f for f in file_entries if f["ext"] in VIDEO_EXTENSIONS]
    valid_files = [f for f in video_files if not is_bonus_or_non_episode(f["path"], season)]
    pool = valid_files if valid_files else (video_files if video_files else file_entries)

    # 1. Episode / Season matching
    if episode is not None:
        # Group pool by season
        season_map: Dict[int, List[Dict[str, Any]]] = {}
        for f in pool:
            sn = extract_season_from_path(f["path"])
            if sn is not None:
                season_map.setdefault(sn, []).append(f)

        for s_key in season_map:
            season_map[s_key].sort(key=lambda x: x["path"])

        s_files = season_map.get(season) if season is not None else None

        best_idx = None
        best_score = -1.0

        for f in pool:
            idx_in_s = None
            if s_files:
                try:
                    idx_in_s = s_files.index(f)
                except ValueError:
                    pass
            sc = score_file_for_episode(f["path"], season, episode, idx_in_season=idx_in_s)
            if sc > best_score:
                best_score = sc
                best_idx = f["idx"]

        if best_idx is not None and best_score > 0:
            return best_idx

        # Fallback to sequential file in target season
        if s_files and 1 <= episode <= len(s_files):
            return s_files[episode - 1]["idx"]

    # 2. Explicit valid index requested (only if valid video file)
    if requested_idx is not None and 0 <= requested_idx < len(files):
        cand = file_entries[requested_idx]
        if cand["ext"] in VIDEO_EXTENSIONS:
            return requested_idx

    # 3. Movie default: largest video file
    pool.sort(key=lambda x: x["size"], reverse=True)
    return pool[0]["idx"] if pool else 0
