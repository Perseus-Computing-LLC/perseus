"""Contract tests for the bounded real-Perseus-Vault replay benchmark."""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

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


def test_recalled_addresses_are_exact_and_unique():
    items = [
        {"category": "capture", "key": "one"},
        {"category": "capture", "key": "one"},
    ]

    with pytest.raises(RuntimeError, match="duplicate"):
        benchmark._require_recalled_addresses(items, ["capture/one"])

    with pytest.raises(RuntimeError, match="exact"):
        benchmark._require_recalled_addresses(
            [{"category": "capture", "key": "one"}, {"category": "capture", "key": "two"}],
            ["capture/one"],
        )


def test_report_requires_retrieved_address_evidence():
    rows = [{
        "case_id": "case-a",
        "production": {"task_resumption": 1.0, "load_bearing_retention": 1.0,
                       "decoder_recovery": 1.0, "prompt_tokens": 1,
                       "uncompressed_tokens": 2},
        "legacy": {"task_resumption": 0.0, "load_bearing_retention": 0.0,
                   "decoder_recovery": 0.0, "prompt_tokens": 1,
                   "uncompressed_tokens": 2},
    }]

    with pytest.raises(ValueError, match="retrieved address"):
        benchmark.build_report(rows, binary="perseus-vault")


def test_fixture_forces_admission_lint_boundary_for_child(monkeypatch):
    monkeypatch.setenv("PERSEUS_VAULT_DISABLE_ADMISSION_LINT", "1")
    normal = benchmark.EphemeralAdmissionFixture(binary="unused")
    corpus = benchmark.EphemeralAdmissionFixture(
        binary="unused", allow_linted_content=True
    )
    try:
        assert normal._vault.env["PERSEUS_VAULT_DISABLE_ADMISSION_LINT"] == "0"
        assert corpus._vault.env["PERSEUS_VAULT_DISABLE_ADMISSION_LINT"] == "1"
    finally:
        normal.close()
        corpus.close()


def test_mcp_read_has_a_bounded_deadline(tmp_path):
    class SlowStdout:
        def readline(self):
            time.sleep(0.2)
            return ""

    client = benchmark.VaultMCP("unused", tmp_path / "vault.db", timeout=0.01)
    client.proc = SimpleNamespace(stdout=SlowStdout(), stderr=None)
    client._stop_process = lambda _proc: None
    with pytest.raises(TimeoutError, match="deadline"):
        client._readline_with_deadline(time.monotonic() + 0.01)
    client.proc = None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux identity guard")
def test_startup_identity_failure_reaps_fresh_process_group(monkeypatch, tmp_path):
    marker = tmp_path / "startup-identity-descendant-survived"
    ready = tmp_path / "startup-identity-descendant-ready"
    child = (
        "import pathlib,time; "
        f"time.sleep(0.35); pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    parent = (
        "import pathlib,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(10)"
    )
    real_popen = benchmark.subprocess.Popen
    spawned = None

    def fake_popen(_args, **kwargs):
        nonlocal spawned
        spawned = real_popen([sys.executable, "-c", parent], **kwargs)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.01)
        assert ready.exists()
        return spawned

    monkeypatch.setattr(benchmark.subprocess, "Popen", fake_popen)
    real_read_identity = benchmark.VaultMCP._read_process_identity
    read_count = 0

    def fail_leader_identity_once(pid):
        nonlocal read_count
        read_count += 1
        if read_count == 1:
            return None
        return real_read_identity(pid)

    monkeypatch.setattr(
        benchmark.VaultMCP,
        "_read_process_identity",
        staticmethod(fail_leader_identity_once),
    )
    client = benchmark.VaultMCP("unused", tmp_path / "vault.db")
    try:
        with pytest.raises(RuntimeError, match="identity"):
            client._start()
        assert client.proc is None
        assert client._process_group_id is None
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if marker.exists():
                break
            time.sleep(0.02)
        assert not marker.exists()
    finally:
        if spawned is not None and (
            spawned.poll() is None
            or benchmark.VaultMCP._process_group_exists(spawned.pid)
        ):
            try:
                os.killpg(spawned.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            spawned.wait(timeout=1)


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX-specific")
@pytest.mark.parametrize(
    "leader_mode",
    [
        "exits_first",
        "leader_reaped_first",
        "leader_reaped_identity_mismatch",
        "exits_on_term",
        "ignores_term",
        "identity_mismatch",
    ],
)
def test_mcp_stop_empties_owned_process_group(tmp_path, leader_mode):
    marker = tmp_path / f"descendant-survived-{leader_mode}"
    child = (
        "import pathlib,time; "
        f"time.sleep(0.35); pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    if leader_mode in {
        "exits_first",
        "leader_reaped_first",
        "leader_reaped_identity_mismatch",
    }:
        parent = (
            "import subprocess,sys; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}])"
        )
    elif leader_mode == "ignores_term":
        parent = (
            "import signal,subprocess,sys,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
        )
    else:
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
        )
    client = benchmark.VaultMCP("unused", tmp_path / "vault.db")
    client._enable_child_subreaper()
    process = subprocess.Popen(
        [sys.executable, "-c", parent],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    client._process_group_id = process.pid
    client._leader_identity = benchmark.VaultMCP._read_process_identity(process.pid)
    client._leader_pidfd = (
        os.pidfd_open(process.pid) if hasattr(os, "pidfd_open") else None
    )
    assert client._leader_identity is not None
    try:
        if leader_mode == "exits_first":
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                identity = benchmark.VaultMCP._read_process_identity(process.pid)
                if identity is not None and identity["state"] == "Z":
                    break
                time.sleep(0.02)
            else:
                pytest.fail("leader did not exit into an observable zombie state")
        elif leader_mode in {"leader_reaped_first", "leader_reaped_identity_mismatch"}:
            process.wait(timeout=1)
            client._leader_pidfd = None
        if leader_mode == "leader_reaped_identity_mismatch":
            saved_identity = client._leader_identity
            client._leader_identity = {
                **saved_identity,
                "session": saved_identity["session"] + 1,
            }
            with pytest.raises(RuntimeError, match="ownership"):
                client._stop_process(process)
            client._leader_identity = saved_identity
        if leader_mode == "identity_mismatch":
            client._leader_identity = {
                **client._leader_identity,
                "start_time": client._leader_identity["start_time"] + 1,
            }
            client.proc = process
            with pytest.raises(RuntimeError, match="identity"):
                client.close()
            assert client.proc is process
            client._leader_identity = benchmark.VaultMCP._read_process_identity(
                process.pid
            ) or {
                "pid": process.pid,
                "pgid": process.pid,
                "start_time": 0,
            }
            client.close()
        client._stop_process(process)
        assert not benchmark.VaultMCP._process_group_exists(process.pid)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and marker.exists():
            time.sleep(0.02)
        assert not marker.exists()
    finally:
        if process.poll() is None or benchmark.VaultMCP._process_group_exists(process.pid):
            client._stop_process(process)


def test_probe_replay_rejects_oversized_corpus_before_starting_vault(tmp_path):
    corpus_path = tmp_path / "corpus.json"
    probes_path = tmp_path / "probes.json"
    corpus_path.write_text(json.dumps({
        "items": [
            {"category": "capture", "key": f"item-{index}", "content": f"fact {index}"}
            for index in range(25)
        ]
    }), encoding="utf-8")
    probes_path.write_text(json.dumps([{
        "id": "probe-0", "query": "fact 0",
        "category": "capture", "key": "item-0",
    }]), encoding="utf-8")

    with pytest.raises(ValueError, match="24"):
        benchmark.run_probe_benchmark("unused", corpus_path, probes_path, tmp_path)

    oversized_path = tmp_path / "oversized-corpus.json"
    oversized_path.write_bytes(b"{" + b" " * benchmark.MAX_REPLAY_BYTES + b"}")
    with pytest.raises(ValueError, match="byte maximum"):
        benchmark.run_corpus_benchmark("unused", oversized_path, tmp_path)


def test_density_ci_pins_dependencies_and_drops_checkout_credentials():
    workflow = (REPO / ".github" / "workflows" / "vault-quality-gate.yml").read_text()
    constraints = REPO / "benchmark" / "real_vault_density" / "requirements-ci.txt"

    assert "requirements-ci.txt" in workflow
    assert '-m "not slow"' in workflow
    assert "-m slow" in workflow
    assert workflow.count("persist-credentials: false") >= 4
    assert constraints.exists()
    assert "pytest==" in constraints.read_text()
    assert "PyYAML==" in constraints.read_text()


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
        "vault_recalled_addresses": ["capture/case-a"],
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
            "vault_recalled_addresses": ["ordinary/key-a", "correction/key-b"],
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


def test_fixture_cleanup_runs_when_vault_shutdown_fails(monkeypatch):
    fixture = benchmark.EphemeralAdmissionFixture(binary="unused")
    db_parent = Path(fixture.db_path).parent

    def fail_shutdown():
        raise RuntimeError("synthetic shutdown failure")

    monkeypatch.setattr(fixture._vault, "close", fail_shutdown)
    with pytest.raises(RuntimeError, match="shutdown"):
        fixture.close()
    assert not db_parent.exists()


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
