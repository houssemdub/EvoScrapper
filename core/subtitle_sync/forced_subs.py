"""
core/subtitle_sync/forced_subs.py — Detection & filtering of forced subtitles, signs, and non-dialogue cues.
Prevents onscreen text, karaoke, and credits from corrupting speech/sync alignment.
"""
import re
from typing import List, Tuple

# Case-insensitive patterns
IGNORECASE_PATTERNS = [
    r"^[\[\(].*?[\]\)]$",                     # [Sign], (Text on screen), (Music playing)
    r"^(sign|text|title|credits?):",           # "Sign: Hospital", "Credits: SubTeam"
    r"^\d{1,2}:\d{2}(:\d{2})?$",               # Timecodes on screen
    r"^♪.*♪$",                                 # Musical notes
    r"^#.*#$",                                 # Lyrics
]

# Case-sensitive patterns (e.g. ALL CAPS signs / title cards)
CASE_SENSITIVE_PATTERNS = [
    r"^[A-Z0-9\s:,\.\-]{4,}$",                 # ALL CAPS short lines / headers (e.g. "CHAPTER ONE")
]

_COMPILED_IGNORECASE = [re.compile(p, re.IGNORECASE) for p in IGNORECASE_PATTERNS]
_COMPILED_CASE_SENSITIVE = [re.compile(p) for p in CASE_SENSITIVE_PATTERNS]


def detect_forced_subtitles(cues: List[Tuple[float, float, str]]) -> List[bool]:
    """
    Returns boolean mask: True = forced/sign/non-dialogue cue to exclude from sync.
    Cues are tuples of (start_sec, end_sec, text).
    """
    forced: List[bool] = []
    for start, end, text in cues:
        clean = text.strip()
        if not clean:
            forced.append(True)
            continue

        # Check regex matches
        is_forced = any(pat.search(clean) for pat in _COMPILED_IGNORECASE)
        if not is_forced and any(c.isupper() for c in clean):
            # Check ALL CAPS if there are letters and NO lowercase letters
            has_letters = any(c.isalpha() for c in clean)
            has_no_lower = not any(c.islower() for c in clean)
            if has_letters and has_no_lower:
                is_forced = any(pat.match(clean) for pat in _COMPILED_CASE_SENSITIVE)

        # Check heuristics: extremely short duration with <= 2 words often indicates a brief flash sign
        dur = end - start
        words = clean.split()
        if not is_forced and dur <= 1.0 and len(words) <= 2 and not any(c in clean for c in "?!.,"):
            is_forced = True

        forced.append(is_forced)

    return forced


def filter_for_sync(
    cues: List[Tuple[float, float, str]],
    forced_mask: List[bool],
) -> List[Tuple[float, float, str]]:
    """
    Filters out forced/sign cues so only genuine spoken dialogue remains for sync.
    """
    return [cue for cue, is_forced in zip(cues, forced_mask) if not is_forced]
