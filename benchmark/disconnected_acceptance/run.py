#!/usr/bin/env python3
"""Run the deterministic, claim-bounded disconnected acceptance bundle (#997).

The default fixture intentionally records absent Vault/Ledger artifacts as
unavailable rather than fabricating a cross-product success. A real deployment
can provide those artifacts and versioned upgrade/rollback bundles through the
same manifest contract.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import math
import os
import re
import resource
import shutil
import signal
import stat
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
_PLATFORM_KEYS = frozenset({"os", "python", "network_policy", "resource_limits"})
_RESOURCE_LIMIT_KEYS = frozenset({"cpu_seconds", "memory_mb", "disk_mb"})
_WORKLOAD_KEYS = frozenset({"source", "query", "restart_count", "upgrade_bundle", "rollback_bundle"})
_BUNDLE_KEYS = frozenset({"path", "version", "sha256"})
_BUNDLE_KEYS_WITH_COMMAND = _BUNDLE_KEYS | {"command"}
_ARTIFACT_KEYS = frozenset({"name", "path", "required", "sbom", "command", "version"})
_SEMANTIC_ARTIFACT_NAMES = frozenset({"perseus", "perseus-vault", "perseus-ledger"})
_OPERATION_SCHEMA = "perseus-disconnected-operation/v1"
_OPERATION_RECEIPT_KEYS = frozenset({
    "schema_version", "action", "version", "artifact_sha256", "query_sha256", "result", "persisted",
})
_CLAIMS_CEILING = {
    "local_offline_capable": "observed_only",
    "iron_bank_submitted": "not_claimed",
    "iron_bank_assessed": "not_claimed",
    "customer_platform_deployable": "not_established",
    "ato_il5_il6": "not_claimed",
}
_CHILD_LIMITS = {"cpu_seconds": 30, "address_space_bytes": 512 * 1024 * 1024, "file_bytes": 16 * 1024 * 1024}
_MAX_CHILD_OUTPUT_BYTES = 64 * 1024
_MAX_CHILD_ERROR_BYTES = 64 * 1024
_ALLOWED_PROBE_OUTCOMES = frozenset({"blocked", "allowed_local"})
_DEFAULT_QUERY = ""
_STABLE_DATE_RE = re.compile(
    rb"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?(?:\s+[A-Za-z][A-Za-z0-9_+:-]*)?\b"
)


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
    if not rel.parts or rel == Path(".") or rel.is_absolute() or ".." in rel.parts:
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


def _secure_file_bytes(root: Path, raw: Any) -> bytes:
    """Read one fixture-controlled file through no-follow directory handles."""
    path = _safe_relative_path(root, raw)
    parts = path.relative_to(root).parts
    if os.name != "posix":
        return path.read_bytes()
    base_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags = base_flags | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = base_flags | getattr(os, "O_NOFOLLOW", 0)
    current_fd = -1
    file_fd = -1
    try:
        current_fd = os.open(str(root), directory_flags)
        for part in parts[:-1]:
            next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise IsADirectoryError(str(path))
        with os.fdopen(file_fd, "rb", closefd=True) as handle:
            file_fd = -1
            return handle.read()
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise AcceptanceError("artifact path contains a symlink") from exc
        raise
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if current_fd >= 0:
            os.close(current_fd)


def _validate_command(command: Any, label: str) -> list[str]:
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise AcceptanceError(f"{label} command must be a non-empty argv list of strings")
    return list(command)


def _validate_bundle_spec(spec: Any, label: str) -> None:
    if spec is None:
        return
    if not isinstance(spec, Mapping) or set(spec) not in {_BUNDLE_KEYS, _BUNDLE_KEYS_WITH_COMMAND}:
        raise AcceptanceError(f"{label} bundle contract is invalid")
    if not isinstance(spec.get("path"), str) or not spec["path"].strip():
        raise AcceptanceError(f"{label} bundle path is invalid")
    if not isinstance(spec.get("version"), str) or not spec["version"].strip():
        raise AcceptanceError(f"{label} bundle version is invalid")
    if not isinstance(spec.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", spec["sha256"]):
        raise AcceptanceError(f"{label} bundle digest is invalid")
    if "command" in spec:
        _validate_command(spec["command"], f"{label} bundle")


def _finite_positive_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value)) and value > 0
    except (OverflowError, TypeError, ValueError):
        return False


def _load_fixture(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AcceptanceError(f"fixture could not be loaded: {exc}") from exc
    if not isinstance(value, Mapping) or set(value) != _REQUIRED_FIXTURE_KEYS or value.get("schema_version") != _SCHEMA:
        raise AcceptanceError("fixture shape or schema is invalid")
    fixture_id = value.get("fixture_id")
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise AcceptanceError("fixture_id must be a non-empty string")
    platform = value.get("platform")
    if not isinstance(platform, Mapping) or set(platform) != _PLATFORM_KEYS:
        raise AcceptanceError("fixture platform shape is invalid")
    if not all(isinstance(platform.get(key), str) and platform[key].strip() for key in ("os", "python")) or platform.get("network_policy") != "deny_all":
        raise AcceptanceError("fixture must declare deny_all network policy")
    limits = platform.get("resource_limits")
    if not isinstance(limits, Mapping) or set(limits) != _RESOURCE_LIMIT_KEYS:
        raise AcceptanceError("fixture resource_limits are incomplete")
    for key in ("cpu_seconds", "memory_mb", "disk_mb"):
        if not _finite_positive_number(limits[key]):
            raise AcceptanceError("fixture resource_limits must be positive finite numbers")
    workload = value.get("workload")
    if not isinstance(workload, Mapping) or set(workload) != _WORKLOAD_KEYS:
        raise AcceptanceError("fixture workload shape is invalid")
    if not isinstance(workload.get("source"), str) or not workload["source"].strip() or not isinstance(workload.get("query"), str) or not workload["query"].strip():
        raise AcceptanceError("fixture workload source and query are required")
    if isinstance(workload.get("restart_count"), bool) or not isinstance(workload.get("restart_count"), int) or workload["restart_count"] < 0:
        raise AcceptanceError("fixture restart_count must be a non-negative integer")
    _validate_bundle_spec(workload.get("upgrade_bundle"), "upgrade")
    _validate_bundle_spec(workload.get("rollback_bundle"), "rollback")
    claims = value.get("claims_ceiling")
    if not isinstance(claims, Mapping) or dict(claims) != _CLAIMS_CEILING:
        raise AcceptanceError("claims ceiling is incomplete or overclaims")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AcceptanceError("fixture must declare artifacts")
    names: set[str] = set()
    paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or not {"name", "path", "required", "sbom"}.issubset(set(artifact)) or set(artifact) - _ARTIFACT_KEYS:
            raise AcceptanceError("artifact manifest entries are invalid")
        if not isinstance(artifact.get("name"), str) or not artifact["name"].strip() or artifact["name"] in names:
            raise AcceptanceError("artifact names must be unique non-empty strings")
        if not isinstance(artifact.get("path"), str) or not artifact["path"].strip():
            raise AcceptanceError("artifact path must be a string")
        rel = Path(artifact["path"])
        if not rel.parts or rel == Path(".") or rel.is_absolute() or ".." in rel.parts or str(rel) in paths:
            raise AcceptanceError("artifact paths must be safe and unique")
        if not isinstance(artifact.get("required", False), bool):
            raise AcceptanceError("artifact required must be boolean")
        if artifact.get("sbom") is not None and not isinstance(artifact.get("sbom"), str):
            raise AcceptanceError("artifact sbom path must be a string or null")
        if "command" in artifact:
            _validate_command(artifact["command"], f"{artifact['name']} adapter")
        if "version" in artifact and (not isinstance(artifact["version"], str) or not artifact["version"].strip()):
            raise AcceptanceError("artifact version must be a non-empty string")
        names.add(artifact["name"])
        paths.add(str(rel))
    if names != _SEMANTIC_ARTIFACT_NAMES:
        raise AcceptanceError("fixture artifact names must match the semantic set")
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
        required = bool(entry["required"])
        adapter = {"state": "declared", "command_sha256": _sha(entry["command"])} if "command" in entry else {"state": "not_declared"}
        try:
            artifact_bytes = _secure_file_bytes(repo_root, entry["path"])
        except FileNotFoundError:
            if required:
                raise AcceptanceError("required_artifact_unavailable")
            result.append({"name": entry["name"], "path": str(rel).replace(os.sep, "/"), "state": "unavailable", "required": required, "sha256": None, "version": None, "sbom": {"state": "unavailable"}, "adapter": adapter})
            continue
        except (IsADirectoryError, NotADirectoryError):
            if required:
                raise AcceptanceError("required_artifact_not_regular")
            result.append({"name": entry["name"], "path": str(rel).replace(os.sep, "/"), "state": "unavailable", "required": required, "sha256": None, "version": None, "sbom": {"state": "not_a_file"}, "adapter": adapter})
            continue
        digest = _sha_bytes(artifact_bytes)
        version = entry.get("version")
        if entry["name"] == "perseus":
            try:
                version = _secure_file_bytes(repo_root, "VERSION").decode("utf-8").strip()
            except (OSError, UnicodeDecodeError):
                version = None
        sbom_ref = entry.get("sbom")
        sbom = {"state": "unavailable"}
        if isinstance(sbom_ref, str) and sbom_ref:
            try:
                sbom = {"state": "available", "sha256": _sha_bytes(_secure_file_bytes(repo_root, sbom_ref))}
            except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                sbom = {"state": "unavailable"}
        if sbom_ref and sbom["state"] != "available" and required:
            raise AcceptanceError("required_sbom_unavailable")
        result.append({"name": entry["name"], "path": str(rel).replace(os.sep, "/"), "state": "available", "required": required, "sha256": digest, "version": version, "sbom": sbom, "adapter": adapter})
    return result


def _child_limits_from_fixture(fixture: Mapping[str, Any]) -> dict[str, int]:
    limits = fixture["platform"]["resource_limits"]
    return {
        "cpu_seconds": max(1, int(math.ceil(float(limits["cpu_seconds"])))),
        "address_space_bytes": max(1, int(math.ceil(float(limits["memory_mb"]) * 1024 * 1024))),
        "file_bytes": max(1, int(math.ceil(float(limits["disk_mb"]) * 1024 * 1024))),
    }


def _child_resource_limiter(resource_limits: Mapping[str, int] | None = None) -> Any:
    if os.name != "posix":
        return None
    limits = dict(resource_limits or _CHILD_LIMITS)

    def apply_limits() -> None:
        limit_specs = (
            (resource.RLIMIT_CPU, limits["cpu_seconds"]),
            (resource.RLIMIT_AS, limits["address_space_bytes"]),
            (resource.RLIMIT_FSIZE, limits["file_bytes"]),
        )
        for kind, value in limit_specs:
            # A disconnected acceptance run must fail closed when a declared
            # containment limit cannot be installed; swallowing this error
            # would turn an observation into an unenforced claim.
            resource.setrlimit(kind, (value, value))

    return apply_limits


def _directory_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _stable_output_digest(value: bytes) -> str:
    """Hash output after removing only calendar-dependent rendered dates."""
    return _sha_bytes(_STABLE_DATE_RE.sub(b"<date>", value))


def _stable_output_bytes(value: bytes) -> int:
    return len(_STABLE_DATE_RE.sub(b"<date>", value))


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


def _validate_child_timeout(timeout: Any) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise AcceptanceError("child_timeout_invalid")
    try:
        value = float(timeout)
    except (OverflowError, TypeError, ValueError):
        raise AcceptanceError("child_timeout_invalid") from None
    if not math.isfinite(value) or value <= 0:
        raise AcceptanceError("child_timeout_invalid")
    return value


def _monitor_size(roots: tuple[Path, ...] | list[Path] | None) -> int:
    if not roots:
        return 0
    unique: list[Path] = []
    for raw in roots:
        root = Path(raw).resolve()
        if any(root == existing or existing in root.parents for existing in unique):
            continue
        unique.append(root)
    return sum(_directory_size(root) for root in unique)


def _is_python_argv(argv: list[str]) -> bool:
    if not argv or not isinstance(argv[0], str):
        return False
    executable = Path(argv[0]).name.casefold()
    return executable.startswith(("python", "pypy"))


def _prepare_offline_guard(argv: list[str], cwd: Path, env: Mapping[str, str]) -> tuple[dict[str, str], Path, Path]:
    """Install an inherited Python guard; reject commands it cannot contain."""
    if not _is_python_argv(argv) or any(flag in argv[1:] for flag in ("-S", "-I", "-E")):
        raise AcceptanceError("offline_guard_unavailable")
    runtime_raw = env.get("PERSEUS_OFFLINE_RUNTIME")
    if not isinstance(runtime_raw, str) or not runtime_raw or not Path(runtime_raw).is_file():
        raise AcceptanceError("offline_guard_runtime_unavailable")
    guard_dir = Path(tempfile.mkdtemp(prefix=".perseus-offline-", dir=str(cwd)))
    report_path = guard_dir / "report.json"
    guard_path = guard_dir / "sitecustomize.py"
    guard_path.write_text(
        "import atexit, importlib.util, json, os\n"
        f"_runtime = {str(Path(runtime_raw).resolve())!r}\n"
        f"_report_path = {str(report_path)!r}\n"
        "def _write(value):\n"
        "    try:\n"
        "        with open(_report_path, 'w', encoding='utf-8') as handle:\n"
        "            json.dump(value, handle, sort_keys=True, separators=(',', ':'), allow_nan=False)\n"
        "    except BaseException:\n"
        "        pass\n"
        "try:\n"
        "    _spec = importlib.util.spec_from_file_location('_perseus_offline_guard_runtime', _runtime)\n"
        "    if _spec is None or _spec.loader is None:\n"
        "        raise RuntimeError('offline runtime unavailable')\n"
        "    _module = importlib.util.module_from_spec(_spec)\n"
        "    _spec.loader.exec_module(_module)\n"
        "    _module.activate_offline_mode()\n"
        "except BaseException:\n"
        "    _write({'active': False, 'policy': 'deny_all_non_loopback', 'attempts': [], 'attempts_truncated': True, 'blocked_attempts': 0, 'allowed_local_attempts': 0})\n"
        "    os._exit(125)\n"
        "def _finish():\n"
        "    try:\n"
        "        _value = _module.offline_network_report()\n"
        "        _module.deactivate_offline_mode()\n"
        "    except BaseException:\n"
        "        _value = {'active': False, 'policy': 'deny_all_non_loopback', 'attempts': [], 'attempts_truncated': True, 'blocked_attempts': 0, 'allowed_local_attempts': 0}\n"
        "    _write(_value)\n"
        "atexit.register(_finish)\n",
        encoding="utf-8",
    )
    child_env = dict(env)
    child_env["PERSEUS_OFFLINE"] = "1"
    child_env["PERSEUS_OFFLINE_REPORT"] = str(report_path)
    old_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    return child_env, guard_dir, report_path


def _read_offline_report(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    required = {"active", "policy", "attempts", "attempts_truncated", "blocked_attempts", "allowed_local_attempts"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("active") is not True or value.get("policy") != "deny_all_non_loopback":
        return None
    if not isinstance(value["attempts"], list) or not isinstance(value["attempts_truncated"], bool):
        return None
    for attempt in value["attempts"]:
        if not isinstance(attempt, Mapping) or set(attempt) != {"operation", "destination", "outcome"}:
            return None
        if not all(isinstance(attempt[key], str) for key in ("operation", "destination", "outcome")) or attempt["outcome"] not in _ALLOWED_PROBE_OUTCOMES:
            return None
    if any(isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 0 for key in ("blocked_attempts", "allowed_local_attempts")):
        return None
    return dict(value)


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    """Terminate the owned group even when the leader already exited."""
    if os.name == "posix":
        # start_new_session=True makes the leader PID the owned PGID. Do both
        # passes unconditionally: a clean leader exit does not reap children
        # that still hold stdout/stderr open.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
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


def _run_bounded_child(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str],
    resource_limits: Mapping[str, int] | None = None,
    monitor_dir: Path | None = None,
    monitor_dirs: tuple[Path, ...] | list[Path] | None = None,
    disk_limit_bytes: int | None = None,
    offline_required: bool | None = None,
) -> dict[str, Any]:
    """Run a bounded child with owned-group and inherited offline containment."""
    timeout_value = _validate_child_timeout(timeout)
    limits = dict(resource_limits or _CHILD_LIMITS)
    if disk_limit_bytes is not None and (isinstance(disk_limit_bytes, bool) or not isinstance(disk_limit_bytes, (int, float)) or not math.isfinite(float(disk_limit_bytes)) or disk_limit_bytes <= 0):
        raise AcceptanceError("disk_limit_invalid")
    monitor_roots = tuple(monitor_dirs or (() if monitor_dir is None else (monitor_dir,)))
    require_offline = env.get("PERSEUS_OFFLINE") == "1" if offline_required is None else offline_required
    child_env = dict(env)
    guard_dir: Path | None = None
    report_path: Path | None = None
    if require_offline:
        child_env, guard_dir, report_path = _prepare_offline_guard(argv, Path(cwd), child_env)
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": child_env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = _child_resource_limiter(limits)
    before_disk = _monitor_size(monitor_roots)
    before_children = resource.getrusage(resource.RUSAGE_CHILDREN) if hasattr(resource, "RUSAGE_CHILDREN") else None
    try:
        process = subprocess.Popen(argv, **kwargs)
    except BaseException:
        if guard_dir is not None:
            shutil.rmtree(guard_dir, ignore_errors=True)
        raise
    captured: dict[str, Any] = {}
    stdout_thread = threading.Thread(target=_bounded_reader, args=(process.stdout, _MAX_CHILD_OUTPUT_BYTES, captured, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_bounded_reader, args=(process.stderr, _MAX_CHILD_ERROR_BYTES, captured, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    status = "passed"
    cleanup_failed = False
    deadline = time.monotonic() + timeout_value
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            try:
                process.wait(timeout=min(0.1, remaining) if disk_limit_bytes is not None else remaining)
            except subprocess.TimeoutExpired:
                if disk_limit_bytes is not None and _monitor_size(monitor_roots) - before_disk > float(disk_limit_bytes):
                    status = "resource_limit"
                    break
    finally:
        # This is deliberately unconditional, including a successful leader
        # exit. It prevents descendants from keeping pipes and workspaces live.
        try:
            _terminate_process_group(process)
        except BaseException:
            cleanup_failed = True
    if process.returncode is None:
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            cleanup_failed = True
    stdout_thread.join(timeout=1.0)
    stderr_thread.join(timeout=1.0)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        cleanup_failed = True
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except BaseException:
            cleanup_failed = True
    stdout_thread.join(timeout=0.25)
    stderr_thread.join(timeout=0.25)
    stdout = captured.get("stdout_bytes", b"")
    stderr = captured.get("stderr_bytes", b"")
    if disk_limit_bytes is not None and _monitor_size(monitor_roots) - before_disk > float(disk_limit_bytes) and status == "passed":
        status = "resource_limit"
    if cleanup_failed:
        status = "blocked" if require_offline else "failed"
    elif status not in {"timeout", "resource_limit"} and process.returncode != 0:
        status = "failed"
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN) if before_children is not None else None
    child_cpu = 0.0
    child_rss = 0.0
    if before_children is not None and after_children is not None:
        child_cpu = max(0.0, (after_children.ru_utime + after_children.ru_stime) - (before_children.ru_utime + before_children.ru_stime))
        child_rss = float(after_children.ru_maxrss) / (1024 if sys.platform != "darwin" else 1)
    if status == "passed" and (child_cpu > float(limits["cpu_seconds"]) or child_rss > float(limits["address_space_bytes"]) / (1024 * 1024)):
        status = "resource_limit"
    offline_report = _read_offline_report(report_path) if report_path is not None else None
    if require_offline and offline_report is None and status == "passed":
        status = "blocked"
    result = {
        "status": status,
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "stdout_prefix_bytes": len(stdout),
        "stderr_prefix_bytes": len(stderr),
        "stdout_truncated": bool(captured.get("stdout_truncated", False)),
        "stderr_truncated": bool(captured.get("stderr_truncated", False)),
        "child_cpu_seconds_observed": round(child_cpu, 6),
        "child_peak_rss_mb_observed": round(child_rss, 3),
        "resource_limits": limits,
        "offline_report": offline_report,
    }
    if guard_dir is not None:
        shutil.rmtree(guard_dir, ignore_errors=True)
    return result


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
        try:
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)) and value >= 0 and value <= ceiling
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise AcceptanceError(f"resource envelope exceeds fixture ceiling: {key}")
    return dict(envelope)


def _runtime_path(root: Path) -> Path:
    candidate = root / "perseus.py"
    if candidate.is_file():
        return candidate
    return Path(__file__).resolve().parents[2] / "perseus.py"


def _stage_file(root: Path, raw: Any, workspace: Path, *, expected: str | None = None) -> tuple[Path, str]:
    rel = Path(raw)
    data = _secure_file_bytes(root, raw)
    digest = _sha_bytes(data)
    if expected is not None and digest != expected.lower():
        raise AcceptanceError("artifact_digest_mismatch")
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if _sha_bytes(target.read_bytes()) != digest:
        raise AcceptanceError("staged_artifact_digest_mismatch")
    return target, digest


def _stage_runtime(root: Path, workspace: Path, *, expected: str | None = None) -> tuple[Path, str]:
    source = _runtime_path(root)
    data = source.read_bytes()
    digest = _sha_bytes(data)
    if expected is not None and digest != expected.lower():
        raise AcceptanceError("artifact_digest_mismatch")
    target = workspace / "perseus.py"
    target.write_bytes(data)
    if _sha_bytes(target.read_bytes()) != digest:
        raise AcceptanceError("staged_artifact_digest_mismatch")
    return target, digest


def _parse_operation_receipt(text: str, *, action: str, version: str, artifact_sha256: str, query: str) -> dict[str, Any]:
    try:
        value = json.loads(text, parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise AcceptanceError("operation_receipt_invalid") from None
    if not isinstance(value, Mapping) or set(value) != _OPERATION_RECEIPT_KEYS:
        raise AcceptanceError("operation_receipt_invalid")
    if (
        value.get("schema_version") != _OPERATION_SCHEMA
        or value.get("action") != action
        or value.get("version") != version
        or value.get("artifact_sha256") != artifact_sha256
        or value.get("query_sha256") != _sha(query)
        or value.get("result") != "passed"
        or value.get("persisted") is not True
    ):
        raise AcceptanceError("operation_receipt_invalid")
    return dict(value)


def _bundle_reason(label: str, kind: str) -> str:
    return f"{label}_bundle_{kind}"


def _operation_reason(label: str, kind: str) -> str:
    return f"{label}_operation_{kind}"


def _check_bundle(
    root: Path,
    spec: Mapping[str, Any],
    label: str,
    *,
    execute: bool = False,
    resource_limits: Mapping[str, int] | None = None,
    monitor_dir: Path | None = None,
    disk_limit_bytes: int | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    if not isinstance(spec, Mapping) or set(spec) not in {_BUNDLE_KEYS, _BUNDLE_KEYS_WITH_COMMAND}:
        return {"status": "blocked", "checked": False, "reason": _bundle_reason(label, "contract_invalid")}
    query_value = _DEFAULT_QUERY if query is None else query
    try:
        _validate_bundle_spec(spec, label)
        actual = _sha_bytes(_secure_file_bytes(root, spec["path"]))
        expected = spec["sha256"]
        if actual != expected.lower():
            raise AcceptanceError("digest_mismatch")
        result = {
            "status": "passed",
            "checked": True,
            "version": spec["version"],
            "sha256": actual,
            "operation_executed": False,
        }
        if not execute:
            return result
        if "command" not in spec:
            raise AcceptanceError("operation_undeclared")
        parent = Path(monitor_dir or root.parent)
        with tempfile.TemporaryDirectory(prefix=f".perseus-{label}-", dir=str(parent)) as workspace_name:
            workspace = Path(workspace_name)
            staged_bundle, _ = _stage_file(root, spec["path"], workspace, expected=actual)
            staged_runtime, _ = _stage_runtime(root, workspace, expected=_sha_bytes(_runtime_path(root).read_bytes()))
            env = dict(os.environ)
            env.pop("PERSEUS_ALLOW_DANGEROUS", None)
            env.update({
                "PERSEUS_OFFLINE": "1",
                "PERSEUS_OFFLINE_RUNTIME": str(staged_runtime),
                "PERSEUS_OPERATION_ACTION": label,
                "PERSEUS_OPERATION_VERSION": spec["version"],
                "PERSEUS_OPERATION_ARTIFACT_SHA256": actual,
                "PERSEUS_OPERATION_QUERY_SHA256": _sha(query_value),
                "PERSEUS_BUNDLE_PATH": str(staged_bundle.relative_to(workspace)).replace(os.sep, "/"),
                "PERSEUS_BUNDLE_VERSION": spec["version"],
                "PERSEUS_BUNDLE_SHA256": actual,
                "PERSEUS_WORKLOAD_QUERY": query_value,
            })
            operation = _run_bounded_child(
                spec["command"],
                cwd=workspace,
                timeout=60,
                env=env,
                resource_limits=resource_limits,
                monitor_dirs=(workspace,),
                disk_limit_bytes=disk_limit_bytes,
                offline_required=True,
            )
            try:
                post_digest = _sha_bytes(_secure_file_bytes(root, spec["path"]))
            except (OSError, TypeError, ValueError, AcceptanceError):
                post_digest = None
            if post_digest != actual:
                raise AcceptanceError("changed_during_operation")
            result.update({
                "status": "blocked",
                "checked": False,
                "operation_executed": True,
                "operation_exit_code": operation.get("exit_code"),
                "operation_output_truncated": bool(operation.get("stdout_truncated") or operation.get("stderr_truncated")),
                "operation_child_cpu_seconds_observed": operation.get("child_cpu_seconds_observed", 0.0),
                "operation_child_peak_rss_mb_observed": operation.get("child_peak_rss_mb_observed", 0.0),
                "offline_report": operation.get("offline_report"),
            })
            if (
                operation.get("status") == "passed"
                and operation.get("exit_code") == 0
                and not operation.get("stdout_truncated")
                and not operation.get("stderr_truncated")
                and not operation.get("stderr")
            ):
                try:
                    receipt = _parse_operation_receipt(operation.get("stdout", ""), action=label, version=spec["version"], artifact_sha256=actual, query=query_value)
                except AcceptanceError:
                    receipt = None
                if receipt is not None:
                    result.update({
                        "status": "passed",
                        "checked": True,
                        "operation_receipt_sha256": _sha(receipt),
                        "operation_receipt_persisted": True,
                    })
            if result["status"] != "passed":
                if operation.get("status") != "passed" or operation.get("exit_code") != 0:
                    reason = _operation_reason(label, "failed")
                elif operation.get("offline_report") is None:
                    reason = _operation_reason(label, "offline_guard_unavailable")
                else:
                    reason = _operation_reason(label, "receipt_invalid")
                result["reason"] = reason
            return result
    except FileNotFoundError:
        return {"status": "blocked", "checked": False, "reason": _bundle_reason(label, "unavailable")}
    except (IsADirectoryError, NotADirectoryError):
        return {"status": "blocked", "checked": False, "reason": _bundle_reason(label, "unavailable")}
    except AcceptanceError as exc:
        kind = str(exc)
        if kind == "digest_mismatch":
            kind = "digest_mismatch"
        elif kind == "changed_during_operation":
            kind = "changed_during_operation"
        elif kind == "operation_undeclared":
            kind = "operation_undeclared"
        elif kind in {"offline_guard_unavailable", "offline_guard_runtime_unavailable"}:
            kind = "offline_guard_unavailable"
        elif kind in {"operation_receipt_invalid", "staged_artifact_digest_mismatch", "artifact_digest_mismatch"}:
            kind = "operation_receipt_invalid"
        else:
            kind = "contract_invalid"
        return {"status": "blocked", "checked": False, "reason": _bundle_reason(label, kind)}
    except (OSError, TypeError, ValueError):
        return {"status": "blocked", "checked": False, "reason": _bundle_reason(label, "unavailable")}


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
    blocked_count = sum(item["outcome"] == "blocked" for item in report["attempts"])
    allowed_count = sum(item["outcome"] == "allowed_local" for item in report["attempts"])
    if report["blocked_attempts"] < blocked_count or report["allowed_local_attempts"] < allowed_count:
        raise AcceptanceError("offline child probe counters are inconsistent")
    if not report["attempts_truncated"] and (report["blocked_attempts"] != blocked_count or report["allowed_local_attempts"] != allowed_count):
        raise AcceptanceError("offline child probe counters are inconsistent")
    return dict(value)


def _run_render(
    repo_root: Path,
    source: str,
    state_dir: Path,
    *,
    attempt: str,
    resource_limits: Mapping[str, int] | None = None,
    query: str | None = None,
    artifact_digest: str | None = None,
) -> dict[str, Any]:
    query_value = _DEFAULT_QUERY if query is None else query
    expected = artifact_digest
    if expected is None:
        try:
            expected = _sha_bytes(_secure_file_bytes(repo_root, "perseus.py"))
        except (OSError, TypeError, ValueError, AcceptanceError):
            raise AcceptanceError("perseus_artifact_unavailable") from None
    started = time.perf_counter()
    limits = dict(resource_limits or _CHILD_LIMITS)
    with tempfile.TemporaryDirectory(prefix=f".perseus-render-{attempt}-", dir=str(state_dir.parent)) as workspace_name:
        workspace = Path(workspace_name)
        staged_runtime, staged_digest = _stage_file(repo_root, "perseus.py", workspace, expected=expected)
        source_path = workspace / "workload.md"
        source_path.write_text(source, encoding="utf-8")
        env = dict(os.environ)
        env.pop("PERSEUS_ALLOW_DANGEROUS", None)
        env.update({
            "PERSEUS_OFFLINE": "1",
            "PERSEUS_OFFLINE_RUNTIME": str(staged_runtime),
            "PERSEUS_HOME": str(state_dir / "home"),
            "PERSEUS_WORKLOAD_QUERY": query_value,
            "PERSEUS_WORKLOAD_QUERY_SHA256": _sha(query_value),
        })
        result = _run_bounded_child(
            [sys.executable, str(staged_runtime), "--offline", "render", str(source_path)],
            cwd=workspace,
            timeout=60,
            env=env,
            resource_limits=limits,
            monitor_dirs=(workspace, state_dir),
            disk_limit_bytes=limits["file_bytes"],
            offline_required=True,
        )
        try:
            post_digest = _sha_bytes(_secure_file_bytes(repo_root, "perseus.py"))
        except (OSError, TypeError, ValueError, AcceptanceError):
            post_digest = None
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    output = result["stdout"].encode("utf-8", errors="replace")
    status = "passed" if result["status"] == "passed" and result["exit_code"] == 0 and "@date" not in result["stdout"] and not result["stdout_truncated"] and not result["stderr_truncated"] and result.get("offline_report") is not None else "failed"
    if post_digest != expected or staged_digest != expected:
        status = "blocked"
    result_value = {
        "attempt": attempt,
        "status": status,
        "exit_code": result["exit_code"],
        "output_sha256": _stable_output_digest(output),
        "output_bytes": result["stdout_prefix_bytes"],
        "stable_output_bytes": _stable_output_bytes(output),
        "output_truncated": result["stdout_truncated"],
        "log_bytes": result["stdout_prefix_bytes"] + result["stderr_prefix_bytes"],
        "log_truncated": result["stdout_truncated"] or result["stderr_truncated"],
        "startup_ms_observed": elapsed_ms,
        "resource_limits": limits,
        "child_cpu_seconds_observed": result["child_cpu_seconds_observed"],
        "child_peak_rss_mb_observed": result["child_peak_rss_mb_observed"],
        "offline_report": result.get("offline_report"),
        "query_sha256": _sha(query_value),
        "artifact_sha256": expected,
    }
    if status == "blocked":
        result_value["reason"] = "perseus_artifact_changed_or_guard_unavailable" if post_digest != expected or staged_digest != expected else "perseus_offline_guard_unavailable"
    elif status == "failed":
        result_value["reason"] = "render_child_failed"
    return result_value


def _run_adapter(
    root: Path,
    spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
    resource_limits: Mapping[str, int],
    *,
    monitor_dir: Path | None = None,
    disk_limit_bytes: int | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Run an explicitly supplied Vault/Ledger adapter without exposing output."""
    name = str(spec["name"])
    if manifest.get("state") != "available":
        return {"status": "unavailable", "reason": "adapter_artifact_unavailable"}
    if "command" not in spec:
        return {"status": "not_run", "reason": "adapter_operation_undeclared"}
    version = manifest.get("version") or spec.get("version")
    if not isinstance(version, str) or not version.strip():
        return {"status": "blocked", "reason": "adapter_version_undeclared"}
    query_value = _DEFAULT_QUERY if query is None else query
    expected = manifest.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return {"status": "blocked", "reason": "adapter_digest_unavailable"}
    parent = Path(monitor_dir or root.parent)
    parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=f".perseus-adapter-{name}-", dir=str(parent)) as workspace_name:
            workspace = Path(workspace_name)
            staged_artifact, actual = _stage_file(root, spec["path"], workspace, expected=expected)
            runtime_source = _runtime_path(root)
            runtime_data = runtime_source.read_bytes()
            staged_runtime = workspace / "perseus.py"
            staged_runtime.write_bytes(runtime_data)
            command = list(spec["command"])
            if command and not Path(command[0]).is_absolute() and (root / command[0]).is_file():
                command[0] = str((root / command[0]).resolve())
            env = dict(os.environ)
            env.pop("PERSEUS_ALLOW_DANGEROUS", None)
            env.update({
                "PERSEUS_OFFLINE": "1",
                "PERSEUS_OFFLINE_RUNTIME": str(staged_runtime),
                "PERSEUS_ADAPTER_NAME": name,
                "PERSEUS_ADAPTER_ARTIFACT": str(staged_artifact.relative_to(workspace)).replace(os.sep, "/"),
                "PERSEUS_ADAPTER_SHA256": actual,
                "PERSEUS_OPERATION_ACTION": name,
                "PERSEUS_OPERATION_VERSION": version,
                "PERSEUS_OPERATION_ARTIFACT_SHA256": actual,
                "PERSEUS_OPERATION_QUERY_SHA256": _sha(query_value),
                "PERSEUS_WORKLOAD_QUERY": query_value,
            })
            operation = _run_bounded_child(
                command,
                cwd=workspace,
                timeout=60,
                env=env,
                resource_limits=resource_limits,
                monitor_dirs=(workspace,),
                disk_limit_bytes=disk_limit_bytes,
                offline_required=True,
            )
            try:
                post_digest = _sha_bytes(_secure_file_bytes(root, spec["path"]))
            except (OSError, TypeError, ValueError, AcceptanceError):
                post_digest = None
            value: dict[str, Any] = {
                "status": "blocked",
                "exit_code": operation.get("exit_code"),
                "artifact_sha256": actual,
                "version": version,
                "output_truncated": bool(operation.get("stdout_truncated") or operation.get("stderr_truncated")),
                "resource_limits": dict(resource_limits),
                "child_cpu_seconds_observed": operation.get("child_cpu_seconds_observed", 0.0),
                "child_peak_rss_mb_observed": operation.get("child_peak_rss_mb_observed", 0.0),
                "offline_report": operation.get("offline_report"),
                "query_sha256": _sha(query_value),
            }
            if post_digest != actual:
                value["reason"] = "adapter_artifact_changed_during_operation"
            elif operation.get("status") != "passed" or operation.get("exit_code") != 0:
                value["reason"] = "adapter_operation_failed"
            elif operation.get("stderr") or value["output_truncated"] or operation.get("offline_report") is None:
                value["reason"] = "adapter_offline_guard_unavailable"
            else:
                try:
                    receipt = _parse_operation_receipt(operation.get("stdout", ""), action=name, version=version, artifact_sha256=actual, query=query_value)
                except AcceptanceError:
                    receipt = None
                if receipt is None:
                    value["reason"] = "adapter_operation_receipt_invalid"
                else:
                    value.update({"status": "passed", "operation_receipt_sha256": _sha(receipt), "operation_receipt_persisted": True})
            return value
    except FileNotFoundError:
        return {"status": "blocked", "reason": "adapter_artifact_unavailable"}
    except AcceptanceError as exc:
        code = str(exc)
        if code in {"offline_guard_unavailable", "offline_guard_runtime_unavailable"}:
            code = "adapter_offline_guard_unavailable"
        elif code in {"artifact_digest_mismatch", "staged_artifact_digest_mismatch"}:
            code = "adapter_digest_mismatch"
        else:
            code = "adapter_operation_blocked"
        return {"status": "blocked", "reason": code}
    except (OSError, TypeError, ValueError):
        return {"status": "blocked", "reason": "adapter_operation_blocked"}


def _resource_envelope(before_cpu: float, before_rss: int, before_disk: int, output_dir: Path, started: float) -> dict[str, Any]:
    after_cpu = time.process_time()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    after_disk = _directory_size(output_dir)
    # ru_maxrss is a process-lifetime high-water mark. Measure only the
    # high-water growth attributable to this acceptance run; otherwise a
    # previously memory-heavy test or caller can fail this run's ceiling.
    rss_unit = 1 if sys.platform == "darwin" else 1024
    peak_rss_mb = max(0.0, float(usage.ru_maxrss) - float(before_rss)) / rss_unit
    return {
        "cpu_seconds_observed": round(max(0.0, after_cpu - before_cpu), 6),
        "peak_rss_mb_observed": round(peak_rss_mb, 3),
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
    child_limits = _child_limits_from_fixture(fixture)
    before_cpu = time.process_time()
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    before_disk = _directory_size(out)
    started = time.perf_counter()
    artifacts = _artifact_manifest(root, fixture)
    perseus_artifact = next(item for item in artifacts if item["name"] == "perseus")
    if perseus_artifact["state"] != "available":
        raise AcceptanceError("required_perseus_artifact_unavailable")
    artifact_specs = {entry["name"]: entry for entry in fixture["artifacts"]}
    workload = fixture["workload"]
    workload_query = workload["query"]
    flow = {
        "perseus_render": _run_render(
            root, workload["source"], state_dir, attempt="initial", resource_limits=child_limits,
            query=workload_query, artifact_digest=perseus_artifact["sha256"],
        ),
    }
    flow["vault"] = _run_adapter(
        root, artifact_specs["perseus-vault"], next(item for item in artifacts if item["name"] == "perseus-vault"),
        child_limits, monitor_dir=out, disk_limit_bytes=child_limits["file_bytes"], query=workload_query,
    )
    flow["ledger"] = _run_adapter(
        root, artifact_specs["perseus-ledger"], next(item for item in artifacts if item["name"] == "perseus-ledger"),
        child_limits, monitor_dir=out, disk_limit_bytes=child_limits["file_bytes"], query=workload_query,
    )
    restart_count = workload["restart_count"]
    if restart_count == 0:
        flow["restart_recovery"] = {"status": "not_run", "reason": "restart_count_zero", "checked": True}
    else:
        for restart_index in range(1, restart_count + 1):
            flow[f"restart_recovery_{restart_index}"] = _run_render(
                root, workload["source"], state_dir, attempt=f"restart-{restart_index}",
                resource_limits=child_limits, query=workload_query, artifact_digest=perseus_artifact["sha256"],
            )
    backup = out / "backup-state"
    shutil.copytree(state_dir, backup, dirs_exist_ok=True)
    backup_digest = _sha(_sorted_files(backup))
    shutil.rmtree(state_dir)
    shutil.copytree(backup, state_dir)
    restored_digest = _sha(_sorted_files(state_dir))
    digest_match = restored_digest == backup_digest
    restore = _run_render(
        root, workload["source"], state_dir, attempt="restore", resource_limits=child_limits,
        query=workload_query, artifact_digest=perseus_artifact["sha256"],
    )
    post_restore_digest = _sha(_sorted_files(state_dir))
    post_digest_match = post_restore_digest == backup_digest
    restore_result_binding = _sha({
        "backup_digest": backup_digest,
        "post_restore_digest": post_restore_digest,
        "render_status": restore.get("status"),
        "render_exit_code": restore.get("exit_code"),
        "render_output_sha256": restore.get("output_sha256"),
        "query_sha256": _sha(workload_query),
    })
    flow["backup_restore"] = {
        "status": "passed" if digest_match and post_digest_match and restore["status"] == "passed" else "failed",
        "backup_digest": backup_digest,
        "restored_digest": restored_digest,
        "digest_match": digest_match,
        "post_restore_digest": post_restore_digest,
        "post_digest_match": post_digest_match,
        "result_binding": restore_result_binding,
        "restored": state_dir.exists(),
        "render": restore,
    }
    upgrade_spec = workload.get("upgrade_bundle")
    rollback_spec = workload.get("rollback_bundle")
    upgrade = _check_bundle(
        root, upgrade_spec, "upgrade", execute=True, resource_limits=child_limits, monitor_dir=out,
        disk_limit_bytes=child_limits["file_bytes"], query=workload_query,
    ) if isinstance(upgrade_spec, Mapping) else {"status": "not_run", "reason": "upgrade_bundle_undeclared", "checked": False}
    rollback = _check_bundle(
        root, rollback_spec, "rollback", execute=True, resource_limits=child_limits, monitor_dir=out,
        disk_limit_bytes=child_limits["file_bytes"], query=workload_query,
    ) if isinstance(rollback_spec, Mapping) else {"status": "not_run", "reason": "rollback_bundle_undeclared", "checked": False}
    with tempfile.TemporaryDirectory(prefix=".perseus-probe-", dir=str(out)) as probe_workspace_name:
        probe_workspace = Path(probe_workspace_name)
        staged_probe_runtime, _ = _stage_file(root, "perseus.py", probe_workspace, expected=perseus_artifact["sha256"])
        probe_env = {
            **dict(os.environ),
            "PERSEUS_OFFLINE": "1",
            "PERSEUS_OFFLINE_RUNTIME": str(staged_probe_runtime),
            "PERSEUS_WORKLOAD_QUERY": workload_query,
            "PERSEUS_WORKLOAD_QUERY_SHA256": _sha(workload_query),
        }
        probe = _run_bounded_child(
            [sys.executable, str(staged_probe_runtime), "--offline", "offline-probe", "https://example.invalid/disconnected-probe", "--json"],
            cwd=probe_workspace,
            timeout=15,
            env=probe_env,
            resource_limits=child_limits,
            monitor_dirs=(probe_workspace,),
            disk_limit_bytes=child_limits["file_bytes"],
            offline_required=True,
        )
    if probe["status"] != "passed" or probe["exit_code"] != 0 or probe["stdout_truncated"] or probe["stderr_truncated"]:
        raise AcceptanceError("offline_child_probe_failed")
    probe_result = _parse_child_probe_json(probe["stdout"])
    network_probe = probe_result["report"]
    blocked = [item for item in network_probe["attempts"] if item["outcome"] == "blocked"]
    unexpected = [item for item in network_probe["attempts"] if item["outcome"] not in {"blocked", "allowed_local"}]
    child_reports = {
        key: value["offline_report"]
        for key, value in flow.items()
        if isinstance(value, Mapping) and isinstance(value.get("offline_report"), Mapping)
    }
    for key, value in (("upgrade", upgrade), ("rollback", rollback), ("probe", probe)):
        if isinstance(value, Mapping) and isinstance(value.get("offline_report"), Mapping):
            child_reports[key] = value["offline_report"]
    child_attempts = [attempt for report in child_reports.values() for attempt in report.get("attempts", [])]
    network = {
        "policy": "deny_all",
        "attempts": network_probe["attempts"],
        "child_attempts": child_attempts,
        "children": child_reports,
        "attempts_truncated": network_probe.get("attempts_truncated", False),
        "expected_blocked": blocked,
        "unexpected_attempts": unexpected,
        "child_probe": {"status": "passed", "exit_code": probe["exit_code"], "report": probe_result},
        "status": "passed" if blocked and not unexpected and not network_probe.get("attempts_truncated", False) and all(report.get("active") is True and not report.get("attempts_truncated", False) for report in child_reports.values()) else "failed",
    }
    resource_envelope = _validate_resource_envelope(_resource_envelope(before_cpu, before_rss, before_disk, out, started), fixture)
    negative_results = [
        {"cell": "vault", "status": flow["vault"]["status"], "reason": flow["vault"].get("reason", "adapter completed")},
        {"cell": "ledger", "status": flow["ledger"]["status"], "reason": flow["ledger"].get("reason", "adapter completed")},
        {"cell": "upgrade", "status": upgrade["status"], "reason": upgrade.get("reason", "operation_completed")},
        {"cell": "rollback", "status": rollback["status"], "reason": rollback.get("reason", "operation_completed")},
    ]
    claims = {
        "local_offline_capable": "observed" if platform_check["status"] == "passed" and flow["perseus_render"]["status"] == "passed" and network["status"] == "passed" else "not_established",
        "iron_bank_submitted": "not_claimed",
        "iron_bank_assessed": "not_claimed",
        "customer_platform_deployable": "not_established",
        "ato_il5_il6": "not_claimed",
    }
    failed_cells = [value for value in flow.values() if isinstance(value, Mapping)] + [network, upgrade, rollback]
    status = "failed" if platform_check["status"] != "passed" or any(item.get("status") in {"failed", "blocked"} for item in failed_cells) else "partial" if any(item["status"] in {"unavailable", "not_run"} for item in negative_results) else "passed"
    workload_digest = _sha(fixture["workload"])
    workload_query_digest = _sha(workload_query)
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
            "output_bytes": value.get("stable_output_bytes", value.get("output_bytes")),
            "output_truncated": value.get("output_truncated"),
            "backup_digest": value.get("backup_digest"),
            "restored_digest": value.get("restored_digest"),
            "digest_match": value.get("digest_match"),
            "post_restore_digest": value.get("post_restore_digest"),
            "post_digest_match": value.get("post_digest_match"),
            "result_binding": value.get("result_binding"),
            "operation_executed": value.get("operation_executed"),
            "operation_receipt_sha256": value.get("operation_receipt_sha256"),
            "query_sha256": value.get("query_sha256"),
            "artifact_sha256": value.get("artifact_sha256"),
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
        "resource_contract": {
            "limits": fixture["platform"]["resource_limits"],
            "enforced_child_limits": child_limits,
            "aggregate_disk_limit_bytes": child_limits["file_bytes"],
            "measurement_status": resource_envelope.get("measurement_status"),
        },
        "upgrade": upgrade,
        "rollback": rollback,
        "negative_results": negative_results,
        "claims": claims,
        "manifest_commitment": manifest_commitment,
        "workload_digest": workload_digest,
        "workload_query_digest": workload_query_digest,
    }
    report_commitment = _sha(report_core)
    evidence_digest = _sha({
        "manifest_commitment": manifest_commitment,
        "report_commitment": report_commitment,
        "workload_digest": workload_digest,
        "workload_query_digest": workload_query_digest,
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
