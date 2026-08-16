"""Clean-restart attempt isolation — retry-contamination fix (#972).

When an agent fails and retries, the failed attempt usually stays in the
context window, contaminating the next attempt. CCRM (arXiv:2605.08563)
formalizes this: an IID model overestimates pass@3 by 17.4 points on
SWE-bench Verified (98.6% vs 81.2%) while the contaminated-cascade model
fits with error < 0.001 — a cascade ratio eps1/eps0 ≈ 7.1, i.e. retry
context is ~7x more error-prone per step. The paper proves a clean-restart
dominance theorem: context-clearing before a retry strictly dominates
replaying the contaminated trace.

This module adds attempt-scoped context isolation as a context-engine
primitive:

* **Transactional checkpoints** at attempt boundaries (Perseus owns
  assembly, so snapshots are cheap and digest-sealed);
* **Fence policy on failure** — restore the pre-attempt snapshot and inject
  a bounded, structured failure summary (what failed, which step, the
  observed error); the failed attempt's turns are quarantined, never
  replayed;
* **Attempt-budget allocation** using the paper's closed form
  ``T* = sqrt(B * log(1/(1-eps1)) / log(1/(1-eps0)))`` for a fixed total
  budget ``B``;
* **Contamination event** emitted whenever a retry is fenced, for
  observability.

Design constraints (matches the sibling context modules): deterministic and
stdlib-only; replay-first digest-sealed artifacts; fail-closed on budget
bounds (the failure summary is truncated to a hard token cap, never
unbounded).
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

TOKEN_NOTE = "rendered token accounting; not provider-billed savings"
DEFAULT_SUMMARY_TOKEN_CAP = 120
DEFAULT_EPS0 = 0.025   # base per-step failure probability
DEFAULT_EPS1 = 0.1775  # contaminated per-step failure probability (~7.1x)

FAILURE_KINDS = frozenset({
    "tool_error", "assertion_failure", "timeout", "model_error",
    "policy_violation",
})


# ── Errors ─────────────────────────────────────────────────────────────────

class RetryIsolationError(ValueError):
    """Base error for retry-isolation construction or verification."""


# ── Deterministic helpers ─────────────────────────────────────────────────

def _rsha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _rjson(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def retry_tokens(text: str) -> int:
    """Deterministic rendered-token estimate (chars//4, ceil)."""
    return max(1, (len(text or "") + 3) // 4)


# ── Context snapshots ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContextSnapshot:
    """A digest-sealed, transactional snapshot of the context at an attempt
    boundary. Identical context always produces the same snapshot_id."""

    attempt_id: str
    context: str
    snapshot_id: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attempt_id:
            raise RetryIsolationError("attempt_id is required")
        if not self.snapshot_id:
            object.__setattr__(self, "snapshot_id", _rsha(
                self.attempt_id, self.context, _rjson(self.meta)))

    def to_dict(self) -> dict:
        return {
            "attempt_id": self.attempt_id,
            "context": self.context,
            "snapshot_id": self.snapshot_id,
            "meta": dict(self.meta),
        }


def snapshot_context(context: str, *, attempt_id: str,
                     meta: Optional[dict] = None) -> dict:
    """Take a transactional checkpoint of the context for one attempt."""
    snap = ContextSnapshot(attempt_id=attempt_id, context=context,
                           meta=meta or {})
    return {
        "schema_version": "perseus-retry-snapshot/v1",
        **snap.to_dict(),
        "tokens": retry_tokens(context),
    }


def verify_snapshot(snapshot: dict) -> dict:
    """Recompute a snapshot's digest commitments."""
    errors: list[str] = []
    if not isinstance(snapshot, dict):
        return {"valid": False, "errors": ["snapshot is not an object"]}
    if snapshot.get("schema_version") != "perseus-retry-snapshot/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    try:
        snap = ContextSnapshot(
            attempt_id=str(snapshot.get("attempt_id", "")),
            context=str(snapshot.get("context", "")),
            snapshot_id=str(snapshot.get("snapshot_id", "")),
            meta=dict(snapshot.get("meta") or {}))
    except RetryIsolationError as exc:
        return {"valid": False, "errors": [f"snapshot invalid: {exc}"]}
    expected_id = _rsha(str(snapshot.get("attempt_id", "")),
                        str(snapshot.get("context", "")),
                        _rjson(dict(snapshot.get("meta") or {})))
    if expected_id != snapshot.get("snapshot_id"):
        errors.append("snapshot_id mismatch")
    if retry_tokens(snapshot.get("context", "")) != snapshot.get("tokens"):
        errors.append("token count mismatch")
    return {"valid": not errors, "errors": errors}


# ── Structured failure summaries ──────────────────────────────────────────

def build_failure_summary(
    *,
    attempt_id: str,
    failed_step: str,
    observed_error: str,
    failure_kind: str = "tool_error",
    max_tokens: int = DEFAULT_SUMMARY_TOKEN_CAP,
    attempt_steps: Optional[list[str]] = None,
) -> str:
    """Bounded, structured failure summary — never the raw failed trace.

    The summary carries: what failed (attempt + step + kind) and the
    observed error, truncated to a hard token cap. It explicitly does NOT
    embed the failed attempt's turns."""
    if failure_kind not in FAILURE_KINDS:
        raise RetryIsolationError(f"unknown failure kind: {failure_kind!r}")
    if max_tokens <= 0:
        raise RetryIsolationError("max_tokens must be > 0")
    step = (failed_step or "").strip()
    error = re.sub(r"\s+", " ", (observed_error or "")).strip()
    steps = attempt_steps or []
    head = (f"<!-- retry-fence:start -->\n"
            f"Attempt {attempt_id} failed.\n"
            f"Failed step: {step}\n"
            f"Failure kind: {failure_kind}\n"
            f"Attempt steps quarantined: {len(steps)}\n"
            f"Observed error: ")
    # Hard cap: truncate the error text so the summary never exceeds the
    # token budget (fail-closed, deterministic).
    cap_err_tokens = max(4, max_tokens - retry_tokens(head + "<!-- retry-fence:end -->"))
    truncated = False
    if retry_tokens(error) > cap_err_tokens:
        while error and retry_tokens(error) > cap_err_tokens:
            error = error[:-8]
        error = error.rstrip() + "…"
        truncated = True
    summary = (head + error + (f" [truncated at {max_tokens} tokens]"
                               if truncated else "")
               + "\n<!-- retry-fence:end -->")
    if retry_tokens(summary) > max_tokens + 8:
        raise RetryIsolationError("failure summary exceeded its token cap")
    return summary


# ── Retry context construction (fencing) ──────────────────────────────────

def build_retry_context(
    snapshot: dict,
    failure: dict,
    *,
    attempt_turns: Optional[list[str]] = None,
    max_summary_tokens: int = DEFAULT_SUMMARY_TOKEN_CAP,
    created_by: str = "",
) -> dict:
    """Restore the pre-attempt snapshot and inject the bounded failure
    summary. The failed attempt's turns are quarantined — they appear
    nowhere in the retry context (verifiable by content scan).

    Emits a contamination event: the fence decision, the quarantine size,
    and the digest commitments, sealed for replay.
    """
    check = verify_snapshot(snapshot)
    if not check["valid"]:
        raise RetryIsolationError(
            "refusing to build retry context from invalid snapshot: "
            + "; ".join(check["errors"]))
    turns = list(attempt_turns or [])
    summary = build_failure_summary(
        attempt_id=str(failure.get("attempt_id", "")),
        failed_step=str(failure.get("failed_step", "")),
        observed_error=str(failure.get("observed_error", "")),
        failure_kind=str(failure.get("failure_kind", "tool_error")),
        max_tokens=max_summary_tokens,
        attempt_steps=turns,
    )
    restored = str(snapshot.get("context", ""))
    retry_context = "\n\n".join(part for part in (restored, summary)
                                if part.strip())
    quarantined = [t for t in turns if t.strip()]
    # Quarantine is checked against the RESTORED portion of the retry
    # context. The summary may legitimately quote the failed step and the
    # observed error — that is its purpose — but the failed attempt's turns
    # must never resurface in the restored pre-attempt context.
    leaked = [t for t in quarantined if t in restored]
    if leaked:  # fail closed: quarantine must be absolute
        raise RetryIsolationError(
            f"quarantine leak: {len(leaked)} failed-attempt turn(s) present "
            "in restored retry context")
    event = {
        "schema_version": "perseus-retry-isolation/v1",
        "created_by": created_by,
        "attempt_id": str(failure.get("attempt_id", "")),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_tokens": retry_tokens(restored),
        "retry_tokens": retry_tokens(retry_context),
        "summary_tokens": retry_tokens(summary),
        "quarantined_turn_count": len(quarantined),
        "contamination_fenced": True,
        "failure_kind": str(failure.get("failure_kind", "tool_error")),
        "failure_summary": summary,
        "retry_context": retry_context,
        "token_accounting": TOKEN_NOTE,
        "generated_at_unix_s": round(time.time(), 3),
    }
    event["event_digest"] = _rsha(
        "snapshot", snapshot.get("snapshot_id"),
        "attempt", event["attempt_id"],
        "summary", _rsha(summary),
        "quarantined", len(quarantined),
        "restored", _rsha(restored))
    return event


def verify_isolation_event(event: dict,
                           snapshot: Optional[dict] = None) -> dict:
    """Replay an isolation event's commitments."""
    errors: list[str] = []
    if not isinstance(event, dict):
        return {"valid": False, "errors": ["event is not an object"]}
    if event.get("schema_version") != "perseus-retry-isolation/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    if not event.get("contamination_fenced"):
        errors.append("contamination flag not set")
    if snapshot is not None:
        check = verify_snapshot(snapshot)
        if not check["valid"]:
            errors.append("snapshot invalid: " + "; ".join(check["errors"]))
        elif snapshot.get("snapshot_id") != event.get("snapshot_id"):
            errors.append("snapshot mismatch")
        restored = snapshot.get("context", "")
        if restored and restored not in event.get("retry_context", ""):
            errors.append("pre-attempt context not restored")
    expected = _rsha(
        "snapshot", event.get("snapshot_id"),
        "attempt", event.get("attempt_id"),
        "summary", _rsha(event.get("failure_summary", "")),
        "quarantined", event.get("quarantined_turn_count"),
        "restored", _rsha(
            (event.get("retry_context", "").split(
                event.get("failure_summary", "\x00"), 1)[0].rstrip("\n")
             if event.get("failure_summary")
             else event.get("retry_context", ""))))
    if expected != event.get("event_digest"):
        errors.append("event_digest mismatch")
    return {"valid": not errors, "errors": errors}


# ── Attempt-budget allocation (paper closed form) ─────────────────────────

def attempt_budget_allocation(
    total_budget: float,
    eps0: float = DEFAULT_EPS0,
    eps1: float = DEFAULT_EPS1,
    *,
    min_attempts: int = 1,
    max_attempts: int = 16,
) -> dict:
    """Optimal attempt count under a fixed total budget, from the paper's
    closed form::

        T* = sqrt(B * log(1/(1-eps1)) / log(1/(1-eps0)))

    where ``eps0`` is the clean per-step failure probability, ``eps1`` the
    contaminated one. Returns the allocation plus the derivation inputs so
    the result is replayable and auditable.
    """
    if total_budget <= 0:
        raise RetryIsolationError("total_budget must be > 0")
    if not 0.0 < eps0 < 1.0 or not 0.0 < eps1 < 1.0:
        raise RetryIsolationError("eps0/eps1 must be in (0, 1)")
    if eps1 <= eps0:
        raise RetryIsolationError(
            "contamination model requires eps1 > eps0 (clean restart is "
            "the better policy)")
    log0 = math.log(1.0 / (1.0 - eps0))
    log1 = math.log(1.0 / (1.0 - eps1))
    t_star = math.sqrt(total_budget * log1 / log0)
    optimal = int(round(min(max(t_star, float(min_attempts)),
                             float(max_attempts))))
    optimal = max(min_attempts, min(max_attempts, optimal))
    return {
        "schema_version": "perseus-attempt-allocation/v1",
        "total_budget": total_budget,
        "eps0": eps0,
        "eps1": eps1,
        "cascade_ratio": round(eps1 / eps0, 3),
        "t_star_continuous": round(t_star, 4),
        "optimal_attempts": optimal,
        "per_attempt_budget": round(total_budget / optimal, 4),
        "derivation": {
            "log0": round(log0, 6),
            "log1": round(log1, 6),
            "formula": "T* = sqrt(B * log(1/(1-eps1)) / log(1/(1-eps0)))",
        },
    }


# ── pass@K simulation (CCRM vs IID) ───────────────────────────────────────

def simulate_pass_at_k(
    k: int,
    steps_per_attempt: int,
    *,
    eps0: float = DEFAULT_EPS0,
    eps1: float = DEFAULT_EPS1,
    trials: int = 4000,
    seed: int = 42,
    policy: str = "contaminated",
) -> dict:
    """Seeded Monte Carlo for pass@K under two policies.

    * ``iid`` — every attempt starts clean: success per attempt is
      independent, P(attempt succeeds) = (1-eps0)^steps.
    * ``contaminated`` — attempt 1 is clean; every retry inherits the
      failed attempt's trace, so its per-step failure rate is eps1.

    * ``clean_restart`` — every retry is fenced: restored snapshot +
      bounded summary, so per-step failure returns to eps0.

    The paper's quantitative claim is reproduced in shape: the IID model
    overestimates pass@K versus the contaminated cascade (17.4 points at
    K=3 on SWE-bench), while clean restart recovers the IID curve — the
    clean-restart dominance theorem in simulation.
    """
    if policy not in {"iid", "contaminated", "clean_restart"}:
        raise RetryIsolationError(f"unknown policy: {policy!r}")
    if k < 1 or steps_per_attempt < 1 or trials < 1:
        raise RetryIsolationError("k, steps_per_attempt, trials must be >= 1")
    rng = random.Random(seed)
    successes = 0

    def attempt_succeeds(rate: float) -> bool:
        for _ in range(steps_per_attempt):
            if rng.random() < rate:
                return False
        return True

    for _ in range(trials):
        ok = attempt_succeeds(eps0)  # first attempt is always clean
        for _ in range(k - 1):
            if ok:
                break
            if policy == "iid":
                ok = attempt_succeeds(eps0)
            elif policy == "contaminated":
                ok = attempt_succeeds(eps1)
            else:  # clean_restart: fence restores the clean rate
                ok = attempt_succeeds(eps0)
        if ok:
            successes += 1
    return {
        "schema_version": "perseus-pass-at-k-simulation/v1",
        "policy": policy,
        "k": k,
        "steps_per_attempt": steps_per_attempt,
        "eps0": eps0,
        "eps1": eps1,
        "trials": trials,
        "seed": seed,
        "pass_rate": round(successes / trials, 4),
    }


def run_ccrm_analysis(
    *,
    total_budget: float = 1000.0,
    steps_per_attempt: int = 8,
    k: int = 3,
    eps0: float = DEFAULT_EPS0,
    eps1: float = DEFAULT_EPS1,
    trials: int = 4000,
    seed: int = 42,
    created_by: str = "",
) -> dict:
    """End-to-end CCRM analysis: allocation + policy comparison, sealed."""
    allocation = attempt_budget_allocation(total_budget, eps0, eps1)
    iid = simulate_pass_at_k(k, steps_per_attempt, eps0=eps0, eps1=eps1,
                             trials=trials, seed=seed, policy="iid")
    contaminated = simulate_pass_at_k(k, steps_per_attempt, eps0=eps0,
                                      eps1=eps1, trials=trials, seed=seed,
                                      policy="contaminated")
    clean = simulate_pass_at_k(k, steps_per_attempt, eps0=eps0, eps1=eps1,
                               trials=trials, seed=seed,
                               policy="clean_restart")
    report = {
        "schema_version": "perseus-ccrm-analysis/v1",
        "created_by": created_by,
        "allocation": allocation,
        "pass_at_k": {"iid": iid["pass_rate"],
                      "contaminated": contaminated["pass_rate"],
                      "clean_restart": clean["pass_rate"]},
        "iid_overestimate_pp": round(
            (iid["pass_rate"] - contaminated["pass_rate"]) * 100, 2),
        "clean_restart_recovery_pp": round(
            (clean["pass_rate"] - contaminated["pass_rate"]) * 100, 2),
        "simulation": {"trials": trials, "seed": seed,
                       "steps_per_attempt": steps_per_attempt, "k": k},
        "token_accounting": TOKEN_NOTE,
        "generated_at_unix_s": round(time.time(), 3),
    }
    report["report_digest"] = _rsha(
        "allocation", _rjson(allocation),
        "pass_at_k", _rjson(report["pass_at_k"]),
        "simulation", _rjson(report["simulation"]))
    return report


__all__ = [
    "TOKEN_NOTE", "DEFAULT_SUMMARY_TOKEN_CAP", "DEFAULT_EPS0", "DEFAULT_EPS1",
    "FAILURE_KINDS", "RetryIsolationError", "ContextSnapshot",
    "snapshot_context", "verify_snapshot", "build_failure_summary",
    "build_retry_context", "verify_isolation_event",
    "attempt_budget_allocation", "simulate_pass_at_k", "run_ccrm_analysis",
    "retry_tokens",
]


# Keep the source module importable from the generated single-file artifact.

def _retry_isolation_module_exports() -> tuple[str, ...]:
    return tuple(__all__)
