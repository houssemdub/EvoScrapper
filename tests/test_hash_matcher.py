import os
import sys
import tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from providers.subtitles.hash_matcher import compute_osdb_hash, compute_shooter_hash


def test_hash_calculation():
    # Create a temporary binary file > 128KB
    with tempfile.NamedTemporaryFile(delete=False) as f:
        temp_path = f.name
        # Write 256KB of dummy data
        f.write(b"\x01\x02\x03\x04" * (64 * 1024))

    try:
        osdb_hash, size = compute_osdb_hash(temp_path)
        assert len(osdb_hash) == 16
        assert size == 256 * 1024
        print(f"[+] Computed OpenSubtitles hash: {osdb_hash} (size: {size})")

        shooter_hash = compute_shooter_hash(temp_path)
        assert len(shooter_hash.split(";")) == 4
        print(f"[+] Computed Shooter MD5 hash: {shooter_hash}")

        from core.hash_matcher import compute_file_hash, compute_opensubtitles_hash
        c_hash = compute_file_hash(temp_path)
        assert c_hash == osdb_hash
        print(f"[+] Core OpenSubtitles hash match verified: {c_hash}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    test_hash_calculation()
    print("[+] Hash matcher tests passed!")
