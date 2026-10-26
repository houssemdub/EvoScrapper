import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js binary not found on system")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tests" / "node" / "seed_reader_measure.mjs"
METRICS_PREFIX = "EVO_METRICS "


def test_local_seed_reader_metrics_are_deterministic(tmp_path):
    """Seeds a local file and measures metadata, first verified byte, and lookahead.

    Only loopback TCP is used: DHT, trackers, LSD, UPnP, and uTP are disabled
    on both clients, and the reader is connected directly to the seeder port.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    env = {
        **os.environ,
        "EVO_STREAM_CACHE_DIR": str(cache_dir),
        "EVO_MEASURE_TIMEOUT_MS": "60000",
        "EVO_MEASURE_BYTES": str(4 * 1024 * 1024),
    }

    result = subprocess.run(
        [NODE, str(SCRIPT)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"measurement process failed with exit code {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    metrics_line = next(
        (line for line in result.stdout.splitlines() if line.startswith(METRICS_PREFIX)),
        None,
    )
    assert metrics_line is not None, f"missing metrics line in stdout:\n{result.stdout}"
    metrics = json.loads(metrics_line[len(METRICS_PREFIX):])

    for key in (
        "metadata_ms",
        "engine_metadata_ms",
        "first_byte_ms",
        "first_byte_after_metadata_ms",
        "seconds_ahead",
        "contiguous_pieces",
        "scan_pieces",
        "piece_length",
        "file_bytes",
        "health_state",
        "readers",
        "bytes_served",
        "status_bytes_served",
    ):
        assert key in metrics, f"missing metric {key}: {metrics}"

    assert metrics["file_bytes"] == 4 * 1024 * 1024
    assert metrics["metadata_ms"] >= 0
    assert metrics["engine_metadata_ms"] >= 0
    assert metrics["engine_metadata_ms"] <= metrics["metadata_ms"] + 50
    assert metrics["first_byte_ms"] >= 0
    assert metrics["first_byte_ms"] < 30000, metrics
    assert metrics["first_byte_after_metadata_ms"] >= 0
    assert metrics["metadata_ms"] < 30000, metrics

    assert metrics["contiguous_pieces"] >= 1
    assert metrics["seconds_ahead"] > 0
    assert metrics["scan_pieces"] >= 64
    assert metrics["bytes_served"] >= metrics["piece_length"]
    assert metrics["status_bytes_served"] == metrics["bytes_served"]
    assert metrics["readers"] == 1
    assert metrics["health_state"] in {"healthy", "deficit", "starved"}
