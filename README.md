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

Requires Python 3.10+. Zero dependencies beyond `pyyaml`.

No pip? Single-file drop-in — `perseus.py` is a compiled build artifact from the modular `src/perseus/` tree, not a hand-maintained monolith:

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

- **40× speedup** — 500 `@query` directives render in 0.28s warm (vs 11.5s cold) with `@cache ttl=300`. Cache backend: local filesystem JSON lookups (one file per directive, SHA-256 keyed). Warm render time is **constant** regardless of directive count.
- **10,000 directives in 0.36 seconds** — 35.6μs per directive. 23,402× faster than an LLM discovering the same information via tool calls (estimated 2.3 hours, assuming 2.5s per tool-call round-trip with 3-way batching). [Full benchmarks →](benchmark/edge-bench/)
- **1,000,000 directives in 22 seconds** — 22μs per directive (lightweight variable/static substitutions — `@env`, `@date`, simple `@read`; no subprocess I/O). 31 MB file, 3M output lines, zero crashes. The ceiling is file I/O, not Perseus logic.
- **120-agent swarm, 0 failures** — 30 developers × 4 agents each, 150 concurrent checkpoint writes in 9.7s on a **local NVMe filesystem** with atomic `O_CREAT | O_EXCL` locking — zero collisions, zero corruption. Network filesystems (NFS, SMB) require careful lock configuration; see [Caveats](#caveats).
- **573 tests passing** — every directive, parser edge case, lock contention scenario, trust gate, and context-overflow guard has coverage.
- **Compile-before-context validated** — Perseus resolves all directives in a single ~0.3s render pass, vs an estimated 7–8,338s for an LLM discovering the same information via tool calls. The gap widens with complexity: [26× → 23,402× faster](benchmark/edge-bench/).

![Perseus Cold vs Warm — @cache eliminates subprocess cost](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-cold-vs-warm.svg)

---

## Hardened

Perseus is tested against edge cases that challenge the "resolve before context" claim:

- **Workspace boundaries** — Symlink escapes (direct, relative, chained, to `/etc`) are all blocked. The trust-gate resolves symlinks to their real target before checking boundaries.
- **Context overflow protection** — `@read` and `@include` warn and truncate when files exceed `max_read_bytes` / `max_include_bytes` (512 KB default, `None` for unlimited).
- **Transitive resolution** — `@include` on `.md` files recursively renders directives up to `max_include_depth` (default 5), with cycle detection.
- **Integrity drift** — Optional `integrity_check` captures file mtimes before render and warns if any file changed mid-resolution.

[33 edge-case tests](tests/test_edge_cases.py) cover circular dependencies, race conditions, symlink escapes, and context overflow. These four config knobs live under `render:` in `~/.perseus/config.yaml`.

### Caveats

Perseus reads from a live filesystem — there is no snapshot isolation unless you enable `integrity_check`. Files can change between directive resolutions. The render output reflects whatever was on disk at the moment each directive resolved, **not** a single atomic point-in-time. This is the right tradeoff for a zero-dependency pre-processor (zero overhead by default, check when it matters), but it is not a database transaction.

The `O_CREAT | O_EXCL` checkpoint locking is atomic on local POSIX filesystems. Network filesystems (**NFS** < v4, **SMB**, cloud mounts) may not honor these semantics — if you run a multi-agent relay across machines, use a local disk or a filesystem with verified atomic-create support.

`perseus.py` is ~10,600 lines. It is a compiled build artifact produced by `scripts/build.py` from the modular `src/perseus/` tree. It is not hand-maintained as a single file. The source modules are the canonical form.

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

If an agent session crashes or a connection drops, Waypoints preserve the execution state.

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

Because Perseus outputs flat files and writes checkpoints to disk, downstream systems can build coordination on top of it without Perseus itself being an orchestration platform. The checkpoint store is namespaced and lock-protected — agents read each other's latest state from the filesystem rather than a message bus. Teams have extended this pattern to multi-agent relay, shared inboxes, and agora task boards.

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

> *Athena gave Perseus a mirror-shield, not a sword. He slew Medusa by watching her reflection — never meeting her gaze directly.*
>
> The Medusa is a chaotic development environment. The mirror is resolved context: you see the situation clearly without being paralyzed by it. **Hermes** gave Perseus winged sandals and guidance; this Perseus returns the favor — giving every AI assistant a way to navigate any workspace without the orientation tax.
>
> ![Perseus with the Head of Medusa — Benvenuto Cellini, 1545](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg/500px-Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg)
>
> *Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Loggia dei Lanzi, Florence.*

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
- [**Edge-Case Vetting**](./tests/test_edge_cases.py) — 33 tests covering circular deps, race conditions, symlink escapes, and context overflow
- [**Product Contract**](./docs/PRODUCT_CONTRACT.md) — What Perseus guarantees and what it doesn't
- [**Roadmap**](./ROADMAP.md) — 22 completed phases, 63 features shipped
- [**VSCode Extension**](./editors/vscode/README.md) — LSP server + editor integration

---

## License

MIT — see [LICENSE](./LICENSE).
