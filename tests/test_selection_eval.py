"""Cross-platform check of the tier-based context-selection corpus.

The dedicated gate (`benchmark/selection/run.py`) produces the report.json and
the CI exit code; this test exercises the same ground truth through the built
artifact on every platform/Python the suite runs on, so a tier-gating regression
fails the normal test run too — not only the dedicated eval job.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from conftest import perseus

if perseus is None:  # pragma: no cover
    pytest.skip("perseus build artifact unavailable", allow_module_level=True)

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "benchmark" / "selection" / "dataset.json"


def _skipped(source, tier):
    cfg = copy.deepcopy(perseus.DEFAULT_CONFIG)
    skipped, directives = [], []
    stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    perseus.render_source(source, cfg, REPO, max_tier=tier,
                          _directive_collector=directives, _stats=stats,
                          _skipped_directives=skipped)
    return {str(s.get("name", "")).lstrip("@") for s in skipped}


def test_selection_dataset_present():
    assert DATASET.is_file(), "benchmark/selection/dataset.json must exist"


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_tier_selection_is_exact(tier):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    for fx in data["fixtures"]:
        declared = {d["name"] for d in fx["directives"]}
        expected = {d["name"] for d in fx["directives"] if d["tier"] > tier}
        actual = _skipped(fx["source"], tier) & declared
        assert actual == expected, (
            f"[{fx['id']}] tier={tier}: expected skipped {sorted(expected)}, "
            f"got {sorted(actual)}"
        )
