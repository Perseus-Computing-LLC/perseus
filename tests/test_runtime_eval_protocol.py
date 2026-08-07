"""Focused #927 runtime-evaluation protocol contract tests."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _module(relpath: str, name: str):
    path = REPO / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


protocol = _module("benchmark/runtime_eval/protocol.py", "runtime_eval_protocol")
runner_module = _module("benchmark/runtime_eval/runner.py", "runtime_eval_runner")
metering = _module("src/perseus/metering.py", "runtime_eval_metering")
gate = _module("scripts/check_vault_quality_scorecard.py", "runtime_eval_scorecard_gate")


@pytest.fixture
def source_artifact(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text('{"safe": true}\n', encoding="utf-8")
    return artifact


def _manifest(source_artifact):
    return protocol.build_manifest(
        suite="test-suite",
        family="prompt_only",
        artifacts=[source_artifact],
        repo_root=REPO,
        seed=17,
        scope={"workspace": "test"},
        provider="none",
        model="offline-deterministic",
        provider_version="1",
        auth_mode="none",
        timestamps={
            "queued_at": "2026-08-07T00:00:00+00:00",
            "started_at": None,
            "finished_at": None,
        },
    )


def test_manifest_is_versioned_self_describing_and_digest_bound(source_artifact):
    manifest = _manifest(source_artifact)

    assert manifest["protocol_version"] == protocol.PROTOCOL_VERSION
    assert manifest["suite"] == "test-suite"
    assert manifest["family"] == "prompt_only"
    assert manifest["seed"] == 17
    assert manifest["scope"]["workspace"]["redacted"] is True
    assert manifest["scope"]["workspace"]["sha256"] == protocol.sha256_bytes(b"test")
    assert manifest["auth"]["mode"] == "none"
    assert manifest["provider"] == {
        "name": "none",
        "model": "offline-deterministic",
        "version": "1",
    }
    assert manifest["repo"]["revision"]
    assert isinstance(manifest["repo"]["dirty"], bool)
    assert manifest["artifacts"][0]["sha256"]
    assert manifest["artifact_digest"]
    assert manifest["suite_digest"]
    assert manifest["timestamps"]["queued_at"].endswith("+00:00")
    assert "manifest_digest" in manifest
    assert "password" not in json.dumps(manifest).lower()


def test_family_selection_rejects_mixed_prompt_stateful_and_wrapper():
    for families in (
        ("prompt_only", "stateful"),
        ("prompt_only", "wrapper"),
        ("stateful", "wrapper"),
    ):
        with pytest.raises(protocol.MixedFamilyError):
            protocol.ensure_single_family(families)

    assert protocol.ensure_single_family(["prompt-only", "prompt_only"]) == "prompt_only"


def test_hash_only_bounds_drop_raw_log_and_private_artifact_content(source_artifact):
    log = protocol.sanitize_log(
        "PROMPT-SENTINEL query=PRIVATE-QUERY memory=PRIVATE-MEMORY "
        "authorization=Bearer SECRET",
        max_bytes=12,
    )
    assert log["truncated"] is True
    assert log["sha256"]
    assert log["captured_bytes"] == 0
    assert "PROMPT-SENTINEL" not in json.dumps(log)
    assert "PRIVATE-QUERY" not in json.dumps(log)
    assert "PRIVATE-MEMORY" not in json.dumps(log)
    assert "SECRET" not in json.dumps(log)

    metadata = protocol.artifact_metadata(source_artifact, max_bytes=1)
    assert metadata["sha256"]
    assert metadata["truncated"] is True
    assert metadata["captured_bytes"] == 0
    assert "safe" not in json.dumps(metadata)


def test_run_store_persists_atomic_lifecycle_and_partial_results(source_artifact, tmp_path):
    store = protocol.RunStore(tmp_path / "runs")
    manifest = _manifest(source_artifact)
    state = store.create(manifest)
    assert state["status"] == "queued"

    state = store.transition(state["run_id"], "running")
    state = store.update(state["run_id"], partial_results={"completed": 1, "total": 2})
    assert state["status"] == "running"
    assert state["partial_results"] == {"completed": 1, "total": 2}

    state = store.transition(state["run_id"], "cancelled", partial=True)
    assert state["status"] == "cancelled"
    assert state["partial"] is True
    assert not list((tmp_path / "runs" / state["run_id"]).glob("*.tmp"))
    assert store.load(state["run_id"])["status"] == "cancelled"


def _script(tmp_path, body):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "worker.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def _spec(script, family="prompt_only"):
    return runner_module.SuiteSpec(
        name="fixture-suite",
        family=family,
        artifacts=(script,),
        command=(sys.executable, str(script), "{result_path}"),
    )


def _pid_gone(pid: int) -> bool:
    """Return True when a PID no longer answers a liveness probe.

    POSIX raises ProcessLookupError for a dead PID; Windows os.kill(pid, 0)
    raises OSError (WinError 87) both for dead PIDs and for PIDs that cannot
    be opened, so treat those as gone too.
    """
    try:
        os.kill(pid, 0)
        return False
    except PermissionError:
        return False  # exists, just owned by another user
    except OSError:
        return True


def test_runner_is_offline_by_default_and_adapts_result_without_raw_payload(tmp_path):
    script = _script(
        tmp_path,
        """
        import json, sys
        json.dump({
            'protocol_version': 'fixture/v1',
            'status': 'passed',
            'usage': {'source': 'estimate', 'input_tokens': 9},
            'prompt': 'PRIVATE-PROMPT',
        }, open(sys.argv[1], 'w'))
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    state = runner.run(_spec(script), seed=4)

    assert state["status"] == "passed"
    assert state["manifest"]["mode"] == "offline"
    assert state["manifest"]["auth"]["mode"] == "none"
    assert state["result"]["usage"]["source"] == "estimate"
    encoded = json.dumps(state, sort_keys=True)
    assert "PRIVATE-PROMPT" not in encoded
    assert "usage" in state["result"]


def test_live_mode_requires_explicit_opt_in(tmp_path):
    script = _script(
        tmp_path,
        """
        import json, sys
        json.dump({'status': 'passed'}, open(sys.argv[1], 'w'))
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    with pytest.raises(protocol.LiveModeRequiredError):
        runner.run(_spec(script), mode="live")

    state = runner.run(
        _spec(script),
        mode="live",
        live=True,
        provider="fixture-provider",
        model="fixture-model",
        provider_version="fixture-1",
        auth_mode="environment",
    )
    assert state["status"] == "passed"
    assert state["manifest"]["mode"] == "live"
    assert state["manifest"]["auth"]["mode"] == "environment"


def test_runner_handles_malformed_result_as_failed_partial_run(tmp_path):
    script = _script(
        tmp_path,
        """
        import sys
        open(sys.argv[1], 'w').write('{not-json')
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    state = runner.run(_spec(script))

    assert state["status"] == "failed"
    assert state["partial"] is True
    assert state["failure"]["kind"] == "malformed_result"
    assert "not-json" not in json.dumps(state)


def test_runner_handles_timeout_and_crash_without_hanging(tmp_path):
    sleeper = _script(
        tmp_path,
        """
        import time
        time.sleep(10)
        """,
    )
    crashing = _script(
        tmp_path / "crash",
        """
        import sys
        sys.exit(7)
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    timed_out = runner.run(_spec(sleeper), timeout_seconds=0.05)
    crashed = runner.run(_spec(crashing))

    assert timed_out["status"] == "failed"
    assert timed_out["failure"]["kind"] == "timeout"
    assert timed_out["partial"] is True
    assert crashed["status"] == "failed"
    assert crashed["failure"]["kind"] == "crash"


def test_restart_marks_stale_running_run_interrupted_and_can_resume(tmp_path):
    script = _script(
        tmp_path,
        """
        import json, sys
        json.dump({'status': 'passed'}, open(sys.argv[1], 'w'))
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    state = runner.store.create(_manifest(script))
    runner.store.transition(state["run_id"], "running")
    interrupted = runner.recover()
    assert interrupted[0]["status"] == "interrupted"

    resumed = runner.restart(state["run_id"], _spec(script))
    assert resumed["status"] == "passed"
    assert resumed["attempt"] == 2


def test_cancel_preserves_partial_result_and_uses_terminal_cancelled_state(tmp_path):
    script = _script(
        tmp_path,
        """
        import time
        time.sleep(10)
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    run_id = runner.start(_spec(script), timeout_seconds=2)
    time.sleep(0.05)
    state = runner.cancel(run_id)

    assert state["status"] == "cancelled"
    assert state["partial"] is True


def test_vault_quality_adapter_wraps_report_without_reimplementing_cases(tmp_path):
    report = tmp_path / "vault-report.json"
    report.write_text(
        json.dumps(
            {
                "benchmark": "perseus-vault-memory-quality",
                "dataset": "perseus-vault-memory-quality-v0",
                "passed": True,
                "checks_passed": 29,
                "checks_total": 29,
                "signature_sha256": "a" * 64,
                "cases": [{"id": "private", "body": "PRIVATE-MEMORY"}],
            }
        ),
        encoding="utf-8",
    )
    adapted = runner_module.adapt_vault_quality_report(report)

    assert adapted["family"] == "stateful"
    assert adapted["status"] == "passed"
    assert adapted["checks"] == {"passed": 29, "total": 29}
    assert adapted["source_report"]["sha256"]
    assert "PRIVATE-MEMORY" not in json.dumps(adapted)
    assert "cases" not in adapted


def test_run_id_is_forwarded_as_external_ref_without_changing_usage_kind():
    path = REPO / "src" / "perseus" / "metering.py"
    metering = _module("src/perseus/metering.py", "runtime_eval_metering")
    captured = {}

    class FakeMeter:
        def __init__(self, **kwargs):
            pass

        def track(self, **kwargs):
            captured.update(kwargs)
            return type("Result", (), {"recorded": True})()

    fake = type(sys)("plutus_agent")
    fake.Meter = FakeMeter
    old = sys.modules.get("plutus_agent")
    sys.modules["plutus_agent"] = fake
    try:
        cfg = {"plutus": {"enabled": True, "db_path": str(path), "org": "test"}}
        result = metering.meter_usage(
            cfg,
            "openai",
            input_tokens=11,
            output_tokens=3,
            run_id="run-927",
        )
    finally:
        if old is None:
            sys.modules.pop("plutus_agent", None)
        else:
            sys.modules["plutus_agent"] = old

    assert result.recorded is True
    assert captured["external_ref"] == "run-927"
    assert captured["input_tokens"] == 11
    assert captured["source"] == "perseus"
    assert "baseline_input_tokens" not in captured


def test_failed_spawn_reaches_failed_to_start_terminal_state(tmp_path):
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    spec = runner_module.SuiteSpec(
        name="missing-command", family="prompt_only",
        command=(str(tmp_path / "does-not-exist"),),
    )
    run_id = runner.start(spec, timeout_seconds=1)
    state = runner.wait(run_id, timeout_seconds=1)
    assert state["status"] == protocol.Status.FAILED_TO_START.value
    assert state["finished_at"]


def test_interrupted_is_terminal_after_recovery(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    recovered = store.recover_running()
    assert recovered[0]["status"] == protocol.Status.INTERRUPTED.value
    assert protocol.Status.INTERRUPTED.value in protocol.TERMINAL_STATUSES
    assert store.load(state["run_id"])["finished_at"]


def test_log_file_hashing_reads_only_bounded_prefix(tmp_path):
    path = tmp_path / "huge.log"
    path.write_bytes(b"x" * (protocol.MAX_LOG_BYTES * 32))
    metadata = protocol.sanitize_log_file(path)
    assert metadata["bytes"] == protocol.MAX_LOG_BYTES * 32
    assert metadata["truncated"] is True
    assert metadata["captured_bytes"] == 0


def test_run_store_redacts_raw_fields_at_persistence_boundary(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    manifest = _manifest(source_artifact)
    manifest["prompt"] = "PRIVATE-PROMPT"
    manifest["manifest_digest"] = protocol._manifest_digest(manifest)
    state = store.create(manifest)
    store.update(state["run_id"], result={"body": "PRIVATE-BODY", "metadata": {"note": "PRIVATE-NOTE"}, "safe": 1})
    persisted = store.load(state["run_id"])
    encoded = json.dumps(persisted, sort_keys=True)
    assert "PRIVATE-PROMPT" not in encoded
    assert "PRIVATE-BODY" not in encoded
    assert "PRIVATE-NOTE" not in encoded
    assert '"prompt":' not in encoded.lower()
    assert '"body":' not in encoded.lower()


def test_build_manifest_live_requires_direct_opt_in(tmp_path):
    with pytest.raises(protocol.LiveModeRequiredError):
        protocol.build_manifest(
            suite="live-direct", family="prompt_only",
            repo_root=REPO, mode="live", provider="provider",
            auth_mode="account", artifacts=(),
        )


def test_aggregate_results_rejects_mixed_families_and_summarizes_one_family():
    passed = {"status": "passed", "family": "prompt_only", "usage": {"source": "none"}}
    failed = {"status": "failed", "family": "prompt_only", "usage": {"source": "none"}}
    aggregate = protocol.aggregate_results([passed, failed])
    assert aggregate["family"] == "prompt_only"
    assert aggregate["total"] == 2
    assert aggregate["passed"] == 1
    with pytest.raises(protocol.MixedFamilyError):
        protocol.aggregate_results([passed, {"status": "passed", "family": "stateful"}])


def test_windows_process_identity_uses_platform_probe(monkeypatch):
    """Windows cleanup must not depend on Linux /proc identity files."""
    class Completed:
        returncode = 0
        stdout = "1234\n"

    monkeypatch.setattr(protocol.os, "name", "nt", raising=False)
    monkeypatch.setattr(protocol.subprocess, "run", lambda *a, **kw: Completed())
    assert protocol.process_identity(1234) == {"pid": 1234, "start_time": 1234, "pgid": 1234}


def test_windows_cleanup_uses_taskkill_without_signal_sigkill(monkeypatch, tmp_path):
    """Windows has no SIGKILL; timeout cleanup must use taskkill /T /F."""
    calls = []

    class FakeProcess:
        pid = 1234

        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("POSIX terminate path used on Windows")

        def kill(self):
            raise AssertionError("POSIX kill path used on Windows")

    monkeypatch.setattr(runner_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(runner_module.protocol, "process_identity", lambda pid: {"start_time": 1, "pgid": 1234})
    monkeypatch.setattr(runner_module.subprocess, "run", lambda argv, **kw: calls.append(argv))
    monkeypatch.setattr(runner_module, "_process_descendants", lambda pid: set())
    assert runner_module._terminate_process_group(
        FakeProcess(), expected_start_time=1, expected_pgid=1234
    ) == set()
    assert calls == [["taskkill", "/PID", "1234", "/T", "/F"]]


def test_timeout_kills_descendant_process_group(tmp_path):
    pid_file = tmp_path / "child.pid"
    script = _script(
        tmp_path,
        f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(30)
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    try:
        state = runner.run(_spec(script), timeout_seconds=0.2)
        assert state["status"] == protocol.Status.FAILED.value
        deadline = time.time() + 2
        while time.time() < deadline and pid_file.exists():
            if _pid_gone(int(pid_file.read_text())):
                break
            time.sleep(0.05)
        if pid_file.exists():
            pid = int(pid_file.read_text())
            try:
                assert Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
            except FileNotFoundError:
                pass
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 9)
            except (ProcessLookupError, ValueError, OSError):
                pass


def test_timeout_kills_sigterm_ignoring_descendant(tmp_path):
    pid_file = tmp_path / "stubborn.pid"
    script = _script(
        tmp_path,
        f"""
        import signal, subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(30)
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    try:
        state = runner.run(_spec(script), timeout_seconds=0.2)
        assert state["status"] == protocol.Status.FAILED.value
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                pid = int(pid_file.read_text())
            except FileNotFoundError:
                break
            if _pid_gone(pid):
                break
            time.sleep(0.05)
        pid = int(pid_file.read_text())
        try:
            assert Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except FileNotFoundError:
            pass
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 9)
            except (ProcessLookupError, ValueError, OSError):
                pass


def test_recovery_terminates_persisted_process_group(tmp_path, source_artifact):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"] , start_new_session=True)
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    identity = protocol.process_identity(child.pid)
    store.update(state["run_id"], pid=child.pid, pgid=child.pid, pid_start_time=identity["start_time"])
    try:
        recovered = store.recover_running()
        assert recovered[0]["status"] == protocol.Status.INTERRUPTED.value
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_aggregate_results_requires_family_on_every_result():
    with pytest.raises(protocol.MixedFamilyError):
        protocol.aggregate_results([{"status": "passed"}], family="prompt_only")


def test_vault_adapter_rejects_partial_passing_scorecard(tmp_path):
    report = tmp_path / "partial-report.json"
    report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    with pytest.raises(protocol.MalformedResultError):
        runner_module.adapt_vault_quality_report(report)


def test_usage_rejects_fractional_token_counts():
    with pytest.raises(protocol.MalformedResultError):
        protocol.normalize_usage({"source": "authoritative", "input_tokens": 3.7})


def test_live_mapping_provider_named_none_is_rejected(tmp_path):
    script = _script(tmp_path, "import json,sys; json.dump({'status':'passed'}, open(sys.argv[1], 'w'))")
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    with pytest.raises(protocol.ProtocolError):
        runner.start(_spec(script), mode="live", live=True, provider={"name": "none"}, auth_mode="account")


def test_interrupted_cannot_transition_directly_to_running(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    store.recover_running()
    with pytest.raises(protocol.LifecycleError):
        store.transition(state["run_id"], protocol.Status.RUNNING)


def test_artifact_metadata_hashes_only_bounded_prefix(tmp_path):
    artifact = tmp_path / "large-artifact.bin"
    artifact.write_bytes(b"x" * (protocol.MAX_RESULT_BYTES * 4))
    metadata = protocol.artifact_metadata(artifact, max_bytes=protocol.MAX_RESULT_BYTES)
    assert metadata["truncated"] is True
    assert metadata["hash_scope"] == "prefix"


def test_timeout_kills_descendant_that_started_its_own_session(tmp_path):
    pid_file = tmp_path / "detached.pid"
    script = _script(
        tmp_path,
        f"""
        import signal, subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'], start_new_session=True)
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(30)
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    try:
        state = runner.run(_spec(script), timeout_seconds=0.2)
        assert state["status"] == protocol.Status.FAILED.value
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                pid = int(pid_file.read_text())
            except FileNotFoundError:
                break
            if _pid_gone(pid):
                break
            time.sleep(0.05)
        pid = int(pid_file.read_text())
        try:
            assert Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except FileNotFoundError:
            pass
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 9)
            except (ProcessLookupError, ValueError, OSError):
                pass


def test_cancel_returns_with_process_identifiers_cleared(tmp_path):
    script = _script(tmp_path, "import time; time.sleep(30)")
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    run_id = runner.start(_spec(script), timeout_seconds=10)
    state = runner.cancel(run_id)
    assert state["status"] == protocol.Status.CANCELLED.value
    assert state["pid"] is None
    assert state["pgid"] is None


def test_requeue_clears_stale_process_group_id(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    store.update(state["run_id"], pid=12345, pgid=12345)
    store.transition(state["run_id"], protocol.Status.INTERRUPTED)
    state = store.requeue(state["run_id"])
    assert state["pid"] is None
    assert state["pgid"] is None


def test_scope_and_bytes_payloads_never_persist_raw_values(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    manifest = _manifest(source_artifact)
    manifest["scope"] = {"workspace": "SCOPE-SECRET", "tenant": "DIRECT-TENANT-SECRET"}
    manifest["manifest_digest"] = protocol._manifest_digest(manifest)
    state = store.create(manifest)
    store.update(state["run_id"], metadata={"value": b"BYTES-SECRET"})
    encoded = json.dumps(store.load(state["run_id"]), sort_keys=True)
    assert "SCOPE-SECRET" not in encoded
    assert "DIRECT-TENANT-SECRET" not in encoded
    assert "BYTES-SECRET" not in encoded


def test_published_v2_scorecard_is_adapted_without_passed_flag(tmp_path):
    report = tmp_path / "scorecard.json"
    report.write_text(json.dumps({
        "scorecard_version": "perseus-vault-memory-quality-scorecard/v2",
        "verdict": "release_ready", "blocking": True, "accuracy": 1.0,
        "failed_categories": [], "missing_categories": [], "invalid_cases": [],
        "unavailable_categories": [], "unavailable_cases": [],
        "unavailable_capabilities": [], "unavailable_metrics": [],
        "failed_metrics": [], "invalid_metrics": [],
    }), encoding="utf-8")
    adapted = runner_module.adapt_vault_quality_report(report)
    assert adapted["status"] == "passed"
    assert "checks" not in adapted


def test_live_empty_auth_mode_is_rejected(tmp_path):
    script = _script(tmp_path, "import json,sys; json.dump({'status':'passed'}, open(sys.argv[1], 'w'))")
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    with pytest.raises(protocol.ProtocolError):
        runner.start(_spec(script), mode="live", live=True, provider="provider", auth_mode="")


def test_metering_rejects_fractional_usage_before_forwarding(monkeypatch, tmp_path):
    response = types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=3.7, completion_tokens=2, completion_tokens_details=None
    ))
    with pytest.raises(ValueError):
        metering._mtr_extract_usage(response)

    class FakeMeter:
        def __init__(self):
            self.calls = []
        def track(self, **kwargs):
            self.calls.append(kwargs)
            return types.SimpleNamespace(recorded=True)

    fake = FakeMeter()
    monkeypatch.setattr(metering, "_mtr_get_meter", lambda cfg: fake)
    cfg = {"plutus": {"enabled": True, "db_path": str(tmp_path / "ledger.db"), "fail_open": False}}
    with pytest.raises(ValueError):
        metering.meter_usage(cfg, "openai", input_tokens=3.7, output_tokens=2)
    assert fake.calls == []


def test_crash_kills_detached_descendant_before_return(tmp_path):
    pid_file = tmp_path / "crash-detached.pid"
    script = _script(
        tmp_path,
        f"""
        import signal, subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'], start_new_session=True)
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(0.1)
        raise SystemExit(7)
        """,
    )
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    try:
        state = runner.run(_spec(script), timeout_seconds=5)
        assert state["status"] == protocol.Status.FAILED.value
        child_pid = int(pid_file.read_text())
        try:
            state_code = Path(f"/proc/{child_pid}/stat").read_text().split()[2]
            assert state_code == "Z", f"detached child still running: {state_code}"
        except FileNotFoundError:
            pass
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 9)
            except (ProcessLookupError, ValueError):
                pass


def test_state_update_scope_is_filtered(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], scope={"workspace": "SCOPE-SECRET", "tenant": "DIRECT-TENANT-SECRET"})
    store.transition(state["run_id"], protocol.Status.RUNNING, scope={"workspace": "TRANSITION-SECRET"})
    encoded = json.dumps(store.load(state["run_id"]), sort_keys=True)
    assert "SCOPE-SECRET" not in encoded
    assert "DIRECT-TENANT-SECRET" not in encoded
    assert "TRANSITION-SECRET" not in encoded


def test_build_manifest_live_empty_auth_is_rejected_directly():
    with pytest.raises(protocol.LiveModeRequiredError):
        protocol.build_manifest(
            suite="live-direct", family="prompt_only", mode="live", live=True,
            provider="provider", auth_mode="", artifacts=(), repo_root=REPO,
        )


def test_blocked_published_scorecard_is_adapted_as_failed(tmp_path):
    report = tmp_path / "blocked-scorecard.json"
    report.write_text(json.dumps({
        "scorecard_version": "perseus-vault-memory-quality-scorecard/v2",
        "verdict": "blocked", "blocking": True, "accuracy": 0.75,
        "failed_categories": ["scope"], "missing_categories": [],
        "invalid_cases": [], "unavailable_categories": [],
        "unavailable_cases": [], "unavailable_capabilities": [],
        "unavailable_metrics": [], "failed_metrics": [], "invalid_metrics": [],
    }), encoding="utf-8")
    adapted = runner_module.adapt_vault_quality_report(report)
    assert adapted["status"] == "failed"


def test_run_store_preserves_manifest_digests(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    loaded = store.load(state["run_id"])["manifest"]
    assert loaded["artifact_digest"]
    assert loaded["suite_digest"]


def test_manifest_recomputes_caller_supplied_artifact_metadata(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(protocol.ProtocolError):
        protocol.build_manifest(suite="bad-artifact", family="prompt_only", repo_root=REPO, artifacts=[{"path": str(missing), "sha256": "a" * 64, "exists": True, "bytes": 1}])


def test_scope_updates_reject_identifier_looking_secrets(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], scope={"workspace": "prompt-secret", "tenant": "direct-tenant-secret"})
    encoded = json.dumps(store.load(state["run_id"]), sort_keys=True)
    assert "prompt-secret" not in encoded
    assert "direct-tenant-secret" not in encoded


def test_cancel_without_attached_job_terminates_persisted_process(tmp_path, source_artifact):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    state = runner.store.create(_manifest(source_artifact))
    runner.store.transition(state["run_id"], protocol.Status.RUNNING)
    identity = protocol.process_identity(child.pid)
    runner.store.update(state["run_id"], pid=child.pid, pgid=child.pid, pid_start_time=identity["start_time"])
    try:
        cancelled = runner.cancel(state["run_id"])
        assert cancelled["status"] == protocol.Status.CANCELLED.value
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill(); child.wait()


def test_recovery_terminates_persisted_detached_descendant(tmp_path, source_artifact):
    pid_file = tmp_path / "recovery-child.pid"
    parent = _script(tmp_path, f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        open({str(pid_file)!r}, 'w').write(str(child.pid))
        time.sleep(30)
    """)
    process = subprocess.Popen([sys.executable, str(parent)], start_new_session=True)
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    identity = protocol.process_identity(process.pid)
    store.update(state["run_id"], pid=process.pid, pgid=process.pid, pid_start_time=(identity or {}).get("start_time"))
    try:
        recovered = store.recover_running()
        assert recovered[0]["status"] == protocol.Status.INTERRUPTED.value
        if pid_file.exists():
            child_pid = int(pid_file.read_text())
            assert not Path(f"/proc/{child_pid}/stat").exists() or Path(f"/proc/{child_pid}/stat").read_text().split()[2] == "Z"
    finally:
        if process.poll() is None:
            process.kill(); process.wait()


def test_runtime_scorecard_requires_all_published_release_fields(tmp_path):
    report = tmp_path / "incomplete-scorecard.json"
    report.write_text(json.dumps({"scorecard_version": "perseus-vault-memory-quality-scorecard/v2", "verdict": "release_ready", "blocking": True, "accuracy": 1.0}), encoding="utf-8")
    with pytest.raises(protocol.MalformedResultError):
        runner_module.adapt_vault_quality_report(report)


def test_response_metering_rejects_falsey_nonintegers():
    for completion in (False, 0.0):
        response = types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=3, completion_tokens=completion, completion_tokens_details=None))
        with pytest.raises(ValueError):
            metering._mtr_extract_usage(response)


def test_v2_cli_validator_requires_every_published_field():
    report = {"scorecard_version": "perseus-vault-memory-quality-scorecard/v2", "verdict": "release_ready", "blocking": True, "accuracy": 1.0, "failed_categories": [], "missing_categories": []}
    assert gate.validate(report)


def test_manifest_digest_survives_load_and_update(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    assert store.load(state["run_id"])["manifest"]["manifest_digest"]
    store.update(state["run_id"], partial=True)
    assert store.load(state["run_id"])["manifest"]["manifest_digest"]


def test_direct_result_artifact_update_recomputes_metadata(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    with pytest.raises(protocol.ProtocolError):
        store.update(state["run_id"], result_artifact={"path": str(tmp_path / "missing.json"), "exists": True, "bytes": 999, "sha256": "0" * 64})


def test_scalar_persistence_and_result_projection_redact_sensitive_values(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], path="prompt-secret", model="raw-model-secret", dataset="raw-dataset-secret", workspace="raw-workspace-secret")
    encoded = json.dumps(store.load(state["run_id"]), sort_keys=True)
    for value in ("prompt-secret", "raw-model-secret", "raw-dataset-secret", "raw-workspace-secret"):
        assert value not in encoded
    result = protocol.normalize_result({"status": "passed", "benchmark": "raw-benchmark-secret", "dataset": "raw-dataset-secret"})
    assert "raw-benchmark-secret" not in json.dumps(result)
    assert "raw-dataset-secret" not in json.dumps(result)


def test_cancel_does_not_publish_terminal_state_before_cleanup(tmp_path, monkeypatch):
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    spec = runner_module.SuiteSpec(name="cancel-race", family="prompt_only", command=(sys.executable, "-c", "import time; time.sleep(30)"))
    run_id = runner.start(spec, timeout_seconds=30)
    original = runner_module._terminate_process_group
    monkeypatch.setattr(runner_module, "_terminate_process_group", lambda *args, **kwargs: set())
    pending = runner.cancel(run_id)
    assert pending["status"] == protocol.Status.RUNNING.value
    monkeypatch.setattr(runner_module, "_terminate_process_group", original)
    cancelled = runner.cancel(run_id)
    assert cancelled["status"] == protocol.Status.CANCELLED.value
    assert cancelled["pid"] is None and cancelled["pgid"] is None


def test_recovery_uses_persisted_owned_process_identity_after_leader_exit(tmp_path, source_artifact):
    pid_file = tmp_path / "owned-child.pid"
    parent = _script(tmp_path, f"""
        import subprocess, sys
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        open({str(pid_file)!r}, 'w').write(str(child.pid))
    """)
    process = subprocess.Popen([sys.executable, str(parent)], start_new_session=True)
    process.wait(timeout=5)
    deadline = time.time() + 2
    while not pid_file.exists() and time.time() < deadline:
        time.sleep(0.01)
    child_pid = int(pid_file.read_text())
    identity = protocol.process_identity(child_pid)
    assert identity is not None
    start_time = identity["start_time"]
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    store.update(state["run_id"], pid=process.pid, pgid=process.pid, owned_processes=[{"pid": child_pid, "start_time": start_time}])
    try:
        recovered = store.recover_running()
        assert recovered[0]["status"] == protocol.Status.RUNNING.value
        assert "recovery_failure" in recovered[0]
    finally:
        try:
            os.kill(child_pid, 9)
        except OSError:
            pass


def test_authoritative_usage_missing_counters_are_not_zero_filled(tmp_path, monkeypatch):
    calls = []
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO, usage_recorder=lambda **kwargs: calls.append(kwargs))
    runner._record_meter_usage("run-1", {"manifest": {"provider": {"name": "p", "model": "m"}}}, {"usage": {"source": "authoritative", "authoritative": {"input_tokens": 3}}})
    assert calls == []


def test_normalize_result_rejects_fractional_check_counters():
    with pytest.raises(protocol.MalformedResultError):
        protocol.normalize_result({"status": "passed", "checks": {"passed": 1.5, "total": 2}})


def test_innocuous_allowlisted_strings_are_hash_only(tmp_path, source_artifact):
    sentinel = "INNOCUOUS_PAYLOAD_927"
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], path=sentinel, model=sentinel, dataset=sentinel, workspace=sentinel, benchmark=sentinel)
    result = protocol.normalize_result({"status": "passed", "path": sentinel, "model": sentinel, "dataset": sentinel, "benchmark": sentinel})
    raw = (store.state_path(state["run_id"]).read_text() + json.dumps(store.load(state["run_id"])) + json.dumps(result))
    assert sentinel not in raw


def test_load_rejects_tampered_manifest_digest(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    path = store.state_path(state["run_id"])
    raw = json.loads(path.read_text())
    raw["manifest"]["suite"] = "tampered-suite"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(protocol.ProtocolError):
        store.load(state["run_id"])


def test_normalize_result_rejects_impossible_check_totals():
    with pytest.raises(protocol.MalformedResultError):
        protocol.normalize_result({"status": "passed", "checks": {"passed": 9, "total": 1}})


def test_v1_scorecard_adapter_matches_cli_legacy_contract(tmp_path):
    report = tmp_path / "v1-scorecard.json"
    report.write_text(json.dumps({"scorecard_version": "perseus-vault-memory-quality-scorecard/v1", "verdict": "release_ready", "blocking": True, "accuracy": 1.0, "failed_categories": [], "missing_categories": []}), encoding="utf-8")
    adapted = runner_module.adapt_vault_quality_report(report)
    assert adapted["status"] == "passed"


def test_meter_response_validates_fractional_usage_before_integration(monkeypatch, tmp_path):
    class FakeMeter:
        def track(self, **kwargs):
            raise AssertionError("integration received unvalidated usage")
    monkeypatch.setattr(metering, "_mtr_get_meter", lambda cfg: FakeMeter())
    integrations = types.ModuleType("plutus_agent.integrations")
    integrations.track_openai = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("integration called"))
    integrations.track_anthropic = integrations.track_openai
    monkeypatch.setitem(sys.modules, "plutus_agent.integrations", integrations)
    response = types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=3.7, completion_tokens=2), model="m")
    cfg = {"plutus": {"enabled": True, "db_path": str(tmp_path / "ledger.db"), "fail_open": False}}
    with pytest.raises(ValueError):
        metering.meter_response(cfg, response, provider="openai")


def test_context_reduction_rejects_fractional_explicit_counts(monkeypatch, tmp_path):
    class FakeMeter:
        def track(self, **kwargs):
            raise AssertionError("fractional estimate reached ledger")
    monkeypatch.setattr(metering, "_mtr_get_meter", lambda cfg: FakeMeter())
    cfg = {"plutus": {"enabled": True, "db_path": str(tmp_path / "ledger.db"), "fail_open": False}}
    with pytest.raises(ValueError):
        metering.meter_context_reduction(cfg, actual_tokens=3.7, baseline_tokens=10.9)


def test_persisted_process_group_identity_mismatch_is_not_signaled(monkeypatch):
    calls = []
    # raising=False keeps the probe meaningful on Windows, where os.killpg
    # does not exist and the NT cleanup path never signals a process group.
    monkeypatch.setattr(protocol.os, "killpg", lambda *args: calls.append(args), raising=False)
    protocol._terminate_persisted_process({"pid": 999999, "pgid": 999999, "pid_start_time": 1, "owned_processes": []})
    assert calls == []


def test_restart_resets_event_generation(tmp_path):
    sleep_script = _script(tmp_path, "import time; time.sleep(30)")
    pass_script = _script(tmp_path / "pass", "import json,sys; json.dump({'status':'passed'}, open(sys.argv[1], 'w'))")
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    cancelled_spec = _spec(sleep_script)
    pass_spec = _spec(pass_script)
    run_id = runner.start(cancelled_spec)
    runner.cancel(run_id)
    runner._events[run_id].set()
    restarted = runner.restart(run_id, spec=pass_spec)
    assert restarted["status"] == protocol.Status.PASSED.value


def test_nonstring_scorecard_versions_fail_closed(tmp_path):
    for version in ([], {}):
        report = tmp_path / f"bad-{len(str(version))}.json"
        report.write_text(json.dumps({"scorecard_version": version, "verdict": "release_ready", "blocking": True, "accuracy": 1.0}), encoding="utf-8")
        assert gate.validate(json.loads(report.read_text()))
        with pytest.raises(protocol.MalformedResultError):
            runner_module.adapt_vault_quality_report(report)


def test_missing_provider_response_counters_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(metering, "_mtr_get_meter", lambda cfg: object())
    cfg = {"plutus": {"enabled": True, "db_path": str(tmp_path / "l.db"), "fail_open": False}}
    response = types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=3, completion_tokens=None))
    with pytest.raises(ValueError):
        metering.meter_response(cfg, response, provider="openai")


def test_raw_meter_usage_requires_input_and_output(tmp_path):
    cfg = {"plutus": {"enabled": True, "db_path": str(tmp_path / "l.db"), "fail_open": False}}
    with pytest.raises(ValueError):
        metering.meter_usage(cfg, "openai")


def test_publish_context_baseline_rejects_fractional_counts():
    with pytest.raises(ValueError):
        metering.publish_context_baseline(actual_input_tokens=3.7, baseline_input_tokens=10)


def test_old_meter_does_not_silently_drop_fractional_baseline(monkeypatch, tmp_path):
    class OldMeter:
        def track(self, **kwargs):
            raise AssertionError("fractional baseline reached old meter")
    monkeypatch.setattr(metering, "_mtr_get_meter", lambda cfg: OldMeter())
    cfg = {"plutus": {"enabled": True, "db_path": str(tmp_path / "l.db"), "fail_open": False}}
    with pytest.raises(ValueError):
        metering.meter_context_reduction(cfg, actual_tokens=3, baseline_tokens=10.9)


def test_adapter_hashes_arbitrary_benchmark_and_dataset(tmp_path):
    sentinel = "INNOCUOUS_REPORT_PAYLOAD_927"
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"passed": True, "checks_passed": 1, "checks_total": 1, "benchmark": sentinel, "dataset": sentinel}), encoding="utf-8")
    adapted = runner_module.adapt_vault_quality_report(report)
    assert sentinel not in json.dumps(adapted)


def test_normalize_result_hashes_metric_keys_and_status_strings():
    sentinel = "INNOCUOUS_METRIC_PAYLOAD_927"
    result = protocol.normalize_result({"status": "passed", "metrics": {sentinel: {"status": sentinel, "rate": 1.0}}})
    assert sentinel not in json.dumps(result)


def test_create_rejects_forged_absolute_manifest_artifact(tmp_path):
    forged = tmp_path / "missing-artifact.json"
    manifest = _manifest(tmp_path / "real.json") if False else {
        "suite": "s", "family": "prompt_only", "artifacts": [{"path": str(forged), "exists": True, "sha256": "0" * 64, "bytes": 999}],
        "manifest_digest": "0" * 64,
    }
    store = protocol.RunStore(tmp_path / "runs")
    with pytest.raises(protocol.ProtocolError):
        store.create(manifest)


def test_persisted_result_digest_survives_and_detects_tamper(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], result={"status": "passed", "checks": {"passed": 1, "total": 1}})
    loaded = store.load(state["run_id"])
    assert loaded["result"]["result_digest"]
    path = store.state_path(state["run_id"]); raw = json.loads(path.read_text()); raw["result"]["checks"]["passed"] = 2; path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(protocol.ProtocolError):
        store.load(state["run_id"])


def test_requeue_clears_process_ownership_atomically(tmp_path, source_artifact, monkeypatch):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact)); store.transition(state["run_id"], protocol.Status.RUNNING)
    store.update(state["run_id"], pid=123, pgid=123, pid_start_time=1, owned_processes=[{"pid": 123, "start_time": 1}])
    store.transition(state["run_id"], protocol.Status.INTERRUPTED)
    writes = []; original = store._write
    monkeypatch.setattr(store, "_write", lambda value: (writes.append(dict(value)), original(value))[1])
    store.requeue(state["run_id"])
    assert len(writes) == 1 and writes[0]["pid"] is None and writes[0]["owned_processes"] == []


def test_persisted_pgid_must_match_leader_identity(monkeypatch):
    calls = []; monkeypatch.setattr(protocol.os, "killpg", lambda *args: calls.append(args), raising=False)
    identity = protocol.process_identity(os.getpid())
    protocol._terminate_persisted_process({"pid": os.getpid(), "pgid": os.getpid() + 1000, "pid_start_time": identity["start_time"], "owned_processes": []})
    assert calls == []


def test_record_meter_usage_preserves_validated_provider_descriptor(tmp_path, source_artifact):
    calls = []; runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO, usage_recorder=lambda **kwargs: calls.append(kwargs))
    state = runner.store.create(_manifest(source_artifact))
    loaded = runner.store.load(state["run_id"])
    runner._record_meter_usage(state["run_id"], loaded, {"usage": {"source": "authoritative", "authoritative": {"input_tokens": 3, "output_tokens": 2}}}, trusted=True)
    assert calls and calls[0]["provider"] == "none" and calls[0]["model"] == "offline-deterministic"


def test_nested_neutral_status_strings_are_hash_only(tmp_path, source_artifact):
    sentinel = "INNOCUOUS_NESTED_SENTINEL_927"
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], nested={"metric": {"status": sentinel}})
    assert sentinel not in store.state_path(state["run_id"]).read_text()
    assert sentinel not in json.dumps(store.load(state["run_id"]))


def test_stale_attempt_ownership_update_is_rejected(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    store.transition(state["run_id"], protocol.Status.INTERRUPTED)
    queued = store.requeue(state["run_id"])
    assert queued["attempt"] == 2
    assert store.update_if_attempt(state["run_id"], 1, owned_processes=[{"pid": 123, "start_time": 1}]) is False
    assert store.load(state["run_id"])["owned_processes"] == []


def test_adapter_nonstring_verdict_and_huge_accuracy_are_bounded(tmp_path):
    bad_verdict = tmp_path / "bad-verdict.json"
    bad_verdict.write_text(json.dumps({"scorecard_version": "perseus-vault-memory-quality-scorecard/v1", "verdict": [], "blocking": True, "accuracy": 1.0, "failed_categories": [], "missing_categories": []}), encoding="utf-8")
    with pytest.raises(protocol.MalformedResultError):
        runner_module.adapt_vault_quality_report(bad_verdict)
    huge = tmp_path / "huge.json"
    huge.write_text('{"scorecard_version":"perseus-vault-memory-quality-scorecard/v1","verdict":"release_ready","blocking":true,"accuracy":' + '9' * 5000 + ',"failed_categories":[],"missing_categories":[]}', encoding="utf-8")
    with pytest.raises(protocol.MalformedResultError):
        runner_module.adapt_vault_quality_report(huge)


def test_public_manifest_artifact_path_is_redacted(source_artifact):
    manifest = _manifest(source_artifact)
    assert manifest["artifacts"][0]["path"]["redacted"] is True


def test_low_level_relative_artifact_forgery_is_rejected(tmp_path, source_artifact):
    manifest = _manifest(source_artifact)
    manifest["artifacts"] = [{"path": "missing-relative.json", "exists": True, "sha256": "0" * 64, "bytes": 99, "truncated": False}]
    manifest["manifest_digest"] = protocol._manifest_digest(manifest)
    with pytest.raises(protocol.ProtocolError):
        protocol.RunStore(tmp_path / "runs").create(manifest)


def test_result_artifact_tamper_and_manifest_identity_tamper_are_rejected(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    output = store.run_dir(state["run_id"]) / "result.json"
    output.write_text("{}", encoding="utf-8")
    store.update(state["run_id"], result_artifact=protocol.artifact_metadata(output))
    raw_path = store.state_path(state["run_id"])
    raw = json.loads(raw_path.read_text())
    raw["result_artifact"]["bytes"] += 1
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(protocol.ProtocolError):
        store.load(state["run_id"])
    raw = json.loads(raw_path.read_text())
    raw["result_artifact"] = protocol.artifact_metadata(output)
    raw["manifest"]["run_id"] = "run-other"
    raw["manifest"]["manifest_digest"] = protocol._manifest_digest(raw["manifest"])
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(protocol.ProtocolError):
        store.load(state["run_id"])


def test_result_lifecycle_and_counter_consistency_are_enforced(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    with pytest.raises(protocol.ProtocolError):
        store.update(state["run_id"], result={"status": "passed", "checks": {"passed": 2, "total": 1}})
    store.transition(state["run_id"], protocol.Status.RUNNING)
    with pytest.raises(protocol.ProtocolError):
        store.transition(state["run_id"], protocol.Status.PASSED, result={"status": "failed"})
    with pytest.raises(protocol.ProtocolError):
        store.transition(state["run_id"], protocol.Status.FAILED, result={"status": "passed"})


def test_uppercase_provider_descriptor_survives_projection(tmp_path, source_artifact):
    manifest = protocol.build_manifest(suite="suite", family="prompt_only", artifacts=[source_artifact], repo_root=REPO, scope={}, provider="OpenAI", model="GPT-4o", provider_version="1", auth_mode="none")
    loaded = protocol.RunStore(tmp_path / "runs").create(manifest)
    loaded = protocol.RunStore(tmp_path / "runs").load(loaded["run_id"])
    assert loaded["manifest"]["provider"]["name"] == "OpenAI"
    assert loaded["manifest"]["provider"]["model"] == "GPT-4o"


def test_child_authoritative_usage_is_not_billed(tmp_path, source_artifact):
    calls = []
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO, usage_recorder=lambda **kw: calls.append(kw))
    state = runner.store.create(_manifest(source_artifact))
    loaded = runner.store.load(state["run_id"])
    runner._record_meter_usage(state["run_id"], loaded, {"usage": {"source": "authoritative", "authoritative": {"input_tokens": 1, "output_tokens": 1}}})
    assert calls == []


def test_v1_minimal_adapter_and_signature_path_projection(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"scorecard_version": "perseus-vault-memory-quality-scorecard/v1", "verdict": "release_ready", "blocking": True, "accuracy": 1.0}), encoding="utf-8")
    result = runner_module.adapt_vault_quality_report(report)
    assert result["status"] == "passed"
    assert result.get("signature_sha256") is None
    assert result["source_report"]["path"]["redacted"] is True


def test_nonstring_result_status_and_bad_signature_fail_closed():
    with pytest.raises(protocol.MalformedResultError):
        protocol.normalize_result({"status": []})
    with pytest.raises(protocol.MalformedResultError):
        protocol.normalize_result({"status": "passed", "signature_sha256": "not-a-digest"})


def test_nonfinite_timeout_and_false_green_transition_are_rejected(tmp_path):
    script = _script(tmp_path, "import json,sys; json.dump({'status':'passed'}, open(sys.argv[1], 'w'))")
    runner = runner_module.RuntimeEvalRunner(tmp_path / "runs", repo_root=REPO)
    with pytest.raises(protocol.ProtocolError):
        runner.start(_spec(script), timeout_seconds=float("nan"))
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    state = runner.store.create(_manifest(artifact))
    with pytest.raises(protocol.ProtocolError):
        runner.store.transition(state["run_id"], protocol.Status.PASSED)


def test_requeue_clears_prior_result_evidence(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.transition(state["run_id"], protocol.Status.RUNNING)
    store.transition(state["run_id"], protocol.Status.FAILED, result={"status": "failed"})
    queued = store.requeue(state["run_id"])
    assert queued["result"] is None
    assert queued["partial_results"] == {}


def test_forged_redacted_manifest_artifact_is_rejected(tmp_path, source_artifact):
    manifest = _manifest(source_artifact)
    manifest = dict(manifest)
    manifest["artifacts"] = [{"path": {"redacted": True, "sha256": "0" * 64, "bytes": 999}, "exists": True, "sha256": "0" * 64, "bytes": 999, "truncated": False}]
    manifest["manifest_digest"] = protocol._manifest_digest(manifest)
    with pytest.raises(protocol.ProtocolError):
        protocol.RunStore(tmp_path / "runs").create(manifest)


def test_missing_result_artifact_path_is_redacted(tmp_path, source_artifact):
    sentinel = "INNOCUOUS_RESULT_ARTIFACT_SENTINEL_927"
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], result_artifact={"path": sentinel, "exists": False, "sha256": None, "bytes": 0, "captured_bytes": 0, "truncated": False})
    assert sentinel not in store.state_path(state["run_id"]).read_text()
    assert sentinel not in json.dumps(store.load(state["run_id"]))


def test_redacted_result_artifact_rejects_extra_fields(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    with pytest.raises(protocol.ProtocolError):
        store.update(state["run_id"], result_artifact={"path": {"redacted": True, "sha256": "0" * 64, "bytes": 1}, "exists": False, "sha256": None, "bytes": 0, "leak": "raw"})


def test_scope_update_persists_hash_only(tmp_path, source_artifact):
    sentinel = "SCOPE_UPDATE_SENTINEL_927"
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], scope={"workspace": sentinel, "nested": {"raw": sentinel}})
    raw = store.state_path(state["run_id"]).read_text()
    assert sentinel not in raw
    loaded = store.load(state["run_id"])
    assert loaded["scope"]["workspace"]["redacted"] is True


def test_redacted_result_artifact_path_projection_must_be_mapping(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    with pytest.raises(protocol.ProtocolError):
        store.update(state["run_id"], result_artifact={"path": ["raw"], "exists": False, "sha256": None, "bytes": 0})


def test_provider_nested_credentials_are_dropped(tmp_path, source_artifact):
    sentinel = "SECRET_PROVIDER_NESTED_927"
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    store.update(state["run_id"], provider={"name": "safe", "api_key": sentinel, "authorization": "Bearer " + sentinel})
    raw = store.state_path(state["run_id"]).read_text()
    assert sentinel not in raw
    assert "api_key" not in raw and "authorization" not in raw


def test_runstore_preserves_manifest_scope_hash_projection(tmp_path, source_artifact):
    store = protocol.RunStore(tmp_path / "runs")
    state = store.create(_manifest(source_artifact))
    loaded = store.load(state["run_id"])
    workspace = loaded["manifest"]["scope"]["workspace"]
    assert workspace["redacted"] is True
    assert workspace["sha256"] == protocol.sha256_bytes(b"test")
    assert workspace["bytes"] == 4
