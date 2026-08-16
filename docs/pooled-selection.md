# Pooled submodular context selection (#970)

A pluggable selection engine that replaces topic-blind recency truncation:
conversation turns, memory entries, and tool outputs form one pooled
candidate set, and a submodular objective — relevance + relevance-weighted
coverage under a token budget, with diminishing returns — selects what
survives at prompt-assembly time. PACMS borrow
([arXiv:2606.20047](https://arxiv.org/abs/2606.20047)): neither RAG
(external docs only) nor lossy compression (query-blind) arbitrates the
agent's already-present pooled context; the selector does.
Implementation: `src/perseus/pooled_selection.py`. Evaluation:
`benchmark/pooled-selection/`.

## Model

- **Pooled candidates** — `session_turn`, `memory_entry`, `tool_output`,
  each with a stable content-derived ID. The pool is the *same* candidate
  set regardless of source.
- **Relevance** — deterministic, stem-tolerant lexical overlap between the
  candidate and the current query (`relevance_score`).
- **Objective** — `F(S) = Σ relevance(c) + λ · Σ relevance(c)·|new_tokens(c)|`.
  Coverage contributions are weighted by the candidate's own relevance, so
  a zero-relevance candidate can never be picked on coverage alone. The
  weighted coverage term is monotone submodular with diminishing returns,
  giving the greedy policy the classic (1-1/e) guarantee for the unit-cost
  case.
- **Greedy selection** — lazy-greedy marginal-gain maximization with stable
  tie-breaking on candidate ID: deterministic, byte-for-byte replayable.

## Pluggability

The engine ships three policies and a registry:

- `submodular_greedy` (default) — relevance + diminishing-returns coverage;
- `relevance_greedy` — relevance only (coverage ablation);
- `recent_first` — the recency-truncation baseline this engine replaces.

`register_policy(name, fn)` lets future policies (e.g. causal-evidence-
supervised pruning, arXiv:2607.21692) swap in with zero compiler changes.

## Provenance and budgets

- **Replay-first trace** — every selection emits a digest-sealed trace:
  what was kept (in pick order) and dropped (with reasons), per-step
  relevance, coverage gain, marginal gain, and the budget ledger.
  `verify_selection_trace` replays the selection; the trace feeds the #962
  auditable compilation DAG and efficiency-frontier analysis
  (arXiv:2605.23071).
- **Fail-closed budgets** — the token budget is a hard cap (enforced and
  verified). Candidates individually over budget are dropped with an
  explicit reason, never silently truncated.

## Evaluation

`benchmark/pooled-selection/run.py` — 12 multi-turn scenarios with planted
ground-truth-relevant candidates, budgets ≤ 50% of pooled tokens. Gate:
submodular recall = 100% (recency baseline measured at ~58% on the same
corpus — the exact failure mode PACMS describes), budget hardness, and
replay-first verification. End-to-end task-success parity vs a full-context
baseline requires live LLM evaluation and is deliberately out of this
offline gate.
