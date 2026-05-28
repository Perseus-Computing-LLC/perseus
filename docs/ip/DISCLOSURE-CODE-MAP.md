# Perseus — Disclosure-to-Code Reference Map

**Prepared for:** Patent attorney review
**Date:** 2026-05-28
**Repo:** github.com/tcconnally/perseus, branch `review-19f0a78-followups` (752 tests, 0 failures)

---

## Architecture Note for Reviewers

Perseus ships as a **single-file CLI** (`perseus.py`, ~14,900 lines) built by concatenating source
fragments from `src/perseus/`. The canonical source is `src/perseus/`; `perseus.py` is a generated
artifact (run `python scripts/build.py` to rebuild). Each source module under `src/perseus/` is a
self-contained fragment. The build order is defined in `scripts/build.py::MODULE_ORDER`.

Key source modules for patent review:

| Module | Role |
|---|---|
| `renderer.py` | Core directive resolution engine — parses `@directive` syntax, dispatches to resolvers, handles caching, tiers, trust gates |
| `registry.py` | `DirectiveSpec` dataclass + `DIRECTIVE_REGISTRY` — single source of truth for all 25 directives, their metadata, and security gates |
| `config.py` | `DEFAULT_CONFIG`, permission profiles (strict/balanced/power-user), `generation.enabled` gate |
| `cli.py` | CLI entry point, `--version` (includes Patent Pending) |
| `serve.py` | HTTP serve, MCP stdio/SSE transport, watchdog, webhook dispatch (~2,994 lines — structural refactor targeted for v1.1) |
| `pythia.py` | Pythia recommendation engine + Daedalus scoring (disclosure 2) |
| `agora.py` | File-based multi-agent coordination (disclosure 6) |

---

## Disclosure → Code Trace

### Disclosure 1: Resolve-Before-Context Pipeline (Tier 1)

| Concept | Source File | Lines / Identifier |
|---|---|---|
| Directive registry | `src/perseus/registry.py` | L11-27 `DirectiveSpec`, L32 `DIRECTIVE_REGISTRY`, L35-78 `_bind_registry()` |
| Render pipeline entry | `src/perseus/renderer.py` | `render_source()`, `_render_lines()` |
| Directive parsing | `src/perseus/renderer.py` | `_parse_directive()` — regex-based `@name args` extraction |
| Resolver dispatch | `src/perseus/registry.py` | `_call_resolver()` L238 — security-gated dispatch |
| Compile-before-context claim | `src/perseus/renderer.py` | Entire flow: parse → resolve → cache → output — all before LLM sees output |
| Cache layer | `src/perseus/renderer.py` | `cache_get()`, `cache_set()`, `_cache_key()` — TTL-based, dependency-fingerprinting planned for v1.1 |
| Build artifact | `perseus.py` | Single-file concatenation, ~14,900 lines |

### Disclosure 2: Checkpoint-Correlated Implicit Reinforcement (Tier 1)

| Concept | Source File | Lines / Identifier |
|---|---|---|
| Pythia engine | `src/perseus/pythia.py` | `cmd_suggest()`, `run_llm()`, `_pythia_online_score_adjustments()` |
| Checkpoint integration | `src/perseus/checkpoint.py` | `cmd_checkpoint()` — records task timestamps for correlation |
| Drift detection | `src/perseus/pythia.py` | `@drift` directive resolver, `_pythia_online_score_adjustments()` |
| Deterministic fallback | `src/perseus/pythia.py` | Rule-based scoring when `memory.pattern_extractor` ≠ "daedalus" |
| `@drift` directive | `src/perseus/registry.py` | L52 — `resolve_drift`, tier 2 |

### Disclosure 3: Five-Site Trust Boundary Architecture (Tier 1)

| Concept | Source File | Lines / Identifier |
|---|---|---|
| Trust gates | `src/perseus/audit.py` | `_audit_trust_gate()` — workspace boundary enforcement |
| Shell execution gate | `src/perseus/registry.py` | L238-243 — `executes_shell` gate via `allow_query_shell` |
| Agent shell gate | `src/perseus/registry.py` | L62 `@agent` — independent `allow_agent_shell` gate (v1.0.5) |
| Workspace boundary | `src/perseus/directives/query.py` | L105-108 — `cwd=workspace` enforcement (v1.0.5) |
| Redaction gate | `src/perseus/redaction.py` | `redact_value()` — applied before pythia/audit/cache persistence (v1.0.5) |
| Plugin hash verification | `src/perseus/registry.py` | L307-345 — SHA-256 verification per plugin file (v1.0.5) |
| Permission profiles | `src/perseus/config.py` | L231-265 — strict/balanced/power-user profiles |
| Audit log | `src/perseus/audit.py` | `audit_event()` — JSONL append-only log |

### Disclosure 4: Resolver-Generator Boundary with Citation Gate (Tier 2)

| Concept | Source File | Lines / Identifier |
|---|---|---|
| `@synthesize` directive | `src/perseus/registry.py` | L69 — tier 3 block directive |
| `@constraint` directive | `src/perseus/registry.py` | L67 — block directive for validation constraints |
| Citation gate logic | `src/perseus/renderer.py` | L764-835 — `@synthesize` block handler, exact-match string comparison, drops uncited claims (L835) |
| `generation.enabled` gate | `src/perseus/config.py` | L153 — defaults to `false` |
| Permission profiles (all disable generation) | `src/perseus/config.py` | L240, L251, L262 — all three profiles keep generation off |
| Synthesis function | `perseus.py` (built) | L12225 `synthesize_question()` — LLM call with citation instructions |

### Disclosure 5: Static Directive Dependency Graph + Predictive Prefetch (Tier 2)

| Concept | Source File | Lines / Identifier |
|---|---|---|
| `@graph` command | `src/perseus/cli.py` | `cmd_graph()` — exports dependency graph as JSON |
| Prefetch engine | `src/perseus/renderer.py` | `_prefetch_trust_block_reason()` — eligibility decision tree |
| Trust-gated prefetch | `src/perseus/directives/query.py` | L464 `_prefetch_trust_block_reason()` |
| Directive metadata for graph | `src/perseus/registry.py` | `DirectiveSpec` fields: `reads_files`, `mutates_state`, `cacheable`, `tier` |
| Dependency resolution | `src/perseus/renderer.py` | `_resolve_dependencies()` — walks `@include` chains |

### Disclosure 6: File-Based Async Multi-Agent Coordination / Agora (Tier 2)

| Concept | Source File | Lines / Identifier |
|---|---|---|
| Agora engine | `src/perseus/agora.py` | Full module — task file read/write, claim/release protocol |
| `@agora` directive | `src/perseus/registry.py` | L50 — `resolve_agora`, tier 2 |
| Inbox / inter-agent messaging | `src/perseus/inbox.py` | Full module — `@inbox` directive, file-based message passing |
| Checkpoint coordination | `src/perseus/checkpoint.py` | `O_CREAT | O_EXCL` atomic locking, namespaced store |
| Task file format | `src/perseus/agora.py` | YAML frontmatter: `status`, `agent`, `depends_on`, `blocks` |

---

## Test Coverage of Patent Claims

| Claim Area | Test File | Key Tests |
|---|---|---|
| Resolve-before-context correctness | `tests/test_renderer.py` | ~100+ tests covering all directives, edge cases |
| Trust boundaries | `tests/test_edge_cases.py` | Symlink escapes, workspace boundaries, context overflow |
| Citation gate | `tests/test_synthesize.py` | Citation validation, dropped claims, conflict detection |
| Prefetch / cache | `tests/test_prefetch.py` | Eligibility, cache hit/miss, TTL |
| Multi-agent coordination | `tests/test_agora.py` | Claim/release, task lifecycle, concurrent access |
| IP evidence | `tests/test_ip_evidence.py` | E1-E6 exhibits — cold/warm benchmarks, prefetch traces, citation gate demos |
| **Full suite** | **all tests/** | **752 passed, 0 failed, 1 skip, 1 xfail** |

---

## Key Dates

- **First commit:** Check `git log --oneline --reverse | head -1` for earliest public timestamp
- **Provisional patent filed:** 2026-05-19
- **Non-provisional deadline:** 2027-05-19
- **Defensive disclosures published:** 2026-05-19 (commits 0bb24ad + preceding)
- **v1.0.5 security review:** 2026-05-28 (Thomas Connally review)
