"""Tests for the #981 portable local/edge runtime adapter seam."""
from __future__ import annotations

import json

import pytest

from conftest import perseus


def _profile():
    return perseus.resolve_execution_profile(
        {
            "schema_version": "perseus-execution-profile/v1",
            "profile_id": "adapter-profile",
            "mode": "constrained-edge",
            "max_context_tokens": 1024,
            "max_context_bytes": 4096,
            "max_items": 4,
            "max_depth": 2,
            "latency_target_ms": 500,
            "resource_class": "edge",
            "network_mode": "offline",
            "runtime_capabilities": ["streaming"],
            "degradation_policy": "partial",
            "auth_mode": "none",
        }
    )


def _capabilities():
    return perseus.RuntimeCapabilities.from_mapping({
        "schema_version": "perseus-runtime-capabilities/v1",
        "backend_id": "reference-local",
        "backend_version": "0.1",
        "model_id": "fake-model",
        "model_version": "1",
        "tokenizer_id": "fake-tokenizer",
        "context_capacity_tokens": 2048,
        "execution_modes": ["offline", "local"],
        "streaming": True,
        "tools": False,
        "hardware_class": "cpu",
        "resource_metrics": ["latency_ms"],
        "auth_mode": "none",
        "provider_ref": "local-reference",
    })


def _request(**extra):
    data = {
        "schema_version": "perseus-runtime-request/v1",
        "request_id": "request-1",
        "execution_profile": _profile(),
        "context_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "input_digest": "c" * 64,
        "execution_mode": "offline",
        "required_capabilities": {"streaming": True},
        "max_output_chars": 128,
    }
    data.update(extra)
    return perseus.AdapterRequest.from_mapping(data)


def test_capabilities_and_request_are_versioned_and_digest_only():
    caps = _capabilities()
    request = _request()
    assert caps.to_dict()["schema_version"] == "perseus-runtime-capabilities/v1"
    assert request.to_dict()["execution_profile_digest"] == _profile()["profile_digest"]
    serialized = json.dumps({"capabilities": caps.to_dict(), "request": request.to_dict()}, sort_keys=True).lower()
    for forbidden in ("api_key", "authorization", "password", "prompt", "content", "private_body"):
        assert forbidden not in serialized
    with pytest.raises(perseus.RuntimeAdapterError):
        perseus.AdapterRequest.from_mapping(dict(request.to_dict(), prompt="do not persist"))


def test_adapter_request_round_trips_its_profile_digest():
    request = _request()
    restored = perseus.AdapterRequest.from_mapping(request.to_dict())
    assert restored.to_dict() == request.to_dict()


def test_capability_negotiation_succeeds_without_network_or_fallback():
    negotiated = perseus.negotiate_runtime_capabilities(
        {"execution_mode": "offline", "min_context_tokens": 1000, "streaming": True},
        _capabilities(),
    )
    assert negotiated["status"] == "complete"
    assert negotiated["external_fallback_allowed"] is False
    assert negotiated["missing"] == []
    assert len(negotiated["capabilities_digest"]) == 64


def test_capability_negotiation_rejects_unsupported_requirements():
    rejected = perseus.negotiate_runtime_capabilities(
        {"execution_mode": "approved_network", "min_context_tokens": 9000, "tools": True},
        _capabilities(),
    )
    assert rejected["status"] == "rejected"
    assert rejected["external_fallback_allowed"] is False
    assert {item["capability"] for item in rejected["missing"]} == {
        "execution_mode", "context_capacity_tokens", "tools"
    }


@pytest.mark.parametrize("status", ["success", "partial", "unavailable", "timeout", "cancelled", "malformed"])
def test_reference_adapter_exercises_every_explicit_status_without_network(status):
    adapter = perseus.ReferenceRuntimeAdapter(
        capabilities=_capabilities(), behavior=status, output="bounded output"
    )
    result = adapter.invoke(_request())
    assert result.status == status
    assert result.request_id == "request-1"
    assert result.external_fallback_allowed is False
    if status in {"success", "partial"}:
        assert result.output == "bounded output"
    else:
        assert result.output is None


def test_malformed_result_and_usage_are_rejected_at_the_boundary():
    with pytest.raises(perseus.RuntimeAdapterError):
        perseus.AdapterResult.from_mapping({
            "schema_version": "perseus-runtime-result/v1",
            "request_id": "request-1",
            "status": "success",
            "output": "x",
            "usage": {"api_key": "forbidden"},
            "runtime": {},
        })


def test_adapter_fails_closed_on_profile_or_capability_mismatch():
    request = _request(required_capabilities={"tools": True})
    result = perseus.ReferenceRuntimeAdapter(capabilities=_capabilities()).invoke(request)
    assert result.status == "unavailable"
    assert result.error_code == "capability_mismatch"
    assert result.external_fallback_allowed is False
