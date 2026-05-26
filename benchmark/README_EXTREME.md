# Perseus Extreme Enterprise Benchmark

**File:** `benchmark/extreme_enterprise_benchmark.py`  
**Outputs:** `extreme_enterprise_results.json` · `extreme_enterprise_report.txt`

---

## Purpose

This benchmark answers one question with no spin:

> **Does deploying Perseus into an enterprise AI-assistant environment make things faster and cheaper — and exactly under what conditions does it not?**

It is designed to be **radically honest**. Every phase where Perseus adds overhead rather than benefit is measured, flagged, and reported explicitly. Nothing is hidden, suppressed, or averaged away.

---

## Quick Start

```bash
# Full run (~15–25 min depending on hardware)
python3 benchmark/extreme_enterprise_benchmark.py

# Fast smoke run (~2 min, CI-friendly)
python3 benchmark/extreme_enterprise_benchmark.py --quick

# Skip optional slow phases
python3 benchmark/extreme_enterprise_benchmark.py \
    --skip-enterprise --skip-memory

# Custom scale
python3 benchmark/extreme_enterprise_benchmark.py \
    --reps 10 --dev-count 100
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--quick` | off | N_REPS=3, directives=[1,5,15,30], concurrency=[1,10,50], devs=10 |
| `--reps N` | 5 | Repetitions per measurement cell |
| `--dev-count N` | 50 | Developers in Phase 7 enterprise simulation |
| `--skip-enterprise` | off | Skip Phase 7 (saves ~5–10 min) |
| `--skip-memory` | off | Skip Phase 9 (requires psutil) |
| `--out PATH` | `extreme_enterprise_results.json` | JSON output path |
| `--report PATH` | `extreme_enterprise_report.txt` | Text report path |

---

## Design Principles

### 1. Controlled A/B Isolation
Every workload variant runs both **without Perseus** (State A: baseline) and **with Perseus** (State B: treated) under identical conditions. Results are always expressed as State-B / State-A ratios.

### 2. Cold / Warm Separation
Each measurement explicitly tracks:
- **COLD:** Fresh Perseus home per render — no disk or session cache exists
- **WARM:** Home pre-populated by an identical prior run — cache fully primed

Both are measured and reported. Neither is hidden behind the other.

### 3. Statistical Rigour
Every timing is repeated `N_REPS` times (default 5). We report:

| Metric | Meaning |
|---|---|
| `mean` | Average wall-clock time (ms) |
| `median` | 50th percentile |
| `p95` | 95th percentile |
| `p99` | 99th percentile |
| `stddev` | Population standard deviation |
| `cv` | Coefficient of variation (stddev/mean) |
| `noisy` | `True` if CV > 0.25 — measurement is unreliable |

### 4. Regression Probes (Phase 6)
Explicit scenarios where Perseus is **expected to be slower** are included and measured honestly:
- Tiny context (1 directive) where subprocess overhead dominates
- Massive context (120 directives, cold) where I/O dominates
- Single-shot renders with zero warm-up
- Sustained cache-miss storms

### 5. Honest Gate Philosophy
Gates are categorised by severity:

| Severity | Meaning |
|---|---|
| `hard` | Blocks overall PASS — these are correctness/safety invariants |
| `soft` | Informational failures — performance goals that may not hold on all hardware |
| `informational` | Always shown, never blocks PASS |

A FAIL on a soft gate **will not** suppress the result — it is always printed verbatim in the report.

---

## Phases

### Phase 0 — Environment Validation
Verifies prerequisites before wasting time:
- `perseus.py` is reachable
- `PERSEUS_BENCH=1` causes the renderer to emit `BENCH|…` stderr telemetry
- psutil is available (for RSS tracking)
- Python ≥ 3.10

**Aborts the suite** if any hard check fails.

---

### Phase 1 — Cold-Start Ladder
**Scope:** `DIRECTIVE_LADDER × TIER_LADDER` measurement cells, each run `N_REPS` times with a fresh Perseus home per repetition.

**Directive ladder:** [1, 5, 15, 30, 60, 120]  
**Tier ladder:** [1, 2, 3]

**What it measures:**
- How render latency scales with directive count and context tier under cold-cache conditions
- The BENCH telemetry breakdown (parse_us, cache_hits/misses, total_us)
- Per-cell output token count

**What to look for:**
- Latency should increase sub-linearly with directive count (parallel resolution)
- CV should stay < 0.25 (stable measurements)
- cache_hits should be 0 on every cold cell

---

### Phase 2 — Warm-Start Ladder
**Scope:** Identical cells to Phase 1, but each cell uses a pre-populated home (one prior render seeds the cache).

**What it measures:**
- Warm-cache render latency for the same workload
- Cache hit rate (should be > 0 for @env directives)
- Whether warmth actually reduces latency

**What to look for:**
- cache_hits > 0 for every warm cell
- Warm latency ≤ cold latency for most cells (regression if not)

---

### Phase 3 — Cold vs. Warm Delta Analysis
**Scope:** Computes warm/cold speedup ratio for every matched Phase 1/Phase 2 cell.

**Key metric:** `warm_speedup_ratio = warm_mean_ms / cold_mean_ms`

| Ratio | Meaning |
|---|---|
| < 1.0 | Warm is faster (cache is helping) |
| ≈ 1.0 | No measurable difference |
| > 1.05 | **REGRESSION** — warm is more than 5% slower than cold |

**Why regressions happen:**
- Disk I/O contention from cache file reads
- Lock contention under concurrent cache writes
- Very low directive counts where cache overhead > benefit
- Noisy measurement environment (CI, shared hardware)

All regressions are flagged explicitly — never averaged away.

---

### Phase 4 — Concurrency Stress
**Scope:** `CONCURRENCY_LADDER` simultaneous renders against the same home, both cold and warm.

**Concurrency ladder:** [1, 10, 50, 100, 250]

**What it measures:**
- Mean and tail latency as concurrent load increases
- Throughput (renders/second) at each concurrency level
- Error rate (process failures, timeouts)
- Latency CV stability under load

**Regression signal:** If `tps@250 < tps@10 × 0.10` the system is collapsing — this is a soft gate.

**Why this matters for enterprise:** 50+ developers on the same workstation or shared NFS mount will hit this path constantly.

---

### Phase 5 — Context-Tier Scaling
**Scope:** Tier 1, 2, 3 × full directive ladder, warm cache.

Perseus supports three context tiers:
- **Tier 1:** Minimal — only always-on directives resolved
- **Tier 2:** Conditional — adds medium-cost directives  
- **Tier 3:** Full — all directives resolved

**What it measures:**
- Latency difference between tiers for each directive count
- Token output difference between tiers
- The cost/benefit of each tier level

**What to look for:** Tier 1 should produce fewer tokens and be faster than Tier 3. If it is not, the tiering system is not functioning.

---

### Phase 6 — Regression Probes
**The most important phase for honesty.** Six explicit scenarios where Perseus overhead may dominate:

| Probe | Scenario | Expected |
|---|---|---|
| A | 1 directive, cold | Overhead likely dominates; latency should still be < 500ms |
| B | 120 directives, cold | I/O-heavy; slowest cold scenario |
| C | Single-shot (no warm-up, 10 runs) | Worst-case cold path; must be < 2000ms |
| D | 1 directive, warm | Best-case; should be faster than Probe A |
| E | 20 renders, all unique keys | Maximum sustained cache-miss rate |
| F | Empty context (State A baseline) | Zero overhead, zero benefit — the cost floor |

**All results are reported regardless of direction.** If Probe D is slower than Probe A, that is explicitly flagged as a regression gate failure.

---

### Phase 7 — Enterprise Day Simulation
**Scope:** `ENTERPRISE_DEV_COUNT` (default 50) simulated developers running a full 8-hour workday in parallel.

**Developer roles** (weighted by typical enterprise distribution):

| Role | Directives | Weight |
|---|---|---|
| Backend | 20 | 30% |
| Frontend | 12 | 20% |
| DevOps | 30 | 15% |
| Data | 25 | 15% |
| Mobile | 10 | 10% |
| Security | 35 | 10% |

**Day events per developer:**

| Event | Renders | Cold % |
|---|---|---|
| Standup | 1 | 100% (always fresh) |
| Code review | 3 | 20% |
| Feature work | 8 | 10% |
| Debug session | 5 | 30% |
| Doc update | 2 | 10% |
| Incident hotfix | 4 | 80% (chaos) |
| End of day | 1 | 0% (always warm) |

**ROI model:**  
Without Perseus, each AI call requires the developer to re-describe their full context inline. The State A cost estimate assumes raw prompt tokens = 10× Perseus output tokens (conservative). This produces an ROI% figure that is clearly labelled with its assumption.

---

### Phase 8 — Cache Pathology
Four sub-tests probing extreme cache conditions:

| Sub-test | Scenario |
|---|---|
| 8a TTL cliff | Fill cache, nuke it, re-render. Ratio must be < 10× |
| 8b Rapid invalidation | 50 concurrent renders; half the cache deleted mid-flight. Wave 2 must succeed ≥ 88% |
| 8c Integrity audit | Walk every cache file: JSON parseable, no corruption |
| 8d Determinism | Same input × 5 runs must produce identical output |

---

### Phase 9 — Memory & Process Hygiene
**Requires:** `pip install psutil`

- 30 sequential renders while polling RSS every 20ms
- Compares early (runs 1–5) vs late (runs 26–30) mean RSS
- RSS growth > 20% flags a suspected memory leak
- `find_orphan_subprocesses()` verifies no perseus processes are left running

---

### Phase 10 — Gate Evaluation
Aggregates all phase results into a single pass/fail verdict.

**Hard gates** (must pass for overall PASS):
- BENCH shim emits telemetry
- No cold renders fully timed out
- Zero errors at concurrency=1
- Error rate ≤ 1% at peak concurrency
- Single-shot cold render ≤ 2000ms
- TTL cliff ratio < 10×
- Rapid invalidation wave 2 ≥ 88% success
- Cache integrity: zero corrupt entries
- Determinism: same input → same output

**Soft gates** (reported but don't block PASS):
- Warm cache faster than cold for all cells
- Warm speedup ≥ 5% for large contexts (≥ 30 directives, tier 3)
- Throughput doesn't collapse at peak concurrency
- Tier 1 produces ≤ tokens than tier 3
- Warm 1-directive faster than cold 1-directive
- Enterprise day ROI positive
- Fleet P99 ≤ 2000ms

**Informational gates** (always shown, never block):
- No overhead-dominant scenarios detected
- Memory hygiene result

---

## Output Files

### `extreme_enterprise_results.json`
Full machine-readable results for all phases. Schema:

```json
{
  "generated_at_utc": "2026-05-26T...",
  "overall_pass": true,
  "total_duration_s": 847.3,
  "phase_0": { "checks": [...], "pass": true },
  "phase_1": { "cells": [{ "n_directives": 1, "tier": 1, "wall_ms": {...}, ... }] },
  "phase_2": { "cells": [...] },
  "phase_3": { "deltas": [...], "regressions": [...], "regression_count": 0 },
  "phase_4": { "cold": [...], "warm": [...], "cv_violations": [] },
  "phase_5": { "cells": [...] },
  "phase_6": { "probes": { "A_tiny_cold": {...}, ... }, "overhead_detected": false },
  "phase_7": { "n_devs": 50, "total_renders": 1200, "estimated_roi_pct": 87.3, ... },
  "phase_8": { "results": { "P8a_ttl_cliff": {...}, ... } },
  "phase_9": { "results": { "rss": {...}, "orphans": {...} } },
  "phase_10": { "gates": [...], "hard": {...}, "soft": {...}, "pass": true }
}
```

### `extreme_enterprise_report.txt`
Human-readable plain-text report. Structured for direct paste into:
- Discord / Slack messages
- Confluence page content
- GitHub PR descriptions
- Email

---

## Interpreting Results

### "Warm is slower than cold" (Phase 3 regression)
Common on fast NVMe + macOS where subprocess startup dominates and cache file I/O adds contention. This is **not hidden** — it's a soft gate failure and appears in the cold/warm table with `!! YES`.

### cache_hits = 0 on warm cells
`@env` directives resolve environment variables at render time without disk caching (they are too fast to cache). Warm benefits are more visible with `@memory`, `@query`, and `@include` directives. This is noted in the output.

### ROI estimate caveats
The Phase 7 ROI assumes 10× token re-description cost without Perseus. Real-world numbers depend on:
- How verbose developers are when prompting without context
- Whether the LLM provider charges for cached tokens (Anthropic prompt cache = 10% rate)
- The token efficiency of your specific directive set

The assumption is printed in the report gate note and in the Phase 7 output.

### noisy=True cells
If `cv > 0.25`, the measurement has high variance. This usually means:
- Not enough repetitions (`--reps 10` or more will stabilise)
- Machine under load during the run
- OS scheduling jitter (common at high concurrency)
Noisy cells are still reported — they are not dropped.

---

## How This Differs from Existing Benchmarks

| Benchmark | Focus |
|---|---|
| `swarm_chaos.py` | Concurrent agent isolation and correctness |
| `cache_thrash.py` | Cache hit-rate mechanics and TTL behaviour |
| `adversarial_extended.py` | Malformed inputs, adversarial prompts |
| `enterprise_day.py` | Single enterprise day simulation |
| `extreme_week.py` | Multi-day enterprise week simulation |
| **`extreme_enterprise_benchmark.py`** | **Everything above, plus: cold/warm isolation with statistical rigour, regression probes, concurrency scaling, tier scaling, memory hygiene, honest gate reporting** |

This suite is designed to be the **single definitive benchmark** for a Perseus deployment decision.

---

## Integration with Existing Suite

The output JSON is standalone and does not depend on other benchmark files. To add this phase to the unified `run_extreme_suite.py` orchestrator:

```python
plan.append((
    "extreme-enterprise",
    [sys.executable, str(ROOT / "extreme_enterprise_benchmark.py"),
     "--quick", "--skip-memory"],
))
```

And add its gates to `eval/gate_runner.py`:

```python
xeb = _load(bench_dir / "extreme_enterprise_results.json")
p10 = xeb.get("phase_10", {})
for g in p10.get("gates", []):
    gate(g["name"], g["pass"], g["observed"], g["threshold"],
         g.get("severity", "hard"))
```
