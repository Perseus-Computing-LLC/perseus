# Perseus context-quality preflight discrimination benchmark (#969)

A **reproducible, fully offline** evaluation of the 7-criteria context-quality
measurement layer: a healthy baseline context and degraded twins (one per
criterion, plus a multi-fault sample) are scored by the deterministic jury
harness, and the harness gates that every degraded sample scores strictly
below the baseline on its target criterion **and** is blocked by the preflight
gate, while the healthy baseline passes.

## Run it

```bash
python scripts/build.py                    # ensure perseus.py is in sync with src/
python benchmark/context-quality/run.py    # score, write results/report, gate
```

Exit code is **non-zero** when any gate fails, so CI can block a regression:

| gate | requirement |
|---|---|
| criterion monotonicity | every degraded sample scores strictly below baseline on its target criterion |
| preflight blocking | every degraded sample is blocked, with the degraded criterion among the blocked set |
| preflight selectivity | the healthy baseline passes |
| replay-first | every report re-verifies from its payload |

## What this measures

Criterion monotonicity is the offline analog of the paper's
criteria→outcome predictability study (arXiv:2607.14275): instead of holding
frontier agents fixed and varying context to observe behavioral outcomes, the
corpus holds the scorer fixed and varies context to verify each criterion
responds in the right direction to a planted defect. The behavioral study
itself requires live LLM evaluation and stays out of this offline gate; the
harness deliberately shares the isolation property — scores depend only on
context content, never on behavioral metrics.

## The corpus

[`dataset.json`](./dataset.json) — a healthy baseline plus seven single-fault
degraded twins (one per criterion) and one multi-fault sample. Defects are
hand-authored and independent of the scorers, so a regression in any jury
shows up here rather than shipping.
