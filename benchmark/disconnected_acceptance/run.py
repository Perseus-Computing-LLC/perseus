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
try:
    import resource
except ModuleNotFoundError:  # pragma: no cover - POSIX-only stdlib module
    resource = None
import secrets
import shutil
import select
import signal
import socket
import stat
import subprocess
import struct
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
_OPERATION_STATE_PATH = "state.json"
_CLAIMS_CEILING = {
    "local_offline_capable": "observed_only",
    "iron_bank_submitted": "not_claimed",
    "iron_bank_assessed": "not_claimed",
    "customer_platform_deployable": "not_established",
    "ato_il5_il6": "not_claimed",
}
_REPORT_CORE_KEYS = (
    "schema_version", "status", "fixture_id", "platform", "artifacts",
    "flow_commitment", "flow_projection_commitment", "network", "resource_contract",
    "resource_envelope", "upgrade", "rollback", "negative_results", "claims",
    "claims_ceiling", "manifest_commitment", "workload_digest", "workload_query_digest",
)
_CHILD_LIMITS = {"cpu_seconds": 30, "address_space_bytes": 512 * 1024 * 1024, "file_bytes": 16 * 1024 * 1024}
_MAX_CHILD_OUTPUT_BYTES = 64 * 1024
_MAX_CHILD_ERROR_BYTES = 64 * 1024
_MAX_PARENT_FILE_BYTES = 16 * 1024 * 1024
_MAX_PARENT_TOTAL_BYTES = 64 * 1024 * 1024
_MAX_OFFLINE_REPORT_BYTES = 64 * 1024
_MAX_REPORT_BYTES = 4 * 1024 * 1024
_OFFLINE_REPORT_READ_TIMEOUT_SECONDS = 0.5
_MAX_OFFLINE_ATTEMPTS = 256
_MAX_FIXTURE_CPU_SECONDS = 300
_MAX_FIXTURE_MEMORY_MB = 4096
_MAX_FIXTURE_DISK_MB = 4096
_MAX_FIXTURE_RESTART_COUNT = 32
_MAX_FIXTURE_BYTES = 1024 * 1024
_MAX_FIXTURE_ID_BYTES = 128
_MAX_FIXTURE_TEXT_BYTES = 4096
_MAX_FIXTURE_PATH_BYTES = 512
_CGROUP_ROOT_ENV = "PERSEUS_ACCEPTANCE_CGROUP_ROOT"
_CGROUP_BROKER_ENV = "PERSEUS_ACCEPTANCE_CGROUP_BROKER"
_MAX_CGROUP_BROKER_FRAME_BYTES = 64 * 1024
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
_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_RULE_PATH_BENEATH = 1
_LANDLOCK_ACCESS_FS_WRITE = (
    (1 << 1)  # WRITE_FILE
    | (1 << 4)  # REMOVE_DIR
    | (1 << 5)  # REMOVE_FILE
    | (1 << 6)  # MAKE_CHAR
    | (1 << 7)  # MAKE_DIR
    | (1 << 8)  # MAKE_REG
    | (1 << 9)  # MAKE_SOCK
    | (1 << 10)  # MAKE_FIFO
    | (1 << 11)  # MAKE_BLOCK
    | (1 << 12)  # MAKE_SYM
    | (1 << 13)  # REFER
    | (1 << 14)  # TRUNCATE
)


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


def _landlock_supported() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        result = libc.syscall(_LANDLOCK_CREATE_RULESET, None, 0, _LANDLOCK_CREATE_RULESET_VERSION)
        return result >= 1
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _install_landlock_write_sandbox(allowed_roots: tuple[Path, ...] | list[Path]) -> None:
    """Restrict writes to parent-declared roots using Linux Landlock."""
    if not sys.platform.startswith("linux") or not allowed_roots:
        raise OSError("filesystem containment primitive is unavailable")
    import ctypes

    class _RulesetAttr(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class _PathBeneath(ctypes.Structure):
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int), ("padding", ctypes.c_uint32)]

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    attr = _RulesetAttr(_LANDLOCK_ACCESS_FS_WRITE)
    ruleset_fd = libc.syscall(
        _LANDLOCK_CREATE_RULESET,
        ctypes.byref(attr),
        ctypes.sizeof(attr),
        0,
    )
    if ruleset_fd < 0:
        raise OSError(ctypes.get_errno(), "landlock ruleset unavailable")
    root_fds: list[int] = []
    try:
        flags = getattr(os, "O_PATH", 0) | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
        if not getattr(os, "O_PATH", 0):
            raise OSError("landlock path handles unavailable")
        for raw_root in allowed_roots:
            root = Path(raw_root).resolve()
            fd = os.open(root, flags)
            root_fds.append(fd)
            rule = _PathBeneath(_LANDLOCK_ACCESS_FS_WRITE, fd, 0)
            if libc.syscall(
                _LANDLOCK_ADD_RULE,
                ruleset_fd,
                _LANDLOCK_RULE_PATH_BENEATH,
                ctypes.byref(rule),
                0,
            ) < 0:
                raise OSError(ctypes.get_errno(), "landlock path rule unavailable")
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")
        if libc.syscall(_LANDLOCK_RESTRICT_SELF, ruleset_fd, 0) < 0:
            raise OSError(ctypes.get_errno(), "landlock restrict-self failed")
    finally:
        for fd in root_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.close(ruleset_fd)
        except OSError:
            pass


def _python_startup_bypasses_sitecustomize(argv: list[str]) -> bool:
    """Return true for interpreter forms that ignore the audit hook."""
    if not _is_python_argv(argv):
        return False
    for token in argv[1:]:
        if token == "-c" or (not token.startswith("-") and token):
            break
        if token in {"-S", "-I", "-E"} or (token.startswith("-") and any(flag in token[1:] for flag in "SIE")):
            return True
    return False
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


def _parent_safe_destination(value: str) -> str:
    """Mirror the runtime's bounded host/path projection without trusting it."""
    lowered = value.casefold()
    safe_bare_host = bool(re.fullmatch(r"[A-Za-z0-9.-]+", value)) and "." in value
    if (
        (safe_bare_host or lowered in {"localhost", "::1", "127.0.0.1"})
        and len(value) <= 256
        and not any(token in lowered for token in ("secret", "token", "password", "passwd", "credential", "api_key", "apikey"))
    ):
        return value
    return _evidence_token(value)


def _parent_derived_offline_report(argv: list[str]) -> dict[str, Any]:
    """Build the only report shape the parent is willing to publish.

    The child-side Python hooks are telemetry, not an authority: code running
    in the child can open the inherited pipe and emit any bytes it wants.  The
    parent therefore derives the expected report from the declared operation
    itself and only accepts child telemetry when it is an exact match.  This
    preserves useful evidence for the explicit probe and the small, declared
    DNS fixture while ensuring child-controlled counters or strings can never
    enter authoritative evidence.
    """
    attempts: list[dict[str, str]] = []
    if "-c" in argv:
        try:
            code = argv[argv.index("-c") + 1]
        except (ValueError, IndexError):
            code = ""
        match = re.search(
            r"(?:gethostbyname(?:_ex)?|getaddrinfo)\(\s*(['\"])([^'\"]+)\1",
            code,
        )
        if match:
            attempts.append({"operation": "dns", "destination": _parent_safe_destination(match.group(2)), "outcome": "blocked"})
    return {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": attempts,
        "attempts_truncated": False,
        "blocked_attempts": len(attempts),
        "allowed_local_attempts": 0,
    }


def _parent_derived_probe_result(destination: str) -> dict[str, Any]:
    """Return the parent-derived public result for the declared probe."""
    safe_destination = _parent_safe_destination(destination)
    report = {
        "active": True,
        "policy": "deny_all_non_loopback",
        "attempts": [{"operation": "probe", "destination": safe_destination, "outcome": "blocked"}],
        "attempts_truncated": False,
        "blocked_attempts": 1,
        "allowed_local_attempts": 0,
    }
    return {
        "blocked": True,
        "destination": _evidence_token(safe_destination),
        "report": _sanitize_offline_report(report),
    }


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
        "child_containment_unavailable",
        "child_resource_limit",
        "child_spawn_failed",
        "contract_invalid",
        "fixture_load_failed",
        "filesystem_sandbox_unavailable",
        "filesystem_observation_unavailable",
        "offline_guard_unavailable",
        "offline_report_invalid",
        "operation_completed",
        "operation_blocked",
        "operation_failed",
        "operation_not_run",
        "operation_status_invalid",
        "operation_unavailable",
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


_UNAVAILABLE_REASONS = frozenset({
    "child_containment_unavailable",
    "filesystem_observation_unavailable",
    "filesystem_sandbox_unavailable",
    "offline_guard_unavailable",
    "offline_sandbox_unavailable",
    "restart_count_zero",
    "rollback_bundle_undeclared",
    "upgrade_bundle_undeclared",
})


def _negative_result_reason(value: Mapping[str, Any] | Any) -> str:
    """Normalize negative cells without ever assigning a success reason."""
    status = value.get("status") if isinstance(value, Mapping) else None
    supplied = value.get("reason") if isinstance(value, Mapping) else None
    if status == "passed":
        return _bounded_reason(supplied, "operation_completed")
    fallback = {
        "blocked": "operation_blocked",
        "failed": "operation_failed",
        "unavailable": "operation_unavailable",
        "not_run": "operation_not_run",
        "timeout": "operation_failed",
        "resource_limit": "operation_failed",
    }.get(status, "operation_status_invalid")
    normalized = _bounded_reason(supplied, fallback)
    return fallback if normalized == "operation_completed" else normalized


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
        raw = path.read_bytes()
        if len(raw) > _MAX_FIXTURE_BYTES:
            raise AcceptanceError("fixture_too_large")
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except AcceptanceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise AcceptanceError("fixture_load_failed") from None
    if not isinstance(value, Mapping) or set(value) != _REQUIRED_FIXTURE_KEYS or value.get("schema_version") != _SCHEMA:
        raise AcceptanceError("fixture shape or schema is invalid")
    fixture_id = value.get("fixture_id")
    if (
        not isinstance(fixture_id, str)
        or not fixture_id.strip()
        or len(fixture_id.encode("utf-8")) > _MAX_FIXTURE_ID_BYTES
    ):
        raise AcceptanceError("fixture_id must be a bounded non-empty string")
    platform = value.get("platform")
    if not isinstance(platform, Mapping) or set(platform) != _PLATFORM_KEYS:
        raise AcceptanceError("fixture platform shape is invalid")
    if not all(
        isinstance(platform.get(key), str)
        and platform[key].strip()
        and len(platform[key].encode("utf-8")) <= _MAX_FIXTURE_TEXT_BYTES
        for key in ("os", "python")
    ) or platform.get("network_policy") != "deny_all":
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
    if (
        not isinstance(workload.get("source"), str)
        or not workload["source"].strip()
        or len(workload["source"].encode("utf-8")) > _MAX_FIXTURE_TEXT_BYTES
        or not isinstance(workload.get("query"), str)
        or not workload["query"].strip()
        or len(workload["query"].encode("utf-8")) > _MAX_FIXTURE_TEXT_BYTES
    ):
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
        if (
            not isinstance(artifact.get("name"), str)
            or not artifact["name"].strip()
            or len(artifact["name"].encode("utf-8")) > _MAX_FIXTURE_TEXT_BYTES
            or artifact["name"] in names
        ):
            raise AcceptanceError("artifact names must be unique non-empty strings")
        if not isinstance(artifact.get("path"), str) or not artifact["path"].strip():
            raise AcceptanceError("artifact path must be a string")
        rel = Path(artifact["path"])
        if (
            len(artifact["path"].encode("utf-8")) > _MAX_FIXTURE_PATH_BYTES
            or not rel.parts
            or rel == Path(".")
            or rel.is_absolute()
            or ".." in rel.parts
            or str(rel) in paths
        ):
            raise AcceptanceError("artifact paths must be safe and unique")
        if not isinstance(artifact.get("required", False), bool):
            raise AcceptanceError("artifact required must be boolean")
        if artifact.get("sbom") is not None and (
            not isinstance(artifact.get("sbom"), str)
            or len(artifact["sbom"].encode("utf-8")) > _MAX_FIXTURE_PATH_BYTES
        ):
            raise AcceptanceError("artifact sbom path must be a bounded string or null")
        if "command" in artifact:
            _validate_command(artifact["command"], f"{artifact['name']} adapter")
        if "version" in artifact and (
            not isinstance(artifact["version"], str)
            or not artifact["version"].strip()
            or len(artifact["version"].encode("utf-8")) > _MAX_FIXTURE_TEXT_BYTES
        ):
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
    resource_module = resource
    if resource_module is None:
        raise AcceptanceError("child_resource_limits_unavailable")

    def apply_limits() -> None:
        limit_specs = (
            (resource_module.RLIMIT_CPU, limits["cpu_seconds"]),
            (resource_module.RLIMIT_AS, limits["address_space_bytes"]),
            (resource_module.RLIMIT_FSIZE, limits["file_bytes"]),
        )
        for kind, value in limit_specs:
            # A disconnected acceptance run must fail closed when a declared
            # containment limit cannot be installed; swallowing this error
            # would turn an observation into an unenforced claim.
            resource_module.setrlimit(kind, (value, value))

    return apply_limits


def _directory_size(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                info = path.stat()
                allocated = int(getattr(info, "st_blocks", 0)) * 512
                total += max(int(info.st_size), allocated)
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
    "disk_growth_bytes_observed",
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


_PUBLIC_DIGEST_KEYS = frozenset({
    "artifact_sha256", "backup_digest", "binding_sha256", "output_sha256",
    "post_restore_digest", "query_sha256", "render_output_sha256",
    "render_query_sha256", "resource_observations_commitment", "restored_digest",
    "workload_digest",
})
_PUBLIC_NUMERIC_KEYS = frozenset({
    "address_space_bytes", "allowed_local_attempts", "blocked_attempts",
    "child_cpu_seconds_observed", "child_peak_rss_mb_observed", "cpu_seconds",
    "cpu_seconds_observed", "disk_growth_bytes_observed", "exit_code", "file_bytes",
    "log_bytes", "operation_child_cpu_seconds_observed", "operation_child_peak_rss_mb_observed",
    "output_bytes", "peak_rss_mb_observed", "restart_count", "stable_output_bytes",
    "startup_ms_observed", "wall_seconds_observed",
})
_PUBLIC_BOOLEAN_KEYS = frozenset({
    "active", "attempts_truncated", "cleanup_failed", "cleanup_verified", "digest_match", "enforced", "log_truncated",
    "output_truncated", "post_digest_match", "report_present", "restored", "stderr_truncated",
})
_PUBLIC_ENUM_VALUES = {
    "boundary": frozenset({"seccomp", "cgroup_broker", "cgroup_v2_sealed"}),
    "offline_sandbox": frozenset({"seccomp"}),
    "policy": frozenset({"deny_all", "deny_all_non_loopback"}),
    "render_status": frozenset({"passed", "blocked", "failed", "unavailable", "not_run", "timeout", "resource_limit", "partial"}),
    "status": frozenset({"passed", "blocked", "failed", "unavailable", "not_run", "timeout", "resource_limit", "partial"}),
    "telemetry": frozenset({"parent_derived", "unavailable"}),
}


def _public_scalar(value: Any, key: str | None) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    if key in _PUBLIC_BOOLEAN_KEYS and type(value) is bool:
        return value
    if key in _PUBLIC_NUMERIC_KEYS and type(value) in {int, float}:
        try:
            if math.isfinite(float(value)):
                return value
        except (OverflowError, TypeError, ValueError):
            pass
    if key in _PUBLIC_DIGEST_KEYS and isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value
    if key == "reason" and isinstance(value, str) and _REASON_CODE_RE.fullmatch(value):
        return value
    if key == "attempt" and isinstance(value, str) and (value in {"initial", "restore"} or re.fullmatch(r"restart-[1-9][0-9]*", value)):
        return value
    if key in _PUBLIC_ENUM_VALUES and isinstance(value, str) and value in _PUBLIC_ENUM_VALUES[key]:
        return value
    return _evidence_token(value)


def _public_projection(value: Any, *, key: str | None = None) -> Any:
    """Project the exact public flow fields used by the release decision."""
    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for item_key, item in value.items():
            if item_key == "reason":
                if item is not None:
                    projected[item_key] = _bounded_reason(item)
                continue
            if item_key in {"stdout", "stderr", "argv", "command"}:
                continue
            projected[item_key] = _public_projection(item, key=item_key)
        if value.get("status") in {"blocked", "failed", "unavailable", "not_run", "timeout", "resource_limit"}:
            projected["reason"] = _negative_result_reason(value)
        return projected
    if isinstance(value, list):
        return [_public_projection(item, key=key) for item in value]
    return _public_scalar(value, key)


def _validate_report_resource_semantics(
    resource_contract: Mapping[str, Any],
    resource_envelope: Mapping[str, Any],
    flow: Mapping[str, Any],
    *,
    expected_limits: Mapping[str, Any] | None = None,
) -> None:
    limits = resource_contract.get("limits")
    if not isinstance(limits, Mapping):
        raise AcceptanceError("resource limits are unavailable")
    if expected_limits is not None and dict(limits) != dict(expected_limits):
        raise AcceptanceError("resource limits are not fixture-bound")
    try:
        ceilings = {
            "cpu_seconds_observed": float(limits["cpu_seconds"]),
            "peak_rss_mb_observed": float(limits["memory_mb"]),
            "disk_growth_bytes_observed": float(limits["disk_mb"]) * 1024 * 1024,
        }
        child_limits = {
            "cpu_seconds": int(math.ceil(float(limits["cpu_seconds"]))),
            "address_space_bytes": int(math.ceil(float(limits["memory_mb"]) * 1024 * 1024)),
            "file_bytes": int(math.ceil(float(limits["disk_mb"]) * 1024 * 1024)),
        }
    except (KeyError, OverflowError, TypeError, ValueError):
        raise AcceptanceError("resource limits are invalid") from None
    if any(not math.isfinite(value) or value <= 0 for value in ceilings.values()):
        raise AcceptanceError("resource limits are invalid")
    required_contract = {
        "limits", "enforced_child_limits", "aggregate_disk_limit_bytes",
        "aggregate_resource_observed", "measurement_status",
        "resource_observations_commitment", "volatile_observations",
    }
    if not required_contract.issubset(resource_contract):
        raise AcceptanceError("resource contract observations are incomplete")
    if resource_contract.get("enforced_child_limits") != child_limits:
        raise AcceptanceError("resource child limits are not fixture-bound")
    if resource_contract.get("aggregate_disk_limit_bytes") != child_limits["file_bytes"]:
        raise AcceptanceError("aggregate disk limit is not fixture-bound")
    if resource_contract.get("measurement_status") != "observed_with_host_metrics":
        raise AcceptanceError("resource measurement status is invalid")
    if set(resource_contract.get("volatile_observations", ())) != {
        "child_cpu_seconds_observed", "child_peak_rss_mb_observed",
        "cpu_seconds_observed", "peak_rss_mb_observed", "wall_seconds_observed",
    }:
        raise AcceptanceError("resource volatile observations are incomplete")

    required_envelope = {
        "cpu_seconds_observed", "peak_rss_mb_observed", "disk_growth_bytes_observed",
        "wall_seconds_observed", "measurement_status", "aggregate_children",
    }
    if not required_envelope.issubset(resource_envelope):
        raise AcceptanceError("resource envelope observations are incomplete")
    if resource_envelope.get("measurement_status") != "observed_with_host_metrics":
        raise AcceptanceError("resource envelope measurement status is invalid")

    def check_mapping(value: Mapping[str, Any], *, prefix: str, require_observations: bool = True) -> None:
        if require_observations and not all(key in value for key in ceilings):
            raise AcceptanceError(f"{prefix}observations are incomplete")
        for key, ceiling in ceilings.items():
            if key not in value:
                continue
            observed = value[key]
            try:
                valid = (
                    type(observed) is not bool
                    and isinstance(observed, (int, float))
                    and math.isfinite(float(observed))
                    and 0 <= float(observed) <= ceiling
                )
            except (OverflowError, TypeError, ValueError):
                valid = False
            if not valid:
                raise AcceptanceError(f"{prefix}{key} exceeds resource ceiling")

    check_mapping(resource_envelope, prefix="resource envelope ")
    wall_seconds = resource_envelope.get("wall_seconds_observed")
    if type(wall_seconds) is bool or not isinstance(wall_seconds, (int, float)) or not math.isfinite(float(wall_seconds)) or wall_seconds < 0:
        raise AcceptanceError("resource envelope wall observation is invalid")
    aggregate = resource_envelope.get("aggregate_children")
    if not isinstance(aggregate, Mapping):
        raise AcceptanceError("aggregate resource envelope is incomplete")
    if aggregate.get("status") not in {"within_limit", "resource_limit", "filesystem_observation_unavailable"}:
        raise AcceptanceError("aggregate resource status is invalid")
    check_mapping(aggregate, prefix="aggregate resource ")
    if resource_contract.get("aggregate_resource_observed") != dict(aggregate):
        raise AcceptanceError("aggregate resource observation is not bound")

    for name, cell in flow.items():
        if not isinstance(cell, Mapping):
            raise AcceptanceError("flow resource envelope is invalid")
        resource_source = cell
        if name == "backup_restore" and isinstance(cell.get("render"), Mapping):
            resource_source = cell["render"]
        published_limits = resource_source.get("resource_limits")
        if published_limits is None:
            if cell.get("status") == "passed":
                raise AcceptanceError(f"flow {name} resource limits are missing")
        elif published_limits != child_limits:
            raise AcceptanceError(f"flow {name} resource limits are not fixture-bound")
        if any(key in cell for key in ceilings):
            check_mapping(cell, prefix=f"flow {name} ")
        if name == "backup_restore" and isinstance(cell.get("render"), Mapping) and any(
            key in cell["render"] for key in ceilings
        ):
            check_mapping(cell["render"], prefix=f"flow {name} render ")


_ALLOWED_REPORT_STATUSES = frozenset({
    "passed", "failed", "blocked", "unavailable", "not_run", "timeout", "resource_limit", "partial",
})


def _validate_process_containment(value: Any, *, label: str, require_enforced: bool) -> None:
    if not isinstance(value, Mapping) or set(value) != {"enforced", "boundary", "cleanup_verified"}:
        raise AcceptanceError(f"{label} process containment is invalid")
    if type(value.get("enforced")) is not bool or type(value.get("cleanup_verified")) is not bool:
        raise AcceptanceError(f"{label} process containment is invalid")
    if value.get("boundary") not in {None, "cgroup_broker", "cgroup_v2_sealed"}:
        raise AcceptanceError(f"{label} process containment boundary is invalid")
    if require_enforced and (
        value.get("enforced") is not True
        or value.get("boundary") not in {"cgroup_broker", "cgroup_v2_sealed"}
        or value.get("cleanup_verified") is not True
    ):
        raise AcceptanceError(f"{label} passed without enforced process containment")


def _validate_report_flow_semantics(flow: Mapping[str, Any]) -> None:
    for name, cell in flow.items():
        if not isinstance(cell, Mapping):
            raise AcceptanceError("flow commitment shape mismatch")
        status = cell.get("status")
        if not isinstance(status, str) or status not in _ALLOWED_REPORT_STATUSES:
            raise AcceptanceError(f"flow {name} status is invalid")
        containment = cell.get("process_containment")
        if name == "backup_restore" and isinstance(cell.get("render"), Mapping):
            containment = cell["render"].get("process_containment")
        if status == "passed":
            _validate_process_containment(containment, label=f"flow {name}", require_enforced=True)
        elif containment is not None:
            _validate_process_containment(containment, label=f"flow {name}", require_enforced=False)
        guard = cell.get("offline_guard")
        offline_report = cell.get("offline_report")
        if name == "backup_restore" and isinstance(cell.get("render"), Mapping):
            render = cell["render"]
            guard = render.get("offline_guard")
            offline_report = render.get("offline_report")
        if isinstance(offline_report, Mapping):
            _validate_public_offline_report(
                offline_report,
                label=f"flow {name}",
                require_active=status == "passed",
            )
        elif status == "passed":
            raise AcceptanceError(f"flow {name} passed without offline report")
        if status == "passed":
            if not isinstance(guard, Mapping) or set(guard) != {"enforced", "boundary", "report_present", "telemetry"}:
                raise AcceptanceError(f"flow {name} offline guard is invalid")
            if (
                guard.get("enforced") is not True
                or guard.get("boundary") != "seccomp"
                or guard.get("report_present") is not True
                or guard.get("telemetry") != "parent_derived"
            ):
                raise AcceptanceError(f"flow {name} passed without enforced offline guard")
            if not isinstance(offline_report, Mapping):
                raise AcceptanceError(f"flow {name} passed without offline report")
        elif guard is not None:
            if not isinstance(guard, Mapping) or not set(guard).issubset({"enforced", "boundary", "report_present", "telemetry"}):
                raise AcceptanceError(f"flow {name} offline guard is invalid")
            if type(guard.get("enforced")) is not bool or type(guard.get("report_present")) is not bool:
                raise AcceptanceError(f"flow {name} offline guard is invalid")
            if guard.get("boundary") not in {None, "seccomp"}:
                raise AcceptanceError(f"flow {name} offline guard is invalid")
            if "telemetry" in guard and guard.get("telemetry") not in {"parent_derived", "unavailable"}:
                raise AcceptanceError(f"flow {name} offline guard is invalid")
        if status == "passed":
            if name != "backup_restore" and (type(cell.get("exit_code")) is not int or cell.get("exit_code") != 0):
                raise AcceptanceError(f"flow {name} passed without zero exit")
            if any(cell.get(key) is True for key in ("output_truncated", "stderr_truncated", "cleanup_failed")):
                raise AcceptanceError(f"flow {name} passed with incomplete evidence")
            if name == "backup_restore" and (
                cell.get("digest_match") is not True
                or cell.get("post_digest_match") is not True
                or not isinstance(cell.get("render"), Mapping)
                or cell["render"].get("status") != "passed"
                or type(cell["render"].get("exit_code")) is not int
                or cell["render"].get("exit_code") != 0
            ):
                raise AcceptanceError("backup restore passed without bound render")
        else:
            reason = cell.get("reason")
            if not isinstance(reason, str) or not _REASON_CODE_RE.fullmatch(reason):
                raise AcceptanceError(f"flow {name} negative result has no bounded reason")


_OFFLINE_PUBLIC_REPORT_KEYS = frozenset({
    "active", "policy", "attempts", "attempts_truncated", "blocked_attempts", "allowed_local_attempts",
})
_EVIDENCE_TOKEN_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _validate_public_offline_report(value: Any, *, label: str, require_active: bool = True) -> None:
    if not isinstance(value, Mapping) or set(value) != _OFFLINE_PUBLIC_REPORT_KEYS:
        raise AcceptanceError(f"{label} offline report shape is invalid")
    if type(value.get("active")) is not bool or (require_active and value.get("active") is not True):
        raise AcceptanceError(f"{label} offline report activity is invalid")
    if value.get("policy") != "deny_all_non_loopback":
        raise AcceptanceError(f"{label} offline report policy is invalid")
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or len(attempts) > _MAX_OFFLINE_ATTEMPTS:
        raise AcceptanceError(f"{label} offline attempts are invalid")
    if not isinstance(value.get("attempts_truncated"), bool):
        raise AcceptanceError(f"{label} offline truncation is invalid")
    for attempt in attempts:
        if not isinstance(attempt, Mapping) or set(attempt) != {"operation", "destination", "outcome"}:
            raise AcceptanceError(f"{label} offline attempt shape is invalid")
        if (
            not isinstance(attempt.get("operation"), str)
            or not _EVIDENCE_TOKEN_RE.fullmatch(attempt["operation"])
            or not isinstance(attempt.get("destination"), str)
            or not _EVIDENCE_TOKEN_RE.fullmatch(attempt["destination"])
            or attempt.get("outcome") not in _ALLOWED_PROBE_OUTCOMES
        ):
            raise AcceptanceError(f"{label} offline attempt values are invalid")
    counters = ("blocked_attempts", "allowed_local_attempts")
    if any(type(value.get(key)) is not int or value[key] < 0 or value[key] > _MAX_OFFLINE_ATTEMPTS for key in counters):
        raise AcceptanceError(f"{label} offline counters are invalid")
    blocked = sum(item["outcome"] == "blocked" for item in attempts)
    allowed_local = sum(item["outcome"] == "allowed_local" for item in attempts)
    if value["blocked_attempts"] < blocked or value["allowed_local_attempts"] < allowed_local:
        raise AcceptanceError(f"{label} offline counters are inconsistent")
    if not value["attempts_truncated"] and (value["blocked_attempts"] != blocked or value["allowed_local_attempts"] != allowed_local):
        raise AcceptanceError(f"{label} offline counters are inconsistent")


def _validate_report_network_semantics(network: Mapping[str, Any]) -> None:
    status = network.get("status")
    if not isinstance(status, str) or status not in _ALLOWED_REPORT_STATUSES:
        raise AcceptanceError("network status is invalid")
    if network.get("policy") != "deny_all":
        raise AcceptanceError("network policy is invalid")
    attempts = network.get("attempts")
    if not isinstance(attempts, list) or len(attempts) > _MAX_OFFLINE_ATTEMPTS:
        raise AcceptanceError("network attempts are invalid")
    for item in attempts:
        if not isinstance(item, Mapping) or set(item) != {"operation", "destination", "outcome"}:
            raise AcceptanceError("network attempt shape is invalid")
        if (
            not isinstance(item.get("operation"), str)
            or not _EVIDENCE_TOKEN_RE.fullmatch(item["operation"])
            or not isinstance(item.get("destination"), str)
            or not _EVIDENCE_TOKEN_RE.fullmatch(item["destination"])
            or item.get("outcome") not in _ALLOWED_PROBE_OUTCOMES
        ):
            raise AcceptanceError("network attempt metadata is invalid")
    if not isinstance(network.get("attempts_truncated"), bool):
        raise AcceptanceError("network truncation is invalid")

    def validate_attempt_list(value: Any, *, label: str) -> None:
        if not isinstance(value, list) or len(value) > _MAX_OFFLINE_ATTEMPTS:
            raise AcceptanceError(f"{label} attempts are invalid")
        for item in value:
            if not isinstance(item, Mapping) or set(item) != {"operation", "destination", "outcome"}:
                raise AcceptanceError(f"{label} attempt shape is invalid")
            if (
                not isinstance(item.get("operation"), str)
                or not _EVIDENCE_TOKEN_RE.fullmatch(item["operation"])
                or not isinstance(item.get("destination"), str)
                or not _EVIDENCE_TOKEN_RE.fullmatch(item["destination"])
                or item.get("outcome") not in _ALLOWED_PROBE_OUTCOMES
            ):
                raise AcceptanceError(f"{label} attempt metadata is invalid")

    expected_blocked = network.get("expected_blocked")
    unexpected_attempts = network.get("unexpected_attempts")
    validate_attempt_list(expected_blocked, label="network expected")
    validate_attempt_list(unexpected_attempts, label="network unexpected")
    if not network.get("attempts_truncated") and expected_blocked != [item for item in attempts if item["outcome"] == "blocked"]:
        raise AcceptanceError("network attempt classification is invalid")
    actual_unexpected = [
        item for item in attempts if item["outcome"] not in {"blocked", "allowed_local"}
    ]
    if not network.get("attempts_truncated") and unexpected_attempts != actual_unexpected:
        raise AcceptanceError("network unexpected-attempt classification is invalid")
    if any(item["outcome"] == "allowed_local" for item in attempts):
        raise AcceptanceError("network deny_all policy permits allowed-local evidence")

    children = network.get("children")
    guards = network.get("child_guards")
    if not isinstance(children, Mapping) or not isinstance(guards, Mapping):
        raise AcceptanceError("network child evidence is invalid")
    if not set(guards).issuperset(set(children)):
        raise AcceptanceError("network child guard pairing is invalid")
    child_attempts: list[dict[str, Any]] = []
    for name, report in children.items():
        _validate_public_offline_report(report, label=f"network child {name}", require_active=status == "passed")
        if status == "passed" and report.get("attempts_truncated") is not False:
            raise AcceptanceError(f"network child {name} has incomplete attempts")
        child_attempts.extend(report["attempts"])
    if network.get("child_attempts") != child_attempts:
        raise AcceptanceError("network child attempts are not report-bound")
    if any(item["outcome"] == "allowed_local" for item in child_attempts):
        raise AcceptanceError("network deny_all policy permits child allowed-local evidence")
    for name, guard in guards.items():
        if not isinstance(guard, Mapping) or not set(guard).issubset({"enforced", "boundary", "report_present", "telemetry"}):
            raise AcceptanceError(f"network child guard {name} is invalid")
        if type(guard.get("enforced")) is not bool or type(guard.get("report_present")) is not bool:
            raise AcceptanceError(f"network child guard {name} is invalid")
        if guard.get("boundary") not in {None, "seccomp"}:
            raise AcceptanceError(f"network child guard {name} is invalid")
        if "telemetry" in guard and guard.get("telemetry") not in {"parent_derived", "unavailable"}:
            raise AcceptanceError(f"network child guard {name} is invalid")

    probe = network.get("child_probe")
    if not isinstance(probe, Mapping) or set(probe) != {"status", "exit_code", "report"}:
        raise AcceptanceError("network child probe is invalid")
    probe_status = probe.get("status")
    if probe_status not in _ALLOWED_REPORT_STATUSES:
        raise AcceptanceError("network child probe status is invalid")
    if probe.get("exit_code") is not None and type(probe.get("exit_code")) is not int:
        raise AcceptanceError("network child probe exit code is invalid")
    probe_envelope = probe.get("report")
    if probe_envelope is not None:
        if (
            not isinstance(probe_envelope, Mapping)
            or set(probe_envelope) != {"blocked", "destination", "report"}
            or type(probe_envelope.get("blocked")) is not bool
            or not isinstance(probe_envelope.get("destination"), str)
            or not _EVIDENCE_TOKEN_RE.fullmatch(probe_envelope["destination"])
        ):
            raise AcceptanceError("network probe envelope is invalid")
        probe_report = probe_envelope.get("report")
        if not isinstance(probe_report, Mapping):
            raise AcceptanceError("network probe report is invalid")
        _validate_public_offline_report(
            probe_report,
            label="network probe",
            require_active=status == "passed",
        )
        actual_probe_blocked = any(item["outcome"] == "blocked" for item in probe_report["attempts"])
        if probe_envelope.get("blocked") is not actual_probe_blocked:
            raise AcceptanceError("network probe blocked flag is not report-bound")
        if any(item["outcome"] == "allowed_local" for item in probe_report["attempts"]):
            raise AcceptanceError("network deny_all policy permits probe allowed-local evidence")
        if status == "passed" and probe_report.get("attempts_truncated") is not False:
            raise AcceptanceError("network probe has incomplete attempts")
        if attempts != probe_report["attempts"]:
            raise AcceptanceError("network attempts are not probe-bound")

    if status == "passed":
        if network.get("attempts_truncated") is not False:
            raise AcceptanceError("network passed with incomplete attempts")
        if (
            probe_status != "passed"
            or probe.get("exit_code") != 0
            or not isinstance(probe_envelope, Mapping)
            or probe_envelope.get("blocked") is not True
            or not any(item["outcome"] == "blocked" for item in attempts)
            or not children
            or not guards
            or set(children) != set(guards)
        ):
            raise AcceptanceError("network passed without complete child evidence")
        for name, guard in guards.items():
            if (
                guard.get("enforced") is not True
                or guard.get("boundary") != "seccomp"
                or guard.get("report_present") is not True
                or guard.get("telemetry") != "parent_derived"
            ):
                raise AcceptanceError(f"network child guard {name} is invalid")


def _validate_report_claims(report: Mapping[str, Any], flow: Mapping[str, Any], network: Mapping[str, Any]) -> None:
    if report.get("claims_ceiling") != _CLAIMS_CEILING:
        raise AcceptanceError("claims ceiling mismatch")
    claims = report.get("claims")
    if not isinstance(claims, Mapping) or set(claims) != set(_CLAIMS_CEILING):
        raise AcceptanceError("claims shape mismatch")
    platform = report.get("platform")
    render = flow.get("perseus_render")
    local_state = (
        isinstance(platform, Mapping)
        and platform.get("status") == "passed"
        and isinstance(render, Mapping)
        and render.get("status") == "passed"
        and network.get("status") == "passed"
    )
    expected = dict(_CLAIMS_CEILING)
    expected["local_offline_capable"] = "observed" if local_state else "not_established"
    if dict(claims) != expected:
        raise AcceptanceError("claims do not match observed semantic state")


def _validate_report_negative_results(report: Mapping[str, Any], flow: Mapping[str, Any]) -> None:
    values = report.get("negative_results")
    if not isinstance(values, list) or len(values) != 4:
        raise AcceptanceError("negative-results envelope is invalid")
    sources = {
        "vault": flow.get("vault"),
        "ledger": flow.get("ledger"),
        "upgrade": report.get("upgrade"),
        "rollback": report.get("rollback"),
    }
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, Mapping) or set(item) != {"cell", "status", "reason"}:
            raise AcceptanceError("negative-results entry is invalid")
        cell = item.get("cell")
        if not isinstance(cell, str) or cell in seen:
            raise AcceptanceError("negative-results binding is invalid")
        source = sources.get(cell)
        if not isinstance(source, Mapping):
            raise AcceptanceError("negative-results binding is invalid")
        if item.get("status") != source.get("status") or item.get("reason") != _negative_result_reason(source):
            raise AcceptanceError("negative-results binding mismatch")
        seen.add(cell)
    if seen != set(sources):
        raise AcceptanceError("negative-results coverage is incomplete")


def _platform_variant_is_partial(platform: Mapping[str, Any] | Any) -> bool:
    """Treat an expected same-OS Python-version matrix variant as partial."""
    if not isinstance(platform, Mapping) or platform.get("status") != "failed":
        return False
    expected = platform.get("expected")
    observed = platform.get("observed")
    return (
        isinstance(expected, Mapping)
        and isinstance(observed, Mapping)
        and expected.get("os") == observed.get("os")
        and isinstance(expected.get("python"), str)
        and isinstance(observed.get("python"), str)
        and expected.get("python") != observed.get("python")
    )


def _validate_report_status(report: Mapping[str, Any], flow: Mapping[str, Any], network: Mapping[str, Any]) -> None:
    platform = report.get("platform")
    if not isinstance(platform, Mapping):
        raise AcceptanceError("platform status is unavailable")
    platform_variant_is_partial = _platform_variant_is_partial(platform)
    sources = [value for value in flow.values() if isinstance(value, Mapping)] + [network]
    for name in ("upgrade", "rollback"):
        value = report.get(name)
        if not isinstance(value, Mapping):
            raise AcceptanceError("aggregate status source is unavailable")
        sources.append(value)
    resource_envelope = report.get("resource_envelope")
    if isinstance(resource_envelope, Mapping) and isinstance(resource_envelope.get("aggregate_children"), Mapping):
        sources.append(resource_envelope["aggregate_children"])
    unavailable = [
        value for value in sources
        if value.get("status") == "unavailable"
        or value.get("status") in _UNAVAILABLE_REASONS
        or value.get("reason") in _UNAVAILABLE_REASONS
    ]
    hard_failures = [
        value for value in sources
        if value.get("status") in {"failed", "blocked", "timeout", "resource_limit", "not_run", "partial"} and value not in unavailable
    ]
    negative_results = report.get("negative_results")
    if not isinstance(negative_results, list):
        raise AcceptanceError("aggregate negative results are unavailable")
    expected_status = (
        "failed"
        if (platform.get("status") != "passed" and not platform_variant_is_partial) or hard_failures
        else "partial"
        if platform_variant_is_partial or unavailable or any(item.get("status") in {"unavailable", "not_run"} for item in negative_results if isinstance(item, Mapping))
        else "passed"
    )
    if report.get("status") != expected_status:
        raise AcceptanceError("aggregate status does not match observed cells")


def _validate_operation_receipt_fields(
    receipt: Any,
    *,
    label: str,
    bundle: Mapping[str, Any],
    query: str,
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or set(receipt) != _OPERATION_RECEIPT_KEYS:
        raise AcceptanceError(f"{label} operation receipt is invalid")
    if (
        receipt.get("schema_version") != _OPERATION_SCHEMA
        or receipt.get("action") != label
        or receipt.get("version") != bundle.get("version")
        or receipt.get("artifact_sha256") != str(bundle.get("sha256", "")).lower()
        or receipt.get("query_sha256") != _sha(query)
        or receipt.get("result") != "passed"
    ):
        raise AcceptanceError(f"{label} operation receipt is not bound")
    persisted = receipt.get("persisted_state")
    if not isinstance(persisted, Mapping) or set(persisted) != _PERSISTED_STATE_KEYS:
        raise AcceptanceError(f"{label} persisted state receipt is invalid")
    if (
        persisted.get("path") != _OPERATION_STATE_PATH
        or not isinstance(persisted.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", persisted["sha256"])
    ):
        raise AcceptanceError(f"{label} persisted state receipt is invalid")
    return dict(receipt)


def _validate_report_operation_semantics(
    value: Any,
    *,
    label: str,
    expected_bundle: Mapping[str, Any] | None,
    query: str,
    expected_resource_limits: Mapping[str, int],
) -> None:
    if not isinstance(value, Mapping):
        raise AcceptanceError(f"{label} operation cell is invalid")
    if expected_bundle is None:
        if value != {"status": "not_run", "reason": f"{label}_bundle_undeclared", "checked": False}:
            raise AcceptanceError(f"{label} operation is not fixture-bound")
        return
    try:
        _validate_bundle_spec(expected_bundle, label)
    except AcceptanceError:
        raise AcceptanceError(f"{label} operation fixture is invalid") from None
    status = value.get("status")
    if status != "passed":
        if status not in _ALLOWED_REPORT_STATUSES - {"passed"}:
            raise AcceptanceError(f"{label} operation status is invalid")
        if type(value.get("checked")) is not bool or value.get("checked") is True:
            raise AcceptanceError(f"{label} negative operation is invalid")
        reason = value.get("reason")
        if not isinstance(reason, str) or not _REASON_CODE_RE.fullmatch(reason):
            raise AcceptanceError(f"{label} negative operation reason is invalid")
        return
    required = {
        "status", "checked", "version", "sha256", "operation_executed", "operation_exit_code",
        "operation_output_truncated", "operation_child_cpu_seconds_observed",
        "operation_child_peak_rss_mb_observed", "operation_resource_limits", "offline_sandbox",
        "offline_report", "offline_guard", "aggregate_resource", "operation_artifact_sha256",
        "operation_query_sha256", "operation_receipt", "operation_receipt_sha256",
        "operation_receipt_persisted", "operation_persisted_state_sha256", "process_containment",
    }
    if set(value) != required:
        raise AcceptanceError(f"{label} passed operation evidence is incomplete")
    expected_digest = str(expected_bundle.get("sha256", "")).lower()
    if (
        type(value.get("checked")) is not bool
        or value.get("checked") is not True
        or value.get("version") != expected_bundle.get("version")
        or value.get("sha256") != expected_digest
        or value.get("operation_executed") is not True
        or type(value.get("operation_exit_code")) is not int
        or value.get("operation_exit_code") != 0
        or type(value.get("operation_output_truncated")) is not bool
        or value.get("operation_output_truncated") is not False
        or value.get("offline_sandbox") != "seccomp"
        or value.get("operation_resource_limits") != dict(expected_resource_limits)
        or value.get("operation_artifact_sha256") != expected_digest
        or value.get("operation_query_sha256") != _sha(query)
        or value.get("operation_receipt_persisted") is not True
    ):
        raise AcceptanceError(f"{label} passed operation evidence is not bound")
    for key in ("operation_child_cpu_seconds_observed", "operation_child_peak_rss_mb_observed"):
        observed = value.get(key)
        if type(observed) is bool or not isinstance(observed, (int, float)) or not math.isfinite(float(observed)) or observed < 0:
            raise AcceptanceError(f"{label} operation resource evidence is invalid")
    guard = value.get("offline_guard")
    if (
        not isinstance(guard, Mapping)
        or set(guard) != {"enforced", "boundary", "report_present", "telemetry"}
        or guard.get("enforced") is not True
        or guard.get("boundary") != "seccomp"
        or guard.get("report_present") is not True
        or guard.get("telemetry") != "parent_derived"
    ):
        raise AcceptanceError(f"{label} operation offline guard is invalid")
    _validate_process_containment(value.get("process_containment"), label=f"{label} operation", require_enforced=True)
    report = value.get("offline_report")
    if not isinstance(report, Mapping):
        raise AcceptanceError(f"{label} operation report is invalid")
    _validate_public_offline_report(report, label=f"{label} operation", require_active=True)
    if report.get("attempts_truncated") is not False:
        raise AcceptanceError(f"{label} operation report is incomplete")
    aggregate = value.get("aggregate_resource")
    if not isinstance(aggregate, Mapping) or set(aggregate) != {
        "cpu_seconds_observed", "peak_rss_mb_observed", "disk_growth_bytes_observed", "status"
    } or aggregate.get("status") != "within_limit":
        raise AcceptanceError(f"{label} operation aggregate resource evidence is invalid")
    for key in ("cpu_seconds_observed", "peak_rss_mb_observed", "disk_growth_bytes_observed"):
        observed = aggregate.get(key)
        if type(observed) is bool or not isinstance(observed, (int, float)) or not math.isfinite(float(observed)) or observed < 0:
            raise AcceptanceError(f"{label} operation aggregate resource evidence is invalid")
    receipt = _validate_operation_receipt_fields(
        value.get("operation_receipt"), label=label, bundle=expected_bundle, query=query
    )
    if (
        value.get("operation_receipt_sha256") != _sha(receipt)
        or value.get("operation_persisted_state_sha256") != receipt["persisted_state"]["sha256"]
    ):
        raise AcceptanceError(f"{label} operation receipt commitment is invalid")


def _expected_network_child_evidence(
    flow: Mapping[str, Any],
    upgrade: Mapping[str, Any],
    rollback: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    reports: dict[str, Any] = {}
    guards: dict[str, Any] = {}
    sources: list[tuple[str, Any]] = list(flow.items()) + [("upgrade", upgrade), ("rollback", rollback)]
    for name, cell in sources:
        source = cell
        if name == "backup_restore" and isinstance(cell, Mapping) and isinstance(cell.get("render"), Mapping):
            source = cell["render"]
        if not isinstance(source, Mapping):
            continue
        if isinstance(source.get("offline_report"), Mapping):
            reports[name] = source["offline_report"]
        if isinstance(source.get("offline_guard"), Mapping):
            guards[name] = source["offline_guard"]
    return reports, guards


def _validate_report_network_projection(
    network: Mapping[str, Any],
    flow: Mapping[str, Any],
    upgrade: Mapping[str, Any],
    rollback: Mapping[str, Any],
) -> None:
    expected_reports, expected_guards = _expected_network_child_evidence(flow, upgrade, rollback)
    if network.get("children") != expected_reports or network.get("child_guards") != expected_guards:
        raise AcceptanceError("network child projection is not flow-bound")


def _validate_report_commitments(
    report: Mapping[str, Any],
    *,
    expected_fixture: Mapping[str, Any] | None = None,
) -> None:
    """Recompute public flow evidence before a report is accepted or written."""
    if not isinstance(expected_fixture, Mapping):
        raise AcceptanceError("expected fixture is required for report validation")
    if not isinstance(report, Mapping) or not isinstance(report.get("flow"), Mapping):
        raise AcceptanceError("flow commitment is unavailable")
    flow = report["flow"]
    if any(not isinstance(value, Mapping) for value in flow.values()):
        raise AcceptanceError("flow commitment shape mismatch")
    workload = expected_fixture.get("workload")
    platform = expected_fixture.get("platform")
    if not isinstance(workload, Mapping) or not isinstance(platform, Mapping):
        raise AcceptanceError("expected fixture is invalid")
    try:
        restart_count = workload["restart_count"]
        expected_flow_keys = {"workload_query", "perseus_render", "vault", "ledger", "backup_restore"}
        expected_flow_keys.update(
            {"restart_recovery"}
            if restart_count == 0
            else {f"restart_recovery_{index}" for index in range(1, restart_count + 1)}
        )
    except (KeyError, TypeError, ValueError):
        raise AcceptanceError("expected fixture workload is invalid") from None
    if set(flow) != expected_flow_keys:
        raise AcceptanceError("flow commitment cell set is not fixture-bound")
    if report.get("fixture_id") != expected_fixture.get("fixture_id"):
        raise AcceptanceError("report fixture binding is invalid")
    if report.get("workload_digest") != _sha(workload) or report.get("workload_query_digest") != _sha(workload.get("query")):
        raise AcceptanceError("report workload binding is invalid")
    expected_projection = {
        key: _public_projection(value)
        for key, value in flow.items()
    }
    if report.get("flow_commitment") != expected_projection:
        raise AcceptanceError("flow commitment mismatch")
    expected_digest = report.get("flow_projection_commitment")
    if not isinstance(expected_digest, str) or expected_digest != _sha(expected_projection):
        raise AcceptanceError("flow commitment digest mismatch")
    _validate_report_flow_semantics(flow)
    child_limits = {
        "cpu_seconds": int(math.ceil(float(platform["resource_limits"]["cpu_seconds"]))),
        "address_space_bytes": int(math.ceil(float(platform["resource_limits"]["memory_mb"]) * 1024 * 1024)),
        "file_bytes": int(math.ceil(float(platform["resource_limits"]["disk_mb"]) * 1024 * 1024)),
    }
    _validate_report_operation_semantics(
        report.get("upgrade"),
        label="upgrade",
        expected_bundle=workload.get("upgrade_bundle"),
        query=workload["query"],
        expected_resource_limits=child_limits,
    )
    _validate_report_operation_semantics(
        report.get("rollback"),
        label="rollback",
        expected_bundle=workload.get("rollback_bundle"),
        query=workload["query"],
        expected_resource_limits=child_limits,
    )
    network = report.get("network")
    if not isinstance(network, Mapping):
        raise AcceptanceError("network commitment is unavailable")
    _validate_report_network_semantics(network)
    _validate_report_network_projection(network, flow, report["upgrade"], report["rollback"])
    _validate_report_claims(report, flow, network)
    _validate_report_negative_results(report, flow)
    manifest_core = {
        "fixture_id": report.get("fixture_id"),
        "workload_digest": report.get("workload_digest"),
        "artifacts": report.get("artifacts"),
        "claims_ceiling": report.get("claims_ceiling"),
        "upgrade": report.get("upgrade"),
        "rollback": report.get("rollback"),
    }
    if report.get("manifest_commitment") != _sha(manifest_core):
        raise AcceptanceError("manifest commitment mismatch")
    resource_contract = report.get("resource_contract")
    resource_envelope = report.get("resource_envelope")
    if not isinstance(resource_contract, Mapping) or not isinstance(resource_envelope, Mapping):
        raise AcceptanceError("resource commitment is unavailable")
    expected_limits = None
    if expected_fixture is not None:
        fixture_platform = expected_fixture.get("platform")
        if not isinstance(fixture_platform, Mapping) or not isinstance(fixture_platform.get("resource_limits"), Mapping):
            raise AcceptanceError("expected fixture resource limits are unavailable")
        expected_limits = fixture_platform["resource_limits"]
    _validate_report_resource_semantics(
        resource_contract,
        resource_envelope,
        flow,
        expected_limits=expected_limits,
    )
    expected_resource_commitment = _sha({
        "resource_envelope": resource_envelope,
        "flow": expected_projection,
    })
    if resource_contract.get("resource_observations_commitment") != expected_resource_commitment:
        raise AcceptanceError("resource commitment mismatch")
    _validate_report_status(report, flow, network)
    if any(key not in report for key in _REPORT_CORE_KEYS):
        raise AcceptanceError("report commitment is unavailable")
    expected_report_commitment = _sha({key: report[key] for key in _REPORT_CORE_KEYS})
    if report.get("report_commitment") != expected_report_commitment:
        raise AcceptanceError("report commitment mismatch")
    stable_flow_commitment = {key: _stable_projection(value) for key, value in expected_projection.items()}
    stable_report_core = {key: report[key] for key in _REPORT_CORE_KEYS}
    stable_report_core["flow_commitment"] = stable_flow_commitment
    stable_report_core["flow_projection_commitment"] = _sha(stable_flow_commitment)
    stable_report_core.pop("resource_envelope", None)
    stable_resource_contract = _stable_projection(stable_report_core["resource_contract"])
    if not isinstance(stable_resource_contract, Mapping):
        raise AcceptanceError("stable resource commitment is invalid")
    stable_resource_contract = dict(stable_resource_contract)
    stable_resource_contract.pop("resource_observations_commitment", None)
    stable_report_core["resource_contract"] = stable_resource_contract
    expected_stable_report_commitment = _sha(stable_report_core)
    if report.get("stable_report_commitment") != expected_stable_report_commitment:
        raise AcceptanceError("stable report commitment mismatch")
    expected_evidence_digest = _sha({
        "manifest_commitment": report.get("manifest_commitment"),
        "stable_report_commitment": expected_stable_report_commitment,
        "workload_digest": report.get("workload_digest"),
        "workload_query_digest": report.get("workload_query_digest"),
        "artifacts": report.get("artifacts"),
        "flow": _stable_projection(expected_projection),
        "backup_digest": flow.get("backup_restore", {}).get("backup_digest"),
        "network": _stable_projection(network),
        "claims_ceiling": report.get("claims_ceiling"),
        "claims": report.get("claims"),
        "upgrade": _stable_projection(report.get("upgrade")),
        "rollback": _stable_projection(report.get("rollback")),
        "negative_results": report.get("negative_results"),
    })
    if report.get("evidence_digest") != expected_evidence_digest:
        raise AcceptanceError("evidence digest mismatch")


def _bounded_reader(stream: Any, limit: int, result: dict[str, Any], key: str) -> None:
    total = 0
    captured = bytearray()
    while total <= limit:
        chunk = stream.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if len(captured) < limit:
            captured.extend(chunk[: limit - len(captured)])
        if total > limit:
            result[f"{key}_limit_exceeded"] = True
            break
    result[f"{key}_bytes"] = bytes(captured)
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
    candidates = {Path(raw).resolve() for raw in roots}
    unique: list[Path] = []
    for root in sorted(candidates, key=lambda path: (len(path.parts), str(path))):
        if any(root == existing or existing in root.parents for existing in unique):
            continue
        unique.append(root)
    return sum(_directory_size(root) for root in unique)


class _FilesystemSnapshot(dict[int, int]):
    def __init__(self, values: Mapping[int, int], *, complete: bool):
        super().__init__(values)
        self.complete = bool(complete)


def _filesystem_observation_complete(value: Mapping[int, int] | None) -> bool:
    if value is None:
        return False
    return bool(getattr(value, "complete", bool(value)))


def _filesystem_free_bytes() -> _FilesystemSnapshot:
    """Return available bytes for every visible filesystem device."""
    if not hasattr(os, "statvfs"):
        return _FilesystemSnapshot({}, complete=False)
    candidates = [Path("/")]
    complete = True
    if sys.platform.startswith("linux"):
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
            for line in mountinfo.splitlines():
                fields = line.split(" - ", 1)[0].split()
                if len(fields) < 5:
                    complete = False
                    continue
                candidates.append(
                    Path(
                        fields[4]
                        .replace(r"\040", " ")
                        .replace(r"\011", "\t")
                        .replace(r"\012", "\n")
                        .replace(r"\134", "\\")
                    )
                )
        except (OSError, UnicodeDecodeError):
            return _FilesystemSnapshot({}, complete=False)
    result: dict[int, int] = {}
    for path in candidates:
        try:
            device = os.stat(path).st_dev
            usage = os.statvfs(path)
            result.setdefault(device, int(usage.f_bavail * usage.f_frsize))
        except (OSError, TypeError, ValueError, AttributeError):
            complete = False
    return _FilesystemSnapshot(result, complete=complete and bool(result))


def _disk_growth_charge(logical_growth: int, filesystem_growth: int, *, prefer_logical: bool = False) -> int:
    logical = max(0, int(logical_growth))
    filesystem = max(0, int(filesystem_growth))
    if prefer_logical and logical > 0:
        return logical
    return max(logical, filesystem)


def _filesystem_growth_bytes(baseline: Mapping[int, int], current: Mapping[int, int]) -> int:
    if not _filesystem_observation_complete(baseline) or not _filesystem_observation_complete(current):
        raise AcceptanceError("filesystem_observation_unavailable")
    if set(baseline) != set(current):
        raise AcceptanceError("filesystem_observation_incomplete")
    return sum(max(0, int(baseline[device]) - int(current[device])) for device in baseline)


class _AggregateResourceBudget:
    """Charge transient child resources against one run-level ceiling."""

    def __init__(self, roots: tuple[Path, ...], *, cpu_seconds: float, memory_mb: float, disk_bytes: int):
        self.roots = roots
        self.cpu_limit = float(cpu_seconds)
        self.memory_limit = float(memory_mb)
        self.disk_limit = int(disk_bytes)
        self.baseline_disk = _monitor_size(roots)
        try:
            self.baseline_filesystems = _filesystem_free_bytes()
        except (OSError, TypeError, ValueError, AcceptanceError):
            self.baseline_filesystems = _FilesystemSnapshot({}, complete=False)
        self.filesystem_observation_failed = not _filesystem_observation_complete(self.baseline_filesystems)
        self.cpu_seconds = 0.0
        self.peak_rss_mb = 0.0
        self.disk_bytes = 0

    def rebaseline_filesystems(self) -> bool:
        """Exclude parent-side containment setup from aggregate child accounting."""
        try:
            current = _filesystem_free_bytes()
        except (OSError, TypeError, ValueError, AcceptanceError):
            self.filesystem_observation_failed = True
            return False
        if not _filesystem_observation_complete(current):
            self.filesystem_observation_failed = True
            return False
        self.baseline_filesystems = current
        return True

    def observe(self, *, cpu_seconds: float, peak_rss_mb: float, disk_growth_bytes: int) -> bool:
        self.cpu_seconds += max(0.0, float(cpu_seconds))
        self.peak_rss_mb = max(self.peak_rss_mb, max(0.0, float(peak_rss_mb)))
        current_growth = max(0, _monitor_size(self.roots) - self.baseline_disk)
        try:
            _filesystem_growth_bytes(self.baseline_filesystems, _filesystem_free_bytes())
        except (AcceptanceError, OSError, TypeError, ValueError):
            self.filesystem_observation_failed = True
        child_disk_growth = max(0, int(disk_growth_bytes))
        self.disk_bytes += child_disk_growth
        if child_disk_growth > 0:
            return not self.exceeded and not self.filesystem_observation_failed
        self.disk_bytes = max(self.disk_bytes, current_growth)
        return not self.exceeded and not self.filesystem_observation_failed

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
            "status": "filesystem_observation_unavailable" if self.filesystem_observation_failed else "resource_limit" if self.exceeded else "within_limit",
        }


def _is_python_argv(argv: list[str]) -> bool:
    if not argv or not isinstance(argv[0], str):
        return False
    executable = Path(argv[0]).name.casefold()
    return executable.startswith(("python", "pypy"))


def _prepare_filesystem_guard(
    argv: list[str], cwd: Path, env: Mapping[str, str], allowed_roots: tuple[Path, ...] | list[Path]
) -> tuple[dict[str, str], Path | None]:
    """Install a fail-closed Python write sandbox when disk accounting is active."""
    child_env = dict(env)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if not _is_python_argv(argv):
        return child_env, None
    guard_dir = Path(tempfile.mkdtemp(prefix=".perseus-filesystem-", dir=str(cwd)))
    guard_path = guard_dir / "sitecustomize.py"
    write_roots = tuple(str(Path(root).resolve()) for root in allowed_roots)
    _strict_write_guard(
        guard_dir,
        guard_path,
        "import os, sys\n"
        f"_allowed_roots = {write_roots!r}\n"
        "def _allowed(value):\n"
        "    try:\n"
        "        if isinstance(value, int):\n"
        "            return True\n"
        "        candidate = os.path.realpath(os.path.abspath(os.fspath(value)))\n"
        "        return any(candidate == root or candidate.startswith(root + os.sep) for root in _allowed_roots)\n"
        "    except BaseException:\n"
        "        return False\n"
        "def _violate():\n"
        "    os._exit(126)\n"
        "def _audit(event, args):\n"
        "    if event == 'open':\n"
        "        path = args[0] if args else None\n"
        "        mode = args[1] if len(args) > 1 else ''\n"
        "        writing = any(flag in mode for flag in 'wax+') if isinstance(mode, str) else isinstance(mode, int) and bool(mode & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))\n"
        "        if writing and not _allowed(path):\n"
        "            _violate()\n"
        "    elif event in {'os.remove', 'os.unlink', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.mknod'}:\n"
        "        if args and not _allowed(args[0]):\n"
        "            _violate()\n"
        "    elif event in {'os.symlink', 'os.link'}:\n"
        "        if len(args) < 2 or not _allowed(args[0]) or not _allowed(args[1]):\n"
        "            _violate()\n"
        "    elif event == 'os.rename':\n"
        "        if len(args) < 2 or not _allowed(args[0]) or not _allowed(args[1]):\n"
        "            _violate()\n"
        "    elif event == 'shutil.copyfile':\n"
        "        if len(args) < 2 or not _allowed(args[0]) or not _allowed(args[1]):\n"
        "            _violate()\n"
        "    elif event == 'os.system':\n"
        "        _violate()\n"
        "    elif event == 'subprocess.Popen':\n"
        "        command = args[0] if args else None\n"
        "        executable = command[0] if isinstance(command, (list, tuple)) and command else command\n"
        "        if not isinstance(executable, str) or not os.path.basename(executable).casefold().startswith(('python', 'pypy')):\n"
        "            _violate()\n"
        "sys.addaudithook(_audit)\n",
        encoding="utf-8",
    )
    old_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    return child_env, guard_dir


def _prepare_offline_guard(
    argv: list[str], cwd: Path, env: Mapping[str, str], *, allowed_roots: tuple[Path, ...] | list[Path] = ()
) -> tuple[dict[str, str], Path | None, int, int]:
    """Install parent-owned Python telemetry; seccomp contains every child."""
    child_env = dict(env)
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["PERSEUS_OFFLINE"] = "1"
    child_env.pop("PERSEUS_OFFLINE_REPORT", None)
    if not _is_python_argv(argv):
        return child_env, None, -1, -1
    report_token = secrets.token_hex(16)
    child_env["PERSEUS_OFFLINE_REPORT_TOKEN"] = report_token
    runtime_raw = env.get("PERSEUS_OFFLINE_RUNTIME")
    runtime_path = Path(runtime_raw) if isinstance(runtime_raw, str) else None
    if runtime_path is None or not runtime_raw or runtime_path.is_symlink() or not runtime_path.is_file():
        raise AcceptanceError("offline_guard_runtime_unavailable")
    guard_dir: Path | None = None
    report_read_fd = report_write_fd = -1
    try:
        guard_dir = Path(tempfile.mkdtemp(prefix=".perseus-offline-", dir=str(cwd)))
        report_read_fd, report_write_fd = os.pipe()
        os.set_inheritable(report_write_fd, True)
        guard_path = guard_dir / "sitecustomize.py"
        write_roots = tuple(str(Path(root).resolve()) for root in allowed_roots) or (str(cwd.resolve()),)
        _strict_write_guard(guard_dir, guard_path,
            "import atexit, importlib.util, json, os\n"
            f"_runtime = {str(runtime_path)!r}\n"
            f"_report_fd = {report_write_fd}\n"
            f"_report_token = {report_token!r}\n"
            f"_allowed_roots = {write_roots!r}\n"
            "_sandbox_violation = False\n"
            "try:\n"
            "    os.set_inheritable(_report_fd, False)\n"
            "except BaseException:\n"
            "    os._exit(125)\n"
            "def _close_report_fd_after_fork():\n"
            "    global _report_fd\n"
            "    try:\n"
            "        os.close(_report_fd)\n"
            "    except OSError:\n"
            "        pass\n"
            "    _report_fd = -1\n"
            "try:\n"
            "    os.register_at_fork(after_in_child=_close_report_fd_after_fork)\n"
            "except AttributeError:\n"
            "    pass\n"
            "def _path_allowed(value):\n"
            "    try:\n"
            "        if isinstance(value, int):\n"
            "            return True\n"
            "        candidate = os.path.realpath(os.path.abspath(os.fspath(value)))\n"
            "        return any(candidate == root or candidate.startswith(root + os.sep) for root in _allowed_roots)\n"
            "    except BaseException:\n"
            "        return False\n"
            "def _audit(event, args):\n"
            "    global _sandbox_violation\n"
            "    try:\n"
            "        if event == 'open':\n"
            "            path = args[0] if args else None\n"
            "            mode = args[1] if len(args) > 1 else ''\n"
            "            if isinstance(mode, str):\n"
            "                writing = any(flag in mode for flag in 'wax+')\n"
            "            elif isinstance(mode, int):\n"
            "                writing = bool(mode & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))\n"
            "            else:\n"
            "                writing = False\n"
            "            if writing and not _path_allowed(path):\n"
            "                raise PermissionError('filesystem sandbox')\n"
            "        elif event in {'os.remove', 'os.unlink', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.chown', 'os.truncate', 'os.utime', 'os.mknod'}:\n"
            "            if args and not _path_allowed(args[0]):\n"
            "                raise PermissionError('filesystem sandbox')\n"
            "        elif event in {'os.symlink', 'os.link'}:\n"
            "            if len(args) < 2 or not _path_allowed(args[0]) or not _path_allowed(args[1]):\n"
            "                raise PermissionError('filesystem sandbox')\n"
            "        elif event == 'os.rename':\n"
            "            if len(args) < 2 or not _path_allowed(args[0]) or not _path_allowed(args[1]):\n"
            "                raise PermissionError('filesystem sandbox')\n"
            "        elif event == 'shutil.copyfile':\n"
            "            if len(args) < 2 or not _path_allowed(args[0]) or not _path_allowed(args[1]):\n"
            "                raise PermissionError('filesystem sandbox')\n"
            "    except BaseException:\n"
            "        _sandbox_violation = True\n"
            "        raise\n"
            "import sys; sys.addaudithook(_audit)\n"
            "def _write_frame(kind, value):\n"
            "    try:\n"
            "        raw = json.dumps({'kind': kind, 'token': _report_token, 'value': value}, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')\n"
            "        if len(raw) > 65536:\n"
            "            return False\n"
            "        packet = len(raw).to_bytes(4, 'big') + raw\n"
            "        offset = 0\n"
            "        while offset < len(packet):\n"
            "            offset += os.write(_report_fd, packet[offset:])\n"
            "        return True\n"
            "    except BaseException:\n"
            "        return False\n"
            "def _start_time():\n"
            "    try:\n"
            "        text = open('/proc/self/stat', encoding='utf-8').read()\n"
            "        return int(text[text.rfind(')') + 2:].split()[19])\n"
            "    except BaseException:\n"
            "        return -1\n"
            "try:\n"
            "    _spec = importlib.util.spec_from_file_location('_perseus_offline_guard_runtime', _runtime)\n"
            "    if _spec is None or _spec.loader is None:\n"
            "        raise RuntimeError('offline runtime unavailable')\n"
            "    _module = importlib.util.module_from_spec(_spec)\n"
            "    _spec.loader.exec_module(_module)\n"
            "    _module.activate_offline_mode()\n"
            "except BaseException:\n"
            "    os._exit(125)\n"
            "def _finish():\n"
            "    try:\n"
            "        _value = _module.offline_network_report()\n"
            "        _module.deactivate_offline_mode()\n"
            "        if _write_frame('report', _value):\n"
            "            _write_frame('complete', {'pid': os.getpid(), 'start_time': _start_time(), 'sandbox_violation': _sandbox_violation})\n"
            "    except BaseException:\n"
            "        pass\n"
            "atexit.register(_finish)\n",
            encoding="utf-8",
        )
    except BaseException:
        for fd in (report_read_fd, report_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        if not cleanup_ok:
            raise AcceptanceError("child_cleanup_failed") from None
        raise
    old_pythonpath = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    return child_env, guard_dir, report_read_fd, report_write_fd


def _read_offline_report(
    report_fd: int | None,
    expected_token: str | None = None,
    *,
    expected_pid: int | None = None,
    expected_start_time: int | None = None,
    expected_report: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Read a report only when it matches a parent-derived expectation.

    A pipe proves only that bytes came from a process which inherited the
    descriptor.  It does not authenticate the bytes, so completion metadata
    and counters from the child are never authoritative.  ``expected_report``
    is constructed by the parent from the declared command; absent that
    binding this boundary fails closed.
    """
    if (
        type(report_fd) is not int
        or report_fd < 0
        or not isinstance(expected_token, str)
        or not re.fullmatch(r"[0-9a-f]{32}", expected_token)
        or not isinstance(expected_report, Mapping)
        or type(expected_pid) is not int
        or expected_pid <= 0
        or type(expected_start_time) is not int
        or expected_start_time < 0
    ):
        return None
    try:
        raw = bytearray()
        os.set_blocking(report_fd, False)
        poller = select.poll()
        poller.register(report_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
        deadline = time.monotonic() + _OFFLINE_REPORT_READ_TIMEOUT_SECONDS
        while len(raw) <= _MAX_OFFLINE_REPORT_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            events = poller.poll(max(1, int(remaining * 1000)))
            if not events:
                return None
            try:
                chunk = os.read(report_fd, min(4096, _MAX_OFFLINE_REPORT_BYTES + 1 - len(raw)))
            except BlockingIOError:
                continue
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > _MAX_OFFLINE_REPORT_BYTES:
            return None
        frames: list[Mapping[str, Any]] = []
        offset = 0
        while offset < len(raw):
            if len(raw) - offset < 4:
                return None
            frame_size = int.from_bytes(raw[offset:offset + 4], "big")
            offset += 4
            if frame_size <= 0 or frame_size > _MAX_OFFLINE_REPORT_BYTES or frame_size > len(raw) - offset:
                return None
            frame = json.loads(bytes(raw[offset:offset + frame_size]).decode("utf-8"), parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
            offset += frame_size
            if not isinstance(frame, Mapping) or set(frame) != {"kind", "token", "value"}:
                return None
            if frame.get("token") != expected_token:
                return None
            frames.append(frame)
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if len(frames) != 2 or frames[0].get("kind") != "report" or frames[1].get("kind") != "complete":
        return None
    completion = frames[1].get("value")
    if (
        not isinstance(completion, Mapping)
        or set(completion) != {"pid", "start_time", "sandbox_violation"}
        or type(completion.get("pid")) is not int
        or completion.get("pid") != expected_pid
        or type(completion.get("start_time")) is not int
        or completion.get("start_time") != expected_start_time
        or completion.get("sandbox_violation") is not False
    ):
        return None
    value = frames[0].get("value")
    required = {"active", "policy", "attempts", "attempts_truncated", "blocked_attempts", "allowed_local_attempts"}
    if not isinstance(value, Mapping) or set(value) != required or value.get("active") is not True or value.get("policy") != "deny_all_non_loopback":
        return None
    if not isinstance(value["attempts"], list) or value["attempts_truncated"] is not False:
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
    blocked_count = sum(item["outcome"] == "blocked" for item in value["attempts"])
    allowed_count = sum(item["outcome"] == "allowed_local" for item in value["attempts"])
    if value["blocked_attempts"] != blocked_count or value["allowed_local_attempts"] != allowed_count:
        return None
    expected = dict(expected_report)
    try:
        expected_sanitized = _sanitize_offline_report(expected)
        actual_sanitized = _sanitize_offline_report(value)
    except (KeyError, TypeError, ValueError):
        return None
    if actual_sanitized != expected_sanitized:
        return None
    return expected_sanitized


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


def _process_has_run_token(pid: int, token: str | None, token_fd: int | None = None) -> bool:
    if not isinstance(token, str) or not token or not sys.platform.startswith("linux"):
        return False
    marker = f"PERSEUS_ACCEPTANCE_RUN_ID={token}".encode("ascii")
    try:
        if marker in (Path("/proc") / str(int(pid)) / "environ").read_bytes()[: 64 * 1024].split(b"\0"):
            return True
    except (OSError, TypeError, ValueError):
        pass
    if type(token_fd) is not int or token_fd < 0:
        return False
    try:
        inherited = (Path("/proc") / str(int(pid)) / "fd" / str(token_fd)).read_bytes()
        return marker in inherited[: 256]
    except (OSError, TypeError, ValueError):
        return False


def _current_ancestry_contains(pid: int, root_pid: int, root_start_time: int) -> bool:
    """Prove a live PID remains below the recorded leader, without markers."""
    if type(pid) is not int or type(root_pid) is not int or type(root_start_time) is not int:
        return False
    seen: set[int] = set()
    current_pid = pid
    for _ in range(256):
        if current_pid in seen or current_pid <= 0:
            return False
        seen.add(current_pid)
        current = _process_identity(current_pid)
        if current is None:
            return False
        if current["pid"] == root_pid:
            return current["start_time"] == root_start_time
        parent_pid = current.get("ppid")
        if type(parent_pid) is not int or parent_pid <= 0 or parent_pid == current_pid:
            return False
        current_pid = parent_pid
    return False


def _ownership_verified(
    identity: Mapping[str, int],
    *,
    leader_identity: Mapping[str, int] | None,
    run_token: str | None,
    token_fd: int | None,
) -> bool:
    root_pid = identity.get("ownership_root_pid")
    root_start_time = identity.get("ownership_root_start_time")
    if isinstance(leader_identity, Mapping):
        root_pid = leader_identity.get("pid")
        root_start_time = leader_identity.get("start_time")
    if (
        type(root_pid) is int
        and type(root_start_time) is int
        and _current_ancestry_contains(identity["pid"], root_pid, root_start_time)
    ):
        return True
    return _process_has_run_token(identity["pid"], run_token, token_fd)


def _owned_processes(
    leader_pid: int,
    baseline: Mapping[int, Mapping[str, int]],
    known: dict[int, dict[str, int]],
    run_token: str | None,
    token_fd: int | None = None,
) -> dict[int, dict[str, int]]:
    """Collect new descendants, reparented subreaper children, or run-token processes."""
    snapshot = _process_snapshot()
    children: dict[int, list[int]] = {}
    for pid, identity in snapshot.items():
        children.setdefault(identity["ppid"], []).append(pid)
    reparented = {
        pid
        for pid, identity in snapshot.items()
        if pid not in baseline
        and identity.get("ppid") == os.getpid()
        and _process_has_run_token(pid, run_token, token_fd)
    }
    pending = [leader_pid, *reparented]
    descendants: set[int] = set()
    while pending:
        parent = pending.pop()
        for child in children.get(parent, ()):
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    for pid in descendants | reparented:
        identity = snapshot.get(pid)
        if identity is not None and pid not in baseline:
            owned = dict(identity)
            if pid in reparented:
                owned["owned_by_token"] = 1
            else:
                owned["owned_by_ancestry"] = 1
                leader = snapshot.get(leader_pid)
                if isinstance(leader, Mapping):
                    owned["ownership_root_pid"] = leader_pid
                    owned["ownership_root_start_time"] = leader["start_time"]
            known[pid] = owned
    for pid, identity in snapshot.items():
        if pid not in baseline and _process_has_run_token(pid, run_token, token_fd):
            owned = dict(known.get(pid, {}))
            owned.update(identity)
            owned["owned_by_token"] = 1
            known[pid] = owned
    return known


def _identity_alive(
    identity: Mapping[str, int],
    run_token: str | None,
    *,
    leader_identity: Mapping[str, int] | None = None,
    token_fd: int | None = None,
) -> tuple[bool, bool]:
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
    return True, _ownership_verified(
        identity,
        leader_identity=leader_identity,
        run_token=run_token,
        token_fd=token_fd,
    )


def _signal_owned(
    identity: Mapping[str, int],
    sig: signal.Signals,
    run_token: str | None,
    trusted_pgid: int | None = None,
    *,
    leader_identity: Mapping[str, int] | None = None,
    token_fd: int | None = None,
) -> bool:
    current = _process_identity(identity["pid"])
    if current is None:
        return not (sys.platform.startswith("linux") and (Path("/proc") / str(identity["pid"])).exists())
    if current["start_time"] != identity["start_time"]:
        return True
    if current["state"] == "Z":
        return True
    if not _ownership_verified(
        identity,
        leader_identity=leader_identity,
        run_token=run_token,
        token_fd=token_fd,
    ):
        return False
    # The verified start time proves this is the same process even if it
    # created a new session or changed PGID after discovery.  Signal the PID
    # directly in that case; never use the stale group identifier.
    try:
        os.kill(identity["pid"], sig)
        return True
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False


class _CgroupScope:
    def __init__(
        self,
        *,
        root: Path,
        group: Path,
        root_fd: int,
        root_procs_fd: int,
        group_fd: int,
        group_procs_fd: int,
        kill_fd: int,
        root_kill_fd: int = -1,
        group_procs_read_fd: int = -1,
        events_fd: int = -1,
        broker_socket: socket.socket | None = None,
        broker_handle: str | None = None,
    ) -> None:
        self.root = root
        self.group = group
        self.root_fd = root_fd
        self.root_procs_fd = root_procs_fd
        self.root_kill_fd = root_kill_fd
        self.group_fd = group_fd
        self.group_procs_fd = group_procs_fd
        self.group_procs_read_fd = group_procs_read_fd
        self.kill_fd = kill_fd
        self.events_fd = events_fd
        self.broker_socket = broker_socket
        self.broker_handle = broker_handle
        self.sealed = False


_CGROUP2_SUPER_MAGIC = 0x63677270
_CGROUP_CONTROL_SEALED_MODE = 0
_CGROUP_DIRECTORY_SEALED_MODE = 0
_CGROUP_PROCS_MODE = 0o644
_CGROUP_KILL_MODE = 0o200
_MAX_CGROUP_MEMBERS_BYTES = 1024 * 1024
_MAX_CGROUP_MEMBER_COUNT = 65536


def _unescape_mountinfo_path(value: str) -> str:
    return value.replace(r"\040", " ").replace(r"\011", "\\t").replace(r"\012", "\\n").replace(r"\134", "\\")


def _cgroup_mountpoint(path: Path) -> bool:
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for line in lines:
        try:
            left, right = line.split(" - ", 1)
            fields = left.split()
            filesystem = right.split()[0]
            if len(fields) >= 5 and filesystem == "cgroup2":
                if Path(_unescape_mountinfo_path(fields[4])) == path:
                    return True
        except (IndexError, ValueError):
            continue
    return False


def _cgroup2_filesystem(fd: int) -> bool:
    import ctypes

    class _StatFs(ctypes.Structure):
        _fields_ = [
            ("f_type", ctypes.c_long),
            ("f_bsize", ctypes.c_long),
            ("f_blocks", ctypes.c_ulonglong),
            ("f_bfree", ctypes.c_ulonglong),
            ("f_bavail", ctypes.c_ulonglong),
            ("f_files", ctypes.c_ulonglong),
            ("f_ffree", ctypes.c_ulonglong),
            ("f_fsid", ctypes.c_int * 2),
            ("f_namelen", ctypes.c_long),
            ("f_frsize", ctypes.c_long),
            ("f_flags", ctypes.c_long),
            ("f_spare", ctypes.c_long * 4),
        ]

    libc = ctypes.CDLL(None, use_errno=True)
    libc.fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(_StatFs)]
    libc.fstatfs.restype = ctypes.c_int
    statfs = _StatFs()
    if libc.fstatfs(fd, ctypes.byref(statfs)) != 0:
        raise OSError(ctypes.get_errno(), "cgroup filesystem probe failed")
    return int(statfs.f_type) == _CGROUP2_SUPER_MAGIC


def _open_cgroup_dir(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags)


def _open_cgroup_control(dir_fd: int, name: str, flags: int) -> int:
    return os.open(name, flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)


def _read_fd_bounded(fd: int, limit: int = _MAX_CGROUP_MEMBERS_BYTES) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, limit + 1)
    if len(data) > limit:
        raise OSError("cgroup control output is oversized")
    return data


def _cgroup_members_fd(fd: int) -> list[int]:
    try:
        pid_max = int(Path("/proc/sys/kernel/pid_max").read_text(encoding="ascii").strip())
    except (OSError, TypeError, ValueError):
        pid_max = 2**31 - 1
    members: list[int] = []
    for raw in _read_fd_bounded(fd).decode("ascii").split():
        try:
            pid = int(raw, 10)
        except (TypeError, ValueError, OverflowError, UnicodeError):
            raise OSError("cgroup membership is malformed") from None
        if pid <= 0 or pid > pid_max:
            raise OSError("cgroup membership is malformed")
        members.append(pid)
        if len(members) > _MAX_CGROUP_MEMBER_COUNT:
            raise OSError("cgroup membership is oversized")
    return members


def _cgroup_populated_fd(fd: int) -> bool:
    values = {}
    for line in _read_fd_bounded(fd, 4096).decode("ascii").splitlines():
        key, separator, value = line.partition(" ")
        if separator:
            values[key] = value.strip()
    if values.get("populated") not in {"0", "1"}:
        raise OSError("cgroup events are malformed")
    return values["populated"] == "1"


def _chmod_scope_fd(fd: int, path: Path, mode: int) -> None:
    if fd >= 0:
        os.fchmod(fd, mode)
    else:
        os.chmod(path, mode)


def _seal_cgroup_scope(scope: _CgroupScope) -> bool:
    try:
        _chmod_scope_fd(scope.root_procs_fd, scope.root / "cgroup.procs", _CGROUP_CONTROL_SEALED_MODE)
        _chmod_scope_fd(scope.root_kill_fd, scope.root / "cgroup.kill", _CGROUP_CONTROL_SEALED_MODE)
        _chmod_scope_fd(scope.group_procs_fd, scope.group / "cgroup.procs", _CGROUP_CONTROL_SEALED_MODE)
        _chmod_scope_fd(scope.kill_fd, scope.group / "cgroup.kill", _CGROUP_CONTROL_SEALED_MODE)
        _chmod_scope_fd(scope.group_fd, scope.group, _CGROUP_DIRECTORY_SEALED_MODE)
        _chmod_scope_fd(scope.root_fd, scope.root, _CGROUP_DIRECTORY_SEALED_MODE)
    except (OSError, ValueError):
        return False
    scope.sealed = True
    return True


def _unseal_cgroup_scope(scope: _CgroupScope) -> bool:
    ok = True
    for fd, path, mode in (
        (scope.root_fd, scope.root, 0o700),
        (scope.root_procs_fd, scope.root / "cgroup.procs", _CGROUP_PROCS_MODE),
        (scope.root_kill_fd, scope.root / "cgroup.kill", _CGROUP_KILL_MODE),
        (scope.group_fd, scope.group, 0o700),
        (scope.group_procs_fd, scope.group / "cgroup.procs", _CGROUP_PROCS_MODE),
        (scope.kill_fd, scope.group / "cgroup.kill", _CGROUP_KILL_MODE),
    ):
        try:
            _chmod_scope_fd(fd, path, mode)
        except (OSError, ValueError):
            ok = False
    if ok:
        scope.sealed = False
    return ok


def _broker_peer_credentials(conn: socket.socket) -> tuple[int, int, int]:
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return struct.unpack("3i", raw)


def _validate_broker_server_peer(conn: socket.socket) -> tuple[int, int, int]:
    pid, uid, gid = _broker_peer_credentials(conn)
    if pid <= 0 or uid != 0:
        raise OSError("broker peer is not a trusted root server")
    return pid, uid, gid


def _broker_socket_path() -> Path:
    configured = os.environ.get(_CGROUP_BROKER_ENV, "")
    if not configured or not os.path.isabs(configured) or len(configured.encode("utf-8")) > 4096:
        raise OSError("cgroup broker endpoint is unavailable")
    endpoint = Path(os.path.abspath(configured))
    current = Path("/")
    try:
        for component in endpoint.parts[1:-1]:
            current = current / component
            item = os.lstat(current)
            if stat.S_ISLNK(item.st_mode) or item.st_uid != 0 or item.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise OSError("cgroup broker endpoint is unsafe")
        item = os.lstat(endpoint)
    except OSError:
        raise OSError("cgroup broker endpoint is unavailable") from None
    if (
        stat.S_ISLNK(item.st_mode)
        or not stat.S_ISSOCK(item.st_mode)
        or item.st_uid != 0
        or item.st_mode & stat.S_IWOTH
    ):
        raise OSError("cgroup broker endpoint is unsafe")
    return endpoint


def _broker_roundtrip(conn: socket.socket, request: Mapping[str, Any]) -> Mapping[str, Any]:
    encoded = json.dumps(dict(request), sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > _MAX_CGROUP_BROKER_FRAME_BYTES:
        raise OSError("cgroup broker request is oversized")
    conn.sendall(encoded + b"\n")
    data = bytearray()
    while len(data) < _MAX_CGROUP_BROKER_FRAME_BYTES:
        chunk = conn.recv(min(4096, _MAX_CGROUP_BROKER_FRAME_BYTES - len(data)))
        if not chunk:
            raise OSError("cgroup broker closed the connection")
        data.extend(chunk)
        if b"\n" in chunk:
            line, _, _ = bytes(data).partition(b"\n")
            try:
                response = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise OSError("cgroup broker response is invalid") from None
            if not isinstance(response, Mapping) or type(response.get("ok")) is not bool:
                raise OSError("cgroup broker response is invalid")
            return response
    raise OSError("cgroup broker response is oversized")


def _create_broker_scope(run_token: str) -> _CgroupScope:
    endpoint = _broker_socket_path()
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(3.0)
    try:
        conn.connect(str(endpoint))
        _validate_broker_server_peer(conn)
        response = _broker_roundtrip(
            conn,
            {"op": "create", "pid": os.getpid(), "run_token": run_token},
        )
        handle = response.get("handle")
        if response.get("ok") is not True or not isinstance(handle, str) or not re.fullmatch(r"[0-9a-f]{32}", handle):
            raise OSError("cgroup broker rejected create")
        return _CgroupScope(
            root=Path("/"),
            group=Path("/"),
            root_fd=-1,
            root_procs_fd=-1,
            group_fd=-1,
            group_procs_fd=-1,
            kill_fd=-1,
            broker_socket=conn,
            broker_handle=handle,
        )
    except (OSError, TypeError, ValueError):
        try:
            conn.close()
        except OSError:
            pass
        raise OSError("cgroup broker is unavailable") from None


def _finish_broker_scope(scope: _CgroupScope, operation: str) -> bool:
    conn = scope.broker_socket
    handle = scope.broker_handle
    if conn is None or not isinstance(handle, str) or operation not in {"release", "cleanup"}:
        return False
    try:
        response = _broker_roundtrip(conn, {"op": operation, "handle": handle})
        return response.get("ok") is True
    except (OSError, TypeError, ValueError):
        return False
    finally:
        try:
            conn.close()
        except OSError:
            pass
        scope.broker_socket = None
        scope.broker_handle = None


def _close_cgroup_scope(scope: _CgroupScope) -> bool:
    ok = True
    if scope.broker_socket is not None:
        try:
            scope.broker_socket.close()
        except OSError:
            ok = False
        scope.broker_socket = None
        scope.broker_handle = None
    for name in ("root_fd", "root_procs_fd", "root_kill_fd", "group_fd", "group_procs_fd", "group_procs_read_fd", "kill_fd", "events_fd"):
        fd = getattr(scope, name)
        if fd < 0:
            continue
        try:
            os.close(fd)
        except OSError:
            ok = False
        setattr(scope, name, -1)
    return ok


def _cgroup_root_from_env() -> Path | None:
    configured = os.environ.get(_CGROUP_ROOT_ENV, "")
    if not configured:
        return None
    if not sys.platform.startswith("linux"):
        raise OSError("cgroup v2 is unavailable")
    if not os.path.isabs(configured) or os.path.realpath(configured) != os.path.abspath(configured):
        raise OSError("cgroup root path is unsafe")
    root = Path(os.path.abspath(configured))
    if _cgroup_mountpoint(root):
        raise OSError("cgroup mount root is not a delegated subtree")
    root_fd = -1
    controls: list[int] = []
    try:
        root_fd = _open_cgroup_dir(root)
        if not _cgroup2_filesystem(root_fd):
            raise OSError("cgroup v2 filesystem is required")
        root_stat = os.fstat(root_fd)
        if root_stat.st_uid != os.geteuid() or os.geteuid() == 0:
            raise OSError("cgroup delegation requires a non-root owner")
        for name in ("cgroup.procs", "cgroup.kill", "cgroup.subtree_control"):
            if not (root / name).exists():
                raise OSError("cgroup control is unavailable")
        for name in ("cgroup.procs", "cgroup.kill"):
            controls.append(_open_cgroup_control(root_fd, name, os.O_WRONLY))
    except (OSError, TypeError, ValueError):
        raise
    finally:
        for fd in controls:
            try:
                os.close(fd)
            except OSError:
                pass
        if root_fd >= 0:
            try:
                os.close(root_fd)
            except OSError:
                pass
    return root


def _cgroup_members(group: Path) -> list[int]:
    members: list[int] = []
    try:
        pid_max = int(Path("/proc/sys/kernel/pid_max").read_text(encoding="ascii").strip())
    except (OSError, TypeError, ValueError):
        pid_max = 2**31 - 1
    for raw in (group / "cgroup.procs").read_text(encoding="ascii").split():
        try:
            pid = int(raw, 10)
        except (TypeError, ValueError, OverflowError):
            raise OSError("cgroup membership is malformed") from None
        if pid <= 0 or pid > pid_max:
            raise OSError("cgroup membership is malformed")
        members.append(pid)
    return members


def _process_in_cgroup(pid: int, group: Path) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        lines = (Path("/proc") / str(pid) / "cgroup").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    for line in lines:
        if "::" not in line:
            continue
        _, relative = line.split("::", 1)
        relative = relative.rstrip("/")
        if relative and relative.rsplit("/", 1)[-1] == group.name:
            return True
    return False


def _signal_cgroup_member(pid: int, group: Path) -> bool:
    """Signal only a live PID with a stable identity still in this scope."""
    if pid == os.getpid():
        return True
    expected = _process_identity(pid)
    if expected is None:
        return True
    if not _process_in_cgroup(pid, group):
        return False
    current = _process_identity(pid)
    if current is None:
        return True
    if current.get("start_time") != expected.get("start_time"):
        return False
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return True
    except (PermissionError, OSError, OverflowError):
        return False


def _create_cgroup_scope(run_token: str, *, required: bool = False) -> _CgroupScope | None:
    if os.environ.get(_CGROUP_BROKER_ENV):
        return _create_broker_scope(run_token)
    if required:
        raise OSError("root-owned cgroup broker is required")
    root = _cgroup_root_from_env()
    if root is None:
        if required:
            raise OSError("cgroup root is required")
        return None
    root_fd = root_procs_fd = root_kill_fd = -1
    group_fd = group_procs_fd = kill_fd = events_fd = group_procs_read_fd = -1
    group: Path | None = None
    scope: _CgroupScope | None = None
    try:
        root_fd = _open_cgroup_dir(root)
        root_procs_fd = _open_cgroup_control(root_fd, "cgroup.procs", os.O_WRONLY)
        root_kill_fd = _open_cgroup_control(root_fd, "cgroup.kill", os.O_WRONLY)
        group_name = f"perseus-acceptance-{os.getpid()}-{run_token}"
        os.mkdir(group_name, 0o700, dir_fd=root_fd)
        group = root / group_name
        group_fd = _open_cgroup_control(root_fd, group_name, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        group_procs_fd = _open_cgroup_control(group_fd, "cgroup.procs", os.O_WRONLY)
        kill_fd = _open_cgroup_control(group_fd, "cgroup.kill", os.O_WRONLY)
        events_fd = _open_cgroup_control(group_fd, "cgroup.events", os.O_RDONLY)
        group_procs_read_fd = _open_cgroup_control(group_fd, "cgroup.procs", os.O_RDONLY)
        scope = _CgroupScope(
            root=root,
            group=group,
            root_fd=root_fd,
            root_procs_fd=root_procs_fd,
            root_kill_fd=root_kill_fd,
            group_fd=group_fd,
            group_procs_fd=group_procs_fd,
            kill_fd=kill_fd,
            group_procs_read_fd=group_procs_read_fd,
            events_fd=events_fd,
        )
        os.write(group_procs_fd, str(os.getpid()).encode("ascii"))
        if os.getpid() not in _cgroup_members(group):
            raise OSError("parent did not enter cgroup scope")
        if _cgroup_members(root):
            raise OSError("delegated cgroup root is not empty")
        if not _seal_cgroup_scope(scope):
            raise OSError("cgroup scope could not be sealed")
        return scope
    except BaseException:
        if scope is not None:
            _release_cgroup_scope(scope)
        else:
            for fd in (root_fd, root_procs_fd, root_kill_fd, group_fd, group_procs_fd, group_procs_read_fd, kill_fd, events_fd):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            if group is not None:
                try:
                    group.rmdir()
                except OSError:
                    pass
        raise


def _cgroup_scope_members(scope: _CgroupScope) -> list[int]:
    if scope.group_procs_read_fd >= 0:
        return _cgroup_members_fd(scope.group_procs_read_fd)
    return _cgroup_members(scope.group)


def _cgroup_scope_populated(scope: _CgroupScope) -> bool:
    if scope.events_fd >= 0:
        return _cgroup_populated_fd(scope.events_fd)
    return bool(_cgroup_scope_members(scope))


def _write_cgroup_fd(fd: int, value: bytes) -> None:
    written = 0
    while written < len(value):
        count = os.write(fd, value[written:])
        if count <= 0:
            raise OSError("cgroup control write made no progress")
        written += count


def _release_cgroup_scope(scope: _CgroupScope) -> bool:
    if scope.broker_socket is not None:
        return _finish_broker_scope(scope, "release")
    cleanup_ok = True
    moved_out = False
    try:
        _write_cgroup_fd(scope.root_procs_fd, str(os.getpid()).encode("ascii"))
        moved_out = True
    except (OSError, ValueError):
        cleanup_ok = False
    try:
        members = _cgroup_scope_members(scope)
    except (OSError, ValueError):
        members = [os.getpid()]
        cleanup_ok = False
    if os.getpid() in members:
        cleanup_ok = False
    elif moved_out:
        try:
            _write_cgroup_fd(scope.kill_fd, b"1")
        except (OSError, ValueError):
            cleanup_ok = False
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            try:
                if not _cgroup_scope_populated(scope):
                    break
            except (OSError, ValueError):
                cleanup_ok = False
                break
            try:
                _write_cgroup_fd(scope.kill_fd, b"1")
            except (OSError, ValueError):
                cleanup_ok = False
                break
            time.sleep(0.01)
        try:
            if _cgroup_scope_populated(scope):
                cleanup_ok = False
        except (OSError, ValueError):
            cleanup_ok = False
    if not _unseal_cgroup_scope(scope):
        cleanup_ok = False
    try:
        if not _cgroup_scope_members(scope):
            os.rmdir(scope.group, dir_fd=scope.root_fd)
        else:
            cleanup_ok = False
    except (OSError, ValueError):
        cleanup_ok = False
    if not _close_cgroup_scope(scope):
        cleanup_ok = False
    return cleanup_ok


def _known_processes_still_live(known: Mapping[int, Mapping[str, int]]) -> bool:
    for identity in known.values():
        current = _process_identity(identity.get("pid", -1))
        if current is not None and current.get("start_time") == identity.get("start_time") and current.get("state") != "Z":
            return True
    return False


def _terminate_cgroup_scope(
    scope: _CgroupScope,
    process: subprocess.Popen[Any] | None,
    known: Mapping[int, Mapping[str, int]] | None = None,
) -> bool:
    """Kill every process in a sealed delegated cgroup, then remove the scope."""
    if scope.broker_socket is not None:
        cleanup_ok = _finish_broker_scope(scope, "cleanup")
        if process is not None:
            try:
                process.wait(timeout=0.5)
            except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
                cleanup_ok = False
        if known is not None and _known_processes_still_live(known):
            cleanup_ok = False
        return cleanup_ok
    cleanup_ok = True
    moved_out = False
    try:
        _write_cgroup_fd(scope.root_procs_fd, str(os.getpid()).encode("ascii"))
        moved_out = True
    except (OSError, ValueError):
        cleanup_ok = False
    try:
        members = _cgroup_scope_members(scope)
    except (OSError, ValueError):
        members = [os.getpid()]
        cleanup_ok = False
    if os.getpid() in members:
        cleanup_ok = False
    elif moved_out:
        try:
            _write_cgroup_fd(scope.kill_fd, b"1")
        except (OSError, ValueError):
            cleanup_ok = False
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            try:
                if not _cgroup_scope_populated(scope):
                    break
            except (OSError, ValueError):
                cleanup_ok = False
                break
            try:
                _write_cgroup_fd(scope.kill_fd, b"1")
            except (OSError, ValueError):
                cleanup_ok = False
                break
            time.sleep(0.01)
        try:
            if _cgroup_scope_populated(scope):
                cleanup_ok = False
        except (OSError, ValueError):
            cleanup_ok = False
    if process is not None:
        try:
            process.wait(timeout=0.5)
        except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
            cleanup_ok = False
    if known is not None and _known_processes_still_live(known):
        cleanup_ok = False
    if not _unseal_cgroup_scope(scope):
        cleanup_ok = False
    try:
        if _cgroup_scope_members(scope):
            cleanup_ok = False
        else:
            os.rmdir(scope.group, dir_fd=scope.root_fd)
    except (OSError, ValueError):
        cleanup_ok = False
    if not _close_cgroup_scope(scope):
        cleanup_ok = False
    return cleanup_ok


def _terminate_process_group(
    process: subprocess.Popen[Any],
    leader_identity: Mapping[str, int] | None,
    known: dict[int, dict[str, int]],
    run_token: str | None,
    *,
    baseline: Mapping[int, Mapping[str, int]] | None = None,
    token_fd: int | None = None,
    cgroup_scope: _CgroupScope | None = None,
) -> bool:
    """Terminate/reap only verified new processes and their current PGID."""
    if cgroup_scope is not None:
        return _terminate_cgroup_scope(cgroup_scope, process, known=known)
    if sys.platform.startswith("win") or os.name == "nt":
        # No verified Windows job-object/creation-time identity is available;
        # never issue PID-only taskkill against a potentially reused PID.
        return False
    if os.name == "posix" and not sys.platform.startswith("linux"):
        # This path has no portable creation-time PID/PGID identity primitive.
        # Never signal a potentially reused process group; callers must report
        # cleanup failure and fail closed.
        return False
    if not sys.platform.startswith("linux"):
        return False
    cleanup_ok = leader_identity is not None
    leader_pid = process.pid
    baseline_snapshot = baseline if baseline is not None else {}
    if os.name != "posix":
        try:
            if leader_identity is not None:
                process.terminate()
            process.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            cleanup_ok = False
        return cleanup_ok
    for sig, wait_time in ((signal.SIGTERM, 0.25), (signal.SIGKILL, 1.0)):
        _owned_processes(leader_pid, baseline_snapshot, known, run_token, token_fd)
        if any(
            isinstance(leader_identity, Mapping)
            and identity.get("pgid") != leader_identity.get("pgid")
            for identity in known.values()
        ):
            # Without a delegated cgroup, a changed PGID proves that the
            # descendant left the only recorded process-group boundary; its
            # token or prior ancestry does not restore containment proof.
            cleanup_ok = False
        group_pgid: int | None = None
        leader_verified = False
        if leader_identity is not None:
            current_leader = _process_identity(leader_pid)
            if current_leader is None:
                if sys.platform.startswith("linux") and (Path("/proc") / str(leader_pid)).exists():
                    cleanup_ok = False
            elif current_leader["start_time"] != leader_identity["start_time"]:
                cleanup_ok = False
            elif current_leader["pgid"] != leader_identity["pgid"]:
                cleanup_ok = False
            else:
                leader_verified = True
                group_pgid = current_leader["pgid"]
                _owned_processes(leader_pid, baseline_snapshot, known, run_token, token_fd)
        if group_pgid is not None and leader_verified:
            try:
                os.killpg(group_pgid, sig)
            except ProcessLookupError:
                pass
            except (PermissionError, OSError):
                cleanup_ok = False
        for identity in list(known.values()):
            if identity["pid"] != leader_pid and not _signal_owned(
                identity,
                sig,
                run_token,
                group_pgid,
                leader_identity=leader_identity,
                token_fd=token_fd,
            ):
                alive, ownership = _identity_alive(
                    identity,
                    run_token,
                    leader_identity=leader_identity,
                    token_fd=token_fd,
                )
                if alive and not ownership:
                    cleanup_ok = False
        try:
            process.wait(timeout=wait_time)
        except subprocess.TimeoutExpired:
            pass
        except (OSError, subprocess.SubprocessError):
            cleanup_ok = False
    if leader_identity is not None:
        current_leader = _process_identity(leader_pid)
        if current_leader is not None and (
            current_leader["start_time"] == leader_identity["start_time"]
            and current_leader["pgid"] == leader_identity["pgid"]
        ):
            _owned_processes(leader_pid, baseline_snapshot, known, run_token, token_fd)
        elif current_leader is None:
            # A Linux subreaper adopts detached descendants after the leader
            # exits; collect those reparented children before the final KILL.
            _owned_processes(leader_pid, baseline_snapshot, known, run_token, token_fd)
        elif current_leader is not None:
            cleanup_ok = False
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        alive_owned = []
        for identity in list(known.values()):
            alive, ownership = _identity_alive(
                identity,
                run_token,
                leader_identity=leader_identity,
                token_fd=token_fd,
            )
            if alive and ownership:
                alive_owned.append(identity)
                if not _signal_owned(
                    identity,
                    signal.SIGKILL,
                    run_token,
                    leader_identity=leader_identity,
                    token_fd=token_fd,
                ):
                    cleanup_ok = False
            elif alive and not ownership:
                cleanup_ok = False
        for pid in {item["pid"] for item in alive_owned}:
            try:
                os.waitpid(pid, os.WNOHANG)
            except (ChildProcessError, ProcessLookupError):
                pass
            except OSError:
                cleanup_ok = False
        if not alive_owned:
            break
        time.sleep(0.01)
    for identity in list(known.values()):
        alive, ownership = _identity_alive(
            identity,
            run_token,
            leader_identity=leader_identity,
            token_fd=token_fd,
        )
        if alive and ownership:
            cleanup_ok = False
        elif alive and not ownership:
            cleanup_ok = False
        try:
            while os.waitpid(identity["pid"], os.WNOHANG)[0] > 0:
                pass
        except (ChildProcessError, ProcessLookupError):
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


def _install_parent_death_signal(expected_parent_pid: int) -> None:
    """Make every forked descendant die when its bounded leader exits."""
    if not sys.platform.startswith("linux"):
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    if prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error_no = ctypes.get_errno()
        raise OSError(error_no, "parent-death signal unavailable")
    if os.getppid() != expected_parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


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
        "process_containment": {"enforced": False, "boundary": None, "cleanup_verified": not cleanup_failed},
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
    allowed_write_dirs: tuple[Path, ...] | list[Path] | None = None,
    disk_limit_bytes: int | None = None,
    offline_required: bool | None = None,
    aggregate_budget: _AggregateResourceBudget | None = None,
    require_process_containment: bool = True,
) -> dict[str, Any]:
    """Run one child with verified ownership, inherited seccomp, and bounds."""
    if type(require_process_containment) is not bool:
        raise AcceptanceError("process_containment_policy_invalid")
    timeout_value = _validate_child_timeout(timeout)
    limits = _validate_child_limits(resource_limits)
    disk_limit = _validate_disk_limit(disk_limit_bytes) if disk_limit_bytes is not None else None
    if aggregate_budget is not None:
        aggregate_budget.observe(cpu_seconds=0.0, peak_rss_mb=0.0, disk_growth_bytes=0)
        if aggregate_budget.filesystem_observation_failed:
            result = _blocked_child_result(limits, reason="filesystem_observation_unavailable")
            result["aggregate_resource"] = aggregate_budget.report()
            return result
        if aggregate_budget.exceeded:
            result = _blocked_child_result(limits, reason="child_resource_limit")
            result["aggregate_resource"] = aggregate_budget.report()
            return result
    monitor_roots = tuple(monitor_dirs or (() if monitor_dir is None else (monitor_dir,))) + (Path(cwd),)
    write_roots = (Path(cwd),) + tuple(allowed_write_dirs or ())
    offline_requested = env.get("PERSEUS_OFFLINE") == "1"
    if offline_required is not None and type(offline_required) is not bool:
        raise AcceptanceError("offline_policy_invalid")
    if offline_required is False and offline_requested:
        raise AcceptanceError("offline_guard_required")
    require_offline = offline_requested if offline_required is None else offline_required
    expected_offline_report = _parent_derived_offline_report(argv) if require_offline else None
    disk_sandbox_requested = disk_limit is not None or aggregate_budget is not None
    landlock_available = _landlock_supported() if disk_sandbox_requested else False
    if disk_sandbox_requested and not landlock_available:
        return _blocked_child_result(limits, reason="filesystem_sandbox_unavailable")
    if require_offline and not sys.platform.startswith("linux"):
        raise AcceptanceError("offline_sandbox_unavailable")
    child_env = dict(env)
    run_token = secrets.token_hex(16)
    child_env["PERSEUS_ACCEPTANCE_RUN_ID"] = run_token
    cgroup_scope: _CgroupScope | None = None
    containment_boundary: str | None = None
    guard_dir: Path | None = None
    report_read_fd = report_write_fd = -1
    token_fd = -1
    if sys.platform.startswith("linux"):
        try:
            if hasattr(os, "memfd_create"):
                token_fd = os.memfd_create(
                    "perseus-acceptance-token",
                    os.MFD_CLOEXEC if hasattr(os, "MFD_CLOEXEC") else 0,
                )
            else:
                token_fd, token_path = tempfile.mkstemp(prefix=".perseus-token-", dir=str(cwd))
                os.unlink(token_path)
            os.write(token_fd, f"PERSEUS_ACCEPTANCE_RUN_ID={run_token}".encode("ascii"))
            os.lseek(token_fd, 0, os.SEEK_SET)
            os.set_inheritable(token_fd, True)
            child_env["PERSEUS_ACCEPTANCE_TOKEN_FD"] = str(token_fd)
        except (AttributeError, OSError, TypeError, ValueError):
            if token_fd >= 0:
                try:
                    os.close(token_fd)
                except OSError:
                    pass
            return _blocked_child_result(limits, reason="child_containment_unavailable")
    if require_offline:
        try:
            child_env, guard_dir, report_read_fd, report_write_fd = _prepare_offline_guard(
                argv, Path(cwd), child_env, allowed_roots=write_roots
            )
        except (OSError, TypeError, ValueError, AcceptanceError):
            if token_fd >= 0:
                try:
                    os.close(token_fd)
                except OSError:
                    pass
            return _blocked_child_result(limits, reason="offline_guard_unavailable")
    elif disk_sandbox_requested:
        if not _is_python_argv(argv):
            return _blocked_child_result(limits, reason="filesystem_sandbox_unavailable")
        try:
            child_env, guard_dir = _prepare_filesystem_guard(argv, Path(cwd), child_env, write_roots)
        except (OSError, TypeError, ValueError, AcceptanceError):
            if token_fd >= 0:
                try:
                    os.close(token_fd)
                except OSError:
                    pass
            return _blocked_child_result(limits, reason="filesystem_sandbox_unavailable")
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
        try:
            resource_limiter = _child_resource_limiter(limits)
            pass_fds: list[int] = []
            if token_fd >= 0:
                pass_fds.append(token_fd)
            if require_offline:
                guard_read_fd, guard_write_fd = os.pipe()
                os.set_inheritable(guard_write_fd, True)
                pass_fds.append(guard_write_fd)
                if report_write_fd >= 0:
                    os.set_inheritable(report_write_fd, True)
                    pass_fds.append(report_write_fd)
            if pass_fds:
                kwargs["pass_fds"] = tuple(pass_fds)
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, AcceptanceError):
            for fd in (token_fd, guard_read_fd, guard_write_fd, report_read_fd, report_write_fd):
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            cleanup_ok = _cleanup_guard_dir(guard_dir)
            reason = "child_resource_limit" if cleanup_ok else "child_cleanup_failed"
            return _blocked_child_result(limits, reason=reason, cleanup_failed=not cleanup_ok)

        expected_parent_pid = os.getpid()

        def _child_setup() -> None:
            if sys.platform.startswith("linux"):
                _install_parent_death_signal(expected_parent_pid)
            if resource_limiter is not None:
                resource_limiter()
            if disk_sandbox_requested and landlock_available:
                _install_landlock_write_sandbox(write_roots)
            if require_offline:
                _install_offline_seccomp()
                os.write(guard_write_fd, b"1")
                os.close(guard_write_fd)

        kwargs["preexec_fn"] = _child_setup
    subreaper_ready = _ensure_child_subreaper() if sys.platform.startswith("linux") else False
    if sys.platform.startswith("linux") and not subreaper_ready:
        for fd in (token_fd, guard_read_fd, guard_write_fd, report_read_fd, report_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        return _blocked_child_result(limits, reason="child_containment_unavailable", cleanup_failed=not cleanup_ok)
    try:
        cgroup_scope = _create_cgroup_scope(
            run_token,
            required=require_process_containment and sys.platform.startswith("linux"),
        )
    except (OSError, TypeError, ValueError):
        for fd in (token_fd, guard_read_fd, guard_write_fd, report_read_fd, report_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        return _blocked_child_result(
            limits,
            reason="child_containment_unavailable" if cleanup_ok else "child_cleanup_failed",
            cleanup_failed=not cleanup_ok,
        )
    if cgroup_scope is not None:
        containment_boundary = "cgroup_broker" if cgroup_scope.broker_socket is not None else "cgroup_v2_sealed"
        child_env.pop(_CGROUP_ROOT_ENV, None)
        child_env.pop(_CGROUP_BROKER_ENV, None)
    if cgroup_scope is not None and aggregate_budget is not None and not aggregate_budget.rebaseline_filesystems():
        for fd in (token_fd, guard_read_fd, guard_write_fd, report_read_fd, report_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        cleanup_ok = _release_cgroup_scope(cgroup_scope) and cleanup_ok
        return _blocked_child_result(
            limits,
            reason="filesystem_observation_unavailable",
            cleanup_failed=not cleanup_ok,
        )
    baseline = _process_snapshot() if subreaper_ready else {}
    before_disk = _monitor_size(monitor_roots)
    filesystem_observation_failed = False
    try:
        before_filesystems = _filesystem_free_bytes() if disk_limit is not None or aggregate_budget is not None else _FilesystemSnapshot({}, complete=True)
    except (OSError, TypeError, ValueError, AcceptanceError):
        before_filesystems = _FilesystemSnapshot({}, complete=False)
        filesystem_observation_failed = True
    if disk_sandbox_requested and (
        filesystem_observation_failed or not _filesystem_observation_complete(before_filesystems)
    ):
        for fd in (token_fd, guard_read_fd, guard_write_fd, report_read_fd, report_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        if cgroup_scope is not None:
            cleanup_ok = _release_cgroup_scope(cgroup_scope) and cleanup_ok
        return _blocked_child_result(
            limits,
            reason="filesystem_observation_unavailable",
            cleanup_failed=not cleanup_ok,
        )
    before_children = (
        resource.getrusage(resource.RUSAGE_CHILDREN)
        if os.name == "posix" and resource is not None and hasattr(resource, "RUSAGE_CHILDREN")
        else None
    )
    try:
        process = subprocess.Popen(argv, **kwargs)
    except (OSError, subprocess.SubprocessError, ValueError):
        for fd in (token_fd, guard_read_fd, report_read_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        cleanup_ok = _cleanup_guard_dir(guard_dir)
        if cgroup_scope is not None:
            cleanup_ok = _release_cgroup_scope(cgroup_scope) and cleanup_ok
        if not cleanup_ok:
            return _blocked_child_result(limits, reason="child_cleanup_failed", cleanup_failed=True)
        if require_offline:
            return _blocked_child_result(limits, reason="offline_guard_unavailable", cleanup_failed=not cleanup_ok)
        if disk_sandbox_requested:
            return _blocked_child_result(limits, reason="filesystem_sandbox_unavailable", cleanup_failed=not cleanup_ok)
        result = _blocked_child_result(limits, reason="child_spawn_failed", cleanup_failed=not cleanup_ok)
        result["status"] = "failed"
        return result
    finally:
        for fd in (guard_write_fd, report_write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
    guard_verified = False
    if guard_read_fd >= 0:
        try:
            ready, _, _ = select.select([guard_read_fd], [], [], 1.0)
            guard_verified = bool(ready and os.read(guard_read_fd, 1) == b"1")
        except (OSError, ValueError):
            guard_verified = False
        finally:
            os.close(guard_read_fd)
    leader_identity = _process_identity(process.pid) if sys.platform.startswith("linux") else None
    known: dict[int, dict[str, int]] = {}
    captured: dict[str, Any] = {}
    peak_rss_bytes = _read_process_peak_rss_bytes(process.pid)
    max_disk_growth = 0
    max_logical_growth = 0
    max_filesystem_growth = 0

    def _observe_filesystem_growth() -> bool:
        nonlocal max_logical_growth, max_filesystem_growth, max_disk_growth, filesystem_observation_failed
        if not disk_sandbox_requested or filesystem_observation_failed:
            return not filesystem_observation_failed
        try:
            current_filesystems = _filesystem_free_bytes()
            if not _filesystem_observation_complete(current_filesystems):
                filesystem_observation_failed = True
                return False
            growth = _filesystem_growth_bytes(before_filesystems, current_filesystems)
        except (AcceptanceError, OSError, TypeError, ValueError):
            filesystem_observation_failed = True
            return False
        max_filesystem_growth = max(max_filesystem_growth, growth)
        logical_growth = max(0, _monitor_size(monitor_roots) - before_disk)
        max_logical_growth = max(max_logical_growth, logical_growth)
        # Filesystem free-space deltas are host-wide noise while the child is live;
        # logical growth is the authoritative charge for monitored roots.
        max_disk_growth = max_logical_growth
        return True

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
                _owned_processes(process.pid, baseline, known, run_token, token_fd)
            peak_rss_bytes = max(peak_rss_bytes, _read_process_peak_rss_bytes(process.pid))
            logical_growth = max(0, _monitor_size(monitor_roots) - before_disk)
            max_logical_growth = max(max_logical_growth, logical_growth)
            max_disk_growth = max_logical_growth
            if not _observe_filesystem_growth():
                status = "blocked"
                break
            if captured.get("stdout_limit_exceeded") or captured.get("stderr_limit_exceeded"):
                status = "resource_limit"
                break
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                status = "timeout"
                break
            try:
                process.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                if disk_limit is not None and max_disk_growth > disk_limit:
                    status = "resource_limit"
                    break
    finally:
        try:
            cleanup_ok = _terminate_process_group(
                process,
                leader_identity,
                known,
                run_token,
                baseline=baseline,
                token_fd=token_fd,
                cgroup_scope=cgroup_scope,
            )
            cleanup_failed = not cleanup_ok
        except (OSError, subprocess.SubprocessError, ValueError):
            cleanup_failed = True
        finally:
            if token_fd >= 0:
                try:
                    os.close(token_fd)
                except OSError:
                    cleanup_failed = True
                token_fd = -1
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
    if captured.get("stdout_limit_exceeded") or captured.get("stderr_limit_exceeded"):
        status = "resource_limit"
    logical_growth = max(0, _monitor_size(monitor_roots) - before_disk)
    max_logical_growth = max(max_logical_growth, logical_growth)
    if not _observe_filesystem_growth():
        status = "blocked"
    if status == "passed" and process.returncode == 0:
        max_disk_growth = max(0, int(max_logical_growth))
    else:
        # A failed or incomplete child may have written outside monitored roots
        # before its guard stopped it; retain the conservative filesystem fallback.
        max_disk_growth = _disk_growth_charge(max_logical_growth, max_filesystem_growth)
    if disk_limit is not None and max_disk_growth > disk_limit and status == "passed":
        status = "resource_limit"
    if cleanup_failed:
        status = "blocked" if require_offline else "failed"
    elif disk_sandbox_requested and process.returncode == 126:
        status = "blocked"
    elif status not in {"timeout", "resource_limit"} and process.returncode != 0:
        status = "blocked" if require_offline or (disk_sandbox_requested and process.returncode == 126) else "failed"
    after_children = (
        resource.getrusage(resource.RUSAGE_CHILDREN)
        if before_children is not None and os.name == "posix" and resource is not None
        else None
    )
    child_cpu = 0.0
    child_rss_from_usage = 0.0
    if before_children is not None and after_children is not None:
        child_cpu = max(0.0, (after_children.ru_utime + after_children.ru_stime) - (before_children.ru_utime + before_children.ru_stime))
        rss_unit = 1 if sys.platform == "darwin" else 1024
        child_rss_from_usage = max(0.0, float(after_children.ru_maxrss) - float(before_children.ru_maxrss)) / rss_unit
    child_rss = max(child_rss_from_usage, peak_rss_bytes / (1024 * 1024))
    if status == "passed" and (child_cpu > limits["cpu_seconds"] or child_rss > limits["address_space_bytes"] / (1024 * 1024)):
        status = "resource_limit"
    offline_report = None
    expected_offline_token = child_env.get("PERSEUS_OFFLINE_REPORT_TOKEN") if require_offline else None
    expected_offline_report_sanitized = None
    if isinstance(expected_offline_report, Mapping):
        try:
            expected_offline_report_sanitized = _sanitize_offline_report(expected_offline_report)
        except (KeyError, TypeError, ValueError):
            expected_offline_report_sanitized = None
    if report_read_fd >= 0:
        try:
            expected_start_time = leader_identity.get("start_time") if isinstance(leader_identity, Mapping) else None
            observed_offline_report = _read_offline_report(
                report_read_fd,
                expected_token=expected_offline_token,
                expected_pid=process.pid,
                expected_start_time=expected_start_time,
                expected_report=expected_offline_report,
            )
            if observed_offline_report is not None and expected_offline_report_sanitized is not None:
                if observed_offline_report == expected_offline_report_sanitized:
                    offline_report = expected_offline_report_sanitized
        finally:
            try:
                os.close(report_read_fd)
            except OSError:
                pass
    guard_cleanup_failed = not _cleanup_guard_dir(guard_dir)
    cleanup_failed = cleanup_failed or guard_cleanup_failed
    if guard_cleanup_failed:
        status = "blocked" if require_offline else "failed"
    if require_offline and (not guard_verified or offline_report is None):
        if status == "passed":
            status = "blocked"
    aggregate_resource = None
    aggregate_observation_failed = False
    if aggregate_budget is not None:
        aggregate_observation_ok = aggregate_budget.observe(
            cpu_seconds=child_cpu,
            peak_rss_mb=child_rss,
            disk_growth_bytes=max_disk_growth,
        )
        aggregate_observation_failed = (
            aggregate_budget.filesystem_observation_failed
            or (not aggregate_observation_ok and not aggregate_budget.exceeded)
        )
        aggregate_resource = aggregate_budget.report()
        if aggregate_observation_failed and status == "passed":
            status = "blocked"
        elif aggregate_budget.exceeded and status == "passed":
            status = "resource_limit"
    reason = None
    if cleanup_failed:
        reason = "child_cleanup_failed"
    elif require_offline and not guard_verified:
        reason = "offline_guard_unavailable"
    elif require_offline and offline_report is None:
        reason = "offline_report_invalid"
    elif status == "resource_limit":
        reason = "child_resource_limit"
    elif status in {"failed", "blocked"}:
        reason = (
            "child_spawn_failed" if process.returncode is None
            else "offline_guard_unavailable" if require_offline
            else "filesystem_observation_unavailable" if filesystem_observation_failed or aggregate_observation_failed
            else "filesystem_sandbox_unavailable" if disk_sandbox_requested and process.returncode == 126
            else "child_spawn_failed"
        )
    result = {
        "status": status,
        "exit_code": process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "stdout_prefix_bytes": len(stdout),
        "stderr_prefix_bytes": len(stderr),
        "stdout_total_bytes": int(captured.get("stdout_total_bytes", len(stdout))),
        "stderr_total_bytes": int(captured.get("stderr_total_bytes", len(stderr))),
        "output_limit_exceeded": bool(captured.get("stdout_limit_exceeded") or captured.get("stderr_limit_exceeded")),
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
            "telemetry": "parent_derived" if offline_report is not None else "unavailable",
        },
        "process_containment": {
            "enforced": containment_boundary is not None,
            "boundary": containment_boundary,
            "cleanup_verified": not cleanup_failed,
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
        os.chmod(target, 0o400)
    if target.stat().st_size > _MAX_PARENT_FILE_BYTES or _sha_bytes(target.read_bytes()) != digest:
        raise AcceptanceError("staged_artifact_digest_mismatch")
    return target, digest


def _stage_runtime(root: Path, workspace: Path, *, expected: str | None = None) -> tuple[Path, str]:
    return _stage_file(root, "perseus.py", workspace, expected=expected, immutable=True)


def _operation_state_snapshot(workspace: Path) -> dict[str, str]:
    """Hash workspace files before an operation for receipt provenance."""
    try:
        entries = _sorted_files(workspace)
    except (OSError, TypeError, ValueError, AcceptanceError):
        raise AcceptanceError("operation_receipt_invalid") from None
    return {str(entry["path"]): str(entry["sha256"]) for entry in entries}


def _parse_operation_receipt(
    text: str,
    *,
    action: str,
    version: str,
    artifact_sha256: str,
    query: str,
    workspace: Path,
    operation_baseline: Mapping[str, str] | None = None,
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
    state_rel = Path(state_path) if isinstance(state_path, str) else Path(".")
    normalized_state_path = str(state_rel).replace(os.sep, "/")
    if (
        not isinstance(state_path, str)
        or not state_path.strip()
        or state_rel.is_absolute()
        or ".." in state_rel.parts
        or ".perseus-immutable" in state_rel.parts
        or normalized_state_path != _OPERATION_STATE_PATH
        or not isinstance(state_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", state_digest)
        or not isinstance(operation_baseline, Mapping)
    ):
        raise AcceptanceError("operation_receipt_invalid")
    try:
        actual_state = _sha_bytes(_secure_file_bytes(workspace, state_path))
    except (OSError, TypeError, ValueError, AcceptanceError):
        raise AcceptanceError("operation_receipt_invalid") from None
    if actual_state != state_digest.lower():
        raise AcceptanceError("operation_receipt_invalid")
    if normalized_state_path in operation_baseline and operation_baseline[normalized_state_path] == actual_state:
        raise AcceptanceError("operation_receipt_invalid")
    return dict(value)


def _resolve_staged_argv(
    command: list[str],
    *,
    root: Path,
    artifact_path: str,
    staged_artifact: Path,
    staged_runtime: Path,
) -> list[str]:
    """Resolve an explicitly allowlisted command to immutable stage paths."""
    argv = _validate_command(command, "operation")
    source_artifact = (root / artifact_path).resolve()
    source_runtime = (root / "perseus.py").resolve()
    interpreter = Path(sys.executable).resolve()

    def resolve_token(raw: str) -> Path | None:
        try:
            candidate = Path(raw)
            return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            return None

    def rewrite_path(raw: str) -> str | None:
        candidate = resolve_token(raw)
        if raw == artifact_path or candidate == source_artifact:
            return str(staged_artifact)
        if raw == "perseus.py" or candidate == source_runtime:
            return str(staged_runtime)
        return None

    first = argv[0]
    first_resolved = resolve_token(first)
    is_interpreter = first == sys.executable or first_resolved == interpreter
    if is_interpreter:
        if len(argv) < 2:
            raise AcceptanceError("operation command form is not allowlisted")
        mode = argv[1]
        if mode == "-c":
            if len(argv) < 3 or not argv[2] or any(token.startswith("-") for token in argv[2:]):
                raise AcceptanceError("operation command form is not allowlisted")
            return [sys.executable, "-c", *argv[2:]]
        if mode.startswith("-"):
            raise AcceptanceError("operation interpreter option is not allowlisted")
        staged_script = rewrite_path(mode)
        if staged_script is None:
            raise AcceptanceError("operation script is not manifest-bound")
        if any(token in {"-m", "-S", "-I", "-E", "-c", "--python-path"} for token in argv[2:]):
            raise AcceptanceError("operation interpreter option is not allowlisted")
        return [sys.executable, staged_script, *argv[2:]]

    staged_first = rewrite_path(first)
    if staged_first is None or first.startswith("-"):
        raise AcceptanceError("operation executable is not manifest-bound")
    if any(token.startswith("-") and token in {"-m", "-S", "-I", "-E", "-c", "--python-path"} for token in argv[1:]):
        raise AcceptanceError("operation interpreter option is not allowlisted")
    return [staged_first, *argv[1:]]


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
            "operation_artifact_sha256": actual,
            "operation_query_sha256": _sha(query_value),
            "operation_resource_limits": _validate_child_limits(resource_limits),
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
            operation_baseline = _operation_state_snapshot(workspace)
            command = _resolve_staged_argv(
                spec["command"], root=root, artifact_path=spec["path"],
                staged_artifact=staged_bundle, staged_runtime=staged_runtime,
            )
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
                command,
                cwd=workspace,
                timeout=60,
                env=env,
                resource_limits=resource_limits,
                monitor_dirs=(workspace, root),
                disk_limit_bytes=disk_limit_bytes,
                offline_required=True,
                require_process_containment=True,
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
                "process_containment": operation.get("process_containment"),
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
                        operation_baseline=operation_baseline,
                    )
                except AcceptanceError:
                    receipt = None
                if receipt is not None:
                    result.update({
                        "status": "passed",
                        "checked": True,
                        "operation_receipt": receipt,
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
            allowed_write_dirs=(state_dir,),
            disk_limit_bytes=limits["file_bytes"],
            offline_required=True,
            require_process_containment=True,
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
    child_reason = result.get("reason")
    status = "passed" if result["status"] == "passed" and result["exit_code"] == 0 and "@date" not in result["stdout"] and not result["stdout_truncated"] and not result["stderr_truncated"] and result.get("offline_sandbox") == "seccomp" else "failed"
    if post_digest != expected or staged_digest != expected or not staged_ok:
        status = "blocked"
    elif result["status"] == "blocked" and child_reason in _UNAVAILABLE_REASONS:
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
        "process_containment": result.get("process_containment"),
        "query_sha256": _sha(query_value),
        "artifact_sha256": expected,
    }
    if status == "blocked":
        result_value["reason"] = (
            child_reason
            if child_reason in _UNAVAILABLE_REASONS
            else "perseus_artifact_changed_or_guard_unavailable"
            if post_digest != expected or staged_digest != expected
            else "perseus_offline_guard_unavailable"
        )
    elif status == "failed":
        result_value["reason"] = "render_child_failed"
    return result_value


def _run_adapter(
    root: Path,
    spec: Mapping[str, Any],
    manifest: Mapping[str, Any],
    resource_limits: Mapping[str, int],
    *,
    runtime_digest: str | None = None,
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
            runtime_expected = runtime_digest
            if not isinstance(runtime_expected, str):
                runtime_expected = _sha_bytes(_secure_file_bytes(root, "perseus.py"))
            if not re.fullmatch(r"[0-9a-f]{64}", runtime_expected):
                return {"status": "blocked", "reason": "adapter_digest_unavailable"}
            staged_runtime, runtime_digest = _stage_runtime(root, workspace, expected=runtime_expected)
            operation_baseline = _operation_state_snapshot(workspace)
            command = _resolve_staged_argv(
                spec["command"], root=root, artifact_path=spec["path"],
                staged_artifact=staged_artifact, staged_runtime=staged_runtime,
            )
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
                require_process_containment=True,
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
                "process_containment": operation.get("process_containment"),
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
                        operation_baseline=operation_baseline,
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


def _resource_envelope(before_cpu: float, before_rss: int | None, before_disk: int, output_dir: Path, started: float) -> dict[str, Any]:
    after_cpu = time.process_time()
    usage = (
        resource.getrusage(resource.RUSAGE_SELF)
        if os.name == "posix" and resource is not None and hasattr(resource, "RUSAGE_SELF")
        else None
    )
    if usage is None or before_rss is None:
        raise AcceptanceError("resource_metrics_unavailable")
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
            require_process_containment=True,
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
        "resource_limits": dict(resource_limits),
        "output_sha256": _stable_output_digest(result.get("stdout", "").encode("utf-8", errors="replace")),
        "output_truncated": bool(result.get("stdout_truncated") or result.get("stderr_truncated")),
        "offline_sandbox": result.get("offline_sandbox"),
        "offline_report": result.get("offline_report"),
        "offline_guard": result.get("offline_guard"),
        "process_containment": result.get("process_containment"),
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
        value["reason"] = (
            result.get("reason")
            if result.get("reason") in _UNAVAILABLE_REASONS
            else "offline_report_invalid"
            if result.get("offline_report") is None
            else "child_spawn_failed"
        )
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
    before_rss = (
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if os.name == "posix" and resource is not None and hasattr(resource, "RUSAGE_SELF")
        else None
    )
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
        child_limits, runtime_digest=perseus_artifact["sha256"], monitor_dir=out, disk_limit_bytes=child_limits["file_bytes"], query=workload_query, aggregate_budget=aggregate_budget,
    )
    flow["ledger"] = _run_adapter(
        root, artifact_specs["perseus-ledger"], _artifact_by_name(artifacts, "perseus-ledger"),
        child_limits, runtime_digest=perseus_artifact["sha256"], monitor_dir=out, disk_limit_bytes=child_limits["file_bytes"], query=workload_query, aggregate_budget=aggregate_budget,
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
    restore_unavailable = restore.get("reason") in _UNAVAILABLE_REASONS
    flow["backup_restore"] = {
        "status": "passed" if restore_passed else "unavailable" if restore_unavailable else "failed",
        "reason": "operation_completed" if restore_passed else restore.get("reason") if restore_unavailable else "restore_state_mismatch" if restore_error is None else restore_error,
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
    probe_destination = "https://example.invalid/disconnected-probe"
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
                [sys.executable, str(staged_probe_runtime), "--offline", "offline-probe", probe_destination, "--json"],
                cwd=probe_workspace,
                timeout=15,
                env=probe_env,
                resource_limits=child_limits,
                monitor_dirs=(probe_workspace, out, root),
                disk_limit_bytes=child_limits["file_bytes"],
                offline_required=True,
                require_process_containment=True,
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
        expected_probe_result = _parent_derived_probe_result(probe_destination)
        if probe_result != expected_probe_result:
            raise AcceptanceError("offline_child_probe_evidence_invalid")
        probe_result = expected_probe_result
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
        key: (
            value["render"]["offline_report"]
            if key == "backup_restore" and isinstance(value.get("render"), Mapping)
            else value["offline_report"]
        )
        for key, value in flow.items()
        if isinstance(value, Mapping)
        and (
            isinstance(value.get("offline_report"), Mapping)
            or (key == "backup_restore" and isinstance(value.get("render"), Mapping) and isinstance(value["render"].get("offline_report"), Mapping))
        )
    }
    child_guards = {
        key: (
            value["render"]["offline_guard"]
            if key == "backup_restore" and isinstance(value.get("render"), Mapping)
            else value["offline_guard"]
        )
        for key, value in flow.items()
        if isinstance(value, Mapping)
        and (
            isinstance(value.get("offline_guard"), Mapping)
            or (key == "backup_restore" and isinstance(value.get("render"), Mapping) and isinstance(value["render"].get("offline_guard"), Mapping))
        )
    }
    for key, value in (("upgrade", upgrade), ("rollback", rollback)):
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
    network_status = (
        "passed"
        if blocked and not unexpected and not network_probe.get("attempts_truncated", False) and guards_enforced and reports_bounded
        else "unavailable"
        if probe.get("reason") in _UNAVAILABLE_REASONS
        else "failed"
    )
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
        "status": network_status,
    }
    resource_envelope = _validate_resource_envelope(_resource_envelope(before_cpu, before_rss, before_disk, out, started), fixture)
    resource_envelope["aggregate_children"] = aggregate_budget.report()
    negative_results = [
        {"cell": "vault", "status": flow["vault"]["status"], "reason": _negative_result_reason(flow["vault"])},
        {"cell": "ledger", "status": flow["ledger"]["status"], "reason": _negative_result_reason(flow["ledger"])},
        {"cell": "upgrade", "status": upgrade["status"], "reason": _negative_result_reason(upgrade)},
        {"cell": "rollback", "status": rollback["status"], "reason": _negative_result_reason(rollback)},
    ]
    claims = {
        "local_offline_capable": "observed" if platform_check["status"] == "passed" and flow["perseus_render"]["status"] == "passed" and network["status"] == "passed" else "not_established",
        "iron_bank_submitted": "not_claimed",
        "iron_bank_assessed": "not_claimed",
        "customer_platform_deployable": "not_established",
        "ato_il5_il6": "not_claimed",
    }
    failed_cells = [value for value in flow.values() if isinstance(value, Mapping)] + [network, upgrade, rollback]
    failed_cells.append(resource_envelope["aggregate_children"])
    unavailable_cells = [
        item for item in failed_cells
        if isinstance(item, Mapping)
        and (
            item.get("status") == "unavailable"
            or item.get("status") in _UNAVAILABLE_REASONS
            or item.get("reason") in _UNAVAILABLE_REASONS
        )
    ]
    hard_failures = [
        item for item in failed_cells
        if isinstance(item, Mapping)
        and item.get("status") in {"failed", "blocked", "timeout", "resource_limit", "not_run", "partial"}
        and item not in unavailable_cells
    ]
    platform_variant_is_partial = _platform_variant_is_partial(platform_check)
    status = (
        "failed"
        if (platform_check["status"] != "passed" and not platform_variant_is_partial) or hard_failures
        else "partial"
        if platform_variant_is_partial or unavailable_cells or any(item["status"] in {"unavailable", "not_run"} for item in negative_results)
        else "passed"
    )
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
        key: _public_projection(value)
        for key, value in flow.items()
        if isinstance(value, Mapping)
    }
    flow_projection_commitment = _sha(flow_commitment)
    resource_observations_commitment = _sha({
        "resource_envelope": resource_envelope,
        "flow": flow_commitment,
    })
    report_core = {
        "schema_version": _REPORT_SCHEMA,
        "status": status,
        "fixture_id": fixture["fixture_id"],
        "platform": platform_check,
        "artifacts": artifacts,
        "flow_commitment": flow_commitment,
        "flow_projection_commitment": flow_projection_commitment,
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
        "claims_ceiling": fixture["claims_ceiling"],
        "manifest_commitment": manifest_commitment,
        "workload_digest": workload_digest,
        "workload_query_digest": workload_query_digest,
    }
    report_commitment = _sha(report_core)
    stable_flow_commitment = {key: _stable_projection(value) for key, value in flow_commitment.items()}
    stable_report_core = dict(report_core)
    stable_report_core["flow_commitment"] = stable_flow_commitment
    stable_report_core["flow_projection_commitment"] = _sha(stable_flow_commitment)
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
        "flow": flow_commitment,
        "resource_envelope": resource_envelope,
        "manifest_commitment": manifest_commitment,
        "report_commitment": report_commitment,
        "stable_report_commitment": stable_report_commitment,
        "evidence_digest": evidence_digest,
    }
    _validate_report_commitments(report, expected_fixture=fixture)
    manifest = {**manifest_core, "manifest_commitment": manifest_commitment, "report_commitment": report_commitment, "stable_report_commitment": stable_report_commitment}
    try:
        manifest_bytes = (_json(manifest) + "\n").encode("utf-8")
        report_bytes = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise AcceptanceError("report_serialization_failed") from None
    if len(manifest_bytes) > _MAX_REPORT_BYTES or len(report_bytes) > _MAX_REPORT_BYTES:
        raise AcceptanceError("report_too_large")
    (out / "manifest.json").write_bytes(manifest_bytes)
    (out / "report.json").write_bytes(report_bytes)
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
        if text in {"fixture_load_failed", "fixture_too_large"}:
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
