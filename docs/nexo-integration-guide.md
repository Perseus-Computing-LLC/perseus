# Perseus × Nexo Integration Guide

**Status:** Reference / Monitoring  
**License note:** Nexo is AGPL v3.0. This guide documents process-level integration — no code from either project is linked or imported.

---

## Overview

**Nexo** (<https://github.com/wazionapps/nexo>) is a local cognitive runtime that transforms MCP-compatible AI agents from stateless assistants into memory-preserving cognitive partners. It provides persistent memory, semantic recall, startup preflight, doctor diagnostics, overnight learning, and 150+ MCP tools.

**Perseus** (<https://github.com/Perseus-Computing-LLC/perseus>) is a live context engine that pre-resolves `@services`, `@health`, `@memory`, and other directives into rendered markdown before the AI assistant opens its context file.

Together: Perseus renders operational context → Nexo injects it at startup → Agent gets both situational awareness AND cognitive memory.

---

## The "Startup Preflight" Overlap

Both Perseus and Nexo serve context at session start:

| Aspect | Perseus | Nexo |
|---|---|---|
| Context injection point | AGENTS.md / context.md | `nexo_startup` MCP tool |
| What it injects | Services, health, memory, skills, tasks | Core rules, calibration, session history, memory |
| Trigger | File-based (assistant reads AGENTS.md) | MCP-based (assistant calls nexostartup) |
| Customizable | Per-workspace context.md | Per-agent calibration + core rules |

The overlap is in **pre-session context delivery** — both aim to give the agent information before it starts working. The key difference: Perseus is file-driven (simpler, works with any assistant), Nexo is tool-driven (deeper integration, richer state).

---

## Integration Pattern: Perseus → Nexo Bootstrap

### Architecture

```
┌──────────────────────────────────────────────────┐
│                  AI Agent Session                  │
│                                                    │
│  1. Agent reads AGENTS.md (Perseus-rendered)       │
│     ├── @services: 3 healthy, 1 down               │
│     ├── @health: 2 stale skills                    │
│     └── @trust: 12 approved, 1 quarantined         │
│                                                    │
│  2. Agent calls nexostartup (Nexo MCP tool)       │
│     ├── Core rules from Nexo                       │
│     ├── Calibrated behavior profile                │
│     ├── Session memory from prior conversations    │
│     └── NOW ALSO: Perseus context (via @perseus)   │
│                                                    │
│  3. Agent has complete picture:                    │
│     - Operational awareness (Perseus)              │
│     - Cognitive memory (Nexo)                      │
└──────────────────────────────────────────────────┘
```

### Step-by-step Setup

#### 1. Install both tools

```bash
# Install Perseus
pip install perseus-ctx

# Install Nexo
npm install -g nexo-brain
nexo setup
```

#### 2. Configure Perseus to render operational context

Create `.perseus/context.md` in your workspace:

```markdown
@perseus
@services
@health
@memory
@trust
```

Run the render to verify:

```bash
perseus render .perseus/context.md
```

#### 3. Configure Nexo to consume Perseus context

In Nexo's configuration (managed via `nexo setup` or `~/.nexo/runtime/`), add Perseus as a pre-bootstrap context source. Two approaches:

**Approach A — File injection (simplest)**

Configure Nexo's `nexo_startup` to read the Perseus-rendered AGENTS.md file:

```json
{
  "startup": {
    "preflight_sources": [
      "file://./AGENTS.md"
    ]
  }
}
```

Perseus renders to AGENTS.md, Nexo reads it at startup.

**Approach B — MCP interop (recommended)**

Nexo's `nexo_startup` tool can call Perseus's MCP server via stdio:

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve"]
    }
  }
}
```

Then Nexo's startup preflight calls `perseus_health`, `perseus_services`, etc. via MCP and aggregates the results.

#### 4. Verify end-to-end

Start a session and check the agent's context:

1. Agent reads AGENTS.md → sees Perseus operational context
2. Agent calls `nexo_startup` → gets cognitive memory + Perseus context
3. Agent now knows: service health, stale skills, MCP trust status, past decisions, user preferences

---

## AGPL v3 License Notice

⚠️ **Nexo is licensed under AGPL v3.0.** This guide documents process-level integration only — no Nexo code is imported, linked, or distributed with Perseus. The integration surface is:

- **Perseus → Nexo:** Perseus renders files that Nexo reads (file-level)
- **Perseus → Nexo (MCP):** Perseus exposes MCP tools that Nexo calls (stdio protocol)
- **No code dependency:** Neither project imports the other

AGPL copyleft is triggered by linking/importing code, not by inter-process communication over standard protocols (MCP, file I/O). This integration pattern is safe.

---

## Practical Example

**Scenario:** You're working on a microservice architecture with 6 services, 3 MCP servers, and an Interlock security gateway.

**Without integration:**
- Agent starts cold — asks "what services are running?" → you answer → wastes 3 turns
- Agent doesn't know MCP tool trust status → calls a quarantined tool → blocked
- Agent forgets last week's architecture decision → re-asks the same question

**With Perseus + Nexo:**
1. Perseus renders: 4 services healthy, 1 degraded, 1 down. 12 tools approved, 1 quarantined.
2. Nexo startup injects: "Last week we decided to use Postgres 16, not 15." + "User prefers conciseness."
3. Agent starts work immediately without clarification turns.

---

## Related Documentation

- [Nexo README](https://github.com/wazionapps/nexo) — full feature list, 150+ MCP tools
- [Perseus Directives](docs/DIRECTIVES.md) — all available @-directives
- [Phase 2 Deep Integration](docs/phase2-deep-integration.md) — evaluation methodology
- [Competitive Analysis Phase 1](docs/competitive-analysis-phase1.md) — cognirepo analysis

---

*Guide authored: 2026-06-18 | Phase 2 of Discord Scout Integration Plan*
