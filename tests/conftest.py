"""Global test isolation: swarm-intelligence singletons must never read the
real runtime data files under data/cometnet/ — leaked entries there would
change resolve ordering and heatmap tests nondeterministically."""
import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def isolate_swarm_intelligence_stores(tmp_path):
    import core.swarm_intelligence as si

    original_heatmap = si._heatmap_store
    original_coverage = si._coverage_store
    si._heatmap_store = si.SeekHeatmapStore(path=str(tmp_path / "heatmap.json"))
    si._coverage_store = si.DebridCoverageIndex(path=str(tmp_path / "coverage.json"))
    yield
    si._heatmap_store = original_heatmap
    si._coverage_store = original_coverage
