# Perseus PACMS pooled-selection benchmark (#970)

A **reproducible, fully offline** evaluation of the pluggable submodular
selection engine over the pooled context. Each scenario plants
ground-truth-relevant candidates (memory entries, tool outputs, session
turns) under recent-but-irrelevant noise with a budget ≤ 50% of the pooled
tokens, and the harness gates that the `submodular_greedy` policy keeps every
required candidate while the `recent_first` recency-truncation baseline is
measured to show the failure mode this engine replaces.

## Run it

```bash
python scripts/build.py                     # ensure perseus.py is in sync with src/
python benchmark/pooled-selection/run.py    # score, write results/report, gate
```

Exit code is **non-zero** when a gate fails, so CI can block a regression:

| gate | requirement |
|---|---|
| kept-set recall | submodular policy keeps 100% of ground-truth-required candidates at ≤ 50% budget |
| budget hardness | `tokens_used <= budget_tokens` on every scenario |
| replay-first | every selection trace re-verifies (`verify_selection_trace`) |
| baseline contrast | recent-first recall is reported for comparison (not gated) |

## What this measures

The selection-quality gate on a multi-turn corpus — the scenario PACMS
([arXiv:2606.20047](https://arxiv.org/abs/2606.20047)) identifies as the
defining failure of recency truncation: old-but-relevant facts are dropped
while verbose irrelevant recent material survives. End-to-end task success
against a full-context baseline requires a live LLM evaluation and stays out
of this offline gate; the harness pins the deterministic selection mechanism
the same way the tier-selection gate (`benchmark/selection/`) pins directive
tiering.

## The corpus

[`dataset.json`](./dataset.json) — 12 multi-turn scenarios across the three
pooled kinds (`session_turn`, `memory_entry`, `tool_output`), each with
hand-authored ground-truth required candidates independent of the engine, so
a regression in relevance scoring, coverage weighting, or budget handling
shows up here rather than shipping.
