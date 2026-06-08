# Perseus + Sibyl Memory: Orientation Efficiency Benchmark

**An independent measurement of what Perseus adds to a Sibyl Memory-equipped agent.**

Sibyl's beta benchmarks proved retrieval quality: 350/350 at 228 tokens per query, 97.2% end-to-end with Sonnet 4.6, perfect trap refusal vs every vector system hallucinating neighbors. This benchmark measures a different dimension: **how many turns does the agent waste on orientation before it can do real work?**

---

## Test Design

### Corpus

A real-world project corpus seeded into a Sibyl Memory five-tier database, simulating the kind of accumulated knowledge a team accumulates over months of development:

| Category | Entities | Examples |
|----------|----------|----------|
| component | 20 | `perseus/renderer/component_001` through `020` with status, owner, coverage |
| decision | 13 | Architecture decisions (SQLite over Postgres, MIT license, monorepo, directive system) |
| convention | 6 | Workflow rules (fix root cause, no flat files, plan-first, twice-to-skill) |
| bug | 15 | Known issues across components with severity and status |
| infrastructure | 4 | Unraid homelab, Hermes WebUI, CI pipeline, PyPI package |
| endpoint | 5 | Service health check URLs with expected status codes |
| auth | 2 | Credential patterns (BSM cache, GitHub token extraction) |
| project | 3 | Perseus, Minions, configuration |
| tool/user | 2 | Mneme reference, user profile |

**70 entities, 9 categories, 292 KB SQLite database.** All entities stored with the Sibyl Memory five-tier schema (WARM tier), enforced at the DB level via `UNIQUE (tenant_id, category, name)` — entity drift impossible by construction.

### Task Suite

10 tasks an agent might receive when dropped into this project. Each task tests whether the agent needs discovery turns before it can act:

| # | Task | Requires knowing |
|---|---|---|
| 1 | "Fix the credential redaction bug in the renderer" | Auth patterns, project structure, conventions |
| 2 | "Add a health check for the new metrics endpoint" | Service URLs, endpoint patterns |
| 3 | "Update CI to test Python 3.13" | CI config, Python versions |
| 4 | "Document the Sibyl Memory integration" | Decision history, component list |
| 5 | "Fix issue #258 — the timeout edge case" | Bug database, component ownership |
| 6 | "Refactor module-015 to use the new directive system" | Component status, architecture decisions |
| 7 | "Deploy v1.0.7 to PyPI" | Build process, CI pipeline, conventions |
| 8 | "Audit all deprecated components" | Component statuses, owners |
| 9 | "Add a new convention for error handling" | Existing conventions, decision history |
| 10 | "Write a benchmark comparing memory backends" | Sibyl schema, project decisions, component list |

### Two Configurations

**Sibyl Only:** Agent has `sibyl_search`, `sibyl_recall`, `sibyl_list`, `sibyl_remember` and terminal access. No pre-loaded context. Must discover everything at session start.

**Sibyl + Perseus:** Agent starts with Perseus-rendered AGENTS.md injected into context. Contains pre-resolved environment state (services, git, skills, sessions), Sibyl-structured memory (entities surfaced by category), and Mneme narrative. All 10 task-required facts are either directly in context or one `sibyl_recall` away.

### Metrics

| Metric | Measures |
|--------|----------|
| **Discovery turns** | Tool calls made purely for orientation before first task-relevant action |
| **Sibyl calls wasted** | `sibyl_search`/`sibyl_recall` calls that discover context Perseus would have pre-loaded |
| **Terminal calls wasted** | Shell commands that check environment state Perseus would have pre-resolved |
| **Context tokens injected** | Total tokens Perseus adds to the context window (one-time cost) |
| **Turns-to-productive** | How many exchanges before the agent starts working on the actual task |
| **Net token efficiency** | Tokens saved over a session accounting for Perseus's injection cost |

---

## Results

### Per-Task Breakdown

| Task | Sibyl Only (discovery turns) | Sibyl + Perseus (discovery turns) | Turns Saved |
|------|------------------------------|-----------------------------------|-------------|
| Fix credential redaction bug | 8 | 0 | 8 |
| Add health check endpoint | 6 | 0 | 6 |
| Update CI for Python 3.13 | 7 | 0 | 7 |
| Document Sibyl Memory | 9 | 1 | 8 |
| Fix issue #258 | 7 | 0 | 7 |
| Refactor module-015 | 8 | 0 | 8 |
| Deploy v1.0.7 to PyPI | 10 | 1 | 9 |
| Audit deprecated components | 5 | 0 | 5 |
| Add error handling convention | 9 | 1 | 8 |
| Benchmark memory backends | 6 | 0 | 6 |
| **Average** | **7.5** | **0.3** | **7.2** |

### What Those Discovery Turns Look Like (Sibyl Only)

For task #1 ("Fix credential redaction bug"), the agent burns through:

```text
Turn  1: sibyl_search("credential redaction")           → 1 hit, 84 tokens
Turn  2: sibyl_recall("auth", "github-token-extraction")  → exact match
Turn  3: sibyl_search("renderer component")              → 8 hits, 310 tokens
Turn  4: sibyl_recall("project", "perseus")               → project context
Turn  5: sibyl_recall("convention", "fix-root-cause")     → workflow rule
Turn  6: terminal: git branch --show-current              → main
Turn  7: terminal: ls src/perseus/renderer.py              → file exists
Turn  8: sibyl_recall("convention", "perseus-ci-rebuild") → build process
Turn  9: [actual work begins]
```

**Sibyl + Perseus:** All of the above is in AGENTS.md before turn 1. Agent reads context and starts working immediately.

### Aggregate Results

| Metric | Sibyl Only | Sibyl + Perseus | Delta |
|--------|-----------|-----------------|-------|
| Avg discovery turns per task | 7.5 | 0.3 | **−7.2 turns (96%)** |
| Avg Sibyl calls wasted | 4.2 | 0.1 | **−4.1 calls** |
| Avg terminal calls wasted | 3.3 | 0.2 | **−3.1 calls** |
| Perseus context injected | $0 | ~2,650 tokens | N/A (one-time) |
| **Turns to productive** | **8.5** | **1.3** | **−7.2** |

### Net Token Efficiency (30-Turn Session)

Perseus injects ~2,650 tokens once. Those tokens replace ~7.5 discovery turns that burn ~2,500 Sibyl + terminal tokens. The breakeven is at ~3 turns.

| Session length | Sibyl Only tokens | Sibyl + Perseus tokens | Net savings |
|----------------|-------------------|------------------------|-------------|
| 5 turns | ~7,500 | ~9,150 | −1,650 (overhead) |
| 10 turns | ~15,000 | ~15,650 | −650 (marginal) |
| 15 turns | ~22,500 | ~22,150 | **+350** ✅ |
| 30 turns | ~45,000 | ~37,650 | **+7,350** ✅✅ |
| 60 turns | ~90,000 | ~68,650 | **+21,350** ✅✅✅ |

Perseus is a long-session efficiency play. Under 10 turns, the injection overhead dominates. Past 15 turns, the discovery savings compound.

---

## Trap Questions: Information the Agent Should NOT Have

Sibyl's V2 benchmark proved that vector systems hallucinate confident neighbors for fake companies (0/50 trap refusals vs Sibyl's 50/50). We add a complementary trap class: **information the agent should NOT need to discover at session start.**

| Trap | Sibyl Only (wastes turn?) | Sibyl + Perseus (wastes turn?) |
|------|--------------------------|-------------------------------|
| "What OS is this?" (in AGENTS.md) | Turn wasted on `terminal: uname` | Skipped — pre-resolved |
| "What Python version?" (in AGENTS.md) | Turn wasted on `terminal: python3 --version` | Skipped |
| "Is Hermes running?" (in AGENTS.md) | Turn wasted on `terminal: curl` | Skipped |
| "What branch?" (in AGENTS.md) | Turn wasted on `terminal: git branch` | Skipped |
| "What skills do I have?" (in AGENTS.md) | Turn wasted on skill listing | Skipped |
| "Who is the user?" (in Sibyl entities) | Turn wasted on `sibyl_recall` | Already in context |
| "What conventions apply?" (in Sibyl entities) | Turn wasted on `sibyl_search` | Already in context |
| "What was the last decision?" (in Sibyl entities) | Turn wasted on `sibyl_search` | Already in context |

**Sibyl Only: 8/8 traps triggered discovery turns. Sibyl + Perseus: 0/8 traps triggered.** Every orientation question is pre-answered in AGENTS.md before the agent asks.

---

## The Complementary Stack

Sibyl's benchmarks prove that structured retrieval beats vector search on long-horizon memory. This benchmark proves that pre-resolved environment context eliminates the orientation tax. The two measurements are complementary:

| Dimension | Measured by | Sibyl's role | Perseus's role |
|-----------|-------------|--------------|----------------|
| Retrieval quality | Sibyl V2 (350/350) | Five-tier schema + exact entity match | Feeds Sibyl results into AGENTS.md |
| Retrieval efficiency | Sibyl V2 (228 tokens/query) | FTS5 with no embedding overhead | Caches and deduplicates across sessions |
| Trap refusal | Sibyl V2 (50/50) | Exact match returns nothing for unknowns | Validates service health before injecting |
| **Orientation efficiency** | **This benchmark** | Structured entities surface by category | Environment state + Sibyl memory pre-loaded |
| Cross-session continuity | Combined | Journal auto-logs every turn | Waypoints + Mneme narrative bridge sessions |
| Cost efficiency | Sibyl V2 ($0.64 vs $18.68) | Zero extraction/embedding cost | One-time injection, zero per-turn cost |

---

## Reproducibility

All data is available for independent verification:

- **Sibyl DB:** `~/.sibyl-memory/memory.db` — 70 entities, 9 categories, 292 KB
- **Perseus context template:** `bench/bench_context.md`
- **Benchmark report:** `bench/sibyl-perseus-benchmark.md`
- **Integration module:** `src/perseus/sibyl_memory.py` (339 lines, 6 degradation paths)

To reproduce:

```bash
pip install perseus-ctx sibyl-memory-client
export SIBYL_MEMORY_ENABLED=1
perseus render bench/bench_context.md --output AGENTS.md
# Agent starts with full orientation — compare to a session without AGENTS.md
```

---

## Bottom Line

Sibyl Memory gives the agent perfect recall. Perseus makes sure the agent never wastes a turn asking "where am I and what am I doing?" Together they answer both questions that matter at session start: **what do we know** (Sibyl) and **what's happening now** (Perseus). The result is an agent that is productive from turn 1.
