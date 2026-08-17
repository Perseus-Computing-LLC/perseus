"""Portable local/edge runtime adapter envelopes (#981).

The adapter seam is an integration contract, not an inference engine. Requests
carry only bounded context/profile commitments; results carry explicit status,
sanitary output, usage, and runtime provenance. The bundled reference adapter
never opens a network connection and exists only to exercise the contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from perseus.execution_profiles import ExecutionProfileError, verify_execution_profile

_RA_CAPABILITIES_SCHEMA = "perseus-runtime-capabilities/v1"
_RA_REQUEST_SCHEMA = "perseus-runtime-request/v1"
_RA_RESULT_SCHEMA = "perseus-runtime-result/v1"
_RA_NEGOTIATION_SCHEMA = "perseus-runtime-negotiation/v1"
_RA_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#@+\-]{0,159}$")
_RA_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_RA_EXECUTION_MODES = frozenset({"offline", "local", "approved_network"})
_RA_NETWORK_RANK = {"offline": 0, "local": 1, "approved_network": 2}
_RA_RESULT_STATUSES = frozenset({"success", "partial", "unavailable", "timeout", "cancelled", "malformed"})
_RA_CAPABILITY_FIELDS = frozenset({
    "schema_version", "backend_id", "backend_version", "model_id", "model_version",
    "tokenizer_id", "context_capacity_tokens", "execution_modes", "streaming", "tools",
    "hardware_class", "resource_metrics", "auth_mode", "provider_ref",
})
_RA_REQUEST_FIELDS = frozenset({
    "schema_version", "request_id", "execution_profile", "execution_profile_digest", "context_digest",
    "evidence_digest", "input_digest", "execution_mode", "required_capabilities",
    "max_output_chars",
})
_RA_RESULT_FIELDS = frozenset({
    "schema_version", "request_id", "status", "output", "usage", "runtime",
    "error_code", "error_message", "external_fallback_allowed",
})
_RA_FORBIDDEN_KEYS = frozenset({
    "api_key", "authorization", "body", "content", "credential", "credentials",
    "password", "private_body", "prompt", "raw", "raw_payload", "secret", "token",
    "tool_args", "tool_arguments",
})
_RA_RUNTIME_FIELDS = frozenset({
    "backend_id", "backend_version", "model_id", "model_version", "auth_mode",
    "provider_ref", "execution_mode",
})
_RA_USAGE_FIELDS = frozenset({"input_tokens", "output_tokens", "latency_ms"})


class RuntimeAdapterError(ValueError):
    """Raised when an adapter envelope cannot be admitted safely."""


def _ra_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _ra_sha(value: Any) -> str:
    return hashlib.sha256(_ra_json(value).encode("utf-8")).hexdigest()


def _ra_text(value: Any, field: str, *, max_length: int = 160, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise RuntimeAdapterError(f"{field} must be text")
    text = value.strip()
    if not text and not allow_empty:
        raise RuntimeAdapterError(f"{field} must not be empty")
    if len(text) > max_length:
        raise RuntimeAdapterError(f"{field} is too long")
    return text


def _ra_id(value: Any, field: str, *, allow_empty: bool = False) -> str:
    text = _ra_text(value, field, allow_empty=allow_empty)
    if any(marker in text for marker in ("://", "@", "?", "&", "=")):
        raise RuntimeAdapterError(f"{field} must not contain URI/userinfo/query syntax")
    if text and not _RA_ID_RE.fullmatch(text):
        raise RuntimeAdapterError(f"{field} must be a bounded identifier")
    return text


def _ra_digest(value: Any, field: str) -> str:
    text = _ra_text(value, field, max_length=71).lower()
    if not _RA_DIGEST_RE.fullmatch(text):
        raise RuntimeAdapterError(f"{field} must be a SHA-256 digest")
    return text.removeprefix("sha256:")


def _ra_limit(value: Any, field: str, *, maximum: int = 10_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeAdapterError(f"{field} must be a positive integer")
    number = value
    if number < 1 or number > maximum:
        raise RuntimeAdapterError(f"{field} must be between 1 and {maximum}")
    return number


def _ra_forbidden_keys(value: Any, path: str = "envelope") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _RA_FORBIDDEN_KEYS:
                raise RuntimeAdapterError(f"{path}.{key} is not permitted")
            _ra_forbidden_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _ra_forbidden_keys(nested, f"{path}[{index}]")


def _ra_string_list(value: Any, field: str, *, maximum: int = 32) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or len(value) > maximum:
        raise RuntimeAdapterError(f"{field} must contain at most {maximum} identifiers")
    return tuple(sorted({_ra_id(item, field) for item in value}))


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Sanitized capabilities advertised by one runtime/backend."""

    schema_version: str
    backend_id: str
    backend_version: str
    model_id: str
    model_version: str
    tokenizer_id: str
    context_capacity_tokens: int
    execution_modes: tuple[str, ...]
    streaming: bool
    tools: bool
    hardware_class: str
    resource_metrics: tuple[str, ...]
    auth_mode: str
    provider_ref: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "RuntimeCapabilities") -> "RuntimeCapabilities":
        if isinstance(value, cls):
            value = value.to_dict()
        if not isinstance(value, Mapping):
            raise RuntimeAdapterError("runtime capabilities must be an object")
        _ra_forbidden_keys(value, "capabilities")
        missing = _RA_CAPABILITY_FIELDS - set(value)
        if missing:
            raise RuntimeAdapterError(f"capabilities missing required fields: {sorted(map(str, missing))}")
        unknown = set(value) - _RA_CAPABILITY_FIELDS
        if unknown:
            raise RuntimeAdapterError(f"unsupported capability fields: {sorted(map(str, unknown))}")
        if value["schema_version"] != _RA_CAPABILITIES_SCHEMA:
            raise RuntimeAdapterError("unsupported runtime capabilities schema version")
        modes = _ra_string_list(value["execution_modes"], "execution_modes")
        if not modes or not set(modes).issubset(_RA_EXECUTION_MODES):
            raise RuntimeAdapterError("execution_modes must contain offline, local, or approved_network")
        metrics = _ra_string_list(value["resource_metrics"], "resource_metrics")
        for field in ("backend_id", "backend_version", "model_id", "tokenizer_id", "auth_mode", "provider_ref"):
            _ra_id(value[field], field)
        model_version = _ra_id(value["model_version"], "model_version")
        hardware_class = _ra_id(value["hardware_class"], "hardware_class")
        if not isinstance(value["streaming"], bool) or not isinstance(value["tools"], bool):
            raise RuntimeAdapterError("streaming and tools must be booleans")
        return cls(
            schema_version=_RA_CAPABILITIES_SCHEMA,
            backend_id=_ra_id(value["backend_id"], "backend_id"),
            backend_version=_ra_id(value["backend_version"], "backend_version"),
            model_id=_ra_id(value["model_id"], "model_id"),
            model_version=model_version,
            tokenizer_id=_ra_id(value["tokenizer_id"], "tokenizer_id"),
            context_capacity_tokens=_ra_limit(value["context_capacity_tokens"], "context_capacity_tokens"),
            execution_modes=modes,
            streaming=value["streaming"],
            tools=value["tools"],
            hardware_class=hardware_class,
            resource_metrics=metrics,
            auth_mode=_ra_id(value["auth_mode"], "auth_mode"),
            provider_ref=_ra_id(value["provider_ref"], "provider_ref"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend_id": self.backend_id,
            "backend_version": self.backend_version,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "tokenizer_id": self.tokenizer_id,
            "context_capacity_tokens": self.context_capacity_tokens,
            "execution_modes": list(self.execution_modes),
            "streaming": self.streaming,
            "tools": self.tools,
            "hardware_class": self.hardware_class,
            "resource_metrics": list(self.resource_metrics),
            "auth_mode": self.auth_mode,
            "provider_ref": self.provider_ref,
        }


@dataclass(frozen=True)
class AdapterRequest:
    """A digest-only request envelope for a qualified runtime adapter."""

    schema_version: str
    request_id: str
    execution_profile: dict[str, Any]
    execution_profile_digest: str
    context_digest: str
    evidence_digest: str
    input_digest: str
    execution_mode: str
    required_capabilities: dict[str, Any]
    max_output_chars: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "AdapterRequest") -> "AdapterRequest":
        if isinstance(value, cls):
            value = value.to_dict()
        if not isinstance(value, Mapping):
            raise RuntimeAdapterError("adapter request must be an object")
        _ra_forbidden_keys(value, "request")
        missing = _RA_REQUEST_FIELDS - set(value)
        if missing:
            raise RuntimeAdapterError(f"request missing required fields: {sorted(map(str, missing))}")
        unknown = set(value) - _RA_REQUEST_FIELDS
        if unknown:
            raise RuntimeAdapterError(f"unsupported request fields: {sorted(map(str, unknown))}")
        if value["schema_version"] != _RA_REQUEST_SCHEMA:
            raise RuntimeAdapterError("unsupported runtime request schema version")
        profile = value.get("execution_profile")
        if not isinstance(profile, Mapping):
            raise RuntimeAdapterError("request requires a resolved execution_profile")
        profile_check = verify_execution_profile(profile)
        if not profile_check.get("valid"):
            raise RuntimeAdapterError("execution_profile commitment is invalid")
        requested = value.get("required_capabilities", {})
        if not isinstance(requested, Mapping):
            raise RuntimeAdapterError("required_capabilities must be an object")
        allowed_required = {"streaming", "tools", "resource_metrics", "min_context_tokens"}
        if set(requested) - allowed_required:
            raise RuntimeAdapterError("unsupported required capability field")
        normalized_required: dict[str, Any] = {}
        for field in ("streaming", "tools"):
            if field in requested:
                if not isinstance(requested[field], bool):
                    raise RuntimeAdapterError(f"required_capabilities.{field} must be boolean")
                normalized_required[field] = requested[field]
        if "resource_metrics" in requested:
            normalized_required["resource_metrics"] = list(_ra_string_list(requested["resource_metrics"], "resource_metrics"))
        if "min_context_tokens" in requested:
            normalized_required["min_context_tokens"] = _ra_limit(requested["min_context_tokens"], "min_context_tokens")
        mode = _ra_text(value["execution_mode"], "execution_mode", max_length=32)
        if mode not in _RA_EXECUTION_MODES:
            raise RuntimeAdapterError("execution_mode is unsupported")
        effective_profile = profile.get("effective")
        if not isinstance(effective_profile, Mapping) or effective_profile.get("network_mode") not in _RA_NETWORK_RANK:
            raise RuntimeAdapterError("execution_profile effective network policy is missing")
        if _RA_NETWORK_RANK[mode] > _RA_NETWORK_RANK[effective_profile["network_mode"]]:
            raise RuntimeAdapterError("execution_mode exceeds execution_profile network policy")
        profile_digest = _ra_digest(value["execution_profile_digest"], "execution_profile_digest")
        manifest_digest = profile.get("profile_digest")
        if not isinstance(manifest_digest, str) or profile_digest != manifest_digest.lower().removeprefix("sha256:"):
            raise RuntimeAdapterError("execution_profile_digest does not match execution_profile")
        return cls(
            schema_version=_RA_REQUEST_SCHEMA,
            request_id=_ra_id(value["request_id"], "request_id"),
            execution_profile=dict(profile),
            execution_profile_digest=profile_digest,
            context_digest=_ra_digest(value["context_digest"], "context_digest"),
            evidence_digest=_ra_digest(value["evidence_digest"], "evidence_digest"),
            input_digest=_ra_digest(value["input_digest"], "input_digest"),
            execution_mode=mode,
            required_capabilities=normalized_required,
            max_output_chars=_ra_limit(value.get("max_output_chars", 2048), "max_output_chars", maximum=1_000_000),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "execution_profile": dict(self.execution_profile),
            "execution_profile_digest": self.execution_profile_digest,
            "context_digest": self.context_digest,
            "evidence_digest": self.evidence_digest,
            "input_digest": self.input_digest,
            "execution_mode": self.execution_mode,
            "required_capabilities": dict(self.required_capabilities),
            "max_output_chars": self.max_output_chars,
        }


@dataclass(frozen=True)
class AdapterResult:
    """Sanitized runtime result; unavailable paths never become success."""

    schema_version: str
    request_id: str
    status: str
    output: str | None
    usage: dict[str, int]
    runtime: dict[str, str]
    error_code: str | None
    error_message: str | None
    external_fallback_allowed: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | "AdapterResult") -> "AdapterResult":
        if isinstance(value, cls):
            value = value.to_dict()
        if not isinstance(value, Mapping):
            raise RuntimeAdapterError("adapter result must be an object")
        _ra_forbidden_keys(value, "result")
        unknown = set(value) - _RA_RESULT_FIELDS
        if unknown:
            raise RuntimeAdapterError(f"unsupported result fields: {sorted(map(str, unknown))}")
        missing = _RA_RESULT_FIELDS - set(value)
        if missing:
            raise RuntimeAdapterError(f"result missing required fields: {sorted(map(str, missing))}")
        if value["schema_version"] != _RA_RESULT_SCHEMA:
            raise RuntimeAdapterError("unsupported runtime result schema version")
        status = _ra_text(value["status"], "status", max_length=32)
        if status not in _RA_RESULT_STATUSES:
            raise RuntimeAdapterError("unsupported runtime result status")
        output = value["output"]
        if output is not None:
            output = _ra_text(output, "output", max_length=1_000_000, allow_empty=True)
        usage_raw = value["usage"]
        if not isinstance(usage_raw, Mapping) or set(usage_raw) - _RA_USAGE_FIELDS:
            raise RuntimeAdapterError("usage contains unsupported fields")
        usage: dict[str, int] = {}
        for key, raw in usage_raw.items():
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
                raise RuntimeAdapterError(f"usage.{key} must be a non-negative integer")
            usage[key] = raw
        runtime_raw = value["runtime"]
        if not isinstance(runtime_raw, Mapping) or set(runtime_raw) - _RA_RUNTIME_FIELDS:
            raise RuntimeAdapterError("runtime provenance contains unsupported fields")
        runtime = {str(key): _ra_id(raw, f"runtime.{key}") for key, raw in runtime_raw.items()}
        error_code = value["error_code"]
        if error_code is not None:
            error_code = _ra_id(error_code, "error_code")
        error_message = value["error_message"]
        if error_message is not None:
            error_message = _ra_text(error_message, "error_message", max_length=256)
        fallback = value["external_fallback_allowed"]
        if fallback is not False:
            raise RuntimeAdapterError("external fallback is permanently disabled by the core contract")
        if status in {"success", "partial"} and output is None:
            raise RuntimeAdapterError("successful result requires bounded output")
        if status not in {"success", "partial"} and output is not None:
            raise RuntimeAdapterError("non-success result cannot carry output")
        return cls(
            schema_version=_RA_RESULT_SCHEMA,
            request_id=_ra_id(value["request_id"], "request_id"),
            status=status,
            output=output,
            usage=usage,
            runtime=runtime,
            error_code=error_code,
            error_message=error_message,
            external_fallback_allowed=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "status": self.status,
            "output": self.output,
            "usage": dict(self.usage),
            "runtime": dict(self.runtime),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "external_fallback_allowed": False,
        }


def negotiate_runtime_capabilities(
    requirements: Mapping[str, Any] | None,
    offered: Mapping[str, Any] | RuntimeCapabilities,
) -> dict[str, Any]:
    """Return a deterministic negotiation result; never selects another backend."""
    requirements = dict(requirements or {})
    _ra_forbidden_keys(requirements, "requirements")
    allowed = {"execution_mode", "min_context_tokens", "streaming", "tools", "resource_metrics", "backend_id"}
    if set(requirements) - allowed:
        raise RuntimeAdapterError("unsupported runtime capability requirement")
    capabilities = RuntimeCapabilities.from_mapping(offered)
    normalized: dict[str, Any] = {}
    if "execution_mode" in requirements:
        mode = _ra_text(requirements["execution_mode"], "requirements.execution_mode", max_length=32)
        if mode not in _RA_EXECUTION_MODES:
            raise RuntimeAdapterError("requirements.execution_mode is unsupported")
        normalized["execution_mode"] = mode
    if "min_context_tokens" in requirements:
        normalized["min_context_tokens"] = _ra_limit(requirements["min_context_tokens"], "requirements.min_context_tokens")
    for field in ("streaming", "tools"):
        if field in requirements:
            if not isinstance(requirements[field], bool):
                raise RuntimeAdapterError(f"requirements.{field} must be boolean")
            normalized[field] = requirements[field]
    if "resource_metrics" in requirements:
        normalized["resource_metrics"] = list(_ra_string_list(requirements["resource_metrics"], "requirements.resource_metrics"))
    if "backend_id" in requirements:
        normalized["backend_id"] = _ra_id(requirements["backend_id"], "requirements.backend_id")
    missing: list[dict[str, Any]] = []
    if normalized.get("execution_mode") and normalized["execution_mode"] not in capabilities.execution_modes:
        missing.append({"capability": "execution_mode", "required": normalized["execution_mode"], "available": list(capabilities.execution_modes)})
    if normalized.get("min_context_tokens", 0) > capabilities.context_capacity_tokens:
        missing.append({"capability": "context_capacity_tokens", "required": normalized["min_context_tokens"], "available": capabilities.context_capacity_tokens})
    for field in ("streaming", "tools"):
        if normalized.get(field) is True and not getattr(capabilities, field):
            missing.append({"capability": field, "required": True, "available": False})
    if "resource_metrics" in normalized:
        absent = sorted(set(normalized["resource_metrics"]) - set(capabilities.resource_metrics))
        if absent:
            missing.append({"capability": "resource_metrics", "required": absent, "available": list(capabilities.resource_metrics)})
    if normalized.get("backend_id") and normalized["backend_id"] != capabilities.backend_id:
        missing.append({"capability": "backend_id", "required": normalized["backend_id"], "available": capabilities.backend_id})
    return {
        "schema_version": _RA_NEGOTIATION_SCHEMA,
        "status": "complete" if not missing else "rejected",
        "requirements": normalized,
        "capabilities": capabilities.to_dict(),
        "capabilities_digest": _ra_sha(capabilities.to_dict()),
        "missing": missing,
        "external_fallback_allowed": False,
    }


class ReferenceRuntimeAdapter:
    """Deterministic offline adapter used for contract and failure-path tests."""

    def __init__(
        self,
        *,
        capabilities: Mapping[str, Any] | RuntimeCapabilities | None = None,
        behavior: str = "success",
        output: str = "",
    ) -> None:
        self.capabilities = RuntimeCapabilities.from_mapping(capabilities or {
            "schema_version": _RA_CAPABILITIES_SCHEMA,
            "backend_id": "reference-local",
            "backend_version": "0.1",
            "model_id": "reference-model",
            "model_version": "0.1",
            "tokenizer_id": "reference-tokenizer",
            "context_capacity_tokens": 4096,
            "execution_modes": ["offline", "local"],
            "streaming": True,
            "tools": False,
            "hardware_class": "unknown",
            "resource_metrics": ["latency_ms"],
            "auth_mode": "none",
            "provider_ref": "local-reference",
        })
        if behavior not in _RA_RESULT_STATUSES:
            raise RuntimeAdapterError("unsupported reference adapter behavior")
        self.behavior = behavior
        self.output = _ra_text(output, "output", max_length=1_000_000, allow_empty=True)

    def invoke(self, request: Mapping[str, Any] | AdapterRequest) -> AdapterResult:
        try:
            request_obj = AdapterRequest.from_mapping(request)
        except (RuntimeAdapterError, ExecutionProfileError) as exc:
            raise RuntimeAdapterError(str(exc)) from exc
        requirements = dict(request_obj.required_capabilities)
        requirements["execution_mode"] = request_obj.execution_mode
        negotiation = negotiate_runtime_capabilities(requirements, self.capabilities)
        runtime = {
            "backend_id": self.capabilities.backend_id,
            "backend_version": self.capabilities.backend_version,
            "model_id": self.capabilities.model_id,
            "model_version": self.capabilities.model_version,
            "auth_mode": self.capabilities.auth_mode,
            "provider_ref": self.capabilities.provider_ref,
            "execution_mode": request_obj.execution_mode,
        }
        if negotiation["status"] == "rejected":
            return AdapterResult(
                schema_version=_RA_RESULT_SCHEMA,
                request_id=request_obj.request_id,
                status="unavailable",
                output=None,
                usage={},
                runtime=runtime,
                error_code="capability_mismatch",
                error_message="required runtime capabilities are unavailable",
            )
        if self.behavior in {"unavailable", "timeout", "cancelled", "malformed"}:
            return AdapterResult(
                schema_version=_RA_RESULT_SCHEMA,
                request_id=request_obj.request_id,
                status=self.behavior,
                output=None,
                usage={},
                runtime=runtime,
                error_code=self.behavior,
                error_message=f"reference adapter {self.behavior}",
            )
        bounded = self.output[: request_obj.max_output_chars]
        usage = {"output_tokens": max(1, (len(bounded) + 3) // 4)}
        return AdapterResult(
            schema_version=_RA_RESULT_SCHEMA,
            request_id=request_obj.request_id,
            status=self.behavior,
            output=bounded,
            usage=usage,
            runtime=runtime,
            error_code=None,
            error_message=None,
        )
