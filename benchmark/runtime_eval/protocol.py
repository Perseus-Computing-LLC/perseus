"""Stdlib-only primitives for the bounded #927 runtime-evaluation protocol.

The module deliberately contains protocol/state machinery, not benchmark
scoring.  Existing benchmark runners remain the source of scores; this module
only describes, bounds, persists, and fingerprints their execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

PROTOCOL_VERSION = "perseus-runtime-eval/v1"
MANIFEST_VERSION = PROTOCOL_VERSION
RESULT_VERSION = "perseus-runtime-eval-result/v1"
RUN_STATE_VERSION = "perseus-runtime-eval-state/v1"
SCORER_VERSION = "adapter-only/v1"

MAX_LOG_BYTES = 64 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_IDENTIFIER_LENGTH = 128


class ProtocolError(ValueError):
    """Base class for fail-closed protocol errors."""


class MixedFamilyError(ProtocolError):
    """Raised when one run attempts to combine score families."""


class LiveModeRequiredError(ProtocolError):
    """Raised when a live run was not explicitly opted into."""


class MalformedResultError(ProtocolError):
    """Raised when a wrapped runner result is not a valid result envelope."""


class LifecycleError(ProtocolError):
    """Raised for an invalid persisted lifecycle transition."""


class Family(str, Enum):
    PROMPT_ONLY = "prompt_only"
    STATEFUL = "stateful"
    WRAPPER = "wrapper"


class Status(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED_TO_START = "failed_to_start"


class _BuiltManifest(dict):
    """Public mapping with non-serializable in-process artifact provenance."""

    def __init__(self, *args: Any, verified_artifacts: Iterable[Mapping[str, Any]] = ()) -> None:
        super().__init__(*args)
        self._verified_artifacts = tuple(dict(item) for item in verified_artifacts)


FAMILIES = frozenset(item.value for item in Family)
STATUSES = frozenset(item.value for item in Status)
TERMINAL_STATUSES = frozenset(
    {
        Status.PASSED.value, Status.FAILED.value, Status.CANCELLED.value,
        Status.INTERRUPTED.value, Status.FAILED_TO_START.value,
    }
)
AUTH_MODES = frozenset({"none", "account", "environment", "api_key", "managed"})
MODES = frozenset({"offline", "live"})

# These are dropped from all public protocol projections.  The runner may read
# a child process's output transiently, but it never stores these values.
_FORBIDDEN_KEY_PARTS = (
    "prompt",
    "query",
    "memory",
    "body",
    "content",
    "secret",
    "credential",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "bearer",
    "tool_arg",
    "arguments",
    "raw",
)


def canonical_json(value: Any) -> str:
    """Serialize a digest input deterministically using only stdlib JSON."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _bounded_identifier(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > MAX_IDENTIFIER_LENGTH:
        raise ProtocolError(f"{field} must be a non-empty identifier of at most {MAX_IDENTIFIER_LENGTH} characters")
    if any(ord(ch) < 32 for ch in text):
        raise ProtocolError(f"{field} contains control characters")
    return text


def normalize_family(value: str | Family) -> str:
    text = str(value.value if isinstance(value, Family) else value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "prompt": Family.PROMPT_ONLY.value,
        "promptonly": Family.PROMPT_ONLY.value,
        "stateless": Family.PROMPT_ONLY.value,
        "prompt_only": Family.PROMPT_ONLY.value,
        "stateful": Family.STATEFUL.value,
        "memory": Family.STATEFUL.value,
        "wrapper": Family.WRAPPER.value,
        "aggregate": Family.WRAPPER.value,
    }
    normalized = aliases.get(text, text)
    if normalized not in FAMILIES:
        raise ProtocolError(f"unknown benchmark family: {value!r}")
    return normalized


def ensure_single_family(families: Iterable[str | Family]) -> str:
    normalized = {normalize_family(value) for value in families}
    if not normalized:
        raise ProtocolError("at least one benchmark family is required")
    if len(normalized) != 1:
        raise MixedFamilyError(
            "one runtime-evaluation run must contain exactly one family; "
            f"received {sorted(normalized)}"
        )
    return next(iter(normalized))


def validate_mode(mode: str, *, live: bool = False) -> str:
    normalized = str(mode or "offline").lower()
    if normalized not in MODES:
        raise ProtocolError(f"unknown runtime-evaluation mode: {mode!r}")
    if normalized == "live" and not live:
        raise LiveModeRequiredError("live mode requires an explicit live=True opt-in")
    return normalized


def _safe_scope(value: Any, *, depth: int = 0, hash_strings: bool = False) -> Any:
    """Keep scope metadata bounded without preserving sensitive payloads."""
    if depth > 3:
        return {"truncated": True}
    if isinstance(value, Mapping) and value.get("redacted") is True:
        digest = value.get("sha256")
        size = value.get("bytes")
        if (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)
                and isinstance(size, int) and not isinstance(size, bool) and size >= 0):
            return {"sha256": digest, "bytes": size, "redacted": True}
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        allowed_scope_keys = {
            "workspace", "workspace_hash", "tenant", "tenant_id", "agent",
            "agent_id", "dataset", "suite", "task", "scope",
        }
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip().lower()
            if key not in allowed_scope_keys or any(part in key for part in _FORBIDDEN_KEY_PARTS):
                continue
            if len(key) > 64:
                continue
            safe = _safe_scope(raw_value, depth=depth + 1, hash_strings=hash_strings)
            if safe is not None:
                result[key] = safe
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_scope(item, depth=depth + 1, hash_strings=hash_strings) for item in list(value)[:32]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if hash_strings:
            return _redacted_scalar(text)
        lowered = text.lower()
        if (not re.fullmatch(r"[a-z0-9][a-z0-9_.:-]{0,63}", text)
                or any(part in lowered for part in _FORBIDDEN_KEY_PARTS)):
            return None
        return _redacted_scalar(text) if hash_strings else text
    return None


def _repo_info(repo_root: Path | None) -> dict[str, Any]:
    root = Path(repo_root).resolve() if repo_root else None
    revision = "unknown"
    dirty = False
    if root and root.exists():
        try:
            revision_result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if revision_result.returncode == 0:
                revision = revision_result.stdout.strip() or "unknown"
            dirty_result = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            dirty = bool(dirty_result.stdout.strip()) if dirty_result.returncode == 0 else False
        except (OSError, subprocess.SubprocessError):
            pass
    return {"revision": revision, "dirty": dirty}


def runtime_descriptor() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }


def _hash_file(path: Path, max_bytes: int = MAX_RESULT_BYTES) -> tuple[str, int, bool]:
    digest = hashlib.sha256()
    size = path.stat().st_size
    limit = max(0, int(max_bytes))
    captured = 0
    with path.open("rb") as handle:
        while captured < limit + 1:
            chunk = handle.read(min(1024 * 1024, limit + 1 - captured))
            if not chunk:
                break
            digest.update(chunk)
            captured += len(chunk)
    return digest.hexdigest(), size, size > limit


def _relative_artifact_path(path: Path, root: Path | None) -> str:
    if root:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def artifact_metadata(path: str | os.PathLike[str], *, root: str | os.PathLike[str] | None = None,
                      max_bytes: int = MAX_RESULT_BYTES) -> dict[str, Any]:
    """Return bounded metadata and a full streaming digest, never file text."""
    target = Path(path)
    root_path = Path(root).resolve() if root else None
    if not target.is_file():
        return {
            "path": _relative_artifact_path(target, root_path),
            "exists": False,
            "sha256": None,
            "bytes": 0,
            "captured_bytes": 0,
            "truncated": False,
        }
    digest, size, truncated = _hash_file(target, max_bytes=max_bytes)
    return {
        "path": _relative_artifact_path(target, root_path),
        "exists": True,
        "sha256": digest,
        "bytes": size,
        "captured_bytes": 0,
        "truncated": truncated,
        "hash_scope": "prefix" if truncated else "full",
    }


def process_identity(pid: int) -> dict[str, int] | None:
    """Return a PID plus platform-specific identity for safe cleanup."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if os.name == "nt":
        try:
            # Embed the PID directly in the command.  Trailing arguments after
            # a powershell -Command *string* are not reliably bound to $args,
            # so "(Get-Process -Id $args[0]).Id" would probe $null, error out,
            # and make the caller treat a live leader as untrackable — leaving
            # taskkill cleanup disabled.  The PID is int-validated above.
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-Process -Id {int(pid)}).Id"],
                capture_output=True, text=True, check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip() == str(pid):
                return {"pid": pid, "start_time": pid, "pgid": pid}
        except (OSError, subprocess.SubprocessError):
            pass
        return None
    identity = _proc_stat_identity(pid)
    if identity is not None:
        return identity
    # #950: macOS/BSD have no /proc — fall back to `ps -o lstart` so
    # cancellation, recovery, persisted PGID validation, restart/requeue, and
    # descendant cleanup keep working there (PID-reuse detection relies on the
    # persisted start timestamp matching the live probe).
    return _ps_identity(pid)


def _proc_stat_identity(pid: int) -> dict[str, int] | None:
    """Linux identity from /proc/<pid>/stat (starttime + pgrp fields)."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        closing = text.rfind(")")
        fields = text[closing + 2 :].split()
        return {"pid": pid, "start_time": int(fields[19]), "pgid": int(fields[2])}
    except (FileNotFoundError, OSError, ValueError, IndexError):
        return None


def _ps_identity(pid: int) -> dict[str, int] | None:
    """BSD/macOS fallback: `ps -o pid= -o pgid= -o lstart= -p <pid>`.

    Returns ``None`` (untrackable) when the process is gone or the start
    timestamp cannot be parsed — callers treat that as cleanup-disabled,
    which is the conservative choice.
    """
    try:
        completed = subprocess.run(
            ["ps", "-o", "pid=", "-o", "pgid=", "-o", "lstart=", "-p", str(pid)],
            capture_output=True, text=True, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    m = re.match(r"\s*(\d+)\s+(\d+)\s+(.+?)\s*$", completed.stdout)
    if m is None:
        return None
    start_time = _lstart_to_epoch(m.group(3))
    if start_time is None:
        return None
    return {"pid": pid, "start_time": start_time, "pgid": int(m.group(2))}


def _lstart_to_epoch(lstart: str) -> int | None:
    """Parse ``ps -o lstart`` (e.g. "Tue Aug 11 10:00:00 2026") to epoch seconds.

    ``ps`` prints the start time in local wall-clock; ``strptime`` yields a
    naive local datetime whose ``.timestamp()`` is the correct local epoch on
    the same machine — persisted and re-probed values stay comparable.  The
    day-of-month may be space-padded ("Aug  8"), so the day field is
    zero-padded before parsing.
    """
    norm = re.sub(r"\s+", " ", lstart).strip()
    m = re.match(r"^(\w{3} \w{3}) (\d{1,2}) (\d{2}:\d{2}:\d{2}) (\d{4})$", norm)
    if m is None:
        return None
    padded = f"{m.group(1)} {m.group(2).zfill(2)} {m.group(3)} {m.group(4)}"
    try:
        return int(datetime.strptime(padded, "%a %b %d %H:%M:%S %Y").timestamp())
    except ValueError:
        return None


def _artifact_state_metadata(value: Any, *, base_dir: Path | None = None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ProtocolError("result_artifact must be artifact metadata with a path")
    if isinstance(value.get("path"), Mapping):
        path_projection = value["path"]
        allowed = {"path", "exists", "sha256", "bytes", "captured_bytes", "truncated", "hash_scope"}
        if not isinstance(path_projection, Mapping) or set(value) - allowed or set(path_projection) - {"sha256", "bytes", "redacted"}:
            raise ProtocolError("redacted result_artifact projection contains unsupported fields")
        if path_projection.get("redacted") is not True or value.get("exists") is not False:
            raise ProtocolError("redacted result_artifact projection is invalid")
        if value.get("sha256") is not None or value.get("bytes") != 0:
            raise ProtocolError("redacted missing result_artifact projection is invalid")
        return {key: value[key] for key in allowed if key in value}
    if not isinstance(value.get("path"), str):
        raise ProtocolError("result_artifact must be artifact metadata with a path")
    raw_path = value["path"]
    target = Path(raw_path)
    if base_dir is not None and not target.is_absolute():
        target = base_dir / target
    actual = artifact_metadata(target)
    comparable = ("path", "exists", "sha256", "bytes", "captured_bytes", "truncated", "hash_scope")
    for key in comparable:
        if key in value and value[key] != actual.get(key):
            raise ProtocolError(f"result_artifact.{key} does not match the file")
    if not actual["exists"]:
        actual["path"] = _redacted_scalar(raw_path)
    return actual


def sanitize_log(value: str | bytes | Mapping[str, Any] | Any, *, max_bytes: int = MAX_LOG_BYTES) -> dict[str, Any]:
    """Represent a log only by bounded metadata and a content commitment."""
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    else:
        try:
            raw = canonical_json(value).encode("utf-8")
        except Exception:
            raw = repr(value).encode("utf-8", errors="replace")
    limit = max(0, int(max_bytes))
    truncated = len(raw) > limit
    hashed = raw[: limit + 1]
    return {
        "sha256": sha256_bytes(hashed),
        "bytes": len(raw),
        "lines": raw.count(b"\n") + (1 if raw else 0),
        # No prefix/suffix is retained.  This marker makes truncation explicit
        # while preserving a strictly hash-only public boundary.
        "captured_bytes": 0,
        "truncated": truncated,
        "hash_scope": "prefix" if truncated else "full",
    }


def sanitize_log_file(path: Any, *, max_bytes: int = MAX_LOG_BYTES) -> dict[str, Any]:
    """Hash a temporary path or file object in bounded chunks and return no log text."""
    close_after = False
    if hasattr(path, "read"):
        handle = path
        try:
            handle.seek(0)
        except (OSError, AttributeError):
            pass
    else:
        target = Path(path)
        if not target.exists():
            return {"sha256": None, "bytes": 0, "lines": 0, "captured_bytes": 0, "truncated": False}
        handle = target.open("rb")
        close_after = True
    limit = max(0, int(max_bytes))
    total_size: int | None = None
    try:
        current = handle.tell()
        handle.seek(0, os.SEEK_END)
        total_size = int(handle.tell())
        handle.seek(0)
    except (OSError, AttributeError):
        try:
            handle.seek(0)
        except (OSError, AttributeError):
            pass
    digest = hashlib.sha256()
    captured = 0
    lines = 0
    try:
        while captured < limit + 1:
            chunk = handle.read(min(1024 * 1024, limit + 1 - captured))
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="replace")
            digest.update(chunk)
            captured += len(chunk)
            lines += chunk.count(b"\n")
    finally:
        if close_after:
            handle.close()
    size = total_size if total_size is not None else captured
    truncated = size > limit or captured > limit
    return {
        "sha256": digest.hexdigest(),
        "bytes": size,
        "lines": lines + (1 if captured and not lines else 0),
        "captured_bytes": 0,
        "truncated": truncated,
        "hash_scope": "prefix" if truncated else "full",
    }


def sanitize_error(error: BaseException | str, kind: str) -> dict[str, Any]:
    message = str(error)
    return {
        "kind": _bounded_identifier(kind, "failure kind"),
        "error_type": type(error).__name__ if isinstance(error, BaseException) else "Error",
        "message": sanitize_log(message),
    }


def _provider_descriptor(provider: str | Mapping[str, Any], model: str | None, version: str | None) -> dict[str, str]:
    if isinstance(provider, Mapping):
        name = provider.get("name") or provider.get("provider") or "none"
        model = provider.get("model", model)
        version = provider.get("version", version)
    else:
        name = provider
    name = _bounded_identifier(name, "provider")
    model = _bounded_identifier(model or "none", "model")
    version = _bounded_identifier(version or "unknown", "provider version")
    if any(part in name.lower() or part in model.lower() or part in version.lower() for part in ("key", "token", "secret", "password")):
        raise ProtocolError("provider descriptor appears to contain credential material")
    return {"name": name, "model": model, "version": version}


def _timestamps(values: Mapping[str, Any] | None) -> dict[str, str | None]:
    values = values or {}
    return {
        "queued_at": values.get("queued_at") or utc_now(),
        "started_at": values.get("started_at"),
        "finished_at": values.get("finished_at"),
    }


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    value = {key: item for key, item in manifest.items() if key != "manifest_digest"}
    return sha256_value(value)


def bind_manifest_run_id(manifest: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    bound = dict(manifest)
    bound["run_id"] = _bounded_identifier(run_id, "run_id")
    bound["manifest_digest"] = _manifest_digest(bound)
    return bound


def build_manifest(
    *,
    suite: str,
    family: str | Family,
    artifacts: Iterable[str | os.PathLike[str] | Mapping[str, Any]] = (),
    repo_root: str | os.PathLike[str] | None = None,
    seed: int = 0,
    scope: Any = None,
    provider: str | Mapping[str, Any] = "none",
    model: str | None = "offline-deterministic",
    provider_version: str | None = "unknown",
    auth_mode: str = "none",
    mode: str = "offline",
    live: bool = False,
    scorer_version: str = SCORER_VERSION,
    timestamps: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a self-describing, hash-bound manifest for one family."""
    normalized_family = normalize_family(family)
    normalized_mode = validate_mode(mode, live=live)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ProtocolError("seed must be a non-negative integer")
    auth = str(auth_mode or "none").strip().lower()
    if auth not in AUTH_MODES:
        raise ProtocolError(f"unknown auth mode: {auth_mode!r}")

    root = Path(repo_root).resolve() if repo_root else None
    metadata: list[dict[str, Any]] = []
    for item in artifacts:
        if isinstance(item, Mapping):
            entry = dict(item)
            item = entry.get("path")
            if not item:
                raise ProtocolError("manifest artifact metadata must include a path")
        path = Path(item)
        if not path.is_absolute() and root:
            path = root / path
        info = artifact_metadata(path, root=root)
        if not info["exists"]:
            raise ProtocolError(f"manifest artifact does not exist: {path}")
        metadata.append(info)
    metadata.sort(key=lambda entry: entry["path"])
    verified_artifacts = tuple(dict(entry) for entry in metadata)
    metadata = [{**entry, "path": _redacted_scalar(entry["path"])} for entry in metadata]
    artifact_digest = sha256_value(metadata)
    suite_name = _bounded_identifier(suite, "suite")
    provider_info = _provider_descriptor(provider, model, provider_version)
    if normalized_mode == "live" and (auth == "none" or provider_info.get("name") in {"", "none"}):
        raise LiveModeRequiredError("live mode requires an explicit provider and auth_mode")
    repo = _repo_info(root)
    safe_scope = _safe_scope(scope if scope is not None else {}, hash_strings=True)
    timestamp_info = _timestamps(timestamps)
    manifest: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "suite": suite_name,
        "suite_digest": sha256_value({"suite": suite_name, "family": normalized_family, "artifact_digest": artifact_digest}),
        "artifact_digest": artifact_digest,
        "artifacts": metadata,
        "repo": repo,
        "repo_revision": repo["revision"],
        "repo_dirty": repo["dirty"],
        "runtime": runtime_descriptor(),
        "provider": provider_info,
        "auth": {"mode": auth},
        "auth_mode": auth,
        "seed": seed,
        "scorer_version": _bounded_identifier(scorer_version, "scorer_version"),
        "family": normalized_family,
        "scope": safe_scope,
        "mode": normalized_mode,
        "timestamps": timestamp_info,
    }
    manifest["manifest_digest"] = _manifest_digest(manifest)
    return _BuiltManifest(manifest, verified_artifacts=verified_artifacts)


def _ensure_json_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MalformedResultError(f"{name} must be a JSON object")
    return value


def _has_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _FORBIDDEN_KEY_PARTS)


def _numeric_usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    fields = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "total_tokens")
    result: dict[str, int] = {}
    for field in fields:
        if field in value:
            item = value[field]
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise MalformedResultError(f"usage.{field} must be a non-negative integer")
            result[field] = item
    return result or None


def normalize_usage(value: Any) -> dict[str, Any]:
    """Keep authoritative provider counters distinct from estimates."""
    if not isinstance(value, Mapping):
        return {"source": "none", "authoritative": None, "estimate": None}
    source = str(value.get("source") or value.get("kind") or "none").lower()
    counters = _numeric_usage(value)
    if source in {"authoritative", "provider", "observed"}:
        return {"source": "authoritative", "authoritative": counters, "estimate": None}
    if source in {"estimate", "estimated", "heuristic"}:
        return {"source": "estimate", "authoritative": None, "estimate": counters}
    if value.get("authoritative") is True:
        return {"source": "authoritative", "authoritative": counters, "estimate": None}
    if counters:
        return {"source": "estimate", "authoritative": None, "estimate": counters}
    return {"source": "none", "authoritative": None, "estimate": None}


def normalize_result(value: Any, *, run_id: str | None = None, family: str | Family | None = None) -> dict[str, Any]:
    """Validate a child result and project only score/usage metadata."""
    source = _ensure_json_object(value, "result")
    if source.get("run_id") is not None and run_id is not None and str(source["run_id"]) != str(run_id):
        raise MalformedResultError("result run_id does not match the active run")
    if source.get("family") is not None and family is not None:
        if normalize_family(source["family"]) != normalize_family(family):
            raise MixedFamilyError("result family does not match the manifest family")
    status = source.get("status")
    if status is None and "pass" in source:
        status = "passed" if source["pass"] is True else "failed"
    if not isinstance(status, str) or status not in {Status.PASSED.value, Status.FAILED.value}:
        raise MalformedResultError("result status must be passed or failed")

    summary: dict[str, Any] = {
        "schema_version": RESULT_VERSION,
        "status": status,
        "passed": status == Status.PASSED.value,
        "usage": normalize_usage(source.get("usage", source.get("provider_usage"))),
        "result_digest": sha256_value(source),
    }
    signature = source.get("signature_sha256")
    if signature is not None:
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            raise MalformedResultError("signature_sha256 must be a 64-character hexadecimal digest")
        summary["signature_sha256"] = signature.lower()
    for key in ("benchmark", "dataset", "offline", "network_calls"):
        item = source.get(key)
        if isinstance(item, (str, bool, int, float)) and not _has_forbidden_key(key):
            if isinstance(item, str):
                summary[key] = _redacted_scalar(item)
            else:
                summary[key] = item
    checks = source.get("checks")
    if isinstance(checks, Mapping):
        safe_checks = {}
        for key in ("passed", "total"):
            if key not in checks:
                continue
            value = checks[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MalformedResultError(f"checks.{key} must be a non-negative integer")
            safe_checks[key] = value
        if "passed" in safe_checks and "total" in safe_checks:
            if safe_checks["passed"] > safe_checks["total"]:
                raise MalformedResultError("checks.passed cannot exceed checks.total")
            if status == Status.PASSED.value and safe_checks["passed"] != safe_checks["total"]:
                raise MalformedResultError("passed result must have all checks passed")
        if safe_checks:
            summary["checks"] = safe_checks
    metrics = source.get("metrics")
    if isinstance(metrics, Mapping):
        metric_summary: dict[str, Any] = {}
        for key, metric in metrics.items():
            if not isinstance(key, str) or _has_forbidden_key(key) or not isinstance(metric, Mapping):
                continue
            safe = {}
            for field in ("status", "rate", "numerator", "denominator"):
                item = metric.get(field)
                if field == "status" and isinstance(item, str):
                    if item in {"passed", "failed", "skipped", "blocked", "unavailable"}:
                        safe[field] = item
                    else:
                        safe[field] = _redacted_scalar(item)
                elif field in {"rate", "numerator", "denominator"} and isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item)):
                    safe[field] = item
            if safe:
                metric_name = "metric-" + sha256_bytes(key.encode("utf-8", errors="replace"))[:32]
                metric_summary[metric_name] = safe
        if metric_summary:
            summary["metrics"] = metric_summary
    return summary


_SAFE_PERSISTED_STRING_KEYS = {
    "protocol_version", "manifest_version", "schema_version", "run_id", "suite",
    "family", "status", "mode", "source", "kind", "error_type", "path",
    "sha256", "hash_scope", "provider", "model", "version", "name",
    "revision", "system", "release", "machine", "implementation", "python", "repo_dirty",
    "workspace", "workspace_hash", "tenant", "tenant_id", "agent", "agent_id",
    "dataset", "task", "scope", "auth_mode", "scorer_version", "benchmark",
    "signature_sha256", "artifact_digest", "suite_digest", "manifest_digest", "result_digest", "queued_at", "started_at", "finished_at", "decision",
}

_IDENTIFIER_VALUE_KEYS = {
    "path", "model", "dataset", "workspace", "workspace_hash", "tenant",
    "tenant_id", "agent", "agent_id", "suite", "task", "benchmark", "name",
    "source", "kind", "decision", "error_type",
}


def _redacted_scalar(value: str) -> dict[str, Any]:
    raw = value.encode("utf-8", errors="replace")
    return {"sha256": sha256_bytes(raw), "bytes": len(raw), "redacted": True}


def _safe_persisted_value(value: Any, *, depth: int = 0) -> Any:
    """Redact raw protocol payloads before they cross the persistence boundary."""
    if depth > 5:
        return {"truncated": True}
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)[:64]
            if _has_forbidden_key(key):
                continue
            if isinstance(raw_value, str) and key.lower() not in _SAFE_PERSISTED_STRING_KEYS:
                continue
            if key.lower() == "result_artifact" and isinstance(raw_value, Mapping):
                artifact_projection = _safe_persisted_value(raw_value, depth=depth + 1)
                if isinstance(artifact_projection, dict) and isinstance(raw_value.get("path"), str):
                    artifact_projection["path"] = raw_value["path"]
                safe[key] = artifact_projection
                continue
            if key.lower() == "provider" and isinstance(raw_value, Mapping):
                descriptor: dict[str, Any] = {}
                for provider_key, provider_value in raw_value.items():
                    provider_key_text = str(provider_key)[:64]
                    if _has_forbidden_key(provider_key_text):
                        continue
                    if provider_key_text in {"name", "model", "version"} and isinstance(provider_value, str):
                        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.://-]{0,127}", provider_value):
                            descriptor[provider_key_text] = provider_value
                        else:
                            descriptor[provider_key_text] = _redacted_scalar(provider_value)
                    else:
                        descriptor[provider_key_text] = _safe_persisted_value(provider_value, depth=depth + 1)
                safe[key] = descriptor
                continue
            if isinstance(raw_value, str) and key.lower() == "status":
                known_statuses = {"queued", "running", "passed", "failed", "cancelled", "interrupted", "failed_to_start", "skipped", "blocked", "unavailable"}
                safe[key] = raw_value if raw_value in known_statuses else _redacted_scalar(raw_value)
                continue
            if isinstance(raw_value, str) and key.lower() in _IDENTIFIER_VALUE_KEYS:
                known_values = {
                    "source": {"none", "authoritative", "provider", "observed", "estimate", "estimate-exact", "estimate-heuristic", "perseus", "runtime-eval-authoritative"},
                    "kind": {"cancel", "timeout", "crash", "malformed_result", "runner", "restart", "failed_to_start", "metering"},
                    "error_type": {"Error", "ValueError", "ProtocolError", "MalformedResultError"},
                    "decision": {"accepted", "blocked", "release_ready"},
                }.get(key.lower(), set())
                if raw_value in known_values:
                    safe[key] = raw_value
                else:
                    safe[key] = _redacted_scalar(raw_value)
                continue
            safe[key] = _safe_persisted_value(raw_value, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [_safe_persisted_value(item, depth=depth + 1) for item in list(value)[:128]]
    if isinstance(value, str):
        if len(value) > 4096:
            return {"sha256": sha256_bytes(value.encode("utf-8", errors="replace")), "bytes": len(value.encode("utf-8", errors="replace")), "truncated": True}
        return value
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"sha256": sha256_bytes(raw), "bytes": len(raw)}
    return {"type": type(value).__name__}


_STRUCTURAL_KEYS = {
    "state_version", "run_id", "status", "attempt", "partial", "manifest",
    "partial_results", "result", "result_artifact", "failure", "logs",
    "exit_code", "pid", "pgid", "pid_start_time", "start_time", "owned_processes",
    "created_at", "started_at", "finished_at", "updated_at", "protocol_version",
    "manifest_version", "suite", "suite_digest", "artifact_digest",
    "manifest_digest", "result_digest", "artifacts", "repo", "runtime",
    "provider", "auth", "auth_mode", "seed", "scorer_version", "family",
    "scope", "mode", "timestamps", "schema_version", "passed", "usage",
    "checks", "metrics", "benchmark", "dataset", "signature_sha256",
    "offline", "network_calls", "source", "authoritative", "estimate",
    "input", "output", "cache_read", "reasoning", "error_type", "kind",
    "message", "value", "nested", "metric", "name", "model", "version",
    "path", "exists", "sha256", "bytes", "captured_bytes", "truncated",
    "hash_scope", "redacted", "queued_at", "total", "numerator", "denominator", "rate",
    "decision", "release", "system", "machine", "implementation", "python",
    "revision", "dirty", "repo_dirty", "queued_at", "task", "workspace", "workspace_hash", "tenant",
    "tenant_id", "agent", "agent_id", "scope", "completed", "metadata",
}


def _hash_unknown_mapping_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            output_key = key if (key.lower() in _STRUCTURAL_KEYS or re.fullmatch(r"key-[0-9a-f]{32}", key)) else "key-" + sha256_bytes(key.encode("utf-8", errors="replace"))[:32]
            result[output_key] = _hash_unknown_mapping_keys(raw_value)
        return result
    if isinstance(value, list):
        return [_hash_unknown_mapping_keys(item) for item in value]
    return value


def _result_state_value(value: Any) -> Any:
    safe = _hash_unknown_mapping_keys(_safe_persisted_value(value))
    if not isinstance(safe, dict):
        return safe
    supplied = safe.pop("result_digest", None)
    digest = sha256_value(safe)
    if supplied is not None and supplied != digest:
        # Normalize/rewrite callers may have committed a pre-sanitization digest;
        # the durable commitment is always over the hash-only projection.
        pass
    safe["result_digest"] = digest
    return safe


def _validate_result_state(value: Any, *, lifecycle_status: str | None = None) -> None:
    if not isinstance(value, Mapping):
        return
    result_status = value.get("status")
    if result_status is not None and result_status not in {Status.PASSED.value, Status.FAILED.value}:
        raise ProtocolError("result status must be passed or failed")
    checks = value.get("checks")
    if isinstance(checks, Mapping) and "passed" in checks and "total" in checks:
        passed = checks["passed"]; total = checks["total"]
        if (isinstance(passed, bool) or not isinstance(passed, int) or
                isinstance(total, bool) or not isinstance(total, int) or
                passed < 0 or total < 0 or passed > total):
            raise ProtocolError("result checks are inconsistent")
        if result_status == Status.PASSED.value and passed != total:
            raise ProtocolError("passed result checks are incomplete")
    if lifecycle_status in {Status.PASSED.value, Status.FAILED.value} and result_status is not None and result_status != lifecycle_status:
        raise ProtocolError("result status disagrees with lifecycle status")


def _validate_manifest_input(manifest: Mapping[str, Any]) -> None:
    if not isinstance(manifest, Mapping):
        raise ProtocolError("manifest must be a JSON object")
    supplied_digest = manifest.get("manifest_digest")
    if supplied_digest is not None and supplied_digest != _manifest_digest(manifest):
        raise ProtocolError("manifest digest does not match supplied manifest")
    artifacts = manifest.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ProtocolError("manifest artifacts must be a list")
    verified_artifacts = getattr(manifest, "_verified_artifacts", None)
    if any(isinstance(entry, Mapping) and isinstance(entry.get("path"), Mapping) for entry in artifacts):
        if not isinstance(verified_artifacts, tuple) or len(verified_artifacts) != len(artifacts):
            raise ProtocolError("redacted manifest artifacts require in-process builder provenance")
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, Mapping):
            raise ProtocolError("manifest artifact metadata is invalid")
        if isinstance(entry.get("path"), Mapping):
            if entry["path"].get("redacted") is not True:
                raise ProtocolError("manifest artifact path projection is invalid")
            source = verified_artifacts[index]
            expected_path = _redacted_scalar(str(source.get("path", "")))
            for key in ("path", "exists", "sha256", "bytes", "truncated"):
                expected = expected_path if key == "path" else source.get(key)
                if entry.get(key) != expected:
                    raise ProtocolError(f"manifest artifact {key} does not match builder provenance")
            continue
        if not isinstance(entry.get("path"), str):
            raise ProtocolError("manifest artifact metadata is invalid")
        path = Path(entry["path"])
        if not path.is_absolute():
            raise ProtocolError("manifest artifact path must be a verified redacted projection")
        if path.is_absolute():
            actual = artifact_metadata(path)
            if not actual["exists"]:
                raise ProtocolError("manifest artifact does not exist")
            for key in ("exists", "sha256", "bytes", "truncated"):
                if key in entry and entry[key] != actual.get(key):
                    raise ProtocolError(f"manifest artifact {key} does not match the file")


def aggregate_results(results: Iterable[Mapping[str, Any]], *, family: str | Family | None = None) -> dict[str, Any]:
    """Aggregate only results belonging to one explicitly selected family."""
    source = list(results)
    if not source:
        raise ProtocolError("at least one result is required")
    if any(item.get("family") is None for item in source):
        raise MixedFamilyError("every result must declare its benchmark family")
    families = [item.get("family") for item in source]
    selected = normalize_family(family) if family is not None else ensure_single_family(families)
    if family is not None:
        ensure_single_family([selected, *families])
    normalized = [normalize_result(item, family=selected) for item in source]
    passed = sum(item["status"] == Status.PASSED.value for item in normalized)
    return {
        "schema_version": RESULT_VERSION,
        "family": selected,
        "total": len(normalized),
        "passed": passed,
        "failed": len(normalized) - passed,
        "results": normalized,
    }


def _persisted_descendants(pid: int) -> set[int]:
    children_by_parent: dict[int, list[int]] = {}
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            text = path.read_text()
            closing = text.rfind(")")
            fields = text[closing + 2 :].split()
            child = int(path.parts[-2])
            parent = int(fields[1])
            children_by_parent.setdefault(parent, []).append(child)
        except (FileNotFoundError, OSError, ValueError, IndexError):
            continue
    pending = [pid]
    found: set[int] = set()
    while pending:
        parent = pending.pop()
        for child in children_by_parent.get(parent, ()):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def _persisted_process_belongs_to_run(pid: int, run_id: str | None) -> bool:
    if not isinstance(run_id, str) or not run_id:
        return False
    marker = f"PERSEUS_RUNTIME_EVAL_RUN_ID={run_id}".encode("utf-8")
    try:
        return marker in Path(f"/proc/{int(pid)}/environ").read_bytes().split(b"\0")
    except (FileNotFoundError, OSError, ValueError):
        return False


def _terminate_persisted_process(state: Mapping[str, Any]) -> bool:
    pgid = state.get("pgid")
    raw_pid = state.get("pid")
    pid = raw_pid if isinstance(raw_pid, int) and raw_pid > 0 else None
    owned_entries = state.get("owned_processes") if isinstance(state.get("owned_processes"), list) else []
    if pid is None and not owned_entries:
        return True
    targets: set[int] = set()
    leader_identity = process_identity(pid) if pid is not None else None
    expected_leader_start = state.get("pid_start_time")
    leader_valid = (pid is not None and isinstance(expected_leader_start, int)
                    and isinstance(pgid, int)
                    and leader_identity is not None
                    and leader_identity["start_time"] == expected_leader_start
                    and leader_identity["pgid"] == pgid)
    if leader_valid:
        targets.add(pid)
    for entry in owned_entries:
        if not isinstance(entry, Mapping):
            continue
        try:
            candidate = int(entry["pid"])
            expected_start = int(entry["start_time"])
        except (KeyError, TypeError, ValueError):
            continue
        current = process_identity(candidate)
        if (current and current["start_time"] == expected_start
                and (leader_valid or _persisted_process_belongs_to_run(candidate, state.get("run_id")))):
            targets.add(candidate)
    discovery_deadline = time.monotonic() + 1.0
    while leader_valid and time.monotonic() < discovery_deadline:
        targets.update(_persisted_descendants(pid))
        if targets - {pid}:
            break
        time.sleep(0.01)
    if os.name == "nt":
        if leader_valid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        return bool(leader_valid or targets)
    if leader_valid and isinstance(pgid, int) and pgid > 0:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for value in targets:
        try:
            os.kill(value, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        live: set[int] = set()
        for value in targets:
            try:
                fields = Path(f"/proc/{value}/stat").read_text().split()
                if len(fields) > 2 and fields[2] != "Z":
                    live.add(value)
                    os.kill(value, signal.SIGKILL)
                    subprocess.run(["kill", "-KILL", str(value)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, ValueError):
                pass
        if not live:
            break
        time.sleep(0.02)
    if leader_valid and isinstance(pgid, int) and pgid > 0:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for value in targets:
        try:
            fields = Path(f"/proc/{value}/stat").read_text().split()
            if len(fields) > 2 and fields[2] != "Z":
                return False
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return False
    return bool(leader_valid or targets)


def _safe_state_field(key: str, value: Any, *, base_dir: Path | None = None) -> Any:
    if key == "scope":
        return _safe_scope(value or {}, hash_strings=True)
    if key.lower() in _IDENTIFIER_VALUE_KEYS and isinstance(value, str):
        return _redacted_scalar(value)
    if key == "result_artifact":
        return _artifact_state_metadata(value, base_dir=base_dir)
    if key == "result":
        return _result_state_value(value)
    return _hash_unknown_mapping_keys(_safe_persisted_value(value))


class RunStore:
    """Atomic JSON state store for one runtime-evaluation directory."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def new_run_id() -> str:
        return "run-" + uuid.uuid4().hex

    def run_dir(self, run_id: str) -> Path:
        _bounded_identifier(run_id, "run_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
            raise ProtocolError("run_id contains unsupported characters")
        return self.root / run_id

    def state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state.json"

    def load(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            path = self.state_path(run_id)
            if not path.is_file():
                raise ProtocolError(f"unknown run_id: {run_id}")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProtocolError(f"invalid persisted run state: {run_id}") from exc
            if not isinstance(value, dict) or value.get("run_id") != run_id or value.get("status") not in STATUSES:
                raise ProtocolError(f"invalid persisted run state: {run_id}")
            raw_artifact = value.get("result_artifact")
            if raw_artifact is not None:
                _artifact_state_metadata(raw_artifact, base_dir=self.run_dir(run_id))
            safe = _hash_unknown_mapping_keys(_safe_persisted_value(value))
            manifest = safe.get("manifest")
            if (not isinstance(manifest, dict)
                    or manifest.get("run_id") != run_id
                    or manifest.get("manifest_digest") != _manifest_digest(manifest)):
                raise ProtocolError(f"manifest digest or run identity mismatch: {run_id}")
            result = safe.get("result")
            if result is not None:
                if not isinstance(result, dict) or result.get("result_digest") != sha256_value({k: v for k, v in result.items() if k != "result_digest"}):
                    raise ProtocolError(f"result digest mismatch: {run_id}")
            return safe

    def _write(self, state: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = dict(state)
            target = self.state_path(str(value["run_id"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            value["updated_at"] = utc_now()
            fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=str(target.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            return value

    def create(self, manifest: Mapping[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        run_id = run_id or self.new_run_id()
        _bounded_identifier(run_id, "run_id")
        target = self.state_path(run_id)
        if target.exists():
            raise ProtocolError(f"run_id already exists: {run_id}")
        _validate_manifest_input(manifest)
        safe_manifest = _hash_unknown_mapping_keys(_safe_persisted_value(manifest))
        if not isinstance(safe_manifest, dict):
            raise ProtocolError("manifest must be a JSON object")
        if "scope" in safe_manifest:
            safe_manifest["scope"] = _safe_scope(safe_manifest.get("scope") or {}, hash_strings=True)
        # Recompute the manifest commitment after the persistence projection;
        # the public builder's digest covered the pre-persistence scope shape.
        safe_manifest["manifest_digest"] = _manifest_digest(safe_manifest)
        bound_manifest = bind_manifest_run_id(safe_manifest, run_id)
        now = utc_now()
        state = {
            "state_version": RUN_STATE_VERSION,
            "run_id": run_id,
            "status": Status.QUEUED.value,
            "attempt": 1,
            "partial": False,
            "manifest": bound_manifest,
            "partial_results": {},
            "result": None,
            "result_artifact": None,
            "failure": None,
            "logs": {},
            "exit_code": None,
            "pid": None,
            "pgid": None,
            "pid_start_time": None,
            "owned_processes": [],
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "updated_at": now,
        }
        return self._write(state)

    def update(self, run_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            return self._update_unlocked(run_id, **fields)

    def _update_unlocked(self, run_id: str, **fields: Any) -> dict[str, Any]:
        state = self.load(run_id)
        for key, value in fields.items():
            if key in {"run_id", "state_version", "manifest", "status", "attempt"}:
                raise ProtocolError(f"field cannot be updated with update(): {key}")
            if key == "result":
                _validate_result_state(value, lifecycle_status=state.get("status"))
            state[key] = _safe_state_field(key, value, base_dir=self.run_dir(run_id))
        return self._write(state)

    def update_if_attempt(self, run_id: str, attempt: int, *, expected_status: str = Status.RUNNING.value, **fields: Any) -> bool:
        """Atomically update fields only while the expected generation/status matches."""
        with self._lock:
            state = self.load(run_id)
            if int(state.get("attempt", 1)) != int(attempt) or state.get("status") != expected_status:
                return False
            for key, value in fields.items():
                if key in {"run_id", "state_version", "manifest", "status", "attempt"}:
                    raise ProtocolError(f"field cannot be updated with update_if_attempt(): {key}")
                if key == "result":
                    _validate_result_state(value, lifecycle_status=state.get("status"))
                state[key] = _safe_state_field(key, value, base_dir=self.run_dir(run_id))
            self._write(state)
            return True


    def transition(self, run_id: str, status: str | Status, *, partial: bool | None = None,
                   expected_attempt: int | None = None,
                   failure: Mapping[str, Any] | None = None, **fields: Any) -> dict[str, Any] | None:
        state = self.load(run_id)
        if expected_attempt is not None and (int(state.get("attempt", 1)) != int(expected_attempt) or state.get("status") != Status.RUNNING.value):
            return None
        target = str(status.value if isinstance(status, Status) else status)
        if target not in STATUSES:
            raise LifecycleError(f"unknown lifecycle status: {target}")
        current = state["status"]
        allowed = {
            Status.QUEUED.value: {Status.RUNNING.value, Status.CANCELLED.value, Status.FAILED_TO_START.value, Status.INTERRUPTED.value},
            Status.RUNNING.value: {Status.PASSED.value, Status.FAILED.value, Status.CANCELLED.value, Status.INTERRUPTED.value, Status.FAILED_TO_START.value},
            Status.INTERRUPTED.value: {Status.QUEUED.value, Status.CANCELLED.value, Status.FAILED.value},
            Status.FAILED.value: {Status.QUEUED.value},
            Status.CANCELLED.value: {Status.QUEUED.value},
            Status.FAILED_TO_START.value: {Status.QUEUED.value},
            Status.PASSED.value: set(),
        }
        if target != current and target not in allowed.get(current, set()):
            raise LifecycleError(f"invalid lifecycle transition {current!r} -> {target!r}")
        if target == Status.PASSED.value:
            candidate_result = fields.get("result", state.get("result"))
            if candidate_result is None:
                raise ProtocolError("passed lifecycle state requires a result")
            _validate_result_state(candidate_result, lifecycle_status=target)
        state["status"] = target
        if partial is not None:
            state["partial"] = bool(partial)
        if failure is not None:
            state["failure"] = _safe_persisted_value(dict(failure))
        for key, value in fields.items():
            if key in {"run_id", "state_version", "manifest", "status", "attempt"}:
                raise ProtocolError(f"field cannot be set by transition(): {key}")
            if key == "result":
                _validate_result_state(value, lifecycle_status=target)
            state[key] = _safe_state_field(key, value, base_dir=self.run_dir(run_id))
        if target == Status.RUNNING.value and state.get("started_at") is None:
            state["started_at"] = utc_now()
        if target in TERMINAL_STATUSES or target == Status.INTERRUPTED.value:
            state["finished_at"] = utc_now()
        return self._write(state)

    def recover_running(self, *, exclude: Iterable[str] = ()) -> list[dict[str, Any]]:
        excluded = set(exclude)
        recovered = []
        for path in sorted(self.root.glob("*/state.json")):
            run_id = path.parent.name
            if run_id in excluded:
                continue
            try:
                state = self.load(run_id)
            except ProtocolError:
                continue
            if state["status"] == Status.RUNNING.value:
                cleaned = _terminate_persisted_process(state)
                if cleaned:
                    recovered.append(
                        self.transition(
                            run_id,
                            Status.INTERRUPTED,
                            partial=True,
                            failure=sanitize_error("process is no longer attached after restart", "restart"),
                            pid=None, pgid=None, pid_start_time=None, owned_processes=[],
                        )
                    )
                else:
                    recovered.append(self.update(
                        run_id,
                        recovery_failure=sanitize_error("owned process cleanup could not be proven", "restart"),
                    ))
        return recovered

    def requeue(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            state = self.load(run_id)
            if state["status"] not in {Status.INTERRUPTED.value, Status.FAILED.value, Status.CANCELLED.value, Status.FAILED_TO_START.value}:
                raise LifecycleError(f"run {run_id} is not restartable from {state['status']!r}")
            state["status"] = Status.QUEUED.value
            state["partial"] = bool(state.get("partial"))
            state["attempt"] = int(state.get("attempt", 1)) + 1
            state["finished_at"] = None
            state["failure"] = None
            state["exit_code"] = None
            state["pid"] = None
            state["pgid"] = None
            state["pid_start_time"] = None
            state["owned_processes"] = []
            state["result_artifact"] = None
            state["result"] = None
            state["partial_results"] = {}
            return self._write(state)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        states = []
        for path in sorted(self.root.glob("*/state.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                states.append(self.load(path.parent.name))
            except ProtocolError:
                continue
            if len(states) >= limit:
                break
        return states


__all__ = [
    "AUTH_MODES",
    "Family",
    "FAMILIES",
    "LifecycleError",
    "LiveModeRequiredError",
    "MalformedResultError",
    "MANIFEST_VERSION",
    "MAX_ARTIFACT_BYTES",
    "MAX_LOG_BYTES",
    "MAX_RESULT_BYTES",
    "MixedFamilyError",
    "MODES",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "RESULT_VERSION",
    "RunStore",
    "RUN_STATE_VERSION",
    "SCORER_VERSION",
    "STATUSES",
    "Status",
    "TERMINAL_STATUSES",
    "artifact_metadata",
    "bind_manifest_run_id",
    "build_manifest",
    "canonical_json",
    "ensure_single_family",
    "normalize_family",
    "normalize_result",
    "normalize_usage",
    "process_identity",
    "runtime_descriptor",
    "sanitize_error",
    "sanitize_log",
    "sanitize_log_file",
    "sha256_bytes",
    "sha256_value",
    "utc_now",
    "validate_mode",
]

# Backwards-compatible spelling for callers that use the more explicit name.
MAX_ARTIFACT_BYTES = MAX_RESULT_BYTES
