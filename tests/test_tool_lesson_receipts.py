"""Receipt-backed procedural-memory coverage tests (#1017)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import perseus


def new_lesson(store):
    return store.observe_failure(
        tool="http", tool_version="1", provider="local", operation="fetch",
        resource="api", error_type="Timeout",
    )


def attempt(
    store,
    lesson_id,
    result,
    *,
    step_id="deploy",
    step_version=1,
    verifier_version="health-v1",
    environment="env-a",
    attribution="unknown",
    evidence="artifact:run-1",
    measured=False,
    attempt_id=None,
):
    return store.record_attempt(
        lesson_id,
        result=result,
        lesson_version=1,
        step_id=step_id,
        step_version=step_version,
        verifier_id="health-check",
        verifier_version=verifier_version,
        environment_fingerprint=environment,
        environment_measured=measured,
        environment_measurement_ref="ledger:environment-1" if measured else None,
        evidence_ref=evidence,
        attribution=attribution,
        attempt_id=attempt_id,
    )


def test_receipts_are_versioned_immutable_and_redaction_safe(tmp_path):
    path = tmp_path / "lessons.jsonl"
    store = perseus.ToolLessonStore(path)
    lesson = new_lesson(store)
    receipt = attempt(store, lesson["lesson_id"], "confirmed", measured=False)
    assert receipt["schema_version"] == "perseus-procedural-attempt-receipt/v1"
    assert receipt["result"] == "confirmed"
    assert receipt["lesson_version"] == 1
    assert receipt["step_id"] == "deploy"
    assert receipt["environment_source"] == "caller_declared"
    assert receipt["environment_trust"] == "untrusted"
    assert receipt["environment_fingerprint"].startswith("sha256:")
    assert "raw" not in json.dumps(receipt).lower()
    assert "password" not in json.dumps(receipt).lower()

    duplicate = attempt(store, lesson["lesson_id"], "confirmed", measured=False)
    assert duplicate["receipt_id"] == receipt["receipt_id"]
    assert duplicate["deduplicated"] is True
    assert len(store.get(lesson["lesson_id"])["receipts"]) == 1

    with pytest.raises(ValueError, match="result"):
        attempt(store, lesson["lesson_id"], "passed")
    with pytest.raises(ValueError, match="immutable"):
        store.record_attempt(
            lesson["lesson_id"], result="failed", lesson_version=1,
            step_id="deploy", step_version=1, verifier_id="health-check",
            verifier_version="health-v1", environment_fingerprint="env-a",
            environment_measured=False, evidence_ref="artifact:run-1",
            receipt_id=receipt["receipt_id"],
        )


def test_known_win_rate_and_coverage_keep_unknown_outcomes_in_denominator(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "baseline.jsonl")
    lesson = new_lesson(store)
    for index in range(7):
        attempt(store, lesson["lesson_id"], "confirmed", attempt_id=f"confirmed-{index}")
    for index in range(3):
        attempt(store, lesson["lesson_id"], "unknown", evidence="artifact:unknown", attempt_id=f"unknown-{index}")
    stats = store.win_rate(lesson["lesson_id"])
    assert stats["all_attempts"] == 10
    assert stats["known_attempts"] == 7
    assert stats["confirmed"] == 7
    assert stats["failed"] == 0
    assert stats["unknown"] == 3
    assert stats["known_win_rate"] == 1.0
    assert stats["coverage"] == pytest.approx(0.7)
    assert stats["win_rate"] == 1.0

    baseline = store.evaluate_admission(
        lesson["lesson_id"], min_known_attempts=5, min_known_win_rate=1.0,
        min_coverage=0.7, policy_version="trust-policy-v1",
    )
    assert baseline["admissible"] is True

    degraded = perseus.ToolLessonStore(tmp_path / "degraded.jsonl")
    lesson2 = new_lesson(degraded)
    for index in range(5):
        attempt(degraded, lesson2["lesson_id"], "confirmed", attempt_id=f"confirmed-{index}")
    for index in range(5):
        attempt(degraded, lesson2["lesson_id"], "unknown", evidence="artifact:unknown", attempt_id=f"unknown-{index}")
    after = degraded.evaluate_admission(
        lesson2["lesson_id"], min_known_attempts=5, min_known_win_rate=1.0,
        min_coverage=0.7, policy_version="trust-policy-v1",
    )
    assert after["admissible"] is False
    assert after["metrics"]["known_win_rate"] == 1.0
    assert after["metrics"]["coverage"] == pytest.approx(0.5)
    assert after["trust_score"] <= baseline["trust_score"]

    with pytest.raises(ValueError, match="coverage"):
        store.admit_lesson(
            lesson["lesson_id"], evidence_refs=["artifact:admission"],
            require_win_rate=True, min_attempts=5, min_win_rate=1.0,
            min_coverage=0.8, policy_version="trust-policy-v1",
        )


def test_unknown_results_and_unknown_failure_attribution_require_review(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = new_lesson(store)
    for index in range(8):
        attempt(store, lesson["lesson_id"], "confirmed", attempt_id=f"confirmed-{index}")
    attempt(store, lesson["lesson_id"], "failed", attribution="unknown", evidence="artifact:failure", attempt_id="failed-unknown")
    verdict = store.triage_lesson(lesson["lesson_id"], min_attempts=1)
    assert verdict["verdict"] == "inconclusive"
    assert store.get(lesson["lesson_id"])["status"] == "proposed"

    lesson2 = new_lesson(store)
    for index in range(8):
        attempt(store, lesson2["lesson_id"], "confirmed", attempt_id=f"confirmed-2-{index}")
    attempt(store, lesson2["lesson_id"], "unknown", evidence="artifact:unknown", attempt_id="unknown-2")
    verdict2 = store.triage_lesson(lesson2["lesson_id"], min_attempts=1)
    assert verdict2["verdict"] == "inconclusive"
    assert store.get(lesson2["lesson_id"])["status"] == "proposed"


def test_coverage_is_sliceable_by_step_verifier_and_environment_and_survives_reload(tmp_path):
    path = tmp_path / "lessons.jsonl"
    store = perseus.ToolLessonStore(path)
    lesson = new_lesson(store)
    attempt(store, lesson["lesson_id"], "confirmed", step_id="deploy", environment="env-a")
    attempt(store, lesson["lesson_id"], "unknown", step_id="deploy", environment="env-a", evidence="artifact:u")
    attempt(store, lesson["lesson_id"], "confirmed", step_id="health", step_version=2, verifier_version="health-v2", environment="env-b", measured=True)
    report = store.coverage_report(lesson["lesson_id"])
    assert report["schema_version"] == "perseus-procedural-coverage/v1"
    assert report["overall"]["all_attempts"] == 3
    assert report["overall"]["coverage"] == pytest.approx(2 / 3)
    assert report["cohorts"]["step"]
    assert report["cohorts"]["verifier"]
    assert report["cohorts"]["environment"]
    assert report["cohorts"]["step"][0]["metrics"]["sufficient_sample"] is False
    assert all("env-a" not in json.dumps(cohort) for cohort in report["cohorts"]["environment"])

    reloaded = perseus.ToolLessonStore(path)
    assert reloaded.win_rate(lesson["lesson_id"])["all_attempts"] == 3
    assert reloaded.coverage_report(lesson["lesson_id"]) == report


def test_procedural_receipt_schema_is_closed_and_accepts_receipt(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = new_lesson(store)
    receipt = attempt(store, lesson["lesson_id"], "failed", attribution="skill_defect")
    schema = perseus.procedural_attempt_receipt_schema()
    assert schema["additionalProperties"] is False
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
