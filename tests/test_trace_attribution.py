"""Trajectory-mined context-source failure attribution (#968)."""
from __future__ import annotations

import pytest

from conftest import perseus

Record = perseus.TrajectoryRecord
Source = perseus.ContextSource
Span = perseus.SourceSpan
mine = perseus.mine_dissatisfaction_signals
attribute = perseus.attribute_failures
classify = perseus.classify_remediation
propose = perseus.propose_remediation
analyze = perseus.run_trace_analysis
verify = perseus.verify_trace_report


def step(kind, content, role="", **meta):
    return Record(kind=kind, content=content, role=role, meta=meta)


def src(source_id, source_type, content, **meta):
    return Source(source_id=source_id, source_type=source_type,
                  content=content, meta=meta)


TOOL_SCHEMA = src("tools:cli", "tool_schema",
                  "pytest runs the test suite.\n\n"
                  "Accepted flags: -q for quiet output.\n\n"
                  "pytest never accepts --fast.")

KB = src("kb:stack", "knowledge_base",
         "The stack runs on Python 3.12.\n\n"
         "Deployment requires an active service account.\n\n"
         "The database uses postgres 16.")

# ── Records and sources ───────────────────────────────────────────────────

def test_step_kinds_and_stable_ids():
    a = step("user_message", "hello")
    b = step("user_message", "hello")
    assert a.step_id == b.step_id
    assert step("agent_message", "hello").step_id != a.step_id
    with pytest.raises(perseus.TraceError):
        step("vibes", "x")


def test_source_spans_are_derived_and_stable():
    s = src("tools:cli", "tool_schema", "a\n\nb\n\nc")
    assert [sp.index for sp in s.spans] == [0, 1, 2]
    s2 = src("tools:cli", "tool_schema", "a\n\nb\n\nc")
    assert [sp.span_id for sp in s.spans] == [sp.span_id for sp in s2.spans]
    with pytest.raises(perseus.TraceError):
        src("x", "vibes", "x")


# ── Signal mining ─────────────────────────────────────────────────────────

def test_correction_signal_mined_after_agent_step():
    recs = [
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("user_message", "no, use -q not --fast", role="user"),
    ]
    signals = mine(recs)
    assert [s["kind"] for s in signals] == ["correction"]
    assert signals[0]["evidence_steps"] == [recs[2].step_id]
    assert "use -q" in signals[0]["quote"]


def test_correction_window_cues():
    recs = [
        step("user_message", "do the thing", role="user"),
        step("agent_message", "done", role="agent"),
        step("user_message", "that's not right, the flag should be -q",
             role="user"),
    ]
    assert [s["kind"] for s in mine(recs)] == ["correction"]


def test_polite_request_is_not_a_correction():
    recs = [
        step("user_message", "do the thing", role="user"),
        step("agent_message", "done", role="agent"),
        step("user_message", "please use pip to install it", role="user"),
    ]
    assert mine(recs) == []


def test_rephrasing_requires_intervening_agent_step():
    two_part = [
        step("user_message", "list all open issues in the perseus repo",
             role="user"),
        step("user_message", "list open issues in the perseus repo",
             role="user"),
    ]
    assert mine(two_part) == []
    with_agent = [
        step("user_message", "list all open issues in the perseus repo",
             role="user"),
        step("agent_message", "searching issues", role="agent"),
        step("user_message", "list open issues in the perseus repo please",
             role="user"),
    ]
    signals = mine(with_agent)
    assert [s["kind"] for s in signals] == ["rephrasing"]


def test_abandonment_on_failing_tool_result_and_abort_cue():
    failing = [
        step("user_message", "deploy now", role="user"),
        step("tool_call", "kubectl apply", role="agent"),
        step("tool_result", "error: connection refused", role="tool"),
    ]
    assert [s["kind"] for s in mine(failing)] == ["abandonment"]
    aborted = [
        step("user_message", "deploy now", role="user"),
        step("agent_message", "starting rollout", role="agent"),
        step("user_message", "never mind", role="user"),
    ]
    assert [s["kind"] for s in mine(aborted)] == ["abandonment"]


def test_explicit_structured_signal():
    recs = [step("dissatisfaction", "the schema says --fast is valid")]
    signals = mine(recs)
    assert signals[0]["kind"] == "explicit"
    assert signals[0]["severity"] == 1.0


# ── Attribution ───────────────────────────────────────────────────────────

def test_attribution_ranks_sources_with_cited_spans():
    signals = mine([
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("tool_result", "error: unrecognized arguments: --fast",
             role="tool"),
        step("user_message", "no, pytest accepts -q, not --fast",
             role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA, KB])
    assert report["schema_version"] == "perseus-trace-attribution/v1"
    diag = report["diagnoses"][0]
    assert diag["verdict"] == "attributed"
    assert diag["attributed_source_id"] == "tools:cli"
    top = diag["ranking"][0]
    assert top["source_type"] == "tool_schema"
    assert top["span_ids"]  # cited spans are real span IDs
    span_ids = {sp.span_id for sp in TOOL_SCHEMA.spans}
    assert set(top["span_ids"]) <= span_ids
    assert diag["evidence"]["evidence_steps"]


def test_attribution_inconclusive_without_span_overlap():
    signals = mine([
        step("user_message", "do the thing", role="user"),
        step("agent_message", "done", role="agent"),
        step("user_message", "no, use the framistan flag", role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    diag = report["diagnoses"][0]
    assert diag["verdict"] == "inconclusive"
    assert diag["attributed_source_id"] == ""


def test_attribution_deterministic_and_digest_stable():
    recs = [
        step("user_message", "deploy", role="user"),
        step("agent_message", "applying", role="agent"),
        step("user_message", "no, deployment requires the service account",
             role="user"),
    ]
    signals = mine(recs)
    a1 = attribute(signals, [KB])
    a2 = attribute(signals, [KB])
    assert a1 == a2
    assert a1["sources_digest"] == a2["sources_digest"]


# ── CREATE vs UPDATE classification ───────────────────────────────────────

def test_update_when_evidence_lands_on_existing_spans():
    signals = mine([
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("user_message", "no, pytest accepts -q, not --fast",
             role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    cls = classify(report, [TOOL_SCHEMA])
    assert cls[0]["decision"] == "update"
    assert cls[0]["fault_category"] == "tool_schema_defect"
    assert cls[0]["confidence"] >= 0.7
    assert cls[0]["cited_span_ids"]


def test_create_when_evidence_never_lands_on_spans():
    signals = mine([
        step("user_message", "run the checks", role="user"),
        step("agent_message", "using pytest", role="agent"),
        step("user_message", "no, use mypy for type checks", role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    cls = classify(report, [TOOL_SCHEMA])
    assert cls[0]["decision"] == "create"
    assert cls[0]["fault_category"] in {"content_gap", "missing_tool"}


def test_create_when_source_type_missing_entirely():
    signals = mine([
        step("user_message", "audit the deployment", role="user"),
        step("agent_message", "scanning", role="agent"),
        step("user_message", "no, respect the security guardrails",
             role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    cls = classify(report, [TOOL_SCHEMA])
    assert cls[0]["decision"] == "create"
    assert cls[0]["fault_category"] == "guardrail_gap"


def test_contradiction_forces_update():
    signals = mine([
        step("user_message", "what python version?", role="user"),
        step("agent_message", "the stack runs on Python 3.12",
             role="agent"),
        step("user_message", "no, the stack does not run on Python 3.12",
             role="user"),
    ])
    report = attribute(signals, [KB])
    cls = classify(report, [KB])
    assert cls[0]["decision"] == "update"
    assert cls[0]["fault_category"] == "contradiction"
    assert cls[0]["confidence"] >= 0.9


def test_reading_agent_confirms_weak_case_but_cannot_flip_decisive():
    signals = mine([
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("user_message", "no, pytest accepts -q, not --fast",
             role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    # Decisive update: advisory agent cannot flip it.
    cls = classify(report, [TOOL_SCHEMA],
                   reading_agent=lambda sid, q: "create")
    assert cls[0]["decision"] == "update"
    assert cls[0]["advisory_input"] == "create"
    # Weak create: advisory agent may confirm/redirect it.
    weak = mine([
        step("user_message", "run the checks", role="user"),
        step("agent_message", "using pytest", role="agent"),
        step("user_message", "no, use mypy for type checks", role="user"),
    ])
    report2 = attribute(weak, [TOOL_SCHEMA])
    cls2 = classify(report2, [TOOL_SCHEMA],
                    reading_agent=lambda sid, q: "update")
    assert cls2[0]["decision"] == "update"


# ── Proposals ─────────────────────────────────────────────────────────────

def test_update_proposal_targets_cited_spans():
    signals = mine([
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("user_message", "no, pytest accepts -q, not --fast",
             role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    cls = classify(report, [TOOL_SCHEMA])
    plans = propose(cls, [TOOL_SCHEMA])
    assert plans[0]["action"] == "update"
    assert plans[0]["target"]["source_id"] == "tools:cli"
    assert plans[0]["target"]["span_ids"]


def test_create_proposal_targets_new_source_type():
    signals = mine([
        step("user_message", "audit the deployment", role="user"),
        step("agent_message", "scanning", role="agent"),
        step("user_message", "no, respect the security guardrails",
             role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    cls = classify(report, [TOOL_SCHEMA])
    plans = propose(cls, [TOOL_SCHEMA])
    assert plans[0]["action"] == "create"
    assert plans[0]["target"]["source_id"] is None
    assert plans[0]["target"]["source_type"] == "guardrails"


# ── End-to-end report + verification ──────────────────────────────────────

def test_end_to_end_report_seals_and_verifies():
    recs = [
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("tool_result", "error: unrecognized arguments: --fast",
             role="tool"),
        step("user_message", "no, pytest accepts -q, not --fast",
             role="user"),
    ]
    report = analyze(recs, [TOOL_SCHEMA, KB], created_by="test")
    assert report["schema_version"] == "perseus-trace/v1"
    assert report["report_digest"]
    check = verify(report)
    assert check["valid"], check["errors"]
    assert report["proposals"][0]["action"] == "update"


def test_tampered_report_fails_verification():
    recs = [
        step("user_message", "run the tests", role="user"),
        step("agent_message", "running pytest --fast", role="agent"),
        step("user_message", "no, use -q", role="user"),
    ]
    report = analyze(recs, [TOOL_SCHEMA], created_by="test")
    report["signals"][0]["severity"] = 0.1
    check = verify(report)
    assert check["valid"] is False
    assert any("recompute" in e for e in check["errors"])


def test_verify_rejects_wrong_schema():
    assert verify({"schema_version": "other"}).get("valid") is False


def test_six_category_taxonomy_is_complete():
    assert perseus.FAULT_CATEGORIES == {
        "content_gap", "stale_content", "contradiction", "missing_tool",
        "tool_schema_defect", "guardrail_gap",
    }
    assert perseus.SOURCE_TYPES == {
        "system_prompt", "knowledge_base", "tool_schema", "skill",
        "guardrails",
    }


def test_no_patch_for_inconclusive_diagnosis():
    signals = mine([
        step("user_message", "do the thing", role="user"),
        step("agent_message", "done", role="agent"),
        step("user_message", "no, use the framistan flag", role="user"),
    ])
    report = attribute(signals, [TOOL_SCHEMA])
    cls = classify(report, [TOOL_SCHEMA])
    assert cls[0]["decision"] == "create" or cls[0]["confidence"] < 0.7
    plans = propose(cls, [TOOL_SCHEMA])
    # A gap diagnosis is never silently promoted to a patch of an
    # attributed source: it must carry an explicit CREATE target.
    assert all(p["action"] == "create" for p in plans)
