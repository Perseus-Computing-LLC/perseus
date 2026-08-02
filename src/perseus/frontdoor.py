"""Single front-door routing contract with explicit degraded modes (#896)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

_REQUEST_CLASSES = frozenset({"direct", "retrieve", "decide", "create", "verify", "act"})
_INTEGRATIONS = ("vault", "ledger")
_STATES = frozenset({"active", "unavailable", "not_configured"})
_CAPABILITY_ORDER = (
    "perseus_vault_recall",
    "ledger_verify",
    "evidence_claim_gate",
    "aar_authorize",
)
_REQUIRED = {
    "retrieve": ("perseus_vault_recall",),
    "decide": ("perseus_vault_recall",),
    "create": ("perseus_vault_recall",),
    "verify": ("ledger_verify", "evidence_claim_gate"),
    "act": ("perseus_vault_recall", "aar_authorize", "ledger_verify"),
}


def _safe_integrations(integrations: Mapping[str, Any] | None) -> dict[str, str]:
    values = dict(integrations or {})
    result: dict[str, str] = {}
    for name in _INTEGRATIONS:
        value = values.get(name, "not_configured")
        if value not in _STATES:
            raise ValueError(f"invalid integration state for {name}: {value!r}")
        result[name] = value
    return result


def route_front_door(
    request_class: str,
    *,
    available_capabilities: set[str] | frozenset[str] | None = None,
    integrations: Mapping[str, Any] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select backstage capabilities without exposing request content."""
    del request_metadata  # request content never enters the route trace
    if request_class not in _REQUEST_CLASSES:
        raise ValueError(f"unknown request class: {request_class!r}")
    states = _safe_integrations(integrations)
    available = set(available_capabilities or ())
    capabilities: list[str] = []
    if request_class != "direct":
        for capability in _REQUIRED[request_class]:
            if capability not in available:
                continue
            if capability == "perseus_vault_recall" and states["vault"] != "active":
                continue
            if capability in {"ledger_verify", "evidence_claim_gate"} and states["ledger"] != "active":
                continue
            if capability == "aar_authorize" and (states["vault"] != "active" or states["ledger"] != "active"):
                continue
            capabilities.append(capability)
    capabilities.sort(key=_CAPABILITY_ORDER.index)
    required = _REQUIRED.get(request_class, ())
    degraded = None
    guarantees: list[str] = []
    if request_class != "direct" and any(required_cap not in capabilities for required_cap in required):
        degraded = "required_integrations_unavailable"
    elif "ledger_verify" in capabilities:
        guarantees.append("ledger_evidence_verification")
    if "perseus_vault_recall" in capabilities:
        guarantees.append("persistent_memory_retrieval")
    if "aar_authorize" in capabilities:
        guarantees.append("authorized_action_preflight")

    payload = {
        "schema_version": "perseus-front-door-route/v1",
        "request_class": request_class,
        "capabilities": capabilities,
        "delegation_reason": "direct handling" if request_class == "direct" else "minimum available capabilities for request class",
        "integration_state": states,
        "degraded_mode": degraded,
        "guarantees": sorted(guarantees),
    }
    payload["trace_payload"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["trace_sha256"] = hashlib.sha256(payload["trace_payload"].encode()).hexdigest()
    return payload


def front_door_response(route: Mapping[str, Any], result: Any) -> dict[str, Any]:
    """Return one result while retaining the machine-readable route envelope."""
    return {
        "route": dict(route),
        "response_mode": "single_accountable_result",
        "result": result,
    }


def route_request(
    request_class: str,
    *,
    available_capabilities: set[str] | frozenset[str] | None = None,
    integrations: Mapping[str, Any] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    result: Any = None,
) -> dict[str, Any]:
    """Route and wrap a request through the single accountable front door."""
    route = route_front_door(
        request_class,
        available_capabilities=available_capabilities,
        integrations=integrations,
        request_metadata=request_metadata,
    )
    return front_door_response(route, result)


__all__ = ["front_door_response", "route_front_door", "route_request"]


# Keep the source module importable from the generated single-file artifact.
# The build concatenator strips this module's internal imports but preserves the
# top-level definitions in order.

def _frontdoor_module_exports() -> tuple[str, ...]:
    return tuple(__all__)
