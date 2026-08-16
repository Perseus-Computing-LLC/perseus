# Trajectory-mined context-source failure attribution (#968)

Automated diagnosis for the context engine: mine agent trajectories for
implicit dissatisfaction (corrections, rephrasing, abandonment), attribute
each failure to the context source that caused it, and classify the
remediation as CREATE vs UPDATE **before** any patch is proposed. Borrows
TRACE's trajectory-mining + multi-component causal attribution loop
([arXiv:2608.09153](https://arxiv.org/abs/2608.09153)) and adapts it to
Perseus's source types. Implementation: `src/perseus/trace_attribution.py`.
Evaluation: `benchmark/trace/`.

## Why

When agent behavior fails, there was no automated way to tell which context
source is defective — maintenance was manual log review. Attribution answers
*where* (which source, which spans), complementing the preflight scoring
layer that answers *how bad* (#969), and feeding remediation of the exact
defective span instead of wholesale rewrites.

## Model

- **Trajectory records** — typed steps (`user_message`, `agent_message`,
  `tool_call`, `tool_result`, `attempt_boundary`, `dissatisfaction`), each
  with a stable content-derived `step_id`.
- **Context sources** — `system_prompt`, `knowledge_base`, `tool_schema`,
  `skill`, `guardrails`; each source is split into canonical spans
  (paragraphs) with immutable span IDs, so a diagnosis can cite *which part*
  of a source is defective.
- **Signals** — deterministic mining, no explicit feedback collection:
  `correction` (cue-opening user message after an agent/tool step),
  `rephrasing` (repeated request across an intervening agent step),
  `abandonment` (run ends on a failing tool result or abort cue), `explicit`
  (structured injection for externally-annotated corpora).
- **Attribution** — textual-gradient-style pass over heterogeneous sources:
  evidence tokens from each signal are matched (stopword-filtered,
  stem-tolerant) against each source's spans; the top source is the
  diagnosis when it clears the shared-token threshold, otherwise the
  diagnosis is `inconclusive` and **no patch is proposed**.
- **CREATE vs UPDATE** — the exploratory-verification step re-reads the
  evidence against the candidate source. Evidence that lands on existing
  spans with the source explaining it (shared > novel tokens) → `update`
  (present but defective/stale); evidence that introduces novel content or
  targets a missing source type → `create`. Negation evidence that
  contradicts an affirmed source claim forces `update` with the
  `contradiction` fault category.

## Fault taxonomy (adapted to Perseus source types)

`content_gap` | `stale_content` | `contradiction` | `missing_tool` |
`tool_schema_defect` | `guardrail_gap`

## Fail-closed and replay-first

- Inconclusive attribution → no remediation proposal, only the diagnosis.
- An optional `reading_agent` (the paper's exploratory-verification step)
  may confirm weak classifications but can never flip a decisive
  deterministic verdict — same advisory-input discipline as the DAG's
  `verdict_hint`.
- `run_trace_analysis` emits a versioned, digest-sealed report;
  `verify_trace_report` recomputes every commitment. Every diagnosis cites
  signal IDs, evidence step IDs, and source span IDs.

## Evaluation

`benchmark/trace/run.py` — offline, deterministic; gates: attribution top-1
≥ 70% (paper baseline 72.7%), CREATE/UPDATE ≥ 90% (paper baseline 96%),
cross-layer verification with zero errors. The corpus is 36 planted-fault
episodes across all six categories with hand-authored ground truth.
