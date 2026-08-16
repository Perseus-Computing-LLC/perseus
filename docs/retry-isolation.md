# Clean-restart attempt isolation (#972)

Attempt-scoped context isolation for multi-attempt agent workloads. When an
attempt fails, its turns stay in the context window and contaminate the
retry. CCRM ([arXiv:2605.08563](https://arxiv.org/abs/2605.08563))
formalizes this: an IID model overestimates pass@3 by 17.4 points on
SWE-bench Verified (98.6% vs 81.2%), the contaminated-cascade model fits
with error < 0.001, and the cascade ratio ε1/ε0 ≈ 7.1 — retry context is
~7x more error-prone per step. The paper's clean-restart dominance theorem
quantifies what context-clearing buys. Implementation:
`src/perseus/retry_isolation.py`. Evaluation: `benchmark/retry-isolation/`.

## The primitives

- **Transactional checkpoints** — `snapshot_context` takes a digest-sealed
  snapshot of the context at each attempt boundary (Perseus owns assembly,
  so this is cheap); `verify_snapshot` replays the digest.
- **Fencing on failure** — `build_retry_context` restores the pre-attempt
  snapshot and injects a bounded, structured failure summary (attempt,
  failed step, failure kind, observed error, quarantine count). The failed
  attempt's turns are **quarantined** — the function fails closed if any of
  them resurface in the restored portion of the retry context. The summary
  is truncated to a hard token cap, never unbounded, and never embeds the
  raw trace.
- **Contamination events** — every fence emits a digest-sealed event
  (`contamination_fenced`, quarantine size, summary, token accounting) for
  observability; `verify_isolation_event` replays it.
- **Attempt-budget allocation** — `attempt_budget_allocation` applies the
  paper's closed form
  `T* = sqrt(B · log(1/(1−ε1)) / log(1/(1−ε0)))`
  to a fixed total budget, returning the optimal attempt count, per-attempt
  budget, and the derivation inputs for audit.

## Relationship to #934

#934 (redaction retry fail-closed) is a skill-mining safety fix; this is
the context-engine primitive for all multi-attempt workloads. They compose:
a fenced retry here can feed its structured failure summary to the #968
TRACE attribution layer as an explicit dissatisfaction signal.

## Evaluation

`benchmark/retry-isolation/run.py` — seeded Monte Carlo at the ~7.1x
cascade ratio: IID overestimate of pass@3 ≥ 8pp (paper: 17.4pp),
clean-restart recovery ≥ 8pp, closed-form allocation exactness, and a
fence demonstration verifying quarantine + event replay. Deterministic
(seed-pinned); the live SWE-bench-style workload remains an opt-in,
paid evaluation outside this offline gate.
