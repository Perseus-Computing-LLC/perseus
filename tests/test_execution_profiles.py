"""Tests for the #980 resource-aware execution profile contract."""
from __future__ import annotations

import hashlib
import json

import pytest

from conftest import perseus


def _profile(mode="constrained-edge"):
    return {
        "schema_version": "perseus-execution-profile/v1",
        "profile_id": "test-profile",
        "mode": mode,
        "max_context_tokens": 2048,
        "max_context_bytes": 8192,
        "max_items": 8,
        "max_depth": 2,
        "latency_target_ms": 250,
        "resource_class": "edge",
        "network_mode": "offline" if mode == "air-gapped" else "local",
        "runtime_capabilities": ["streaming"],
        "degradation_policy": "partial",
        "auth_mode": "none",
    }


def test_profile_normalization_is_versioned_bounded_and_secret_free():
    profile = perseus.ExecutionProfile.from_mapping(_profile())
    data = profile.to_dict()
    assert data["schema_version"] == "perseus-execution-profile/v1"
    assert data["max_context_tokens"] == 2048
    assert data["runtime_capabilities"] == ["streaming"]
    assert "api_key" not in json.dumps(data).lower()
    with pytest.raises(perseus.ExecutionProfileError):
        perseus.ExecutionProfile.from_mapping(dict(_profile(), api_key="must-reject"))


def test_resolution_intersects_hard_context_item_and_depth_limits():
    resolved = perseus.resolve_execution_profile(
        _profile(),
        requirements={
            "max_context_tokens": 1000,
            "max_context_bytes": 3000,
            "max_items": 3,
            "max_depth": 1,
            "required_capabilities": ["streaming"],
        },
        resources={"memory_class": "small", "compute_class": "low"},
    )
    assert resolved["status"] == "complete"
    assert resolved["effective"]["max_context_tokens"] == 1000
    assert resolved["effective"]["max_context_bytes"] == 3000
    assert resolved["effective"]["max_items"] == 3
    assert resolved["effective"]["max_depth"] == 1
    assert resolved["resource_state"] == "known"
    assert len(resolved["profile_digest"]) == 64


def test_unavailable_resources_are_explicit_not_fabricated():
    resolved = perseus.resolve_execution_profile(_profile(), resources=None)
    assert resolved["resource_state"] == "unknown"
    assert resolved["resources"] == {}
    assert "available_memory_mb" not in resolved["resources"]


def test_degraded_retrieval_is_reported_without_overflowing_the_profile():
    resolved = perseus.negotiate_context_budget(
        _profile(), retrieval_status="partial", requested_tokens=1800
    )
    assert resolved["status"] == "degraded"
    assert resolved["diagnostics"]["degraded"] is True
    assert "retrieval_partial" in resolved["diagnostics"]["reasons"]
    assert resolved["effective"]["max_context_tokens"] == 1800


def test_air_gapped_profile_rejects_network_requirement():
    with pytest.raises(perseus.ExecutionProfileError, match="offline"):
        perseus.resolve_execution_profile(
            _profile("air-gapped"),
            requirements={"network_mode": "approved_network"},
        )


def test_unsupported_capability_fails_closed_and_digest_replays():
    with pytest.raises(perseus.ExecutionProfileError, match="capabil"):
        perseus.resolve_execution_profile(
            _profile(), requirements={"required_capabilities": ["tools"]}
        )
    resolved_a = perseus.resolve_execution_profile(_profile())
    resolved_b = perseus.resolve_execution_profile(_profile())
    assert resolved_a == resolved_b
    verification = perseus.verify_execution_profile(resolved_a)
    assert verification["valid"] is True
    tampered = json.loads(json.dumps(resolved_a))
    tampered["effective"]["max_items"] = 1
    assert perseus.verify_execution_profile(tampered)["valid"] is False


def test_profile_projects_to_dag_budget_and_manifest():
    resolved = perseus.resolve_execution_profile(_profile())
    budget = perseus.execution_profile_compilation_budget(resolved)
    assert budget["max_tokens"] == 2048
    assert budget["max_nodes"] == 8
    assert budget["max_depth"] == 2
