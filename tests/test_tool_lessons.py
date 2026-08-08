"""Evidence-linked tool-lesson lifecycle (#926)."""
from __future__ import annotations

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
