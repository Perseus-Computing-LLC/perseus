# Perseus Gauntlet v2 — Methodology

**Version:** 2.0.0  
**Date:** 2026-06-19  
**Perseus version tested:** v1.0.8  

## Abstract

The Perseus Gauntlet is a comprehensive benchmark harness that measures a
Perseus deployment across four dimensions: render speed, memory retrieval
accuracy, agent task completion, and long-term stability. The Gauntlet
produces a single composite score (0–100) and a PASS/FAIL certification.

The Gauntlet is fully reproducible. Anyone can run it against their own
Perseus deployment. All source code lives in `benchmark/gauntlet/v2/`.

## Score

| Metric | Result |
|--------|--------|
| **Composite Score** | **100.0 / 100** |
| Certification | PASS ★★★★★ |
| Phases | 10 |
| Gates passed | 16 / 16 active |
| Gates skipped | 0 |

## The 10 Phases

Each phase targets a specific dimension of Perseus's behavior
under load. Hard gates must pass; soft gates surface warnings.

| # | Phase | Duration | What it measures |
|---|------|----------|------------------|
| 0 | **Pre-Flight** | ~5 min | Environment sanity: Perseus version, vault populated, NFS/lock health |
| 1 | **Render: Cold Baseline** | ~9 min | Raw render speed across 50+ role profiles. P50 must be ≤ 500 ms. |
| 2 | **Render: Warm/Cache** | ~3 min | Cache hit rates, warm speedup over cold baseline, cache integrity 100% |
| 3 | **Memory: Retrieval** | ~10 min | Mnēmē FTS5 precision/recall, P50 cold ≤ 50 ms, P50 warm ≤ 5 ms |
| 4 | **Agent: Single Task** | ~20 min | Hermetic coding tasks against a pre-seeded codebase. Success rate ≥ 90%. |
| 5 | **Agent: Multi-Agent** | ~20 min | Parallel agent coordination (kanban-style). Throughput ≥ 5 tasks/min, success ≥ 80%. |
| 6 | **Enterprise Week** | ~81 min | 5-day simulation with chaos injection. Zero failures. |
| 7 | **Adversarial** | ~60 min | 12+ hostile scenarios: unterminated macros, shell injection, checkpoint lock poisoning, FTS5 injection, SSRF probes. All must pass. |
| 8 | **Sustained Torture** | ~120 min | 2-hour continuous load. RSS growth ≤ 5%, error rate ≤ 0.01%. |
| 9 | **Token Efficiency** | ~22 sec | Compression ratio ≤ 1.0 (no inflation). Verifies Perseus doesn't bloat context windows. |

## Scoring Model

The composite score is a weighted average across four dimensions:

| Dimension | Weight | What gates contribute |
|-----------|--------|-----------------------|
| **Render** | 25% | Cold P50, warm speedup, cache integrity |
| **Memory** | 25% | F1 recall, cold/warm P50 |
| **Agent** | 25% | Single-task success, multi-agent throughput |
| **Stability** | 25% | Enterprise week failures, adversarial passes, torture RSS/error rate |

Each gate contributes a 0–1 sub-score. The dimension score is the mean of
its gates. The composite is the weighted sum × 100.

A score ≥ 80 earns a PASS certification.

## Gate Definitions

Gates are binary checkpoints within each phase. **Hard gates** (16 of 16)
block certification on failure. **Soft gates** surface warnings but don't
block the score.

| Gate | Type | Threshold |
|------|------|-----------|
| NFS health check | Soft | healthy == True |
| Phase time budgets | Hard | Within budget |
| Phase 1: Zero failures | Hard | failures == 0 |
| Phase 1: Cold P50 ≤ 500ms | Hard | p50_s ≤ 0.5 |
| Phase 2: Warm speedup ≥ 2% | Hard | speedup ≥ 1.02 |
| Phase 2: Cache integrity 100% | Hard | corrupt == 0 |
| Phase 3: Mneme recall ≥ 80% | Hard | recall ≥ 0.8 |
| Phase 3: Mneme cold P50 ≤ 50ms | Hard | ≤ 50ms |
| Phase 4: Task success ≥ 90% | Hard | ≥ 0.9 |
| Phase 5: Multi-agent success ≥ 80% | Hard | ≥ 0.8 |
| Phase 6: Enterprise week zero failures | Hard | failures == 0 |
| Phase 7: Adversarial all pass | Hard | all scenarios complete |
| Phase 7: All adversarial scenarios complete | Hard | count == 12 |
| Phase 8: RSS growth ≤ 5% | Hard | ≤ 5% |
| Phase 8: Error rate ≤ 0.01% | Hard | ≤ 0.0001 |
| Phase 9: Compression ratio ≤ 1.0 | Hard | ≤ 1.0 |

## Reproducing the Gauntlet

### Prerequisites

- Python 3.10+
- pyyaml (`pip install pyyaml`)
- Perseus build artifact (`perseus.py`) at repo root or `/workspace/perseus/`
- A writable `/tmp/perseus-gauntlet/` directory (created automatically)

### Full run (~5.5 hours)

```bash
cd perseus-repo
python3 benchmark/gauntlet/v2/gauntlet_v2_orchestrator.py \
    --nodes local --duration full
```

### Smoke test (~30 minutes)

```bash
python3 benchmark/gauntlet/v2/gauntlet_v2_orchestrator.py \
    --nodes local --duration smoke
```

### Outputs

All results are written to `benchmark/gauntlet/v2/`:

| File | Description |
|------|-------------|
| `gauntlet_v2_results.json` | Per-phase metrics, gate results, timing data |
| `gauntlet_v2_report.md` | Human-readable summary with phase tables and gate results |
| `gauntlet_v2_score.txt` | Single-line score + PASS/FAIL |
| `gauntlet_v2_telemetry.ndjson` | Time-series telemetry for graphing |
| `gauntlet_v2_intermediate.json` | Checkpoint file for resuming interrupted runs |

### Interpreting failures

If a gate fails, the `gauntlet_v2_results.json` file contains the observed
value vs. the threshold. Common failures:

- **Cold P50 > 500ms**: Slow filesystem or network-attached storage.
  Re-run on local SSD.
- **Mneme recall < 80%**: Vault not seeded with enough documents.
  Run `perseus memory index rebuild` before the Gauntlet.
- **Adversarial failures**: Security regressions. Check the individual
  scenario output in the telemetry log.

## Historical Results

| Date | Perseus | Score | Notes |
|------|---------|-------|-------|
| 2026-06-15 | v1.0.7 | 100.0 | Initial Gauntlet v2, all 16 gates passed |
| 2026-06-19 | v1.0.8 | 100.0 | Re-verified with Mimir auto-discovery fix |

## Architecture

The Gauntlet is a single-orchestrator, multi-node design:

```
gauntlet_v2_orchestrator.py    ← Main entry, phase scheduling
├── gauntlet_v2_lib.py         ← Metrics, gates, telemetry, scoring
├── gauntlet_v2_memory.py      ← Mnēmē FTS5 benchmarks (phase 3)
├── gauntlet_v2_agent.py       ← Agent task scaffolding (phases 4-5)
├── gauntlet_v2_adversarial.py ← Hostile scenario engine (phase 7)
└── gauntlet_v2_node.py        ← Multi-node coordination (phases 5-6)
```

Nodes communicate via NFS sentinel files. The local node writes probes
to a shared directory; remote nodes (not yet implemented) poll for them.
This design keeps the Gauntlet language-agnostic — any Perseus deployment
can participate.

## Competitive context

The Gauntlet is, to our knowledge, the only open benchmark for
pre-session context engines. No direct competitor publishes comparable
numbers. The methodology is designed to be adversarial — the 12 hostile
scenarios in Phase 7 probe the same attack surfaces a red team would.
This distinguishes Perseus from marketing benchmarks that only measure
happy-path performance.
