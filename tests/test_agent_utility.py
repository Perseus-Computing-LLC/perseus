"""Provider-free paired coding-agent utility protocol contracts (#992)."""
from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path

import pytest

from benchmark.agent_utility import protocol
from benchmark.agent_utility.runner import run_synthetic_pair

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "benchmark" / "agent_utility" / "fixtures"
MANIFEST_PATH = FIXTURE_DIR / "preregistration.json"


def manifest():
    return protocol.load_manifest(MANIFEST_PATH)


def test_fixture_manifest_is_strict_and_binds_every_digest():
    loaded = manifest()
    assert loaded["schema_version"] == protocol.SCHEMA_VERSION
    assert loaded["challenge"]["visible_prompt"]
    assert len(loaded["challenge"]["task_digest"]) == 64
    assert loaded["source"]["materialization"] == "gitless"
    assert loaded["verifier"]["owner"] == "runner"
    assert loaded["verifier"]["hidden"] is True
    assert loaded["verifier"]["mutable"] is False
    assert loaded["fixtures"]["capability"]["digest"]
    assert loaded["fixtures"]["replay"]["digest"]
    assert loaded["fixtures"]["memory"]["digest"]
    assert loaded["manifest_digest"]

    unknown = copy.deepcopy(loaded)
    unknown["surprise"] = True
    with pytest.raises(protocol.ManifestError, match="unknown field"):
        protocol.validate_manifest(unknown)


def test_manifest_rejects_unbound_mutable_verifier_and_missing_digest():
    loaded = manifest()
    mutable = copy.deepcopy(loaded)
    mutable["verifier"]["mutable"] = True
    with pytest.raises(protocol.ManifestError, match="mutable"):
        protocol.validate_manifest(mutable)

    unbound = copy.deepcopy(loaded)
    del unbound["verifier"]["input_binding"]
    with pytest.raises(protocol.ManifestError, match="binding"):
        protocol.validate_manifest(unbound)

    missing = copy.deepcopy(loaded)
    del missing["verifier"]["digest"]
    with pytest.raises(protocol.ManifestError, match="digest"):
        protocol.validate_manifest(missing)


def test_manifest_rejects_path_escape_missing_resources_and_contradictory_arms():
    loaded = manifest()
    escaped = copy.deepcopy(loaded)
    escaped["challenge"]["allowed_output_subtrees"] = ["../escape"]
    with pytest.raises(protocol.ManifestError, match="path"):
        protocol.validate_manifest(escaped)

    missing_resources = copy.deepcopy(loaded)
    del missing_resources["resources"]["memory_mb"]
    with pytest.raises(protocol.ManifestError, match="resources"):
        protocol.validate_manifest(missing_resources)

    contradictory = copy.deepcopy(loaded)
    contradictory["arms"][0]["memory_mode"] = "frozen_fixture"
    contradictory["arms"][0]["fixture_id"] = "memory-fixture"
    with pytest.raises(protocol.ManifestError, match="control"):
        protocol.validate_manifest(contradictory)


def test_no_cost_preflight_and_smoke_never_start_a_model_call():
    loaded = manifest()
    smoke = protocol.run_smoke(MANIFEST_PATH)
    assert smoke["status"] == "passed"
    assert smoke["model_calls"] == 0
    assert smoke["paid_started"] is False
    assert smoke["checks"]["source_materialized"] is True
    assert smoke["checks"]["control_isolated"] is True
    assert smoke["checks"]["treatment_fixture_restored"] is True
    assert smoke["checks"]["verifier_bound"] is True
    assert smoke["checks"]["mutation_audit_ready"] is True
    assert smoke["checks"]["cleanup_verified"] is True
    assert smoke["spend"]["status"] == "not_run"

    runtime = protocol.fixture_runtime(loaded, FIXTURE_DIR)
    preflight = protocol.run_preflight(loaded, runtime=runtime, paid=False)
    assert preflight["ready"] is True
    assert preflight["spend"]["status"] == "not_run"


def test_paid_preflight_fails_closed_on_missing_or_unobserved_spend_fence():
    loaded = manifest()
    runtime = protocol.fixture_runtime(loaded, FIXTURE_DIR)
    blocked = protocol.run_preflight(loaded, runtime=runtime, paid=True)
    assert blocked["ready"] is False
    assert "credential_identity_missing" in blocked["failed"]
    assert "spend_check_missing" in blocked["failed"]

    spend = {
        "credential_identity": loaded["spend_fence"]["credential_identity"],
        "per_key_budget_usd": loaded["spend_fence"]["per_key_budget_usd"],
        "shared_headroom_usd": loaded["spend_fence"]["shared_headroom_usd"],
        "between_arm_drain_observed": False,
    }
    blocked = protocol.run_preflight(
        loaded, runtime=runtime, paid=True,
        credential_identity=spend["credential_identity"], spend=spend,
    )
    assert blocked["ready"] is False
    assert "between_arm_drain_unobserved" in blocked["failed"]
    assert blocked["spend"]["status"] == "failed"


def test_synthetic_pair_has_independent_delivery_use_and_outcome_receipts():
    result = run_synthetic_pair(MANIFEST_PATH)
    validated = protocol.validate_result(result, manifest())
    assert validated["schema_version"] == protocol.RESULT_SCHEMA_VERSION
    assert len(validated["cases"]) == 2
    assert {case["arm_id"] for case in validated["cases"]} == {"control", "treatment"}
    for case in validated["cases"]:
        assert set(case) >= {"delivery", "observable_use", "outcome"}
        assert case["delivery"]["kind"] == "delivery"
        assert case["observable_use"]["kind"] == "observable_use"
        assert case["outcome"]["kind"] == "outcome"
        assert case["observable_use"]["non_use_inferred"] is False
        assert case["observable_use"]["status"] == "not_observed"
        assert "used" not in case["observable_use"]
    assert validated["cases"][0]["comparability_key"] == validated["cases"][1]["comparability_key"]


def _tree_pair(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    for root in (before, after):
        (root / "out").mkdir(parents=True)
        (root / "src").mkdir()
        (root / "src" / "same.txt").write_text("same\n", encoding="utf-8")
        (root / "outside.txt").write_text("original\n", encoding="utf-8")
    return before, after


@pytest.mark.parametrize("mutation", ["added", "removed", "changed", "permission", "type"])
def test_mutation_audit_invalidates_every_off_target_mutation(tmp_path, mutation):
    before, after = _tree_pair(tmp_path)
    target = after / "outside.txt"
    if mutation == "added":
        target.unlink()
        (after / "new.txt").write_text("new\n", encoding="utf-8")
    elif mutation == "removed":
        target.unlink()
    elif mutation == "changed":
        target.write_text("changed\n", encoding="utf-8")
    elif mutation == "permission":
        target.chmod(stat.S_IRUSR)
    elif mutation == "type":
        target.unlink()
        target.mkdir()
        (target / "nested").write_text("nested\n", encoding="utf-8")
    report = protocol.audit_mutations(before, after, allowed_output_subtrees=["out"])
    assert report["valid"] is False
    assert report["off_target"]
    assert mutation in {item["kind"] for item in report["off_target"]} or (
        mutation == "type" and "type_changed" in {item["kind"] for item in report["off_target"]}
    )
    # Audit output is deterministic and contains no host paths.
    assert report == protocol.audit_mutations(before, after, allowed_output_subtrees=["out"])
    assert str(tmp_path) not in json.dumps(report)


def test_mutation_audit_covers_symlink_retarget_and_allows_declared_output(tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    before, after = _tree_pair(tmp_path)
    (before / "link").symlink_to("src/same.txt")
    (after / "link").symlink_to("outside.txt")
    report = protocol.audit_mutations(before, after, allowed_output_subtrees=["out"])
    assert report["valid"] is False
    assert any(item["kind"] == "symlink_retargeted" for item in report["off_target"])

    (after / "out" / "answer.txt").write_text("answer\n", encoding="utf-8")
    allowed = protocol.audit_mutations(before, after, allowed_output_subtrees=["out"])
    assert allowed["valid"] is False  # the symlink remains off target
    (after / "link").unlink()
    (before / "link").unlink()
    allowed = protocol.audit_mutations(before, after, allowed_output_subtrees=["out"])
    assert allowed["valid"] is True
    assert allowed["off_target"] == []


def _case(manifest_obj, arm_id, pair_id="pair-1", cohort_id="cohort-a"):
    key = protocol.build_comparability_key(manifest_obj)
    return {
        "case_id": f"{pair_id}-{arm_id}",
        "pair_id": pair_id,
        "cohort_id": cohort_id,
        "challenge_id": manifest_obj["challenge"]["id"],
        "arm_id": arm_id,
        "status": "completed",
        "acceptance": "accepted",
        "comparability_key": key,
        "capability": {"status": "available"},
        "delivery": protocol.make_delivery_receipt(
            "run", arm_id, delivered=arm_id == "treatment",
            fixture_id=(manifest_obj["fixtures"]["memory"]["id"] if arm_id == "treatment" else None),
            fixture_digest=(manifest_obj["fixtures"]["memory"]["digest"] if arm_id == "treatment" else None),
        ),
        "observable_use": protocol.make_observable_use_receipt("run", arm_id, marker_observed=False),
        "outcome": protocol.make_outcome_receipt(
            "run", arm_id, correctness=1.0,
            mutation_audit={"valid": True, "off_target": []},
        ),
    }


def _valid_result():
    loaded = manifest()
    cases = [_case(loaded, "control"), _case(loaded, "treatment")]
    metrics = [{
        "id": "correctness",
        "kind": "binary",
        "unit": "score",
        "status": "available",
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
    }]
    return protocol.build_result(
        loaded, cases, metrics,
        build_under_test={"id": "fixture-build", "commit": "b" * 40, "digest": "c" * 64},
    )


def test_result_contract_rejects_bad_denominators_nonfinite_values_and_missing_capability():
    loaded = manifest()
    valid = _valid_result()
    assert protocol.validate_result(valid, loaded)["accepted_count"] == 2

    empty = copy.deepcopy(valid)
    empty["cases"] = []
    with pytest.raises(protocol.ResultValidationError, match="cases"):
        protocol.validate_result(empty, loaded)

    nonfinite = copy.deepcopy(valid)
    nonfinite["metrics"][0]["value"] = float("nan")
    with pytest.raises(protocol.ResultValidationError, match="finite"):
        protocol.validate_result(nonfinite, loaded)

    denominator = copy.deepcopy(valid)
    denominator["metrics"][0]["numerator"] = 3
    with pytest.raises(protocol.ResultValidationError, match="denominator"):
        protocol.validate_result(denominator, loaded)

    capability = copy.deepcopy(valid)
    del capability["cases"][0]["capability"]
    with pytest.raises(protocol.ResultValidationError, match="capability"):
        protocol.validate_result(capability, loaded)


def test_result_contract_retains_excluded_runs_and_requires_reason():
    loaded = manifest()
    result = _valid_result()
    result["cases"][0]["acceptance"] = "excluded"
    result["cases"][0]["exclusion_reasons"] = []
    with pytest.raises(protocol.ResultValidationError, match="exclusion"):
        protocol.validate_result(result, loaded)
    result["cases"][0]["exclusion_reasons"] = ["off_target_mutation"]
    result["accepted_count"] = 1
    result["excluded_count"] = 1
    result["result_digest"] = protocol.sha256_value({key: result[key] for key in result if key != "result_digest"})
    assert protocol.validate_result(result, loaded)["excluded_count"] == 1


def test_off_target_mutation_zeroes_and_retains_excluded_attempt():
    loaded = manifest()
    outcome = protocol.make_outcome_receipt(
        "run", "treatment", correctness=1.0,
        mutation_audit={"valid": False, "off_target": [{"path": "outside.txt", "kind": "changed"}]},
    )
    assert outcome["status"] == "invalidated"
    assert outcome["mutation_invalidated"] is True
    assert outcome["correctness"]["value"] == 0.0
    result = _valid_result()
    case = result["cases"][1]
    case["status"] = "invalidated"
    case["acceptance"] = "excluded"
    case["exclusion_reasons"] = ["off_target_mutation"]
    case["outcome"] = outcome
    result["accepted_count"] = 1
    result["excluded_count"] = 1
    result["result_digest"] = protocol.sha256_value({key: result[key] for key in result if key != "result_digest"})
    assert protocol.validate_result(result, loaded)["excluded_count"] == 1


def test_report_keeps_cohorts_separate_and_labels_small_samples_exploratory():
    loaded = manifest()
    cases = [_case(loaded, "control", "a", "cohort-a"), _case(loaded, "treatment", "a", "cohort-a"),
             _case(loaded, "control", "b", "cohort-b"), _case(loaded, "treatment", "b", "cohort-b")]
    result = protocol.build_result(
        loaded, cases,
        [{"id": "correctness", "kind": "binary", "unit": "score", "status": "available",
          "numerator": 4, "denominator": 4, "value": 1.0}],
        build_under_test={"id": "fixture-build", "commit": "b" * 40, "digest": "c" * 64},
    )
    report = protocol.render_report(result)
    assert "Observed results" in report
    assert "Derived paired deltas" in report
    assert "Exploratory" in report
    assert "cohort-a" in report and "cohort-b" in report
    assert "pooled productivity" in report.lower() or "not pooled" in report.lower()
    assert "claim not established" in report.lower()


def test_public_evidence_is_digest_sealed_and_sanitized():
    result = _valid_result()
    result["manifest"] = manifest()
    result["raw_prompt"] = "PRIVATE PROMPT"
    result["child_stdout"] = "PRIVATE STDOUT"
    result["host_path"] = "/private/host/path"
    result["credentials"] = {"api_key": "PRIVATE KEY"}
    sealed = protocol.seal_public_evidence(result)
    encoded = json.dumps(sealed, sort_keys=True)
    assert sealed["evidence_digest"]
    assert "PRIVATE" not in encoded
    assert "/private/host/path" not in encoded
    assert protocol.verify_public_evidence(sealed) is True
    tampered = copy.deepcopy(sealed)
    tampered["evidence"]["accepted_count"] = 999
    assert protocol.verify_public_evidence(tampered) is False


def test_existing_context_bench_artifacts_remain_readable():
    assert (REPO / "benchmark" / "context-bench" / "pilot.json").is_file()
    assert (REPO / "benchmark" / "context-bench" / "README.md").is_file()
    assert (REPO / "benchmark" / "runtime_eval" / "protocol.py").is_file()
    assert (REPO / "benchmark" / "runtime_eval" / "runner.py").is_file()
