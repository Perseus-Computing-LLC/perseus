# Perseus 🪞

> *"Hold up the mirror so you can face the Medusa without being turned to stone."*

Perseus is a **live context engine** for AI assistants. It solves the cold-start problem: every session begins with an AI that has no idea what's running, what you've been working on, which tools are available, or where you left off. Perseus resolves that state **before** it hits the context window — and writes waypoints **during** a session so the next one can resume exactly where it left off.

Built as a companion to [Hermes Agent](https://hermes-agent.nousresearch.com), but designed to be assistant-agnostic.

**Status: Alpha v0.1 — Core CLI built and working.**

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

Any `.md` file beginning with `@perseus v0.1` becomes live — no special extension required. Compatible with `AGENTS.md`, `CLAUDE.md`, and any doc an assistant would read.

### 2. Session Waypoints (`perseus checkpoint`)
Writes incremental resumption state during a session. If the connection drops — service restart, timeout, network blip — the next session loads the last waypoint and picks up without re-orientation.

```
✅ Checkpoint written: 2026-05-18T0649.yaml
   Task:   Setting up ntfy webhook integration
   Status: handler written, pending test run
   Next:   run pytest tests/test_webhook.py
```

### 3. Pythia — Tool Oracle (`perseus suggest`)
Given a task description and the current environment state, ranks the highest-utility tool paths: which skill to load, which integration to use, which approach minimizes friction. The Medusa of tool selection — faced with the mirror instead of directly.

Named **Pythia** (the Oracle at Delphi who gave Perseus his mission). Oracle Corp is litigious.

```
$ perseus suggest "deploy the staging container"

# → structured prompt emitted with live env snapshot:
#   - 102 available skills with freshness
#   - service health checks
#   - recent sessions digest
#   - last checkpoint
# → assistant reads prompt, produces ranked recommendations inline
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Perseus                         │
│                                                  │
│  ┌──────────────┐  ┌───────────────────────────┐ │
│  │   Renderer   │  │    Waypoint Store         │ │
│  │              │  │                           │ │
│  │ @query   ✅  │  │  checkpoints/ (history)   │ │
│  │ @read    🔶  │  │  latest.yaml  (symlink)   │ │
│  │ @session ✅  │  └───────────────────────────┘ │
│  │ @services ✅ │                                │
│  │ @skills  ✅  │  ┌───────────────────────────┐ │
│  │ @date    ✅  │  │    Pythia (Tool Oracle)   │ │
│  │ @waypoint ✅ │  │                           │ │
│  │ @if/cache 🔶 │  │  task → ranked tool paths │ │
│  └──────────────┘  └───────────────────────────┘ │
└─────────────────────────────────────────────────┘
         ↓ rendered context
┌─────────────────────────────────────────────────┐
│              AI Assistant (Hermes)               │
│   Starts with complete, accurate picture.        │
│   No pre-flight tax. Resume from waypoint.       │
└─────────────────────────────────────────────────┘
```

---

## Quick Start

**Requirements:** Python 3.10+, `pyyaml` (`pip install pyyaml`)

```bash
# Install
cp perseus.py ~/.local/bin/perseus
chmod +x ~/.local/bin/perseus

# Configure (set absolute paths for your environment)
mkdir -p ~/.perseus
cat > ~/.perseus/config.yaml << 'EOF'
oracle:
  skill_dir: /home/you/.hermes/skills
hermes:
  sessions_dir: /home/you/.hermes/sessions
EOF

# Render a live context document
perseus render /workspace/myproject/.perseus/context.md

# Write a session waypoint
perseus checkpoint \
  --task "Implementing @query directive" \
  --status "resolver written, tests pending" \
  --next "add to render loop, test with context.md" \
  --workspace /workspace/perseus

# Recover last waypoint
perseus recover

# Get Pythia recommendations
perseus suggest "I need to search for a pattern across a large codebase"
```

---

## Directives

Directives appear inside `.md` files that start with `@perseus v0.1`. The file renders to plain markdown — no special syntax visible to the reader.

| Directive | Status | Notes |
|---|---|---|
| `@query "shell cmd"` | ✅ | Runs command, embeds output as code block |
| `@skills [flag_stale=true] [category=X]` | ✅ | Scans Hermes skills dir, reads frontmatter |
| `@services` (YAML block) | ✅ | HTTP health checks with latency |
| `@session [count=N] [topic="..."]` | ✅ | Recent session digest from sessions dir |
| `@date format="YYYY-MM-DD HH:mm z"` | ✅ | Live date/time inline or standalone |
| `@waypoint [ttl=N]` | ✅ | Latest checkpoint rendered inline |
| `@prompt...@end` | ✅ | AI instruction callout block |
| `@read <file> path="..."` | 🔶 Phase 2 | File/JSON/YAML key extraction |
| `@env VAR [fallback="..."]` | 🔶 Phase 2 | Environment variable with fallback |
| `@if/@else/@endif` | 🔶 Phase 2 | Conditional context blocks |
| `@include <file>` | 🔶 Phase 2 | File inclusion |
| `@constraint...@end` | 🔶 Phase 3 | Machine-readable rules table |
| `@cache session/ttl=N` | 🔶 Phase 3 | Avoid re-running slow queries |

---

## Source File Format

```markdown
@perseus v0.1

@prompt
This document was rendered live by Perseus. Trust all values.
@end

# Session Context — @date format="YYYY-MM-DD HH:mm z"

## Last Session
@waypoint ttl=86400

## Environment
@query "git log --oneline -5"
@query "docker ps --format 'table {{.Names}}\t{{.Status}}'"

## Available Skills
@skills flag_stale=true

## Services
@services
  - name: Hermes WebUI
    url: http://localhost:7779
  - name: My App
    url: http://localhost:3001/health

## Recent Sessions
@session count=5
```

---

## Integration with Hermes Agent

Perseus is designed to wire into Hermes via `AGENTS.md` injection and `workdir` cron:

```yaml
# .hermes/config.yaml (excerpt)
context_script: ~/.perseus/render.sh   # runs before each session opens
```

Any workspace can opt in by adding `@perseus v0.1` to the first line of its `AGENTS.md` or `CLAUDE.md`. Perseus pre-renders it and hands the assistant a live, accurate document.

---

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Close the Pythia loop; `@query` directive; workdir auto-injection | 🔶 Active |
| **Phase 2** | `@read`, `@env`, `@if/@else`, `@include` — real project AGENTS.md opt-in | Planned |
| **Phase 3** | Cache layer; smart `recover`; `@constraint` | Planned |
| **Phase 4** | Perseus renders its own roadmap live (self-bootstrapping) | Planned |
| **Phase 5** | `--llm` flag for local model; accepted-recommendation training data; `perseus init` | Future |

Full detail: [ROADMAP.md](./ROADMAP.md)

---

## Etymology

**Perseus** — the hero who slew Medusa by using a mirrored shield rather than looking at her directly. The Medusa here is the chaos of knowing which tool, which context, which approach to use — paralyzing in complexity when faced head-on. The mirror is live, resolved context: you face the complexity through an accurate reflection instead of being turned to stone by it.

**Hermes** provided Perseus with winged sandals, a sword, and guidance. This Perseus returns the favor.

**Pythia** — the Oracle at Delphi. She didn't make decisions; she surfaced the truth so the hero could. That's the Tool Oracle: it doesn't choose for you, it shows you the ranked paths clearly so you can move.

---

## License

MIT
