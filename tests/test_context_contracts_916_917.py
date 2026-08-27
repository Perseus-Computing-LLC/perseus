"""Focused contract tests for Perseus issues #916 and #917."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from conftest import cfg, perseus


_SCOPE = {"tenant": "tenant-a", "workspace": "workspace-a", "topic": "release"}


def _candidate(candidate_id: str, summary: str, **extra) -> dict:
    value = {
        "id": candidate_id,
        "summary": summary,
        "scope": dict(_SCOPE),
        "source_id": f"vault:{candidate_id}",
        "validity": "observed",
        "verified": True,
        "valid_at": "2026-08-04T00:00:00Z",
        "recorded_at": "2026-08-04T00:00:01Z",
    }
    value.update(extra)
    for key in ("content", "body", "raw", "private_body"):
        content = value.get(key)
        if isinstance(content, str) and content:
            value["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            break
    return value


def test_versioned_context_schema_accepts_rank_ask_projection_consent_and_release_shapes():
    schema_path = Path(__file__).parents[1] / "schemas" / "context-contract.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    scope = dict(_SCOPE)
    records = [_candidate("schema-case", "Use signed receipts.", topic="release")]
    boundary = perseus.AgentProjectionBoundary()
    outputs = [
        perseus.context_rank(records, task="signed receipts", scope=scope),
        perseus.context_ask("signed receipts", records, scope=scope),
    ]
    preview = boundary.preview(records, agent_id="agent-schema", scope=scope, task="release")
    outputs.append(preview)
    boundary.grant_consent(
        agent_id="agent-schema", scope=scope,
        permissions={"preview": True, "release": True}, topics=["release"],
    )
    outputs.extend([
        boundary.release(preview),
        boundary.revoke(agent_id="agent-schema", scope=scope, topic="release"),
    ])
    errors = [
        (output["schema_version"], list(error.path), error.message)
        for output in outputs
        for error in validator.iter_errors(output)
    ]
    assert errors == []


def test_context_rank_is_deterministic_bounded_and_private_by_construction():
    candidates = [
        _candidate(
            "decision-old",
            "Use the unsigned path",
            content="PRIVATE BODY secret=sk-proj-12345678901234567890",
        ),
        _candidate(
            "decision-new",
            "Use the signed receipt path before release",
            content="PRIVATE BODY secret=sk-proj-12345678901234567890",
            rank_features={"task_terms": 3},
        ),
    ]

    first = perseus.context_rank(
        candidates,
        task="Which signed receipt path should the release use?",
        scope=_SCOPE,
        policy={"max_candidates": 8},
        budget={"max_items": 8, "max_chars": 1200},
    )
    second = perseus.context_rank(
        candidates,
        task="Which signed receipt path should the release use?",
        scope=_SCOPE,
        policy={"max_candidates": 8},
        budget={"max_items": 8, "max_chars": 1200},
    )

    assert first == second
    assert first["schema_version"] == "perseus-context-rank/v1"
    assert first["status"] == "complete"
    assert [item["candidate_id"] for item in first["candidates"]] == [
        "decision-new",
        "decision-old",
    ]
    assert all("content" not in item and "summary" not in item for item in first["candidates"])
    assert "PRIVATE BODY" not in json.dumps(first)
    assert "sk-proj-12345678901234567890" not in json.dumps(first)
    assert first["candidates"][0]["evidence"][0]["source_id"] == "vault:decision-new"
    assert first["scoring"]["mode"] == "deterministic"


def test_context_rank_rejects_duplicate_ids_and_unbounded_input_explicitly():
    duplicate = perseus.context_rank(
        [_candidate("same", "one"), _candidate("same", "two")],
        task="choose",
        scope=_SCOPE,
    )
    oversized = perseus.context_rank(
        [_candidate(f"candidate-{i}", "item") for i in range(65)],
        task="choose",
        scope=_SCOPE,
    )

    assert duplicate["status"] == "invalid_input"
    assert duplicate["failure_state"] == "duplicate_candidate_id"
    assert oversized["status"] == "invalid_input"
    assert oversized["failure_state"] == "candidate_limit_exceeded"


def test_context_rank_filters_scope_and_surfaces_stale_or_contradictory_state():
    result = perseus.context_rank(
        [
            _candidate("in-scope", "supported choice"),
            _candidate("other-workspace", "supported choice", scope={"workspace": "other"}),
            _candidate("stale", "old choice", validity="stale", verified=False),
            _candidate("contradictory", "conflicting choice", validity="contradictory", verified=False),
        ],
        task="supported choice",
        scope=_SCOPE,
    )

    assert result["status"] == "review"
    assert result["failure_state"] == "contradictory_evidence"
    assert [item["candidate_id"] for item in result["candidates"]] == ["in-scope", "stale"]
    assert "other-workspace" in result["excluded_candidate_ids"]
    assert result["candidates"][1]["uncertainty"]["class"] == "stale"


def test_context_ask_is_evidence_linked_and_abstains_without_support():
    supported = perseus.context_ask(
        "Which release path was chosen?",
        context=[
            _candidate(
            "receipt-choice",
            "The release path uses a durable signed receipt before an external write.",
            validity="observed",
            )
        ],
        scope=_SCOPE,
        budget={"max_chars": 120},
    )
    unsupported = perseus.context_ask(
        "What is the unreleased purchase plan?",
        context=[_candidate("unrelated", "The release uses a signed receipt.")],
        scope=_SCOPE,
    )

    assert supported["schema_version"] == "perseus-context-ask/v1"
    assert supported["status"] == "complete"
    assert supported["validity_state"] == "observed"
    assert supported["confidence"]["class"] in {"high", "medium"}
    assert supported["source_refs"] == ["vault:receipt-choice"]
    assert "question" not in supported
    assert unsupported["status"] == "abstain"
    assert unsupported["outcome"] == "insufficient_evidence"
    assert unsupported["answer"] is None


def test_context_operations_expose_routing_budget_and_degraded_states():
    result = perseus.context_ask(
        "What is the current release choice?",
        context=[_candidate("current", "Use signed receipts.")],
        scope=_SCOPE,
        integrations={"vault": "unavailable", "ledger": "not_configured"},
        budget={"max_chars": 2},
    )

    assert result["status"] == "degraded"
    assert result["failure_state"] == "vault_unavailable"
    assert result["context_decision"]["route"] in {
        "inline",
        "reduced_text",
        "retrieve_on_demand",
    }
    assert result["route"]["schema_version"] == "perseus-front-door-route/v1"


def test_degraded_projection_release_receipt_preserves_degraded_status():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-degraded",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [_candidate("degraded-item", "signed release", topic="release")],
        agent_id="agent-degraded",
        scope=_SCOPE,
        task="release",
        integrations={"vault": "unavailable", "ledger": "active"},
    )
    released = boundary.release(preview)
    assert released["status"] == "degraded"
    assert released["receipt"]["status"] == "degraded"


def test_pause_can_be_resumed_but_revocation_remains_blocking():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-resume",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [_candidate("resume-item", "signed release", topic="release")],
        agent_id="agent-resume",
        scope=_SCOPE,
        task="release",
    )
    boundary.pause(agent_id="agent-resume", scope=_SCOPE, topic="release")
    assert boundary.release(preview)["failure_state"] == "paused"
    assert boundary.resume(agent_id="agent-resume", scope=_SCOPE, topic="release")["status"] == "resumed"
    assert boundary.release(preview)["status"] == "complete"
    boundary.revoke(agent_id="agent-resume", scope=_SCOPE, topic="release")
    assert boundary.release(preview)["failure_state"] == "revoked"


def test_context_timeout_is_explicit_not_an_empty_success():
    result = perseus.context_ask(
        "What is the current release choice?",
        context=[_candidate("current", "The release choice is signed receipts.")],
        scope=_SCOPE,
        integrations={"vault": "timeout", "ledger": "active"},
    )

    assert result["status"] == "degraded"
    assert result["failure_state"] == "timeout"


def test_projection_pause_is_distinct_from_revoke_and_blocks_release():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-a",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [_candidate("decision-1", "Use signed receipts.", topic="release")],
        agent_id="agent-a",
        scope=_SCOPE,
        task="release",
    )
    boundary.pause(agent_id="agent-a", scope=_SCOPE, topic="release")

    blocked = boundary.release(preview)
    assert blocked["status"] == "review"
    assert blocked["failure_state"] == "paused"


def test_agent_projection_preview_is_sanitized_and_receipt_is_metadata_only():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-a",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    records = [
        {
            "id": "decision-1",
            "summary": "Use the signed receipt path.",
            "agent_text": "Use the signed receipt path.",
            "source_id": "vault:decision-1",
            "content": "PRIVATE BODY must never be durable",
            "prompt": "PRIVATE PROMPT must never be durable",
            "tool_args": {"token": "sk-proj-12345678901234567890"},
            "scope": dict(_SCOPE),
            "topic": "release",
            "validity": "observed",
            "content_sha256": hashlib.sha256(b"PRIVATE BODY must never be durable").hexdigest(),
            "selection_reason": "highest deterministic rank",
        }
    ]

    preview = boundary.preview(
        records,
        agent_id="agent-a",
        scope=_SCOPE,
        task="prepare the release",
        request_class="decide",
        policy_version="policy-1",
        policy={"max_items": 4},
    )
    released = boundary.release(preview)

    assert preview["schema_version"] == "perseus-agent-projection/v1"
    assert preview["status"] == "complete"
    assert preview["projection"]["items"][0]["text"] == "Use the signed receipt path."
    assert "content" not in preview["projection"]["items"][0]
    assert "PRIVATE BODY" not in json.dumps(preview)
    assert "PRIVATE PROMPT" not in json.dumps(preview)
    assert "sk-proj-12345678901234567890" not in json.dumps(preview)
    assert released["status"] == "complete"
    assert released["projection_digest"] == preview["projection_digest"]
    assert "text" not in released["receipt"]
    assert "PRIVATE BODY" not in json.dumps(released["receipt"])
    assert released["receipt"]["schema_version"] == "perseus-context-release/v1"


def test_projection_requires_consent_then_revocation_invalidates_cache():
    boundary = perseus.AgentProjectionBoundary()
    records = [_candidate("decision-1", "Use the signed receipt path.", topic="release")]
    preview = boundary.preview(
        records,
        agent_id="agent-a",
        scope=_SCOPE,
        task="release",
        policy_version="policy-1",
    )

    denied = boundary.release(preview)
    assert denied["status"] == "review"
    assert denied["failure_state"] == "consent_required"

    boundary.grant_consent(
        agent_id="agent-a",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    released = boundary.release(preview)
    cached = boundary.release(preview)
    assert released["status"] == "complete"
    assert cached["cache"]["hit"] is True

    revocation = boundary.revoke(agent_id="agent-a", scope=_SCOPE, topic="release")
    after_revoke = boundary.release(preview)
    assert revocation["status"] == "revoked"
    assert revocation["cache_invalidated"] is True
    assert after_revoke["status"] == "abstain"
    assert after_revoke["failure_state"] == "revoked"
    assert after_revoke["cache"]["hit"] is False


def test_projection_digest_binds_scope_policy_permissions_and_source_commitments():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-a",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    base = boundary.preview(
        [_candidate("decision-1", "Use signed receipts.", topic="release")],
        agent_id="agent-a",
        scope=_SCOPE,
        task="release",
        policy_version="policy-1",
    )
    changed_policy = boundary.preview(
        [_candidate("decision-1", "Use signed receipts.", topic="release")],
        agent_id="agent-a",
        scope=_SCOPE,
        task="release",
        policy_version="policy-2",
    )
    changed_scope = boundary.preview(
        [_candidate("decision-1", "Use signed receipts.", topic="release")],
        agent_id="agent-a",
        scope={**_SCOPE, "topic": "other"},
        task="release",
        policy_version="policy-1",
    )

    assert len(base["projection_digest"]) == 64
    assert base["projection_digest"] != changed_policy["projection_digest"]
    assert base["projection_digest"] != changed_scope["projection_digest"]


def test_projection_release_rejects_tampered_preview_and_redacts_bare_credentials():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-a",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [{"id": "c1", "topic": "release", "summary": "deploy status", "agent_text": "deploy status secret=TopSecret123"}],
        agent_id="agent-a",
        scope=_SCOPE,
        task="deploy status",
    )
    assert "TopSecret123" not in json.dumps(preview, sort_keys=True)
    tampered = dict(preview)
    tampered["projection"] = dict(preview["projection"])
    tampered["projection"]["items"] = []
    rejected = boundary.release(tampered)
    assert rejected["failure_state"] == "invalid_projection_digest"


def test_projection_release_rejects_self_consistent_forged_preview():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-forge",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [_candidate("forged-item", "safe summary", topic="release")],
        agent_id="agent-forge",
        scope=_SCOPE,
        task="release",
    )

    forged = copy.deepcopy(preview)
    forged["projection"]["items"][0]["text"] = "FORGED-RAW-SECRET"
    projection = forged["projection"]
    normalized_scope = perseus._cc_validate_scope_contract(projection["scope"])
    scope_fp = perseus._cc_sha(normalized_scope)
    forged["projection_digest"] = perseus._cc_sha({
        "schema_version": perseus.AGENT_PROJECTION_SCHEMA_VERSION,
        "agent_id": projection["agent_id"],
        "scope": normalized_scope,
        "request_class": perseus._cc_safe_id(projection["request_class"], fallback="decide"),
        "task_sha256": str(projection["task_sha256"]),
        "policy_version": perseus._cc_safe_id(projection["policy_version"], fallback="policy-v1") or "policy-v1",
        "policy_commitment": str(projection["policy_commitment"]),
        "redaction_policy": projection["redaction_policy"],
        "permissions_commitment": str(projection["permissions_commitment"]),
        "revocation_epoch": boundary._revocation_epoch("agent-forge", scope_fp, "release"),
        "items": projection["items"],
        "selection": forged["selection"],
    })

    rejected = boundary.release(forged)

    assert rejected["status"] == "review"
    assert rejected["failure_state"] == "invalid_projection_digest"
    assert "FORGED-RAW-SECRET" not in json.dumps(rejected)


def test_projection_omits_compact_raw_material_markers_from_agent_text():
    boundary = perseus.AgentProjectionBoundary()
    marker = json.dumps({
        "prompt": "PROMPT-SECRET",
        "body": "BODY-SECRET",
        "credentials": "CRED-SECRET",
    })

    preview = boundary.preview(
        [_candidate("json-marker", marker, topic="release")],
        agent_id="agent-marker",
        scope=_SCOPE,
        task="prompt body credentials",
    )

    assert preview["status"] == "abstain"
    assert preview["failure_state"] == "projection_empty"
    assert preview["projection"]["items"] == []
    serialized = json.dumps(preview)
    assert "PROMPT-SECRET" not in serialized
    assert "BODY-SECRET" not in serialized
    assert "CRED-SECRET" not in serialized


def test_projection_omits_unicode_escaped_raw_material_markers():
    boundary = perseus.AgentProjectionBoundary()
    marker = 'prefix {"\\u0070rompt":"ESCAPED-PROMPT"}'

    preview = boundary.preview(
        [_candidate("escaped-marker", marker, topic="release")],
        agent_id="agent-escaped-marker",
        scope=_SCOPE,
        task="prompt",
    )

    assert preview["status"] == "abstain"
    assert preview["failure_state"] == "projection_empty"
    assert "ESCAPED-PROMPT" not in json.dumps(preview)


def test_issued_preview_registry_is_bounded():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-cache",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    records = [_candidate("cache-item", "safe summary", topic="release")]
    previews = [
        boundary.preview(records, agent_id="agent-cache", scope=_SCOPE, task=f"task-{index}")
        for index in range(perseus.PROJECTION_MAX_RECORDS + 1)
    ]

    assert len(boundary._previews) <= perseus.PROJECTION_MAX_RECORDS
    assert boundary.release(previews[0])["failure_state"] == "invalid_projection_digest"
    assert boundary.release(previews[-1])["status"] == "complete"


def test_context_operations_are_advertised_and_callable_over_mcp(tmp_path):
    names = {tool["name"] for tool in perseus._get_all_mcp_tools(cfg())}
    assert {
        "perseus_context_rank",
        "perseus_context_ask",
        "perseus_agent_projection_preview",
    } <= names
    assert "perseus_agent_projection_release" in names
    assert "perseus_agent_projection_consent" not in names
    assert "perseus_agent_projection_revoke" not in names

    result = perseus._call_tool(
        "perseus_context_rank",
        {
            "task": "signed receipt",
            "scope": _SCOPE,
            "candidates": [_candidate("decision-1", "signed receipt")],
        },
        cfg(),
        tmp_path,
    )
    payload = json.loads(result)
    assert payload["schema_version"] == "perseus-context-rank/v1"
    assert payload["candidates"][0]["candidate_id"] == "decision-1"


def test_consent_topic_restriction_denies_missing_or_ambiguous_projection_topic():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-topic",
        scope={"tenant": "tenant-a", "workspace": "workspace-a"},
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [
            _candidate("release-item", "release decision", topic="release"),
            _candidate("ops-item", "operations decision", topic="operations"),
        ],
        agent_id="agent-topic",
        scope={"tenant": "tenant-a", "workspace": "workspace-a"},
        task="decision",
    )
    blocked = boundary.release(preview)
    assert blocked["status"] == "review"
    assert blocked["failure_state"] == "scope_mismatch"


def test_projection_digest_binds_nested_identity_and_scope():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-digest",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [_candidate("digest-item", "signed release", topic="release")],
        agent_id="agent-digest",
        scope=_SCOPE,
        task="release",
    )
    tampered = dict(preview)
    tampered["projection"] = dict(preview["projection"])
    tampered["projection"]["agent_id"] = "other-agent"
    tampered["projection"]["scope"] = {**_SCOPE, "topic": "other"}
    rejected = boundary.release(tampered)
    assert rejected["failure_state"] == "invalid_projection_digest"


def test_content_commitment_rejects_mismatched_supplied_hash():
    result = perseus.context_rank(
        [{
            "id": "commitment-mismatch",
            "summary": "signed release",
            "content": "actual private body",
            "content_sha256": "a" * 64,
            "scope": _SCOPE,
            "source_id": "vault:commitment-mismatch",
        }],
        task="signed release",
        scope=_SCOPE,
    )
    assert result["status"] == "invalid_input"
    assert result["failure_state"] == "invalid_input"


def test_mcp_consent_requires_explicit_allowlist_and_transport_authority(tmp_path):
    consent_name = "perseus_agent_projection_consent"
    args = {
        "agent_id": "mcp-auth-agent",
        "scope": {"tenant": "tenant-a", "workspace": "workspace-a", "topic": "release"},
        "permissions": {"preview": True, "release": True},
        "topics": ["release"],
    }
    c = cfg()
    c["mcp"] = {
        "tool_allowlist": [consent_name],
        "trusted_transport_identities": ["operator-a"],
    }

    unauthenticated = perseus._call_tool(consent_name, args, c, tmp_path)
    assert unauthenticated.startswith("Error:")
    assert "authority" in unauthenticated.lower()

    caller_supplied_authority = perseus._call_tool(
        consent_name,
        {**args, "authority_token": "authority-test-token", "grantor_id": "operator-a"},
        c,
        tmp_path,
    )
    assert caller_supplied_authority.startswith("Error:")
    assert "transport authority" in caller_supplied_authority.lower()

    granted = perseus._call_tool(
        consent_name,
        args,
        c,
        tmp_path,
        transport_identity="operator-a",
    )
    payload = json.loads(granted)
    assert payload["status"] == "granted"
    assert payload["grantor_id"] == "operator-a"
    assert payload["authority_method"] == "trusted_transport_identity"
    assert "authority-test-token" not in granted


def test_projection_authority_wrappers_require_literal_true_boolean():
    consent = perseus.agent_projection_consent(
        agent_id="typed-authority-agent",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        _authority_verified="false",
        _grantor_id="operator-a",
    )
    revoke = perseus.agent_projection_revoke(
        agent_id="typed-authority-agent",
        scope=_SCOPE,
        _authority_verified="false",
    )
    resume = perseus.agent_projection_resume(
        agent_id="typed-authority-agent",
        scope=_SCOPE,
        _authority_verified="false",
    )

    assert consent["failure_state"] == "permission_denied"
    assert revoke["failure_state"] == "permission_denied"
    assert resume["failure_state"] == "permission_denied"


def test_evidence_metadata_is_closed_and_sensitive_values_are_not_emitted():
    result = perseus.context_rank(
        [
            _candidate(
                "metadata-case",
                "signed release",
                provenance_class="operator@example.invalid",
                valid_at="operator@example.invalid",
                recorded_at="not-a-timestamp",
                observed_at="Bearer secret-value",
            )
        ],
        task="signed release",
        scope=_SCOPE,
    )
    serialized = json.dumps(result, sort_keys=True)
    assert "operator@example.invalid" not in serialized
    assert "Bearer secret-value" not in serialized
    evidence = result["candidates"][0]["evidence"][0]
    assert evidence["provenance_class"] in {"observed", "derived", "inferred", "stale", "contradictory", "unknown"}
    assert "valid_at" not in evidence
    assert "recorded_at" not in evidence
    assert "observed_at" not in evidence


def test_projection_invalid_input_is_schema_valid():
    schema_path = Path(__file__).parents[1] / "schemas" / "context-contract.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    invalid = perseus.AgentProjectionBoundary().preview(
        [], agent_id="", scope={}, task="release",
    )

    assert [error.message for error in validator.iter_errors(invalid)] == []
    assert "projection" not in invalid
    assert "projection_digest" not in invalid


def test_release_rejects_top_level_preview_status_and_failure_tampering():
    schema_path = Path(__file__).parents[1] / "schemas" / "context-contract.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    boundary = perseus.AgentProjectionBoundary()
    records = [_candidate("tamper-status", "signed release", topic="release")]
    preview = boundary.preview(records, agent_id="tamper-agent", scope=_SCOPE, task="release")
    boundary.grant_consent(
        agent_id="tamper-agent", scope=_SCOPE,
        permissions={"preview": True, "release": True}, topics=["release"],
    )

    for key in ("status", "failure_state"):
        tampered = dict(preview)
        tampered[key] = "forged"
        rejected = boundary.release(tampered)
        assert rejected["failure_state"] == "invalid_projection_digest"
        assert [error.message for error in validator.iter_errors(rejected)] == []


def test_mcp_authorization_failures_return_schema_valid_structured_envelopes(tmp_path):
    schema_path = Path(__file__).parents[1] / "schemas" / "context-contract.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    c = cfg()
    c["mcp"] = {
        "tool_allowlist": [
            "perseus_agent_projection_consent",
            "perseus_agent_projection_revoke",
        ],
    }
    calls = [
        (
            "perseus_agent_projection_consent",
            {
                "agent_id": "envelope-agent",
                "scope": _SCOPE,
                "permissions": {"preview": True, "release": True},
            },
        ),
        (
            "perseus_agent_projection_revoke",
            {"agent_id": "envelope-agent", "scope": _SCOPE},
        ),
    ]
    for name, arguments in calls:
        response = perseus._handle_tools_call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
            c,
            tmp_path,
        )
        structured = response["result"]["structuredContent"]
        assert [error.message for error in validator.iter_errors(structured)] == []
        assert structured["operation"] in {"agent_projection_consent", "agent_projection_revoke"}


def test_stdio_server_passes_configured_transport_identity(monkeypatch, tmp_path):
    c = cfg()
    c["mcp"] = {"stdio_transport_identity": "stdio-operator"}
    seen = []
    messages = iter([
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "perseus_context_rank", "arguments": {}}},
        perseus._EOF,
    ])
    monkeypatch.setattr(perseus, "_read_message", lambda: next(messages))
    monkeypatch.setattr(perseus, "_write_message", lambda message: None)
    monkeypatch.setattr(
        perseus,
        "_handle_tools_call",
        lambda message, cfg, workspace, *, transport_identity=None: seen.append(transport_identity) or {},
    )
    assert perseus.serve_mcp(c, tmp_path) == 0
    assert seen == ["stdio-operator"]


def test_projection_metadata_uses_closed_provenance_and_timestamp_fields():
    boundary = perseus.AgentProjectionBoundary()
    preview = boundary.preview(
        [_candidate(
            "metadata-projection",
            "signed release",
            provenance_class="operator@example.invalid",
            valid_at="operator@example.invalid",
            recorded_at="Bearer secret-value",
            topic="release",
        )],
        agent_id="agent-metadata",
        scope=_SCOPE,
        task="signed release",
    )

    serialized = json.dumps(preview, sort_keys=True)
    assert "operator@example.invalid" not in serialized
    assert "Bearer secret-value" not in serialized
    item = preview["projection"]["items"][0]
    assert "valid_at" not in item
    assert "recorded_at" not in item


def test_scope_matching_uses_top_level_topic_and_rejects_conflicts():
    result = perseus.context_rank(
        [
            _candidate(
                "top-level-topic",
                "signed release",
                scope={"tenant": "tenant-a", "workspace": "workspace-a"},
                topic="release",
            ),
            _candidate(
                "conflicting-topic",
                "signed release",
                scope=dict(_SCOPE),
                topic="operations",
            ),
        ],
        task="signed release",
        scope=_SCOPE,
    )

    assert [item["candidate_id"] for item in result["candidates"]] == ["top-level-topic"]
    assert "conflicting-topic" in result["excluded_candidate_ids"]


def test_projection_digest_binds_nested_projection_metadata():
    boundary = perseus.AgentProjectionBoundary()
    boundary.grant_consent(
        agent_id="agent-nested-digest",
        scope=_SCOPE,
        permissions={"preview": True, "release": True},
        topics=["release"],
    )
    preview = boundary.preview(
        [_candidate("nested-digest", "signed release", topic="release")],
        agent_id="agent-nested-digest",
        scope=_SCOPE,
        task="release",
        policy_version="policy-1",
    )
    tampered = dict(preview)
    tampered["projection"] = dict(preview["projection"])
    tampered["projection"]["policy_version"] = "policy-2"

    rejected = boundary.release(tampered)

    assert rejected["failure_state"] == "invalid_projection_digest"


def test_mcp_release_requires_authenticated_authority_for_state_mutation(tmp_path):
    c = cfg()
    c["mcp"] = {"tool_allowlist": ["perseus_agent_projection_release"]}
    result = perseus._call_tool(
        "perseus_agent_projection_release",
        {
            "records": [],
            "agent_id": "agent-mcp-release",
            "scope": _SCOPE,
        },
        c,
        tmp_path,
    )

    assert result.startswith("Error:")
    assert "authority" in result.lower()


def test_authenticated_transport_identity_reaches_mcp_structured_content(tmp_path):
    c = cfg()
    c["mcp"] = {
        "tool_allowlist": ["perseus_agent_projection_consent"],
        "trusted_transport_identities": ["operator-session"],
    }
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "params": {
            "name": "perseus_agent_projection_consent",
            "arguments": {
                "agent_id": "agent-transport",
                "scope": _SCOPE,
                "permissions": {"preview": True, "release": True},
                "topics": ["release"],
            },
        },
    }

    response = perseus._handle_tools_call(
        msg,
        c,
        tmp_path,
        transport_identity="operator-session",
    )
    result = response["result"]
    payload = json.loads(result["content"][0]["text"])

    assert payload["status"] == "granted"
    assert payload["grantor_id"] == "operator-session"
    assert result["structuredContent"] == payload


def test_agent_projection_release_is_advertised_as_state_changing():
    assert perseus is not None
    c = cfg()
    c["mcp"] = {"tool_allowlist": ["perseus_agent_projection_release"]}
    advertised = {tool["name"]: tool for tool in perseus._get_all_mcp_tools(c)}
    annotations = advertised["perseus_agent_projection_release"]["annotations"]
    assert annotations["readOnlyHint"] is False
    assert annotations["destructiveHint"] is True


def test_context_mcp_output_schemas_are_closed_and_structured_content_matches(tmp_path):
    names = {
        "perseus_context_rank",
        "perseus_context_ask",
        "perseus_agent_projection_preview",
        "perseus_agent_projection_consent",
        "perseus_agent_projection_release",
        "perseus_agent_projection_revoke",
    }
    c = cfg()
    c["mcp"] = {"tool_allowlist": sorted(names)}
    advertised = {tool["name"]: tool for tool in perseus._get_all_mcp_tools(c)}

    def assert_closed(schema):
        if not isinstance(schema, dict):
            return
        if schema.get("type") == "object":
            assert schema.get("additionalProperties") is False, schema
        for value in schema.values():
            if isinstance(value, dict):
                assert_closed(value)
            elif isinstance(value, list):
                for item in value:
                    assert_closed(item)

    for name in names:
        schema = advertised[name]["outputSchema"]
        assert_closed(schema)
        assert_closed(perseus._build_output_schema(name, None))

    response = perseus._handle_tools_call(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "params": {
                "name": "perseus_context_rank",
                "arguments": {
                    "task": "signed receipt",
                    "scope": _SCOPE,
                    "candidates": [_candidate("schema-dispatch", "signed receipt")],
                },
            },
        },
        c,
        tmp_path,
    )
    structured = response["result"]["structuredContent"]
    assert list(Draft202012Validator(advertised["perseus_context_rank"]["outputSchema"]).iter_errors(structured)) == []
