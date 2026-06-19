# Phase 2 — Deep Integration Evaluation

**Date:** 2026-06-18  
**Scope:** Nexo (#16), poly-agent-mcp (#15), Interlock (#17)

---

## Nexo — Cognitive Runtime with Startup Preflight

**Repo:** <https://github.com/wazionapps/nexo>  
**License:** AGPL v3.0  
**Maturity:** 950 commits, 376 tags, v7.37.3, active daily

### What It Is

Nexo is a local cognitive runtime that transforms AI agents from stateless assistants into "cognitive partners." It provides:

- Persistent SQLite memory with semantic recall
- 150+ MCP tools
- Startup preflight (session initialization, bootstrap context)
- Doctor diagnostics and self-healing
- Overnight learning and background jobs
- Email monitoring and automated task management
- Metacognitive guard with trust scoring
- Semantic router (18 decision kinds, 3-layer chain)

### Perseus Overlap Analysis

| Nexo Feature | Perseus Equivalent | Overlap |
|---|---|---|
| Startup preflight (`nexo_startup`, `nexo_smart_startup`) | Pre-session context rendering | **HIGH** |
| Core Rules injection (`cortex/task_open`) | `AGENTS.md` injection | **HIGH** |
| Managed bootstrap files for Claude Code, Codex | `perseus render` output | Medium |
| Persistent memory (local-context.db) | Mimir (mimir.db) | **HIGH** |
| Self-healing / doctor diagnostics | `perseus doctor` | Medium |
| Email monitor + task automation | N/A (operational context only) | None |
| Semantic router (mDeBERTa + cached LLM) | N/A | None |
| LoCoMo benchmark (F1 0.588) | No published benchmarks | None |
| 376 versioned releases | v1.0.8 | Nexo far ahead |

### Integration Assessment

**Can Perseus feed into Nexo?** Yes, but direction matters:

- **Nexo as consumer of Perseus context**: Perseus could render `@services`, `@health`, `@memory` into a markdown block that Nexo's `nexo_startup` tool injects as bootstrap context. This makes Perseus a "context provider" plugin for Nexo.
- **Perseus as consumer of Nexo state**: Perseus's `@memory` directive could query Nexo's `local-context.db` for pre-existing session knowledge.

**AGPL v3 concern:** Any code that links tightly with Nexo's runtime (importing Nexo modules, calling Nexo APIs) would need AGPL licensing. The safe integration path is **process-level** (stdio MCP) — Perseus calls Nexo's MCP tools over stdio, which doesn't trigger AGPL copyleft.

**Recommendation:** Author a **Nexo Integration Guide** showing Perseus as a pre-bootstrap context provider. Perseus renders workspace state → Nexo consumes it via `nexo_startup` → agent gets both operational awareness AND cognitive memory. No code changes to either project required.

---

## poly-agent-mcp — MULTI-AGENT ORCHESTRATION (DEAD)

**Repo:** <https://github.com/JentesI337/poly-agent-mcp>  
**License:** Not specified  
**Maturity:** **1 commit, 0 stars, 0 forks. Reference code only — not runnable.**

### What Happened

The original Discord Scout LLM classifier scored this at **7.0** — the highest in the entire list. On actual inspection:

- Single commit: "Mirror of the poly-agent engine's MCP server. Reference code — not runnable standalone."
- 0 stars, 0 forks, last activity April 2026
- No subsequent development

**This project was severely over-scored by the LLM classifier.** It's a reference dump, not a working system. The poly-agent engine itself may exist elsewhere (not linked), but the public MCP server is abandonware.

### Revised Score

**Original:** 7.0 → **Revised: 1.0** (reference code dump, not a functioning project)

### Action

Remove from active integration pipeline. If the author publishes a runnable version, re-evaluate.

---

## Interlock — MCP Runtime Trust Layer

**Repo:** <https://github.com/MaazAhmed47/Interlock>  
**License:** Apache 2.0 ✅  
**Maturity:** 191 commits, 291 tests, pre-release/design-partner stage

### What It Is

A self-hosted MCP security gateway that detects tool-surface drift after approval:

1. **Baseline** MCP tools when first approved
2. **Monitor** for schema, data access, external reach, side effect, auth scope, or behavior changes
3. **Quarantine** risky changes before execution (blocks the tool call)
4. **Record** tamper-evident audit evidence with hash-chain verification
5. **Emit Security Receipts** for drift, policy, and quarantine decisions

### Architecture

- Python backend (FastAPI/Flask) + React frontend (`interlock-web/`)
- MCP gateway proxy sits between agent and MCP servers
- Trust registry tracks approved tool baselines
- Drift classifier scores risk and triggers quarantine
- Tamper-evident audit log with hash-chain verification
- Helm charts for Kubernetes deployment
- Live demo at <https://getinterlock.dev>

### Perseus Integration: `@trust` Directive

The plan envisioned Perseus surfacing Interlock status. This is actionable:

**Perseus `@trust` directive** would:
1. Query Interlock's `/api/trust/status` endpoint (or Interlock's MCP tools)
2. Return a trust summary: tools approved, quarantined, blocked
3. Render as a markdown table in Perseus context:
   ```
   | Tool | Status | Last Verified | Risk |
   |---|---|---|---|
   | file_read | ✅ Approved | 2h ago | Low |
   | db_query | ⚠️ Quarantined | 15m ago | MEDIUM — schema drift detected |
   | deploy | 🔒 Blocked | 1d ago | CRITICAL — new network egress |
   ```

### Implementation Path

1. **Interlock already exposes MCP tools** — Perseus calls Interlock's MCP server via stdio
2. **Perseus `@trust` directive** reads Interlock state and renders trust summary
3. **Minimal integration surface** — Perseus just reads; Interlock does the security heavy lifting

**Effort:** ~2-3 days to implement `@trust` directive in Perseus
**Value:** First tangible security integration — differentiates Perseus from all other context engines

---

## Memory Connector — Deprioritized

The original Phase 2 plan called for "Build Perseus connector proof-of-concept for top memory backend." After evaluation:

| Candidate | License | Maturity | Viable? |
|---|---|---|---|
| YourMemory | CC BY-NC 4.0 | 230 commits | ❌ Non-commercial |
| memory-mesh | MIT | 5 commits | ❌ Too early |
| memtrace-public | Proprietary EULA | 103 commits | ❌ Proprietary |
| codebase-memory-mcp | MIT | 862 commits | ✅ But code-structural, not agent memory |

**Recommendation:** Repurpose this item as "codebase-memory-mcp integration via `@codebase` directive" — covered in the Phase 1 competitive analysis.

---

## Phase 2 Summary

| Item | Original Plan | Actual Outcome | Action |
|---|---|---|---|
| Memory connector | YourMemory or memory-mesh | Neither viable (license/immaturity) | Skip. Re-evaluate Q4 2026. |
| Interlock integration | `@trust` directive | Apache 2.0, 191 commits, viable | Implement `@trust` next |
| Nexo evaluation | Startup preflight overlap | AGPL v3, process-level integration possible | Author integration guide |
| poly-agent-mcp guide | Integration doc | 1 commit, dead project | Remove from pipeline |

### Next Immediate Step

Implement Perseus `@trust` directive integrating with Interlock — the highest-value, lowest-blocker item remaining.
