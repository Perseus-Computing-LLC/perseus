# CogniRepo Competitive Analysis

**Date:** 2026-06-18  
**Source:** Direct repo inspection (76 commits, active development)

---

## What CogniRepo Is

A local MCP context engine that combines memory persistence, code intelligence, and cross-agent handoff in a single Python package. Published on PyPI as `cognirepo`.

**Stack:** Python 3.11+ | FAISS (vectors) | NetworkX (graph) | tree-sitter (AST) | BM25 (sparse)  
**License:** MIT  
**MCP tools:** 34 (per README)  
**Active:** Yes (last commit Jun 17, 2026)

---

## Feature Overlap with Perseus

| Perseus Feature | CogniRepo Equivalent | Overlap |
|---|---|---|
| `@services` health directive | N/A (code-focused, not infra) | None |
| `@memory` / `@read` directives | `context_pack`, `retrieve_memory` | **HIGH** |
| `@file` directive | `lookup_symbol` (FAISS + AST) | **HIGH** |
| Mimir persistent memory | `store_memory`, `retrieve_memory`, BM25 + vector | **HIGH** |
| `@agent` directive (task board) | `prime_session` (session init) | Medium |
| `@skills` directive | N/A | None |
| `mimir_remember` / `mimir_recall` | `store_memory` / `retrieve_memory` | **HIGH** |
| `mimir_decay` (Ebbinghaus) | `cron/prune_memory.py` | Medium |
| `mimir_cohere` (grooming) | None observed | None |
| Perseus `@tools` directive | None | None |
| Cross-agent handoff | `last_context.json` shared | **HIGH** |
| User profiling | `get_user_profile()` | None |
| Error pattern avoidance | `record_error()` | None |
| Architecture decisions | `record_decision()` | Medium |
| Multi-repo org graph | `CHILD_OF` / `CALLS_API` edges | None |

---

## Direct Competition Analysis

### Where CogniRepo Wins

1. **Benchmarked token reduction**: Claims 50-84% reduction on Python repos, validated across 6 real projects (FastAPI, Flask, Celery, Ansible, Moby/Docker, Kubernetes). Perseus has no published token-savings benchmark.

2. **Code intelligence depth**: FAISS + tree-sitter + NetworkX provides AST-level code understanding. Perseus renders workspace state but doesn't parse code structure.

3. **User behavior profiling**: `get_user_profile()` adapts context depth and style to individual developers. Perseus has no user-adaptation layer.

4. **Error pattern learning**: `record_error()` builds institutional memory of past failures. Perseus's Mimir can store errors but doesn't learn from them automatically.

5. **Cross-agent handoff**: `last_context.json` works across Claude → Gemini → Cursor. Perseus's cross-agent story is configuration-based (AGENTS.md), not a shared context file standard.

### Where Perseus Wins

1. **Infrastructure awareness**: Perseus's `@services` directive checks service health, Docker status, latency — CogniRepo is purely code-focused, no infrastructure awareness.

2. **Operational scope**: Perseus handles git state, task boards, skill management, config drift detection. CogniRepo doesn't touch these.

3. **Tool count and structure**: Mimir has 27 focused tools with clear categories. CogniRepo's 34 tools cover more surface area but may have schema bloat (self-admitted: "MCP tool schema overhead ~4,100 tokens for 34 tools").

4. **Rust vs Python**: Mimir is a compiled Rust binary (fast, no runtime). CogniRepo is Python (slower indexing, pip dependency chain).

5. **Skill system**: Perseus's `@skills` directive surfaces procedural knowledge. CogniRepo has no equivalent.

6. **Ebbinghaus decay**: Mimir's decay model is scientifically grounded. CogniRepo's `prune_memory.py` is a cron job, not a cognitive model.

### Honest Assessment

CogniRepo is the most serious competitive threat to Perseus in the "context engine" space. It overlaps significantly with Perseus's context rendering AND Mimir's persistent memory. However:

- **CogniRepo is code-first.** Perseus is **workspace-first**. They optimize for different primary use cases.
- **CogniRepo excels at Python repos.** Perseus is language-agnostic.
- **CogniRepo doesn't do operational awareness.** Perseus's service health, git state, and task board rendering has no cognirepo equivalent.

### Strategic Response

1. **Lean into operational context** — Perseus's unique moat is infrastructure awareness. Double down on `@services`, `@health`, `@drift`.
2. **Add code intelligence as optional layer** — A `@codebase` directive that optionally invokes tree-sitter or codebase-memory-mcp for structural context.
3. **Publish token savings benchmarks** — CogniRepo's published numbers set the bar. Perseus needs comparable metrics.
4. **Cross-agent handoff standard** — Perseus's AGENTS.md + Perseus context injection is already a cross-agent standard. Market this harder.

---

## ContextForge Test Results

**Repo:** <https://github.com/zeroranker/contextforge>  
**Version:** 1.0.0 (1 commit, April 2026)  
**PyPI status:** NOT published (name squatted by unrelated project)

### Test Setup

Target: Perseus `src/` directory (50 files)  
Command: `contextforge forge src/ --budget 10000 -o /tmp/cf-perseus-src.md`

### Results

| Metric | Value |
|---|---|
| Files fully included | 7 |
| Files truncated | 1 |
| Files excluded | 42 |
| Token budget | 10,000 |
| Actual tokens | 10,272 (102.7% of budget) |
| Compression claimed | 95.1% |
| Output lines | 1,097 |

### Assessment

- **Works as advertised** — successfully excludes noise (tests, docs, changelogs) and keeps source signatures
- **Budget overrun** — exceeded 10K token budget by 2.7%. Acceptable for a first release
- **Single commit** — project appears to be an initial dump, not actively maintained
- **Strategy: "signature"** — keeps function/class signatures, truncates implementations. Good for code overview, loses implementation detail
- **Perseus integration viability**: As a pre-render step, ContextForge could compress large codebases before Perseus renders the workspace context. However, Perseus handles operational context, not source code — the overlap is minimal.

### Recommendation

ContextForge addresses a real problem (repo too big for context window) but Perseus's focus is operational context, not source compression. If the project matures, Perseus could invoke it as an optional `@compress` pre-render step for code-heavy workspaces. Monitor for now.

---

## Phase 1 Competitive Analysis: Summary

| Project | Type | Threat Level | Action |
|---|---|---|---|
| codebase-memory-mcp | Code structural memory | None (complementary) | Document, integrate via `@codebase` |
| memory-mesh | Personal data memory | None (too early) | Monitor, re-evaluate Sep 2026 |
| memtrace-public | Code structural memory | Medium (proprietary) | Watch for license change |
| YourMemory | Agent memory | HIGH (published benchmarks) | Publish Mimir benchmarks |
| cognirepo | Context + memory engine | HIGH (direct overlap) | Lean into operational context moat |
| ContextForge | Context compression | Low | Monitor for maturity |
