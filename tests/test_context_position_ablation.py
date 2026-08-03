"""Cross-platform checks for the context-position ablation corpus and harness.

The dedicated gate (`benchmark/context_position/run.py`) produces report.json
and the CI exit code; these tests exercise the same corpus and core functions
on every platform/Python the suite runs on, so a position/provenance regression
fails the normal test run too — not only the dedicated eval job.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "benchmark" / "context_position" / "dataset.json"
RUN_PY = REPO / "benchmark" / "context_position" / "run.py"

sys_path = str(REPO / "benchmark" / "context_position")
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("context_position_run", RUN_PY)
_cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cp)  # type: ignore[union-attr]


def _load():
    return json.loads(DATASET.read_text(encoding="utf-8"))


def test_dataset_present_and_valid():
    assert DATASET.is_file(), "benchmark/context_position/dataset.json must exist"
    data = _load()
    valid, errors = _cp.validate_dataset(data)
    assert valid, f"dataset invalid: {errors}"


def test_all_positions_and_conditions_covered():
    data = _load()
    assert set(data["positions"]) == {"beginning", "middle", "end", "shuffled", "provenance_ranked"}
    assert set(data["conditions"]) == {"full", "resolver_selected", "resolver_selected_contract_anchor"}


@pytest.mark.parametrize("position", ["beginning", "middle", "end", "shuffled", "provenance_ranked"])
def test_position_ordering_preserves_item_set(position):
    data = _load()
    rng = __import__("random").Random(1)
    for fx in data["fixtures"]:
        ordered = _cp.position_order(position, fx["evidence"], rng)
        assert {i["id"] for i in ordered} == {i["id"] for i in fx["evidence"]}, (
            f"[{fx['id']}] position {position} dropped or added evidence"
        )


def test_resolver_drops_quarantined_and_superseded_without_newer():
    data = _load()
    for fx in data["fixtures"]:
        selected = _cp.resolver_select(fx["evidence"])
        selected_ids = {i["id"] for i in selected}
        for item in fx["evidence"]:
            if item["trust_class"] in {"quarantined", "untrusted"}:
                assert item["id"] not in selected_ids, (
                    f"[{fx['id']}] {item['id']} must be filtered by resolver"
                )


def test_poisoned_injection_never_wins():
    data = _load()
    rng = __import__("random").Random(20260803)
    for fx in data["fixtures"]:
        for position in data["positions"]:
            for condition in data["conditions"]:
                row = _cp.run_cell(fx, position, condition, rng)
                assert not row["poisoned_won"], (
                    f"[{fx['id']}] {position}/{condition}: poisoned evidence won"
                )


def test_heldout_ood_always_abstains():
    data = _load()
    rng = __import__("random").Random(20260803)
    for position in data["positions"]:
        for condition in data["conditions"]:
            row = _cp.run_cell({"id": "heldout-ood", "task": "held-out question",
                                "expected_answer": None,
                                "expected_coverage": [], "evidence": data["fixtures"][5]["evidence"]},
                               position, condition, rng)
            assert row["abstained"], f"heldout-ood {position}/{condition} did not abstain"


def test_attention_metric_is_diagnostic_only():
    data = _load()
    rng = __import__("random").Random(20260803)
    for fx in data["fixtures"]:
        for position in data["positions"]:
            for condition in data["conditions"]:
                row = _cp.run_cell(fx, position, condition, rng)
                assert row["attention"]["diagnostic_only"] is True


def test_full_harness_gate_passes():
    # Mirrors run.py main() acceptance without shelling out: correctness on
    # non-abstaining cells must be exact, and OOD must abstain.
    data = _load()
    rng = __import__("random").Random(20260803)
    rows = []
    for fx in data["fixtures"]:
        for position in data["positions"]:
            for condition in data["conditions"]:
                rows.append(_cp.run_cell(fx, position, condition, rng))
    non_abstain = [r for r in rows if not r["abstained"]]
    correctness = sum(r["correct"] for r in non_abstain) / max(1, len(non_abstain))
    assert correctness >= 1.0, f"correctness {correctness} < 1.0"
    ood = [r for r in rows if r["fixture"] == "heldout-ood"]
    assert all(r["abstained"] for r in ood)
