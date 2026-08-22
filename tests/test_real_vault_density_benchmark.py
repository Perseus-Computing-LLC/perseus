"""Contract tests for the bounded real-Perseus-Vault replay benchmark."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "benchmark" / "real_vault_density" / "run.py"
_spec = importlib.util.spec_from_file_location("real_vault_density_run", SCRIPT)
benchmark = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(benchmark)


@pytest.fixture
def dataset():
    return benchmark.load_dataset()


def test_live_binary_requires_explicit_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("PERSEUS_VAULT_BENCHMARK_BIN", raising=False)
    monkeypatch.delenv("PERSEUS_VAULT_BIN", raising=False)
    assert benchmark.find_binary() is None

    candidate = tmp_path / "perseus-vault"
    candidate.write_text("fixture binary placeholder")
    monkeypatch.setenv("PERSEUS_VAULT_BENCHMARK_BIN", str(candidate))
    assert benchmark.find_binary() == str(candidate.resolve())


def test_dataset_is_bounded_offline_and_has_load_bearing_cases(dataset):
    assert dataset["offline"] is True
    assert 2 <= len(dataset["cases"]) <= 10
    assert all(len(case["items"]) == 2 for case in dataset["cases"])
    assert all(case["load_bearing_ids"] for case in dataset["cases"])
    assert all(case["query"] == "" for case in dataset["cases"])


def test_selected_load_bearing_item_counts_as_decoder_recovered():
    perseus = benchmark.load_perseus()
    case = benchmark.load_dataset()["cases"][0]
    vault_items = [
        {
            "id": "mem-ordinary",
            "category": "observation",
            "key": "deploy-status",
            "content": case["items"][0]["content"],
        },
        {
            "id": "mem-correction",
            "category": "correction",
            "key": "deploy-boundary",
            "content": case["items"][1]["content"],
        },
    ]

    result = benchmark.evaluate_case(perseus, case, vault_items)

    assert result["production"]["load_bearing_retention"] == 1.0
    assert result["production"]["decoder_recovery"] == 1.0


def test_corpus_dataset_replays_all_items_once_with_explicit_bounds():
    corpus = {
        "items": [
            {"category": "capture", "key": "one", "content": "first"},
            {"category": "capture", "key": "two", "content": "second"},
            {"category": "capture", "key": "three", "content": "third"},
        ]
    }

    dataset = benchmark.build_corpus_dataset(corpus)

    assert len(dataset["cases"]) == 1
    assert len(dataset["cases"][0]["items"]) == 3
    assert dataset["corpus_item_count"] == 3
    assert dataset["cases"][0]["query"] == ""
    assert dataset["cases"][0]["budget_chars"] == 160


def test_corpus_case_reports_decoder_coverage_for_omitted_items():
    perseus = benchmark.load_perseus()
    items = [
        {"id": "mem-one", "category": "capture", "key": "one", "content": "first content", "relevance": 1.0},
        {"id": "mem-two", "category": "capture", "key": "two", "content": "second content", "relevance": 0.5},
        {"id": "mem-three", "category": "capture", "key": "three", "content": "third content", "relevance": 0.1},
    ]

    result = benchmark.evaluate_corpus_case(perseus, items, budget=20)

    assert result["production"]["omitted_item_count"] > 0
    assert result["production"]["decoder_coverage"] == 1.0
    assert result["legacy"]["decoder_coverage"] == 0.0
    assert result["production"]["selected_item_fraction"] < 1.0


def test_report_signature_covers_corpus_metadata():
    rows = [{
        "case_id": "case-a",
        "vault_recalled_ids": [],
        "production": {"task_resumption": 1.0, "load_bearing_retention": 1.0,
                       "decoder_recovery": 1.0, "prompt_tokens": 1,
                       "uncompressed_tokens": 2},
        "legacy": {"task_resumption": 0.0, "load_bearing_retention": 0.0,
                   "decoder_recovery": 0.0, "prompt_tokens": 1,
                   "uncompressed_tokens": 2},
    }]
    report = benchmark.build_report(rows, binary="perseus-vault")
    report["corpus"] = {"items": 24, "format": "perseus-sanitized-replay-v1"}

    assert benchmark.verify_report_signature(report) is False
    finalized = benchmark.finalize_report(report)
    assert benchmark.verify_report_signature(finalized) is True
    finalized["corpus"]["items"] = 23
    assert benchmark.verify_report_signature(finalized) is False


def test_report_contract_requires_real_vault_and_decoder_metrics():
    rows = [
        {
            "case_id": "case-a",
            "vault_recalled_ids": ["ordinary", "correction"],
            "production": {
                "task_resumption": 1.0,
                "load_bearing_retention": 1.0,
                "decoder_recovery": 1.0,
                "prompt_tokens": 10,
                "uncompressed_tokens": 20,
            },
            "legacy": {
                "task_resumption": 0.0,
                "load_bearing_retention": 0.0,
                "decoder_recovery": 0.0,
                "prompt_tokens": 10,
                "uncompressed_tokens": 20,
            },
        }
    ]

    report = benchmark.build_report(rows, binary="perseus-vault")

    assert report["real_vault"] is True
    assert report["network_calls"] == 0
    assert report["gate"]["pass"] is True
    assert report["methods"]["production"]["decoder_recovery"] == 1.0
    assert report["signature_sha256"]


@pytest.mark.slow
def test_real_vault_replay_passes_when_binary_is_available(tmp_path):
    binary = benchmark.find_binary(None)
    if binary is None:
        pytest.skip("perseus-vault release binary is not available")

    report = benchmark.run_benchmark(binary, tmp_path)

    assert report["real_vault"] is True
    assert report["network_calls"] == 0
    assert report["gate"]["pass"] is True
    assert report["methods"]["production"]["task_resumption"] == 1.0
    assert report["methods"]["production"]["load_bearing_retention"] == 1.0
    assert report["methods"]["production"]["decoder_recovery"] == 1.0
    assert report["vault"]["cases_replayed"] == len(report["case_results"])
    assert report["signature_sha256"]


def test_ephemeral_fixture_owns_distinct_private_databases(tmp_path):
    first = benchmark.EphemeralAdmissionFixture(binary="unused")
    second = benchmark.EphemeralAdmissionFixture(binary="unused")
    try:
        first_path = Path(first.db_path)
        second_path = Path(second.db_path)

        assert first_path != second_path
        assert first_path.parent != second_path.parent
        assert first_path.parent.name.startswith("perseus-vault-density-")
        assert second_path.parent.name.startswith("perseus-vault-density-")
        assert tmp_path not in first_path.parents
        assert tmp_path not in second_path.parents
    finally:
        first.close()
        second.close()


def test_ephemeral_fixture_matches_vault_unicode_json_canonicalization():
    body = {"summary": "I’m cautious", "content": "I’m cautious"}

    assert benchmark.EphemeralAdmissionFixture._stable_json(body) == (
        '{"content":"I’m cautious","summary":"I’m cautious"}'
    )


@pytest.mark.slow
def test_ephemeral_admission_fixture_is_serveable_and_cleans_up(tmp_path):
    binary = benchmark.find_binary(None)
    if binary is None:
        pytest.skip("perseus-vault release binary is not available")

    with benchmark.EphemeralAdmissionFixture(binary=binary) as fixture:
        db_path = fixture.db_path
        result = fixture.remember(
            "integration-fixture", "deterministic", {"content": "fixture record"}
        )
        recalled = fixture.recall("fixture record", category="integration-fixture")

        assert Path(db_path).parent.name.startswith("perseus-vault-density-")
        assert result["serveable"] is True
        assert result.get("proposed") is not True
        assert any(item["key"] == "deterministic" for item in recalled["items"])

    assert not Path(db_path).exists()


@pytest.mark.slow
def test_unauthenticated_write_remains_a_non_serveable_proposal(tmp_path):
    binary = benchmark.find_binary(None)
    if binary is None:
        pytest.skip("perseus-vault release binary is not available")

    vault = benchmark.VaultMCP(binary, tmp_path / "negative.db")
    try:
        result = vault.call(
            "perseus_vault_remember",
            {
                "category": "negative-contract",
                "key": "proposal",
                "body_json": '{"content":"review me"}',
                "type": "fact",
                "skip_dedup": True,
            },
        )
        recalled = vault.call(
            "perseus_vault_recall",
            {
                "query": "review me",
                "category": "negative-contract",
                "limit": 10,
                "mode": "fts5",
                "trust_weight": 0,
                "min_decay": 0,
            },
        )
    finally:
        vault.close()

    assert result["proposed"] is True
    assert result.get("serveable") is not True
    assert recalled["items"] == []
