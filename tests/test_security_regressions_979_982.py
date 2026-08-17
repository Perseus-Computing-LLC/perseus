"""Independent regression probes for the #979-#982 security review."""
from __future__ import annotations

import copy
import hashlib
import json
import time

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
    assert result["status"] == "invalid_input"
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



def test_context_ask_rejects_raw_content_projection_even_when_requested():
    result = perseus.context_ask(
        "What is the SSN?",
        context=[{
            "candidate_id": "content-leak",
            "source_id": "vault:content-leak",
            "validity": "observed",
            "content": "private scalar SSN 999-88-7777",
            "evidence_digest": "a" * 64,
        }],
        policy={"allow_content": True},
    )
    assert result["status"] == "invalid_input"
    assert "999-88-7777" not in json.dumps(result, sort_keys=True)


@pytest.mark.parametrize("coverage_state", ["empty", "partial", "stale", "conflicted", "unavailable", "timeout"])
def test_context_ask_propagates_explicit_coverage_state_when_evidence_is_required(coverage_state):
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "coverage-" + coverage_state,
            "summary": "The signed release path is used.",
            "source_id": "vault:coverage-" + coverage_state,
            "validity": "observed",
            "coverage_state": coverage_state,
            "content": "The signed release path is used.",
            "evidence_digest": hashlib.sha256("The signed release path is used.".encode("utf-8")).hexdigest(),
        }],
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["answer"] is None
    assert result["status"] in {"abstain", "review", "unavailable"}



def test_required_context_rank_does_not_invent_provider_attestation():
    result = perseus.context_rank(
        [_entry(agent_text="signed release path", summary="The signed release path is used.")],
        task="signed release path",
        policy={"evidence_required": True},
    )
    assert result["status"] == "abstain"
    assert result["evidence_projection"]["coverage"]["provider_states"] == {
        "vault": "not_configured", "ledger": "not_configured"
    }


def test_context_ask_rejects_non_public_source_namespace():
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[_entry(source_id="attacker:forged", content="The signed release path is used.")],
    )
    assert result["status"] == "invalid_input"


@pytest.mark.parametrize("identifier", ["file:/tmp/private", "scheme:path"])
def test_profile_and_runtime_identifiers_reject_scheme_prefixes(identifier):
    with pytest.raises(perseus.ExecutionProfileError):
        perseus.ExecutionProfile.from_mapping(_profile(profile_id=identifier))
    with pytest.raises(perseus.RuntimeAdapterError):
        perseus.RuntimeCapabilities.from_mapping({
            "schema_version": "perseus-runtime-capabilities/v1",
            "backend_id": identifier,
            "backend_version": "1",
            "model_id": "model",
            "model_version": "1",
            "tokenizer_id": "tokenizer",
            "context_capacity_tokens": 4096,
            "execution_modes": ["offline"],
            "streaming": False,
            "tools": False,
            "hardware_class": "unknown",
            "resource_metrics": [],
            "auth_mode": "none",
            "provider_ref": "local",
        })


@pytest.mark.parametrize("max_candidates", [0, -1])
def test_context_rank_rejects_nonpositive_max_candidates(max_candidates):
    result = perseus.context_rank([_entry()], task="bounded evidence", policy={"max_candidates": max_candidates})
    assert result["status"] == "invalid_input"



def test_agent_projection_selection_reason_uses_only_allowlisted_rank_reasons():
    agent_id = "reason-sentinel-agent"
    scope = {"workspace": "reason-sentinel-workspace"}
    perseus.agent_projection_consent(
        agent_id=agent_id,
        scope=scope,
        permissions={"release": True},
        _authority_verified=True,
        _grantor_id="reason-sentinel-grantor",
    )
    body = "signed release"
    result = perseus.agent_projection_preview(
        [{
            "candidate_id": "reason-sentinel-item",
            "agent_text": body,
            "source_id": "vault:reason-sentinel",
            "content": body,
            "evidence_digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "validity": "observed",
            "selection_reason": "PRIVATE_SCALAR_SENTINEL_birth_date_2010",
            "scope": scope,
        }],
        agent_id=agent_id,
        scope=scope,
        task="signed release",
        integrations={"vault": "active", "ledger": "active"},
    )
    rendered = json.dumps(result, sort_keys=True)
    assert "PRIVATE_SCALAR_SENTINEL_birth_date_2010" not in rendered
    assert result["projection"]["items"][0]["selection_reason"] == "scope_match; policy_allowed; task_term_match; source_validity"


@pytest.mark.parametrize("status", ["empty", "partial", "stale", "conflicted", "unavailable", "timeout"])
def test_context_ask_propagates_status_alias_when_evidence_is_required(status):
    body = "The signed release path is used."
    result = perseus.context_ask(
        "Which signed release path is used?",
        context=[{
            "candidate_id": "status-alias-" + status,
            "summary": body,
            "source_id": "vault:status-alias-" + status,
            "validity": "observed",
            "status": status,
            "content": body,
            "evidence_digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }],
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["answer"] is None
    assert result["status"] in {"abstain", "review", "unavailable"}



def test_agent_projection_string_scope_is_commitment_sanitized():
    scope = "https://user:SUPERSECRET@example.com/private"
    agent_id = "scope-uri-sentinel-agent"
    result = perseus.agent_projection_consent(
        agent_id=agent_id,
        scope=scope,
        permissions={"release": True},
        _authority_verified=True,
        _grantor_id="scope-uri-sentinel-grantor",
    )
    serialized = json.dumps(result, sort_keys=True)
    assert "SUPERSECRET" not in serialized
    assert result["scope"]["workspace"].startswith("sha256:")


@pytest.mark.parametrize("text", [
    "https://:SUPERSECRET@example.com/private",
    '{"\\u0063ontent":"PRIVATE_SENTINEL"}',
])
def test_runtime_result_redacts_empty_userinfo_and_escaped_raw_fields(text):
    result = perseus.AdapterResult.from_mapping({
        "schema_version": "perseus-runtime-result/v1",
        "request_id": "runtime-redaction-sentinel",
        "status": "success",
        "output": text,
        "usage": {},
        "runtime": {},
        "error_code": None,
        "error_message": None,
        "external_fallback_allowed": False,
    })
    serialized = json.dumps(result.to_dict(), sort_keys=True)
    assert "SUPERSECRET" not in serialized
    assert "PRIVATE_SENTINEL" not in serialized


def test_direct_adapter_result_construction_cannot_bypass_envelope_validation():
    with pytest.raises(perseus.RuntimeAdapterError):
        perseus.AdapterResult(
            schema_version="bad",
            request_id="direct-result-sentinel",
            status="wat",
            output="ok",
            usage={"input_tokens": -1},
            runtime={"api_key": "SECRET"},
            error_code=None,
            error_message=None,
            external_fallback_allowed=True,
        )
    with pytest.raises(perseus.RuntimeAdapterError):
        perseus.AdapterResult(
            schema_version="perseus-runtime-result/v1",
            request_id="direct-result-sentinel",
            status="success",
            output="ok",
            usage={},
            runtime={"api_key": "SECRET"},
            error_code=None,
            error_message=None,
            external_fallback_allowed=False,
        )


def _resign_dag_for_test(artifact):
    graph = perseus.ContextDAG.from_dict(artifact["graph"])
    budget = dict(artifact["budget"])
    budget.pop("wall_clock_s", None)
    parts = [
        "packet", perseus._dag_json(artifact["packet"]),
        "verdict", perseus._dag_json(artifact["verdict"]),
        "advisory", perseus._dag_json(artifact["advisory"]),
        "policy", perseus._dag_json(artifact["policy"]),
        "budget", perseus._dag_json(budget),
        "graph", graph.digest(),
        "execution_profile", perseus._dag_json(artifact.get("execution_profile", {})),
    ]
    if artifact.get("execution_profile"):
        parts.extend([
            "profile_status", artifact.get("status"),
            "profile_diagnostics", perseus._dag_json(artifact.get("profile_diagnostics", {})),
        ])
    artifact["compiled_digest"] = perseus._dag_sha(*parts)
    return artifact


def _dag_probe_artifact():
    node = perseus.ContextNode(
        kind="requirement",
        content="who owns the arcade?",
        evidence={"validity": "observed", "verified": True, "source_ids": ["task"]},
    )
    def fetch(_node):
        return [perseus.ContextNode(
            kind="retrieved_record",
            content="alice owns the arcade",
            evidence={"validity": "observed", "verified": True, "source_ids": ["vault:1"]},
        )]
    return perseus.compile_context_dag(task_id="dag-selection-sentinel", root=node, fetch=fetch, verdict_hint="sufficient")


@pytest.mark.parametrize("mutation", ["duplicate", "empty"])
def test_compiled_dag_rejects_resigned_duplicate_or_empty_selection(mutation):
    artifact = _dag_probe_artifact()
    if mutation == "duplicate":
        artifact["selected_node_ids"].append(artifact["selected_node_ids"][0])
        artifact["packet"].append(copy.deepcopy(artifact["packet"][0]))
    else:
        artifact["selected_node_ids"] = []
        artifact["packet"] = []
    checked = perseus.verify_compiled_dag(_resign_dag_for_test(artifact))
    assert checked["valid"] is False



def test_agent_projection_propagates_evidence_required_abstention():
    scope = {"workspace": "agent-evidence-gate"}
    body = "signed release"
    record = {
        "candidate_id": "agent-evidence-item",
        "agent_text": body,
        "content": body,
        "source_id": "vault:agent-evidence",
        "scope": scope,
        "validity_state": "observed",
        "validity": "observed",
        "verified": True,
        "evidence_digest": hashlib.sha256(body.encode()).hexdigest(),
    }
    perseus.agent_projection_consent(
        agent_id="agent-evidence-gate-agent",
        scope=scope,
        permissions={"release": True},
        _authority_verified=True,
        _grantor_id="agent-evidence-gate-grantor",
    )
    result = perseus.agent_projection_preview(
        [record],
        agent_id="agent-evidence-gate-agent",
        scope=scope,
        task="signed release",
        policy={"evidence_required": True},
    )
    assert result["status"] != "complete"
    assert result["release_decision"] != "ready"


def test_context_ask_evidence_required_rejects_synthetic_source_reference():
    result = perseus.context_ask(
        "answer body",
        context=[{
            "candidate_id": "missing-source-item",
            "agent_text": "answer body",
            "content": "answer body",
            "validity_state": "observed",
            "validity": "observed",
            "verified": True,
        }],
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["status"] != "complete"
    assert result.get("answer") is None
    assert result.get("source_refs") == []


def test_allow_private_never_releases_private_scalars():
    scope = {"workspace": "private-boundary"}
    body = "PRIVATE_SCALAR_SENTINEL"
    record = {
        "candidate_id": "private-boundary-item",
        "agent_text": body,
        "content": body,
        "source_id": "vault:private-boundary",
        "scope": scope,
        "private": True,
        "validity_state": "observed",
        "validity": "observed",
        "verified": True,
        "evidence_digest": hashlib.sha256(body.encode()).hexdigest(),
    }
    perseus.agent_projection_consent(
        agent_id="private-boundary-agent",
        scope=scope,
        permissions={"release": True},
        _authority_verified=True,
        _grantor_id="private-boundary-grantor",
    )
    result = perseus.agent_projection_preview(
        [record],
        agent_id="private-boundary-agent",
        scope=scope,
        task="private release",
        policy={"allow_private": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert "PRIVATE_SCALAR_SENTINEL" not in json.dumps(result, sort_keys=True)


def test_adapter_result_mappings_are_immutable_after_validation():
    result = perseus.AdapterResult(
        schema_version="perseus-runtime-result/v1",
        request_id="immutable-result",
        status="success",
        output="ok",
        usage={},
        runtime={},
        error_code=None,
        error_message=None,
        external_fallback_allowed=False,
    )
    with pytest.raises(TypeError):
        result.usage["input_tokens"] = -1
    with pytest.raises(TypeError):
        result.runtime["api_key"] = "SECRET"


def _resign_dag_with_profile_presence(artifact, profile_present):
    graph = perseus.ContextDAG.from_dict(artifact["graph"])
    budget = dict(artifact["budget"])
    budget.pop("wall_clock_s", None)
    profile = artifact.get("execution_profile", {}) if profile_present else {}
    parts = [
        "packet", perseus._dag_json(artifact["packet"]),
        "verdict", perseus._dag_json(artifact["verdict"]),
        "advisory", perseus._dag_json(artifact["advisory"]),
        "policy", perseus._dag_json(artifact["policy"]),
        "budget", perseus._dag_json(budget),
        "graph", graph.digest(),
        "execution_profile_present", profile_present,
        "execution_profile", perseus._dag_json(profile),
    ]
    if profile_present:
        parts.extend([
            "profile_status", artifact.get("status"),
            "profile_diagnostics", perseus._dag_json(artifact.get("profile_diagnostics", {})),
        ])
    artifact["compiled_digest"] = perseus._dag_sha(*parts)
    return artifact


def test_profile_backed_dag_cannot_drop_profile_envelope_after_resigning():
    profile = {
        "schema_version": "perseus-execution-profile/v1",
        "profile_id": "profile-envelope-sentinel",
        "mode": "constrained-edge",
        "max_context_tokens": 2048,
        "max_context_bytes": 8192,
        "max_items": 4,
        "max_depth": 2,
        "latency_target_ms": 1000,
        "resource_class": "edge",
        "network_mode": "offline",
        "runtime_capabilities": [],
        "degradation_policy": "partial",
        "auth_mode": "none",
    }
    node = perseus.ContextNode(kind="requirement", content="compile", evidence={"validity": "observed", "verified": True, "source_ids": ["file:root"]})
    artifact = perseus.compile_context_dag(task_id="profile-envelope-sentinel", root=node, execution_profile=profile)
    tampered = copy.deepcopy(artifact)
    for key in ("execution_profile", "execution_profile_digest", "profile_diagnostics", "status"):
        tampered.pop(key, None)
    tampered["execution_profile_present"] = False
    assert perseus.verify_compiled_dag(_resign_dag_with_profile_presence(tampered, False))["valid"] is False


def test_malformed_dag_node_content_fails_closed_without_crashing():
    node = perseus.ContextNode(kind="requirement", content="compile", evidence={"validity": "observed", "verified": True, "source_ids": ["file:root"]})
    artifact = perseus.compile_context_dag(task_id="malformed-node-sentinel", root=node)
    graph = copy.deepcopy(artifact["graph"])
    raw = graph["nodes"][0]
    raw["content"] = 123
    raw["summary"] = "safe summary"
    raw["content_ref"] = perseus._dag_sha(123)
    raw["node_id"] = perseus._dag_sha(raw["kind"], raw["content_ref"], perseus._dag_json(raw["evidence"]), raw["version"], perseus._dag_json(raw["meta"]))
    graph["digest"] = perseus._dag_sha(
        graph["task_id"],
        ",".join(sorted(item["node_id"] for item in graph["nodes"])),
        ",".join(sorted(item["edge_id"] for item in graph["edges"])),
        graph["version"],
        perseus._dag_json(graph["meta"]),
    )
    tampered = copy.deepcopy(artifact)
    tampered["graph"] = graph
    try:
        result = perseus.verify_compiled_dag(tampered)
    except Exception as exc:  # pragma: no cover - assertion gives a useful failure
        pytest.fail(f"malformed DAG crashed verifier: {type(exc).__name__}: {exc}")
    assert result["valid"] is False



def test_agent_projection_redacts_uri_userinfo_in_text():
    scope = {"workspace": "uri-text-boundary"}
    body = "safe answer scheme://:SUPERSECRET@example.test/private"
    record = {
        "candidate_id": "uri-text-item",
        "agent_text": body,
        "content": body,
        "source_id": "vault:uri-text",
        "scope": scope,
        "validity_state": "observed",
        "validity": "observed",
        "verified": True,
        "evidence_digest": hashlib.sha256(body.encode()).hexdigest(),
    }
    perseus.agent_projection_consent(
        agent_id="uri-text-agent",
        scope=scope,
        permissions={"release": True},
        _authority_verified=True,
        _grantor_id="uri-text-grantor",
    )
    result = perseus.agent_projection_preview(
        [record],
        agent_id="uri-text-agent",
        scope=scope,
        task="safe answer",
        integrations={"vault": "active", "ledger": "active"},
    )
    serialized = json.dumps(result, sort_keys=True)
    assert "SUPERSECRET" not in serialized
    assert "scheme://:SUPERSECRET@example.test" not in serialized


def test_dag_verifier_rejects_wall_clock_over_deadline():
    node = perseus.ContextNode(
        kind="requirement",
        content="deadline sentinel",
        evidence={"validity": "observed", "verified": True, "source_ids": ["file:deadline"]},
    )
    artifact = perseus.compile_context_dag(task_id="deadline-sentinel", root=node)
    artifact["budget"]["wall_clock_s"] = artifact["budget"]["limits"]["deadline_s"] + 1000
    assert perseus.verify_compiled_dag(artifact)["valid"] is False



def test_sensitive_source_reference_suffixes_are_committed_not_emitted():
    body = "credential source body"
    entry = _entry(
        candidate_id="source-leak",
        source_id="vault:api_key:SECRET_SENTINEL",
        content=body,
        evidence_digest=hashlib.sha256(body.encode()).hexdigest(),
        validity_state="observed",
        validity="observed",
        verified=True,
    )
    evidence = perseus.project_context_evidence(
        [entry],
        provider_states={"vault": "active", "ledger": "active"},
        evidence_required=True,
    )
    ranked = perseus.context_rank(
        [entry],
        task="credential source",
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    asked = perseus.context_ask(
        "credential source",
        context=[entry],
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    serialized = json.dumps({"evidence": evidence, "rank": ranked, "ask": asked}, sort_keys=True)
    assert "SECRET_SENTINEL" not in serialized
    assert "api_key" not in serialized.lower()
    assert any(ref.startswith("vault:sha256:") for ref in evidence["selected"][0]["source_refs"])


def test_verify_compiled_dag_rejects_malformed_uncertainty_and_graph_container():
    node = perseus.ContextNode(kind="requirement", content="malformed sentinel")
    artifact = perseus.compile_context_dag(task_id="malformed-sentinel", root=node)
    malformed_uncertainty = copy.deepcopy(artifact)
    malformed_uncertainty["graph"]["nodes"][0]["uncertainty"] = 123
    malformed_graph = copy.deepcopy(artifact)
    malformed_graph["graph"] = None
    assert perseus.verify_compiled_dag(malformed_uncertainty)["valid"] is False
    assert perseus.verify_compiled_dag(malformed_graph)["valid"] is False



def test_verify_compiled_dag_rejects_non_mapping_budget_without_raising():
    node = perseus.ContextNode(kind="requirement", content="budget container sentinel")
    artifact = perseus.compile_context_dag(task_id="budget-container-sentinel", root=node)
    for malformed in (123, None, [], ["not-a-pair"]):
        candidate = copy.deepcopy(artifact)
        candidate["budget"] = malformed
        assert perseus.verify_compiled_dag(candidate)["valid"] is False



def test_private_sensitivity_is_trimmed_before_public_projection():
    body = "PRIVATE_SCALAR_SENTINEL"
    record = _entry(
        candidate_id="private-whitespace",
        agent_text=body,
        summary="The private item exists.",
        relevance=1.0,
        source_id="vault:private-ws",
        sensitivity="private ",
        content=body,
        evidence_digest=hashlib.sha256(body.encode()).hexdigest(),
    )
    result = perseus.context_ask(
        "private item",
        context=[record],
        policy={"min_score": 0},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert "PRIVATE_SCALAR_SENTINEL" not in json.dumps(result)
    assert result["status"] != "complete"


def test_context_and_runtime_redact_json_api_credentials_and_bearer_tails():
    body = 'answer {"api_key":"CRED_SENTINEL"}'
    context_result = perseus.context_ask(
        "answer",
        context=[_entry(candidate_id="json-credential", agent_text=body, source_id="vault:cred-json")],
        cfg={"redaction": {"enabled": False}},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert "CRED_SENTINEL" not in json.dumps(context_result)
    for output in ('{"api_key":"CRED_SENTINEL"}', "Authorization: Bearer CRED_SENTINEL"):
        runtime_result = perseus.AdapterResult(
            schema_version="perseus-runtime-result/v1",
            request_id="credential-redaction",
            status="success",
            output=output,
            usage={},
            runtime={},
            error_code=None,
            error_message=None,
            external_fallback_allowed=False,
        )
        assert "CRED_SENTINEL" not in json.dumps(runtime_result.to_dict())


def test_evidence_required_rejects_explicit_synthetic_artifact_reference():
    body = "observed evidence"
    record = _entry(
        candidate_id="synthetic-source-item",
        agent_text=body,
        content=body,
        source_id="artifact:candidate:synthetic-source-item",
        evidence_digest=hashlib.sha256(body.encode()).hexdigest(),
    )
    result = perseus.context_ask(
        "observed",
        context=[record],
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["status"] != "complete"
    assert "artifact:candidate:synthetic-source-item" not in json.dumps(result)


def test_dag_rejects_non_boolean_verified_evidence():
    with pytest.raises(perseus.ContextDagError):
        perseus.ContextNode(
            kind="retrieved_record",
            content="strict evidence",
            evidence={"validity": "inferred", "verified": "false", "source_ids": ["file:x"]},
        )


def test_context_rank_rejects_overflow_and_non_finite_relevance():
    for relevance in (10 ** 10000, float("nan"), float("inf")):
        result = perseus.context_rank(
            [{"candidate_id": "numeric", "agent_text": "numeric", "relevance": relevance}],
            task="numeric",
            policy={"min_score": 0},
            integrations={"vault": "active", "ledger": "active"},
        )
        assert result["status"] == "invalid_input"



def test_public_evidence_and_context_rank_reject_string_verified_flags():
    body = "verified type sentinel"
    record = _entry(
        candidate_id="verified-type",
        content=body,
        agent_text=body,
        verified="false",
        evidence_digest=hashlib.sha256(body.encode()).hexdigest(),
    )
    with pytest.raises(perseus.ContextEvidenceError):
        perseus.project_context_evidence([record], evidence_required=True)
    result = perseus.context_rank(
        [record],
        task="verified type",
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["status"] == "invalid_input"



def test_answer_projection_requires_real_public_source_reference():
    result = perseus.context_ask(
        "answer body",
        context=[{"candidate_id": "no-source", "agent_text": "answer body", "content": "answer body", "validity": "observed", "verified": True}],
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["status"] != "complete"
    assert "artifact:candidate:" not in json.dumps(result)


def test_dag_evidence_uncertainty_metadata_and_sources_are_closed():
    with pytest.raises(perseus.ContextDagError):
        perseus.ContextNode(
            kind="retrieved_record",
            content="public node",
            evidence={"validity": "observed", "verified": True, "source_ids": ["attacker:forged"], "private_scalar": "DAG_SECRET"},
            meta={"private": "DAG_META_SECRET"},
        )
    with pytest.raises(perseus.ContextDagError):
        perseus.ContextNode(
            kind="retrieved_record",
            content="bad uncertainty",
            uncertainty={"class": "bogus", "score": "not-a-number"},
            evidence={"validity": "observed", "verified": True, "source_ids": ["file:source"]},
        )


def test_runtime_provider_reference_is_commitment_only():
    capabilities = perseus.RuntimeCapabilities.from_mapping({
        "schema_version": "perseus-runtime-capabilities/v1",
        "backend_id": "backend",
        "backend_version": "1",
        "model_id": "model",
        "model_version": "1",
        "tokenizer_id": "tokenizer",
        "context_capacity_tokens": 128,
        "execution_modes": ["offline"],
        "streaming": False,
        "tools": False,
        "hardware_class": "cpu",
        "resource_metrics": [],
        "auth_mode": "none",
        "provider_ref": "RUNTIME_PRIVATE_SENTINEL",
    })
    output = capabilities.to_dict()
    assert "RUNTIME_PRIVATE_SENTINEL" not in json.dumps(output)
    assert output["provider_ref"].startswith("sha256:")


def test_dag_rejects_duplicate_containers_and_cisc_non_finite_inputs():
    node = perseus.ContextNode(kind="requirement", content="duplicate", evidence={"validity": "observed", "verified": True, "source_ids": ["file:root"]})
    graph = perseus.ContextDAG(task_id="duplicate")
    graph.add_node(node)
    raw = graph.to_dict()
    raw["nodes"].append(copy.deepcopy(raw["nodes"][0]))
    with pytest.raises(perseus.ContextDagError):
        perseus.ContextDAG.from_dict(raw)
    with pytest.raises(perseus.ContextDagError):
        perseus.cisc_prioritize([{"path_id": "a", "confidence": float("inf")}])
    with pytest.raises(perseus.ContextDagError):
        perseus.cisc_prioritize([{"path_id": "a", "confidence": 1.0}], temperature=float("nan"))


def test_dag_deadline_is_checked_after_slow_fetch():
    root = perseus.ContextNode(
        kind="requirement",
        content="deadline root",
        uncertainty={"class": "low", "score": 0.2},
        evidence={"validity": "observed", "verified": True, "source_ids": ["file:root"]},
    )
    def slow_fetch(_node):
        time.sleep(0.03)
        return []
    with pytest.raises(perseus.BudgetExceeded):
        perseus.compile_context_dag(
            task_id="deadline-after-fetch",
            root=root,
            fetch=slow_fetch,
            budget=perseus.CompilationBudget(deadline_s=0.001),
        )


def test_multi_topic_revocation_blocks_old_projection():
    boundary = perseus.AgentProjectionBoundary()
    scope = {"tenant": "tenant-revoke", "workspace": "workspace-revoke"}
    boundary.grant_consent(
        agent_id="agent-revoke",
        scope=scope,
        permissions={"preview": True, "release": True},
        topics=["alpha", "beta"],
    )
    records = []
    for topic in ("alpha", "beta"):
        body = f"{topic} decision"
        records.append({
            "candidate_id": topic,
            "topic": topic,
            "scope": scope,
            "summary": body,
            "agent_text": body,
            "content": body,
            "source_id": f"vault:{topic}",
            "validity": "observed",
            "verified": True,
            "content_sha256": hashlib.sha256(body.encode()).hexdigest(),
        })
    preview = boundary.preview(
        records,
        agent_id="agent-revoke",
        scope=scope,
        task="decision",
        integrations={"vault": "active", "ledger": "active"},
    )
    assert preview["status"] == "complete"
    assert boundary.release(preview)["status"] == "complete"
    boundary.revoke(agent_id="agent-revoke", scope=scope, topic="alpha")
    released = boundary.release(preview)
    assert released["failure_state"] == "revoked"
