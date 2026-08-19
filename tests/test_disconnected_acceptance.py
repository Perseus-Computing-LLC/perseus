"""Disconnected deployment acceptance bundle tests (#997)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import perseus


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "benchmark" / "disconnected_acceptance" / "run.py"
_SPEC = importlib.util.spec_from_file_location("disconnected_acceptance", RUN)
assert _SPEC and _SPEC.loader
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)


def test_offline_guard_blocks_dns_and_records_bounded_attempt():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    try:
        with pytest.raises(perseus.OfflineNetworkError):
            perseus.offline_network_check("https://example.invalid")
        report = perseus.offline_network_report()
        assert report["active"] is True
        assert report["attempts"][0]["outcome"] == "blocked"
        assert report["attempts"][0]["destination"] == "https://example.invalid"
    finally:
        perseus.deactivate_offline_mode()


def test_cli_offline_flag_is_enforced_for_a_local_render(tmp_path):
    source = tmp_path / "context.md"
    source.write_text("@perseus v1.0.26\n@date\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "perseus.py"), "--offline", "render", str(source)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "@date" not in result.stdout
    assert "202" in result.stdout


def test_child_cli_offline_probe_blocks_external_destination():
    result = subprocess.run(
        [sys.executable, str(ROOT / "perseus.py"), "--offline", "offline-probe", "https://example.invalid/probe", "--json"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["blocked"] is True
    assert payload["report"]["blocked_attempts"] == 1


def test_offline_guard_covers_send_and_name_service_variants():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    try:
        with pytest.raises(perseus.OfflineNetworkError):
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("203.0.113.9", 9))
        with pytest.raises(perseus.OfflineNetworkError):
            socket.gethostbyname_ex("example.invalid")
        with pytest.raises(perseus.OfflineNetworkError):
            socket.gethostbyaddr("203.0.113.9")
    finally:
        perseus.deactivate_offline_mode()


def test_disconnected_harness_emits_claim_bounded_machine_report(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path)
    assert report["schema_version"] == "perseus-disconnected-report/v1"
    assert report["status"] == "partial"
    assert report["network"]["policy"] == "deny_all"
    assert report["network"]["unexpected_attempts"] == []
    assert report["flow"]["perseus_render"]["status"] == "passed"
    assert report["flow"]["vault"]["status"] == "unavailable"
    assert report["flow"]["ledger"]["status"] == "unavailable"
    assert report["claims"]["ato_il5_il6"] == "not_claimed"
    assert report["claims"]["local_offline_capable"] == "observed"
    assert report["negative_results"]
    assert "resource_envelope" in report
    assert "raw" not in json.dumps(report).casefold()


def test_disconnected_evidence_digest_is_reproducible(tmp_path):
    first = harness.run_acceptance(ROOT, output_dir=tmp_path / "one")
    second = harness.run_acceptance(ROOT, output_dir=tmp_path / "two")
    assert first["evidence_digest"] == second["evidence_digest"]
    assert json.loads((tmp_path / "one" / "report.json").read_text()) ["evidence_digest"] == first["evidence_digest"]


def test_partial_report_requires_explicit_cli_opt_in(tmp_path):
    assert harness.main(["--repo", str(ROOT), "--output", str(tmp_path / "strict")]) == 1
    assert harness.main(["--repo", str(ROOT), "--output", str(tmp_path / "allowed"), "--allow-partial"]) == 0


def test_offline_guard_rejects_wildcards_reverse_dns_and_sanitizes_errors():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    try:
        for destination in ("0.0.0.0", "::", "localhost"):
            with pytest.raises(perseus.OfflineNetworkError):
                perseus.offline_network_check(destination, operation="dns")
        with pytest.raises(perseus.OfflineNetworkError):
            socket.gethostbyaddr("127.0.0.1")
        with pytest.raises(perseus.OfflineNetworkError):
            socket.getnameinfo(("127.0.0.1", 80), 0)
        with pytest.raises(perseus.OfflineNetworkError) as exc_info:
            perseus.offline_network_check("https://user:super-secret@example.invalid/path")
        assert "super-secret" not in str(exc_info.value)
        assert "user:" not in str(exc_info.value)
    finally:
        perseus.deactivate_offline_mode()


def test_offline_guard_allows_only_numeric_loopback_and_unix_socket_destinations():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    try:
        assert perseus.offline_network_check(("127.0.0.1", 9)) is True
        assert perseus.offline_network_check(("::1", 9, 0, 0)) is True
        assert perseus.offline_network_check("/tmp/perseus.sock") is True
        with pytest.raises(perseus.OfflineNetworkError):
            perseus.offline_network_check("localhost")
    finally:
        perseus.deactivate_offline_mode()


def test_offline_guard_covers_sendfile_egress():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(perseus.OfflineNetworkError):
            sock.sendfile(io.BytesIO(b"not allowed"))
    finally:
        sock.close()
        perseus.deactivate_offline_mode()


def test_in_process_cli_restores_offline_environment_and_monkeypatches(monkeypatch, tmp_path):
    source = tmp_path / "context.md"
    source.write_text("@perseus v1.0.26\n@date\n", encoding="utf-8")
    original_connect = socket.socket.connect
    monkeypatch.setenv("PERSEUS_OFFLINE", "caller-value")
    monkeypatch.setattr(sys, "argv", ["perseus", "--offline", "render", str(source)])
    try:
        perseus.main()
        observed = (socket.socket.connect, os.environ.get("PERSEUS_OFFLINE"), perseus._OFF_ACTIVE)
    finally:
        if getattr(perseus, "_OFF_ACTIVE", False):
            perseus.deactivate_offline_mode()
    assert observed == (original_connect, "caller-value", False)


def test_resource_limit_setup_failure_is_fail_closed(monkeypatch):
    if os.name != "posix":
        pytest.skip("resource limits are POSIX-specific")

    def deny(*_args):
        raise OSError("setrlimit denied")

    monkeypatch.setattr(harness.resource, "setrlimit", deny)
    apply_limits = harness._child_resource_limiter()
    with pytest.raises(OSError, match="setrlimit denied"):
        apply_limits()


def test_bounded_child_owns_timeout_descendants_and_caps_output(tmp_path):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")
    marker = tmp_path / "descendant-leaked"
    marker_literal = repr(str(marker))
    grandchild_code = f"import pathlib,time; time.sleep(0.8); pathlib.Path({marker_literal}).write_text('leaked')"
    code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild_code!r}]); "
        f"sys.stdout.write('x' * {harness._MAX_CHILD_OUTPUT_BYTES * 2}); sys.stdout.flush(); time.sleep(5)"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", code], cwd=tmp_path, timeout=0.25, env=dict(os.environ)
    )
    assert result["status"] == "timeout"
    assert result["stdout_truncated"] is True
    assert result["stdout_prefix_bytes"] <= harness._MAX_CHILD_OUTPUT_BYTES
    time.sleep(1.0)
    assert not marker.exists()


def test_fixture_requires_complete_nested_contract(tmp_path):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    del data["platform"]["resource_limits"]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(harness.AcceptanceError):
        harness._load_fixture(fixture_path)


def test_required_artifact_and_symlink_paths_are_rejected(tmp_path):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    data["artifacts"][1]["required"] = True
    data["artifacts"][1]["path"] = "external/vault"
    (tmp_path / "perseus.py").write_text("runtime", encoding="utf-8")
    (tmp_path / "external").mkdir()
    with pytest.raises(harness.AcceptanceError):
        harness._artifact_manifest(tmp_path, data)
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "external" / "vault").symlink_to(outside)
    with pytest.raises(harness.AcceptanceError):
        harness._artifact_manifest(tmp_path, data)


def test_resource_envelope_cannot_exceed_fixture_ceiling():
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    with pytest.raises(harness.AcceptanceError):
        harness._validate_resource_envelope(
            {
                "cpu_seconds_observed": 31.0,
                "peak_rss_mb_observed": 513.0,
                "disk_growth_bytes_observed": 257 * 1024 * 1024,
                "wall_seconds_observed": 1.0,
            },
            fixture,
        )


def test_declared_upgrade_bundle_is_bound_to_actual_digest_check(tmp_path):
    bundle = tmp_path / "upgrade.json"
    bundle.write_text("upgrade-v1", encoding="utf-8")
    spec = {
        "path": "upgrade.json",
        "version": "v1",
        "sha256": harness._sha_bytes(bundle.read_bytes()),
    }
    checked = harness._check_bundle(tmp_path, spec, "upgrade")
    assert checked["status"] == "passed"
    assert checked["checked"] is True
    spec["sha256"] = "0" * 64
    assert harness._check_bundle(tmp_path, spec, "upgrade")["status"] == "blocked"


def test_child_probe_json_rejects_nonfinite_malformed_and_extra_data():
    valid = {
        "blocked": True,
        "destination": "https://example.invalid/probe",
        "report": {
            "active": True,
            "policy": "deny_all_non_loopback",
            "attempts": [{"operation": "probe", "destination": "https://example.invalid/probe", "outcome": "blocked"}],
            "attempts_truncated": False,
            "blocked_attempts": 1,
            "allowed_local_attempts": 0,
        },
    }
    assert harness._parse_child_probe_json(json.dumps(valid))["blocked"] is True
    for malformed in (
        json.dumps({**valid, "report": {**valid["report"], "value": float("nan")}}),
        "[]",
        json.dumps(valid) + " trailing",
    ):
        with pytest.raises(harness.AcceptanceError):
            harness._parse_child_probe_json(malformed)


def test_evidence_digest_commits_to_outputs_and_manifest_report_commitments(tmp_path):
    first_fixture = tmp_path / "first.json"
    second_fixture = tmp_path / "second.json"
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    first_fixture.write_text(json.dumps(data), encoding="utf-8")
    changed = json.loads(json.dumps(data))
    changed["workload"]["source"] += "\nchanged stable workload\n"
    second_fixture.write_text(json.dumps(changed), encoding="utf-8")
    first = harness.run_acceptance(ROOT, fixture_path=first_fixture, output_dir=tmp_path / "one")
    second = harness.run_acceptance(ROOT, fixture_path=second_fixture, output_dir=tmp_path / "two")
    assert first["evidence_digest"] != second["evidence_digest"]
    assert first["manifest_commitment"]
    assert first["report_commitment"]
    manifest = json.loads((tmp_path / "one" / "manifest.json").read_text())
    assert manifest["manifest_commitment"] == first["manifest_commitment"]
    assert manifest["report_commitment"] == first["report_commitment"]


def test_process_group_kills_term_ignoring_descendants_after_leader_exits(tmp_path):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")
    marker = tmp_path / "descendant-ignored-term"
    marker_literal = repr(str(marker))
    grandchild = (
        "import pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"time.sleep(0.8); pathlib.Path({marker_literal}).write_text('leaked')"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); time.sleep(5)"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", parent], cwd=tmp_path, timeout=0.1, env=dict(os.environ)
    )
    assert result["status"] == "timeout"
    time.sleep(1.0)
    assert not marker.exists()


def test_offline_guard_hashes_short_secrets_and_local_paths():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    try:
        secret = "https://example.invalid/s"
        local_path = "/tmp/short-secret"
        with pytest.raises(perseus.OfflineNetworkError) as exc_info:
            perseus.offline_network_check(secret)
        assert secret not in str(exc_info.value)
        assert perseus.offline_network_check(local_path) is True
        destinations = [item["destination"] for item in perseus.offline_network_report()["attempts"]]
        assert destinations[0].startswith("sha256:")
        assert destinations[1].startswith("sha256:")
    finally:
        perseus.deactivate_offline_mode()


def test_offline_mode_is_reentrant_and_inner_exit_keeps_outer_guard():
    perseus.deactivate_offline_mode()
    with perseus.offline_mode():
        with perseus.offline_mode():
            with pytest.raises(perseus.OfflineNetworkError):
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("203.0.113.9", 9))
        assert perseus.offline_mode_active() is True
        with pytest.raises(perseus.OfflineNetworkError):
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("203.0.113.9", 9))
    assert perseus.offline_mode_active() is False


def test_getaddrinfo_numeric_loopback_is_accounted():
    perseus.deactivate_offline_mode()
    perseus.activate_offline_mode()
    try:
        socket.getaddrinfo("127.0.0.1", 9)
        report = perseus.offline_network_report()
        assert report["allowed_local_attempts"] == 1
        assert report["attempts"][-1]["outcome"] == "allowed_local"
    finally:
        perseus.deactivate_offline_mode()


def test_output_bundle_contains_no_raw_workload_body(tmp_path):
    fixture = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    marker = "UNIQUE-WORKLOAD-BODY-MARKER"
    fixture["workload"]["source"] = f"@perseus v1.0.26\n{marker}\n"
    fixture_path = tmp_path / "fixture.json"
    output = tmp_path / "evidence"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    harness.run_acceptance(ROOT, fixture_path=fixture_path, output_dir=output)
    assert all(marker.encode() not in path.read_bytes() for path in output.rglob("*" ) if path.is_file())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.__setitem__("fixture_id", 7),
        lambda data: data["platform"].__setitem__("extra", True),
        lambda data: data["workload"].__setitem__("extra", True),
        lambda data: data["artifacts"][0].__setitem__("extra", True),
        lambda data: data["claims_ceiling"].__setitem__("extra", "nope"),
        lambda data: data["claims_ceiling"].__setitem__("iron_bank_submitted", "approved"),
        lambda data: data["platform"]["resource_limits"].__setitem__("cpu_seconds", float("inf")),
    ],
)
def test_fixture_rejects_closed_schema_violations(tmp_path, mutate):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    mutate(data)
    fixture_path = tmp_path / "invalid-fixture.json"
    fixture_path.write_text(json.dumps(data, allow_nan=True), encoding="utf-8")
    with pytest.raises(harness.AcceptanceError):
        harness._load_fixture(fixture_path)


def test_resource_envelope_rejects_nan():
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    with pytest.raises(harness.AcceptanceError):
        harness._validate_resource_envelope(
            {
                "cpu_seconds_observed": float("nan"),
                "peak_rss_mb_observed": 1.0,
                "disk_growth_bytes_observed": 1.0,
            },
            fixture,
        )


def test_resource_envelope_measures_peak_rss_above_run_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(
        harness.resource,
        "getrusage",
        lambda _kind: SimpleNamespace(ru_maxrss=520 * 1024),
    )
    envelope = harness._resource_envelope(
        before_cpu=0.0,
        before_rss=500 * 1024,
        before_disk=0,
        output_dir=tmp_path,
        started=time.perf_counter(),
    )
    assert envelope["peak_rss_mb_observed"] == 20.0
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    assert harness._validate_resource_envelope(envelope, fixture)["peak_rss_mb_observed"] == 20.0


def test_child_probe_json_rejects_inconsistent_counters():
    payload = {
        "blocked": True,
        "destination": "https://example.invalid/probe",
        "report": {
            "active": True,
            "policy": "deny_all_non_loopback",
            "attempts": [{"operation": "probe", "destination": "x", "outcome": "blocked"}],
            "attempts_truncated": False,
            "blocked_attempts": 0,
            "allowed_local_attempts": 0,
        },
    }
    with pytest.raises(harness.AcceptanceError):
        harness._parse_child_probe_json(json.dumps(payload))


def test_fixture_limits_drive_child_enforcement_values():
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    limits = harness._child_limits_from_fixture(fixture)
    assert limits == {
        "cpu_seconds": 30,
        "address_space_bytes": 512 * 1024 * 1024,
        "file_bytes": 256 * 1024 * 1024,
    }


def test_declared_bundle_requires_and_executes_digest_bound_operation(tmp_path):
    bundle = tmp_path / "upgrade.json"
    marker = tmp_path / "executed"
    bundle.write_text("upgrade-v1", encoding="utf-8")
    digest = harness._sha_bytes(bundle.read_bytes())
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "upgrade",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha(""),
        "result": "passed",
        "persisted": True,
    }
    command = [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('ok'); print({json.dumps(receipt, sort_keys=True)!r})"]
    spec = {
        "path": "upgrade.json",
        "version": "v1",
        "sha256": digest,
        "command": command,
    }
    checked = harness._check_bundle(tmp_path, spec, "upgrade", execute=True)
    assert checked["status"] == "passed"
    assert checked["operation_executed"] is True
    assert marker.read_text() == "ok"


def test_bundle_without_operation_cannot_report_passed(tmp_path):
    bundle = tmp_path / "upgrade.json"
    bundle.write_text("upgrade-v1", encoding="utf-8")
    spec = {
        "path": "upgrade.json",
        "version": "v1",
        "sha256": harness._sha_bytes(bundle.read_bytes()),
    }
    checked = harness._check_bundle(tmp_path, spec, "upgrade", execute=True)
    assert checked["status"] == "blocked"
    assert checked["checked"] is False


def test_stable_output_digest_ignores_rendered_calendar_date():
    first = b"Rendered on 2026-08-19 12:34:56 UTC"
    second = b"Rendered on 2027-01-02 12:34:56 UTC"
    assert harness._stable_output_digest(first) == harness._stable_output_digest(second)


def test_backup_restore_reports_digest_comparison(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    restored = report["flow"]["backup_restore"]
    assert restored["digest_match"] is True
    assert restored["restored_digest"] == restored["backup_digest"]


def test_successful_child_finalizes_owned_process_group_before_return(tmp_path):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")
    marker = tmp_path / "success-descendant-leaked"
    grandchild = (
        "import pathlib,time; "
        f"time.sleep(0.8); pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    parent = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); print('ok')"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", parent], cwd=tmp_path, timeout=2.0, env=dict(os.environ)
    )
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    time.sleep(1.0)
    assert not marker.exists()


def test_bounded_child_rejects_nonfinite_timeout_before_spawn(monkeypatch, tmp_path):
    def fail_if_spawned(*_args, **_kwargs):
        raise AssertionError("Popen must not run for an invalid timeout")

    monkeypatch.setattr(harness.subprocess, "Popen", fail_if_spawned)
    with pytest.raises(harness.AcceptanceError, match="timeout"):
        harness._run_bounded_child(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path,
            timeout=float("nan"),
            env=dict(os.environ),
        )


def test_bundle_failures_use_bounded_reason_codes_without_paths(tmp_path):
    spec = {
        "path": "missing/upgrade.json",
        "version": "v1",
        "sha256": "0" * 64,
    }
    checked = harness._check_bundle(tmp_path, spec, "upgrade")
    assert checked["status"] == "blocked"
    assert checked["reason"] == "upgrade_bundle_unavailable"
    assert str(tmp_path) not in json.dumps(checked)


def test_fixture_requires_semantic_artifact_set(tmp_path):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    data["artifacts"] = [
        {"name": "arbitrary-a", "path": "perseus.py", "required": True, "sbom": None},
        {"name": "arbitrary-b", "path": "VERSION", "required": False, "sbom": None},
        {"name": "arbitrary-c", "path": "sbom.cdx.json", "required": False, "sbom": None},
    ]
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(harness.AcceptanceError, match="semantic"):
        harness._load_fixture(fixture_path)


def test_workload_query_and_restart_count_are_exercised(tmp_path, monkeypatch):
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    fixture["workload"] = dict(fixture["workload"], restart_count=2, query="query-used-by-every-cell")
    calls = []

    def fake_render(*args, **kwargs):
        calls.append((args, kwargs))
        return {"attempt": kwargs["attempt"], "status": "passed", "exit_code": 0, "output_sha256": "x", "stable_output_bytes": 1, "output_truncated": False}

    monkeypatch.setattr(harness, "_run_render", fake_render)
    monkeypatch.setattr(harness, "_run_bounded_child", lambda *args, **kwargs: {"status": "passed", "exit_code": 0, "stdout": json.dumps({"blocked": True, "destination": "x", "report": {"active": True, "policy": "deny_all_non_loopback", "attempts": [{"operation": "probe", "destination": "x", "outcome": "blocked"}], "attempts_truncated": False, "blocked_attempts": 1, "allowed_local_attempts": 0}}), "stderr": "", "stdout_prefix_bytes": 1, "stderr_prefix_bytes": 0, "stdout_truncated": False, "stderr_truncated": False, "child_cpu_seconds_observed": 0.0, "child_peak_rss_mb_observed": 0.0, "offline_report": {"active": True, "policy": "deny_all_non_loopback", "attempts": [], "attempts_truncated": False, "blocked_attempts": 0, "allowed_local_attempts": 0}})
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    report = harness.run_acceptance(ROOT, fixture_path=fixture_path, output_dir=tmp_path / "out")
    assert [item[1]["attempt"] for item in calls] == ["initial", "restart-1", "restart-2", "restore"]
    assert all(item[1]["query"] == "query-used-by-every-cell" for item in calls)
    assert report["workload_query_digest"] == harness._sha("query-used-by-every-cell")


def test_operation_receipt_must_bind_action_version_digest_query_and_persistence(tmp_path):
    bundle = tmp_path / "upgrade.json"
    bundle.write_text("upgrade-v1", encoding="utf-8")
    digest = harness._sha_bytes(bundle.read_bytes())
    query = "receipt-query"
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "upgrade",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha(query),
        "result": "passed",
        "persisted": True,
    }
    command = [sys.executable, "-c", f"print({json.dumps(receipt, sort_keys=True)!r})"]
    spec = {"path": "upgrade.json", "version": "v1", "sha256": digest, "command": command}
    checked = harness._check_bundle(tmp_path, spec, "upgrade", execute=True, query=query)
    assert checked["status"] == "passed"
    assert checked["operation_receipt_sha256"]
    receipt["version"] = "v2"
    bad_command = [sys.executable, "-c", f"print({json.dumps(receipt, sort_keys=True)!r})"]
    checked = harness._check_bundle(tmp_path, {**spec, "command": bad_command}, "upgrade", execute=True, query=query)
    assert checked["status"] == "blocked"
    assert checked["reason"] == "upgrade_operation_receipt_invalid"


def test_restore_requires_post_restore_state_binding(tmp_path, monkeypatch):
    real_render = harness._run_render

    def render_and_mutate(*args, **kwargs):
        result = real_render(*args, **kwargs)
        if kwargs["attempt"] == "restore":
            (Path(args[2]) / "mutation-marker").write_text("changed", encoding="utf-8")
        return result

    monkeypatch.setattr(harness, "_run_render", render_and_mutate)
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    restored = report["flow"]["backup_restore"]
    assert restored["status"] == "failed"
    assert restored["post_restore_digest"] != restored["backup_digest"]


def test_every_offline_python_child_has_guard_and_attempt_accounting(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    code = (
        "import json,socket\n"
        "blocked=False\n"
        "try: socket.gethostbyname('example.invalid')\n"
        "except Exception as exc: blocked=type(exc).__name__ == 'OfflineNetworkError'\n"
        "print(json.dumps({'blocked': blocked}))"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout=5,
        env={**dict(os.environ), "PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    assert result["status"] == "passed"
    assert json.loads(result["stdout"])["blocked"] is True
    assert result["offline_report"]["blocked_attempts"] == 1


def test_offline_guard_rejects_uncontainable_non_python_child(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    with pytest.raises(harness.AcceptanceError, match="offline_guard_unavailable"):
        harness._run_bounded_child(
            ["/bin/sh", "-c", "true"],
            cwd=tmp_path,
            timeout=5,
            env={**dict(os.environ), "PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
            offline_required=True,
        )


def test_disk_monitor_covers_dedicated_child_workspace(tmp_path):
    code = "open('workspace-write', 'wb').write(b'x' * 4096)"
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(tmp_path,),
        disk_limit_bytes=1024,
    )
    assert result["status"] == "resource_limit"


def test_adapter_requires_bound_machine_receipt(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    artifact = tmp_path / "adapter.bin"
    artifact.write_text("adapter-v1", encoding="utf-8")
    digest = harness._sha_bytes(artifact.read_bytes())
    query = "adapter-query"
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "perseus-vault",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha(query),
        "result": "passed",
        "persisted": True,
    }
    command = [sys.executable, "-c", f"print({json.dumps(receipt, sort_keys=True)!r})"]
    spec = {"name": "perseus-vault", "path": "adapter.bin", "command": command, "version": "v1"}
    manifest = {"state": "available", "sha256": digest, "version": "v1"}
    checked = harness._run_adapter(tmp_path, spec, manifest, harness._CHILD_LIMITS, monitor_dir=tmp_path / "out", query=query)
    assert checked["status"] == "passed"
    receipt["persisted"] = False
    bad = {**spec, "command": [sys.executable, "-c", f"print({json.dumps(receipt, sort_keys=True)!r})"]}
    checked = harness._run_adapter(tmp_path, bad, manifest, harness._CHILD_LIMITS, monitor_dir=tmp_path / "out2", query=query)
    assert checked["status"] == "blocked"
    assert checked["reason"] == "adapter_operation_receipt_invalid"


def test_render_binds_execution_to_manifest_digest(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    real_secure = harness._secure_file_bytes
    calls = {"perseus.py": 0}

    def mutate_after_stage(root, raw):
        value = real_secure(root, raw)
        if raw == "perseus.py":
            calls[raw] += 1
            if calls[raw] >= 2:
                return value + b"tampered"
        return value

    expected = harness._sha_bytes(real_secure(ROOT, "perseus.py"))
    monkeypatch.setattr(harness, "_secure_file_bytes", mutate_after_stage)
    result = harness._run_render(ROOT, "@perseus v1.0.26\n@date\n", state, attempt="digest", artifact_digest=expected)
    assert result["status"] == "blocked"
    assert result["reason"] == "perseus_artifact_changed_or_guard_unavailable"
