# Context-assembly comparison — pinned tasks (direct vs linear vs DAG)

Evaluation for perseus#962 (auditable context-compilation DAG). Deterministic, provider-free run over a frozen synthetic task set.

**Claim discipline:** coverage is a *synthetic reference* (fixture-derived fact presence, not model accuracy). Token numbers are *derived* estimates (``dag_tokens``, chars//4) — not provider billing. Generalization to provider runs is **not established** by this benchmark; the retired adapter is not distributed here.

## Aggregate (excluding the budget-rejection task)

- tasks: 7, budget-rejected: 1 (fail-closed budget enforcement)
- replay deterministic: True
- artifact verification: True

| mode | mean tokens | mean coverage | mean reduction vs direct |
|---|---:|---:|---:|
| direct (stuff all) | 134.8 | 1.0 | — |
| linear (uniform summaries) | 132.7 | 0.833 | 1.8% |
| dag (selective + budgeted) | 94.3 | 0.833 | 29.7% |

DAG terminal verdicts: abstain=0, escalate=1, sufficient=5

## Per-task rows

| task | direct tok / cov | linear tok / cov | dag tok / cov | dag verdict | reduction |
|---|---:|---:|---:|---|---:|
| arcade-01 | 197 / 1.0 | 195 / 0.5 | 151 / 1.0 | sufficient | 23.4% |
| clinic-02 | 161 / 1.0 | 161 / 1.0 | 92 / 1.0 | sufficient | 42.9% |
| needle-03 | 135 / 1.0 | 135 / 1.0 | 119 / 0.0 | sufficient | 11.9% |
| org-04 | 130 / 1.0 | 130 / 1.0 | 77 / 1.0 | sufficient | 40.8% |
| escalate-05 | 71 / 1.0 | 71 / 1.0 | 56 / 1.0 | escalate | 21.1% |
| chain-06 | 115 / 1.0 | 104 / 0.5 | 71 / 1.0 | sufficient | 38.3% |
| budget-07 | 106 / 1.0 | 106 / 1.0 | rejected (max_tokens) | — | — |

## Findings

- **Selective DAG assembly carries fewer tokens than stuffing while preserving fixture fact coverage** where the gold facts ride on relevant/uncertain records (arcade-01, clinic-02, org-04, chain-06).
- **Uniform linear summaries lose mid-text facts** by construction (head+tail window); the DAG keeps full record text for the records it selects.
- **Relevance-thresholded selection can drop a low-relevance needle (needle-03).** This is the documented trade-off of selective assembly: token savings versus recall. In production the terminal evaluator's abstain path plus an external coverage signal is the control for this failure mode; that loop is out of scope for this deterministic fixture.
- **Unresolved contradictions escalate** (escalate-05) — the DAG refuses to silently ship conflicting records.
- **Budgets fail closed** (budget-07): the run is rejected with ``BudgetExceeded`` rather than truncated.
- **Every compiled artifact verifies and replays deterministically** (digest-stable across repeated compiles).

## Reproduce

```
python3 benchmark/context_dag/run.py
```

results digest: `ef5591b9acc71615826b0ab1b264294c2099552ad31a0f45f9c99458c6080282`

