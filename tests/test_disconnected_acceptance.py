"""Disconnected deployment acceptance bundle tests (#997)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import socket
import subprocess
import shlex
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import perseus


pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="disconnected acceptance primitives require Linux",
)


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "benchmark" / "disconnected_acceptance" / "run.py"
BROKER = ROOT / "benchmark" / "disconnected_acceptance" / "cgroup_broker.py"
_SPEC = importlib.util.spec_from_file_location("disconnected_acceptance", RUN)
assert _SPEC and _SPEC.loader
harness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(harness)
_BROKER_SPEC = importlib.util.spec_from_file_location("disconnected_acceptance_broker", BROKER)
assert _BROKER_SPEC and _BROKER_SPEC.loader
broker = importlib.util.module_from_spec(_BROKER_SPEC)
_BROKER_SPEC.loader.exec_module(broker)


_REAL_RUN_BOUNDED_CHILD = harness._run_bounded_child


def _legacy_test_child(*args, **kwargs):
    """Keep non-acceptance unit probes explicit about legacy cleanup semantics."""
    kwargs.setdefault("require_process_containment", False)
    return _REAL_RUN_BOUNDED_CHILD(*args, **kwargs)


setattr(harness, "_run_bounded_child", _legacy_test_child)


def _enable_test_only_disk_guard(monkeypatch):
    """Exercise accounting/report semantics without claiming host Landlock support."""
    monkeypatch.setattr(harness, "_landlock_supported", lambda: True)
    monkeypatch.setattr(harness, "_install_landlock_write_sandbox", lambda _roots: None)


def _fixture():
    return harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")


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


def test_disconnected_harness_emits_claim_bounded_machine_report(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
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
    monkeypatch.setattr(perseus, "install_inherited_seccomp", lambda: None)
    try:
        perseus.main()
        observed = (socket.socket.connect, os.environ.get("PERSEUS_OFFLINE"), perseus._OFF_ACTIVE)
    finally:
        if getattr(perseus, "_OFF_ACTIVE", False):
            perseus.deactivate_offline_mode()
    assert observed == (original_connect, "caller-value", False)


def test_console_entrypoint_installs_inherited_seccomp_for_offline(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["perseus", "--offline"])
    monkeypatch.setattr(perseus, "install_inherited_seccomp", lambda: calls.append(True))
    monkeypatch.setattr(perseus, "_main_impl", lambda: 0)
    assert perseus.main() == 0
    assert calls == [True]


def test_resource_limit_setup_failure_is_fail_closed(monkeypatch):
    if os.name != "posix":
        pytest.skip("resource limits are POSIX-specific")

    def deny(*_args):
        raise OSError("setrlimit denied")

    monkeypatch.setattr(harness.resource, "setrlimit", deny)
    apply_limits = harness._child_resource_limiter()
    with pytest.raises(OSError, match="setrlimit denied"):
        apply_limits()


def test_missing_posix_resource_capability_fails_closed(monkeypatch):
    if os.name != "posix":
        pytest.skip("resource limits are POSIX-specific")
    monkeypatch.setattr(harness, "resource", None)
    with pytest.raises(harness.AcceptanceError, match="resource"):
        harness._child_resource_limiter()


def test_harness_imports_without_posix_resource_capability():
    code = (
        "import builtins, importlib.util\n"
        f"run = {str(RUN)!r}\n"
        "real_import = builtins.__import__\n"
        "def deny_resource(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    if name == 'resource':\n"
        "        raise ModuleNotFoundError('resource is unavailable')\n"
        "    return real_import(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = deny_resource\n"
        "spec = importlib.util.spec_from_file_location('disconnected_acceptance_no_resource', run)\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert module.resource is None\n"
        "module.os.name = 'nt'\n"
        "assert module._child_resource_limiter() is None\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    assert result.returncode == 0, result.stderr


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
    assert result["status"] == "resource_limit"
    assert result["stdout_truncated"] is True
    assert result["output_limit_exceeded"] is True
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


def test_fixture_cpu_contract_allows_coverage_budget_but_preserves_ceiling():
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    limits = fixture["platform"]["resource_limits"]
    assert limits["cpu_seconds"] == harness._MAX_FIXTURE_CPU_SECONDS == 300
    envelope = {
        "cpu_seconds_observed": 299.0,
        "peak_rss_mb_observed": 1.0,
        "disk_growth_bytes_observed": 1.0,
    }
    assert harness._validate_resource_envelope(envelope, fixture) == envelope
    with pytest.raises(harness.AcceptanceError, match="cpu_seconds_observed"):
        harness._validate_resource_envelope({**envelope, "cpu_seconds_observed": 301.0}, fixture)


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


def test_report_commitment_binds_resource_observations(tmp_path, monkeypatch):
    envelopes = [
        {"cpu_seconds_observed": 1.0, "peak_rss_mb_observed": 10.0, "disk_growth_bytes_observed": 1.0, "wall_seconds_observed": 1.0, "measurement_status": "observed_with_host_metrics"},
        {"cpu_seconds_observed": 2.0, "peak_rss_mb_observed": 11.0, "disk_growth_bytes_observed": 2.0, "wall_seconds_observed": 2.0, "measurement_status": "observed_with_host_metrics"},
    ]
    monkeypatch.setattr(harness, "_resource_envelope", lambda *_args: envelopes.pop(0))
    first = harness.run_acceptance(ROOT, output_dir=tmp_path / "one")
    second = harness.run_acceptance(ROOT, output_dir=tmp_path / "two")
    assert first["report_commitment"] != second["report_commitment"]
    assert first["evidence_digest"] == second["evidence_digest"]


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


@pytest.mark.skipif(os.name != "posix", reason="resource metrics are POSIX-specific")
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


@pytest.mark.skipif(os.name != "posix", reason="resource metrics are POSIX-specific")
def test_child_rss_observation_uses_per_run_highwater_baseline(monkeypatch, tmp_path):
    readings = iter(
        [
            SimpleNamespace(ru_utime=0.0, ru_stime=0.0, ru_maxrss=100 * 1024),
            SimpleNamespace(ru_utime=0.0, ru_stime=0.0, ru_maxrss=200 * 1024),
        ]
    )
    monkeypatch.setattr(harness.resource, "getrusage", lambda _kind: next(readings))
    result = harness._run_bounded_child(
        [sys.executable, "-c", "pass"], cwd=tmp_path, timeout=5, env=dict(os.environ)
    )
    assert result["child_peak_rss_mb_observed"] == 100.0


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
        "cpu_seconds": 300,
        "address_space_bytes": 512 * 1024 * 1024,
        "file_bytes": 256 * 1024 * 1024,
    }


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
def test_immutable_staged_file_is_owner_read_only_and_digest_bound(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"immutable staged bytes")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    staged, digest = harness._stage_file(tmp_path, "source.bin", workspace)
    mode = staged.stat().st_mode & 0o777
    assert mode == 0o400
    assert mode & 0o077 == 0
    harness._verify_staged_file(staged, digest, workspace=workspace)
    with pytest.raises(harness.AcceptanceError, match="replaced"):
        harness._stage_file(tmp_path, "source.bin", workspace)


def test_declared_bundle_requires_and_executes_digest_bound_operation(tmp_path):
    bundle = tmp_path / "upgrade.json"
    (tmp_path / "perseus.py").write_bytes((ROOT / "perseus.py").read_bytes())
    bundle.write_text("upgrade-v1", encoding="utf-8")
    digest = harness._sha_bytes(bundle.read_bytes())
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "upgrade",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha(""),
        "result": "passed",
        "persisted_state": {"path": "state.json", "sha256": harness._sha_bytes(b"persisted")},
    }
    command = [sys.executable, "-c", f"open('state.json', 'wb').write(b'persisted'); print({json.dumps(receipt, sort_keys=True)!r})"]
    spec = {
        "path": "upgrade.json",
        "version": "v1",
        "sha256": digest,
        "command": command,
    }
    checked = harness._check_bundle(tmp_path, spec, "upgrade", execute=True)
    assert checked["status"] == "passed"
    assert checked["operation_executed"] is True
    assert checked["operation_receipt_persisted"] is True


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


def test_cgroup_scope_seals_parent_and_child_controls(tmp_path):
    if os.name != "posix":
        pytest.skip("cgroup boundary is POSIX-specific")
    root = tmp_path / "delegated"
    group = root / "scope"
    root.mkdir()
    group.mkdir()
    for path in (
        root / "cgroup.procs",
        root / "cgroup.kill",
        group / "cgroup.procs",
        group / "cgroup.kill",
    ):
        path.write_text("", encoding="ascii")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    root_fd = os.open(root, flags)
    group_fd = os.open(group, flags)
    root_procs_fd = os.open(root / "cgroup.procs", os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
    root_kill_fd = os.open(root / "cgroup.kill", os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
    group_procs_fd = os.open(group / "cgroup.procs", os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
    kill_fd = os.open(group / "cgroup.kill", os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
    scope = harness._CgroupScope(
        root=root,
        group=group,
        root_fd=root_fd,
        root_procs_fd=root_procs_fd,
        group_fd=group_fd,
        group_procs_fd=group_procs_fd,
        kill_fd=kill_fd,
        root_kill_fd=root_kill_fd,
    )
    try:
        assert harness._seal_cgroup_scope(scope) is True
        assert (os.fstat(root_fd).st_mode & 0o777) == 0
        assert (os.fstat(group_fd).st_mode & 0o777) == 0
        assert (os.fstat(root_procs_fd).st_mode & 0o777) == 0
        assert (os.fstat(root_kill_fd).st_mode & 0o777) == 0
        assert (os.fstat(group_procs_fd).st_mode & 0o777) == 0
        assert (os.fstat(kill_fd).st_mode & 0o777) == 0
    finally:
        harness._unseal_cgroup_scope(scope)
        try:
            for path in (
                root / "cgroup.procs",
                root / "cgroup.kill",
                group / "cgroup.procs",
                group / "cgroup.kill",
            ):
                path.unlink(missing_ok=True)
            group.rmdir()
            root.rmdir()
        except OSError:
            pass
        for fd in (root_fd, root_procs_fd, root_kill_fd, group_fd, group_procs_fd, kill_fd):
            try:
                os.close(fd)
            except OSError:
                pass



@pytest.mark.skipif(os.name != "posix", reason="POSIX socket permission bits only")
def test_broker_listener_uses_group_mode_and_restores_umask(tmp_path, monkeypatch):
    socket_dir = tmp_path / "private"
    socket_dir.mkdir()
    os.chmod(socket_dir, 0o700)
    parent_fd = os.open(
        socket_dir,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
    )
    monkeypatch.setattr(broker, "_open_private_directory", lambda _path: os.dup(parent_fd))
    monkeypatch.setattr(broker.os, "chown", lambda *_args: None)
    original_umask = os.umask(0o027)
    os.umask(original_umask)
    listener = None
    try:
        listener = broker._bind_listener(socket_dir / "broker.sock", os.getuid())
        assert (socket_dir / "broker.sock").stat().st_mode & 0o777 == 0o660
        restored_umask = os.umask(0o027)
        os.umask(restored_umask)
        assert restored_umask == original_umask
    finally:
        os.umask(original_umask)
        if listener is not None:
            listener.close()
        (socket_dir / "broker.sock").unlink(missing_ok=True)
        os.close(parent_fd)


def test_broker_opens_pidfd_when_python_wrapper_is_missing():
    fd = broker._open_pidfd(os.getpid())
    try:
        assert fd >= 0
    finally:
        os.close(fd)


def test_broker_client_rejects_non_root_server_peer(monkeypatch):
    monkeypatch.setattr(harness, "_broker_peer_credentials", lambda _conn: (4242, 1002, 1002))
    with pytest.raises(OSError, match="broker peer"):
        harness._validate_broker_server_peer(object())


def test_broker_cleanup_never_writes_stale_peer_pid(monkeypatch):
    scope = object.__new__(broker._Scope)
    scope.peer_pid = 4242
    scope.peer_start_time = 11
    scope.peer_pidfd = 99
    scope.root_procs_fd = 1
    scope.group_read_fd = 2
    scope.kill_fd = 3
    scope.events_fd = 4
    scope.root_fd = scope.group_fd = scope.group_procs_fd = -1
    scope.root = Path("/unused")
    scope.group = Path("/unused/group")
    scope.handle = "0" * 32
    monkeypatch.setattr(broker, "_pidfd_is_alive", lambda _fd: False)
    monkeypatch.setattr(broker, "_process_start_time", lambda _pid: None)
    writes = []
    monkeypatch.setattr(broker, "_write_fd", lambda fd, data: writes.append((fd, data)))
    monkeypatch.setattr(broker, "_members", lambda _fd: [])
    monkeypatch.setattr(broker, "_populated", lambda _fd: False)
    monkeypatch.setattr(broker, "_chmod", lambda *_args: None)
    monkeypatch.setattr(broker.os, "rmdir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scope, "close", lambda: True, raising=False)
    assert broker._cleanup_scope(scope) is True
    assert (scope.root_procs_fd, str(scope.peer_pid).encode("ascii")) not in writes


def test_broker_cleanup_fails_closed_if_peer_changes_after_move_out(monkeypatch):
    scope = object.__new__(broker._Scope)
    scope.peer_pid = 4242
    scope.peer_start_time = 11
    scope.peer_pidfd = 99
    scope.root_procs_fd = 1
    scope.group_read_fd = 2
    scope.kill_fd = 3
    scope.events_fd = 4
    scope.root_fd = scope.group_fd = scope.group_procs_fd = -1
    scope.root = Path("/unused")
    scope.group = Path("/unused/group")
    scope.handle = "0" * 32
    identities = iter((True, False))
    monkeypatch.setattr(broker, "_peer_identity_matches", lambda *_args: next(identities))
    writes = []
    monkeypatch.setattr(broker, "_write_fd", lambda fd, data: writes.append((fd, data)))
    monkeypatch.setattr(broker, "_members", lambda _fd: [])
    monkeypatch.setattr(broker, "_populated", lambda _fd: False)
    monkeypatch.setattr(broker, "_chmod", lambda *_args: None)
    monkeypatch.setattr(broker.os, "rmdir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(scope, "close", lambda: True, raising=False)
    assert broker._cleanup_scope(scope) is False
    assert (scope.root_procs_fd, str(scope.peer_pid).encode("ascii")) in writes


def test_broker_cleanup_failure_stops_listener_rebind(monkeypatch):
    monkeypatch.setattr(broker, "_handle_client", lambda *_args: False)
    with pytest.raises(SystemExit, match="cleanup"):
        broker._serve_session_result(False)


def test_report_flow_requires_process_containment_for_passed_cell():
    cell = {
        "status": "passed",
        "exit_code": 0,
        "offline_report": {
            "active": True,
            "policy": "deny_all_non_loopback",
            "attempts": [],
            "attempts_truncated": False,
            "blocked_attempts": 0,
            "allowed_local_attempts": 0,
        },
        "offline_guard": {
            "enforced": True,
            "boundary": "seccomp",
            "report_present": True,
            "telemetry": "parent_derived",
        },
        "process_containment": {
            "enforced": False,
            "boundary": None,
            "cleanup_verified": True,
        },
    }
    with pytest.raises(harness.AcceptanceError, match="containment"):
        harness._validate_report_flow_semantics({"test": cell})


def test_disk_charge_is_conservative_against_filesystem_growth():
    assert harness._disk_growth_charge(128, 3_229_485_565) == 3_229_485_565


def test_directory_size_counts_allocated_blocks(tmp_path):
    payload = tmp_path / "payload"
    payload.write_bytes(b"x")
    expected = payload.stat().st_blocks * 512
    assert harness._directory_size(tmp_path) >= expected


def test_missing_cgroup_broker_is_a_hard_containment_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_ACCEPTANCE_CGROUP_BROKER", str(tmp_path / "missing.sock"))
    monkeypatch.delenv("PERSEUS_ACCEPTANCE_CGROUP_ROOT", raising=False)
    with pytest.raises(OSError, match="broker"):
        harness._create_broker_scope("red-test")


def test_broker_removes_listener_after_accepting_parent_session(tmp_path):
    socket_path = tmp_path / "broker.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(socket_path))
        accepted = broker._accept_one_session(server, socket_path)
        assert not socket_path.exists()
        accepted.close()
    finally:
        client.close()
        server.close()
        socket_path.unlink(missing_ok=True)


def test_bounded_child_cannot_reach_broker_endpoint(tmp_path):
    endpoint = os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_BROKER")
    if not endpoint or not Path(endpoint).parent.exists():
        pytest.skip("host cgroup broker integration is not configured")
    marker = tmp_path / "broker-capability-reached"
    child = (
        "import pathlib,socket; "
        f"s=socket.socket(socket.AF_UNIX); "
        f"s.settimeout(0.2); "
        f"\ntry: s.connect({endpoint!r})\n"
        f"\nexcept OSError: pass\n"
        f"\nelse: pathlib.Path({str(marker)!r}).write_text('connected')"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-S", "-c", child],
        cwd=tmp_path,
        timeout=2.0,
        env=dict(os.environ),
        require_process_containment=True,
    )
    assert result["status"] == "passed"
    assert result["process_containment"] == {
        "enforced": True,
        "boundary": "cgroup_broker",
        "cleanup_verified": True,
    }
    assert not marker.exists()


def test_broker_retains_root_scope_process(tmp_path, monkeypatch):
    (tmp_path / "cgroup.procs").write_text("", encoding="ascii")
    monkeypatch.setattr(broker.os, "getpid", lambda: 4242)
    with pytest.raises(TypeError, match="root FD"):
        broker._retain_root(tmp_path)
    root_fd = os.open(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        broker._retain_root(root_fd)
    finally:
        os.close(root_fd)
    assert (tmp_path / "cgroup.procs").read_text(encoding="ascii") == "4242"


def test_required_containment_rejects_direct_cgroup_env_without_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("PERSEUS_ACCEPTANCE_CGROUP_ROOT", str(tmp_path))
    monkeypatch.delenv("PERSEUS_ACCEPTANCE_CGROUP_BROKER", raising=False)
    with pytest.raises(OSError, match="broker"):
        harness._create_cgroup_scope("a" * 32, required=True)


def test_configured_cgroup_boundary_unavailable_blocks_child(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("cgroup boundary is POSIX-specific")
    monkeypatch.setenv("PERSEUS_ACCEPTANCE_CGROUP_ROOT", str(tmp_path / "missing-cgroup"))
    monkeypatch.delenv("PERSEUS_ACCEPTANCE_CGROUP_BROKER", raising=False)
    result = harness._run_bounded_child(
        [sys.executable, "-c", "print('ok')"], cwd=tmp_path, timeout=2.0, env=dict(os.environ),
        require_process_containment=True,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "child_containment_unavailable"


def test_successful_child_cannot_escape_with_a_detached_session(tmp_path):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")
    containment_configured = bool(
        os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_ROOT")
        or os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_BROKER")
    )
    marker = tmp_path / "detached-descendant-leaked"
    ready = tmp_path / "detached-descendant-ready"
    grandchild = (
        "import os,pathlib,time; os.setsid(); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(1.0); "
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    parent = (
        "import pathlib,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"deadline=time.monotonic()+1.0; "
        f"\nwhile time.monotonic() < deadline and not pathlib.Path({str(ready)!r}).exists(): time.sleep(0.01); "
        "print('ok')"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", parent], cwd=tmp_path, timeout=2.0, env=dict(os.environ),
        require_process_containment=True,
    )
    if containment_configured:
        assert result["status"] == "passed"
        assert result["exit_code"] == 0
    else:
        assert result["status"] in {"blocked", "failed"}
    time.sleep(1.2)
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


def test_fixture_resource_and_restart_caps_fail_closed(tmp_path):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    data["platform"]["resource_limits"]["disk_mb"] = harness._MAX_FIXTURE_DISK_MB + 1
    fixture_path = tmp_path / "too-large.json"
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(harness.AcceptanceError):
        harness._load_fixture(fixture_path)
    data["platform"]["resource_limits"]["disk_mb"] = 256
    data["workload"]["restart_count"] = harness._MAX_FIXTURE_RESTART_COUNT + 1
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(harness.AcceptanceError):
        harness._load_fixture(fixture_path)


def test_workload_query_and_restart_count_are_exercised(tmp_path, monkeypatch):
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    fixture["workload"] = dict(fixture["workload"], restart_count=2, query="query-used-by-every-cell")
    calls = []

    def fake_render(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "attempt": kwargs["attempt"],
            "status": "passed",
            "exit_code": 0,
            "output_sha256": "x",
            "stable_output_bytes": 1,
            "output_truncated": False,
            "resource_limits": dict(kwargs["resource_limits"]),
            "offline_report": {
                "active": True,
                "policy": "deny_all_non_loopback",
                "attempts": [],
                "attempts_truncated": False,
                "blocked_attempts": 0,
                "allowed_local_attempts": 0,
            },
            "offline_guard": {
                "enforced": True,
                "boundary": "seccomp",
                "report_present": True,
                "telemetry": "parent_derived",
            },
            "process_containment": {
                "enforced": True,
                "boundary": "cgroup_broker",
                "cleanup_verified": True,
            },
        }

    monkeypatch.setattr(harness, "_run_render", fake_render)
    monkeypatch.setattr(harness, "_run_bounded_child", lambda *args, **kwargs: {"status": "passed", "exit_code": 0, "stdout": json.dumps({"blocked": True, "destination": "x", "report": {"active": True, "policy": "deny_all_non_loopback", "attempts": [{"operation": "probe", "destination": "x", "outcome": "blocked"}], "attempts_truncated": False, "blocked_attempts": 1, "allowed_local_attempts": 0}}), "stderr": "", "stdout_prefix_bytes": 1, "stderr_prefix_bytes": 0, "stdout_truncated": False, "stderr_truncated": False, "child_cpu_seconds_observed": 0.0, "child_peak_rss_mb_observed": 0.0, "offline_report": {"active": True, "policy": "deny_all_non_loopback", "attempts": [], "attempts_truncated": False, "blocked_attempts": 0, "allowed_local_attempts": 0}, "offline_sandbox": "seccomp", "offline_guard": {"enforced": True, "boundary": "seccomp", "report_present": True, "telemetry": "parent_derived"}, "process_containment": {"enforced": True, "boundary": "cgroup_broker", "cleanup_verified": True}})
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    report = harness.run_acceptance(ROOT, fixture_path=fixture_path, output_dir=tmp_path / "out")
    assert [item[1]["attempt"] for item in calls] == ["initial", "restart-1", "restart-2", "restore"]
    assert all(item[1]["query"] == "query-used-by-every-cell" for item in calls)
    assert report["workload_query_digest"] == harness._sha("query-used-by-every-cell")


def test_operation_receipt_must_bind_action_version_digest_query_and_persistence(tmp_path):
    bundle = tmp_path / "upgrade.json"
    (tmp_path / "perseus.py").write_bytes((ROOT / "perseus.py").read_bytes())
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
        "persisted_state": {"path": "state.json", "sha256": harness._sha_bytes(b"persisted")},
    }
    command = [sys.executable, "-c", f"open('state.json', 'wb').write(b'persisted'); print({json.dumps(receipt, sort_keys=True)!r})"]
    spec = {"path": "upgrade.json", "version": "v1", "sha256": digest, "command": command}
    checked = harness._check_bundle(tmp_path, spec, "upgrade", execute=True, query=query)
    assert checked["status"] == "passed"
    assert checked["operation_receipt_sha256"]
    receipt["version"] = "v2"
    bad_command = [sys.executable, "-c", f"print({json.dumps(receipt, sort_keys=True)!r})"]
    checked = harness._check_bundle(tmp_path, {**spec, "command": bad_command}, "upgrade", execute=True, query=query)
    assert checked["status"] == "blocked"
    assert checked["reason"] == "upgrade_operation_receipt_invalid"


def test_receipt_rejects_arbitrary_decoy_state_file(tmp_path):
    (tmp_path / "perseus.py").write_bytes((ROOT / "perseus.py").read_bytes())
    bundle = tmp_path / "upgrade.json"
    bundle.write_text("upgrade-v1", encoding="utf-8")
    artifact_digest = harness._sha_bytes(bundle.read_bytes())
    state_digest = harness._sha_bytes(b"decoy-state")
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "upgrade",
        "version": "v1",
        "artifact_sha256": artifact_digest,
        "query_sha256": harness._sha(""),
        "result": "passed",
        "persisted_state": {"path": "decoy.json", "sha256": state_digest},
    }
    command = [
        sys.executable,
        "-c",
        f"open('decoy.json', 'wb').write(b'decoy-state'); print({json.dumps(receipt, sort_keys=True)!r})",
    ]
    checked = harness._check_bundle(
        tmp_path,
        {"path": "upgrade.json", "version": "v1", "sha256": artifact_digest, "command": command},
        "upgrade",
        execute=True,
    )
    assert checked["status"] == "blocked"
    assert checked["reason"] == "upgrade_operation_receipt_invalid"


def test_restore_requires_post_restore_state_binding(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
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
    result = harness._run_bounded_child(
        ["/bin/sh", "-c", "true"],
        cwd=tmp_path,
        timeout=5,
        env={**dict(os.environ), "PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["offline_sandbox"] == "seccomp"
    assert result["offline_report"] is None


def test_offline_policy_cannot_be_disabled_by_explicit_false(tmp_path):
    with pytest.raises(harness.AcceptanceError, match="offline_guard_required"):
        harness._run_bounded_child(
            [sys.executable, "-c", "print('ok')"],
            cwd=tmp_path,
            timeout=5,
            env={**dict(os.environ), "PERSEUS_OFFLINE": "1"},
            offline_required=False,
        )


def test_seccomp_contains_python_s_without_sitecustomize(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    result = harness._run_bounded_child(
        [sys.executable, "-S", "-c", "import socket; print(socket.socket().connect_ex(('203.0.113.9', 9)))"],
        cwd=tmp_path,
        timeout=5,
        env={**dict(os.environ), "PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["offline_sandbox"] == "seccomp"


def test_offline_required_must_be_a_boolean(tmp_path):
    with pytest.raises(harness.AcceptanceError, match="offline_policy"):
        harness._run_bounded_child(
            [sys.executable, "-c", "print('ok')"],
            cwd=tmp_path,
            timeout=5,
            env={"PERSEUS_OFFLINE": "0"},
            offline_required=0,
        )


def test_guard_cleanup_failure_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(harness.shutil, "rmtree", lambda *_args, **_kwargs: None)
    result = harness._run_bounded_child(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        timeout=5,
        env={"PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(ROOT / "perseus.py")},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["cleanup_failed"] is True


def test_seccomp_contains_nested_python_s_descendant(tmp_path, monkeypatch):
    nested = "import socket; socket.socket()"
    command = [
        "/bin/sh",
        "-c",
        f"exec {shlex.quote(sys.executable)} -S -c {shlex.quote(nested)}",
    ]
    result = harness._run_bounded_child(
        command,
        cwd=tmp_path,
        timeout=5,
        env={**dict(os.environ), "PERSEUS_OFFLINE": "1"},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["offline_sandbox"] == "seccomp"
    assert result["offline_report"] is None


    _enable_test_only_disk_guard(monkeypatch)
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
        "persisted_state": {"path": "state.json", "sha256": harness._sha_bytes(b"persisted")},
    }
    command = [sys.executable, "-c", f"open('state.json', 'wb').write(b'persisted'); print({json.dumps(receipt, sort_keys=True)!r})"]
    spec = {"name": "perseus-vault", "path": "adapter.bin", "command": command, "version": "v1"}
    manifest = {"state": "available", "sha256": digest, "version": "v1"}
    checked = harness._run_adapter(tmp_path, spec, manifest, harness._CHILD_LIMITS, monitor_dir=tmp_path / "out", query=query)
    assert checked["status"] == "passed"
    receipt["persisted_state"]["sha256"] = "0" * 64
    bad = {**spec, "command": [sys.executable, "-c", f"open('state.json', 'wb').write(b'persisted'); print({json.dumps(receipt, sort_keys=True)!r})"]}
    checked = harness._run_adapter(tmp_path, bad, manifest, harness._CHILD_LIMITS, monitor_dir=tmp_path / "out2", query=query)
    assert checked["status"] == "blocked"
    assert checked["reason"] == "adapter_operation_receipt_invalid"


def test_render_binds_execution_to_manifest_digest(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
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


def test_successful_detached_descendant_closing_pipes_is_reaped(tmp_path):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")
    marker = tmp_path / "closed-pipes-descendant-leaked"
    grandchild = (
        "import os,pathlib,time; os.setsid(); os.close(1); os.close(2); "
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
    time.sleep(1.0)
    assert not marker.exists()


def test_detached_descendant_cannot_escape_after_leader_exit(tmp_path):
    if os.name != "posix" or not sys.platform.startswith("linux"):
        pytest.skip("Linux process-death containment is required")
    marker = tmp_path / "detached-descendant-leaked"
    ready = tmp_path / "detached-descendant-ready"
    grandchild = (
        "import os,pathlib,time; os.setsid(); os.environ.clear(); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(0.8); "
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    parent = (
        "import os,pathlib,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"deadline=time.monotonic()+1.0; "
        f"\nwhile time.monotonic() < deadline and not pathlib.Path({str(ready)!r}).exists(): time.sleep(0.01); "
        "os._exit(0)"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        timeout=2.0,
        env=dict(os.environ),
        require_process_containment=True,
    )
    containment_configured = bool(
        os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_ROOT")
        or os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_BROKER")
    )
    if containment_configured:
        assert result["status"] == "passed"
    else:
        assert result["status"] in {"blocked", "failed"}
    time.sleep(1.0)
    assert not marker.exists()


def test_exec_detached_descendant_requires_cgroup_containment(tmp_path):
    if os.name != "posix" or not sys.platform.startswith("linux"):
        pytest.skip("Linux cgroup containment is required")
    marker = tmp_path / "exec-detached-descendant-leaked"
    ready = tmp_path / "exec-detached-descendant-ready"
    exec_code = (
        "import pathlib,time; "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(0.8); "
        f"pathlib.Path({str(marker)!r}).write_text('leaked')"
    )
    grandchild = (
        "import os,pathlib,sys,time; os.setsid(); "
        "fd=int(os.environ['PERSEUS_ACCEPTANCE_TOKEN_FD']); os.close(fd); "
        f"os.execve(sys.executable, [sys.executable, '-c', {exec_code!r}], {{}})"
    )
    parent = (
        "import pathlib,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        f"deadline=time.monotonic()+1.0; "
        f"\nwhile time.monotonic() < deadline and not pathlib.Path({str(ready)!r}).exists(): time.sleep(0.01); "
        "__import__('os')._exit(0)"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        timeout=2.0,
        env=dict(os.environ),
        require_process_containment=True,
    )
    containment_configured = bool(
        os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_ROOT")
        or os.environ.get("PERSEUS_ACCEPTANCE_CGROUP_BROKER")
    )
    if containment_configured:
        assert result["status"] == "passed"
    else:
        assert result["status"] in {"blocked", "failed"}
    time.sleep(1.0)
    assert not marker.exists()


def test_reparented_descendant_without_independent_proof_is_unowned(monkeypatch):
    reparented_pid = 424243
    snapshot = {
        reparented_pid: {
            "pid": reparented_pid,
            "state": "S",
            "ppid": os.getpid(),
            "pgid": reparented_pid,
            "start_time": 99,
        },
    }
    monkeypatch.setattr(harness, "_process_snapshot", lambda: snapshot)
    known = {}
    result = harness._owned_processes(
        424242,
        {os.getpid(): {"pid": os.getpid(), "ppid": 1, "pgid": os.getpid(), "start_time": 1}},
        known,
        None,
    )
    assert reparented_pid not in result


def test_non_linux_cleanup_without_tree_primitive_fails_closed(monkeypatch):
    class FakeProcess:
        pid = 424242
        returncode = 0

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(harness.os, "name", "nt")
    monkeypatch.setattr(harness.sys, "platform", "win32")
    assert harness._terminate_process_group(
        FakeProcess(),
        {"pid": 424242, "start_time": 1},
        {},
        "run-token",
    ) is False


def test_windows_cleanup_fails_closed_without_job_object(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 424242
        returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(harness.os, "name", "nt")
    monkeypatch.setattr(harness.sys, "platform", "win32")
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    assert harness._terminate_process_group(
        FakeProcess(),
        {"pid": 424242, "start_time": 424242},
        {},
        "run-token",
    ) is False
    assert calls == []


def test_non_linux_posix_cleanup_fails_closed_without_identity_primitive(monkeypatch):
    calls = []

    class FakeProcess:
        pid = 424242
        returncode = None

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def poll(self):
            return self.returncode

    def fake_killpg(pgid, sig):
        calls.append((pgid, sig))

    monkeypatch.setattr(harness.os, "name", "posix")
    monkeypatch.setattr(harness.sys, "platform", "darwin")
    monkeypatch.setattr(harness.os, "killpg", fake_killpg)
    assert harness._terminate_process_group(
        FakeProcess(),
        {"pid": 424242, "pgid": 424242, "start_time": 424242},
        {},
        "run-token",
    ) is False
    assert calls == []


def test_cleanup_refuses_pid_reuse_or_unverified_pgid_signal(monkeypatch):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")

    class FakeProcess:
        pid = 424242
        returncode = 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(
        harness,
        "_process_identity",
        lambda _pid: {"pid": 424242, "state": "S", "ppid": 1, "pgid": 999, "start_time": 2},
    )
    monkeypatch.setattr(harness.os, "killpg", lambda *_args: pytest.fail("unverified PGID was signaled"))
    assert harness._terminate_process_group(
        FakeProcess(), {"pid": 424242, "pgid": 424242, "start_time": 1}, {}, "run-token"
    ) is False


def test_owned_descendant_requires_current_ancestry_or_token_before_pgid_change(monkeypatch):
    calls = []
    monkeypatch.setattr(
        harness,
        "_process_identity",
        lambda _pid: {"pid": 424242, "state": "S", "ppid": 1, "pgid": 999, "start_time": 1},
    )
    monkeypatch.setattr(harness.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    identity = {
        "pid": 424242,
        "pgid": 424242,
        "start_time": 1,
        "owned_by_ancestry": 1,
    }
    assert harness._signal_owned(identity, signal.SIGTERM, None, trusted_pgid=424242) is False
    assert calls == []


def test_owned_descendant_with_current_ancestry_can_change_pgid(monkeypatch):
    calls = []
    identities = {
        424242: {"pid": 424242, "state": "S", "ppid": 424241, "pgid": 999, "start_time": 1},
        424241: {"pid": 424241, "state": "S", "ppid": 1, "pgid": 424241, "start_time": 2},
    }
    monkeypatch.setattr(harness, "_process_identity", identities.get)
    monkeypatch.setattr(harness.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    identity = {
        "pid": 424242,
        "pgid": 424242,
        "start_time": 1,
        "owned_by_ancestry": 1,
        "ownership_root_pid": 424241,
        "ownership_root_start_time": 2,
    }
    leader = {"pid": 424241, "start_time": 2}
    assert harness._signal_owned(identity, signal.SIGTERM, None, trusted_pgid=424242, leader_identity=leader) is True
    assert calls == [(424242, signal.SIGTERM)]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, 0, -1, "1", None, []])
def test_child_resource_bounds_reject_malformed_values_before_spawn(monkeypatch, tmp_path, bad):
    def fail_if_spawned(*_args, **_kwargs):
        raise AssertionError("Popen must not run for an invalid resource bound")

    monkeypatch.setattr(harness.subprocess, "Popen", fail_if_spawned)
    with pytest.raises(harness.AcceptanceError, match="resource"):
        harness._run_bounded_child(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path,
            timeout=5,
            env=dict(os.environ),
            resource_limits={
                "cpu_seconds": bad,
                "address_space_bytes": 1024,
                "file_bytes": 1024,
            },
        )


def test_python_s_child_cannot_catch_seccomp_and_pass_without_owned_report(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    code = (
        "import socket; "
        "\ntry: socket.socket().connect_ex(('203.0.113.9', 9))\n"
        "except BaseException: pass\n"
        "print('completed')"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-S", "-c", code],
        cwd=tmp_path,
        timeout=5,
        env={**dict(os.environ), "PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["offline_sandbox"] == "seccomp"
    assert result["offline_report"] is None


def test_nested_non_python_launcher_cannot_hide_zero_attempt_network_failure(tmp_path):
    nested = (
        "import socket; "
        "\ntry: socket.socket().connect_ex(('203.0.113.9', 9))\n"
        "except BaseException: pass\n"
        "print('completed')"
    )
    command = ["/bin/sh", "-c", f"exec {shlex.quote(sys.executable)} -S -c {shlex.quote(nested)}"]
    result = harness._run_bounded_child(
        command,
        cwd=tmp_path,
        timeout=5,
        env={"PERSEUS_OFFLINE": "1"},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["offline_sandbox"] == "seccomp"
    assert result["offline_report"] is None


def test_offline_guard_setup_failure_returns_bounded_blocked_result(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_prepare_offline_guard", lambda *_args: (_ for _ in ()).throw(OSError("/private/secret")))
    result = harness._run_bounded_child(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        timeout=5,
        env={"PERSEUS_OFFLINE": "1"},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "offline_guard_unavailable"
    assert "/private/secret" not in json.dumps(result)


def test_disk_limit_includes_child_cwd_even_when_not_declared_separately(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    code = "open('cwd-write', 'wb').write(b'x' * 4096)"
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(tmp_path / "unrelated-root",),
        disk_limit_bytes=1024,
    )
    assert result["status"] == "resource_limit"


def test_disk_growth_charge_is_conservative_against_host_free_space_noise():
    assert harness._disk_growth_charge(128, 3_229_485_565) == 3_229_485_565


def test_filesystem_growth_sums_all_devices():
    assert harness._filesystem_growth_bytes({1: 100, 2: 100}, {1: 90, 2: 70}) == 40


def test_new_filesystem_device_blocks_aggregate_observation(tmp_path, monkeypatch):
    snapshots = iter(
        [
            harness._FilesystemSnapshot({1: 100}, complete=True),
            harness._FilesystemSnapshot({1: 90, 2: 100}, complete=True),
        ]
    )
    monkeypatch.setattr(harness, "_filesystem_free_bytes", lambda: next(snapshots))
    budget = harness._AggregateResourceBudget((tmp_path,), cpu_seconds=30, memory_mb=512, disk_bytes=1024)
    result = harness._run_bounded_child(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(tmp_path,),
        disk_limit_bytes=1024,
        aggregate_budget=budget,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "filesystem_observation_unavailable"


def test_monitor_size_is_order_independent_for_nested_roots(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    (child / "payload").write_bytes(b"x" * 800)
    parent_first = harness._monitor_size((parent, child))
    child_first = harness._monitor_size((child, parent))
    assert child_first == parent_first


def test_aggregate_resource_budget_charges_persistent_child_workspace_growth(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    budget = harness._AggregateResourceBudget((tmp_path,), cpu_seconds=30, memory_mb=512, disk_bytes=6000)
    first = harness._run_bounded_child(
        [sys.executable, "-c", "open('first-write', 'wb').write(b'x' * 800)"],
        cwd=tmp_path, timeout=5, env=dict(os.environ), monitor_dirs=(tmp_path,),
        disk_limit_bytes=6000, aggregate_budget=budget,
    )
    second = harness._run_bounded_child(
        [sys.executable, "-c", "open('second-write', 'wb').write(b'x' * 800)"],
        cwd=tmp_path, timeout=5, env=dict(os.environ), monitor_dirs=(tmp_path,),
        disk_limit_bytes=6000, aggregate_budget=budget,
    )
    assert first["status"] == "passed"
    assert second["status"] == "resource_limit"
    assert second["aggregate_resource"]["disk_growth_bytes_observed"] > 1024


def test_parent_artifact_reads_are_bounded(tmp_path):
    (tmp_path / "large.bin").write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    with pytest.raises(harness.AcceptanceError, match="read"):
        harness._secure_file_bytes(tmp_path, "large.bin")


def test_staged_adapter_bytes_cannot_be_mutated_during_execution(tmp_path):
    bundle = tmp_path / "upgrade.json"
    bundle.write_text("upgrade-v1", encoding="utf-8")
    digest = harness._sha_bytes(bundle.read_bytes())
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "upgrade",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha(""),
        "result": "passed",
        "persisted_state": {"path": "state.json", "sha256": harness._sha_bytes(b"persisted")},
    }
    code = (
        "import json,os,pathlib; "
        "pathlib.Path(os.environ['PERSEUS_BUNDLE_PATH']).write_text('tampered'); "
        f"print({json.dumps(receipt, sort_keys=True)!r})"
    )
    checked = harness._check_bundle(
        tmp_path,
        {"path": "upgrade.json", "version": "v1", "sha256": digest, "command": [sys.executable, "-c", code]},
        "upgrade",
        execute=True,
    )
    assert checked["status"] == "blocked"


def test_adapter_runtime_bytes_cannot_be_mutated_during_execution(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    artifact = tmp_path / "adapter.bin"
    artifact.write_text("adapter-v1", encoding="utf-8")
    digest = harness._sha_bytes(artifact.read_bytes())
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "perseus-vault",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha(""),
        "result": "passed",
        "persisted_state": {"path": "state.json", "sha256": harness._sha_bytes(b"persisted")},
    }
    code = (
        "import pathlib; "
        f"pathlib.Path({str(runtime)!r}).write_bytes(b'tampered-runtime'); "
        "pathlib.Path('state.json').write_bytes(b'persisted'); "
        f"print({json.dumps(receipt, sort_keys=True)!r})"
    )
    checked = harness._run_adapter(
        tmp_path,
        {
            "name": "perseus-vault",
            "path": "adapter.bin",
            "version": "v1",
            "command": [sys.executable, "-c", code],
        },
        {"state": "available", "sha256": digest, "version": "v1"},
        harness._CHILD_LIMITS,
        monitor_dir=tmp_path / "out",
    )
    assert checked["status"] == "blocked"
    assert checked["reason"] == "adapter_operation_failed"
    assert checked["runtime_post_sha256"] == harness._sha_bytes((ROOT / "perseus.py").read_bytes())


def test_adapter_runtime_must_match_initial_manifest_digest(tmp_path):
    runtime = tmp_path / "perseus.py"
    initial = (ROOT / "perseus.py").read_bytes()
    runtime.write_bytes(initial)
    runtime_digest = harness._sha_bytes(initial)
    artifact = tmp_path / "adapter.bin"
    artifact.write_text("adapter-v1", encoding="utf-8")
    artifact_digest = harness._sha_bytes(artifact.read_bytes())
    runtime.write_bytes(b"substituted-runtime")
    checked = harness._run_adapter(
        tmp_path,
        {
            "name": "perseus-vault",
            "path": "adapter.bin",
            "version": "v1",
            "command": [sys.executable, "-c", "pass"],
        },
        {"state": "available", "sha256": artifact_digest, "version": "v1"},
        harness._CHILD_LIMITS,
        runtime_digest=runtime_digest,
        monitor_dir=tmp_path / "out",
    )
    assert checked["status"] == "blocked"
    assert checked["reason"] == "adapter_digest_mismatch"


def test_incomplete_runtime_manifest_returns_bounded_acceptance_error(tmp_path, monkeypatch):
    real = harness._artifact_manifest(ROOT, harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json"))
    monkeypatch.setattr(harness, "_artifact_manifest", lambda *_args: [real[0]])
    with pytest.raises(harness.AcceptanceError, match="manifest"):
        harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")


def test_workload_query_has_an_executed_and_bound_flow_cell(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    query_cell = report["flow"]["workload_query"]
    assert query_cell["status"] == "passed"
    assert query_cell["query_sha256"] == report["workload_query_digest"]
    assert query_cell["workload_digest"] == report["workload_digest"]


def test_zero_restart_count_is_explicitly_bound_without_restart_execution(tmp_path):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    data["workload"]["restart_count"] = 0
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    report = harness.run_acceptance(ROOT, fixture_path=fixture_path, output_dir=tmp_path / "evidence")
    restart = report["flow"]["restart_recovery"]
    assert restart["status"] == "not_run"
    assert restart["restart_count"] == 0
    assert restart["query_sha256"] == report["workload_query_digest"]
    assert restart["workload_digest"] == report["workload_digest"]


def test_restore_binding_includes_restored_state_digest(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    restored = report["flow"]["backup_restore"]
    assert restored["result_binding"]
    assert restored["result_binding"]["restored_digest"] == restored["restored_digest"]


def test_flow_commitment_binds_complete_publication_projection(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    render = report["flow_commitment"]["perseus_render"]
    assert render["offline_report"]
    assert render["offline_guard"]["enforced"] is True
    assert "startup_ms_observed" in render
    assert "output_sha256" in render
    assert report["flow_commitment"]["backup_restore"]["result_binding"]["binding_sha256"]
    assert report["resource_contract"]["resource_observations_commitment"]


def _recommit_report_for_test(report):
    manifest_core = {
        "fixture_id": report["fixture_id"],
        "workload_digest": report["workload_digest"],
        "artifacts": report["artifacts"],
        "claims_ceiling": report["claims_ceiling"],
        "upgrade": report["upgrade"],
        "rollback": report["rollback"],
    }
    report["manifest_commitment"] = harness._sha(manifest_core)
    report["report_commitment"] = harness._sha({key: report[key] for key in harness._REPORT_CORE_KEYS})
    stable_flow = {key: harness._stable_projection(value) for key, value in report["flow"].items()}
    stable_core = {key: report[key] for key in harness._REPORT_CORE_KEYS}
    stable_core["flow_commitment"] = stable_flow
    stable_core["flow_projection_commitment"] = harness._sha(stable_flow)
    stable_core.pop("resource_envelope", None)
    stable_resource = dict(harness._stable_projection(stable_core["resource_contract"]))
    stable_resource.pop("resource_observations_commitment", None)
    stable_core["resource_contract"] = stable_resource
    report["stable_report_commitment"] = harness._sha(stable_core)
    report["evidence_digest"] = harness._sha({
        "manifest_commitment": report["manifest_commitment"],
        "stable_report_commitment": report["stable_report_commitment"],
        "workload_digest": report["workload_digest"],
        "workload_query_digest": report["workload_query_digest"],
        "artifacts": report["artifacts"],
        "flow": harness._stable_projection(report["flow"]),
        "backup_digest": report["flow"].get("backup_restore", {}).get("backup_digest"),
        "network": harness._stable_projection(report["network"]),
        "claims_ceiling": report["claims_ceiling"],
        "claims": report["claims"],
        "upgrade": harness._stable_projection(report["upgrade"]),
        "rollback": harness._stable_projection(report["rollback"]),
        "negative_results": report["negative_results"],
    })


def test_report_commitment_requires_fixture_binding(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    with pytest.raises(harness.AcceptanceError, match="expected fixture"):
        harness._validate_report_commitments(report)


def test_report_validator_requires_exact_network_flow_projection(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    removable = next(
        name for name, cell in mutated["flow"].items()
        if isinstance(cell, dict) and cell.get("status") == "passed" and name in mutated["network"]["children"]
    )
    mutated["network"]["children"].pop(removable)
    mutated["network"]["child_guards"].pop(removable)
    mutated["network"]["child_attempts"] = [
        attempt
        for child in mutated["network"]["children"].values()
        for attempt in child["attempts"]
    ]
    _recommit_report_for_test(mutated)
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    with pytest.raises(harness.AcceptanceError, match="network child projection"):
        harness._validate_report_commitments(mutated, expected_fixture=fixture)


def test_report_validator_rejects_minimal_recommitted_passed_operation(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    mutated["upgrade"] = {"status": "passed", "checked": True}
    for item in mutated["negative_results"]:
        if item["cell"] == "upgrade":
            item.update(status="passed", reason="operation_completed")
    _recommit_report_for_test(mutated)
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    with pytest.raises(harness.AcceptanceError, match="upgrade operation"):
        harness._validate_report_commitments(mutated, expected_fixture=fixture)


def test_report_validation_rejects_mutated_raw_flow(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    original_status = mutated["flow"]["perseus_render"]["status"]
    mutated["flow"]["perseus_render"]["status"] = "passed" if original_status != "passed" else "failed"
    with pytest.raises(harness.AcceptanceError, match="flow commitment"):
        harness._validate_report_commitments(mutated, expected_fixture=_fixture())


def test_report_validation_rejects_recommitted_raw_resource_mutation(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    mutated["flow"]["perseus_render"]["cpu_seconds_observed"] = 999
    mutated["flow"]["perseus_render"]["raw_flow"] = "SENSITIVE_FLOW_PAYLOAD"
    mutated["flow_commitment"] = {
        key: harness._public_projection(value)
        for key, value in mutated["flow"].items()
        if isinstance(value, dict)
    }
    mutated["flow_projection_commitment"] = harness._sha(mutated["flow_commitment"])
    with pytest.raises(harness.AcceptanceError, match="commitment|resource|observations"):
        harness._validate_report_commitments(mutated, expected_fixture=_fixture())


def test_report_validation_rejects_recommitted_semantic_resource_forgery(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    mutated["resource_envelope"]["cpu_seconds_observed"] = 999999.0
    flow_projection = {
        key: harness._public_projection(value)
        for key, value in mutated["flow"].items()
    }
    mutated["flow_commitment"] = flow_projection
    mutated["flow_projection_commitment"] = harness._sha(flow_projection)
    mutated["resource_contract"]["resource_observations_commitment"] = harness._sha({
        "resource_envelope": mutated["resource_envelope"],
        "flow": flow_projection,
    })
    report_core_keys = (
        "schema_version", "status", "fixture_id", "platform", "artifacts",
        "flow_commitment", "flow_projection_commitment", "network", "resource_contract",
        "resource_envelope", "upgrade", "rollback", "negative_results", "claims",
        "manifest_commitment", "workload_digest", "workload_query_digest",
    )
    mutated["report_commitment"] = harness._sha({key: mutated[key] for key in report_core_keys})
    with pytest.raises(harness.AcceptanceError, match="resource|report"):
        harness._validate_report_commitments(mutated, expected_fixture=_fixture())


def test_report_validation_rejects_recommitted_mutated_resource_limits(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    mutated["resource_contract"]["limits"]["cpu_seconds"] = 999999
    mutated["resource_envelope"]["cpu_seconds_observed"] = 999998.0
    flow_projection = {
        key: harness._public_projection(value)
        for key, value in mutated["flow"].items()
    }
    mutated["flow_commitment"] = flow_projection
    mutated["flow_projection_commitment"] = harness._sha(flow_projection)
    mutated["resource_contract"]["resource_observations_commitment"] = harness._sha({
        "resource_envelope": mutated["resource_envelope"],
        "flow": flow_projection,
    })
    mutated["report_commitment"] = harness._sha({
        key: mutated[key]
        for key in harness._REPORT_CORE_KEYS
    })
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    with pytest.raises(harness.AcceptanceError, match="fixture-bound"):
        harness._validate_report_commitments(mutated, expected_fixture=fixture)


def test_report_validation_rejects_recommitted_raw_network_attempt(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    raw_attempt = {
        "operation": "raw-operation",
        "destination": "SENSITIVE_NETWORK_DESTINATION",
        "outcome": "blocked",
    }
    child_report = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": [],
        "attempts_truncated": False,
        "blocked_attempts": 0,
        "allowed_local_attempts": 0,
    }
    mutated["network"] = {
        "policy": "deny_all",
        "attempts": [raw_attempt],
        "child_attempts": [],
        "children": {"forged-child": child_report},
        "child_guards": {
            "forged-child": {
                "enforced": True,
                "boundary": "seccomp",
                "report_present": True,
                "telemetry": "parent_derived",
            },
        },
        "attempts_truncated": False,
        "expected_blocked": [raw_attempt],
        "unexpected_attempts": [],
        "child_probe": {
            "status": "passed",
            "exit_code": 0,
            "report": {
                "blocked": True,
                "destination": "sha256:" + "0" * 64,
                "report": {**child_report, "attempts": [raw_attempt], "blocked_attempts": 1},
            },
        },
        "status": "passed",
    }
    mutated["report_commitment"] = harness._sha({
        key: mutated[key]
        for key in harness._REPORT_CORE_KEYS
    })
    with pytest.raises(harness.AcceptanceError, match="network"):
        harness._validate_report_commitments(mutated, expected_fixture=_fixture())


def _valid_passed_network_for_test(*, attempts=None, probe_attempts=None, child_report=None, probe_blocked=True):
    if attempts is None:
        attempts = [{"operation": "sha256:" + "1" * 64, "destination": "sha256:" + "2" * 64, "outcome": "blocked"}]
    if probe_attempts is None:
        probe_attempts = list(attempts)
    if child_report is None:
        child_report = {
            "active": True,
            "policy": "deny_all_non_loopback",
            "attempts": [],
            "attempts_truncated": False,
            "blocked_attempts": 0,
            "allowed_local_attempts": 0,
        }
    probe_report = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": probe_attempts,
        "attempts_truncated": False,
        "blocked_attempts": sum(item["outcome"] == "blocked" for item in probe_attempts),
        "allowed_local_attempts": sum(item["outcome"] == "allowed_local" for item in probe_attempts),
    }
    return {
        "policy": "deny_all",
        "attempts": attempts,
        "child_attempts": [],
        "children": {"child": child_report},
        "child_guards": {
            "child": {
                "enforced": True,
                "boundary": "seccomp",
                "report_present": True,
                "telemetry": "parent_derived",
            },
        },
        "attempts_truncated": False,
        "expected_blocked": [item for item in attempts if item["outcome"] == "blocked"],
        "unexpected_attempts": [item for item in attempts if item["outcome"] not in {"blocked", "allowed_local"}],
        "child_probe": {
            "status": "passed",
            "exit_code": 0,
            "report": {
                "blocked": probe_blocked,
                "destination": "sha256:" + "3" * 64,
                "report": probe_report,
            },
        },
        "status": "passed",
    }


def test_passed_network_requires_an_actual_blocked_probe_attempt():
    network = _valid_passed_network_for_test(attempts=[], probe_attempts=[], probe_blocked=True)
    with pytest.raises(harness.AcceptanceError, match="network"):
        harness._validate_report_network_semantics(network)


def test_deny_all_network_rejects_allowed_local_attempts():
    attempt = {"operation": "sha256:" + "1" * 64, "destination": "sha256:" + "2" * 64, "outcome": "allowed_local"}
    network = _valid_passed_network_for_test(attempts=[attempt], probe_attempts=[attempt], probe_blocked=False)
    with pytest.raises(harness.AcceptanceError, match="network"):
        harness._validate_report_network_semantics(network)


def test_passed_network_requires_untruncated_child_reports():
    child_report = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": [],
        "attempts_truncated": True,
        "blocked_attempts": 0,
        "allowed_local_attempts": 0,
    }
    network = _valid_passed_network_for_test(child_report=child_report)
    with pytest.raises(harness.AcceptanceError, match="network"):
        harness._validate_report_network_semantics(network)


def test_aggregate_status_rejects_inconclusive_required_cell():
    flow = {
        "required": {"status": "timeout", "reason": "child_timeout"},
        "available": {"status": "passed"},
    }
    network = {"status": "passed"}
    report = {
        "status": "passed",
        "platform": {"status": "passed"},
        "upgrade": {"status": "passed"},
        "rollback": {"status": "passed"},
        "negative_results": [],
    }
    with pytest.raises(harness.AcceptanceError, match="aggregate status"):
        harness._validate_report_status(report, flow, network)


def test_aggregate_status_rejects_incomplete_resource_observation():
    report = {
        "status": "passed",
        "platform": {"status": "passed"},
        "upgrade": {"status": "passed"},
        "rollback": {"status": "passed"},
        "negative_results": [],
        "resource_envelope": {
            "aggregate_children": {"status": "filesystem_observation_unavailable"},
        },
    }
    with pytest.raises(harness.AcceptanceError, match="aggregate status"):
        harness._validate_report_status(report, {}, {"status": "passed"})


def test_resource_validation_binds_passed_flow_limits(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    flow = json.loads(json.dumps(report["flow"]))
    flow["perseus_render"]["resource_limits"]["cpu_seconds"] += 1
    with pytest.raises(harness.AcceptanceError, match="fixture-bound"):
        harness._validate_report_resource_semantics(
            report["resource_contract"],
            report["resource_envelope"],
            flow,
            expected_limits=fixture["platform"]["resource_limits"],
        )


def test_resource_validation_requires_limits_for_passed_flow(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    fixture = harness._load_fixture(ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json")
    flow = json.loads(json.dumps(report["flow"]))
    del flow["perseus_render"]["resource_limits"]
    flow["perseus_render"]["status"] = "passed"
    with pytest.raises(harness.AcceptanceError, match="fixture-bound|resource limits"):
        harness._validate_report_resource_semantics(
            report["resource_contract"],
            report["resource_envelope"],
            flow,
            expected_limits=fixture["platform"]["resource_limits"],
        )


def test_backup_restore_rejects_boolean_render_exit_code(tmp_path):
    offline_report = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": [],
        "attempts_truncated": False,
        "blocked_attempts": 0,
        "allowed_local_attempts": 0,
    }
    flow = {
        "backup_restore": {
            "status": "passed",
            "digest_match": True,
            "post_digest_match": True,
            "render": {
                "status": "passed",
                "exit_code": False,
                "offline_report": offline_report,
                "offline_guard": {
                    "enforced": True,
                    "boundary": "seccomp",
                    "report_present": True,
                    "telemetry": "parent_derived",
                },
                "process_containment": {
                    "enforced": True,
                    "boundary": "cgroup_broker",
                    "cleanup_verified": True,
                },
            },
        },
    }
    with pytest.raises(harness.AcceptanceError, match="backup restore"):
        harness._validate_report_flow_semantics(flow)


def test_network_nonpassed_status_still_rejects_raw_attempt_metadata():
    with pytest.raises(harness.AcceptanceError, match="network"):
        harness._validate_report_network_semantics({
            "status": "timeout",
            "policy": "deny_all",
            "attempts": [{"operation": "raw", "destination": "secret.example", "outcome": "blocked"}],
            "attempts_truncated": False,
            "expected_blocked": [],
            "unexpected_attempts": [],
            "child_attempts": [],
            "children": {},
            "child_guards": {},
            "child_probe": {"status": "timeout", "exit_code": None, "report": None},
        })


def test_passed_flow_requires_parent_derived_offline_guard_and_report():
    with pytest.raises(harness.AcceptanceError, match="offline (guard|report)"):
        harness._validate_report_flow_semantics({
            "render": {
                "status": "passed",
                "exit_code": 0,
                "process_containment": {
                    "enforced": True,
                    "boundary": "cgroup_broker",
                    "cleanup_verified": True,
                },
            },
        })


def test_resource_validation_requires_complete_fixture_bound_observations():
    limits = {"cpu_seconds": 3, "memory_mb": 4, "disk_mb": 5}
    envelope = {
        "cpu_seconds_observed": 0.1,
        "peak_rss_mb_observed": 0.2,
        "disk_growth_bytes_observed": 3,
    }
    with pytest.raises(harness.AcceptanceError, match="resource"):
        harness._validate_report_resource_semantics(
            {"limits": limits}, envelope, {}, expected_limits=limits
        )


def test_report_serializes_public_flow_projection_only(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    serialized = (tmp_path / "evidence" / "report.json").read_text(encoding="utf-8")
    assert "stdout" not in report["flow"]
    assert "stderr" not in report["flow"]
    assert "stdout" not in serialized
    assert "stderr" not in serialized


def test_report_validation_rejects_recommitted_status_contract_forgery(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    mutated["flow"]["perseus_render"]["status"] = "passed"
    mutated["flow"]["perseus_render"]["exit_code"] = 7
    mutated["flow"]["perseus_render"]["offline_guard"] = {
        "enforced": False,
        "boundary": None,
        "report_present": False,
        "telemetry": "unavailable",
    }
    flow_projection = {
        key: harness._public_projection(value)
        for key, value in mutated["flow"].items()
    }
    mutated["flow_commitment"] = flow_projection
    mutated["flow_projection_commitment"] = harness._sha(flow_projection)
    mutated["resource_contract"]["resource_observations_commitment"] = harness._sha({
        "resource_envelope": mutated["resource_envelope"],
        "flow": flow_projection,
    })
    report_core_keys = (
        "schema_version", "status", "fixture_id", "platform", "artifacts",
        "flow_commitment", "flow_projection_commitment", "network", "resource_contract",
        "resource_envelope", "upgrade", "rollback", "negative_results", "claims",
        "manifest_commitment", "workload_digest", "workload_query_digest",
    )
    mutated["report_commitment"] = harness._sha({key: mutated[key] for key in report_core_keys})
    with pytest.raises(harness.AcceptanceError, match="status|commitment|stable|evidence|zero exit|offline|containment"):
        harness._validate_report_commitments(mutated, expected_fixture=_fixture())


def test_report_validation_rejects_recommitted_aggregate_status_forgery(tmp_path):
    report = harness.run_acceptance(ROOT, output_dir=tmp_path / "evidence")
    mutated = json.loads(json.dumps(report))
    mutated["status"] = "failed" if report["status"] != "failed" else "passed"
    mutated["report_commitment"] = harness._sha({
        key: mutated[key]
        for key in harness._REPORT_CORE_KEYS
    })
    with pytest.raises(harness.AcceptanceError, match="aggregate status"):
        harness._validate_report_commitments(mutated, expected_fixture=_fixture())


def test_public_projection_hashes_unknown_scalar_payload():
    payload = "SENSITIVE_FLOW_PAYLOAD"
    projected = harness._public_projection({"status": "passed", "raw_flow": payload})
    assert projected["status"] == "passed"
    assert projected["raw_flow"].startswith("sha256:")
    assert projected["raw_flow"] != payload
    assert payload not in json.dumps(projected, sort_keys=True)


def test_negative_result_missing_reason_never_normalizes_success():
    assert harness._negative_result_reason({"status": "blocked"}) == "operation_blocked"
    assert harness._negative_result_reason({"status": "failed"}) == "operation_failed"
    assert harness._negative_result_reason({"status": "unavailable"}) == "operation_unavailable"


def test_public_fixture_errors_are_bounded_and_private(tmp_path, capsys):
    missing = tmp_path / "private-fixture-name.json"
    assert harness.main(["--repo", str(ROOT), "--fixture", str(missing), "--json"]) == 1
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert "No such file" not in output
    assert "fixture_load_failed" in output


def test_library_fixture_load_errors_are_bounded(tmp_path):
    missing = tmp_path / "private-customer-token.json"
    with pytest.raises(harness.AcceptanceError) as exc_info:
        harness._load_fixture(missing)
    text = str(exc_info.value)
    assert str(tmp_path) not in text
    assert "No such file" not in text


def test_fixture_rejects_unbounded_public_identifier(tmp_path):
    data = json.loads((ROOT / "benchmark" / "disconnected_acceptance" / "fixture.json").read_text())
    data["fixture_id"] = "X" * 10000
    fixture_path = tmp_path / "oversized-fixture.json"
    fixture_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(harness.AcceptanceError):
        harness._load_fixture(fixture_path)


def test_forged_pipe_report_cannot_become_authoritative(tmp_path):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def activate_offline_mode(): pass\n"
        "def offline_network_report(): return {"
        "'active': True, 'policy': 'deny_all_non_loopback', 'attempts': [], "
        "'attempts_truncated': False, 'blocked_attempts': 0, "
        "'allowed_local_attempts': 0}\n"
        "def deactivate_offline_mode(): pass\n",
        encoding="utf-8",
    )
    forged = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": [{"operation": "SENSITIVE_MARKER", "destination": "SENSITIVE_MARKER", "outcome": "blocked"}],
        "attempts_truncated": False,
        "blocked_attempts": 1,
        "allowed_local_attempts": 0,
    }
    code = (
        "import os,sitecustomize; "
        f"sitecustomize._write_frame('report', {forged!r}); "
        "sitecustomize._write_frame('complete', {'pid': os.getpid(), 'start_time': sitecustomize._start_time(), 'sandbox_violation': False}); os._exit(0)"
    )
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout=5,
        env={"PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert result.get("reason") == "offline_report_invalid"
    assert "SENSITIVE_MARKER" not in json.dumps(result)


def test_offline_report_requires_parent_nonce_in_each_frame():
    pid = os.getpid()
    identity = harness._process_identity(pid)
    assert identity is not None
    expected_report = harness._parent_derived_offline_report([sys.executable, "-c", "print('ok')"])
    read_fd, write_fd = os.pipe()
    frames = [
        {"kind": "report", "value": expected_report},
        {
            "kind": "complete",
            "value": {"pid": pid, "start_time": identity["start_time"], "sandbox_violation": False},
        },
    ]
    raw = b"".join(
        len(json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()).to_bytes(4, "big")
        + json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
        for frame in frames
    )
    try:
        os.write(write_fd, raw)
    finally:
        os.close(write_fd)
    try:
        assert harness._read_offline_report(
            read_fd,
            "parent-nonce",
            expected_pid=pid,
            expected_start_time=identity["start_time"],
            expected_report=expected_report,
        ) is None
    finally:
        os.close(read_fd)


def test_offline_reader_output_is_not_authoritative(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def activate_offline_mode(): pass\n"
        "def offline_network_report(): return {"
        "'active': True, 'policy': 'deny_all_non_loopback', 'attempts': [], "
        "'attempts_truncated': False, 'blocked_attempts': 0, "
        "'allowed_local_attempts': 0}\n"
        "def deactivate_offline_mode(): pass\n",
        encoding="utf-8",
    )
    forged = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": [{"operation": "SENSITIVE_READER", "destination": "SENSITIVE_READER", "outcome": "blocked"}],
        "attempts_truncated": False,
        "blocked_attempts": 1,
        "allowed_local_attempts": 0,
    }
    monkeypatch.setattr(harness, "_read_offline_report", lambda *args, **kwargs: forged)
    argv = [sys.executable, "-c", "print('ok')"]
    result = harness._run_bounded_child(
        argv,
        cwd=tmp_path,
        timeout=5,
        env={"PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    expected = harness._sanitize_offline_report(harness._parent_derived_offline_report(argv))
    assert result["status"] == "blocked"
    assert result["offline_report"] is None
    assert result["offline_report"] != expected
    assert "SENSITIVE_READER" not in json.dumps(result)


def test_report_reader_deadline_handles_descendant_holding_write_fd():
    if os.name != "posix":
        pytest.skip("pipe inheritance is POSIX-specific")
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        time.sleep(2.0)
        os.close(write_fd)
        os._exit(0)
    os.close(write_fd)
    identity = harness._process_identity(child)
    assert identity is not None
    started = time.monotonic()
    try:
        result = harness._read_offline_report(
            read_fd,
            expected_token="0" * 32,
            expected_pid=child,
            expected_start_time=identity["start_time"],
            expected_report=harness._parent_derived_offline_report([sys.executable, "-c", "pass"]),
        )
        elapsed = time.monotonic() - started
    finally:
        os.close(read_fd)
        os.waitpid(child, 0)
    assert result is None
    assert elapsed < 1.0


def test_cleanup_does_not_signal_descendants_after_leader_pid_reuse(monkeypatch):
    if os.name != "posix":
        pytest.skip("process-group assertion is POSIX-specific")

    class FakeProcess:
        pid = 424242
        returncode = 0

        def wait(self, timeout=None):
            return 0

    baseline = {111: {"pid": 111, "state": "S", "ppid": 1, "pgid": 111, "start_time": 10}}
    unrelated = {"pid": 900, "state": "S", "ppid": 1, "pgid": 900, "start_time": 20, "owned_by_ancestry": 1}

    def discover(_leader_pid, received_baseline, known, _run_token, _token_fd=None):
        if received_baseline != baseline:
            known[unrelated["pid"]] = dict(unrelated)
        return known

    def identity(pid):
        if pid == 424242:
            return {"pid": pid, "state": "S", "ppid": 1, "pgid": 777, "start_time": 999}
        if pid == 900:
            return dict(unrelated)
        return None

    monkeypatch.setattr(harness, "_owned_processes", discover)
    monkeypatch.setattr(harness, "_process_identity", identity)
    monkeypatch.setattr(harness.os, "killpg", lambda *_args: pytest.fail("unrelated reused-PID group was signaled"))
    assert harness._terminate_process_group(
        FakeProcess(),
        {"pid": 424242, "pgid": 424242, "start_time": 1},
        {},
        "run-token",
        baseline=baseline,
    ) is False


def test_python_s_cannot_bypass_filesystem_containment(tmp_path):
    allowed = tmp_path / "allowed"
    escape = tmp_path / "escape"
    allowed.mkdir()
    escape.mkdir()
    escaped = escape / "outside.bin"
    code = f"open({str(escaped)!r}, 'wb').write(b'escape')"
    result = harness._run_bounded_child(
        [sys.executable, "-S", "-c", code],
        cwd=allowed,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(allowed,),
        disk_limit_bytes=1024,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "filesystem_sandbox_unavailable"
    assert not escaped.exists()


def test_landlock_unavailable_blocks_native_ctypes_write(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    escape = tmp_path / "escape"
    allowed.mkdir()
    escape.mkdir()
    escaped = escape / "outside.bin"
    code = (
        "import ctypes, os; "
        f"fd=ctypes.CDLL(None).open({str(escaped).encode()!r}, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600); "
        "os.write(fd, b'escape'); os.close(fd)"
    )
    monkeypatch.setattr(harness, "_landlock_supported", lambda: False)
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=allowed,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(allowed,),
        disk_limit_bytes=1024,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "filesystem_sandbox_unavailable"
    assert not escaped.exists()


def test_observation_root_is_not_a_child_write_root(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    workspace = tmp_path / "workspace"
    observed_repo = tmp_path / "observed-repo"
    workspace.mkdir()
    observed_repo.mkdir()
    target = observed_repo / "claims.json"
    code = f"open({str(target)!r}, 'wb').write(b'forged')"
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=workspace,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(workspace, observed_repo),
        disk_limit_bytes=1024,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "filesystem_sandbox_unavailable"
    assert not target.exists()


def test_filesystem_guard_validates_link_destination(tmp_path):
    allowed = tmp_path / "allowed"
    escape = tmp_path / "escape"
    allowed.mkdir()
    escape.mkdir()
    source = allowed / "source.txt"
    destination = escape / "link.txt"
    source.write_text("source", encoding="utf-8")
    code = f"import os; os.symlink({str(source)!r}, {str(destination)!r})"
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=allowed,
        timeout=5,
        env=dict(os.environ),
        monitor_dirs=(allowed,),
        disk_limit_bytes=1024,
    )
    assert result["status"] == "blocked"
    assert not destination.exists()


def test_bounded_reader_stops_an_unbounded_output_stream(tmp_path):
    code = "import os; chunk=b'x' * 8192; [os.write(1, chunk) for _ in iter(int, 1)]"
    started = time.monotonic()
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout=5,
        env=dict(os.environ),
    )
    elapsed = time.monotonic() - started
    assert result["status"] == "resource_limit"
    assert result["stdout_truncated"] is True
    assert result["output_limit_exceeded"] is True
    assert result["stdout_total_bytes"] <= harness._MAX_CHILD_OUTPUT_BYTES + 8192
    assert elapsed < 3


def test_disk_budget_charges_writes_outside_declared_roots(tmp_path, monkeypatch):
    _enable_test_only_disk_guard(monkeypatch)
    workspace = tmp_path / "workspace"
    declared = tmp_path / "declared"
    escape = tmp_path / "escape"
    workspace.mkdir()
    declared.mkdir()
    escape.mkdir()
    escaped_file = escape / "outside.bin"
    runtime = tmp_path / "runtime.py"
    runtime.write_text(
        "def activate_offline_mode(): pass\n"
        "def offline_network_report(): return {"
        "'active': True, 'policy': 'deny_all_non_loopback', 'attempts': [], "
        "'attempts_truncated': False, 'blocked_attempts': 0, "
        "'allowed_local_attempts': 0}\n"
        "def deactivate_offline_mode(): pass\n",
        encoding="utf-8",
    )
    code = f"open({str(escaped_file)!r}, 'wb').write(b'x' * 8192)"
    budget = harness._AggregateResourceBudget((declared,), cpu_seconds=30, memory_mb=512, disk_bytes=1024)
    result = harness._run_bounded_child(
        [sys.executable, "-c", code],
        cwd=workspace,
        timeout=5,
        env={
            "PERSEUS_OFFLINE": "1",
            "PERSEUS_OFFLINE_RUNTIME": str(runtime),
        },
        monitor_dirs=(declared,),
        disk_limit_bytes=1024,
        aggregate_budget=budget,
        offline_required=True,
    )
    assert result["status"] in {"blocked", "resource_limit"}
    assert result["disk_growth_bytes_observed"] > 0
    assert result["aggregate_resource"]["disk_growth_bytes_observed"] > budget.disk_limit
    assert not escaped_file.exists()


def test_operation_receipt_rejects_immutable_staged_persisted_state(tmp_path):
    staged = tmp_path / ".perseus-immutable" / "perseus.py"
    staged.parent.mkdir()
    staged.write_bytes(b"immutable-runtime")
    digest = harness._sha_bytes(b"bundle")
    receipt = {
        "schema_version": "perseus-disconnected-operation/v1",
        "action": "upgrade",
        "version": "v1",
        "artifact_sha256": digest,
        "query_sha256": harness._sha("query"),
        "result": "passed",
        "persisted_state": {
            "path": ".perseus-immutable/perseus.py",
            "sha256": harness._sha_bytes(staged.read_bytes()),
        },
    }
    with pytest.raises(harness.AcceptanceError, match="receipt"):
        harness._parse_operation_receipt(
            json.dumps(receipt),
            action="upgrade",
            version="v1",
            artifact_sha256=digest,
            query="query",
            workspace=tmp_path,
        )


def test_staged_argv_rejects_unbound_script_path(tmp_path):
    staged_artifact = tmp_path / ".perseus-immutable" / "adapter.bin"
    staged_runtime = tmp_path / ".perseus-immutable" / "perseus.py"
    staged_artifact.parent.mkdir()
    staged_artifact.write_text("adapter", encoding="utf-8")
    staged_runtime.write_text("runtime", encoding="utf-8")
    outside = tmp_path / "alternate.py"
    outside.write_text("alternate", encoding="utf-8")
    with pytest.raises(harness.AcceptanceError, match="operation"):
        harness._resolve_staged_argv(
            [sys.executable, str(outside)],
            root=tmp_path,
            artifact_path="adapter.bin",
            staged_artifact=staged_artifact,
            staged_runtime=staged_runtime,
        )


def test_operation_command_executes_staged_bundle_path(tmp_path):
    runtime = tmp_path / "perseus.py"
    runtime.write_bytes((ROOT / "perseus.py").read_bytes())
    bundle = tmp_path / "upgrade.py"
    bundle.write_text(
        "import json, os, pathlib\n"
        "pathlib.Path('state.json').write_bytes(b'staged' if '.perseus-immutable' in __file__ else b'unstaged')\n"
        "print(json.dumps({'schema_version': 'perseus-disconnected-operation/v1', 'action': 'upgrade', 'version': 'v1', 'artifact_sha256': os.environ['PERSEUS_BUNDLE_SHA256'], 'query_sha256': '" + harness._sha("") + "', 'result': 'passed', 'persisted_state': {'path': 'state.json', 'sha256': '" + harness._sha_bytes(b"staged") + "'}}, sort_keys=True))\n",
        encoding="utf-8",
    )
    digest = harness._sha_bytes(bundle.read_bytes())
    checked = harness._check_bundle(
        tmp_path,
        {"path": "upgrade.py", "version": "v1", "sha256": digest, "command": [sys.executable, str(bundle)]},
        "upgrade",
        execute=True,
    )
    assert checked["status"] == "passed"
    assert checked["operation_persisted_state_sha256"] == harness._sha_bytes(b"staged")


def test_offline_guard_pipe_setup_failure_cleans_guard_dir(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.py"
    runtime.write_text("def activate_offline_mode(): pass\n", encoding="utf-8")

    def fail_pipe():
        raise OSError("pipe denied")

    monkeypatch.setattr(harness.os, "pipe", fail_pipe)
    with pytest.raises(OSError, match="pipe denied"):
        harness._prepare_offline_guard(
            [sys.executable, "-c", "pass"],
            tmp_path,
            {"PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        )
    assert not list(tmp_path.glob(".perseus-offline-*"))


def test_limiter_setup_failure_cleans_offline_guard(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.py"
    runtime.write_text("def activate_offline_mode(): pass\n", encoding="utf-8")

    def fail_limiter(*_args, **_kwargs):
        raise OSError("limiter denied")

    monkeypatch.setattr(harness, "_child_resource_limiter", fail_limiter)
    result = harness._run_bounded_child(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        timeout=5,
        env={"PERSEUS_OFFLINE": "1", "PERSEUS_OFFLINE_RUNTIME": str(runtime)},
        offline_required=True,
    )
    assert result["status"] == "blocked"
    assert not list(tmp_path.glob(".perseus-offline-*"))
