#!/usr/bin/env python3
"""Run the deterministic, claim-bounded disconnected acceptance bundle (#997).

The default fixture intentionally records absent Vault/Ledger artifacts as
unavailable rather than fabricating a cross-product success. A real deployment
can provide those artifacts and versioned upgrade/rollback bundles through the
same manifest contract.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping


_SCHEMA = "perseus-disconnected-acceptance/v1"
_REPORT_SCHEMA = "perseus-disconnected-report/v1"
_REQUIRED_FIXTURE_KEYS = frozenset({"schema_version", "fixture_id", "platform", "artifacts", "workload", "claims_ceiling"})
_CHILD_LIMITS = {"cpu_seconds": 30, "address_space_bytes": 512 * 1024 * 1024, "file_bytes": 16 * 1024 * 1024}
_MAX_CHILD_OUTPUT_BYTES = 64 * 1024
_MAX_CHILD_ERROR_BYTES = 64 * 1024
_ALLOWED_PROBE_OUTCOMES = frozenset({"blocked", "allowed_local"})


class AcceptanceError(ValueError):
    """Raised when the acceptance fixture or evidence contract is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: Any) -> str:
    return _sha_bytes(_json(value).encode("utf-8"))


def _safe_relative_path(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise AcceptanceError("artifact path must be a non-empty string")
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise AcceptanceError("artifact path escapes the fixture boundary")
    path = root / rel
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise AcceptanceError("artifact path contains a symlink")
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AcceptanceError("artifact path escapes the fixture boundary") from exc
    return path


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceError(f"fixture could not be loaded: {exc}") from exc
    if not isinstance(value, Mapping) or set(value) != _REQUIRED_FIXTURE_KEYS or value.get("schema_version") != _SCHEMA:
        raise AcceptanceError("fixture shape or schema is invalid")
    platform = value.get("platform")
    if not isinstance(platform, Mapping) or platform.get("network_policy") != "deny_all":
        raise AcceptanceError("fixture must declare deny_all network policy")
    limits = platform.get("resource_limits")
    if not isinstance(limits, Mapping) or set(limits) != {"cpu_seconds", "memory_mb", "disk_mb"}:
        raise AcceptanceError("fixture resource_limits are incomplete")
    for key in ("cpu_seconds", "memory_mb", "disk_mb"):
        if isinstance(limits[key], bool) or not isinstance(limits[key], (int, float)) or limits[key] <= 0:
            raise AcceptanceError("fixture resource_limits must be positive finite numbers")
    workload = value.get("workload")
    if not isinstance(workload, Mapping) or not isinstance(workload.get("source"), str) or not workload["source"].strip():
        raise AcceptanceError("fixture workload source is required")
    claims = value.get("claims_ceiling")
    required_claims = {"local_offline_capable", "iron_bank_submitted", "iron_bank_assessed", "customer_platform_deployable", "ato_il5_il6"}
    if not isinstance(claims, Mapping) or set(claims) != required_claims or claims.get("ato_il5_il6") != "not_claimed":
        raise AcceptanceError("claims ceiling is incomplete or overclaims")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AcceptanceError("fixture must declare artifacts")
    names: set[str] = set()
    paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or set(artifact) - {"name", "path", "required", "sbom"}:
            raise AcceptanceError("artifact manifest entries are invalid")
        if not isinstance(artifact.get("name"), str) or not artifact["name"].strip() or artifact["name"] in names:
            raise AcceptanceError("artifact names must be unique non-empty strings")
        if not isinstance(artifact.get("path"), str):
            raise AcceptanceError("artifact path must be a string")
        rel = Path(artifact["path"])
        if rel.is_absolute() or ".." in rel.parts or str(rel) in paths:
            raise AcceptanceError("artifact paths must be safe and unique")
        if not isinstance(artifact.get("required", False), bool):
            raise AcceptanceError("artifact required must be boolean")
        if artifact.get("sbom") is not None and not isinstance(artifact.get("sbom"), str):
            raise AcceptanceError("artifact sbom path must be a string or null")
        names.add(artifact["name"])
        paths.add(str(rel))
    return dict(value)


def _runtime_module(repo_root: Path) -> Any:
    path = repo_root / "perseus.py"
    spec = importlib.util.spec_from_file_location("perseus_disconnected_runtime", path)
    if spec is None or spec.loader is None:
        raise AcceptanceError("could not load the Perseus runtime artifact")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact_manifest(repo_root: Path, fixture: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = []
    for entry in fixture["artifacts"]:
        rel = Path(entry["path"])
        path = _safe_relative_path(repo_root, entry["path"])
        required = bool(entry.get("required", False))
        if path.is_symlink():
            raise AcceptanceError(f"artifact is a symlink: {rel}")
        if not path.exists():
            if required:
                raise AcceptanceError(f"required artifact is unavailable: {rel}")
            result.append({"name": entry["name"], "path": str(rel).replace(os.sep, "/"), "state": "unavailable", "required": required, "sha256": None, "version": None, "sbom": {"state": "unavailable"}})
            continue
        if not path.is_file():
            if required:
                raise AcceptanceError(f"required artifact is not a regular file: {rel}")
            result.append({"name": entry["name"], "path": str(rel).replace(os.sep, "/"), "state": "unavailable", "required": required, "sha256": None, "version": None, "sbom": {"state": "not_a_file"}})
            continue
        digest = _sha_bytes(path.read_bytes())
        version = (repo_root / "VERSION").read_text(encoding="utf-8").strip() if entry["name"] == "perseus" and (repo_root / "VERSION").is_file() else None
        sbom_ref = entry.get("sbom")
        sbom_path = _safe_relative_path(repo_root, sbom_ref) if isinstance(sbom_ref, str) and sbom_ref else None
        if sbom_path is not None and sbom_path.is_symlink():
            raise AcceptanceError(f"SBOM reference is a symlink: {sbom_ref}")
        sbom = {"state": "available", "sha256": _sha_bytes(sbom_path.read_bytes())} if sbom_path is not None and sbom_path.is_file() else {"state": "unavailable"}
        if sbom_ref and sbom["state"] != "available" and required:
            raise AcceptanceError(f"required SBOM reference is unavailable: {sbom_ref}")
        result.append({"name": entry["name"], "path": str(rel).replace(os.sep, "/"), "state": "available", "required": required, "sha256": digest, "version": version, "sbom": sbom})
    return result


def _child_resource_limiter() -> Any:
    if os.name != "posix":
        return None

    def apply_limits() -> None:
        limits = (
            (resource.RLIMIT_CPU, _CHILD_LIMITS["cpu_seconds"]),
            (resource.RLIMIT_AS, _CHILD_LIMITS["address_space_bytes"]),
            (resource.RLIMIT_FSIZE, _CHILD_LIMITS["file_bytes"]),
        )
        for kind, value in limits:
            # A disconnected acceptance run must fail closed when a declared
            # containment limit cannot be installed; swallowing this error
            # would turn an observation into an unenforced claim.
            resource.setrlimit(kind, (value, value))

    return apply_limits


def _bounded_reader(stream: Any, limit: int, result: dict[str, Any], key: str) -> None:
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if sum(len(item) for item in chunks) < limit:
            remaining = limit - sum(len(item) for item in chunks)
            chunks.append(chunk[:remaining])
    result[f"{key}_bytes"] = b"".join(chunks)
    result[f"{key}_total_bytes"] = total
    result[f"{key}_truncated"] = total > limit


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def _run_bounded_child(argv: list[str], *, cwd: Path, timeout: float, env: Mapping[str, str]) -> dict[str, Any]:
    """Run a bounded child, owning its process group and output drains."""
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": dict(env),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _child_resource_limiter()
    process = subprocess.Popen(argv, **kwargs)
    captured: dict[str, Any] = {}
    stdout_thread = threading.Thread(target=_bounded_reader, args=(process.stdout, _MAX_CHILD_OUTPUT_BYTES, captured, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_bounded_reader, args=(process.stderr, _MAX_CHILD_ERROR_BYTES, captured, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    status = "passed"
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        status = "timeout"
        _terminate_process_group(process)
    stdout_thread.join(timeout=1.0)
    stderr_thread.join(timeout=1.0)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        _terminate_process_group(process)
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
    stdout = captured.get("stdout_bytes", b"")
    stderr = captured.get("stderr_bytes", b"")
    if status != "timeout" and process.returncode != 0:
        status = "failed"
    return {
        "status": status,
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "stdout_prefix_bytes": len(stdout),
        "stderr_prefix_bytes": len(stderr),
        "stdout_truncated": bool(captured.get("stdout_truncated", False)),
        "stderr_truncated": bool(captured.get("stderr_truncated", False)),
    }


def _validate_resource_envelope(envelope: Mapping[str, Any], fixture: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, Mapping):
        raise AcceptanceError("resource envelope is invalid")
    limits = fixture["platform"]["resource_limits"]
    checks = (
        ("cpu_seconds_observed", float(limits["cpu_seconds"])),
        ("peak_rss_mb_observed", float(limits["memory_mb"])),
        ("disk_growth_bytes_observed", float(limits["disk_mb"]) * 1024 * 1024),
    )
    for key, ceiling in checks:
        value = envelope.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > ceiling:
            raise AcceptanceError(f"resource envelope exceeds fixture ceiling: {key}")
    return dict(envelope)


def _check_bundle(root: Path, spec: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(spec, Mapping) or set(spec) != {"path", "version", "sha256"}:
        return {"status": "blocked", "checked": False, "reason": f"{label} bundle contract is invalid"}
    try:
        path = _safe_relative_path(root, spec["path"])
        expected = spec["sha256"]
        if not isinstance(spec["version"], str) or not spec["version"] or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise AcceptanceError(f"{label} bundle digest/version is invalid")
        if path.is_symlink() or not path.is_file():
            raise AcceptanceError(f"{label} bundle is unavailable")
        actual = _sha_bytes(path.read_bytes())
        if actual != expected.lower():
            raise AcceptanceError(f"{label} bundle digest mismatch")
        return {"status": "passed", "checked": True, "path": str(Path(spec["path"])).replace(os.sep, "/"), "version": spec["version"], "sha256": actual}
    except (OSError, TypeError, ValueError, AcceptanceError) as exc:
        return {"status": "blocked", "checked": False, "reason": str(exc)}


def _parse_child_probe_json(text: str) -> dict[str, Any]:
    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant: {value}")
    try:
        value = json.loads(text, parse_constant=reject_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AcceptanceError("offline child probe returned malformed JSON") from exc
    if not isinstance(value, Mapping) or set(value) != {"blocked", "destination", "report"} or value.get("blocked") is not True or not isinstance(value.get("destination"), str):
        raise AcceptanceError("offline child probe envelope is invalid")
    report = value.get("report")
    required = {"active", "policy", "attempts", "attempts_truncated", "blocked_attempts", "allowed_local_attempts"}
    if not isinstance(report, Mapping) or set(report) != required or report.get("active") is not True or report.get("policy") != "deny_all_non_loopback":
        raise AcceptanceError("offline child probe report is invalid")
    if not isinstance(report["attempts"], list) or not isinstance(report["attempts_truncated"], bool):
        raise AcceptanceError("offline child probe attempts are invalid")
    for attempt in report["attempts"]:
        if not isinstance(attempt, Mapping) or set(attempt) != {"operation", "destination", "outcome"}:
            raise AcceptanceError("offline child probe attempt is invalid")
        if not all(isinstance(attempt[key], str) for key in ("operation", "destination", "outcome")) or attempt["outcome"] not in _ALLOWED_PROBE_OUTCOMES:
            raise AcceptanceError("offline child probe attempt values are invalid")
    if any(isinstance(report[key], bool) or not isinstance(report[key], int) or report[key] < 0 for key in ("blocked_attempts", "allowed_local_attempts")):
        raise AcceptanceError("offline child probe counters are invalid")
    return dict(value)


def _run_render(repo_root: Path, source: str, state_dir: Path, *, attempt: str) -> dict[str, Any]:
    source_path = state_dir / f"workload-{attempt}.md"
    source_path.write_text(source, encoding="utf-8")
    started = time.perf_counter()
    env = dict(os.environ)
    env.pop("PERSEUS_ALLOW_DANGEROUS", None)
    env["PERSEUS_HOME"] = str(state_dir / "home")
    result = _run_bounded_child(
        [sys.executable, str(repo_root / "perseus.py"), "--offline", "render", str(source_path)],
        cwd=repo_root,
        timeout=60,
        env=env,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    output = result["stdout"].encode("utf-8", errors="replace")
    status = "passed" if result["status"] == "passed" and "@date" not in result["stdout"] and not result["stdout_truncated"] and not result["stderr_truncated"] else "failed"
    return {
        "attempt": attempt,
        "status": status,
        "exit_code": result["exit_code"],
        "output_sha256": _sha_bytes(output),
        "output_bytes": result["stdout_prefix_bytes"],
        "output_truncated": result["stdout_truncated"],
        "log_bytes": result["stdout_prefix_bytes"] + result["stderr_prefix_bytes"],
        "log_truncated": result["stdout_truncated"] or result["stderr_truncated"],
        "startup_ms_observed": elapsed_ms,
        "resource_limits": dict(_CHILD_LIMITS),
    }


def _resource_envelope(before_cpu: float, before_rss: int, before_disk: int, output_dir: Path, started: float) -> dict[str, Any]:
    after_cpu = time.process_time()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    after_disk = shutil.disk_usage(output_dir).used
    return {
        "cpu_seconds_observed": round(max(0.0, after_cpu - before_cpu), 6),
        "peak_rss_mb_observed": round(float(usage.ru_maxrss) / (1024 if sys.platform != "darwin" else 1), 3),
        "disk_growth_bytes_observed": max(0, after_disk - before_disk),
        "wall_seconds_observed": round(max(0.0, time.perf_counter() - started), 6),
        "measurement_status": "observed_with_host_metrics",
    }


def run_acceptance(repo_root: Path | str, *, fixture_path: Path | str | None = None, output_dir: Path | str | None = None) -> dict[str, Any]:
    """Run the offline Perseus slice and emit a bounded cross-product report."""
    root = Path(repo_root).resolve()
    fixture = _load_fixture(Path(fixture_path).resolve() if fixture_path else root / "benchmark" / "disconnected_acceptance" / "fixture.json")
    observed_platform = {"os": "linux" if sys.platform.startswith("linux") else sys.platform, "python": f"{sys.version_info.major}.{sys.version_info.minor}"}
    fixture_platform = fixture["platform"]
    platform_check = {
        "expected": {"os": fixture_platform.get("os"), "python": fixture_platform.get("python")},
        "observed": observed_platform,
        "status": "passed" if all(observed_platform[key] == fixture_platform.get(key) for key in observed_platform) else "failed",
    }
    owned_output = output_dir is None
    temp_context = tempfile.TemporaryDirectory(prefix="perseus-disconnected-") if owned_output else None
    out = Path(temp_context.name).resolve() if temp_context else Path(output_dir).resolve()
    if not owned_output and out.exists() and any(out.iterdir()):
        raise AcceptanceError("evidence output directory must be fresh and empty")
    out.mkdir(parents=True, exist_ok=True)
    state_dir = out / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    before_cpu = time.process_time()
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    before_disk = shutil.disk_usage(out).used
    started = time.perf_counter()
    artifacts = _artifact_manifest(root, fixture)
    perseus_artifact = next(item for item in artifacts if item["name"] == "perseus")
    if perseus_artifact["state"] != "available":
        raise AcceptanceError("required Perseus artifact is unavailable")
    flow = {
        "perseus_render": _run_render(root, fixture["workload"]["source"], state_dir, attempt="initial"),
        "vault": {"status": "unavailable", "reason": "fixture declares no local Vault artifact or command"},
        "ledger": {"status": "unavailable", "reason": "fixture declares no local Ledger artifact or command"},
    }
    flow["restart_recovery"] = _run_render(root, fixture["workload"]["source"], state_dir, attempt="restart")
    backup = out / "backup-state"
    shutil.copytree(state_dir, backup, dirs_exist_ok=True)
    backup_digest = _sha(_sorted_files(backup))
    shutil.rmtree(state_dir)
    shutil.copytree(backup, state_dir)
    restore = _run_render(root, fixture["workload"]["source"], state_dir, attempt="restore")
    flow["backup_restore"] = {"status": "passed" if restore["status"] == "passed" else "failed", "backup_digest": backup_digest, "restored": state_dir.exists(), "render": restore}
    upgrade_spec = fixture["workload"].get("upgrade_bundle")
    rollback_spec = fixture["workload"].get("rollback_bundle")
    upgrade = _check_bundle(root, upgrade_spec, "upgrade") if isinstance(upgrade_spec, Mapping) else {"status": "not_run", "reason": "fixture does not declare a second versioned bundle", "checked": False}
    rollback = _check_bundle(root, rollback_spec, "rollback") if isinstance(rollback_spec, Mapping) else {"status": "not_run", "reason": "fixture does not declare a second versioned bundle", "checked": False}
    probe = _run_bounded_child(
        [sys.executable, str(root / "perseus.py"), "--offline", "offline-probe", "https://example.invalid/disconnected-probe", "--json"],
        cwd=root,
        timeout=15,
        env=dict(os.environ),
    )
    if probe["status"] != "passed" or probe["exit_code"] != 0 or probe["stdout_truncated"] or probe["stderr_truncated"]:
        raise AcceptanceError(f"offline child probe failed: {probe['status']}")
    probe_result = _parse_child_probe_json(probe["stdout"])
    network_probe = probe_result["report"]
    blocked = [item for item in network_probe["attempts"] if item["outcome"] == "blocked"]
    unexpected = [item for item in network_probe["attempts"] if item["outcome"] not in {"blocked", "allowed_local"}]
    network = {
        "policy": "deny_all",
        "attempts": network_probe["attempts"],
        "attempts_truncated": network_probe.get("attempts_truncated", False),
        "expected_blocked": blocked,
        "unexpected_attempts": unexpected,
        "child_probe": {"status": "passed", "exit_code": probe["exit_code"], "report": probe_result},
        "status": "passed" if blocked and not unexpected and not network_probe.get("attempts_truncated", False) else "failed",
    }
    resource_envelope = _validate_resource_envelope(_resource_envelope(before_cpu, before_rss, before_disk, out, started), fixture)
    negative_results = [
        {"cell": "vault", "status": "unavailable", "reason": flow["vault"]["reason"]},
        {"cell": "ledger", "status": "unavailable", "reason": flow["ledger"]["reason"]},
        {"cell": "upgrade", "status": upgrade["status"], "reason": upgrade["reason"]},
        {"cell": "rollback", "status": rollback["status"], "reason": rollback["reason"]},
    ]
    claims = {
        "local_offline_capable": "observed" if platform_check["status"] == "passed" and flow["perseus_render"]["status"] == "passed" and network["status"] == "passed" else "not_established",
        "iron_bank_submitted": "not_claimed",
        "iron_bank_assessed": "not_claimed",
        "customer_platform_deployable": "not_established",
        "ato_il5_il6": "not_claimed",
    }
    failed_cells = [flow["perseus_render"], flow["restart_recovery"], flow["backup_restore"], network, upgrade, rollback]
    status = "failed" if platform_check["status"] != "passed" or any(item.get("status") in {"failed", "blocked"} for item in failed_cells) else "partial" if any(item["status"] in {"unavailable", "not_run"} for item in negative_results) else "passed"
    workload_digest = _sha(fixture["workload"])
    manifest_core = {
        "fixture_id": fixture["fixture_id"],
        "workload_digest": workload_digest,
        "artifacts": artifacts,
        "claims_ceiling": fixture["claims_ceiling"],
        "upgrade": upgrade,
        "rollback": rollback,
    }
    manifest_commitment = _sha(manifest_core)
    flow_commitment = {
        key: {
            "status": value.get("status"),
            "exit_code": value.get("exit_code"),
            "output_sha256": value.get("output_sha256"),
            "output_bytes": value.get("output_bytes"),
            "output_truncated": value.get("output_truncated"),
            "backup_digest": value.get("backup_digest"),
        }
        for key, value in flow.items()
        if isinstance(value, Mapping)
    }
    report_core = {
        "schema_version": _REPORT_SCHEMA,
        "status": status,
        "fixture_id": fixture["fixture_id"],
        "platform": platform_check,
        "artifacts": artifacts,
        "flow_commitment": flow_commitment,
        "network": network,
        "resource_contract": {"limits": fixture["platform"]["resource_limits"], "measurement_status": resource_envelope.get("measurement_status")},
        "upgrade": upgrade,
        "rollback": rollback,
        "negative_results": negative_results,
        "claims": claims,
        "manifest_commitment": manifest_commitment,
        "workload_digest": workload_digest,
    }
    report_commitment = _sha(report_core)
    evidence_digest = _sha({
        "manifest_commitment": manifest_commitment,
        "report_commitment": report_commitment,
        "workload_digest": workload_digest,
        "artifacts": artifacts,
        "flow": flow_commitment,
        "backup_digest": flow.get("backup_restore", {}).get("backup_digest"),
        "network": network,
        "claims_ceiling": fixture["claims_ceiling"],
        "claims": claims,
        "upgrade": upgrade,
        "rollback": rollback,
        "negative_results": negative_results,
    })
    report = {
        **report_core,
        "flow": flow,
        "resource_envelope": resource_envelope,
        "manifest_commitment": manifest_commitment,
        "report_commitment": report_commitment,
        "evidence_digest": evidence_digest,
    }
    manifest = {**manifest_core, "manifest_commitment": manifest_commitment, "report_commitment": report_commitment}
    (out / "manifest.json").write_text(_json(manifest) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if temp_context is not None:
        # Keep the return value useful while avoiding a temp-directory path in
        # public evidence. The caller receives the report, not host paths.
        temp_context.cleanup()
    return report


def _sorted_files(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        result.append({"path": str(path.relative_to(root)).replace(os.sep, "/"), "sha256": _sha_bytes(path.read_bytes()), "size": path.stat().st_size})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline disconnected acceptance harness.")
    parser.add_argument("--repo", default=".", help="Perseus repository root")
    parser.add_argument("--fixture", default=None, help="Acceptance fixture JSON")
    parser.add_argument("--output", default=None, help="Evidence output directory")
    parser.add_argument("--json", action="store_true", help="Print the full report")
    parser.add_argument("--allow-partial", action="store_true", help="Return success for a partial report with explicitly unavailable cells")
    args = parser.parse_args(argv)
    try:
        report = run_acceptance(args.repo, fixture_path=args.fixture, output_dir=args.output)
    except (OSError, TypeError, ValueError, AcceptanceError) as exc:
        print(f"DISCONNECTED ACCEPTANCE BLOCKED: {exc}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True) if args.json or not args.output else f"DISCONNECTED ACCEPTANCE {report['status'].upper()}: {report['evidence_digest']}")
    return 0 if report["status"] == "passed" or (report["status"] == "partial" and args.allow_partial) else 1


if __name__ == "__main__":
    raise SystemExit(main())
