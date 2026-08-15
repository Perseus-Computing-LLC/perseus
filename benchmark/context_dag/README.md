# Context-assembly comparison — pinned tasks (direct vs linear vs DAG)

Evaluation for [perseus#962](https://github.com/Perseus-Computing-LLC/perseus/issues/962)
(auditable context-compilation DAG, AGoT 2502.05078 + CISC 2502.06233).
Deterministic, provider-free run over a frozen synthetic task set
(`dataset.json`). Everything reruns byte-identically:

```bash
python3 benchmark/context_dag/run.py   # regenerates results.json + report.md
```

## Arms

| Arm | Definition |
|---|---|
| **direct** | Every record stuffed into context — the uniform-stuffing baseline. |
| **linear** | Every record uniformly summarized to a fixed head+tail window (70 chars) — the linear-summary baseline per AGoT adoption guidance. |
| **dag** | Selective, budgeted DAG compilation via `perseus.compile_context_dag`: a deterministic relevance/uncertainty-aware fetcher expands only relevant (≥0.5), uncertain, contradictory, or policy branches; hard budgets fail closed; terminal evaluator emits sufficient/abstain/escalate. |

## Metrics

- **tokens** — `dag_tokens` (chars//4, ceil): rendered estimate for budget
  accounting. *Derived, not provider billing.*
- **coverage** — fraction of task `facts` (answer-bearing substrings) present
  verbatim in the assembled packet. *Synthetic reference: fixture-derived
  fact presence, not model accuracy.*
- **verdict** — DAG terminal evaluator output.
- **replay determinism** — the compiled artifact digest must be identical
  across repeated compiles; every artifact must pass
  `verify_compiled_dag`.

## Claim boundary

This benchmark establishes assembly-layer *shape* — budget enforcement,
versioning, replay, verdict gating, and the token/coverage trade-off of
selective compilation on pinned synthetic fixtures. It does **not** establish
provider-run token efficiency, accuracy against a contamination-proof holdout,
or any leaderboard comparison. That is the scope of the Context-Bench run
([#961](https://github.com/Perseus-Computing-LLC/perseus/issues/961)), which
uses this instrumented assembly path.

See `report.md` for the current numbers and findings.
