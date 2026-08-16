# Perseus TRACE attribution benchmark (#968)

A **reproducible, fully offline** evaluation of trajectory-mined context-source
failure attribution — the diagnosis layer under front-door routing (#896) and
the auditable compilation DAG (#962). No network, no API key, no LLM: it
imports the built `perseus.py` and runs the deterministic
mine → attribute → classify → propose pipeline against a hand-authored
six-category fault corpus with ground-truth annotations.

## Run it

```bash
python scripts/build.py            # ensure perseus.py is in sync with src/
python benchmark/trace/run.py      # score, write results.json + report.md, gate
```

Exit code is **non-zero** when a gate fails, so CI can block an attribution
regression:

| gate | threshold | basis |
|---|---|---|
| attribution top-1 accuracy | ≥ 70% | paper baseline 72.7% (60 traces) |
| CREATE vs UPDATE accuracy | ≥ 90% | paper baseline 96% operation accuracy |
| cross-layer verification | zero errors | every diagnosis cites evidence steps; cited spans resolve; report re-verifies |

## The corpus

[`dataset.json`](./dataset.json) — 36 planted-fault episodes, 6 per category of
the adapted taxonomy (`tool_schema_defect`, `missing_tool`, `stale_content`,
`content_gap`, `contradiction`, `guardrail_gap`), across five source groups
(tool schemas, knowledge base, skills, system prompt, guardrails-absent). The
annotations are hand-authored ground truth, independent of the implementation,
so a regression in the miner, the attribution scoring, or the CREATE/UPDATE
classifier is caught here rather than shipped.

## What is measured

- **Attribution** — on UPDATE episodes, whether the top-ranked context source
  matches the planted source.
- **CREATE vs UPDATE** — whether the exploratory-verification classifier picks
  the correct remediation class for every episode.
- **Cross-layer verification** — every diagnosis must cite trajectory evidence
  steps, every cited span ID must resolve to a real source span, and the
  digest-sealed report must re-verify (`verify_trace_report`).

The gates measure the *deterministic mechanism* on the internal corpus, not
the paper's LLM-based numbers; the paper figures are the reference baselines
the thresholds are derived from.
