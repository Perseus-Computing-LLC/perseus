# Perseus™ 🪞

**Perseus is a live context engine for AI assistants.** It solves the cold-start problem — every new session, the assistant already knows what's running, what you were working on, and what tools exist. No orientation phase. No pre-flight tax. Works with any assistant that reads a file: **Claude Code, Cursor, Codex, Hermes, Rovo Dev.**

[![CI](https://github.com/tcconnally/perseus/actions/workflows/test.yml/badge.svg)](https://github.com/tcconnally/perseus/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/perseus-ctx)](https://pypi.org/project/perseus-ctx/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[**perseus.observer →**](https://perseus.observer)

![Perseus demo — before/after cold-start](demo.gif)

![Perseus Efficiency — Cold vs Warm Render Speed](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-efficiency.svg)

---

## Install

```bash
pip install perseus-ctx
```

No pip? Single-file drop-in:

```bash
curl -fsSL https://raw.githubusercontent.com/tcconnally/perseus/main/perseus.py \
  -o ~/.local/bin/perseus && chmod +x ~/.local/bin/perseus
```

---

## The Problem

Every AI assistant session starts cold. Before useful work begins, the assistant burns turns on orientation — checking which services are running, reading stale config files, rediscovering where you left off. Static markdown files (`.cursorrules`, `CLAUDE.md`) rot immediately. The port you wrote down has changed. The container that was "always running" hasn't been started since Tuesday.

**Stale context isn't neutral. It's drag.**

---

## The Fix: Resolve Before Context

Perseus is a pre-processor. You write directives in a source document — `@query`, `@services`, `@waypoint` — and Perseus resolves them at render time, then outputs plain markdown. The assistant reads **verified facts**, not instructions to go find facts.

```
Without Perseus                     With Perseus
────────────────────────────────    ──────────────────────────────────
"Port is 3001 (check .env)"    →   Port: 3001
"47 tests (may be stale)"      →   Tests: 540 passing (run 8s ago)
"Check docker ps first"        →   mongo-dev: Up 4h 12m
"Where did we leave off?"      →   Checkpoint: webhook handler written,
                                              pending test run
```

This isn't a replacement for `CLAUDE.md` — it's a pre-processor you bolt onto **any** `.md` file. Add `@perseus` to line 1 and it becomes live. The assistant never sees directive syntax. It sees a document that was already true.

---

## 30 Seconds to Live Context

```bash
perseus init /workspace/myproject          # scaffold a source document
perseus render .perseus/context.md --output CLAUDE.md  # render to whatever your assistant reads
```

That's it. The output file name is the only assistant-specific detail:

| Assistant | Output file |
|---|---|
| Claude Code | `CLAUDE.md` |
| Hermes Agent | `.hermes.md` |
| Cursor | `.cursorrules` or `.cursor/context.md` |
| Codex | `AGENTS.md` |
| Rovo Dev | `AGENTS.md` |
| Any other | Whatever your assistant reads at session start |

Keep it fresh with `cron`, `launchd`, `systemd`, or `perseus watch` — see the [Integration Guide](./docs/HERMES_INTEGRATION.md) for auto-refresh setups.

---

## Proof

- **40× speedup** — 500 `@query` directives render in 0.28s warm (vs 11.5s cold) with `@cache ttl=300`. Warm render time is **constant** regardless of directive count.
- **1,000,000 directives in 22 seconds** — 22μs per directive, 31 MB file, 3M output lines, zero crashes. The ceiling is file I/O, not Perseus logic.
- **120-agent swarm, 0 failures** — 30 developers × 4 agents each, 150 concurrent checkpoint writes in 9.7s on a shared store. Atomic `O_CREAT | O_EXCL` locking — zero collisions, zero corruption.
- **540 tests passing** — every directive, parser edge case, lock contention scenario, and trust gate has coverage.

![Perseus Cold vs Warm — @cache eliminates subprocess cost](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-cold-vs-warm.svg)

---

## How It Works

You write this:

```markdown
@perseus v0.4

# Context — @date format="YYYY-MM-DD HH:mm z"

## What's Running
@query "docker ps --format 'table {{.Names}}\t{{.Status}}'"

## Last Session
@waypoint ttl=86400

## Ports
@read .env key="API_PORT" fallback="3001"
```

Perseus renders this:

```markdown
# Context — 2026-05-18 08:33 CDT

## What's Running
mongo-dev    Up 4 hours
redis-dev    Up 4 hours

## Last Session
Checkpoint written: 2026-05-18T08:28
Task: webhook handler — written, pending test run
Next: run pytest tests/test_webhook.py

## Ports
3001
```

The assistant never sees a directive. It sees a document that was already true.

Full directive reference: [`docs/DIRECTIVES.md`](./docs/DIRECTIVES.md) (20 directives: `@query`, `@read`, `@env`, `@services`, `@waypoint`, `@agora`, `@memory`, `@skills`, `@validate`, `@synthesize`, and more — plus `@cache` modifiers).

---

## Session Waypoints

The Fates cut the thread when the connection drops. Waypoints are how you pick it back up.

```bash
perseus checkpoint \
  --task "Implementing webhook integration" \
  --status "handler written, pending test run" \
  --next "run pytest tests/test_webhook.py" \
  --workspace /workspace/myproject
```

The next session recovers immediately with `perseus recover` — workspace-aware, freshness-gated, no re-orientation.

---

## Multi-Agent Coordination

Checkpoints aren't just for session recovery — they're the backbone of multi-agent relay. Each developer runs 3–5 AI agents that coordinate internally via checkpoint handoff. Clusters talk to each other through shared inbox and agora task boards.

```
dev-01: [architect → implementer → reviewer → tester]  ─┐
dev-02: [architect → implementer → reviewer → tester]  ─┤
...                                                      ├─ shared checkpoint store
dev-30: [architect → implementer → reviewer → tester]  ─┘     (namespaced + lock-protected)
```

Proven at enterprise scale — see [Multi-Agent Relay](./docs/EXAMPLES.md#subagent-handover-zero-tax-orientation).

---

## Architecture

```
Source document (.perseus/context.md)
  @perseus v0.4
  @query "git log --oneline -5"          ┐
  @read .env key="PORT"                  │  Directives resolved
  @waypoint ttl=86400                    │  before context window.
  @services                              │  Cache layer avoids
    - name: My App                       │  re-running slow queries.
      url: http://localhost:3001/health  ┘
          │
          ▼ perseus render
  Resolved markdown (facts, not instructions)
          │
          ▼
  .hermes.md  ←── cron watchdog keeps this ≤5 min fresh
          │
          ▼
  AI context window — complete, accurate, zero pre-flight tax

  Waypoints: ~/.perseus/checkpoints/
  Cache:     ~/.perseus/cache/
  Config:    ~/.perseus/config.yaml
```

---

> *Athena didn't tell Perseus to fight Medusa. She handed him a shield — polished to a mirror — and let him see the monster clearly without meeting her gaze. The trick was never strength. It was reflection.*

![Perseus with the Head of Medusa — Benvenuto Cellini, 1545](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg/500px-Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg)

*Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Loggia dei Lanzi, Florence.*

**Perseus** slew Medusa by watching her reflection in Athena's polished shield — he never met her gaze directly. The Medusa here is the paralysis of facing a chaotic development environment. The mirror is resolved context: you see the situation clearly without being turned to stone by it. **Hermes** gave Perseus winged sandals and guidance. This Perseus returns the favor — giving Hermes (and every AI assistant) a way to navigate any workspace without the orientation tax.

---

## Documentation

Everything else lives in `docs/`:

- [**Website**](https://perseus.observer) — Landing page with benchmarks, assistant compatibility, and 30-second quickstart
- [**Quickstart**](./docs/quickstart.md) — Install, configure, and render your first context in 5 minutes
- [**Integration Guide**](./docs/HERMES_INTEGRATION.md) — Wire Perseus to Hermes, Codex, Claude Code, Cursor, or Rovo Dev
- [**Context Packs**](./docs/CONTEXT_PACKS.md) — Portable workspace context with assistant-specific profiles
- [**CLI Reference**](./docs/CLI.md) — Full command surface: `render`, `checkpoint`, `agora`, `suggest`, `serve`, `synthesize`, and more
- [**Directives Reference**](./docs/DIRECTIVES.md) — All 20 directives with modifiers and examples
- [**Performance Benchmarks**](./docs/PERFORMANCE.md) — Scaling data, cold vs. warm, enterprise profiles
- [**Container Runtime**](./docs/CONTAINER.md) — Docker and compose deployment
- [**Contributing**](./docs/CONTRIBUTING.md) — How to contribute code, directives, and tests
- [**Product Contract**](./docs/PRODUCT_CONTRACT.md) — What Perseus guarantees and what it doesn't
- [**Roadmap**](./ROADMAP.md) — 22 completed phases, 63 features shipped
- [**VSCode Extension**](./editors/vscode/README.md) — LSP server + editor integration

---

## License

MIT — see [LICENSE](./LICENSE).
