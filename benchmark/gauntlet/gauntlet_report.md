# Perseus Gauntlet — Final Report

**Version:** 1.0.0
**Date:** 2026-06-02T16:24:53.315971+00:00

## Summary

| Metric | Result |
|--------|--------|
| Phases | 12 |
| Gates passed | 8/14 active |
| Gates skipped | 1 |
| Overall | **FAIL** |

**Host:** 94aaa147beae
**Perseus:** perseus v1.0.5 — Patent Pending
**Developers per node:** 500
**Nodes:** ['local']

## Phase Results

| # | Phase | Duration | Failures | Success Rate | Key Metric |
|---|------|----------|----------|-------------|------------|
| 0 | Pre-Flight | 0s | 0 | 100.0% | 0.00s |
| 1 | Baseline Cold | 15m | 0 | 100.0% | 0.49s |
| 2 | Warm Baseline | 6m | 1 | 99.8% | 0.47s |
| 3 | Enterprise Week | 94m | 2 | 100.0% | 0.49s |
| 4 | Agora Swarm | 15m | 0 | 100.0% | 0.44s |
| 5 | Checkpoint Relay | 14m | 0 | 100.0% | 0.42s |
| 6 | Inbox Storm | 15m | 0 | 100.0% | 0.44s |
| 7 | adversarial-gauntlet | 119m | 0 | 100.0% | ? |
| 8 | Semantic Integrity | 0s | 0 | 100.0% | ? |
| 9 | Token Efficiency | 9s | 0 | 100.0% | ? |
| 10 | Sustained Torture | 120m | 0 | 100.0% | 0.42s |
| 11 | Final Report | 0s | 0 | 100.0% | ? |

## Gate Results (8/14 active passed; 1 skipped)

| Gate | Pass | Observed | Threshold | Severity |
|------|------|----------|-----------|----------|
| NFS health check | ✅ | {"healthy": true, "path": "/tmp/perseus-gauntlet", "mode": "local-tmp"} | healthy == True | soft |
| Phase time budgets | ❌ | [{"phase": 7, "name": "adversarial-gauntlet", "duration_s": 7161.414, "max_duration_s": 3600, "over_by_s": 3561.414}, {"phase": 10, "name": "Sustained Torture", "duration_s": 7202.015, "max_duration_s": 7200, "over_by_s": 2.015}] | within_time_budget == True | hard |
| Phase 1: Zero failures (cold baseline) | ✅ | 0 | failures == 0 | hard |
| Phase 2: Warm not slower than cold (5% tolerance) | ✅ | 1.2 | speedup >= 0.95 | hard |
| Phase 3: Enterprise week zero failures | ❌ | 2 | failures == 0 | hard |
| Phase 4: Agora swarm collision_rate == 0.0 | ✅ | 0.0 | == 0.0 | hard |
| Phase 5: Checkpoint zero corruption | ❌ | no data (hard gate requires data) | corrupt == 0 | hard |
| Phase 6: Inbox delivery >= 99.9% | ✅ | 1.0 | >= 0.999 | hard |
| Phase 7: Adversarial overall_pass | ❌ | false | True | hard |
| Phase 7: All adversarial scenarios complete | ✅ | 12 | 12 scenarios | hard |
| Phase 8: Semantic integrity overall_pass | SKIP | skipped: Requires GOOGLE_API_KEY | True | hard |
| Phase 9: Compression ratio <= 1.0 (no inflation) | ❌ | 1.048048780487805 | <= 1.0 | hard |
| Phase 9: P99 overhead < 5ms (stub) | ✅ | 0 | < 5ms | hard |
| Phase 10: RSS growth <= 5% | ❌ | 26.427369601794727 | <= 5% | hard |
| Phase 10: Error rate <= 0.01% | ✅ | 0 | <= 0.0001 | hard |

## Score: 0.0/100

★☆☆☆☆ — Critical failures.
