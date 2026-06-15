# Perseus Gauntlet v2 — Final Report

**Version:** 2.0.0
**Date:** 2026-06-11T10:41:14.564729+00:00

## Summary

| Metric | Result |
|--------|--------|
| Phases | 10 |
| Gates passed | 15/16 active |
| Gates skipped | 0 |
| Overall | **FAIL** |

**Host:** hermes-webui
**Perseus:** perseus v1.0.7 — Patent Pending
**Nodes:** ['local']
**Duration:** full

## Phase Results

| # | Phase | Duration | Failures | Success Rate | Key Metric |
|---|------|----------|----------|-------------|------------|
| 0 | Pre-Flight | 0s | 0 | 100.0% | ? |
| 1 | Render: Cold Baseline | 14m | 0 | 100.0% | 0.753 |
| 2 | Render: Warm/Cache | 5m | 0 | 100.0% | 0.624 |
| 3 | Memory: Retrieval | 0s | 0 | 100.0% | ? |
| 4 | Agent: Single Task | 6s | 0 | 100.0% | 0.610 |
| 5 | Agent: Multi-Agent | 6s | 0 | 100.0% | 1.255 |
| 6 | Enterprise Week | 128m | 0 | 100.0% | 0.513 |
| 7 | Adversarial | 60m | 0 | 100.0% | ? |
| 8 | Sustained Torture | 120m | 0 | 100.0% | 0.493 |
| 9 | Token Efficiency | 32s | 0 | 0.0% | 1.000 |

## Gate Results

| Gate | Pass | Observed | Threshold | Severity |
|------|------|----------|-----------|----------|
| NFS health check | ✅ | {'healthy': True, 'path': '/mnt/perseus-gauntlet', 'mode': 'local'} | healthy == True | soft |
| Phase time budgets | ✅ | all phases within time budget | within_time_budget == True | hard |
| Phase 1: Zero failures (cold baseline) | ✅ | 0 | failures == 0 | hard |
| Phase 1: Cold P50 <= 500ms | ❌ | 0.7534713745117188 | p50_s <= 0.5 | hard |
| Phase 2: Warm speedup >= 2% | ✅ | 1.207 | speedup >= 1.02 | hard |
| Phase 2: Cache integrity 100% | ✅ | 0 | corrupt == 0 | hard |
| Phase 3: Mneme recall >= 80% | ✅ | 0.867 | recall >= 0.8 | hard |
| Phase 3: Mneme cold P50 <= 50ms | ✅ | 0.758 | <= 50ms | hard |
| Phase 4: Task success >= 90% | ✅ | 1.0 | >= 0.9 | hard |
| Phase 5: Multi-agent success >= 80% | ✅ | 1.0 | >= 0.8 | hard |
| Phase 6: Enterprise week zero failures | ✅ | 0 | failures == 0 | hard |
| Phase 7: Adversarial all scenarios pass | ✅ | True | True | hard |
| Phase 7: All adversarial scenarios complete | ✅ | 12 | all complete | hard |
| Phase 8: RSS growth <= 5% | ✅ | -1.464856874076065 | <= 5% | hard |
| Phase 8: Error rate <= 0.01% | ✅ | 0 | <= 0.0001 | hard |
| Phase 9: Compression ratio <= 1.0 (no inflation) | ✅ | 1.0 | <= 1.0 | hard |

## Score: 94.2/100

★★★★☆ — FAIL
