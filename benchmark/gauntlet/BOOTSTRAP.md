# Perseus Gauntlet — Bootstrap Prompt

You are building and running the most comprehensive Perseus benchmark ever created.
This is a self-contained prompt — everything you need to implement and execute is below.

**Target machine:** Dedicated Linux box, 16+ cores, 32GB+ RAM, NVMe storage.
**Duration:** ~8.5 hours at full scale. Validate plumbing at 10% scale first (~20 min).

---

## What You're Building

A multi-phase, multi-machine torture test that exercises every Perseus directive and subsystem
at enterprise scale: 2,000 simulated developers across 4 nodes, 25 distinct role profiles,
12 adversarial scenarios, 40+ pass/fail gates.

The benchmark simulates: cold starts, warm cache, a full work week, 8,000-agent swarm
coordination on a shared task board, 80,000 concurrent checkpoint writes, 40,000 cross-team
messages, adversarial conditions (disk full, network partition, OOM, clock skew, etc.),
semantic integrity validation via real LLM judging, token compression measurement, and
2 hours of sustained torture to detect memory leaks and degradation.

---

## Architecture

```
              ┌─────────────────────────────┐
              │     COORDINATOR (node-0)     │
              │  Orchestrates all phases     │
              │  Collects telemetry          │
              │  Hosts shared NFS store      │
              └──────────┬──────────────────┘
                         │ NFS mount at /mnt/perseus-gauntlet
     ┌───────────────────┼───────────────────┐
     │                   │                   │
┌────▼─────┐   ┌────────▼────┐   ┌────────▼────┐   ┌────────▼────┐
│  NODE-1  │   │   NODE-2    │   │   NODE-3    │   │   NODE-4    │
│ 10 teams │   │  10 teams   │   │  10 teams   │   │  10 teams   │
│ 500 devs │   │  500 devs   │   │  500 devs   │   │  500 devs   │
└──────────┘   └─────────────┘   └─────────────┘   └─────────────┘
```

**If you only have one machine**, run all 4 nodes as separate processes with isolated
PERSEUS_HOME directories. Concurrency will be CPU-bound but the test is still valid.

---

## Prerequisites (on each node)

```bash
pip install perseus-ctx pyyaml
perseus --version  # must be v1.0.4+

# NFS mount for shared state (if multi-machine):
mkdir -p /mnt/perseus-gauntlet
mount -t nfs <coordinator-ip>:/export/gauntlet /mnt/perseus-gauntlet

# Or local dir if single-machine:
mkdir -p /mnt/perseus-gauntlet
```

---

## Files to Create

All files live under `/workspace/perseus/benchmark/gauntlet/`. Create them in this order:

### 1. `gauntlet_lib.py`

Shared utilities: metrics collection, gating engine, telemetry schema, NFS helpers,
directive counter, cache verifier, report generator.

Key exports:
```python
class GauntletMetrics:  # collects per-phase timing, counts, distributions
class GateRunner:       # evaluates pass/fail conditions, produces gate report
class TelemetrySink:    # NDJSON writer for per-render records
class NfsProbe:         # touch+rm health check for NFS mount
def verify_cache_integrity(cache_dir):  # validates all cache entries are valid YAML/JSON
def compute_cost_projection(total_directives, pricing_tiers):  # annual savings calc
def generate_final_report(phase_results, gate_results):  # writes gauntlet_report.md
```

### 2. Role Profile Context Files (25 files)

Create `gauntlet_role_profiles/` with 25 `.perseus/context.md` files. Each starts with
`@perseus v0.8` and `@prompt` block. Profiles range from 30 directives (intern) to 120
(devops). Exercise every directive type across the set:

| # | Role | Directive Count | Key Directives |
|---|---|---|---|
| 1 | Platform Engineer | 80 | @query (git, docker, df, free, uptime), @services (15), @read (8) |
| 2 | Web Developer | 65 | @query (npm, node, jest), @skills, @read (package.json, tsconfig) |
| 3 | Mobile Developer | 60 | @query (gradle, java), @read, @waypoint |
| 4 | Data Engineer | 75 | @query (spark-submit --version, airflow version), @services (20), @read |
| 5 | ML Engineer | 70 | @query (nvidia-smi, pip list, python --version), @skills, @memory |
| 6 | DevOps | **120** | EVERY directive — heaviest profile. @query (kubectl, terraform, helm, ansible, docker, ssh, curl), @services (30+), @health, @drift, @agora, @inbox, @waypoint, @prefetch, @synthesize, @graph |
| 7 | Security Engineer | 85 | @query (lynis, trivy, nmap stubs), @drift, @health |
| 8 | QA Engineer | 55 | @query (pytest, cypress), @agora, @inbox |
| 9 | DevTools | 90 | @query (bazel, make, cmake), @skills, @prefetch |
| 10 | Docs Writer | 50 | @read, @synthesize, @memory |
| 11 | Team Lead | 60 | @agora, @inbox, @health, @waypoint |
| 12 | Architect | 65 | @graph, @prefetch, @drift, @memory, @read |
| 13 | SRE | 110 | @query (k8s, terraform, prometheus), @services (30+), @health, @drift |
| 14 | Backend (Python) | 70 | @query (pip, pytest, mypy), @read (pyproject.toml, setup.cfg), @waypoint |
| 15 | Backend (Go) | 65 | @query (go mod, go test, go vet), @read (go.mod, go.sum), @waypoint |
| 16 | Backend (Rust) | 65 | @query (cargo build, cargo test, rustc --version), @read (Cargo.toml), @waypoint |
| 17 | Frontend (React) | 60 | @query (npm run build, jest), @read (package.json), @skills |
| 18 | Frontend (Vue) | 60 | @query (npm run build, vitest), @read (package.json), @skills |
| 19 | Full-Stack | 85 | mixed heavy profile — all categories |
| 20 | Database Admin | 75 | @query (psql --version, mongod --version), @services, @read |
| 21 | Network Engineer | 70 | @query (ip addr, ss -tlnp, curl localhost), @services (30+) |
| 22 | Release Manager | 55 | @agora, @inbox, @waypoint, @health |
| 23 | Performance Engineer | 80 | @query (perf, flamegraph, sysbench), @drift, @health |
| 24 | Accessibility Auditor | 50 | @read, @skills, @synthesize |
| 25 | Intern | 30 | minimal directives — baseline comparison, @read only |

**Directive distribution requirements across the 25 profiles:**
- Every profile must include at least: `@query "git log --oneline -5" @cache ttl=300`
- `@cache ttl=300` on ALL @query directives (for warm-phase measurement)
- `@services` must include at least 5 services per profile (URL-based: localhost:port)
- `@waypoint ttl=86400` in at least 15 of 25 profiles
- `@agora status=open,in_progress` in at least 10 profiles
- `@inbox` in at least 8 profiles
- `@memory focus="recent"` in at least 8 profiles
- `@health` in at least 10 profiles
- `@drift` in at least 8 profiles
- `@prefetch` in at least 6 profiles
- `@synthesize` in at least 5 profiles
- `@graph` in at least 5 profiles
- `@skills flag_stale=true` in at least 15 profiles

### 3. `gauntlet_node.py`

Per-node worker. Receives commands from the coordinator via shared NFS files (phase command
files). Each node:

1. Reads `NODE_ID` and `PERSEUS_HOME` from environment
2. Waits for phase command file on NFS: `/mnt/perseus-gauntlet/phase_cmds/phase_N_node_M.json`
3. Executes the phase (cold render, warm render, enterprise event, etc.)
4. Writes results to `/mnt/perseus-gauntlet/results/phase_N_node_M.json`
5. Signals completion via sentinel file

Key functions:
```python
def render_all_developers(role_profiles, developers, cache_state='cold', tier=3):
    """Render all context files for all developers on this node. Returns metrics."""

def render_enterprise_event(developers, event_spec, node_id):
    """Execute one enterprise week event (burst or staggered)."""

def run_adversarial_scenario(scenario_id, config, duration_s):
    """Execute one adversarial scenario for the specified duration."""

def sustained_torture_loop(duration_s, concurrent_renders):
    """Continuous cold/warm cycling with memory monitoring."""
```

### 4. `gauntlet_adversarial.py`

12 adversarial scenarios. Each is a function that sets up the adverse condition, runs
renders for 300s, then cleans up and verifies recovery.

```python
SCENARIOS = {
    'A1_disk_full':    fill_nfs_to_95_percent_then_continue,
    'A2_network_partition': isolate_node_iptables,
    'A3_clock_skew':   skew_system_clock_2h,
    'A4_oom_pressure':  consume_90_percent_ram,
    'A5_cache_poison':  inject_invalid_cache_entries,
    'A6_pid_reuse':     rapid_process_churn,
    'A7_signal_storm':  send_sigterm_sigint_randomly,
    'A8_fd_exhaustion': open_50k_file_descriptors,
    'A9_fork_bomb_defense': limit_subprocesses_hammer_concurrent,
    'A10_symlink_race': create_symlink_chains_during_render,
    'A11_locale_corruption': set_invalid_locale,
    'A12_timezone_shift': change_tz_during_enterprise_week,
}
```

**Important safety:** A1, A4, and A9 are genuinely dangerous. Each must have:
- A kill switch (check for sentinel file every 30s)
- A cleanup function that runs even on exception
- A 5-minute maximum duration (hard timeout)

### 5. `gauntlet_orchestrator.py`

Main entry point. Accepts CLI args, sequences all 11 phases, collects results from nodes,
evaluates gates, generates final report.

```bash
python3 benchmark/gauntlet/gauntlet_orchestrator.py \
    --nodes node-1,node-2,node-3,node-4 \
    --nfs-path /mnt/perseus-gauntlet \
    --developers-per-node 500 \
    --teams-per-node 10 \
    --roles-dir benchmark/gauntlet/gauntlet_role_profiles \
    --duration full \
    --output-dir benchmark/gauntlet/
```

**Phase sequencing:**

| Phase | Name | Duration | Key Gates |
|---|---|---|---|
| 0 | Pre-Flight | 5 min | NFS health, Perseus version match, node reachability |
| 1 | Baseline Cold | 30 min | Zero failures, P99 ≤ 120s, median ≤ 30s |
| 2 | Warm Baseline | 15 min | Warm not slower than cold, cache hit ≥ 85% |
| 3 | Enterprise Week | 120 min | Zero failures, weekend decay matches Day 1, chaos survival |
| 4 | Agora Swarm | 45 min | Zero board corruption, claim contention ≤ 5%, 40K ops ≤ 10 min |
| 5 | Checkpoint Relay | 45 min | Zero corruption, throughput ≥ 50 wps, lock contention ≤ 2% |
| 6 | Inbox Storm | 30 min | Delivery ≥ 99.9%, zero duplicates, P99 ≤ 5s |
| 7 | Adversarial Gauntlet | 60 min | Zero corruption, zero crashes, clean recovery from all 12 |
| 8 | Semantic Integrity | 30 min | Equivalence ≥ 0.90, calibration error ≤ 0.10 |
| 9 | Token Efficiency | 15 min | No token inflation (ratio ≤ 1.0), P99 overhead ≤ 5ms |
| 10 | Sustained Torture | 120 min | RSS growth ≤ 5%, P50 stable ±10%, errors ≤ 0.01% |
| 11 | Final Report | 10 min | Aggregate all results, compute score |

**For Phase 8 (Semantic Integrity),** the judge protocol is:
- Use Gemini 2.5 Flash via `v1beta` endpoint
- Key from `GOOGLE_API_KEY` env var
- Generate responses for both State A (no Perseus) and State B (with Perseus context)
- Judge compares responses, NOT prompts (comparing prompts gives false negatives)
- Include 10 A-vs-A calibration pairs to measure judge variance
- Adjusted score = (raw - control_error) / (1 - control_error)
- Judge prompt must explicitly tolerate: different phrasing, alternate variable names, extra explanation

**For Phase 9 (Token Efficiency):**
- Use `telemetry/hooks.py` pattern if available, or stub with token counters
- Measure prompt tokens with and without Perseus context
- Compute compression ratio per role profile
- Project annual savings across 3 pricing tiers: Claude Opus 4.7, GPT-5, Gemini 2.5 Pro

---

## Validation: 10% Scale Smoke Test

Before the full run, validate plumbing at 10% scale:

```bash
python3 benchmark/gauntlet/gauntlet_orchestrator.py \
    --nodes local \
    --nfs-path /mnt/perseus-gauntlet \
    --developers-per-node 50 \
    --teams-per-node 1 \
    --duration smoke \
    --output-dir benchmark/gauntlet/
```

This runs Phases 0–2 only at reduced scale. Should complete in ~20 minutes.
If it passes, you're clear for the full run.

---

## Expected Output

After a successful full run:

```
benchmark/gauntlet/
├── gauntlet_results.json       # Machine-readable: all phase metrics, gate results, cost projections
├── gauntlet_report.md          # Human-readable: summary table, per-phase breakdown, recommendations
├── gauntlet_telemetry.ndjson   # Per-render records (100K+ lines)
├── gauntlet_score.txt          # Single number: overall score 0-100
└── gauntlet_checkpoints/       # Phase checkpoints for resumability
```

The final report must answer:
1. Did Perseus survive? (overall pass/fail)
2. What's the cold→warm speedup at 2,000-dev scale?
3. Can 8,000 agents coordinate on a single task board?
4. Can 80,000 checkpoints write to one NFS store without corruption?
5. Does any directive type degrade under load?
6. Are there memory leaks over 2 hours of continuous renders?
7. What's the semantic equivalence score with real LLM judging?
8. What's the token compression ratio and annual cost savings?
9. Which adversarial scenario was closest to breaking Perseus?
10. What's the overall Gauntlet score?

---

## Critical Constraints

- **pyyaml is the only dependency.** No new pip packages without explicit approval.
- **Perseus v1.0.4+** must be installed on all nodes.
- **All directives must be valid Perseus syntax.** Test each role profile with `perseus render` before running the full benchmark.
- **Adversarial scenarios A1, A4, A9 have kill switches.** Never run them without.
- **Phase 8 uses real LLM calls.** Requires `GOOGLE_API_KEY` in environment.
- **Don't compute dollar amounts in final output.** Use ratios and compression percentages.
- **Pre-existing PIDs must be excluded from orphan detection.** Snapshot before each phase.
- **Cold and warm must use separate PERSEUS_HOME directories.** Never mix them.
- **Gate count includes skips with reasons.** Silently-skipped gates = data loss.
- **All results are incremental.** Save after each phase so a crash at Phase 9 doesn't lose Phases 0–8.

---

## Quick Start (on the dedicated machine)

```bash
# 1. Clone and install
git clone https://github.com/tcconnally/perseus.git /workspace/perseus
cd /workspace/perseus
pip install -e .

# 2. Create the gauntlet directory and all files (as specified above)
mkdir -p benchmark/gauntlet/gauntlet_role_profiles
# ... implement gauntlet_lib.py, 25 role profiles, gauntlet_node.py, etc. ...

# 3. Set up shared state
mkdir -p /mnt/perseus-gauntlet

# 4. Smoke test at 10% scale
python3 benchmark/gauntlet/gauntlet_orchestrator.py \
    --nodes local --nfs-path /mnt/perseus-gauntlet \
    --developers-per-node 50 --duration smoke

# 5. If smoke test passes, run full gauntlet
python3 benchmark/gauntlet/gauntlet_orchestrator.py \
    --nodes local --nfs-path /mnt/perseus-gauntlet \
    --developers-per-node 500 --duration full

# 6. Read the report
cat benchmark/gauntlet/gauntlet_report.md
```

Go. Build it. Run it. Break it. Prove Perseus holds.
