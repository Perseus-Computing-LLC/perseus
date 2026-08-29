"""Provider-free tests for the Context+Vault compiler (#1016)."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from conftest import cfg, perseus


PROVIDERS = {"vault": "active", "ledger": "active"}


def record(
    identifier: str,
    text: str,
    source: str,
    *,
    role: str = "user",
    session: str = "session-1",
    workspace: str = "ws-a",
    validity: str = "observed",
    **extra,
):
    value = {
        "candidate_id": identifier,
        "content": text,
        "agent_text": text,
        "source_id": f"vault:{source}",
        "provenance_id": f"ledger:{source}",
        "role": role,
        "session_id": session,
        "scope": {"workspace": workspace},
        "validity_state": validity,
        "verified": validity == "observed",
        "event_time": "2026-08-28T10:00:00Z",
        "valid_at": "2026-08-28T10:00:00Z",
        "recorded_at": "2026-08-28T10:01:00Z",
    }
    value.update(extra)
    return value


def compile_request(records, **extra):
    request = {
        "task": "How many distinct deployments occurred across sessions?",
        "scope": {"workspace": "ws-a"},
        "query_time_unix_ms": 1787911200000,
        "records": records,
        "provider_states": PROVIDERS,
        "policy": {"evidence_required": True, "max_packet_tokens": 400},
    }
    request.update(extra)
    return request


def test_gold_blind_compiler_is_deterministic_bounded_and_verifiable():
    records = [
        record("deploy-1", "Deployment alpha completed in staging.", "deploy-1", session="s-1"),
        record("deploy-2", "Deployment beta completed in production.", "deploy-2", session="s-2"),
        record("deploy-duplicate", "Deployment alpha completed in staging.", "deploy-dup", session="s-3"),
        record("wrong-scope", "Deployment outside this workspace.", "wrong", workspace="ws-b"),
        record("assistant-1", "You should deploy on Friday.", "assistant-1", role="assistant", session="s-1"),
    ]
    first = perseus.context_compile(compile_request(records))
    second = perseus.context_compile(compile_request(list(reversed(records))))

    assert first["schema_version"] == "perseus-context-vault/v1"
    assert first["operation"] == "context_compile"
    assert first["query_plan"]["labels"] == ["multi_session"]
    assert first["query_plan"]["query_time_unix_ms"] == 1787911200000
    assert first["digest"] == second["digest"]
    assert first["packet"] == second["packet"]
    assert first["telemetry"]["estimated_render_tokens"] <= 400
    assert first["telemetry"]["source_count"] >= 2
    assert all(item["role_provenance"] in {"user_stated", "assistant_context"} for item in first["packet"])
    assert any(item["role_provenance"] == "assistant_context" for item in first["packet"])
    assert "wrong-scope" not in {item["candidate_id"] for item in first["packet"]}
    assert "Deployment alpha completed in staging." not in json.dumps(first["compiled_dag"])
    assert "answer_session_ids" not in json.dumps(first)
    assert "question_type" not in json.dumps(first)
    assert perseus.verify_context_compile(first)["valid"] is True
    assert perseus.render_context_packet(first) == perseus.render_context_packet(first)


def test_compiler_rejects_gold_fields_instead_of_consuming_them():
    request = compile_request([record("x", "safe evidence", "x")])
    request["records"][0]["answer_session_ids"] = ["sensitive-gold"]
    result = perseus.context_compile(request)
    assert result["status"] == "invalid_input"
    assert result["failure_state"] == "gold_field_present"


def test_temporal_preference_update_and_conflict_metadata_are_preserved():
    records = [
        record(
            "pref-user", "I prefer compact releases.", "pref-user", role="user",
            category="preference", preference_class="stable_preference",
        ),
        record(
            "pref-assistant", "You may prefer large releases.", "pref-assistant", role="assistant",
            category="preference", preference_class="suggestion",
        ),
        record(
            "version-old", "The service uses port 8080.", "version-old", session="s-1",
            category="config", key="service-port", version=1, is_prior=True,
            superseded_by="version-new",
        ),
        record(
            "version-new", "The service uses port 9090.", "version-new", session="s-2",
            category="config", key="service-port", version=2, is_current=True,
            supersedes="version-old",
        ),
        record(
            "conflict-a", "The retention period is 7 days.", "conflict-a",
            category="policy", key="retention", session="s-3",
        ),
        record(
            "conflict-b", "The retention period is 30 days.", "conflict-b",
            category="policy", key="retention", session="s-4",
        ),
    ]
    result = perseus.context_compile(
        compile_request(
            records,
            task="What is the latest retention policy and what did the user prefer before the change?",
        )
    )
    assert result["query_plan"]["labels"] == ["temporal", "preference", "update"]
    temporal_items = [item for item in result["packet"] if item["candidate_id"] == "version-old"]
    assert temporal_items and {"event_time", "valid_time", "recorded_time"}.issubset(temporal_items[0]["temporal"])
    assert {item["role_provenance"] for item in result["packet"]} >= {"user_stated", "assistant_context"}
    assert result["update_relations"]
    assert any(relation["kind"] == "updates" for relation in result["update_relations"])
    assert result["conflicts"]
    assert result["status"] == "review"
    assert result["failure_state"] == "contradictory_evidence"


def test_scope_and_evidence_gates_run_before_selection():
    records = [
        record("good", "The authorized current value is green.", "good"),
        record("stale", "The stale value is purple.", "stale", validity="stale"),
        record("denied", "The unauthorized value is orange.", "denied", authorized=False),
    ]
    result = perseus.context_compile(compile_request(records))
    packet_ids = {item["candidate_id"] for item in result["packet"]}
    assert "good" in packet_ids
    assert "stale" not in packet_ids
    assert "denied" not in packet_ids
    assert any(item["reason"] in {"stale_evidence", "authorization_denied"} for item in result["omissions"])
    assert result["evidence_projection"]["coverage"]["state"] == "evidence_backed"


def test_missing_provider_attestation_abstains_without_changing_default_behavior():
    result = perseus.context_compile(
        compile_request([record("x", "safe evidence", "x")], provider_states=None)
    )
    assert result["status"] == "unavailable"
    assert result["failure_state"] in {"vault_unavailable", "ledger_unavailable"}


def test_context_dag_accepts_typed_update_edges():
    node = perseus.ContextNode(
        kind="retrieved_record",
        content="record",
        evidence={"validity": "observed", "verified": True, "source_ids": ["vault:r"]},
    )
    other = perseus.ContextNode(
        kind="retrieved_record",
        content="new record",
        evidence={"validity": "observed", "verified": True, "source_ids": ["vault:n"]},
    )
    graph = perseus.ContextDAG(task_id="update-edge")
    old_id = graph.add_node(node)
    new_id = graph.add_node(other)
    graph.add_edge("updates", old_id, new_id)
    assert graph.to_dict()["edges"][0]["kind"] == "updates"


def test_context_vault_schema_accepts_compiler_result():
    import yaml
    from jsonschema import Draft202012Validator
    from pathlib import Path

    result = perseus.context_compile(compile_request([record("x", "safe evidence", "x")]))
    schema = yaml.safe_load(
        (Path(__file__).parents[1] / "schemas" / "context-vault.schema.yaml").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result)


def test_mcp_context_compile_is_opt_in_and_dispatches_structured_output(tmp_path):
    disabled = cfg()
    assert not any(
        tool["name"] == "perseus_context_compile"
        for tool in perseus._get_all_mcp_tools(disabled)
    )
    enabled = copy.deepcopy(disabled)
    enabled["perseus_vault"]["context_serving"]["enabled"] = True
    assert any(
        tool["name"] == "perseus_context_compile"
        for tool in perseus._get_all_mcp_tools(enabled)
    )
    args = compile_request([record("x", "safe evidence", "x")])
    raw = perseus._call_tool("perseus_context_compile", args, enabled, tmp_path)
    payload = json.loads(raw)
    assert payload["operation"] == "context_compile"
    assert payload["schema_version"] == "perseus-context-vault/v1"
