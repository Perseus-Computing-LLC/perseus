"""Independent regression probes for the #979-#982 security review."""
from __future__ import annotations

import copy
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
        "content": "bounded evidence body",
        "evidence_digest": hashlib.sha256("bounded evidence body".encode("utf-8")).hexdigest(),
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


def test_public_evidence_fields_reject_uri_credentials_and_private_reasons():
    with pytest.raises(perseus.ContextEvidenceError, match="source"):
        perseus.project_context_evidence([
            _entry(
                source_id="https://user:supersecret@example.com/private",
                selection_reason="private memory: child birth date 2010-01-01",
            )
        ])


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
        [_entry(coverage_state=coverage_state)],
        provider_states={"vault": "active", "ledger": "active"},
        evidence_required=True,
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


def _canonical_sha(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def test_forged_profile_manifest_is_rejected_at_adapter_boundary():
    profile = perseus.resolve_execution_profile(_profile())
    forged = copy.deepcopy(profile)
    forged["effective"]["network_mode"] = "approved_network"
    unsigned = dict(forged)
    unsigned.pop("profile_digest")
    forged["profile_digest"] = _canonical_sha(unsigned)
    with pytest.raises(perseus.RuntimeAdapterError):
        perseus.AdapterRequest.from_mapping(
            _request(forged, execution_mode="approved_network")
        )


def test_arbitrary_source_sentinels_are_rejected():
    with pytest.raises(perseus.ContextEvidenceError, match="source"):
        perseus.project_context_evidence([_entry(source_id="safe-private-sentinel-9f2c")])


def test_nested_evidence_collections_are_bounded_at_production():
    with pytest.raises(perseus.ContextEvidenceError, match="source"):
        perseus.project_context_evidence([
            _entry(source_refs=[f"vault:ref-{index}" for index in range(65)])
        ])
    with pytest.raises(perseus.ContextEvidenceError, match="provider"):
        perseus.project_context_evidence(
            [_entry()],
            provider_states={f"provider-{index}": "active" for index in range(129)},
        )


def test_digest_fields_reject_non_string_values():
    with pytest.raises(perseus.ContextEvidenceError, match="digest"):
        perseus.project_context_evidence([_entry(evidence_digest=int("9" * 64))])
    profile = _profile()
    with pytest.raises(perseus.RuntimeAdapterError, match="context_digest"):
        perseus.AdapterRequest.from_mapping(
            _request(perseus.resolve_execution_profile(profile), context_digest=int("9" * 64))
        )


def test_dag_verifier_recomputes_budget_accounting_before_accepting_digest():
    root = perseus.ContextNode(
        kind="requirement",
        content="abcd",
        evidence={"validity": "observed", "verified": True, "source_ids": ["task"]},
    )
    artifact = perseus.compile_context_dag(task_id="budget-forge", root=root)
    artifact["budget"]["bytes"] = 0
    artifact["budget"]["limits"]["max_bytes"] = 1
    sealed = dict(artifact["budget"])
    sealed.pop("wall_clock_s", None)
    artifact["compiled_digest"] = perseus._dag_sha(
        "packet", perseus._dag_json(artifact["packet"]),
        "verdict", perseus._dag_json(artifact["verdict"]),
        "advisory", perseus._dag_json(artifact["advisory"]),
        "policy", perseus._dag_json(artifact["policy"]),
        "budget", perseus._dag_json(sealed),
        "graph", artifact["graph"]["digest"],
        "execution_profile", perseus._dag_json({}),
    )
    assert perseus.verify_compiled_dag(artifact)["valid"] is False


def test_verifier_rejects_non_iso_timestamps():
    projection = perseus.project_context_evidence([_entry()])
    projection["selected"][0]["valid_at"] = "PRIVATE_RAW"
    unsigned = dict(projection)
    unsigned.pop("projection_digest")
    projection["projection_digest"] = _canonical_sha(unsigned)
    assert perseus.verify_context_evidence(projection)["valid"] is False


def test_selected_ids_must_be_a_sequence():
    with pytest.raises(perseus.ContextEvidenceError, match="selected_ids"):
        perseus.project_context_evidence([_entry()], selected_ids="item-1")


def test_malformed_empty_optional_latency_limit_is_rejected():
    with pytest.raises(perseus.ExecutionProfileError, match="latency_target_ms"):
        perseus.ExecutionProfile.from_mapping(_profile(latency_target_ms=""))


def test_profile_and_capability_identifiers_reject_uri_userinfo_forms():
    with pytest.raises(perseus.ExecutionProfileError):
        perseus.ExecutionProfile.from_mapping(_profile(profile_id="https://user:hunter2@example.com/profile"))
    with pytest.raises(perseus.ExecutionProfileError):
        perseus.ExecutionProfile.from_mapping(_profile(runtime_capabilities=["https://user:hunter2@example.com/capability"]))


def test_air_gapped_profile_cannot_be_rewritten_to_a_networked_policy():
    with pytest.raises(perseus.ExecutionProfileError, match="offline"):
        perseus.ExecutionProfile.from_mapping(_profile(mode="air-gapped", network_mode="approved_network"))


def test_projection_verifier_requires_source_references():
    projection = perseus.project_context_evidence([_entry()])
    projection["selected"][0]["source_refs"] = []
    unsigned = dict(projection)
    unsigned.pop("projection_digest")
    projection["projection_digest"] = _canonical_sha(unsigned)
    assert perseus.verify_context_evidence(projection)["valid"] is False


def test_malformed_unicode_bodies_fail_closed_in_evidence_commitments():
    for body in ("\ud800", "\ud801"):
        replacement_digest = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()
        with pytest.raises(perseus.ContextEvidenceError):
            perseus.project_context_evidence([_entry(content=body, evidence_digest=replacement_digest)])


def test_context_ask_abstains_when_evidence_is_required_but_not_observed():
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "partial-record",
            "summary": "The signed release path is used.",
            "validity": "partial",
            "source_id": "vault:partial-record",
        }],
        policy={"evidence_required": True},
    )
    assert result["status"] == "abstain"
    assert result["answer"] is None


def test_context_rank_propagates_required_evidence_abstention_to_top_level():
    for integration_state in ("not_configured", "timeout"):
        result = perseus.context_rank(
            [_entry(validity_state="partial")],
            task="bounded evidence summary",
            policy={"evidence_required": True},
            integrations={"vault": integration_state, "ledger": "active"},
        )
        assert result["status"] == "abstain"
        assert result["evidence_projection"]["coverage"]["abstention_required"] is True


def test_incomplete_integration_maps_do_not_default_missing_providers_to_active():
    result = perseus.context_rank(
        [_entry()],
        task="bounded evidence summary",
        integrations={"vault": "active"},
    )
    assert result["status"] != "complete"
    assert result["failure_state"] == "ledger_unavailable"


def test_explicit_none_hard_profile_requirements_are_rejected():
    with pytest.raises(perseus.ExecutionProfileError, match="max_context_tokens"):
        perseus.resolve_execution_profile(
            _profile(), requirements={"max_context_tokens": None}
        )


def test_evidence_writer_rejects_oversized_source_reference_collections():
    with pytest.raises(perseus.ContextEvidenceError):
        perseus.project_context_evidence([_entry(source_refs=[f"vault:item-{i}" for i in range(65)])])


def test_context_ask_rejects_conflicting_raw_body_aliases():
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "conflicting-body",
            "summary": "The signed release path is used.",
            "source_id": "vault:conflicting-body",
            "validity": "observed",
            "content": "private-A",
            "body": "private-B",
        }],
    )
    assert result["status"] == "invalid_input"


def test_context_operations_reject_non_text_raw_body_aliases():
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "binary-body",
            "summary": "The signed release path is used.",
            "source_id": "vault:binary-body",
            "content": b"private-body",
        }],
    )
    assert result["status"] == "invalid_input"


def test_evidence_required_context_ask_requires_computed_body_commitment_and_trusted_source():
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "forged-record",
            "summary": "The signed release path is used.",
            "source_id": "attacker:forged-record",
            "validity": "observed",
            "evidence_digest": "a" * 64,
        }],
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["status"] == "abstain"
    assert result["answer"] is None


def test_digest_only_records_cannot_become_evidence_backed():
    projection = perseus.project_context_evidence(
        [_entry(source_id="vault:digest-only", content="")], evidence_required=True
    )
    assert projection["coverage"]["state"] != "evidence_backed"
    assert projection["coverage"]["abstention_required"] is True


def test_untrusted_source_namespaces_cannot_become_evidence_backed():
    body = "authoritative body"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with pytest.raises(perseus.ContextEvidenceError, match="source"):
        perseus.project_context_evidence([_entry(
            source_id="attacker:forged",
            content=body,
            evidence_digest=digest,
        )], evidence_required=True)


def test_context_ask_rejects_unbounded_source_reference_fanout():
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "many-refs",
            "summary": "The signed release path is used.",
            "source_refs": [f"vault:ref-{index}" for index in range(65)],
            "validity": "observed",
            "content": "bounded evidence body",
        }],
    )
    assert result["status"] == "invalid_input"


@pytest.mark.parametrize("bad_budget", [True, 0, {"max_items": 0}, {"max_chars": 0}, {"max_items": 1.5}, {"max_items": None}])
def test_context_limits_reject_boolean_fractional_none_and_nonpositive_values(bad_budget):
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[_entry()],
        budget=bad_budget,
    )
    assert result["status"] == "invalid_input"


def test_context_question_task_and_policy_controls_are_strictly_typed_and_bounded():
    question_result = perseus.context_ask("q" * 513, context=[_entry()])
    task_result = perseus.context_rank([_entry()], task="t" * 513)
    nan_result = perseus.context_rank([_entry()], task="signed release", policy={"min_score": float("nan")})
    bool_result = perseus.context_ask("signed release", context=[_entry()], policy={"allow_content": "false"})
    assert question_result["status"] == "invalid_input"
    assert task_result["status"] == "invalid_input"
    assert nan_result["status"] == "invalid_input"
    assert bool_result["status"] == "invalid_input"


@pytest.mark.parametrize("kwargs", [
    {"max_nodes": True}, {"max_nodes": 1.5}, {"max_nodes": 0},
    {"max_bytes": False}, {"max_bytes": 0}, {"deadline_s": float("nan")},
])
def test_compilation_budget_rejects_manual_type_confusion_and_nonpositive_limits(kwargs):
    with pytest.raises(perseus.ContextDagError):
        perseus.CompilationBudget(**kwargs)



def _resign_projection(projection):
    unsigned = dict(projection)
    unsigned.pop("projection_digest", None)
    projection["projection_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return projection


def test_projection_verifier_rejects_self_consistent_missing_or_unknown_provider_attestation():
    projection = perseus.project_context_evidence(
        [_entry()],
        provider_states={"vault": "active", "ledger": "active"},
        evidence_required=True,
    )
    missing = json.loads(json.dumps(projection))
    missing["coverage"]["provider_states"] = {}
    assert perseus.verify_context_evidence(_resign_projection(missing))["valid"] is False
    unknown = json.loads(json.dumps(projection))
    unknown["coverage"]["provider_states"] = {"sha256:" + "a" * 64: "active"}
    assert perseus.verify_context_evidence(_resign_projection(unknown))["valid"] is False
