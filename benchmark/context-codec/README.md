# Perseus Context Codec benchmark (#971)

A **reproducible, fully offline** evaluation of commitment-preserving
verifiable compression: each long-session corpus entry plants typed semantic
commitments (goals, constraints, decisions, preferences, tool results,
evidence, safety boundaries), and the harness gates that extraction recovers
them, compression preserves them, and the fail-closed path restores the
original whenever preservation cannot be certified.

## Run it

```bash
python scripts/build.py                 # ensure perseus.py is in sync with src/
python benchmark/context-codec/run.py   # score, write results/report, gate
```

Exit code is **non-zero** when a gate fails, so CI can block a regression:

| gate | requirement |
|---|---|
| extraction | every planted commitment type is recovered (at minimum the declared critical/safety counts) |
| Critical Atom Recall | = 1.0 on the deterministic path (gate ≥ 0.99, the issue's success criterion) |
| Weighted Atom Recall | ≥ 0.99 |
| safety boundaries | zero lost — never compressed lossily |
| round-trip recoverability | = 1.0 per compaction event |
| fail-closed | an injected lossy compressor (drops the commitment table) reverts to the original text on every session |
| replay-first | every compaction report re-verifies from its inputs |

## The corpus

[`dataset.json`](./dataset.json) — 5 long-session entries across deployment,
operations, compliance, data-engineering, and security personas, each with
hand-authored planted commitments and ground-truth counts, plus body noise
(duplicate lines) that exercises the deterministic body compression.
