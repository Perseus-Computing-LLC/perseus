"""Versioned, resource-aware execution profiles for context compilation (#980).

This module defines a deterministic planning contract only. It does not select a
model, call a provider, measure hardware, or persist resource telemetry. A
profile describes hard context limits and explicit degradation/network policy;
resolution returns a sanitized manifest that a compiler or runtime adapter can
consume.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

_EP_SCHEMA_VERSION = "perseus-execution-profile/v1"
_EP_DIAGNOSTIC_SCHEMA_VERSION = "perseus-execution-diagnostics/v1"
_EP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_EP_ALLOWED_FIELDS = frozenset({
    "schema_version", "profile_id", "mode", "max_context_tokens",
    "max_context_bytes", "max_items", "max_depth", "latency_target_ms",
    "resource_class", "network_mode", "runtime_capabilities",
    "degradation_policy", "auth_mode", "runtime_ref", "model_ref",
})
_EP_REQUIREMENT_FIELDS = frozenset({
    "network_mode", "require_offline", "required_capabilities",
    "max_context_tokens", "max_context_bytes", "max_items", "max_depth",
    "latency_target_ms",
})
_EP_RESOURCE_FIELDS = frozenset({
    "memory_class", "compute_class", "network_available",
    "available_memory_mb", "available_compute_units", "resource_metrics",
})
_EP_NETWORK_MODES = frozenset({"offline", "local", "approved_network"})
_EP_NETWORK_RANK = {"offline": 0, "local": 1, "approved_network": 2}
_EP_DEGRADATION_POLICIES = frozenset({"fail_closed", "partial", "omit_low_priority"})
_EP_RETRIEVAL_STATES = frozenset({"complete", "partial", "degraded", "unavailable", "timeout"})
_EP_MODE_DEFAULTS = {
    "standard-local": {
        "max_context_tokens": 8192,
        "max_context_bytes": 32768,
        "max_items": 64,
        "max_depth": 4,
        "latency_target_ms": None,
        "resource_class": "unknown",
        "network_mode": "local",
        "degradation_policy": "partial",
    },
    "constrained-edge": {
        "max_context_tokens": 2048,
        "max_context_bytes": 8192,
        "max_items": 16,
        "max_depth": 2,
        "latency_target_ms": 500,
        "resource_class": "edge",
        "network_mode": "local",
        "degradation_policy": "partial",
    },
    "air-gapped": {
        "max_context_tokens": 4096,
        "max_context_bytes": 16384,
        "max_items": 32,
        "max_depth": 3,
        "latency_target_ms": None,
        "resource_class": "isolated",
        "network_mode": "offline",
        "degradation_policy": "fail_closed",
    },
}
_EP_FORBIDDEN_KEYS = frozenset({
    "api_key", "authorization", "body", "content", "credential", "credentials",
    "password", "private_body", "prompt", "raw", "raw_payload", "secret",
    "token", "tool_args", "tool_arguments",
})


class ExecutionProfileError(ValueError):
    """Raised when a profile or hard capability requirement is invalid."""


def _ep_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _ep_sha(value: Any) -> str:
    return hashlib.sha256(_ep_json(value).encode("utf-8")).hexdigest()


def _ep_text(value: Any, field: str, *, max_length: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExecutionProfileError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text) > max_length:
        raise ExecutionProfileError(f"{field} is too long")
    if any(key in text.casefold().replace("-", "_") for key in _EP_FORBIDDEN_KEYS):
        raise ExecutionProfileError(f"{field} contains forbidden credential/raw-data marker")
    return text


def _ep_id(value: Any, field: str, *, default: str = "") -> str:
    text = _ep_text(value if value is not None else default, field)
    if any(marker in text for marker in ("://", "@", "?", "&", "=")):
        raise ExecutionProfileError(f"{field} must not contain URI/userinfo/query syntax")
    if not _EP_ID_RE.fullmatch(text):
        raise ExecutionProfileError(f"{field} must be a bounded identifier")
    return text


def _ep_limit(value: Any, field: str, *, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExecutionProfileError(f"{field} must be a positive integer")
    number = value
    if number < 1 or number > maximum:
        raise ExecutionProfileError(f"{field} must be between 1 and {maximum}")
    return number


def _ep_optional_limit(value: Any, field: str, *, maximum: int = 10_000_000) -> int | None:
    if value is None:
        return None
    return _ep_limit(value, field, maximum=maximum)


def _ep_forbidden_keys(value: Any, path: str = "profile") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _EP_FORBIDDEN_KEYS:
                raise ExecutionProfileError(f"{path}.{key} is not permitted")
            _ep_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _ep_forbidden_keys(nested, f"{path}[{index}]")


@dataclass(frozen=True)
class ExecutionProfile:
    """A bounded, portable description of the resources a compiler may use."""

    schema_version: str
    profile_id: str
    mode: str
    max_context_tokens: int
    max_context_bytes: int
    max_items: int
    max_depth: int
    latency_target_ms: int | None
    resource_class: str
    network_mode: str
    runtime_capabilities: tuple[str, ...]
    degradation_policy: str
    auth_mode: str
    runtime_ref: str = ""
    model_ref: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "ExecutionProfile" | None) -> "ExecutionProfile":
        if isinstance(value, cls):
            value = value.to_dict()
        if value is None:
            value = {"mode": "standard-local", "profile_id": "default-local"}
        if not isinstance(value, Mapping):
            raise ExecutionProfileError("execution profile must be an object")
        _ep_forbidden_keys(value)
        unknown = set(value) - _EP_ALLOWED_FIELDS
        if unknown:
            raise ExecutionProfileError(f"unsupported execution profile fields: {sorted(map(str, unknown))}")
        mode = str(value.get("mode", "standard-local")).strip()
        if mode not in _EP_MODE_DEFAULTS:
            raise ExecutionProfileError(f"unsupported execution profile mode: {mode!r}")
        defaults = _EP_MODE_DEFAULTS[mode]
        schema_version = str(value.get("schema_version", _EP_SCHEMA_VERSION)).strip()
        if schema_version != _EP_SCHEMA_VERSION:
            raise ExecutionProfileError("unsupported execution profile schema version")
        profile_id = _ep_id(value.get("profile_id", mode), "profile_id")
        network_mode = str(value.get("network_mode", defaults["network_mode"])).strip()
        if network_mode not in _EP_NETWORK_MODES:
            raise ExecutionProfileError("network_mode must be offline, local, or approved_network")
        if mode == "air-gapped" and network_mode != "offline":
            raise ExecutionProfileError("air-gapped mode requires offline network_mode")
        degradation_policy = str(value.get("degradation_policy", defaults["degradation_policy"])).strip()
        if degradation_policy not in _EP_DEGRADATION_POLICIES:
            raise ExecutionProfileError("unsupported degradation_policy")
        capabilities = value.get("runtime_capabilities", ())
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        if not isinstance(capabilities, (list, tuple)) or len(capabilities) > 32:
            raise ExecutionProfileError("runtime_capabilities must contain at most 32 identifiers")
        capability_values = tuple(sorted({_ep_id(item, "runtime_capability") for item in capabilities}))
        auth_mode = _ep_text(value.get("auth_mode", "none"), "auth_mode", max_length=64)
        runtime_ref = _ep_id(value.get("runtime_ref", "ref:none"), "runtime_ref")
        model_ref = _ep_id(value.get("model_ref", "ref:none"), "model_ref")
        return cls(
            schema_version=schema_version,
            profile_id=profile_id,
            mode=mode,
            max_context_tokens=_ep_limit(value.get("max_context_tokens", defaults["max_context_tokens"]), "max_context_tokens"),
            max_context_bytes=_ep_limit(value.get("max_context_bytes", defaults["max_context_bytes"]), "max_context_bytes"),
            max_items=_ep_limit(value.get("max_items", defaults["max_items"]), "max_items", maximum=4096),
            max_depth=_ep_limit(value.get("max_depth", defaults["max_depth"]), "max_depth", maximum=128),
            latency_target_ms=_ep_optional_limit(value.get("latency_target_ms", defaults["latency_target_ms"]), "latency_target_ms", maximum=86_400_000),
            resource_class=_ep_text(value.get("resource_class", defaults["resource_class"]), "resource_class", max_length=64),
            network_mode=network_mode,
            runtime_capabilities=capability_values,
            degradation_policy=degradation_policy,
            auth_mode=auth_mode,
            runtime_ref=runtime_ref,
            model_ref=model_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "mode": self.mode,
            "max_context_tokens": self.max_context_tokens,
            "max_context_bytes": self.max_context_bytes,
            "max_items": self.max_items,
            "max_depth": self.max_depth,
            "latency_target_ms": self.latency_target_ms,
            "resource_class": self.resource_class,
            "network_mode": self.network_mode,
            "runtime_capabilities": list(self.runtime_capabilities),
            "degradation_policy": self.degradation_policy,
            "auth_mode": self.auth_mode,
            "runtime_ref": self.runtime_ref,
            "model_ref": self.model_ref,
        }


def _ep_requirements(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ExecutionProfileError("profile requirements must be an object")
    _ep_forbidden_keys(value, "requirements")
    unknown = set(value) - _EP_REQUIREMENT_FIELDS
    if unknown:
        raise ExecutionProfileError(f"unsupported profile requirements: {sorted(map(str, unknown))}")
    result: dict[str, Any] = {}
    for field in ("max_context_tokens", "max_context_bytes", "max_items", "max_depth", "latency_target_ms"):
        if field in value:
            if value[field] is None:
                raise ExecutionProfileError(f"requirements.{field} must be a positive integer")
            result[field] = _ep_limit(value[field], f"requirements.{field}", maximum=86_400_000 if field == "latency_target_ms" else 10_000_000)
    required = value.get("required_capabilities", ())
    if isinstance(required, str):
        required = [required]
    if not isinstance(required, (list, tuple)) or len(required) > 32:
        raise ExecutionProfileError("required_capabilities must contain at most 32 identifiers")
    result["required_capabilities"] = sorted({_ep_id(item, "required_capability") for item in required})
    if "network_mode" in value:
        network_mode = str(value["network_mode"]).strip()
        if network_mode not in _EP_NETWORK_MODES:
            raise ExecutionProfileError("requirements.network_mode is unsupported")
        result["network_mode"] = network_mode
    result["require_offline"] = value.get("require_offline", False)
    if not isinstance(result["require_offline"], bool):
        raise ExecutionProfileError("requirements.require_offline must be boolean")
    return result


def _ep_resources(value: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    if value is None:
        return {}, "unknown"
    if not isinstance(value, Mapping):
        raise ExecutionProfileError("resources must be an object")
    _ep_forbidden_keys(value, "resources")
    unknown = set(value) - _EP_RESOURCE_FIELDS
    if unknown:
        raise ExecutionProfileError(f"unsupported resource fields: {sorted(map(str, unknown))}")
    result: dict[str, Any] = {}
    for field in ("memory_class", "compute_class"):
        if value.get(field) is not None:
            result[field] = _ep_text(value[field], f"resources.{field}", max_length=64)
    if value.get("network_available") is not None:
        if not isinstance(value["network_available"], bool):
            raise ExecutionProfileError("resources.network_available must be boolean")
        result["network_available"] = value["network_available"]
    for field in ("available_memory_mb", "available_compute_units"):
        if value.get(field) is not None:
            result[field] = _ep_limit(value[field], f"resources.{field}", maximum=10_000_000_000)
    metrics = value.get("resource_metrics")
    if metrics is not None:
        if isinstance(metrics, str):
            metrics = [metrics]
        if not isinstance(metrics, (list, tuple)) or len(metrics) > 32:
            raise ExecutionProfileError("resources.resource_metrics must contain at most 32 names")
        result["resource_metrics"] = sorted({_ep_id(item, "resource_metric") for item in metrics})
    return result, "known" if result else "unknown"


def execution_profile_compilation_budget(resolved: Mapping[str, Any]) -> dict[str, Any]:
    """Project a resolved profile into the existing DAG budget vocabulary."""
    if not isinstance(resolved, Mapping) or not isinstance(resolved.get("effective"), Mapping):
        raise ExecutionProfileError("resolved execution profile is malformed")
    effective = resolved["effective"]
    latency = effective.get("latency_target_ms")
    return {
        "max_nodes": max(1, int(effective["max_items"])),
        "max_depth": max(1, int(effective["max_depth"])),
        "max_fanout": max(1, int(effective["max_items"])),
        "max_tokens": int(effective["max_context_tokens"]),
        "max_bytes": int(effective["max_context_bytes"]),
        "deadline_s": max(0.001, float(latency) / 1000.0) if latency is not None else 30.0,
    }


def _ep_resolve_execution_profile_impl(
    profile: Mapping[str, Any] | ExecutionProfile | None = None,
    *,
    requirements: Mapping[str, Any] | None = None,
    resources: Mapping[str, Any] | None = None,
    retrieval_status: str = "complete",
) -> dict[str, Any]:
    """Resolve hard limits and capabilities into a digest-sealed manifest."""
    base = ExecutionProfile.from_mapping(profile)
    req = _ep_requirements(requirements)
    if retrieval_status not in _EP_RETRIEVAL_STATES:
        raise ExecutionProfileError("retrieval_status is unsupported")
    requested_network = req.get("network_mode")
    if requested_network and _EP_NETWORK_RANK[requested_network] > _EP_NETWORK_RANK[base.network_mode]:
        raise ExecutionProfileError(f"profile network policy {base.network_mode} cannot satisfy requested {requested_network} requirement")
    if req.get("require_offline") and _EP_NETWORK_RANK[base.network_mode] < _EP_NETWORK_RANK["offline"]:
        raise ExecutionProfileError("profile does not satisfy required offline mode")
    missing = sorted(set(req.get("required_capabilities", ())) - set(base.runtime_capabilities))
    if missing:
        raise ExecutionProfileError(f"required capabilities are unsupported: {', '.join(missing)}")
    safe_resources, resource_state = _ep_resources(resources)
    effective = base.to_dict()
    if req.get("require_offline") or requested_network is not None:
        effective["network_mode"] = "offline" if req.get("require_offline") else requested_network
    for field in ("max_context_tokens", "max_context_bytes", "max_items", "max_depth", "latency_target_ms"):
        if field in req and req[field] is not None:
            if field == "latency_target_ms" and effective[field] is None:
                raise ExecutionProfileError("latency target cannot be resolved without a profile latency bound")
            effective[field] = min(int(effective[field]), int(req[field]))
    if effective["max_context_tokens"] < 1 or effective["max_context_bytes"] < 1 or effective["max_items"] < 1 or effective["max_depth"] < 1:
        raise ExecutionProfileError("requirements leave no usable context budget")
    reasons: list[str] = []
    status = "complete"
    abstention_required = False
    if retrieval_status in {"partial", "degraded"}:
        status = "degraded"
        reasons.append("retrieval_partial")
    elif retrieval_status in {"unavailable", "timeout"}:
        status = "degraded"
        reasons.append(f"retrieval_{retrieval_status}")
        abstention_required = True
    diagnostics = {
        "schema_version": _EP_DIAGNOSTIC_SCHEMA_VERSION,
        "degraded": bool(reasons),
        "reasons": reasons,
        "resource_state": resource_state,
        "abstention_required": abstention_required,
        "degradation_policy": base.degradation_policy,
    }
    resolved: dict[str, Any] = {
        "schema_version": _EP_SCHEMA_VERSION,
        "profile": base.to_dict(),
        "effective": effective,
        "requirements": req,
        "resources": safe_resources,
        "resource_state": resource_state,
        "status": status,
        "diagnostics": diagnostics,
    }
    resolved["compilation_budget"] = execution_profile_compilation_budget(resolved)
    resolved["profile_digest"] = _ep_sha(resolved)
    return resolved


class _EPExecutionProfileResolver:
    """Callable API object kept outside the directive resolver registry."""

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _ep_resolve_execution_profile_impl(*args, **kwargs)


resolve_execution_profile = _EPExecutionProfileResolver()


def negotiate_context_budget(
    profile: Mapping[str, Any] | ExecutionProfile | None = None,
    *,
    requested_tokens: int | None = None,
    requested_bytes: int | None = None,
    requested_items: int | None = None,
    requested_depth: int | None = None,
    retrieval_status: str = "complete",
    resources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    requirements: dict[str, Any] = {}
    for name, value in (
        ("max_context_tokens", requested_tokens),
        ("max_context_bytes", requested_bytes),
        ("max_items", requested_items),
        ("max_depth", requested_depth),
    ):
        if value is not None:
            requirements[name] = value
    return resolve_execution_profile(
        profile,
        requirements=requirements,
        resources=resources,
        retrieval_status=retrieval_status,
    )


def verify_execution_profile(resolved: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the digest and recompute every resolved profile relationship."""
    required = {
        "schema_version", "profile", "effective", "requirements", "resources",
        "resource_state", "status", "diagnostics", "compilation_budget",
        "profile_digest",
    }
    if not isinstance(resolved, Mapping) or set(resolved) != required:
        return {"valid": False, "error": "resolved profile shape is invalid"}
    supplied = resolved.get("profile_digest")
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return {"valid": False, "error": "profile digest must be a SHA-256 string"}
    try:
        diagnostics = resolved["diagnostics"]
        if not isinstance(diagnostics, Mapping) or set(diagnostics) != {
            "schema_version", "degraded", "reasons", "resource_state",
            "abstention_required", "degradation_policy",
        }:
            return {"valid": False, "error": "profile diagnostics shape is invalid"}
        reasons = diagnostics["reasons"]
        if not isinstance(reasons, list) or any(not isinstance(reason, str) for reason in reasons):
            return {"valid": False, "error": "profile diagnostic reasons are invalid"}
        retrieval_reasons = {
            "retrieval_partial": "partial",
            "retrieval_degraded": "degraded",
            "retrieval_unavailable": "unavailable",
            "retrieval_timeout": "timeout",
        }
        retrieval_states = {retrieval_reasons[reason] for reason in reasons if reason in retrieval_reasons}
        if len(retrieval_states) > 1 or any(
            reason not in retrieval_reasons and reason not in {"max_depth", "max_items", "max_context_tokens", "max_context_bytes"}
            for reason in reasons
        ):
            return {"valid": False, "error": "profile diagnostic reasons are invalid"}
        retrieval_status = next(iter(retrieval_states), "complete")
        expected = _ep_resolve_execution_profile_impl(
            resolved["profile"],
            requirements=resolved["requirements"] or None,
            resources=resolved["resources"],
            retrieval_status=retrieval_status,
        )
        candidate = dict(resolved)
        candidate["profile_digest"] = expected["profile_digest"]
        if _ep_json(candidate) != _ep_json(expected):
            return {
                "valid": False,
                "profile_digest": supplied,
                "expected_digest": expected["profile_digest"],
                "error": "resolved profile does not recompute from its inputs",
            }
        unsigned = dict(resolved)
        unsigned.pop("profile_digest")
        expected_digest = _ep_sha(unsigned)
    except (ExecutionProfileError, TypeError, ValueError, KeyError):
        return {"valid": False, "error": "profile manifest is not valid"}
    return {
        "valid": expected_digest == supplied,
        "profile_digest": supplied,
        "expected_digest": expected_digest,
    }
