"""Evidence-linked tool-lesson lifecycle (#926)."""
from __future__ import annotations

import pytest

from conftest import perseus


def test_failure_deduplication_and_causal_non_promotion(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl", max_proposals=4)
    failure = dict(tool="http", tool_version="1", operation="fetch", resource="api", error_type="Timeout", status=504)
    first = store.observe_failure(**failure)
    duplicate = store.observe_failure(**failure)
    assert first["lesson_id"] == duplicate["lesson_id"]
    assert duplicate["deduplicated"] is True
    assert store.telemetry()["deduplicated_failures"] == 1

    store.expose_lesson(first["lesson_id"], injection_ref="inject-1")
    unrelated = store.record_follow_up(first["lesson_id"], tool="filesystem", operation="read", success=True, evidence_ref="u")
    assert unrelated["classification"] == "unrelated"
    assert store.get(first["lesson_id"])["status"] == "injected"

    correlated = store.record_follow_up(first["lesson_id"], **failure, success=True, evidence_ref="corr")
    assert correlated["classification"] == "temporal_correlation"
    assert store.get(first["lesson_id"])["status"] == "correlated"
    store.admit_lesson(first["lesson_id"], evidence_refs=["independent-review"])
    assert store.get(first["lesson_id"])["status"] == "active"


def test_lessons_are_scoped_and_decay_or_supersede_without_erasing_evidence(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    one = store.observe_failure(tool="db", tool_version="1", operation="query", resource="orders", error_type="Busy", scope={"workspace": "a"})
    two = store.observe_failure(tool="db", tool_version="1", operation="query", resource="orders", error_type="Busy", scope={"workspace": "b"})
    assert one["lesson_id"] != two["lesson_id"]
    assert store.lookup(tool="db", operation="query", resource="orders", scope={"workspace": "a"})["lesson_id"] == one["lesson_id"]
    store.decay_lesson(one["lesson_id"], reason="ineffective")
    assert store.get(one["lesson_id"])["status"] == "decayed"
    store.supersede_lesson(two["lesson_id"], replacement_id="replacement")
    record = store.get(two["lesson_id"])
    assert record["status"] == "superseded"
    assert record["replacement_id"] == "replacement"
    assert record["failure_signature"]


def test_lessons_do_not_correlate_across_provider_or_version_and_terminal_reobserve_is_new(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    first = store.observe_failure(tool="http", tool_version="1", provider="a", operation="fetch", resource="api", error_type="Timeout")
    store.expose_lesson(first["lesson_id"], injection_ref="inject")
    other_provider = store.record_follow_up(first["lesson_id"], tool="http", tool_version="1", provider="b", operation="fetch", resource="api", success=True)
    other_version = store.record_follow_up(first["lesson_id"], tool="http", tool_version="2", provider="a", operation="fetch", resource="api", success=True)
    assert other_provider["classification"] == "unrelated"
    assert other_version["classification"] == "unrelated"
    store.decay_lesson(first["lesson_id"], reason="expired")
    with pytest.raises(ValueError):
        store.admit_lesson(first["lesson_id"], evidence_refs=["late-evidence"])
    replacement = store.observe_failure(tool="http", tool_version="1", provider="a", operation="fetch", resource="api", error_type="Timeout")
    assert replacement["lesson_id"] != first["lesson_id"]
    assert replacement["prior_lesson_id"] == first["lesson_id"]
    assert store.get(first["lesson_id"])["injection_refs"] == ["inject"]


def test_outcome_ledger_accumulates_and_correlates(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = store.observe_failure(tool="http", tool_version="1", operation="fetch", resource="api", error_type="Timeout", status=504)
    store.expose_lesson(lesson["lesson_id"], injection_ref="inject-1")
    store.record_outcome(lesson["lesson_id"], success=True, evidence_ref="ev-1")
    # A success after injection records temporal correlation, not causal proof.
    assert store.get(lesson["lesson_id"])["status"] == "correlated"
    assert store.get(lesson["lesson_id"])["evidence_refs"] == ["ev-1"]
    store.record_outcome(lesson["lesson_id"], success=False, attribution="skill_defect")
    store.record_outcome(lesson["lesson_id"], success=False, attribution="routing_error")
    stats = store.win_rate(lesson["lesson_id"])
    assert stats["attempts"] == 3
    assert stats["successes"] == 1
    assert stats["failures"] == 2
    assert stats["win_rate"] == pytest.approx(1 / 3)
    assert stats["sufficient_sample"] is True
    assert store.telemetry()["outcomes_recorded"] == 3


def test_win_rate_window_is_bounded_and_tail_scoped(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = store.observe_failure(tool="http", tool_version="1", operation="fetch", resource="api", error_type="Timeout")
    for _ in range(70):
        store.record_outcome(lesson["lesson_id"], success=True)
    record = store.get(lesson["lesson_id"])
    assert len(record["outcomes"]["recent"]) == 64  # bounded rolling window
    full = store.win_rate(lesson["lesson_id"])
    assert full["attempts"] == 70 and full["win_rate"] == 1.0
    tail = store.win_rate(lesson["lesson_id"], window=10)
    assert tail["attempts"] == 10 and tail["win_rate"] == 1.0
    for _ in range(10):
        store.record_outcome(lesson["lesson_id"], success=False, attribution="skill_defect")
    full2 = store.win_rate(lesson["lesson_id"])
    assert full2["attempts"] == 80 and full2["failures"] == 10 and full2["win_rate"] == pytest.approx(0.875)
    tail2 = store.win_rate(lesson["lesson_id"], window=10)
    assert tail2["failures"] == 10 and tail2["win_rate"] == 0.0


def test_outcome_verified_admission_gate(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = store.observe_failure(tool="http", tool_version="1", operation="fetch", resource="api", error_type="Timeout")
    store.expose_lesson(lesson["lesson_id"], injection_ref="inject")
    with pytest.raises(ValueError):
        store.admit_lesson(lesson["lesson_id"], evidence_refs=["e"], require_win_rate=True)
    for _ in range(4):
        store.record_outcome(lesson["lesson_id"], success=False, attribution="skill_defect")
    with pytest.raises(ValueError):
        store.admit_lesson(lesson["lesson_id"], evidence_refs=["e"], require_win_rate=True, min_attempts=5)
    store.record_outcome(lesson["lesson_id"], success=True)
    with pytest.raises(ValueError):
        store.admit_lesson(lesson["lesson_id"], evidence_refs=["e"], require_win_rate=True)  # 1/5 < 0.7
    for _ in range(20):
        store.record_outcome(lesson["lesson_id"], success=True)
    admitted = store.admit_lesson(lesson["lesson_id"], evidence_refs=["e"], require_win_rate=True)
    assert admitted["status"] == "active"
    # Evidence-only admission remains available and unchanged.
    with pytest.raises(ValueError):
        store.admit_lesson(lesson["lesson_id"], evidence_refs=[], require_win_rate=True)


def test_triage_retires_collapsed_lesson_fault_and_exonerates_routing(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = store.observe_failure(tool="http", tool_version="1", operation="fetch", resource="api", error_type="Timeout")
    for _ in range(5):
        store.record_outcome(lesson["lesson_id"], success=False, attribution="skill_defect")
    verdict = store.triage_lesson(lesson["lesson_id"])
    assert verdict["verdict"] == "insufficient_sample"
    assert store.get(lesson["lesson_id"])["status"] == "proposed"
    for _ in range(5):
        store.record_outcome(lesson["lesson_id"], success=False, attribution="skill_defect")
    verdict = store.triage_lesson(lesson["lesson_id"])
    assert verdict["verdict"] == "retire"
    assert verdict["lesson_fault"] == 10 and verdict["exculpated"] == 0
    record = store.get(lesson["lesson_id"])
    assert record["status"] == "decayed"
    assert "win_rate_collapsed" in record["decay_reason"]
    assert "lesson_fault:10" in record["decay_reason"]
    with pytest.raises(ValueError):
        store.record_outcome(lesson["lesson_id"], success=True)  # terminal lessons are frozen
    with pytest.raises(ValueError):
        store.triage_lesson(lesson["lesson_id"])  # terminal lessons cannot be triaged

    # Collapse with failures peeling to routing_error: exonerated, never retired.
    lesson2 = store.observe_failure(tool="db", tool_version="1", operation="query", resource="orders", error_type="Busy")
    store.expose_lesson(lesson2["lesson_id"], injection_ref="i2")
    for _ in range(3):
        store.record_outcome(lesson2["lesson_id"], success=True)
    for _ in range(7):
        store.record_outcome(lesson2["lesson_id"], success=False, attribution="routing_error")
    verdict = store.triage_lesson(lesson2["lesson_id"])
    assert verdict["verdict"] == "exonerated"
    assert verdict["exculpated"] == 7
    assert store.get(lesson2["lesson_id"])["status"] == "correlated"  # untouched

    # Healthy win rate: no mutation.
    lesson3 = store.observe_failure(tool="fs", tool_version="1", operation="read", resource="cfg", error_type="Missing")
    for _ in range(10):
        store.record_outcome(lesson3["lesson_id"], success=True)
    assert store.triage_lesson(lesson3["lesson_id"])["verdict"] == "healthy"

    # Unknown failure attribution requires review rather than silently retiring
    # a lesson whose causal fault was not established.
    lesson4 = store.observe_failure(tool="net", tool_version="1", operation="send", resource="queue", error_type="Refused")
    for _ in range(4):
        store.record_outcome(lesson4["lesson_id"], success=True)
    for _ in range(6):
        store.record_outcome(lesson4["lesson_id"], success=False, attribution="unknown")
    verdict = store.triage_lesson(lesson4["lesson_id"])
    assert verdict["verdict"] == "inconclusive"


def test_outcome_validation_and_persistence(tmp_path):
    store = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    lesson = store.observe_failure(tool="http", tool_version="1", operation="fetch", resource="api", error_type="Timeout")
    with pytest.raises(ValueError):
        store.record_outcome(lesson["lesson_id"], success=True, attribution="who_knows")
    with pytest.raises(ValueError):
        store.record_outcome(lesson["lesson_id"], success="yes")
    with pytest.raises(ValueError):
        store.record_outcome("lesson:missing", success=True)
    store.record_outcome(lesson["lesson_id"], success=True)
    store.record_outcome(lesson["lesson_id"], success=False, attribution="data_drift")
    reloaded = perseus.ToolLessonStore(tmp_path / "lessons.jsonl")
    stats = reloaded.win_rate(lesson["lesson_id"])
    assert stats["attempts"] == 2 and stats["failures"] == 1
    assert reloaded.get(lesson["lesson_id"])["outcomes"]["by_attribution"] == {"data_drift": 1}
    assert reloaded.telemetry()["outcomes_recorded"] == 2
