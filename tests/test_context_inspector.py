"""Provider-free contract tests for the progressive context inspector (#1007)."""
from __future__ import annotations

import argparse
import hashlib
import json

import pytest
from pathlib import Path

from conftest import perseus


_SECRET = "PRIVATE BODY api_key=do-not-publish"


def _decision(candidate_id: str, token_estimate: int, disposition: str, **extra) -> dict:
    value = {
        "candidate_id": candidate_id,
        "candidate_commitment": "sha256:" + hashlib.sha256(candidate_id.encode()).hexdigest(),
        "source_arms": [{"arm": "vault", "retrieval_rank": extra.pop("retrieval_rank", 1)}],
        "final_rank": extra.pop("final_rank", None),
        "token_estimate": token_estimate,
        "disposition": disposition,
        "reason_code": disposition,
        "source_refs": [f"vault:{candidate_id}"],
        "evidence_state": extra.pop("evidence_state", "evidence_backed"),
        "validity_state": extra.pop("validity_state", "observed"),
    }
    value.update(extra)
    return value


def _normal_input() -> dict:
    return {
        "run": {
            "run_id": "run-1007",
            "task_id": "task-context-inspector",
            "policy": {"version": "policy-v1", "digest": "sha256:" + "1" * 64},
            "retrieval_profile": {"name": "hybrid", "digest": "sha256:" + "2" * 64},
            "provider_status": "active",
            "latency_ms": 12,
            "declared_budget_tokens": 30,
            "baseline_tokens": 25,
        },
        "candidates": [
            _decision("selected", 20, "selected", final_rank=1, delivered=True, packet_position=1),
            _decision("budgeted", 15, "dropped_budget", final_rank=None),
            _decision("out-of-scope", 10, "out_of_scope", final_rank=None, evidence_state="empty"),
        ],
        "provider_usage": {"provider": "fixture", "input_tokens": 50, "output_tokens": 10, "total_tokens": 60},
        "configuration": {"version": "fixture-config-v1", "mode": "provider-free"},
    }


def test_inspector_has_high_signal_summary_and_separate_token_ledgers():
    report = perseus.inspect_context_run(_normal_input())

    assert report["schema_version"] == "perseus-context-inspector/v1"
    assert report["operation"] == "context_inspect"
    assert report["status"] == "complete"
    assert report["run"]["run_id"] == "run-1007"
    assert report["run"]["counts"]["candidates"]["value"] == 3
    assert report["run"]["counts"]["eligible"]["value"] == 2
    assert report["run"]["counts"]["selected"]["value"] == 1
    assert report["run"]["counts"]["delivered"]["value"] == 1

    rendered = report["budget"]["rendered"]
    assert rendered["retrieved"]["value"] == 45
    assert rendered["eligible"]["value"] == 35
    assert rendered["selected"]["value"] == 20
    assert rendered["delivered"]["value"] == 20
    assert rendered["omitted"]["value"] == 15
    assert rendered["saved"]["value"] == 5
    assert rendered["retrieved"]["unit"] == "tokens"
    assert report["budget"]["within_budget"]["value"] is True

    # Provider usage is present, but can never be relabeled as rendered savings.
    assert report["budget"]["provider_billed"]["value"] == 60
    assert report["budget"]["provider_billed"]["semantics"] == "provider_reported_usage"
    assert report["budget"]["provider_billed"]["semantics"] != rendered["saved"]["semantics"]
    assert "provider-billed" not in rendered["saved"]["semantics"]

    assert report["selection"]["items"][0]["candidate_id"] == "selected"
    assert report["selection"]["items"][0]["packet_position"] == 1
    assert report["selection"]["items"][1]["reason_code"] == "dropped_budget"
    assert report["selection"]["items"][2]["disposition"] == "out_of_scope"
    assert report["budget"]["constraints"]["hard_rejections"] == ["dropped_budget"]
    assert _SECRET not in json.dumps(report, sort_keys=True)

    top_level_status = _normal_input()
    top_level_status["status"] = "complete"
    assert perseus.inspect_context_run(top_level_status)["run"]["provider"]["status"] == "active"

    declared = _normal_input()
    declared["budget"] = {"contributions": {"requirements": {"retrieved": 4, "eligible": 4, "selected": 2, "delivered": 2, "omitted": 2, "saved": 0}}}
    declared_report = perseus.inspect_context_run(declared)
    assert declared_report["budget"]["contributions"]["requirements"]["tokens"]["selected"]["value"] == 2
    assert declared_report["budget"]["contributions"]["requirements"]["tokens"]["selected"]["definition"] == report["budget"]["contributions"]["requirements"]["tokens"]["selected"]["definition"]


def test_inspector_preserves_explicit_degraded_abstention_and_missing_states():
    degraded = _normal_input()
    degraded["run"]["status"] = "degraded"
    degraded["run"]["provider_status"] = "partial"
    degraded["candidates"][0]["evidence_state"] = "stale"
    degraded["candidates"][0]["validity_state"] = "stale"
    degraded["candidates"][0]["reason_code"] = "selected"
    report = perseus.inspect_context_run(degraded)
    assert report["status"] == "degraded"
    assert report["run"]["state"]["degraded"] is True
    assert report["selection"]["items"][0]["evidence_state"] == "stale"

    abstained = _normal_input()
    abstained["run"]["status"] = "abstain"
    abstained["run"]["abstention_required"] = True
    abstained["candidates"] = [_decision("none", 0, "abstained", evidence_state="empty", validity_state="unknown")]
    abstained.pop("provider_usage")
    abstained_report = perseus.inspect_context_run(abstained)
    assert abstained_report["status"] == "abstained"
    assert abstained_report["run"]["state"]["abstention_required"] is True
    assert abstained_report["budget"]["provider_billed"]["state"] == "missing"
    assert abstained_report["selection"]["items"][0]["evidence_state"] == "empty"


def test_comparison_reuses_identical_metric_definitions_and_keeps_missing_provider_usage_distinct():
    baseline = _normal_input()
    candidate = _normal_input()
    candidate["run"]["run_id"] = "run-1007-candidate"
    candidate["run"]["declared_budget_tokens"] = 40
    candidate["candidates"][0]["token_estimate"] = 18
    candidate.pop("provider_usage")

    report = perseus.inspect_context_comparison(baseline, candidate)
    assert report["operation"] == "context_compare"
    assert set(report["baseline"]["budget"]["rendered"]) == set(report["candidate"]["budget"]["rendered"])
    assert report["delta"]["rendered"]["delivered"]["unit"] == "tokens"
    assert report["delta"]["rendered"]["delivered"]["value"] == -2
    assert report["delta"]["provider_billed"]["state"] == "missing"
    assert report["claims"][0]["evidence_class"] == "rendered_token_accounting"
    assert report["claims"][0]["matched_baseline"] is True


def test_inspector_scenarios_are_deterministic_and_expose_commitments_and_replay():
    names = [item["name"] for item in perseus.context_inspector_scenarios()]
    assert names == [
        "current_decision",
        "changed_state",
        "evidence_verification",
        "contradiction",
        "no_evidence",
    ]
    first = [perseus.inspect_context_scenario(name) for name in names]
    second = [perseus.inspect_context_scenario(name) for name in names]
    assert first == second
    for report in first:
        assert report["scenario"]["fixture_commitment"].startswith("sha256:")
        assert report["scenario"]["policy"]["digest"].startswith("sha256:")
        assert report["scenario"]["configuration"]["digest"].startswith("sha256:")
        assert report["replay"]["status"] == "verified"
        assert report["commitments"]["replay"]["digest"] == report["replay"]["replay_digest"]
    assert first[3]["status"] in {"conflicted", "abstained"}
    assert first[4]["status"] == "abstained"


def test_inspector_render_hides_candidate_details_until_requested():
    report = perseus.inspect_context_run(_normal_input())
    summary = perseus.render_context_inspector(report, view="summary")
    detail = perseus.render_context_inspector(report, view="detail")
    assert "## Run summary" in summary
    assert "## Selection detail" not in summary
    assert "selected" not in summary.split("## Run summary", 1)[-1].lower() or "selected count" in summary.lower()
    assert "## Budget breakdown" in detail
    assert "## Selection detail" in detail
    assert "budgeted" in detail
    assert "provider-billed usage" in detail
    assert _SECRET not in detail
    scenario_view = perseus.render_context_inspector(perseus.inspect_context_scenario("current_decision"), view="summary")
    assert "## Reproducible scenario" in scenario_view
    assert "query commitment" in scenario_view
    assert "configuration:" in scenario_view


def test_context_inspector_cli_emits_json_without_mutating_input(tmp_path, capsys):
    source = tmp_path / "inspector.json"
    original = _normal_input()
    source.write_text(json.dumps(original), encoding="utf-8")
    args = argparse.Namespace(
        input=str(source), scenario=None, list_scenarios=False, view="summary",
        json=True, output=None,
    )
    assert perseus.cmd_context_inspector(args, {}) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["operation"] == "context_inspect"
    assert json.loads(source.read_text(encoding="utf-8")) == original


def test_context_inspector_schema_accepts_a_report():
    import yaml
    from jsonschema import Draft202012Validator

    schema_path = Path(__file__).parents[1] / "schemas" / "context-inspector.schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    errors = list(Draft202012Validator(schema).iter_errors(perseus.inspect_context_run(_normal_input())))
    assert errors == []



def test_context_inspector_is_advertised_as_read_only_mcp_tool(tmp_path):
    allowed = ["perseus_context_inspect"]
    advertised = {item["name"]: item for item in perseus._get_all_mcp_tools({"mcp": {"tool_allowlist": allowed}})}
    tool = advertised["perseus_context_inspect"]
    assert tool["annotations"]["readOnlyHint"] is True
    assert tool["inputSchema"]["properties"]["artifact"]["type"] == "object"
    schema = tool["outputSchema"]

    def assert_closed(value):
        if not isinstance(value, dict):
            return
        if value.get("type") == "object":
            assert value.get("additionalProperties") is False
        for child in value.values():
            if isinstance(child, dict):
                assert_closed(child)
            elif isinstance(child, list):
                for item in child:
                    assert_closed(item)

    assert_closed(schema)
    response = perseus._handle_tools_call(
        {
            "jsonrpc": "2.0",
            "id": 1007,
            "params": {"name": "perseus_context_inspect", "arguments": {"artifact": _normal_input()}},
        },
        {"mcp": {"tool_allowlist": allowed}},
        tmp_path,
    )
    assert response["result"].get("isError", False) is False
    structured = response["result"]["structuredContent"]
    assert structured["operation"] == "context_inspect"
    assert structured["status"] == "complete"
    from jsonschema import Draft202012Validator
    assert list(Draft202012Validator(schema).iter_errors(structured)) == []


@pytest.mark.parametrize("run_status", ["disabled", "unavailable", "partial", "timeout", "stale", "conflicted", "empty", "abstain"])
def test_context_inspector_preserves_explicit_operational_states(run_status):
    payload = {"run": {"run_id": "state-fixture", "status": run_status}, "candidates": []}
    report = perseus.inspect_context_run(payload)
    expected = "abstained" if run_status == "abstain" else run_status
    assert report["status"] == expected
    assert expected in {report["status"], report["run"]["state"]["status"]}


def test_context_inspector_accepts_verified_portable_context_artifact_without_raw_body():
    artifact = perseus.build_agent_context_artifact(
        intent="verify a bounded source",
        sources=[{"ref": "vault:source-a", "sha256": "a" * 64}],
    )
    report = perseus.inspect_context_run(artifact)
    assert report["status"] == "complete"
    assert report["budget"]["rendered"]["delivered"]["value"] == artifact["budget"]["estimated_tokens"]
    assert report["selection"]["items"][0]["source_refs"] == ["artifact:vault:source-a"]
    serialized = json.dumps(report, sort_keys=True)
    assert "verify a bounded source" not in serialized
    assert "content" not in serialized.lower()
    assert report["replay"]["sealed_artifacts"]["artifact"]["state"] == "verified"
