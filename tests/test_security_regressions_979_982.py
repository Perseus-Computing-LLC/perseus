"""Independent regression probes for the #979-#982 security review."""
from __future__ import annotations

import hashlib
import json

import pytest

from conftest import perseus


def _entry(identifier: str = "item-1", **extra):
    value = {
        "candidate_id": identifier,
        "agent_text": "bounded evidence summary",
        "source_id": "vault:entity-1",
        "provenance_id": "ledger:receipt-1",
        "evidence_digest": "a" * 64,
        "valid_at": "2026-08-17T12:00:00Z",
        "transaction_time": "2026-08-17T12:01:00Z",
        "validity_state": "observed",
        "verified": True,
        "selection_reason": "source matched the task",
    }
    value.update(extra)
    return value


def _request(profile, **extra):
    value = {
        "schema_version": "perseus-runtime-request/v1",
        "request_id": "request-1",
        "execution_profile": profile,
        "execution_profile_digest": profile["profile_digest"],
        "context_digest": "a" * 64,
        "evidence_digest": "b" * 64,
        "input_digest": "c" * 64,
        "execution_mode": "offline",
        "required_capabilities": {},
        "max_output_chars": 128,
    }
    value.update(extra)
    return value


def _profile(**extra):
    value = {
        "schema_version": "perseus-execution-profile/v1",
        "profile_id": "security-regression",
        "mode": "constrained-edge",
        "max_context_tokens": 1024,
        "max_context_bytes": 4096,
        "max_items": 4,
        "max_depth": 2,
        "latency_target_ms": 500,
        "resource_class": "edge",
        "network_mode": "offline",
        "runtime_capabilities": [],
        "degradation_policy": "fail_closed",
        "auth_mode": "none",
    }
    value.update(extra)
    return value


def test_public_evidence_fields_cannot_leak_uri_credentials_or_private_reasons():
    projection = perseus.project_context_evidence([
        _entry(
            source_id="https://user:supersecret@example.com/private",
            selection_reason="private memory: child birth date 2010-01-01",
        )
    ])
    serialized = json.dumps(projection, sort_keys=True)
    assert "supersecret" not in serialized
    assert "child birth date" not in serialized
    assert any(ref.startswith("sha256:") for ref in projection["selected"][0]["source_refs"])
    assert projection["selected"][0]["inclusion_reason"] == "selection_reason_suppressed"


def test_raw_body_digest_is_recomputed_and_forged_claims_are_rejected():
    body = "actual-private-body"
    with pytest.raises(perseus.ContextEvidenceError, match="digest"):
        perseus.project_context_evidence([_entry(content=body, evidence_digest="a" * 64)])
    honest = perseus.project_context_evidence([
        _entry(content=body, evidence_digest=hashlib.sha256(body.encode()).hexdigest())
    ])
    assert honest["selected"][0]["evidence_digest"] == hashlib.sha256(body.encode()).hexdigest()
    assert body not in json.dumps(honest, sort_keys=True)
    with pytest.raises(perseus.ContextEvidenceError, match="must be text"):
        perseus.project_context_evidence([_entry(body={"private": "secret"}, evidence_digest="a" * 64)])


@pytest.mark.parametrize("coverage_state", ["empty", "unavailable", "timeout"])
def test_non_backed_item_states_require_abstention(coverage_state):
    projection = perseus.project_context_evidence(
        [_entry(coverage_state=coverage_state)], evidence_required=True
    )
    assert projection["coverage"]["state"] == coverage_state
    assert projection["coverage"]["abstention_required"] is True


def test_context_rank_propagates_required_evidence_abstention():
    result = perseus.context_rank(
        [_entry(coverage_state="partial")],
        task="bounded evidence",
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["status"] == "abstain"
    assert result["failure_state"] == "insufficient_evidence"
    assert result["evidence_projection"]["status"] == "abstention_required"


def test_not_configured_vault_is_not_a_complete_context_result():
    result = perseus.context_rank(
        [_entry()],
        task="bounded evidence",
        integrations={"vault": "not_configured", "ledger": "active"},
    )
    assert result["status"] == "degraded"
    assert result["failure_state"] == "vault_unavailable"
    assert result["evidence_projection"]["status"] == "unavailable"


def test_evidence_projection_collections_are_hard_bounded():
    with pytest.raises(perseus.ContextEvidenceError, match="at most 64"):
        perseus.project_context_evidence([_entry(f"item-{index}") for index in range(65)])


def test_projection_schema_is_checked_before_digest_and_render():
    projection = perseus.project_context_evidence([_entry()])
    forged = json.loads(json.dumps(projection))
    forged["coverage"] = {}
    unsigned = dict(forged)
    unsigned.pop("projection_digest")
    forged["projection_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert perseus.verify_context_evidence(forged)["valid"] is False
    with pytest.raises(perseus.ContextEvidenceError):
        perseus.render_context_evidence(forged)


def test_profile_network_requirements_lower_policy_but_cannot_escalate():
    resolved = perseus.resolve_execution_profile(
        _profile(network_mode="local"), requirements={"network_mode": "offline"}
    )
    assert resolved["effective"]["network_mode"] == "offline"
    with pytest.raises(perseus.ExecutionProfileError, match="network"):
        perseus.resolve_execution_profile(
            _profile(network_mode="offline"),
            requirements={"network_mode": "approved_network"},
        )


def test_adapter_request_cannot_escalate_profile_network_policy():
    profile = perseus.resolve_execution_profile(_profile())
    with pytest.raises(perseus.RuntimeAdapterError, match="network policy"):
        perseus.AdapterRequest.from_mapping(
            _request(profile, execution_mode="approved_network")
        )


def test_manual_request_instances_are_revalidated_at_adapter_boundary():
    profile = perseus.resolve_execution_profile(_profile())
    forged = perseus.AdapterRequest(
        schema_version="perseus-runtime-request/v1",
        request_id="request-1",
        execution_profile=profile,
        execution_profile_digest=profile["profile_digest"],
        context_digest="a" * 64,
        evidence_digest="b" * 64,
        input_digest="c" * 64,
        execution_mode="approved_network",
        required_capabilities={},
        max_output_chars=128,
    )
    with pytest.raises(perseus.RuntimeAdapterError, match="network policy"):
        perseus.AdapterRequest.from_mapping(forged)


def test_fractional_and_unresolvable_latency_limits_fail_with_typed_errors():
    with pytest.raises(perseus.ExecutionProfileError, match="positive integer"):
        perseus.ExecutionProfile.from_mapping(_profile(max_items=1.9))
    with pytest.raises(perseus.ExecutionProfileError, match="latency target"):
        perseus.resolve_execution_profile(
            None, requirements={"latency_target_ms": 100}
        )


def test_dag_enforces_profile_byte_limit_separately_from_token_estimate():
    root = perseus.ContextNode(
        kind="requirement",
        content="abcd",
        evidence={"validity": "observed", "verified": True, "source_ids": ["task"]},
    )
    with pytest.raises(perseus.BudgetExceeded, match="max_bytes"):
        perseus.compile_context_dag(
            task_id="byte-limit",
            root=root,
            execution_profile=_profile(max_context_tokens=100, max_context_bytes=1),
        )


def test_runtime_result_requires_the_complete_schema_envelope():
    with pytest.raises(perseus.RuntimeAdapterError, match="missing required fields"):
        perseus.AdapterResult.from_mapping({
            "schema_version": "perseus-runtime-result/v1",
            "request_id": "request-1",
            "status": "success",
            "output": "bounded",
        })
