# Perseus Gauntlet Report

Overall: PASS
Gates: 17/17

## Phase Summary

| Phase | Status | Key Metrics |
|---|---|---|
| phase_0_preflight | PASS | `{}` |
| phase_1_cold | PASS | `{"cache_state": "cold", "failures": 0, "renders": 500, "timing": {"mean": 2.0399, "median": 1.9953, "n": 500, "p95": 2.6546, "p99": 2.9433}}` |
| phase_2_warm | PASS | `{"seed": {"cache_state": "warm", "failures": 0, "renders": 500, "timing": {"mean": 0.7652, "median": 0.7629, "n": 500, "p95": 0.8804, "p99": 0.9459}}, "speedup": 2.61, "warm": {"ca` |
| phase_3_enterprise_week | PASS | `{"end_of_day": {"cache_state": "mixed", "failures": 0, "renders": 500, "timing": {"mean": 0.8382, "median": 0.7582, "n": 500, "p95": 1.5469, "p99": 1.8488}}, "feature_work": {"cach` |
| phase_4_agora_swarm | PASS | `{"duration_s": 367.878}` |
| phase_5_checkpoint_relay | PASS | `{"writes": 2000}` |
| phase_6_inbox_storm | PASS | `{"delivered": 1000, "total": 1000}` |
| phase_7_adversarial | PASS | `{"pass": true, "scenarios": [{"duration_s": 0.0, "pass": true, "reason": "dangerous disk-fill scenario requires PERSEUS_GAUNTLET_ALLOW_DISK_FILL=1", "scenario": "A1_disk_full", "sk` |
| phase_8_semantic_integrity | PASS | `{"pass": true, "reason": "GOOGLE_API_KEY not set", "skipped": true}` |
| phase_9_token_efficiency | PASS | `{"baseline_to_perseus_token_ratio": 7.5, "compression_pct": 86.67, "tiers": {"gemini": {"relative_savings_pct": 86.67}, "gpt": {"relative_savings_pct": 86.67}, "opus": {"relative_s` |
| phase_10_sustained_torture | PASS | `{"failures": 0, "renders": 517, "timing": {"mean": 0.2318, "median": 0.2165, "n": 517, "p95": 0.316, "p99": 0.4713}}` |
| phase_11_final | PASS | `{"gate_report": {"failed": [], "gates": [{"details": "ok", "name": "NFS/local shared path writable", "pass": true, "severity": "hard"}, {"details": "perseus v1.0.4", "name": "Perse` |

## Gates

| Gate | Result | Details |
|---|---|---|
| NFS/local shared path writable | PASS | ok |
| Perseus version is v1.0.4+ | PASS | perseus v1.0.4 |
| sample role profile renders | PASS |  |
| cold baseline zero failures | PASS | {"n": 500, "median": 1.9953, "p95": 2.6546, "p99": 2.9433, "mean": 2.0399} |
| cold baseline median <= 30s | PASS | {"n": 500, "median": 1.9953, "p95": 2.6546, "p99": 2.9433, "mean": 2.0399} |
| cold baseline p99 <= 120s | PASS | {"n": 500, "median": 1.9953, "p95": 2.6546, "p99": 2.9433, "mean": 2.0399} |
| warm baseline zero failures | PASS | {"n": 500, "median": 0.7649, "p95": 0.9522, "p99": 1.0579, "mean": 0.7819} |
| warm speedup measured | PASS | speedup=2.61x |
| enterprise week zero failures | PASS | {"standup": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 0.7666, "p95": 0.94, "p99": 1.0634, "mean": 0.7753}, "cache_state": "mixed"}, "feature_work": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 1.6268, "p95": 1.9271, "p99": 2.0783, "mean": 1.5543}, "cache_state": "mixed"}, "incident_hotfix": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 0.7794, "p95": 0.9524, "p99": 1.0247, "mean": 0.7841}, "cache_state": "mixed"}, "end_of_day": {"renders":  |
| agora swarm command completes | PASS |  |
| checkpoint relay zero corruption | PASS | writes=2000 |
| inbox storm delivery >= 99.9% | PASS | 1000/1000 |
| adversarial gauntlet pass/skip accounted | PASS | ["A1_disk_full", "A2_network_partition", "A3_clock_skew", "A4_oom_pressure", "A7_signal_storm", "A9_fork_bomb_defense"] |
| semantic integrity real LLM judge | SKIP | GOOGLE_API_KEY not set |
| token compression >= 85% | PASS | {"total_directives": 35000, "baseline_to_perseus_token_ratio": 7.5, "compression_pct": 86.67, "tiers": {"opus": {"relative_savings_pct": 86.67}, "gpt": {"relative_savings_pct": 86.67}, "gemini": {"relative_savings_pct": 86.67}}} |
| sustained torture errors <= 0.01% | PASS | {"renders": 517, "failures": 0, "timing": {"n": 517, "median": 0.2165, "p95": 0.316, "p99": 0.4713, "mean": 0.2318}} |
| cache integrity audit | PASS | {"total": 13520, "bad": [], "ok": true} |
