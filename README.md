# Perseus™ 🪞

**Perseus is a live context engine for AI assistants.** It solves the cold-start problem — every new session, the assistant already knows what's running, what you were working on, and what tools exist. No orientation phase. No pre-flight tax. Works with any assistant that reads a file: **Claude Code, Cursor, Codex, Hermes Agent (by NousResearch), Rovo Dev.**

[![CI](https://github.com/tcconnally/perseus/actions/workflows/test.yml/badge.svg)](https://github.com/tcconnally/perseus/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/perseus-ctx)](https://pypi.org/project/perseus-ctx/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[**perseus.observer →**](https://perseus.observer)

<!-- mcp-name: io.github.tcconnally/perseus -->

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
"47 tests (may be stale)"      →   Tests: all passing (run 8s ago)
"Check docker ps first"        →   mongo-dev: Up 4h 12m
"Where did we leave off?"      →   Checkpoint: webhook handler written,
                                              pending test run
```

Perseus replaces your assistant's context file — `CLAUDE.md`, `.cursorrules`, `AGENTS.md`, `.hermes.md` — with rendered live context. **If you already have a hand-written context file, migrate its static content into `.perseus/context.md` first.** Perseus overwrites the output file on every render. Add `@perseus` to line 1 of your source and it becomes live. The assistant never sees directive syntax. It sees a document that was already true.

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

Keep it fresh with `cron`, `launchd`, `systemd`, or `perseus watch` — see the [Integration Guide](./docs/HERMES_INTEGRATION.md) for Hermes auto-refresh setups. For other assistants (Codex, Cursor, Claude Code, Rovo Dev), follow the adapter patterns in [`spec/integration.md`](./spec/integration.md).

---

## Proof

- **450× cold→warm gap** — **50,000 `@query` directives in 1.36 seconds.** 612.6s without cache, 1.36s with `@cache ttl=300`. Warm time is flat regardless of scale — the render path is free. Cache: local filesystem JSON, one file per directive, SHA-256 keyed. [Raw data →](benchmark/cold-vs-warm.json)
- **301× faster than an LLM doing the same work** — enterprise simulation: **500 developers, 10 teams, 5-day workweek.** 16,250 context renders in 961s wall clock. **Zero failures.** An LLM burning tool-call round-trips would take 83 hours and cost thousands in API tokens. Perseus does it in 16 minutes for zero API cost. [Full enterprise benchmark →](benchmark/extreme_week_results.json)
- **1,000,000 directives in 22 seconds** — 22μs per directive. 31 MB file, 3M output lines, zero crashes. The ceiling is file I/O, not Perseus logic.
- **120-agent swarm, 0 collisions** — 30 developers × 4 agents each, 150 concurrent checkpoint writes in 9.7s on local NVMe with atomic `O_CREAT | O_EXCL` locking. Network filesystems (NFS, SMB) require careful lock config; see [Caveats](#caveats).
- **All green** — every directive, parser edge case, lock contention, trust gate, and overflow guard has coverage. <!-- test-count: 604 -->
- **Compile-before-context** — Perseus resolves everything in a single render pass (~0.3s) before the assistant reads the file. An LLM discovering the same facts via tool calls spends 7–298,388s getting there. The gap only widens: [26× → 23,402× → 301×](benchmark/edge-bench/).
- **10× cheaper per session, every provider, every scale** — see the token economics for full provider breakdowns. [Token economics →](benchmark/edge-bench/)

![Perseus Cold vs Warm — @cache eliminates subprocess cost](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-cold-vs-warm.svg)

---

## Hardened

Perseus is tested against edge cases that challenge the "resolve before context" claim:

- **Workspace boundaries** — Symlink escapes (direct, relative, chained, to `/etc`) are all blocked. The trust-gate resolves symlinks to their real target before checking boundaries.
- **Context overflow protection** — `@read` and `@include` warn and truncate when files exceed `max_read_bytes` / `max_include_bytes` (512 KB default, `None` for unlimited).
- **Transitive resolution** — `@include` on `.md` files recursively renders directives up to `max_include_depth` (default 5), with cycle detection.
- **Integrity drift** — Optional `integrity_check` captures file mtimes before render and warns if any file changed mid-resolution.

[Edge-case tests](tests/test_edge_cases.py) cover circular dependencies, race conditions, symlink escapes, and context overflow. These four config knobs live under `render:` in `~/.perseus/config.yaml`.

- **Plugin sandboxing** — Plugin directives with `executes_shell=True` are gated
  behind `allow_query_shell`, same as built-ins. Plugin errors are caught and
  surfaced as inline warnings — a broken plugin never breaks a render.

### Caveats

Perseus reads from a live filesystem — there is no snapshot isolation unless you enable `integrity_check`. Files can change between directive resolutions. The render output reflects whatever was on disk at the moment each directive resolved, **not** a single atomic point-in-time. This is the right tradeoff for a zero-dependency pre-processor (zero overhead by default, check when it matters), but it is not a database transaction.

The `O_CREAT | O_EXCL` checkpoint locking is atomic on local POSIX filesystems. Network filesystems (**NFS** < v4, **SMB**, cloud mounts) may not honor these semantics — if you run a multi-agent relay across machines, use a local disk or a filesystem with verified atomic-create support.

`perseus.py` is a compiled build artifact produced by `scripts/build.py` from the modular `src/perseus/` tree. It is not hand-maintained as a single file. The source modules are the canonical form.

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

### Extensibility in Practice

Macros reduce repetition. Pipes compose. Aliases keep things short:

```markdown
@macro health-check %service%
@query "curl -s http://%service%:8080/health"
@services
  - name: %service%
    url: http://%service%:8080/health
@endmacro

@q "git log --oneline -5" | @cache ttl=300
@health-check my-api
```

The assistant sees resolved output — never a directive.

Full directive reference: [`docs/DIRECTIVES.md`](./docs/DIRECTIVES.md).

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

![120-agent swarm demo — 120 agents claiming tasks via atomic sidecar locks, zero collisions](demo-swarm.gif)

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
  Plugins:  ~/.perseus/plugins/        ─┐  Discovered at render time.
            ~/.perseus/validators/       │  Macros, hooks, webhooks,
            ~/.perseus/formats/          ┘  and aliases load from config.

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
  Plugins:   ~/.perseus/plugins/
  Validators:~/.perseus/validators/
  Formats:   ~/.perseus/formats/
  Cache:     ~/.perseus/cache/
  Config:    ~/.perseus/config.yaml
```

---

## Extensibility (Hephaestus)

Perseus is extensible without source patching. Drop Python files into
`~/.perseus/` and the renderer discovers them at startup.

### Plugins

```python
# ~/.perseus/plugins/my_plugin.py
from perseus.registry import DirectiveSpec

def _resolve_service_status(args, cfg, workspace):
    import urllib.request
    try:
        resp = urllib.request.urlopen(args.strip(), timeout=5)
        return f"Status: {resp.status}"
    except Exception as e:
        return f"Error: {e}"

REGISTER = {
    "@service-status": DirectiveSpec(
        name="@service-status",
        resolver=_resolve_service_status,
        args=["url"],
        kind="inline",
        call_sig="acw",
        executes_shell=False,
        safe_for_hover=True,
        cacheable=True,
        summary="Check HTTP status of a URL",
    )
}
```

Use it in context files: `@service-status https://api.example.com/health`

Built-in directives always win collisions. Plugins respect the same permission
profile as built-ins (`executes_shell` gates behind `allow_query_shell`).

### Macros

Reusable directive compositions — no Python needed:

```markdown
@macro deploy %env% %version%
@query "kubectl rollout status deploy/app -n %env%"
@services
  - name: app-%env%
    url: https://%env%.example.com/health
@endmacro

@deploy production 2.3.1
```

Macros expand before directive resolution. Chaining supported up to depth 5 with
cycle detection. Define them in your context file or at `.perseus/macros.md`.

### Render Pipeline Hooks

Shell scripts or Python callbacks fire at render lifecycle points —
`on_render_start`, `on_directive_resolved`, `on_cache_hit`, `on_cache_miss`,
`on_render_complete`, `on_directive_error`:

```yaml
# ~/.perseus/config.yaml
hooks:
  enabled: true
  on_render_complete:
    - cmd: "notify-send 'Context refreshed'"
  on_directive_error:
    - plugin: "my_error_handler"
```

### Pipe Syntax

Chain directives with `|` for lightweight composition (max 3 stages):

```markdown
@query "ls services/" | @cache ttl=300
@read config.yaml path="endpoints" | @validate schema="endpoint-list"
```

Output of each stage becomes the first positional argument to the next.

### Tiered Context (Progressive Disclosure)

Not every question needs the full environment injected. A "what's 2+2?" shouldn't pull in Docker health checks, skill listings, and session digests. Perseus now ships tiered context rendering — the agent *is* the RAG.

```bash
perseus render .perseus/context.md --tier 1    # core context (~12 directives, lean)
perseus render .perseus/context.md --tier 2    # + services, skills, sessions
perseus render .perseus/context.md              # everything (backward compatible)
```

Three tiers, assigned per directive in the registry:

| Tier | Name | What goes here |
|------|------|---------------|
| **1** | Always | Core context — lightweight, always needed (`@date`, `@memory`, `@waypoint`, `@health`, `@env`) |
| **2** | Conditional | Task-specific, heavier (`@services`, `@skills`, `@session`, `@agora`, `@inbox`) |
| **3** | On-Demand | Bulky/expensive — the agent pulls it if needed (`@query`, `@read`, `@include`, `@tree`, `@list`) |

Directives above the tier limit are skipped and reported in a **Context Manifest**:

```
> 📋 Context Manifest — Tier limit: 1
>
> • @services (Tier 2 / Conditional) — Health-check listed services
> • @skills (Tier 2 / Conditional) — List available skills
> • @query (Tier 3 / On-Demand) — Run a shell command and embed stdout
>
> Re-run with `perseus render --tier 2` for conditional context,
> or `--tier 3` for full context on demand.
```

Template authors can override per-instance with `@tier:N`:

```markdown
@services @tier:1    # Always resolve this block, even though @services defaults to Tier 2
docker
nginx
@end
```

Set `render.default_tier: 1` in `~/.perseus/config.yaml` to make lean context the default for all renders. No embedding model, no LLM routing — one integer comparison per directive gates resolution. The agent sees what's available and can pull it on demand.

### Directive Aliases

Config-driven shorthand — single-pass, no recursive expansion:

```yaml
# ~/.perseus/config.yaml
directives:
  aliases:
    "@q": "@query"
    "@svc": "@services"
    "@stale-skills": "@skills flag_stale=true category=all"
```

Pre-defined aliases: `@q→@query`, `@r→@read`, `@svc→@services`, `@mb→@memory`,
`@ag→@agora`, `@wp→@waypoint`, `@sess→@session`. Config aliases override them.

### Custom Schema Validators

Plugin validators for domain-specific schemas:

```markdown
@query "cat endpoints.yaml" schema="plugin:endpoint_list"
```

Validator modules in `~/.perseus/validators/` export a `validate(value, schema_def)`
function returning `(valid: bool, message: str)`.

### Event Webhooks

POST render lifecycle events to an external URL with optional HMAC-SHA256 signing:

```yaml
webhooks:
  enabled: true
  url: "https://hooks.example.com/perseus-events"
  secret: "your-hmac-key"
  events:
    - on_render_start
    - on_render_complete
    - on_directive_error
```

### Structured JSON Output

```bash
perseus render .perseus/context.md --format json
```

Returns `{meta, resolved, directives, integrity}` — consumable by agents, CI
pipelines, and format plugins in `~/.perseus/formats/`.

### Allowlisted External Tools

`@tool` runs external executables with an explicit allowlist, argument
restrictions, timeouts, and output size caps — safer than ad-hoc `@agent`:

```yaml
tools:
  enabled: true
  allowlist:
    - path: "/usr/local/bin/scanner"
      args_allowlist: ["--workspace", "--format"]
      timeout_s: 30
      max_output_bytes: 65536
```

```markdown
@tool "/usr/local/bin/scanner" --workspace . --format json @cache ttl=3600
```

### Remote Context Fetching

`@perseus <url>` fetches rendered context from a remote Perseus serve instance:

```markdown
@perseus https://team-server:8420/workspace/infra @cache ttl=300
```

Gated by `foreign_resolver.allowlist` and `render.allow_remote_services_health`.

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
- [**Integration Guide**](./docs/HERMES_INTEGRATION.md) — Wire Perseus to Hermes via LLM routing (Hermes Agent by NousResearch)
- [**Adapter Patterns**](./spec/integration.md) — Wire Perseus to Claude Code, Cursor, Codex, Rovo Dev, and other assistants
- [**Context Packs**](./docs/CONTEXT_PACKS.md) — Portable workspace context with assistant-specific profiles
- [**CLI Reference**](./docs/CLI.md) — Full command surface: `render`, `checkpoint`, `agora`, `suggest`, `serve`, `synthesize`, and more
- [**Directives Reference**](./docs/DIRECTIVES.md) — All directives with modifiers and examples
- [**Performance Benchmarks**](./docs/PERFORMANCE.md) — Scaling data, cold vs. warm, enterprise profiles
- [**Container Runtime**](./docs/CONTAINER.md) — Docker and compose deployment
- [**Contributing**](./docs/CONTRIBUTING.md) — How to contribute code, directives, and tests
- [**Edge-Case Vetting**](./tests/test_edge_cases.py) — Tests covering circular deps, race conditions, symlink escapes, and context overflow
- [**Product Contract**](./docs/PRODUCT_CONTRACT.md) — What Perseus guarantees and what it doesn't
- [**Roadmap**](./ROADMAP.md) — Shipped phases and features (live Perseus source; raw directives are input, not output. Render with `perseus render ROADMAP.md`)
- [**VSCode Extension**](./editors/vscode/README.md) — LSP server + editor integration

---

## License

MIT — see [LICENSE](./LICENSE).
