import hashlib
import os
import struct
from typing import Tuple


def compute_osdb_hash(filepath: str) -> Tuple[str, int]:
    """
    Computes the standard OpenSubtitles / MPC-HC / Stremio 64-bit checksum
    and file size in bytes for binary video synchronization.
    Formula: uint64(size) + sum_uint64(first 64KB) + sum_uint64(last 64KB).
    """
    longlongformat = "<q"  # little-endian signed 64-bit integer
    bytesize = struct.calcsize(longlongformat)
    filesize = os.path.getsize(filepath)
    hash_val = filesize

    if filesize < 65536 * 2:
        raise ValueError("File must be at least 128KB for OpenSubtitles hash")

    with open(filepath, "rb") as f:
        # First 64KB
        for _ in range(65536 // bytesize):
            buffer = f.read(bytesize)
            (l_value,) = struct.unpack(longlongformat, buffer)
            hash_val = (hash_val + l_value) & 0xFFFFFFFFFFFFFFFF

        # Seek to last 64KB
        f.seek(max(0, filesize - 65536), 0)
        for _ in range(65536 // bytesize):
            buffer = f.read(bytesize)
            (l_value,) = struct.unpack(longlongformat, buffer)
            hash_val = (hash_val + l_value) & 0xFFFFFFFFFFFFFFFF

    return "%016x" % hash_val, filesize


def compute_shooter_hash(filepath: str) -> str:
    """
    Computes the Shooter.cn / SPlayer 4-offset MD5 multi-hash.
    """
    filesize = os.path.getsize(filepath)
    if filesize < 8192:
        raise ValueError("File too small for Shooter hash calculation")

    offsets = [
        4096,
        int(filesize / 3) * 2,
        int(filesize / 3),
        filesize - 8192,
    ]

    md5_list = []
    with open(filepath, "rb") as f:
        for offset in offsets:
            f.seek(offset, 0)
            data = f.read(4096)
            md5_list.append(hashlib.md5(data).hexdigest())

    return ";".join(md5_list)
