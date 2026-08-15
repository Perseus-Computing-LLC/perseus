# Context-compilation DAG (#962)

Auditable, budgeted context compilation as a typed, versioned directed acyclic
graph. Implementation: `src/perseus/context_dag.py`. Evaluation:
`benchmark/context_dag/`.

## Why

The context engine assembles packets, but the assembly itself has never been a
replayable artifact — there is no answer to "why did item X make the final
packet". AGoT ([arXiv:2502.05078](https://arxiv.org/abs/2502.05078)) shows
selective DAG expansion beats uniform stuffing on reasoning tasks, but its
edges and complexity labels are LLM-generated, so a self-confirming graph can
make an unsupported record look well-supported. Perseus compiles context with
immutable, content-derived IDs and versioned, typed edges so the graph cannot
drift from the evidence it explains.

## Model

- **Node kinds** — `requirement` (the task), `retrieved_record` (evidence),
  `summary` (derived), `contradiction` (conflict), `policy_constraint`
  (governance), `tool_output` (instrument), `decision` (conclusion).
- **Edge kinds** — `supports`, `depends_on`, `contradicts`, `invalidates`,
  `selected_for`.
- **Immutable IDs** — node ID = SHA-256 over kind + content hash + canonical
  evidence + version; edge ID = SHA-256 over kind + endpoints + version +
  meta. Identical evidence lands on the same ID; any drift produces a new ID
  or a hard collision error.
- **Versioned subgraphs** — `ContextDAG.fork_version()` bumps the version
  while sharing nodes/edges; `subgraph()` extracts a linked subgraph carrying
  the parent digest. `ContextDAG.digest()` seals the whole graph.

## Selective expansion

Expansion is layer-wise and selective. A branch is expanded only when it is:

- uncertain (`low` / `inferred` / `stale` / `tie`), or
- a contradiction, or
- high-impact by kind (`requirement`, `policy_constraint`, `decision`).

Confident, verified evidence is carried as-is and never re-fetched
(`should_expand`). Each branch is fetched at most once per compilation.

## Hard budgets (fail closed)

`CompilationBudget` enforces `max_nodes`, `max_depth`, `max_fanout`,
`max_tokens`, and a wall-clock `deadline_s`. Any breach raises
`BudgetExceeded` — a compilation is rejected rather than silently truncated.
Token accounting is the rendered `dag_tokens` estimate (chars//4); it is
**not** provider-billed savings.

## Terminal evaluator

`evaluate_compilation` maps (advisory hint, gaps, contradictions) to
`sufficient` | `abstain` | `escalate`. The advisory hint (and optional CISC
confidence) is a model input; deterministic gates override it, fail-closed:

1. unresolved contradictions → **escalate** (needs a resolver, not a vote);
2. policy gaps (policy_constraint without a `policy_ref`) → **abstain**;
3. provenance gaps (unverified inferred/stale records) → **abstain**;
4. only then is the advisory hint honored.

`CompilationPolicy.requires_verified` widens the provenance gate to every
unverified, non-observed node.

## CISC prioritization (behind evidence gates)

`cisc_prioritize` (arXiv:2502.06233) ranks candidate paths by
confidence-weighted vote. Confidence is *uncalibrated model self-confidence* —
a review-effort heuristic, never an evidence substitute. Every winner must
pass `apply_evidence_gate`: every path node verified/observed, no unresolved
contradiction, no policy/provenance gap — otherwise the gate abstains.

## Compiled artifact

`compile_context_dag(task_id, root, fetch, budget, policy, verdict_hint)`
builds, expands, and seals:

```jsonc
{
  "schema_version": "perseus-context-dag/v1",
  "compiled_digest": "...",   // seals packet + verdict + advisory + policy + budget + graph
  "graph": {...},             // full typed, versioned graph with its own digest
  "selected_node_ids": [...],
  "packet": [...],            // ordered nodes — links back to the exact subgraph
  "verdict": {...},           // terminal verdict + reason + overrides
  "advisory": {...},          // sealed advisory inputs (replay fidelity)
  "policy": {...},            // sealed policy knobs
  "budget": {...}             // consumption report + limits
}
```

`verify_compiled_dag` recomputes every commitment (including the verdict from
graph state); `render_compiled_dag` replays the packet deterministically.
Timestamps and wall-clock are recorded but excluded from digests, so repeated
compiles of the same inputs are byte-identical.

## Evaluation (pinned tasks)

`benchmark/context_dag/` compares **direct** (stuff all) vs **linear**
(uniform summaries) vs **dag** (selective + budgeted) on a frozen synthetic
task set. Metrics: rendered tokens, synthetic-reference fact coverage,
terminal verdicts, replay determinism, and a fail-closed budget-rejection
task. Findings so far: selective DAG assembly carries ~30% fewer tokens than
stuffing while preserving fixture facts where gold facts ride on
relevant/uncertain records; uniform linear summaries lose mid-text facts for
almost no savings; low-relevance needles can be dropped by relevance
thresholding (production control = the evaluator's abstain path plus an
external coverage signal); unresolved contradictions escalate; budgets fail
closed. Coverage is a *synthetic reference* — provider-run efficacy belongs to
the Context-Bench run (#961), which uses this instrumented path.

## API surface

- `ContextNode`, `ContextEdge`, `ContextDAG` — typed, versioned graph types.
- `CompilationBudget`, `BudgetLedger`, `BudgetExceeded` — hard budgets.
- `should_expand`, `evaluate_compilation` — policy + terminal gates.
- `cisc_prioritize`, `apply_evidence_gate` — optional CISC arm.
- `compile_context_dag`, `verify_compiled_dag`, `render_compiled_dag` —
  compile / verify / replay.
- `dag_tokens` — rendered token estimate.
