"""Offline semantic-density benchmark contract."""
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "benchmark" / "semantic_density" / "run.py"
_spec = importlib.util.spec_from_file_location("semantic_density_run", SCRIPT)
benchmark = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(benchmark)


def test_dataset_is_small_offline_and_has_load_bearing_cases():
    dataset = benchmark.load_dataset()

    assert dataset["offline"] is True
    assert 3 <= len(dataset["cases"]) <= 20
    assert all(case["items"] for case in dataset["cases"])
    assert any(
        item["category"] in benchmark.LOAD_BEARING_CATEGORIES
        for case in dataset["cases"]
        for item in case["items"]
    )


def test_production_serving_retains_load_bearing_fact_and_decoder():
    perseus = benchmark.load_perseus()
    case = next(case for case in benchmark.load_dataset()["cases"]
                if case["id"] == "deployment-handoff")

    production = benchmark.evaluate_case(perseus, case, method="production")

    assert production["task_resumption"] == 1.0
    assert production["load_bearing_retention"] == 1.0
    assert production["decoder_recovery"] == 1.0
    assert production["omitted_ids"] == ["mem-ordinary-deploy"]
    assert production["decoder_ids"] == ["mem-ordinary-deploy"]
    assert production["prompt_tokens"] < production["uncompressed_tokens"]


def test_legacy_relevance_baseline_can_drop_load_bearing_fact():
    perseus = benchmark.load_perseus()
    case = next(case for case in benchmark.load_dataset()["cases"]
                if case["id"] == "deployment-handoff")

    legacy = benchmark.evaluate_case(perseus, case, method="legacy")

    assert legacy["task_resumption"] == 0.0
    assert legacy["load_bearing_retention"] == 0.0
    assert legacy["decoder_recovery"] == 0.0


def test_report_gate_is_deterministic_and_requires_decoder_recovery():
    perseus = benchmark.load_perseus()
    report = benchmark.run_benchmark(perseus, benchmark.load_dataset())

    assert report["offline"] is True
    assert report["network_calls"] == 0
    assert report["gate"]["pass"] is True
    assert report["methods"]["production"]["decoder_recovery"] == 1.0
    assert report["methods"]["production"]["load_bearing_retention"] == 1.0
    assert report["signature_sha256"]


def test_report_includes_all_case_level_outputs_for_replay_audit():
    perseus = benchmark.load_perseus()
    report = benchmark.run_benchmark(perseus, benchmark.load_dataset())

    for method in ("production", "legacy"):
        rows = report["methods"][method]["cases"]
        assert len(rows) == report["cases"]
        assert all("selected_ids" in row for row in rows)
        assert all("omitted_ids" in row for row in rows)
