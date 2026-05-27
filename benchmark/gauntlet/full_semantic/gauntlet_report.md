# Perseus Gauntlet Report

Overall: FAIL
Gates: 15/17

## Phase Summary

| Phase | Status | Key Metrics |
|---|---|---|
| phase_0_preflight | PASS | `{}` |
| phase_1_cold | PASS | `{"cache_state": "cold", "failures": 0, "renders": 500, "timing": {"mean": 2.0331, "median": 2.035, "n": 500, "p95": 2.4041, "p99": 2.5123}}` |
| phase_2_warm | PASS | `{"seed": {"cache_state": "warm", "failures": 0, "renders": 500, "timing": {"mean": 0.9435, "median": 0.9373, "n": 500, "p95": 1.2141, "p99": 1.3477}}, "speedup": 2.27, "warm": {"ca` |
| phase_3_enterprise_week | PASS | `{"end_of_day": {"cache_state": "mixed", "failures": 0, "renders": 500, "timing": {"mean": 1.1093, "median": 1.0363, "n": 500, "p95": 1.994, "p99": 2.4644}}, "feature_work": {"cache` |
| phase_4_agora_swarm | PASS | `{"duration_s": 474.098}` |
| phase_5_checkpoint_relay | PASS | `{"writes": 2000}` |
| phase_6_inbox_storm | PASS | `{"delivered": 1000, "total": 1000}` |
| phase_7_adversarial | FAIL | `{"pass": false, "scenarios": [{"duration_s": 0.235, "filled_bytes": 63753420, "pass": true, "result": {"rc": 0, "stderr": "", "stdout_len": 26}, "scenario": "A1_disk_full", "simula` |
| phase_8_semantic_integrity | FAIL | `{"error": "HTTP Error 429: Too Many Requests", "model": "gemini-2.5-flash", "pass": false}` |
| phase_9_token_efficiency | PASS | `{"baseline_to_perseus_token_ratio": 7.5, "compression_pct": 86.67, "tiers": {"gemini": {"relative_savings_pct": 86.67}, "gpt": {"relative_savings_pct": 86.67}, "opus": {"relative_s` |
| phase_10_sustained_torture | PASS | `{"failures": 0, "renders": 588, "timing": {"mean": 0.2037, "median": 0.1896, "n": 588, "p95": 0.2821, "p99": 0.4115}}` |
| phase_11_final | FAIL | `{"gate_report": {"failed": ["adversarial gauntlet pass/skip accounted", "semantic integrity real LLM judge"], "gates": [{"details": "ok", "name": "NFS/local shared path writable", ` |

## Gates

| Gate | Result | Details |
|---|---|---|
| NFS/local shared path writable | PASS | ok |
| Perseus version is v1.0.4+ | PASS | perseus v1.0.4 |
| sample role profile renders | PASS |  |
| cold baseline zero failures | PASS | {"n": 500, "median": 2.035, "p95": 2.4041, "p99": 2.5123, "mean": 2.0331} |
| cold baseline median <= 30s | PASS | {"n": 500, "median": 2.035, "p95": 2.4041, "p99": 2.5123, "mean": 2.0331} |
| cold baseline p99 <= 120s | PASS | {"n": 500, "median": 2.035, "p95": 2.4041, "p99": 2.5123, "mean": 2.0331} |
| warm baseline zero failures | PASS | {"n": 500, "median": 0.896, "p95": 1.0831, "p99": 1.1667, "mean": 0.9032} |
| warm speedup measured | PASS | speedup=2.27x |
| enterprise week zero failures | PASS | {"standup": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 0.91, "p95": 1.2829, "p99": 1.8249, "mean": 0.9362}, "cache_state": "mixed"}, "feature_work": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 1.956, "p95": 2.5748, "p99": 3.3022, "mean": 1.9285}, "cache_state": "mixed"}, "incident_hotfix": {"renders": 500, "failures": 0, "timing": {"n": 500, "median": 0.9517, "p95": 1.2285, "p99": 1.3373, "mean": 0.9699}, "cache_state": "mixed"}, "end_of_day": {"renders": 5 |
| agora swarm command completes | PASS |  |
| checkpoint relay zero corruption | PASS | writes=2000 |
| inbox storm delivery >= 99.9% | PASS | 1000/1000 |
| adversarial gauntlet pass/skip accounted | FAIL | [] |
| semantic integrity real LLM judge | FAIL | {"pass": false, "error": "HTTP Error 429: Too Many Requests", "model": "gemini-2.5-flash"} |
| token compression >= 85% | PASS | {"total_directives": 35000, "baseline_to_perseus_token_ratio": 7.5, "compression_pct": 86.67, "tiers": {"opus": {"relative_savings_pct": 86.67}, "gpt": {"relative_savings_pct": 86.67}, "gemini": {"relative_savings_pct": 86.67}}} |
| sustained torture errors <= 0.01% | PASS | {"renders": 588, "failures": 0, "timing": {"n": 588, "median": 0.1896, "p95": 0.2821, "p99": 0.4115, "mean": 0.2037}} |
| cache integrity audit | PASS | {"total": 13520, "bad": [], "ok": true} |
