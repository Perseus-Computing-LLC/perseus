"""Provider-free route-on versus route-off ablation tests (#1022)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import perseus


def item(identifier, text, *, validity="observed", authorized=True, direct=False, session=None):
    return {
        "candidate_id": identifier,
        "content": text,
        "agent_text": text,
        "source_id": f"vault:{identifier}",
        "provenance_id": f"ledger:{identifier}",
        "role": "user",
        "scope": {"workspace": "ws-a"},
        "session_id": session or identifier,
        "validity_state": validity,
        "verified": validity == "observed",
        "authorized": authorized,
        "direct_evidence": direct,
    }


def manifest():
    return {
        "dataset_revision": "fixture-dataset-v1",
        "corpus_revision": "fixture-corpus-v1",
        "context_revision": "perseus-context-vault-v1",
        "vault_revision": "perseus-vault-fixture-v1",
        "answerer": "not_measured",
        "judge": "not_measured",
        "retry_policy": {"max_attempts": 1},
        "route_config": {"structural_weight": 0.2, "feature": "bounded_rank_signal"},
    }


def test_route_ablation_holds_inputs_and_budget_constant_and_replays():
    records = [
        item("direct", "The user directly stated the release is green.", direct=True),
        item("source-b", "A second session contains the deployment date.", session="s-b"),
        item("source-c", "A third session contains the deployment owner.", session="s-c"),
        item("stale", "The stale session says an unsupported owner is admin.", validity="stale"),
        item("denied", "The unauthorized session says the owner is root.", authorized=False),
    ]
    report = perseus.run_context_route_ablation(
        "What did the user state across sessions?",
        records=records,
        scope={"workspace": "ws-a"},
        query_time_unix_ms=1787911200000,
        provider_states={"vault": "active", "ledger": "active"},
        manifest=manifest(),
    )
    assert report["schema_version"] == "perseus-context-route-ablation/v1"
    assert report["manifest"]["gold_blind"] is True
    assert report["manifest"]["query_plan"]["plan_digest"] == report["arms"]["route_off"]["query_plan"]["plan_digest"]
    assert report["manifest"]["token_budget"]["max_packet_tokens"] == report["arms"]["route_on"]["compiler_result"]["policy"]["max_packet_tokens"]
    assert report["comparison"]["candidate_input_equal"] is True
    assert report["comparison"]["budget_equal"] is True
    assert report["comparison"]["route_only_factor"] is True
    assert set(report["arms"]) == {"route_off", "route_on"}
    assert report["arms"]["route_off"]["replay"]["verified"] is True
    assert report["arms"]["route_on"]["replay"]["verified"] is True
    assert "stale" not in {i["candidate_id"] for i in report["arms"]["route_on"]["packet"]}
    assert "denied" not in {i["candidate_id"] for i in report["arms"]["route_on"]["packet"]}
    assert report["arms"]["route_on"]["metrics"]["route_score_is_authority"] is False
    assert report["arms"]["route_on"]["metrics"]["provider_billed_tokens"]["state"] == "not_measured"
    assert perseus.verify_route_ablation(report)["valid"] is True


def test_high_route_score_cannot_elevate_unsupported_or_stale_evidence():
    records = [
        item("good", "The supported value is green.", direct=True),
        item("stale", "The stale unsupported value is red.", validity="stale"),
        item("unsupported", "The unverified value is blue.", validity="inferred"),
    ]
    report = perseus.run_context_route_ablation(
        "What is the supported value?",
        records=records,
        scope={"workspace": "ws-a"},
        query_time_unix_ms=1787911200000,
        route_scores={"good": 0.01, "stale": 1.0, "unsupported": 1.0},
        provider_states={"vault": "active", "ledger": "active"},
        manifest=manifest(),
    )
    for arm in report["arms"].values():
        ids = {entry["candidate_id"] for entry in arm["packet"]}
        assert "good" in ids
        assert "stale" not in ids
        assert "unsupported" not in ids
    assert any(
        omission["candidate_id"] in {"stale", "unsupported"}
        and omission["reason"] in {"stale_evidence", "unverified_evidence"}
        for omission in report["arms"]["route_on"]["omissions"]
    )


def test_route_ablation_rejects_gold_dependent_inputs():
    records = [item("x", "safe")]
    records[0]["question_type"] = "single-session-user"
    with pytest.raises(ValueError, match="gold"):
        perseus.run_context_route_ablation(
            "safe question",
            records=records,
            scope={"workspace": "ws-a"},
            query_time_unix_ms=1787911200000,
            provider_states={"vault": "active", "ledger": "active"},
            manifest=manifest(),
        )


def test_route_ablation_schema_accepts_report():
    import yaml
    from jsonschema import Draft202012Validator

    report = perseus.run_context_route_ablation(
        "Which deployment is current?",
        records=[item("current", "The current deployment is green.", direct=True)],
        scope={"workspace": "ws-a"},
        query_time_unix_ms=1787911200000,
        provider_states={"vault": "active", "ledger": "active"},
        manifest=manifest(),
    )
    schema = yaml.safe_load(
        (Path(__file__).parents[1] / "schemas" / "context-route-ablation.schema.yaml").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
