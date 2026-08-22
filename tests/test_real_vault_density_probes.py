"""Probe contracts for semantic replay over the sanitized Vault corpus."""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "benchmark" / "real_vault_density" / "run.py"
spec = importlib.util.spec_from_file_location("real_vault_density_probes", SCRIPT)
assert spec and spec.loader
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)

CORPUS = REPO / "benchmark" / "real_vault_density" / "sanitized_corpus.json"
PROBES = REPO / "benchmark" / "real_vault_density" / "probes.json"


def test_probe_manifest_is_bounded_and_targets_corpus_items():
    corpus = benchmark.load_corpus(CORPUS)
    probes = benchmark.load_probes(PROBES)
    addresses = {(item["category"], item["key"]) for item in corpus["items"]}

    assert 3 <= len(probes) <= 8
    assert all((probe["category"], probe["key"]) in addresses for probe in probes)
    assert all(probe["query"] and probe["required_terms"] for probe in probes)


def test_probe_evaluation_reports_rank_task_and_decoder_outcomes():
    perseus = benchmark.load_perseus()
    probe = {
        "id": "p1",
        "category": "capture",
        "key": "target",
        "query": "target phrase",
        "required_terms": ["target phrase"],
    }
    recalled = [
        {"id": "mem-other", "category": "capture", "key": "other",
         "content": "irrelevant content", "summary": "irrelevant content"},
        {"id": "mem-target", "category": "capture", "key": "target",
         "content": "target phrase with supporting detail", "summary": "target phrase"},
    ]

    result = benchmark.evaluate_probe(probe, recalled, perseus, budget=80)

    assert result["rank"] == 2
    assert result["hit_at_5"] is True
    assert result["production"]["task_resumption"] == 1.0
    assert result["production"]["decoder_coverage"] == 0.0


def test_probe_evaluation_counts_omitted_target_as_decoder_recoverable():
    perseus = benchmark.load_perseus()
    probe = {
        "id": "p2",
        "category": "capture",
        "key": "target",
        "query": "target",
        "required_terms": ["target phrase"],
    }
    recalled = [
        {"id": "mem-other", "category": "capture", "key": "other",
         "content": "other " * 40, "summary": "other"},
        {"id": "mem-target", "category": "capture", "key": "target",
         "content": "target phrase", "summary": "target phrase"},
    ]

    result = benchmark.evaluate_probe(probe, recalled, perseus, budget=40)

    assert result["rank"] == 2
    assert result["production"]["task_resumption"] == 0.0
    assert result["production"]["decoder_coverage"] == 1.0
    assert result["legacy"]["decoder_coverage"] == 0.0


def test_probe_report_is_measurement_only_and_signature_bound():
    rows = [
        {"probe_id": "p1", "target": "capture/target", "rank": 1, "hit_at_5": True,
         "production": {"task_resumption": 1.0, "decoder_coverage": 0.0,
                        "prompt_tokens": 10, "uncompressed_tokens": 100},
         "legacy": {"task_resumption": 1.0, "decoder_coverage": 0.0,
                     "prompt_tokens": 10, "uncompressed_tokens": 100}},
    ]

    report = benchmark.build_probe_report(
        rows, binary="perseus-vault", corpus_items=24, budget_chars=640,
    )

    assert report["measurement_only"] is True
    assert report["gate"]["pass"] is None
    assert report["methods"]["production"]["task_resumption"] == 1.0
    assert report["budget_chars"] == 640
    assert len(report["probe_replay_signature"]) == 64
    assert benchmark.verify_report_signature(report) is True


def test_probe_report_aggregates_retrieval_and_task_metrics():
    rows = [
        {"rank": 1, "hit_at_5": True,
         "production": {"task_resumption": 1.0, "decoder_coverage": 1.0},
         "legacy": {"task_resumption": 0.0, "decoder_coverage": 0.0}},
        {"rank": None, "hit_at_5": False,
         "production": {"task_resumption": 0.0, "decoder_coverage": 0.0},
         "legacy": {"task_resumption": 0.0, "decoder_coverage": 0.0}},
    ]

    report = benchmark.summarize_probes(rows)

    assert report == {
        "count": 2,
        "hit_at_5": 0.5,
        "mrr": 0.5,
        "production_task_resumption": 0.5,
        "production_decoder_coverage": 0.5,
        "legacy_task_resumption": 0.0,
        "legacy_decoder_coverage": 0.0,
    }


def test_probe_report_is_reproducible_from_explicit_rows():
    rows = [{
        "probe_id": "p1",
        "target": "capture/target",
        "rank": 1,
        "hit_at_5": True,
        "production": {"task_resumption": 1.0, "decoder_coverage": 0.0},
        "legacy": {"task_resumption": 1.0, "decoder_coverage": 0.0},
    }]

    first = benchmark.build_probe_report(rows, "perseus-vault", 1, 640)
    second = benchmark.build_probe_report(rows, "perseus-vault", 1, 640)

    assert first == second
    assert first["probe_replay_signature"] == benchmark.probe_replay_signature(first)
    assert benchmark.verify_report_signature(first)
