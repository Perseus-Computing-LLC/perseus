# Perseus Gauntlet Report

Overall: FAIL
Gates: 15/17

## Phase Summary

| Phase | Status | Key Metrics |
|---|---|---|
| phase_0_preflight | PASS | `{}` |
| phase_1_cold | PASS | `{"cache_state": "cold", "failures": 0, "renders": 500, "timing": {"mean": 1.9276, "median": 1.8905, "n": 500, "p95": 2.6868, "p99": 3.0624}}` |
| phase_2_warm | PASS | `{"seed": {"cache_state": "warm", "failures": 0, "renders": 500, "timing": {"mean": 1.0288, "median": 0.9602, "n": 500, "p95": 1.6353, "p99": 1.9532}}, "speedup": 1.98, "warm": {"ca` |
| phase_3_enterprise_week | PASS | `{"end_of_day": {"cache_state": "mixed", "failures": 0, "renders": 500, "timing": {"mean": 1.0512, "median": 0.9522, "n": 500, "p95": 1.9103, "p99": 2.1877}}, "feature_work": {"cach` |
| phase_4_agora_swarm | PASS | `{"duration_s": 424.82}` |
| phase_5_checkpoint_relay | FAIL | `{"writes": 0}` |
| phase_6_inbox_storm | FAIL | `{"delivered": 0, "total": 1000}` |
| phase_7_adversarial | PASS | `{"pass": true, "scenarios": [{"duration_s": 0.001, "pass": true, "reason": "dangerous disk-fill scenario requires PERSEUS_GAUNTLET_ALLOW_DISK_FILL=1", "scenario": "A1_disk_full", "` |
| phase_8_semantic_integrity | PASS | `{"pass": true, "reason": "GOOGLE_API_KEY not set", "skipped": true}` |
| phase_9_token_efficiency | PASS | `{"baseline_to_perseus_token_ratio": 7.5, "compression_pct": 86.67, "tiers": {"gemini": {"relative_savings_pct": 86.67}, "gpt": {"relative_savings_pct": 86.67}, "opus": {"relative_s` |
| phase_10_sustained_torture | PASS | `{"failures": 0, "renders": 498, "timing": {"mean": 0.2404, "median": 0.217, "n": 498, "p95": 0.3659, "p99": 0.5809}}` |
| phase_11_final | FAIL | `{"gate_report": {"failed": ["checkpoint relay zero corruption", "inbox storm delivery >= 99.9%"], "gates": [{"details": "ok", "name": "NFS/local shared path writable", "pass": true` |

## Gates

| Gate | Result | Details |
|---|---|---|
| NFS/local shared path writable | PASS | ok |
| Perseus version is v1.0.4+ | PASS | perseus v1.0.4 |
| sample role profile renders | PASS | ration not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
perseus audit: write failed (PermissionError(1, 'Operation not permitted'))
 |
| cold baseline zero failures | PASS | {"n": 500, "median": 1.8905, "p95": 2.6868, "p99": 3.0624, "mean": 1.9276} |
| cold baseline median <= 30s | PASS | {"n": 500, "median": 1.8905, "p95": 2.6868, "p99": 3.0624, "mean": 1.9276} |
| cold baseline p99 <= 120s | PASS | {"n": 500, "median": 1.8905, "p95": 2.6868, "p99": 3.0624, "mean": 1.9276} |
| warm baseline zero failures | PASS | {"n": 500, "median": 0.957, "p95": 1.3678, "p99": 1.4792, "mean": 0.9961} |
| warm speedup measured | PASS | speedup=1.98x |
| enterprise week zero failures | PASS | {"standup": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 0.9027, "p95": 1.0758, "p99": 1.2449, "mean": 0.9073}, "cache_state": "mixed"}, "feature_work": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 1.8987, "p95": 3.4335, "p99": 3.8965, "mean": 1.9955}, "cache_state": "mixed"}, "incident_hotfix": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 0.9104, "p95": 1.5204, "p99": 1.9418, "mean": 0.9935}, "cache_state": "mixed"}, "end_of_day": {"renders" |
| agora swarm command completes | PASS |  |
| checkpoint relay zero corruption | FAIL | writes=0 |
| inbox storm delivery >= 99.9% | FAIL | 0/1000 |
| adversarial gauntlet pass/skip accounted | PASS | ["A1_disk_full", "A2_network_partition", "A3_clock_skew", "A4_oom_pressure", "A7_signal_storm", "A9_fork_bomb_defense"] |
| semantic integrity real LLM judge | SKIP | GOOGLE_API_KEY not set |
| token compression >= 85% | PASS | {"total_directives": 35000, "baseline_to_perseus_token_ratio": 7.5, "compression_pct": 86.67, "tiers": {"opus": {"relative_savings_pct": 86.67}, "gpt": {"relative_savings_pct": 86.67}, "gemini": {"relative_savings_pct": 86.67}}} |
| sustained torture errors <= 0.01% | PASS | {"renders": 498, "failures": 0, "timing": {"n": 498, "median": 0.217, "p95": 0.3659, "p99": 0.5809, "mean": 0.2404}} |
| cache integrity audit | PASS | {"total": 13520, "bad": [], "ok": true} |
