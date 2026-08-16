"""Clean-restart attempt isolation — CCRM retry contamination (#972)."""
from __future__ import annotations

import math

import pytest

from conftest import perseus

snapshot = perseus.snapshot_context
verify_snap = perseus.verify_snapshot
summary = perseus.build_failure_summary
build_retry = perseus.build_retry_context
verify_event = perseus.verify_isolation_event
allocate = perseus.attempt_budget_allocation
simulate = perseus.simulate_pass_at_k
analyze = perseus.run_ccrm_analysis


BASE_CONTEXT = ("You are a deployment assistant.\n\n"
                "Goal: ship the release.\n\n"
                "The deploy tool takes --env staging.")

FAILURE = {
    "attempt_id": "attempt-1",
    "failed_step": "deploy --env prod",
    "observed_error": "error: permission denied for environment prod",
    "failure_kind": "tool_error",
}

CONTAMINATED_TURNS = [
    "deploy --env prod",
    "error: permission denied for environment prod",
    "trying prod credentials instead",
    "falling back to force flag",
]


# ── Snapshots ─────────────────────────────────────────────────────────────

def test_snapshot_is_digest_sealed_and_deterministic():
    a = snapshot(BASE_CONTEXT, attempt_id="attempt-1")
    b = snapshot(BASE_CONTEXT, attempt_id="attempt-1")
    assert a["snapshot_id"] == b["snapshot_id"]
    assert a["schema_version"] == "perseus-retry-snapshot/v1"
    assert a["tokens"] == perseus.retry_tokens(BASE_CONTEXT)
    assert snapshot(BASE_CONTEXT, attempt_id="attempt-2")["snapshot_id"] \
        != a["snapshot_id"]
    assert verify_snap(a)["valid"]


def test_snapshot_requires_attempt_id_and_detects_tamper():
    with pytest.raises(perseus.RetryIsolationError):
        snapshot(BASE_CONTEXT, attempt_id="")
    a = snapshot(BASE_CONTEXT, attempt_id="attempt-1")
    a["context"] = "tampered"
    check = verify_snap(a)
    assert check["valid"] is False
    assert any("snapshot_id" in e for e in check["errors"])


# ── Failure summaries ─────────────────────────────────────────────────────

def test_summary_is_structured_and_bounded():
    s = summary(attempt_id="attempt-1", failed_step="deploy --env prod",
                observed_error="error: permission denied",
                attempt_steps=CONTAMINATED_TURNS)
    assert "<!-- retry-fence:start -->" in s
    assert "Attempt attempt-1 failed." in s
    assert "Failed step: deploy --env prod" in s
    assert "Attempt steps quarantined: 4" in s
    assert "error: permission denied" in s
    assert perseus.retry_tokens(s) <= perseus.DEFAULT_SUMMARY_TOKEN_CAP + 8


def test_summary_truncates_long_errors_to_hard_cap():
    s = summary(attempt_id="a", failed_step="step",
                observed_error="x" * 5000, max_tokens=60)
    assert perseus.retry_tokens(s) <= 60 + 8
    assert "[truncated at 60 tokens]" in s
    assert "…" in s


def test_summary_validates_kind_and_cap():
    with pytest.raises(perseus.RetryIsolationError):
        summary(attempt_id="a", failed_step="s", observed_error="e",
                failure_kind="vibes")
    with pytest.raises(perseus.RetryIsolationError):
        summary(attempt_id="a", failed_step="s", observed_error="e",
                max_tokens=0)


# ── Retry fencing ─────────────────────────────────────────────────────────

def test_retry_context_restores_snapshot_and_quarantines_turns():
    snap = snapshot(BASE_CONTEXT, attempt_id="attempt-0")
    event = build_retry(snap, FAILURE, attempt_turns=CONTAMINATED_TURNS)
    assert event["contamination_fenced"] is True
    assert BASE_CONTEXT in event["retry_context"]
    assert "<!-- retry-fence:start -->" in event["retry_context"]
    assert event["quarantined_turn_count"] == 4
    # The failed attempt's turns are absent from the RESTORED portion of
    # the retry context — verifiable in the context trace, per the success
    # criteria. (The bounded summary may quote the failed step/error; that
    # is its purpose and it is not a quarantine leak.)
    restored = event["retry_context"].replace(event["failure_summary"], "")
    for turn in CONTAMINATED_TURNS:
        assert turn not in restored


def test_quarantine_leak_fails_closed():
    snap = snapshot(BASE_CONTEXT, attempt_id="attempt-0")
    # A turn identical to base context content must still be quarantined
    # from the retry context when it appeared in the failed attempt.
    with pytest.raises(perseus.RetryIsolationError):
        build_retry(snap, FAILURE, attempt_turns=[BASE_CONTEXT])


def test_retry_event_verifies_and_detects_tamper():
    snap = snapshot(BASE_CONTEXT, attempt_id="attempt-0")
    event = build_retry(snap, FAILURE, attempt_turns=CONTAMINATED_TURNS)
    check = verify_event(event, snapshot=snap)
    assert check["valid"], check["errors"]
    event["failure_summary"] = "tampered"
    assert verify_event(event, snapshot=snap)["valid"] is False


def test_retry_context_deterministic():
    snap = snapshot(BASE_CONTEXT, attempt_id="attempt-0")
    a = build_retry(snap, FAILURE, attempt_turns=CONTAMINATED_TURNS)
    b = build_retry(snap, FAILURE, attempt_turns=CONTAMINATED_TURNS)
    assert a["retry_context"] == b["retry_context"]
    assert a["event_digest"] == b["event_digest"]


def test_invalid_snapshot_rejected():
    snap = snapshot(BASE_CONTEXT, attempt_id="attempt-0")
    snap["context"] = "tampered"
    with pytest.raises(perseus.RetryIsolationError):
        build_retry(snap, FAILURE)


# ── Attempt-budget allocation ─────────────────────────────────────────────

def test_allocation_matches_paper_closed_form():
    total, eps0, eps1 = 1000.0, 0.01, 0.071
    out = allocate(total, eps0, eps1)
    log0 = math.log(1 / (1 - eps0))
    log1 = math.log(1 / (1 - eps1))
    expected = math.sqrt(total * log1 / log0)
    assert out["t_star_continuous"] == round(expected, 4)
    assert out["cascade_ratio"] == round(eps1 / eps0, 3)
    assert out["per_attempt_budget"] == round(
        total / out["optimal_attempts"], 4)
    assert out["derivation"]["formula"] == \
        "T* = sqrt(B * log(1/(1-eps1)) / log(1/(1-eps0)))"


def test_allocation_validation():
    with pytest.raises(perseus.RetryIsolationError):
        allocate(0.0)
    with pytest.raises(perseus.RetryIsolationError):
        allocate(100.0, eps0=0.5, eps1=0.1)  # eps1 must exceed eps0
    with pytest.raises(perseus.RetryIsolationError):
        allocate(100.0, eps0=0.0)
    out = allocate(10.0)
    assert 1 <= out["optimal_attempts"] <= 16


# ── CCRM simulation ───────────────────────────────────────────────────────

def test_iid_overestimates_pass_at_k_vs_contaminated_cascade():
    iid = simulate(3, 8, trials=4000, seed=42, policy="iid")
    cont = simulate(3, 8, trials=4000, seed=42, policy="contaminated")
    # Paper: IID overestimates pass@3 by 17.4 points (98.6% vs 81.2%) on
    # SWE-bench Verified; with the ~7.1x cascade ratio calibrated defaults
    # the simulation reproduces the same shape (double-digit overestimate).
    gap_pp = round((iid["pass_rate"] - cont["pass_rate"]) * 100, 1)
    assert gap_pp >= 8.0, f"gap only {gap_pp}pp"


def test_clean_restart_recovers_the_iid_curve():
    iid = simulate(3, 8, trials=4000, seed=42, policy="iid")
    clean = simulate(3, 8, trials=4000, seed=42, policy="clean_restart")
    # Clean-restart dominance: fencing returns per-step failure to eps0,
    # so the pass rate matches the IID model (within simulation noise).
    assert abs(clean["pass_rate"] - iid["pass_rate"]) < 0.02
    cont = simulate(3, 8, trials=4000, seed=42, policy="contaminated")
    assert clean["pass_rate"] > cont["pass_rate"]


def test_simulation_is_seeded_deterministic():
    a = simulate(3, 8, trials=1000, seed=7, policy="contaminated")
    b = simulate(3, 8, trials=1000, seed=7, policy="contaminated")
    assert a["pass_rate"] == b["pass_rate"]


def test_ccrm_analysis_report_seals_and_shows_recovery():
    report = analyze(total_budget=1000.0, created_by="test", trials=2000)
    assert report["schema_version"] == "perseus-ccrm-analysis/v1"
    assert report["iid_overestimate_pp"] >= 8.0
    assert report["clean_restart_recovery_pp"] >= 8.0
    assert report["report_digest"]
    assert report["allocation"]["optimal_attempts"] >= 1


def test_unknown_policy_and_bad_params_rejected():
    with pytest.raises(perseus.RetryIsolationError):
        simulate(3, 8, policy="vibes")
    with pytest.raises(perseus.RetryIsolationError):
        simulate(0, 8)
