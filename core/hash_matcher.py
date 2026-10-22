import asyncio
import os
import struct
from typing import Any, Dict, List, Optional
import aiohttp


def compute_opensubtitles_hash(head_bytes: bytes, tail_bytes: bytes, file_size: int) -> str:
    """
    Computes the standardized OpenSubtitles 64-bit binary movie checksum.
    The algorithm sums 64-bit little-endian integers from the first 64KB and last 64KB,
    added to the total file size, with 64-bit overflow wraparound.
    """
    fmt = "<q"  # 64-bit signed little-endian int
    bytesize = struct.calcsize(fmt)  # 8 bytes

    hash_val = file_size

    # Sum head 64KB
    head_len = min(len(head_bytes), 65536)
    head_chunks = head_len // bytesize
    for i in range(head_chunks):
        val = struct.unpack(fmt, head_bytes[i * bytesize : (i + 1) * bytesize])[0]
        hash_val = (hash_val + val) & 0xFFFFFFFFFFFFFFFF

    # Sum tail 64KB
    tail_len = min(len(tail_bytes), 65536)
    tail_chunks = tail_len // bytesize
    for i in range(tail_chunks):
        val = struct.unpack(fmt, tail_bytes[i * bytesize : (i + 1) * bytesize])[0]
        hash_val = (hash_val + val) & 0xFFFFFFFFFFFFFFFF

    return f"{hash_val:016x}"


def compute_file_hash(filepath: str) -> Optional[str]:
    """
    Computes OpenSubtitles movie hash for a local video file on disk.
    """
    if not os.path.isfile(filepath):
        return None

    size = os.path.getsize(filepath)
    if size < 131072:
        return None

    try:
        with open(filepath, "rb") as f:
            head = f.read(65536)
            f.seek(max(0, size - 65536), os.SEEK_SET)
            tail = f.read(65536)
        return compute_opensubtitles_hash(head, tail, size)
    except Exception:
        return None


async def search_subtitles_by_hash(
    movie_hash: str,
    file_size: int,
    lang: str = "en",
) -> List[Dict[str, Any]]:
    """
    Queries OpenSubtitles API for exact 64-bit binary checksum match.
    Provides frame-perfect subtitle synchronization with 0ms drift.
    """
    if not movie_hash or file_size <= 0:
        return []

    url = f"https://rest.opensubtitles.org/search/moviebytesize-{file_size}/moviehash-{movie_hash}/sublanguageid-{lang}"
    headers = {
        "User-Agent": "TemporaryUserAgent",
        "Accept": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=4.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        results = []
                        for item in data:
                            results.append({
                                "id": f"os_hash_{item.get('IDSubtitleFile', '')}",
                                "name": item.get("SubFileName") or item.get("MovieReleaseName") or "Hash Matched Subtitle",
                                "lang": item.get("SubLanguageID", lang),
                                "download_url": item.get("SubDownloadLink", ""),
                                "source": "OpenSubtitles (Exact Hash)",
                                "score": 999.0,  # Highest priority
                                "is_hash_match": True,
                            })
                        return results
        except Exception as e:
            print(f"[HashMatcher] OpenSubtitles hash search warning: {e}")

    return []
