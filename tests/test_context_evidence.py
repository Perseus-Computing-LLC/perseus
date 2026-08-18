"""Tests for the #982 context evidence/abstention projection."""
from __future__ import annotations

import hashlib
import json

import pytest

from conftest import perseus


def _candidate_commitment(identifier):
    return "sha256:" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def _entry(identifier="item-1", **extra):
    value = {
        "candidate_id": identifier,
        "agent_text": "The bounded evidence summary.",
        "source_id": "vault:entity-1",
        "provenance_id": "ledger:receipt-1",
        "content": "The bounded evidence body.",
        "evidence_digest": hashlib.sha256("The bounded evidence body.".encode("utf-8")).hexdigest(),
        "valid_at": "2026-08-17T12:00:00Z",
        "transaction_time": "2026-08-17T12:01:00Z",
        "validity_state": "observed",
        "selection_reason": "source matched the task",
        "relevance": 0.99,
    }
    value.update(extra)
    return value


def test_success_projection_is_deterministic_sanitized_and_traceable():
    projection = perseus.project_context_evidence(
        [_entry()],
        provider_states={"vault": "active", "ledger": "active"},
        evidence_required=True,
    )
    assert projection["schema_version"] == "perseus-context-evidence/v1"
    assert projection["coverage"]["state"] == "evidence_backed"
    assert projection["coverage"]["abstention_required"] is False
    item = projection["selected"][0]
    assert item["source_refs"] == ["ledger:receipt-1", "vault:entity-1"]
    assert item["evidence_digest"] == hashlib.sha256("The bounded evidence body.".encode("utf-8")).hexdigest()
    assert item["transaction_time"] == "2026-08-17T12:01:00Z"
    serialized = json.dumps(projection, sort_keys=True).lower()
    for forbidden in ("prompt", "private_body", "api_key", "authorization", "password"):
        assert forbidden not in serialized
    assert perseus.verify_context_evidence(projection, [_entry()])["valid"] is True
    assert perseus.render_context_evidence(projection, [_entry()]) == perseus.render_context_evidence(projection, [_entry()])


def test_states_remain_distinct_and_evidence_required_abstains():
    cases = {
        "partial": {"coverage_state": "partial"},
        "conflicted": {"coverage_state": "conflicted"},
        "stale": {"validity_state": "stale"},
        "empty": [],
        "unavailable": {"provider_states": {"vault": "unavailable"}},
        "timeout": {"provider_states": {"vault": "timeout"}},
    }
    for expected, case in cases.items():
        if isinstance(case, list):
            entries = case
            providers = {"vault": "active", "ledger": "active"}
        else:
            entry_values = {key: value for key, value in case.items() if key != "provider_states"}
            entries = [_entry(**entry_values)]
            providers = case.get("provider_states", {"vault": "active", "ledger": "active"})
            if "ledger" not in providers:
                providers = {**providers, "ledger": "active"}
        projection = perseus.project_context_evidence(
            entries, provider_states=providers, evidence_required=True
        )
        assert projection["coverage"]["state"] == expected
        assert projection["coverage"]["abstention_required"] is True
        assert projection["status"] == "abstention_required"


def test_score_does_not_become_a_truth_gate_and_exclusions_are_bounded():
    projection = perseus.project_context_evidence(
        [_entry("low-score", relevance=0.0)],
        excluded=[{"candidate_id": "missing", "reason": "scope mismatch"}],
        provider_states={"vault": "active", "ledger": "active"},
        evidence_required=True,
    )
    assert projection["coverage"]["state"] == "evidence_backed"
    assert projection["diagnostics"]["relevance_is_not_truth_gate"] is True
    assert projection["excluded"] == [{"candidate_id": _candidate_commitment("missing"), "reason": "scope mismatch"}]


def test_raw_material_digest_mismatch_is_rejected_before_projection():
    with pytest.raises(perseus.ContextEvidenceError, match="evidence"):
        perseus.project_context_evidence(
            [_entry(content="password=top-secret", body="private body")],
            evidence_required=True,
        )


def test_item_without_source_reference_is_excluded_even_with_a_digest():
    projection = perseus.project_context_evidence([
        {"candidate_id": "no-source", "evidence_digest": "e" * 64}
    ])
    assert projection["coverage"]["state"] == "empty"
    assert projection["excluded"] == [{"candidate_id": _candidate_commitment("no-source"), "reason": "source_reference_missing"}]


def test_context_rank_composes_evidence_projection_and_abstains_on_stale_required_evidence():
    result = perseus.context_rank(
        [_entry(validity_state="stale", verified=False)],
        task="bounded evidence summary",
        policy={"evidence_required": True},
        integrations={"vault": "active", "ledger": "active"},
    )
    assert result["evidence_projection"]["coverage"]["state"] == "stale"
    assert result["evidence_projection"]["status"] == "abstention_required"


def test_tampering_projection_digest_fails_closed():
    projection = perseus.project_context_evidence([_entry()])
    tampered = json.loads(json.dumps(projection))
    tampered["selected"][0]["source_refs"] = ["forged"]
    assert perseus.verify_context_evidence(tampered)["valid"] is False


def test_evidence_required_without_provider_attestation_abstains():
    projection = perseus.project_context_evidence([_entry()], evidence_required=True)
    assert projection["coverage"]["state"] == "unavailable"
    assert projection["coverage"]["abstention_required"] is True
    assert projection["coverage"]["provider_states"] == {"ledger": "not_configured", "vault": "not_configured"}
