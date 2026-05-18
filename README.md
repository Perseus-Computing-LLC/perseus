# Perseus 🪞

> *"Hold up the mirror so you can face the Medusa without being turned to stone."*

Perseus is a **live context engine** for AI assistants. It solves the cold-start problem: every session begins with an AI that has no idea what's running, what you've been working on, which tools are available, or where you left off. Perseus resolves that state **before** it hits the context window — and writes waypoints **during** a session so you can resume exactly where you were interrupted.

Built as a companion to [Hermes Agent](https://hermes-agent.nousresearch.com), but designed to be assistant-agnostic.

---

## The Problem

Every AI assistant session starts cold. Before useful work can begin, the assistant burns turns on orientation:

- What services are running?
- What were we working on last time?
- Which tool is the right one for this task?
- Where did we leave off when the connection dropped?

This is the **pre-flight tax** — and it compounds across every session, every day, every developer.

Static markdown files (CLAUDE.md, AGENTS.md, READMEs) make it worse: they were accurate when written and are stale by the time they're read. The assistant either trusts outdated data or stops to verify it, spawning more tool calls, consuming more context, delaying actual work.

---

## The Solution

Perseus has three interlocking components:

### 1. Live Context Injection (`perseus render`)
Resolves a session context document **before** it reaches the assistant's context window. No stale values, no pre-flight verification calls needed.

```
# Instead of:                          # Perseus renders:
"Port is 3001 (check .env)"      →    "Port: 3001 (live from .env)"
"47 tests (may be stale)"         →    "Tests: 52 passing (run 30s ago)"
"Check docker ps first"           →    "mongo-dev: Up 3h  redis-dev: Up 3h"
```

Directives supported: `@query` (shell), `@read` (file/JSON/YAML/env), `@session` (recent work digest), `@services` (health checks), `@skills` (available tools), `@if/@else` (conditional context), `@cache` (ttl/session scoping).

### 2. Session Waypoints (`perseus checkpoint`)
Writes incremental resumption state during a session. If the connection drops — service restart, timeout, network blip — the next session loads the last waypoint and picks up without re-orientation.

```
Waypoint written: 2026-05-18T06:49 CT
  Task: Setting up ntfy webhook integration
  Status: handler written, pending test run
  Next: run pytest tests/test_webhook.py
  Context: /workspace/ntfy-dev, branch: feature/webhook-auth
```

### 3. Tool Oracle (`perseus suggest`)
Given a task description and the current environment state, surfaces the highest-utility tool path: which skill to load, which integration to use, which approach minimizes latency and maximizes fidelity. The Medusa of tool selection — faced with the mirror instead of directly.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Perseus                         │
│                                                  │
│  ┌──────────────┐  ┌───────────────────────────┐ │
│  │   Renderer   │  │    Waypoint Store         │ │
│  │              │  │                           │ │
│  │ @query       │  │  session.md  (current)    │ │
│  │ @read        │  │  waypoints/  (history)    │ │
│  │ @session     │  │  recovery.md (last known) │ │
│  │ @services    │  └───────────────────────────┘ │
│  │ @skills      │                                │
│  │ @if/@cache   │  ┌───────────────────────────┐ │
│  └──────────────┘  │    Tool Oracle            │ │
│                    │                           │ │
│                    │  task → ranked tool paths │ │
│                    └───────────────────────────┘ │
└─────────────────────────────────────────────────┘
         ↓ rendered context
┌─────────────────────────────────────────────────┐
│              AI Assistant (Hermes)               │
│   Starts with complete, accurate picture.        │
│   No pre-flight tax. Resume from waypoint.       │
└─────────────────────────────────────────────────┘
```

---

## Integration with Hermes Agent

Perseus is designed to wire into Hermes via `AGENTS.md` injection and the `workdir` cron job feature:

```yaml
# .hermes/config.yaml (excerpt)
context_script: ~/.perseus/render.sh   # runs before each session
checkpoint_hook: ~/.perseus/checkpoint.sh  # called on session events
```

A rendered Perseus context document is injected into every session that uses a configured workspace — same mechanism as `AGENTS.md`, but always live.

---

## Roadmap

### v0.1 — Foundation
- [ ] `perseus render` — directive-based context renderer (shell, file, env)
- [ ] `@query`, `@read`, `@env`, `@date`, `@if`, `@cache` directives
- [ ] AGENTS.md / CLAUDE.md compatible output format
- [ ] Hermes `workdir` integration

### v0.2 — Waypoints
- [ ] `perseus checkpoint` — write resumption state
- [ ] `perseus recover` — load last waypoint into session context
- [ ] Cron job integration for automatic checkpointing
- [ ] Waypoint diffing (what changed since last checkpoint)

### v0.3 — Tool Oracle
- [ ] `perseus suggest <task>` — ranked tool/skill recommendations
- [ ] Environment-aware scoring (what's installed, what's healthy)
- [ ] Skill freshness tracking (stale skill detection)
- [ ] Integration fingerprinting (which services are actually live)

### v0.4 — Production Hardening
- [ ] Multi-workspace support
- [ ] TTL cache management
- [ ] Hermes plugin packaging
- [ ] Assistant-agnostic adapter layer (Claude Code, OpenAI, etc.)

---

## Etymology

**Perseus** — the hero who slew Medusa by using a mirrored shield rather than looking at her directly. The Medusa here is the chaos of knowing which tool, which context, which approach to use — paralyzing in complexity when faced head-on. The mirror is live, resolved context: you face the complexity through an accurate reflection instead of being turned to stone by it.

**Hermes** provided Perseus with winged sandals, a sword, and guidance. This Perseus returns the favor.

---

## Status

🚧 **Early design phase.** Architecture and roadmap are being defined.

---

## License

MIT
