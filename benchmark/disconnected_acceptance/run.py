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
import hmac
import importlib.util
import json
import math
import os
import re
import resource
import secrets
import shutil
import select
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
    "schema_version", "action", "version", "artifact_sha256", "query_sha256", "result", "persisted_state",
})
_PERSISTED_STATE_KEYS = frozenset({"path", "sha256"})
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
_MAX_PARENT_FILE_BYTES = 16 * 1024 * 1024
_MAX_PARENT_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_OFFLINE_REPORT_BYTES = 64 * 1024
_MAX_OFFLINE_ATTEMPTS = 256
_MAX_FIXTURE_CPU_SECONDS = 300
_MAX_FIXTURE_MEMORY_MB = 4096
_MAX_FIXTURE_DISK_MB = 4096
_MAX_FIXTURE_RESTART_COUNT = 32
_REASON_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_ALLOWED_PROBE_OUTCOMES = frozenset({"blocked", "allowed_local"})
_OFFLINE_SECCOMP_SYSCALLS = (
    40,   # sendfile
    41,   # socket
    42,   # connect
    43,   # accept
    44,   # sendto
    45,   # recvfrom
    46,   # sendmsg
    47,   # recvmsg
    48,   # shutdown
    49,   # bind
    50,   # listen
    51,   # getsockname
    52,   # getpeername
    53,   # socketpair
    102,  # socketcall (32-bit ABI)
    275,  # splice
    276,  # tee
    278,  # vmsplice
    288,  # accept4
    299,  # recvmmsg
    307,  # sendmmsg
    425,  # io_uring_setup
    426,  # io_uring_enter
    427,  # io_uring_register
)
_OFFLINE_AUDIT_ARCH_X86_64 = 0xC000003E
_OFFLINE_X32_SYSCALL_BIT = 0x40000000


def _install_offline_seccomp() -> None:
    """Install an inherited deny-network seccomp filter on x86_64 Linux.

    The Python monkeypatch is useful telemetry, but it is not a containment
    boundary: ``python -S`` and native/non-Python descendants can bypass it.
    Seccomp filters are inherited across fork/exec, so this closes that class
    without shipping a helper binary. Unsupported hosts fail closed.
    """
    if not sys.platform.startswith("linux") or os.uname().machine.casefold() not in {"x86_64", "amd64"}:
        raise OSError("offline seccomp is unavailable on this host")
    import ctypes

    class _SockFilter(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]

    class _SockFprog(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.POINTER(_SockFilter))]

    bpf_ld_w_abs = 0x20
    bpf_jmp_jeq_k = 0x15
    bpf_jmp_jge_k = 0x25
    bpf_ret_k = 0x06
    seccomp_ret_errno = 0x00050001  # SECCOMP_RET_ERRNO | EPERM
    seccomp_ret_kill_process = 0x80000000  # SECCOMP_RET_KILL_PROCESS
    seccomp_ret_allow = 0x7FFF0000  # SECCOMP_RET_ALLOW
    instructions = [
        _SockFilter(bpf_ld_w_abs, 0, 0, 4),  # seccomp_data.arch
        _SockFilter(bpf_jmp_jeq_k, 1, 0, _OFFLINE_AUDIT_ARCH_X86_64),
        _SockFilter(bpf_ret_k, 0, 0, seccomp_ret_kill_process),
        _SockFilter(bpf_ld_w_abs, 0, 0, 0),  # seccomp_data.nr
        _SockFilter(bpf_jmp_jge_k, 0, 1, _OFFLINE_X32_SYSCALL_BIT),
        _SockFilter(bpf_ret_k, 0, 0, seccomp_ret_errno),
    ]
    for syscall_number in _OFFLINE_SECCOMP_SYSCALLS:
        instructions.append(_SockFilter(bpf_jmp_jeq_k, 0, 1, syscall_number))
        instructions.append(_SockFilter(bpf_ret_k, 0, 0, seccomp_ret_errno))
    instructions.append(_SockFilter(bpf_ret_k, 0, 0, seccomp_ret_allow))
    array_type = _SockFilter * len(instructions)
    array = array_type(*instructions)
    program = _SockFprog(len(instructions), array)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
    if libc.prctl(22, 2, ctypes.addressof(program), 0, 0) != 0:  # PR_SET_SECCOMP / FILTER
        raise OSError(ctypes.get_errno(), "PR_SET_SECCOMP failed")


def _evidence_token(value: Any) -> str:
    """Hash child-controlled telemetry scalars before publication."""
    text = value if isinstance(value, str) else repr(value)
    return "sha256:" + _sha_bytes(text.encode("utf-8", errors="replace"))


def _sanitize_offline_report(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = dict(value)
    sanitized.pop("guard_token", None)
    sanitized["attempts"] = [
        {
            "operation": _evidence_token(item["operation"]),
            "destination": _evidence_token(item["destination"]),
            "outcome": item["outcome"],
        }
        for item in value["attempts"]
    ]
    return sanitized

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


def _secure_file_bytes(root: Path, raw: Any, *, max_bytes: int = _MAX_PARENT_FILE_BYTES) -> bytes:
    """Read one fixture-controlled file through no-follow directory handles."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise AcceptanceError("parent_read_limit_invalid")
    path = _safe_relative_path(root, raw)
    parts = path.relative_to(root).parts
    if os.name != "posix":
        if path.is_symlink() or not path.is_file():
            raise AcceptanceError("artifact_not_regular")
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise AcceptanceError("parent_read_limit_exceeded")
        return data
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
            raise AcceptanceError("artifact_not_regular")
        with os.fdopen(file_fd, "rb", closefd=True) as handle:
            file_fd = -1
            data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise AcceptanceError("parent_read_limit_exceeded")
            return data
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


def _bounded_reason(value: Any, default: str = "contract_invalid") -> str:
    """Return only a short machine reason code at the public boundary."""
    if not isinstance(value, str) or not _REASON_CODE_RE.fullmatch(value):
        return default
    if value in {
        "adapter_artifact_changed_during_operation",
        "adapter_artifact_unavailable",
        "adapter_digest_mismatch",
        "adapter_digest_unavailable",
        "adapter_offline_guard_unavailable",
        "adapter_operation_blocked",
        "adapter_operation_failed",
        "adapter_operation_receipt_invalid",
        "adapter_operation_undeclared",
        "adapter_version_undeclared",
        "backup_restore_failed",
        "child_cleanup_failed",
        "child_resource_limit",
        "child_spawn_failed",
        "contract_invalid",
        "fixture_load_failed",
        "offline_guard_unavailable",
        "offline_report_invalid",
        "operation_completed",
        "perseus_artifact_changed_or_guard_unavailable",
        "perseus_artifact_unavailable",
        "perseus_offline_guard_unavailable",
        "render_child_failed",
        "restart_count_zero",
        "restore_state_mismatch",
        "resource_limit",
    }:
        return value
    if re.fullmatch(r"(?:upgrade|rollback)_(?:bundle|operation)_[a-z0-9_]{1,64}", value):
        return value
    return default


def _validate_child_limits(resource_limits: Mapping[str, Any] | None) -> dict[str, int]:
    """Validate OS resource bounds before constructing a child process."""
    values = _CHILD_LIMITS if resource_limits is None else resource_limits
    if not isinstance(values, Mapping) or set(values) != set(_CHILD_LIMITS):
        raise AcceptanceError("child_resource_limits_invalid")
    result: dict[str, int] = {}
    for key in _CHILD_LIMITS:
        value = values.get(key)
        if type(value) is not int or value <= 0:
            raise AcceptanceError("child_resource_limits_invalid")
        result[key] = value
    return result


def _validate_disk_limit(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise AcceptanceError("disk_limit_invalid")
    return value


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
    ceilings = {
        "cpu_seconds": _MAX_FIXTURE_CPU_SECONDS,
        "memory_mb": _MAX_FIXTURE_MEMORY_MB,
        "disk_mb": _MAX_FIXTURE_DISK_MB,
    }
    for key in ("cpu_seconds", "memory_mb", "disk_mb"):
        if not _finite_positive_number(limits[key]) or float(limits[key]) > ceilings[key]:
            raise AcceptanceError("fixture resource_limits must be positive finite numbers")
    workload = value.get("workload")
    if not isinstance(workload, Mapping) or set(workload) != _WORKLOAD_KEYS:
        raise AcceptanceError("fixture workload shape is invalid")
    if not isinstance(workload.get("source"), str) or not workload["source"].strip() or not isinstance(workload.get("query"), str) or not workload["query"].strip():
        raise AcceptanceError("fixture workload source and query are required")
    if (
        type(workload.get("restart_count")) is not int
        or workload["restart_count"] < 0
        or workload["restart_count"] > _MAX_FIXTURE_RESTART_COUNT
    ):
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
    limits = _validate_child_limits(resource_limits)

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


_VOLATILE_FIELDS = frozenset({
    "child_cpu_seconds_observed",
    "child_peak_rss_mb_observed",
    "operation_child_cpu_seconds_observed",
    "operation_child_peak_rss_mb_observed",
    "cpu_seconds_observed",
    "peak_rss_mb_observed",
    "wall_seconds_observed",
    "startup_ms_observed",
    "resource_observations_commitment",
})


def _stable_projection(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _stable_projection(item)
            for key, item in value.items()
            if key not in _VOLATILE_FIELDS
        }
    if isinstance(value, list):
        return [_stable_projection(item) for item in value]
    return value


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


class _AggregateResourceBudget:
    """Charge transient child resources against one run-level ceiling."""

    def __init__(self, roots: tuple[Path, ...], *, cpu_seconds: float, memory_mb: float, disk_bytes: int):
        self.roots = roots
        self.cpu_limit = float(cpu_seconds)
        self.memory_limit = float(memory_mb)
        self.disk_limit = int(disk_bytes)
        self.baseline_disk = _monitor_size(roots)
        self.cpu_seconds = 0.0
        self.peak_rss_mb = 0.0
        self.disk_bytes = 0

    def observe(self, *, cpu_seconds: float, peak_rss_mb: float, disk_growth_bytes: int) -> bool:
        self.cpu_seconds += max(0.0, float(cpu_seconds))
        self.peak_rss_mb = max(self.peak_rss_mb, max(0.0, float(peak_rss_mb)))
        current_growth = max(0, _monitor_size(self.roots) - self.baseline_disk)
        self.disk_bytes += max(0, int(disk_growth_bytes))
        self.disk_bytes = max(self.disk_bytes, current_growth)
        return not self.exceeded

    @property
    def exceeded(self) -> bool:
        return (
            self.cpu_seconds > self.cpu_limit
            or self.peak_rss_mb > self.memory_limit
            or self.disk_bytes > self.disk_limit
        )

    def report(self) -> dict[str, Any]:
        return {
            "cpu_seconds_observed": round(self.cpu_seconds, 6),
            "peak_rss_mb_observed": round(self.peak_rss_mb, 3),
            "disk_growth_bytes_observed": self.disk_bytes,
            "status": "resource_limit" if self.exceeded else "within_limit",
        }


def _is_python_argv(argv: list[str]) -> bool:
    if not argv or not isinstance(argv[0], str):
        return False
    executable = Path(argv[0]).name.casefold()
    return executable.startswith(("python", "pypy"))


def _prepare_offline_guard(
    argv: list[str], cwd: Path, env: Mapping[str, str]
) -> tuple[dict[str, str], Path | None, Path | None, str | None]:
    """Install parent-owned Python telemetry; seccomp contains every child."""
    child_env = dict(env)
    child_env["PERSEUS_OFFLINE"] = "1"
    child_env.pop("PERSEUS_OFFLINE_REPORT", None)
    if not _is_python_argv(argv):
        return child_env, None, None, None
    runtime_raw = env.get("PERSEUS_OFFLINE_RUNTIME")
    runtime_path = Path(runtime_raw) if isinstance(runtime_raw, str) else None
    if runtime_path is None or not runtime_raw or runtime_path.is_symlink() or not runtime_path.is_file():
        raise AcceptanceError("offline_guard_runtime_unavailable")
    guard_dir = Path(tempfile.mkdtemp(prefix=".perseus-offline-", dir=str(cwd)))
    report_path = guard_dir / "report.json"
    guard_path = guard_dir / "sitecustomize.py"
    guard_token = secrets.token_hex(16)
    _strict_write_guard(guard_dir, guard_path,
        "import atexit, importlib.util, json, os\n"
        f"_runtime = {str(runtime_path)!r}\n"
        f"_report_path = {str(report_path)!r}\n"
        f"_guard_token = {guard_token!r}\n"
        "def _write(value):\n"
        "    try:\n"
        "        value = dict(value)\n"
        "        value['guard_token'] = _guard_token\n"
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
    old_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    return child_env, guard_dir, report_path, guard_token


def _read_offline_report(path: Path, expected_token: str | None) -> dict[str, Any] | None:
    if not isinstance(expected_token, str) or not expected_token:
        return None
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return None
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            return None
        if info.st_size > _MAX_OFFLINE_REPORT_BYTES:
            return None
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags)
        try:
            raw = os.read(fd, _MAX_OFFLINE_REPORT_BYTES + 1)
        finally:
            os.close(fd)
        if len(raw) > _MAX_OFFLINE_REPORT_BYTES:
            return None
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    required = {"active", "policy", "attempts", "attempts_truncated", "blocked_attempts", "allowed_local_attempts", "guard_token"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("active") is not True or value.get("policy") != "deny_all_non_loopback":
        return None
    if not isinstance(value.get("guard_token"), str) or not hmac.compare_digest(value["guard_token"], expected_token):
        return None
    if not isinstance(value["attempts"], list) or not isinstance(value["attempts_truncated"], bool):
        return None
    if len(value["attempts"]) > _MAX_OFFLINE_ATTEMPTS:
        return None
    for attempt in value["attempts"]:
        if not isinstance(attempt, Mapping) or set(attempt) != {"operation", "destination", "outcome"}:
            return None
        if not all(isinstance(attempt[key], str) for key in ("operation", "destination", "outcome")) or attempt["outcome"] not in _ALLOWED_PROBE_OUTCOMES:
            return None
    if any(isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 0 or value[key] > _MAX_OFFLINE_ATTEMPTS for key in ("blocked_attempts", "allowed_local_attempts")):
        return None
    return _sanitize_offline_report(value)


def _cleanup_guard_dir(path: Path | None) -> bool:
    """Remove a guard directory strictly; return false on any uncertainty."""
    if path is None:
        return True
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return False
        os.chmod(path, 0o700)
        for item in path.rglob("*"):
            if item.is_dir() and not item.is_symlink():
                os.chmod(item, 0o700)
            elif item.is_file() and not item.is_symlink():
                os.chmod(item, 0o600)
        shutil.rmtree(path, ignore_errors=False)
        return not path.exists()
    except (OSError, TypeError, ValueError):
        return False


def _strict_write_guard(guard_dir: Path, path: Path, text: str, **kwargs: Any) -> None:
    try:
        path.write_text(text, **kwargs)
    except (OSError, TypeError, ValueError):
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        raise AcceptanceError("offline_guard_unavailable" if cleanup_ok else "child_cleanup_failed") from None


def _process_identity(pid: int) -> dict[str, int] | None:
    """Read PID, PGID, parent, state, and Linux start time without guessing."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        text = (Path("/proc") / str(int(pid)) / "stat").read_text(encoding="utf-8")
        closing = text.rfind(")")
        fields = text[closing + 2 :].split()
        return {
            "pid": int(pid),
            "state": fields[0],
            "ppid": int(fields[1]),
            "pgid": int(fields[2]),
            "start_time": int(fields[19]),
        }
    except (FileNotFoundError, OSError, IndexError, TypeError, ValueError):
        return None


def _process_snapshot() -> dict[int, dict[str, int]]:
    if not sys.platform.startswith("linux"):
        return {}
    result: dict[int, dict[str, int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return result
    for entry in entries:
        if entry.isdigit():
            identity = _process_identity(int(entry))
            if identity is not None:
                result[int(entry)] = identity
    return result


def _process_has_run_token(pid: int, token: str | None) -> bool:
    if not isinstance(token, str) or not token or not sys.platform.startswith("linux"):
        return False
    try:
        marker = f"PERSEUS_ACCEPTANCE_RUN_ID={token}".encode("ascii")
        return marker in (Path("/proc") / str(int(pid)) / "environ").read_bytes()[: 64 * 1024].split(b"\0")
    except (OSError, TypeError, ValueError):
        return False


def _owned_processes(
    leader_pid: int,
    baseline: Mapping[int, Mapping[str, int]],
    known: dict[int, dict[str, int]],
    run_token: str | None,
) -> dict[int, dict[str, int]]:
    """Collect only new descendants or processes carrying this run marker."""
    snapshot = _process_snapshot()
    children: dict[int, list[int]] = {}
    for pid, identity in snapshot.items():
        children.setdefault(identity["ppid"], []).append(pid)
    pending = [leader_pid]
    descendants: set[int] = set()
    while pending:
        parent = pending.pop()
        for child in children.get(parent, ()):
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    for pid in descendants:
        identity = snapshot.get(pid)
        if identity is not None and pid not in baseline:
            owned = dict(identity)
            owned["owned_by_ancestry"] = 1
            known[pid] = owned
    for pid, identity in snapshot.items():
        if pid not in baseline and _process_has_run_token(pid, run_token):
            owned = dict(identity)
            owned["owned_by_ancestry"] = known.get(pid, {}).get("owned_by_ancestry", 0)
            known[pid] = owned
    return known


def _identity_alive(identity: Mapping[str, int], run_token: str | None) -> tuple[bool, bool]:
    """Return (alive, ownership_verified) for a PID/start-time boundary."""
    current = _process_identity(identity["pid"])
    if current is None:
        if sys.platform.startswith("linux") and (Path("/proc") / str(identity["pid"])).exists():
            return True, False
        return False, True
    if current["start_time"] != identity["start_time"]:
        return False, True
    if current["state"] == "Z":
        return False, True
    if identity.get("owned_by_ancestry") != 1 and run_token is not None and not _process_has_run_token(identity["pid"], run_token):
        return True, False
    return True, True


def _signal_owned(
    identity: Mapping[str, int], sig: signal.Signals, run_token: str | None, trusted_pgid: int | None = None
) -> bool:
    current = _process_identity(identity["pid"])
    if current is None:
        return not (sys.platform.startswith("linux") and (Path("/proc") / str(identity["pid"])).exists())
    if current["start_time"] != identity["start_time"]:
        return True
    if current["state"] == "Z":
        return True
    if (
        trusted_pgid != current["pgid"]
        and identity.get("owned_by_ancestry") != 1
        and run_token is not None
        and not _process_has_run_token(identity["pid"], run_token)
    ):
        return False
    if current["pgid"] != identity.get("pgid"):
        return False
    try:
        os.kill(identity["pid"], sig)
        return True
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False


def _terminate_process_group(
    process: subprocess.Popen[Any],
    leader_identity: Mapping[str, int] | None,
    known: dict[int, dict[str, int]],
    run_token: str | None,
) -> bool:
    """Terminate/reap only verified new processes and their current PGID."""
    cleanup_ok = leader_identity is not None
    leader_pid = process.pid
    if os.name != "posix":
        try:
            if leader_identity is not None:
                process.terminate()
            process.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            cleanup_ok = False
        return cleanup_ok
    for sig, wait_time in ((signal.SIGTERM, 0.25), (signal.SIGKILL, 1.0)):
        _owned_processes(leader_pid, {}, known, run_token)
        group_pgid: int | None = None
        if leader_identity is not None:
            current_leader = _process_identity(leader_pid)
            if current_leader is None:
                if sys.platform.startswith("linux") and (Path("/proc") / str(leader_pid)).exists():
                    cleanup_ok = False
            elif current_leader["start_time"] != leader_identity["start_time"]:
                cleanup_ok = False
            else:
                if current_leader["pgid"] == leader_identity["pgid"]:
                    group_pgid = current_leader["pgid"]
                else:
                    cleanup_ok = False
        if group_pgid is None:
            for identity in list(known.values()):
                current = _process_identity(identity["pid"])
                if (
                    current is not None
                    and current["start_time"] == identity["start_time"]
                    and current["pgid"] == identity.get("pgid")
                    and (
                        identity.get("owned_by_ancestry") == 1
                        or _process_has_run_token(identity["pid"], run_token)
                    )
                ):
                    group_pgid = current["pgid"]
                    break
        if group_pgid is not None:
            try:
                os.killpg(group_pgid, sig)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError):
                cleanup_ok = False
        for identity in list(known.values()):
            if identity["pid"] != leader_pid and not _signal_owned(identity, sig, run_token, group_pgid):
                alive, ownership = _identity_alive(identity, run_token)
                if alive and not ownership:
                    cleanup_ok = False
        try:
            process.wait(timeout=wait_time)
        except subprocess.TimeoutExpired:
            pass
        except (OSError, subprocess.SubprocessError):
            cleanup_ok = False
    _owned_processes(leader_pid, {}, known, run_token)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        alive_owned = []
        for identity in list(known.values()):
            alive, ownership = _identity_alive(identity, run_token)
            if alive and ownership:
                alive_owned.append(identity)
                if not _signal_owned(identity, signal.SIGKILL, run_token):
                    cleanup_ok = False
            elif alive and not ownership:
                cleanup_ok = False
        for pid in {item["pid"] for item in alive_owned}:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            except OSError:
                cleanup_ok = False
        if not alive_owned:
            break
        time.sleep(0.01)
    for identity in list(known.values()):
        alive, ownership = _identity_alive(identity, run_token)
        if alive and ownership:
            cleanup_ok = False
        elif alive and not ownership:
            cleanup_ok = False
        try:
            while os.waitpid(identity["pid"], os.WNOHANG)[0] > 0:
                pass
        except ChildProcessError:
            pass
        except OSError:
            cleanup_ok = False
    if process.returncode is None:
        try:
            process.wait(timeout=0.25)
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
            cleanup_ok = False
    return cleanup_ok


_SUBREAPER_UNAVAILABLE = object()
_subreaper_state: bool | object | None = None


def _ensure_child_subreaper() -> bool:
    """Make orphaned descendants observable so detached sessions fail closed."""
    global _subreaper_state
    if _subreaper_state is not None:
        return _subreaper_state is True
    if not sys.platform.startswith("linux"):
        _subreaper_state = _SUBREAPER_UNAVAILABLE
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        prctl.restype = ctypes.c_int
        if prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            _subreaper_state = _SUBREAPER_UNAVAILABLE
            return False
    except (AttributeError, OSError, TypeError, ValueError):
        _subreaper_state = _SUBREAPER_UNAVAILABLE
        return False
    _subreaper_state = True
    return True


def _read_process_peak_rss_bytes(pid: int) -> int:
    """Read a live Linux process high-water RSS without shared high-water reuse."""
    if not sys.platform.startswith("linux"):
        return 0
    try:
        for line in (Path("/proc") / str(pid) / "status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, IndexError, ValueError):
        return 0
    return 0


def _blocked_child_result(limits: Mapping[str, int], *, reason: str, cleanup_failed: bool = False) -> dict[str, Any]:
    return {
        "status": "blocked",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "stdout_prefix_bytes": 0,
        "stderr_prefix_bytes": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "child_cpu_seconds_observed": 0.0,
        "child_peak_rss_mb_observed": 0.0,
        "disk_growth_bytes_observed": 0,
        "aggregate_resource": None,
        "resource_limits": dict(limits),
        "offline_sandbox": None,
        "offline_report": None,
        "offline_guard": {"enforced": False, "boundary": None, "report_present": False},
        "cleanup_failed": cleanup_failed,
        "reason": _bounded_reason(reason, "offline_guard_unavailable"),
    }


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
    aggregate_budget: _AggregateResourceBudget | None = None,
) -> dict[str, Any]:
    """Run one child with verified ownership, inherited seccomp, and bounds."""
    timeout_value = _validate_child_timeout(timeout)
    limits = _validate_child_limits(resource_limits)
    disk_limit = _validate_disk_limit(disk_limit_bytes) if disk_limit_bytes is not None else None
    if aggregate_budget is not None:
        aggregate_budget.observe(cpu_seconds=0.0, peak_rss_mb=0.0, disk_growth_bytes=0)
        if aggregate_budget.exceeded:
            result = _blocked_child_result(limits, reason="child_resource_limit")
            result["aggregate_resource"] = aggregate_budget.report()
            return result
    monitor_roots = tuple(monitor_dirs or (() if monitor_dir is None else (monitor_dir,))) + (Path(cwd),)
    offline_requested = env.get("PERSEUS_OFFLINE") == "1"
    if offline_required is not None and type(offline_required) is not bool:
        raise AcceptanceError("offline_policy_invalid")
    if offline_required is False and offline_requested:
        raise AcceptanceError("offline_guard_required")
    require_offline = offline_requested if offline_required is None else offline_required
    if require_offline and not sys.platform.startswith("linux"):
        raise AcceptanceError("offline_sandbox_unavailable")
    child_env = dict(env)
    run_token = secrets.token_hex(16)
    child_env["PERSEUS_ACCEPTANCE_RUN_ID"] = run_token
    guard_dir: Path | None = None
    report_path: Path | None = None
    report_token: str | None = None
    if require_offline:
        try:
            child_env, guard_dir, report_path, report_token = _prepare_offline_guard(argv, Path(cwd), child_env)
        except (OSError, TypeError, ValueError, AcceptanceError):
            return _blocked_child_result(limits, reason="offline_guard_unavailable")
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": child_env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    guard_read_fd = guard_write_fd = -1
    if os.name == "posix":
        kwargs["start_new_session"] = True
        resource_limiter = _child_resource_limiter(limits)
        if require_offline:
            guard_read_fd, guard_write_fd = os.pipe()
            os.set_inheritable(guard_write_fd, True)
            kwargs["pass_fds"] = (guard_write_fd,)

        def _child_setup() -> None:
            if resource_limiter is not None:
                resource_limiter()
            if require_offline:
                _install_offline_seccomp()
                os.write(guard_write_fd, b"1")

        kwargs["preexec_fn"] = _child_setup
    subreaper_ready = _ensure_child_subreaper() if sys.platform.startswith("linux") else False
    if sys.platform.startswith("linux") and not subreaper_ready:
        if guard_read_fd >= 0:
            os.close(guard_read_fd)
        if guard_write_fd >= 0:
            os.close(guard_write_fd)
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        return _blocked_child_result(limits, reason="child_containment_unavailable", cleanup_failed=not cleanup_ok)
    baseline = _process_snapshot() if subreaper_ready else {}
    before_disk = _monitor_size(monitor_roots)
    before_children = resource.getrusage(resource.RUSAGE_CHILDREN) if hasattr(resource, "RUSAGE_CHILDREN") else None
    try:
        process = subprocess.Popen(argv, **kwargs)
    except (OSError, subprocess.SubprocessError, ValueError):
        if guard_read_fd >= 0:
            os.close(guard_read_fd)
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        if not cleanup_ok:
            return _blocked_child_result(limits, reason="child_cleanup_failed", cleanup_failed=True)
        if require_offline:
            return _blocked_child_result(limits, reason="offline_guard_unavailable", cleanup_failed=not cleanup_ok)
        result = _blocked_child_result(limits, reason="child_spawn_failed", cleanup_failed=not cleanup_ok)
        result["status"] = "failed"
        return result
    finally:
        if guard_write_fd >= 0:
            os.close(guard_write_fd)
    guard_verified = False
    if guard_read_fd >= 0:
        try:
            ready, _, _ = select.select([guard_read_fd], [], [], 1.0)
            guard_verified = bool(ready and os.read(guard_read_fd, 1) == b"1")
        except (OSError, ValueError):
            guard_verified = False
        finally:
            os.close(guard_read_fd)
    leader_identity = _process_identity(process.pid) if sys.platform.startswith("linux") else {"pid": process.pid, "start_time": process.pid, "pgid": process.pid}
    known: dict[int, dict[str, int]] = {}
    captured: dict[str, Any] = {}
    peak_rss_bytes = _read_process_peak_rss_bytes(process.pid)
    max_disk_growth = 0
    stdout_thread = threading.Thread(target=_bounded_reader, args=(process.stdout, _MAX_CHILD_OUTPUT_BYTES, captured, "stdout"), daemon=True)
    stderr_thread = threading.Thread(target=_bounded_reader, args=(process.stderr, _MAX_CHILD_ERROR_BYTES, captured, "stderr"), daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    status = "passed"
    cleanup_failed = False
    deadline = time.monotonic() + timeout_value
    try:
        while True:
            if subreaper_ready:
                _owned_processes(process.pid, baseline, known, run_token)
            peak_rss_bytes = max(peak_rss_bytes, _read_process_peak_rss_bytes(process.pid))
            max_disk_growth = max(max_disk_growth, max(0, _monitor_size(monitor_roots) - before_disk))
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            try:
                process.wait(timeout=min(0.1, remaining) if disk_limit is not None else remaining)
            except subprocess.TimeoutExpired:
                if disk_limit is not None and max_disk_growth > disk_limit:
                    status = "resource_limit"
                    break
    finally:
        try:
            cleanup_ok = _terminate_process_group(process, leader_identity, known, run_token)
            cleanup_failed = not cleanup_ok
        except (OSError, subprocess.SubprocessError, ValueError):
            cleanup_failed = True
    if process.returncode is None:
        try:
            process.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
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
    max_disk_growth = max(max_disk_growth, max(0, _monitor_size(monitor_roots) - before_disk))
    if disk_limit is not None and max_disk_growth > disk_limit and status == "passed":
        status = "resource_limit"
    if cleanup_failed:
        status = "blocked" if require_offline else "failed"
    elif status not in {"timeout", "resource_limit"} and process.returncode != 0:
        status = "blocked" if require_offline else "failed"
    after_children = resource.getrusage(resource.RUSAGE_CHILDREN) if before_children is not None else None
    child_cpu = 0.0
    child_rss_from_usage = 0.0
    if before_children is not None and after_children is not None:
        child_cpu = max(0.0, (after_children.ru_utime + after_children.ru_stime) - (before_children.ru_utime + before_children.ru_stime))
        rss_unit = 1 if sys.platform == "darwin" else 1024
        child_rss_from_usage = max(0.0, float(after_children.ru_maxrss) - float(before_children.ru_maxrss)) / rss_unit
    child_rss = max(child_rss_from_usage, peak_rss_bytes / (1024 * 1024))
    if status == "passed" and (child_cpu > limits["cpu_seconds"] or child_rss > limits["address_space_bytes"] / (1024 * 1024)):
        status = "resource_limit"
    offline_report = _read_offline_report(report_path, report_token) if report_path is not None else None
    guard_cleanup_failed = not _cleanup_guard_dir(guard_dir)
    cleanup_failed = cleanup_failed or guard_cleanup_failed
    if guard_cleanup_failed:
        status = "blocked" if require_offline else "failed"
    if require_offline and (not guard_verified or report_path is None or offline_report is None):
        if status == "passed":
            status = "blocked"
    aggregate_resource = None
    if aggregate_budget is not None:
        aggregate_budget.observe(
            cpu_seconds=child_cpu,
            peak_rss_mb=child_rss,
            disk_growth_bytes=max_disk_growth,
        )
        aggregate_resource = aggregate_budget.report()
        if aggregate_budget.exceeded and status == "passed":
            status = "resource_limit"
    reason = None
    if cleanup_failed:
        reason = "child_cleanup_failed"
    elif require_offline and not guard_verified:
        reason = "offline_guard_unavailable"
    elif require_offline and (report_path is None or offline_report is None):
        reason = "offline_report_invalid"
    elif status == "resource_limit":
        reason = "child_resource_limit"
    elif status in {"failed", "blocked"}:
        reason = "child_spawn_failed" if process.returncode is None else "offline_guard_unavailable" if require_offline else "child_spawn_failed"
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
        "disk_growth_bytes_observed": max_disk_growth,
        "aggregate_resource": aggregate_resource,
        "resource_limits": limits,
        "offline_sandbox": "seccomp" if require_offline and guard_verified else None,
        "offline_report": offline_report,
        "offline_guard": {
            "enforced": bool(require_offline and guard_verified),
            "boundary": "seccomp" if require_offline and guard_verified else None,
            "report_present": offline_report is not None,
            "telemetry": "parent_owned" if offline_report is not None else "unavailable",
        },
        "cleanup_failed": cleanup_failed,
    }
    if reason is not None:
        result["reason"] = _bounded_reason(reason)
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
    if candidate.is_file() and not candidate.is_symlink():
        return candidate
    raise AcceptanceError("perseus_artifact_unavailable")


def _restore_stage_permissions(workspace: Path) -> None:
    stage_root = workspace / ".perseus-immutable"
    if not stage_root.exists() or stage_root.is_symlink():
        return
    for item in sorted(stage_root.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if item.is_symlink():
            continue
        try:
            os.chmod(item, 0o700 if item.is_dir() else 0o600)
        except OSError:
            pass
    try:
        os.chmod(stage_root, 0o700)
    except OSError:
        pass


def _verify_staged_file(path: Path, expected: str, *, workspace: Path | None = None) -> None:
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError("staged_artifact_unavailable")
    if workspace is not None:
        try:
            raw = str(path.relative_to(workspace)).replace(os.sep, "/")
            data = _secure_file_bytes(workspace, raw)
        except (ValueError, OSError, TypeError, AcceptanceError):
            raise AcceptanceError("staged_artifact_unavailable") from None
    else:
        if path.stat().st_size > _MAX_PARENT_FILE_BYTES:
            raise AcceptanceError("staged_artifact_digest_mismatch")
        data = path.read_bytes()
    if _sha_bytes(data) != expected:
        raise AcceptanceError("staged_artifact_digest_mismatch")


def _stage_file(
    root: Path,
    raw: Any,
    workspace: Path,
    *,
    expected: str | None = None,
    immutable: bool = True,
) -> tuple[Path, str]:
    rel = Path(raw)
    data = _secure_file_bytes(root, raw)
    digest = _sha_bytes(data)
    if expected is not None and digest != expected.lower():
        raise AcceptanceError("artifact_digest_mismatch")
    stage_root = workspace / ".perseus-immutable" if immutable else workspace
    target = stage_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        raise AcceptanceError("staged_artifact_replaced") from None
    if immutable:
        os.chmod(target, 0o444)
    if target.stat().st_size > _MAX_PARENT_FILE_BYTES or _sha_bytes(target.read_bytes()) != digest:
        raise AcceptanceError("staged_artifact_digest_mismatch")
    return target, digest


def _stage_runtime(root: Path, workspace: Path, *, expected: str | None = None) -> tuple[Path, str]:
    return _stage_file(root, "perseus.py", workspace, expected=expected, immutable=True)


def _parse_operation_receipt(
    text: str,
    *,
    action: str,
    version: str,
    artifact_sha256: str,
    query: str,
    workspace: Path,
) -> dict[str, Any]:
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
    ):
        raise AcceptanceError("operation_receipt_invalid")
    persisted = value.get("persisted_state")
    if not isinstance(persisted, Mapping) or set(persisted) != _PERSISTED_STATE_KEYS:
        raise AcceptanceError("operation_receipt_invalid")
    state_path = persisted.get("path")
    state_digest = persisted.get("sha256")
    if (
        not isinstance(state_path, str)
        or not state_path.strip()
        or Path(state_path).is_absolute()
        or ".." in Path(state_path).parts
        or not isinstance(state_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", state_digest)
    ):
        raise AcceptanceError("operation_receipt_invalid")
    try:
        actual_state = _sha_bytes(_secure_file_bytes(workspace, state_path))
    except (OSError, TypeError, ValueError, AcceptanceError):
        raise AcceptanceError("operation_receipt_invalid") from None
    if actual_state != state_digest.lower():
        raise AcceptanceError("operation_receipt_invalid")
    return dict(value)


def _bundle_reason(label: str, kind: str) -> str:
    safe_label = label if label in {"upgrade", "rollback"} else "bundle"
    return f"{safe_label}_bundle_{kind}"


def _operation_reason(label: str, kind: str) -> str:
    safe_label = label if label in {"upgrade", "rollback"} else "operation"
    return f"{safe_label}_operation_{kind}"


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
    aggregate_budget: _AggregateResourceBudget | None = None,
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
            staged_runtime, _ = _stage_runtime(root, workspace, expected=_sha_bytes(_secure_file_bytes(root, "perseus.py")))
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
                monitor_dirs=(workspace, root),
                disk_limit_bytes=disk_limit_bytes,
                offline_required=True,
                aggregate_budget=aggregate_budget,
            )
            _verify_staged_file(staged_bundle, actual, workspace=workspace)
            _verify_staged_file(staged_runtime, _sha_bytes(_secure_file_bytes(root, "perseus.py")), workspace=workspace)
            _restore_stage_permissions(workspace)
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
                "offline_sandbox": operation.get("offline_sandbox"),
                "offline_report": operation.get("offline_report"),
                "offline_guard": operation.get("offline_guard"),
                "aggregate_resource": operation.get("aggregate_resource"),
            })
            if (
                operation.get("status") == "passed"
                and operation.get("exit_code") == 0
                and not operation.get("stdout_truncated")
                and not operation.get("stderr_truncated")
                and not operation.get("stderr")
            ):
                try:
                    receipt = _parse_operation_receipt(
                        operation.get("stdout", ""), action=label, version=spec["version"],
                        artifact_sha256=actual, query=query_value, workspace=workspace,
                    )
                except AcceptanceError:
                    receipt = None
                if receipt is not None:
                    result.update({
                        "status": "passed",
                        "checked": True,
                        "operation_receipt_sha256": _sha(receipt),
                        "operation_receipt_persisted": True,
                        "operation_persisted_state_sha256": receipt["persisted_state"]["sha256"],
                    })
            if result["status"] != "passed":
                if operation.get("status") != "passed" or operation.get("exit_code") != 0:
                    reason = _operation_reason(label, "failed")
                elif operation.get("offline_sandbox") != "seccomp":
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
    if not isinstance(report["attempts"], list) or len(report["attempts"]) > _MAX_OFFLINE_ATTEMPTS or not isinstance(report["attempts_truncated"], bool):
        raise AcceptanceError("offline child probe attempts are invalid")
    for attempt in report["attempts"]:
        if not isinstance(attempt, Mapping) or set(attempt) != {"operation", "destination", "outcome"}:
            raise AcceptanceError("offline child probe attempt is invalid")
        if not all(isinstance(attempt[key], str) for key in ("operation", "destination", "outcome")) or attempt["outcome"] not in _ALLOWED_PROBE_OUTCOMES:
            raise AcceptanceError("offline child probe attempt values are invalid")
    if any(isinstance(report[key], bool) or not isinstance(report[key], int) or report[key] < 0 or report[key] > _MAX_OFFLINE_ATTEMPTS for key in ("blocked_attempts", "allowed_local_attempts")):
        raise AcceptanceError("offline child probe counters are invalid")
    blocked_count = sum(item["outcome"] == "blocked" for item in report["attempts"])
    allowed_count = sum(item["outcome"] == "allowed_local" for item in report["attempts"])
    if report["blocked_attempts"] < blocked_count or report["allowed_local_attempts"] < allowed_count:
        raise AcceptanceError("offline child probe counters are inconsistent")
    if not report["attempts_truncated"] and (report["blocked_attempts"] != blocked_count or report["allowed_local_attempts"] != allowed_count):
        raise AcceptanceError("offline child probe counters are inconsistent")
    sanitized = dict(value)
    sanitized["destination"] = _evidence_token(value["destination"])
    sanitized["report"] = _sanitize_offline_report(report)
    return sanitized


def _run_render(
    repo_root: Path,
    source: str,
    state_dir: Path,
    *,
    attempt: str,
    resource_limits: Mapping[str, int] | None = None,
    query: str | None = None,
    artifact_digest: str | None = None,
    aggregate_budget: _AggregateResourceBudget | None = None,
) -> dict[str, Any]:
    query_value = _DEFAULT_QUERY if query is None else query
    expected = artifact_digest
    if expected is None:
        try:
            expected = _sha_bytes(_secure_file_bytes(repo_root, "perseus.py"))
        except (OSError, TypeError, ValueError, AcceptanceError):
            raise AcceptanceError("perseus_artifact_unavailable") from None
    started = time.perf_counter()
    limits = _validate_child_limits(resource_limits)
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
            monitor_dirs=(workspace, state_dir, repo_root),
            disk_limit_bytes=limits["file_bytes"],
            offline_required=True,
            aggregate_budget=aggregate_budget,
        )
        staged_ok = True
        try:
            _verify_staged_file(staged_runtime, expected, workspace=workspace)
        except AcceptanceError:
            staged_ok = False
        _restore_stage_permissions(workspace)
        try:
            post_digest = _sha_bytes(_secure_file_bytes(repo_root, "perseus.py"))
        except (OSError, TypeError, ValueError, AcceptanceError):
            post_digest = None
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    output = result["stdout"].encode("utf-8", errors="replace")
    status = "passed" if result["status"] == "passed" and result["exit_code"] == 0 and "@date" not in result["stdout"] and not result["stdout_truncated"] and not result["stderr_truncated"] and result.get("offline_sandbox") == "seccomp" else "failed"
    if post_digest != expected or staged_digest != expected or not staged_ok:
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
        "offline_sandbox": result.get("offline_sandbox"),
        "offline_report": result.get("offline_report"),
        "offline_guard": result.get("offline_guard"),
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
    aggregate_budget: _AggregateResourceBudget | None = None,
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
            runtime_expected = _sha_bytes(_secure_file_bytes(root, "perseus.py"))
            staged_runtime, runtime_digest = _stage_runtime(root, workspace, expected=runtime_expected)
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
                monitor_dirs=(workspace, root),
                disk_limit_bytes=disk_limit_bytes,
                offline_required=True,
                aggregate_budget=aggregate_budget,
            )
            _verify_staged_file(staged_artifact, actual, workspace=workspace)
            _verify_staged_file(staged_runtime, runtime_digest, workspace=workspace)
            _restore_stage_permissions(workspace)
            try:
                post_digest = _sha_bytes(_secure_file_bytes(root, spec["path"]))
            except (OSError, TypeError, ValueError, AcceptanceError):
                post_digest = None
            try:
                post_runtime_digest = _sha_bytes(_secure_file_bytes(root, "perseus.py"))
            except (OSError, TypeError, ValueError, AcceptanceError):
                post_runtime_digest = None
            value: dict[str, Any] = {
                "status": "blocked",
                "exit_code": operation.get("exit_code"),
                "artifact_sha256": actual,
                "runtime_artifact_sha256": runtime_expected,
                "runtime_post_sha256": post_runtime_digest,
                "version": version,
                "output_truncated": bool(operation.get("stdout_truncated") or operation.get("stderr_truncated")),
                "resource_limits": dict(resource_limits),
                "child_cpu_seconds_observed": operation.get("child_cpu_seconds_observed", 0.0),
                "child_peak_rss_mb_observed": operation.get("child_peak_rss_mb_observed", 0.0),
                "offline_sandbox": operation.get("offline_sandbox"),
                "offline_report": operation.get("offline_report"),
                "offline_guard": operation.get("offline_guard"),
                "query_sha256": _sha(query_value),
            }
            if post_digest != actual or post_runtime_digest != runtime_expected:
                value["reason"] = "adapter_artifact_changed_during_operation"
            elif operation.get("status") != "passed" or operation.get("exit_code") != 0:
                value["reason"] = "adapter_operation_failed"
            elif operation.get("stderr") or value["output_truncated"] or operation.get("offline_sandbox") != "seccomp":
                value["reason"] = "adapter_offline_guard_unavailable"
            else:
                try:
                    receipt = _parse_operation_receipt(
                        operation.get("stdout", ""), action=name, version=version,
                        artifact_sha256=actual, query=query_value, workspace=workspace,
                    )
                except AcceptanceError:
                    receipt = None
                if receipt is None:
                    value["reason"] = "adapter_operation_receipt_invalid"
                else:
                    value.update({
                        "status": "passed", "operation_receipt_sha256": _sha(receipt),
                        "operation_receipt_persisted": True,
                        "operation_persisted_state_sha256": receipt["persisted_state"]["sha256"],
                    })
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


def _artifact_by_name(artifacts: list[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    matches = [entry for entry in artifacts if entry.get("name") == name]
    if len(matches) != 1:
        raise AcceptanceError("artifact_manifest_incomplete")
    return matches[0]


def _run_workload_query(
    root: Path,
    out: Path,
    query: str,
    workload_digest: str,
    artifact_digest: str,
    restart_count: int,
    resource_limits: Mapping[str, int],
    aggregate_budget: _AggregateResourceBudget | None = None,
) -> dict[str, Any]:
    """Execute the declared query dispatch and bind its inputs in the result."""
    query_digest = _sha(query)
    with tempfile.TemporaryDirectory(prefix=".perseus-query-", dir=str(out)) as workspace_name:
        workspace = Path(workspace_name)
        staged_runtime, staged_digest = _stage_runtime(root, workspace, expected=artifact_digest)
        code = (
            "import json,os; "
            "value={'query_sha256': os.environ.get('PERSEUS_WORKLOAD_QUERY_SHA256'), "
            "'workload_digest': os.environ.get('PERSEUS_WORKLOAD_DIGEST'), "
            "'artifact_sha256': os.environ.get('PERSEUS_ARTIFACT_SHA256'), "
            "'restart_count': int(os.environ.get('PERSEUS_RESTART_COUNT', '-1'))}; "
            "print(json.dumps(value, sort_keys=True, separators=(',', ':')))"
        )
        env = dict(os.environ)
        env.pop("PERSEUS_ALLOW_DANGEROUS", None)
        env.update({
            "PERSEUS_OFFLINE": "1",
            "PERSEUS_OFFLINE_RUNTIME": str(staged_runtime),
            "PERSEUS_WORKLOAD_QUERY": query,
            "PERSEUS_WORKLOAD_QUERY_SHA256": query_digest,
            "PERSEUS_WORKLOAD_DIGEST": workload_digest,
            "PERSEUS_ARTIFACT_SHA256": artifact_digest,
            "PERSEUS_RESTART_COUNT": str(restart_count),
        })
        result = _run_bounded_child(
            [sys.executable, "-c", code],
            cwd=workspace,
            timeout=15,
            env=env,
            resource_limits=resource_limits,
            monitor_dirs=(workspace, out, root),
            disk_limit_bytes=resource_limits["file_bytes"],
            offline_required=True,
            aggregate_budget=aggregate_budget,
        )
        staged_ok = True
        try:
            _verify_staged_file(staged_runtime, staged_digest, workspace=workspace)
        except AcceptanceError:
            staged_ok = False
        _restore_stage_permissions(workspace)
    value: dict[str, Any] = {
        "status": "blocked",
        "exit_code": result.get("exit_code"),
        "query_sha256": query_digest,
        "workload_digest": workload_digest,
        "artifact_sha256": artifact_digest,
        "restart_count": restart_count,
        "output_sha256": _stable_output_digest(result.get("stdout", "").encode("utf-8", errors="replace")),
        "output_truncated": bool(result.get("stdout_truncated") or result.get("stderr_truncated")),
        "offline_sandbox": result.get("offline_sandbox"),
        "offline_report": result.get("offline_report"),
        "offline_guard": result.get("offline_guard"),
    }
    try:
        observed = json.loads(result.get("stdout", ""), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, json.JSONDecodeError):
        observed = None
    if (
        result.get("status") == "passed"
        and result.get("exit_code") == 0
        and not result.get("stdout_truncated")
        and not result.get("stderr_truncated")
        and result.get("offline_sandbox") == "seccomp"
        and staged_ok
        and isinstance(observed, Mapping)
        and dict(observed) == {
            "artifact_sha256": artifact_digest,
            "query_sha256": query_digest,
            "restart_count": restart_count,
            "workload_digest": workload_digest,
        }
    ):
        value["status"] = "passed"
    else:
        value["reason"] = "offline_report_invalid" if result.get("offline_report") is None else "child_spawn_failed"
    return value


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
    aggregate_budget = _AggregateResourceBudget(
        (root, out),
        cpu_seconds=float(fixture["platform"]["resource_limits"]["cpu_seconds"]),
        memory_mb=float(fixture["platform"]["resource_limits"]["memory_mb"]),
        disk_bytes=int(math.ceil(float(fixture["platform"]["resource_limits"]["disk_mb"]) * 1024 * 1024)),
    )
    before_cpu = time.process_time()
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    before_disk = _directory_size(out)
    started = time.perf_counter()
    artifacts = _artifact_manifest(root, fixture)
    perseus_artifact = _artifact_by_name(artifacts, "perseus")
    if perseus_artifact["state"] != "available":
        raise AcceptanceError("required_perseus_artifact_unavailable")
    artifact_specs = {entry["name"]: entry for entry in fixture["artifacts"]}
    workload = fixture["workload"]
    workload_query = workload["query"]
    workload_digest = _sha(workload)
    workload_query_digest = _sha(workload_query)
    restart_count = workload["restart_count"]
    flow = {
        "workload_query": _run_workload_query(
            root, out, workload_query, workload_digest, perseus_artifact["sha256"],
            restart_count, child_limits, aggregate_budget,
        ),
        "perseus_render": _run_render(
            root, workload["source"], state_dir, attempt="initial", resource_limits=child_limits,
            query=workload_query, artifact_digest=perseus_artifact["sha256"], aggregate_budget=aggregate_budget,
        ),
    }
    flow["vault"] = _run_adapter(
        root, artifact_specs["perseus-vault"], _artifact_by_name(artifacts, "perseus-vault"),
        child_limits, monitor_dir=out, disk_limit_bytes=child_limits["file_bytes"], query=workload_query, aggregate_budget=aggregate_budget,
    )
    flow["ledger"] = _run_adapter(
        root, artifact_specs["perseus-ledger"], _artifact_by_name(artifacts, "perseus-ledger"),
        child_limits, monitor_dir=out, disk_limit_bytes=child_limits["file_bytes"], query=workload_query, aggregate_budget=aggregate_budget,
    )
    if restart_count == 0:
        flow["restart_recovery"] = {
            "status": "not_run", "reason": "restart_count_zero", "checked": True,
            "restart_count": restart_count, "query_sha256": workload_query_digest,
            "workload_digest": workload_digest, "artifact_sha256": perseus_artifact["sha256"],
        }
    else:
        for restart_index in range(1, restart_count + 1):
            flow[f"restart_recovery_{restart_index}"] = _run_render(
                root, workload["source"], state_dir, attempt=f"restart-{restart_index}",
                resource_limits=child_limits, query=workload_query, artifact_digest=perseus_artifact["sha256"], aggregate_budget=aggregate_budget,
            )
    backup = out / "backup-state"
    backup_digest: str | None = None
    restored_digest: str | None = None
    post_restore_digest: str | None = None
    digest_match = post_digest_match = False
    restore: dict[str, Any] = {"status": "blocked", "reason": "backup_restore_failed"}
    restore_error: str | None = None
    try:
        _copytree_bounded(state_dir, backup)
        backup_digest = _sha(_sorted_files(backup))
        shutil.rmtree(state_dir)
        _copytree_bounded(backup, state_dir)
        restored_digest = _sha(_sorted_files(state_dir))
        digest_match = restored_digest == backup_digest
        restore = _run_render(
            root, workload["source"], state_dir, attempt="restore", resource_limits=child_limits,
            query=workload_query, artifact_digest=perseus_artifact["sha256"], aggregate_budget=aggregate_budget,
        )
        post_restore_digest = _sha(_sorted_files(state_dir))
        post_digest_match = post_restore_digest == backup_digest
    except (OSError, TypeError, ValueError, AcceptanceError):
        restore_error = "backup_restore_failed"
        restore = {"status": "blocked", "reason": restore_error}
    binding_material = {
        "backup_digest": backup_digest,
        "restored_digest": restored_digest,
        "post_restore_digest": post_restore_digest,
        "digest_match": digest_match,
        "post_digest_match": post_digest_match,
        "render_status": restore.get("status"),
        "render_exit_code": restore.get("exit_code"),
        "render_output_sha256": restore.get("output_sha256"),
        "render_query_sha256": restore.get("query_sha256"),
        "artifact_sha256": perseus_artifact["sha256"],
        "workload_digest": workload_digest,
        "restart_count": restart_count,
    }
    restore_passed = restore_error is None and digest_match and post_digest_match and restore.get("status") == "passed"
    flow["backup_restore"] = {
        "status": "passed" if restore_passed else "failed",
        "reason": "operation_completed" if restore_passed else "restore_state_mismatch" if restore_error is None else restore_error,
        "backup_digest": backup_digest,
        "restored_digest": restored_digest,
        "digest_match": digest_match,
        "post_restore_digest": post_restore_digest,
        "post_digest_match": post_digest_match,
        "result_binding": {**binding_material, "binding_sha256": _sha(binding_material)},
        "restored": state_dir.exists() and not state_dir.is_symlink(),
        "render": restore,
    }
    for cell in flow.values():
        if isinstance(cell, dict):
            cell.setdefault("workload_digest", workload_digest)
            cell.setdefault("query_sha256", workload_query_digest)
            cell.setdefault("restart_count", restart_count)
            cell.setdefault("artifact_sha256", perseus_artifact["sha256"])
    upgrade_spec = workload.get("upgrade_bundle")
    rollback_spec = workload.get("rollback_bundle")
    upgrade = _check_bundle(
        root, upgrade_spec, "upgrade", execute=True, resource_limits=child_limits, monitor_dir=out,
        disk_limit_bytes=child_limits["file_bytes"], query=workload_query, aggregate_budget=aggregate_budget,
    ) if isinstance(upgrade_spec, Mapping) else {"status": "not_run", "reason": "upgrade_bundle_undeclared", "checked": False}
    rollback = _check_bundle(
        root, rollback_spec, "rollback", execute=True, resource_limits=child_limits, monitor_dir=out,
        disk_limit_bytes=child_limits["file_bytes"], query=workload_query, aggregate_budget=aggregate_budget,
    ) if isinstance(rollback_spec, Mapping) else {"status": "not_run", "reason": "rollback_bundle_undeclared", "checked": False}
    probe: dict[str, Any]
    probe_result: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(prefix=".perseus-probe-", dir=str(out)) as probe_workspace_name:
            probe_workspace = Path(probe_workspace_name)
            staged_probe_runtime, probe_digest = _stage_file(
                root, "perseus.py", probe_workspace, expected=perseus_artifact["sha256"]
            )
            probe_env = {
                **dict(os.environ),
                "PERSEUS_OFFLINE": "1",
                "PERSEUS_OFFLINE_RUNTIME": str(staged_probe_runtime),
                "PERSEUS_WORKLOAD_QUERY": workload_query,
                "PERSEUS_WORKLOAD_QUERY_SHA256": workload_query_digest,
            }
            probe = _run_bounded_child(
                [sys.executable, str(staged_probe_runtime), "--offline", "offline-probe", "https://example.invalid/disconnected-probe", "--json"],
                cwd=probe_workspace,
                timeout=15,
                env=probe_env,
                resource_limits=child_limits,
                monitor_dirs=(probe_workspace, out, root),
                disk_limit_bytes=child_limits["file_bytes"],
                offline_required=True,
                aggregate_budget=aggregate_budget,
            )
            try:
                _verify_staged_file(staged_probe_runtime, probe_digest, workspace=probe_workspace)
            except AcceptanceError:
                probe["status"] = "blocked"
                probe["reason"] = "offline_guard_unavailable"
            _restore_stage_permissions(probe_workspace)
        if (
            probe.get("status") != "passed"
            or probe.get("exit_code") != 0
            or probe.get("stdout_truncated")
            or probe.get("stderr_truncated")
        ):
            raise AcceptanceError("offline_child_probe_failed")
        probe_result = _parse_child_probe_json(probe.get("stdout", ""))
    except (OSError, TypeError, ValueError, AcceptanceError):
        probe = {
            "status": "blocked", "exit_code": None, "offline_sandbox": None,
            "offline_report": None, "offline_guard": {"enforced": False, "boundary": None, "report_present": False},
            "reason": "offline_guard_unavailable",
        }
        probe_result = {
            "blocked": False, "destination": _evidence_token("probe"),
            "report": {
                "active": False, "policy": "deny_all_non_loopback", "attempts": [],
                "attempts_truncated": True, "blocked_attempts": 0, "allowed_local_attempts": 0,
            },
        }
    network_probe = probe_result["report"]
    blocked = [item for item in network_probe["attempts"] if item["outcome"] == "blocked"]
    unexpected = [item for item in network_probe["attempts"] if item["outcome"] not in {"blocked", "allowed_local"}]
    child_reports = {
        key: value["offline_report"]
        for key, value in flow.items()
        if isinstance(value, Mapping) and isinstance(value.get("offline_report"), Mapping)
    }
    child_guards = {
        key: value["offline_guard"]
        for key, value in flow.items()
        if isinstance(value, Mapping) and isinstance(value.get("offline_guard"), Mapping)
    }
    for key, value in (("upgrade", upgrade), ("rollback", rollback), ("probe", probe)):
        if isinstance(value, Mapping) and isinstance(value.get("offline_report"), Mapping):
            child_reports[key] = value["offline_report"]
        if isinstance(value, Mapping) and isinstance(value.get("offline_guard"), Mapping):
            child_guards[key] = value["offline_guard"]
    executed_guards = [guard for guard in child_guards.values() if isinstance(guard, Mapping)]
    child_attempts = [attempt for report in child_reports.values() for attempt in report.get("attempts", [])]
    guards_enforced = bool(executed_guards) and all(guard.get("enforced") is True and guard.get("boundary") == "seccomp" for guard in executed_guards)
    reports_bounded = all(
        report.get("active") is True and report.get("attempts_truncated") is False
        for report in child_reports.values()
    ) if child_reports else False
    network = {
        "policy": "deny_all",
        "attempts": network_probe["attempts"],
        "child_attempts": child_attempts,
        "children": child_reports,
        "child_guards": child_guards,
        "attempts_truncated": network_probe.get("attempts_truncated", False),
        "expected_blocked": blocked,
        "unexpected_attempts": unexpected,
        "child_probe": {"status": probe.get("status"), "exit_code": probe.get("exit_code"), "report": probe_result},
        "status": "passed" if blocked and not unexpected and not network_probe.get("attempts_truncated", False) and guards_enforced and reports_bounded else "failed",
    }
    resource_envelope = _validate_resource_envelope(_resource_envelope(before_cpu, before_rss, before_disk, out, started), fixture)
    resource_envelope["aggregate_children"] = aggregate_budget.report()
    negative_results = [
        {"cell": "vault", "status": flow["vault"]["status"], "reason": _bounded_reason(flow["vault"].get("reason"), "operation_completed")},
        {"cell": "ledger", "status": flow["ledger"]["status"], "reason": _bounded_reason(flow["ledger"].get("reason"), "operation_completed")},
        {"cell": "upgrade", "status": upgrade["status"], "reason": _bounded_reason(upgrade.get("reason"), "operation_completed")},
        {"cell": "rollback", "status": rollback["status"], "reason": _bounded_reason(rollback.get("reason"), "operation_completed")},
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
    def _publication_projection(value: Any) -> Any:
        if isinstance(value, Mapping):
            projected: dict[str, Any] = {}
            for key, item in value.items():
                if key == "reason":
                    if item is not None:
                        projected[key] = _bounded_reason(item)
                    continue
                if key in {"stdout", "stderr", "argv", "command"}:
                    continue
                projected[key] = _publication_projection(item)
            return projected
        if isinstance(value, list):
            return [_publication_projection(item) for item in value]
        return value

    flow_commitment = {
        key: _publication_projection(value)
        for key, value in flow.items()
        if isinstance(value, Mapping)
    }
    resource_observations_commitment = _sha({
        "resource_envelope": resource_envelope,
        "flow": {
            key: _publication_projection(value)
            for key, value in flow.items()
            if isinstance(value, Mapping)
        },
    })
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
            "aggregate_resource_observed": aggregate_budget.report(),
            "measurement_status": resource_envelope.get("measurement_status"),
            "resource_observations_commitment": resource_observations_commitment,
            "volatile_observations": [
                "child_cpu_seconds_observed", "child_peak_rss_mb_observed",
                "cpu_seconds_observed", "peak_rss_mb_observed", "wall_seconds_observed",
            ],
        },
        "resource_envelope": resource_envelope,
        "upgrade": upgrade,
        "rollback": rollback,
        "negative_results": negative_results,
        "claims": claims,
        "manifest_commitment": manifest_commitment,
        "workload_digest": workload_digest,
        "workload_query_digest": workload_query_digest,
    }
    report_commitment = _sha(report_core)
    stable_flow_commitment = {key: _stable_projection(value) for key, value in flow_commitment.items()}
    stable_report_core = dict(report_core)
    stable_report_core["flow_commitment"] = stable_flow_commitment
    stable_report_core.pop("resource_envelope", None)
    stable_resource_contract = _stable_projection(stable_report_core["resource_contract"])
    stable_resource_contract.pop("resource_observations_commitment", None)
    stable_report_core["resource_contract"] = stable_resource_contract
    stable_report_commitment = _sha(stable_report_core)

    evidence_digest = _sha({
        "manifest_commitment": manifest_commitment,
        "stable_report_commitment": stable_report_commitment,
        "workload_digest": workload_digest,
        "workload_query_digest": workload_query_digest,
        "artifacts": artifacts,
        "flow": _stable_projection(flow_commitment),
        "backup_digest": flow.get("backup_restore", {}).get("backup_digest"),
        "network": _stable_projection(network),
        "claims_ceiling": fixture["claims_ceiling"],
        "claims": claims,
        "upgrade": _stable_projection(upgrade),
        "rollback": _stable_projection(rollback),
        "negative_results": negative_results,
    })
    report = {
        **report_core,
        "flow": flow,
        "resource_envelope": resource_envelope,
        "manifest_commitment": manifest_commitment,
        "report_commitment": report_commitment,
        "stable_report_commitment": stable_report_commitment,
        "evidence_digest": evidence_digest,
    }
    manifest = {**manifest_core, "manifest_commitment": manifest_commitment, "report_commitment": report_commitment, "stable_report_commitment": stable_report_commitment}
    (out / "manifest.json").write_text(_json(manifest) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if temp_context is not None:
        # Keep the return value useful while avoiding a temp-directory path in
        # public evidence. The caller receives the report, not host paths.
        temp_context.cleanup()
    return report


def _sorted_files(root: Path, *, max_total_bytes: int = _MAX_PARENT_TOTAL_BYTES) -> list[dict[str, Any]]:
    if type(max_total_bytes) is not int or max_total_bytes <= 0:
        raise AcceptanceError("parent_read_limit_invalid")
    if root.is_symlink() or not root.is_dir():
        raise AcceptanceError("backup_state_invalid")
    paths: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        for name in list(dirnames):
            candidate = Path(directory) / name
            if candidate.is_symlink():
                raise AcceptanceError("backup_state_symlink")
        for name in filenames:
            candidate = Path(directory) / name
            if candidate.is_symlink() or not candidate.is_file():
                raise AcceptanceError("backup_state_invalid")
            paths.append(candidate)
    result = []
    total = 0
    for path in sorted(paths):
        rel = path.relative_to(root)
        data = _secure_file_bytes(root, str(rel), max_bytes=_MAX_PARENT_FILE_BYTES)
        total += len(data)
        if total > max_total_bytes:
            raise AcceptanceError("parent_read_limit_exceeded")
        result.append({"path": str(rel).replace(os.sep, "/"), "sha256": _sha_bytes(data), "size": len(data)})
    return result


def _copytree_bounded(source: Path, target: Path, *, max_total_bytes: int = _MAX_PARENT_TOTAL_BYTES) -> None:
    entries = _sorted_files(source, max_total_bytes=max_total_bytes)
    target.mkdir(parents=True, exist_ok=False)
    total = 0
    for entry in entries:
        rel = Path(entry["path"])
        data = _secure_file_bytes(source, entry["path"], max_bytes=_MAX_PARENT_FILE_BYTES)
        total += len(data)
        if total > max_total_bytes:
            raise AcceptanceError("parent_read_limit_exceeded")
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(data)
        if _sha_bytes(_secure_file_bytes(target, entry["path"], max_bytes=_MAX_PARENT_FILE_BYTES)) != entry["sha256"]:
            raise AcceptanceError("backup_copy_digest_mismatch")


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
    except (OSError, TypeError, ValueError, KeyError, IndexError, StopIteration, subprocess.SubprocessError, AcceptanceError) as exc:
        text = str(exc)
        if text.startswith("fixture could not be loaded"):
            code = "fixture_load_failed"
        elif "offline" in text and "guard" in text:
            code = "offline_guard_unavailable"
        elif "restore" in text or "backup" in text:
            code = "backup_restore_failed"
        else:
            code = "contract_invalid"
        print(f"DISCONNECTED ACCEPTANCE BLOCKED: {_bounded_reason(code)}")
        return 1
    print(json.dumps(report, indent=2, sort_keys=True) if args.json or not args.output else f"DISCONNECTED ACCEPTANCE {report['status'].upper()}: {report['evidence_digest']}")
    return 0 if report["status"] == "passed" or (report["status"] == "partial" and args.allow_partial) else 1


if __name__ == "__main__":
    raise SystemExit(main())
