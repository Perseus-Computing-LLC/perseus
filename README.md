# Perseus™ 🪞 — MCP Server + Live Context Engine

**Perseus is an MCP server and live context engine for AI assistants.** It solves the cold-start problem — every new session, the assistant already knows what's running, what you were working on, and what tools exist. No orientation phase. No pre-flight tax. Works with any MCP-compatible assistant: **Claude Desktop, Claude Code, Cursor, Codex, Hermes Agent (by NousResearch), Rovo Dev.**

![Perseus demo — before/after cold-start](demo.gif)

[![CI](https://github.com/tcconnally/perseus/actions/workflows/test.yml/badge.svg)](https://github.com/tcconnally/perseus/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/perseus-ctx)](https://pypi.org/project/perseus-ctx/)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-blue)](https://registry.modelcontextprotocol.io/servers/io.github.tcconnally/perseus)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Status: Patent Pending](https://img.shields.io/badge/status-patent_pending-blue)](./docs/ip/README.md)
[**perseus.observer →**](https://perseus.observer)

<!-- mcp-name: io.github.tcconnally/perseus -->

![Perseus Efficiency — Cold vs Warm Render Speed](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-efficiency.svg)

![Perseus Extreme Enterprise Benchmark — Cold/Warm · Concurrency · Gates](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-xeb-infographic-full.svg)

---

### TL;DR

Perseus is a **live context engine and MCP server** for AI assistants, eliminating cold starts. It resolves dynamic data (running services, code changes, session state) *before* the assistant sees it, providing **verified facts** instead of stale files or instructions to find information.

```bash
pip install perseus-ctx
perseus init /workspace/myproject
perseus render .perseus/context.md --output CLAUDE.md
```

Works with any MCP-compatible assistant: Claude Desktop, Claude Code, Cursor, Codex, Hermes Agent, and Rovo Dev.

---

## Wire Perseus to Your Assistant (MCP)

Perseus implements the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), exposing tools over stdio or SSE transport. Every tool resolves live workspace state at invocation time — no stale cache, no pre-computed snapshots.

### Quick Start (MCP Server)

```bash
pip install perseus-ctx
perseus mcp serve                          # stdio (Claude Desktop, Claude Code, Cursor, Codex)
perseus mcp serve --transport sse --port 8420  # SSE (remote agents, multi-machine)
```

### Assistant-Specific Wiring

Pick your assistant and add the config block shown:

**Hermes Agent** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  perseus:
    transport: stdio
    command: perseus
    args: ["mcp", "serve"]
```

Then verify with `hermes mcp test perseus`. Tools appear as `mcp_perseus_*` in your session.

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve"],
      "env": { "PERSEUS_WORKSPACE": "/path/to/workspace" }
    }
  }
}
```

**Claude Code** (`.mcp.json` in your project root):

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

**Cursor** (`.cursor/mcp.json`):

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

**Codex** (`~/.codex/config.toml` or per-project `.mcp.json`):

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

**Rovo Dev** (`.mcp.json` in repo root):

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

Rovo Dev also reads `AGENTS.md` at session start — pair MCP tools with rendered context for a complete setup.

### Docker

```bash
docker build -t perseus .
docker run --rm -v /path/to/workspace:/workspace perseus mcp serve
```

See [Container Runtime](./docs/CONTAINER.md) for full Docker and compose deployment.

### MCP Registry

Published as [`io.github.tcconnally/perseus`](https://registry.modelcontextprotocol.io/servers/io.github.tcconnally/perseus) on the official MCP Registry. Includes `server.json` for zero-config discovery.

---

### MCP Tools

24 MCP tools resolve live state at invocation time. Two sensitive tools (`perseus_query` and `perseus_agent`) require explicit `mcp.tool_allowlist` opt-in because they execute commands in the user's local shell — **not sandboxed, full user permissions apply**:

| Tool | Description |
|---|---|
| `perseus_services` | Health-check running services |
| `perseus_query` | Run a shell command and return stdout |
| `perseus_read` | Read file contents |
| `perseus_list` | List directory or structured data |
| `perseus_tree` | Tree view of directory |
| `perseus_env` | Read environment variables |
| `perseus_date` | Current date/time |
| `perseus_waypoint` | Latest checkpoint summary |
| `perseus_session` | Recent session digests |
| `perseus_health` | Context maintenance report |
| `perseus_drift` | Oracle drift report |
| `perseus_memory` | Mnēmē narrative memory |
| `perseus_mneme` | Recall persistent memories via in-process BM25 |
| `perseus_skills` | List available skills with staleness flags |
| `perseus_include` | Include and render another file |
| `perseus_agent` | Execute local agent subprocess |
| `perseus_agora` | Task board from tasks/*.md |
| `perseus_inbox` | Agent message inbox |
| `perseus_prompt` | System prompt block |
| `perseus_validate` | Validate rendered block against schema |
| `perseus_tool` | Run allowlisted external tool |
| `perseus_perseus` | Fetch context from remote Perseus instance |
| `perseus_get_context` | Full rendered workspace context |
| `perseus_get_health` | Daedalus context-maintenance heuristics |

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

## Quick Start (30 Seconds to Live Context)

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

Keep it fresh with cron, launchd, systemd, or `perseus watch`:

```bash
# Linux systemd (auto-refresh every 5 minutes)
perseus systemd .perseus/context.md --output AGENTS.md --interval 5m --install --enable

# macOS launchd
perseus launchd .perseus/context.md --output AGENTS.md

# Cron (any POSIX host)
perseus cron .perseus/context.md --output AGENTS.md --every 5 --install
```

See the [Integration Guide](./docs/HERMES_INTEGRATION.md) for Hermes-specific auto-refresh setups and [spec/integration.md](./spec/integration.md) for full adapter patterns.

---

## Why Perseus? (Proof, Hardening, and Enterprise Value)

Perseus delivers verified, up-to-date context, eliminating the need for AI assistants to spend turns orienting themselves. Here's how it stands up:

### Performance & Efficiency

- **1,190× cold→warm gap** — Real-world scenario using the Perseus repo itself as the benchmark target. At the 1,408 directive scale, the cold render took **578.7s**, while the warm render took **0.486s**. [Raw data →](benchmark/real_deltas.json)
- **Mnēmē persistent memory** — In-process BM25 recall, zero daemon. **37ms search P50 at 10,000 docs**, flat across all scales. Perseus `@mneme` renders: **51× cold→warm speedup** with @cache. **2,700 docs/sec** write throughput, **0.4ms P50** saves. [Full results →](benchmark/mneme_hardcore.json)
- **94% token reduction, 0ms overhead** — live 200-request A/B harness: 488 → 27 avg prompt tokens per request. P99 latency overhead: **0ms** — Perseus adds nothing to response time. [Full harness results →](benchmark/ultimate_suite_results.json)
- **Enterprise Ready** — Cost analysis shows that for a 500-developer team, Perseus can save significant token costs per year. [Cost analysis →](benchmark/titan_cost.json)
- **Extreme Enterprise Benchmark** — 10-phase suite (reps=10, 50 devs, 250 concurrent agents): **10/10 hard gates · 6/6 soft gates · 0 errors at 250 concurrent · 90% enterprise ROI · fleet P99 1,169ms**. The benchmark is designed to surface regressions, not hide them. [Full methodology →](benchmark/README_EXTREME.md) · [Raw results →](benchmark/extreme_enterprise_results_full.json)

![Perseus Cold vs Warm — @cache eliminates subprocess cost](https://raw.githubusercontent.com/tcconnally/perseus/main/benchmark/infographic/perseus-cold-vs-warm.svg)

### Reliability & Security

Perseus is tested against edge cases that challenge the "resolve before context" claim. **Phase 26** (v1.0.5) completed a full security review against the MCP transport and foreign resolver surface:

- **MCP SSE bearer-token auth** — `POST /message` requires Bearer token via `mcp.sse_bearer_token` config key (falls back to `serve.auth_token` for backward compat). Unauthenticated requests receive 401.
- **Platform-portable MCP timeout** — `_call_tool()` uses `ThreadPoolExecutor` + `Future.result(timeout=...)` instead of Unix-only SIGALRM. Works on Windows, macOS, and Linux.

**Platform support:** Perseus is developed and CI-tested on Linux (Ubuntu, Python 3.10–3.12). macOS is supported but not in CI. Windows is supported with caveats: the MCP transport and core render pipeline work cross-platform, but approximately 8% of the test suite currently fails on Windows due to POSIX-specific shell assumptions, path handling differences, and missing `select` support in the LSP module. Native Windows scheduling (Task Scheduler) is deferred — use WSL cron or invoke `perseus render` from your own scheduler. Windows improvements are tracked but not the primary target.
- **Foreign resolver SSRF protection** — URL allowlist via `foreign_resolver.url_allowlist`, private-IP blocking (`block_private_ips`, default true), HMAC signature verification (`verify_signatures` now defaults to true, minimum 32-char secret). Redirects re-check destination IPs. Localhost (127.0.0.1, ::1) explicitly allowed for local testing.

- **14/14 hard gates passed** — The ultimate benchmark suite, including swarm chaos, cache thrash, and adversarial tests, passed all gates. [Full results →](benchmark/ultimate_suite_results.json)
- **Semantic Equivalence: 1.0** — A live Gemini 2.5 Flash judge found 20/20 A/B test pairs to be semantically equivalent, confirming that Perseus changes what the assistant *knows*, not what it says.
- **Workspace boundaries** — Symlink escapes (direct, relative, chained, to `/etc`) are all blocked. The trust-gate resolves symlinks to their real target before checking boundaries.
- **Context overflow protection** — `@read` and `@include` warn and truncate when files exceed `max_read_bytes` / `max_include_bytes` (512 KB default, `None` for unlimited).
- **Transitive resolution** — `@include` on `.md` files recursively renders directives up to `max_include_depth` (default 5), with cycle detection.
- **Integrity drift** — Optional `integrity_check` captures file mtimes before render and warns if any file changed mid-resolution.
- **Plugin sandboxing** — Plugin directives with `executes_shell=True` are gated behind `allow_query_shell`, same as built-ins. Plugin errors are caught and surfaced as inline warnings — a broken plugin never breaks a render.

[Edge-case tests](tests/test_edge_cases.py) cover circular dependencies, race conditions, symlink escapes, and context overflow. These four config knobs live under `render:` in `~/.perseus/config.yaml`.

Perseus reads from a live filesystem — there is no snapshot isolation unless you enable `integrity_check`. Files can change between directive resolutions. The render output reflects whatever was on disk at the moment each directive resolved, **not** a single atomic point-in-time. This is the right tradeoff for a zero-dependency pre-processor (zero overhead by default, check when it matters), but it is not a database transaction.

The `O_CREAT | O_EXCL` checkpoint locking is atomic on local POSIX filesystems. Network filesystems (**NFS** < v4, **SMB**, cloud mounts) may not honor these semantics — if you run a multi-agent relay across machines, use a local disk or a filesystem with verified atomic-create support.

`perseus.py` is a compiled build artifact produced by `scripts/build.py` from the modular `src/perseus/` tree. It is not hand-maintained as a single file. The source modules are the canonical form.

---

## How Perseus Works

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

## Active Tasks
@agora status=open,in_progress

## Skills Available
@skills flag_stale=true category=devops,github

## Project Memory
@memory focus="recent"
```

Perseus renders this:

```markdown
# Context — 2026-05-27 08:33 CDT

## What's Running
mongo-dev    Up 4 hours
redis-dev    Up 4 hours

## Last Session
Checkpoint written: 2026-05-27T08:28
Task: webhook handler — written, pending test run
Next: run pytest tests/test_webhook.py

## Ports
3001

## Active Tasks
| ID | Title | Status | Scope |
|---|---|---|---|
| task-08 | List and Tree Directives | Complete | medium |
| task-12 | Mnēmē Narrative Memory | Complete | large |

## Skills Available
| Skill | Category | Updated |
|---|---|---|
| hermes-agent | autonomous-ai-agents | 2026-05-20 |
| github-pr-workflow | github | 2026-05-15 |
| docker-stack-auditing ⚠ | devops | 2026-03-01 |
| documentation-audit | software-development | 2026-05-26 |

## Project Memory
### Recent
- 2026-05-27: Shipped MCP deep integration (Phase 25). 24 directives exposed as MCP tools by default.
- 2026-05-26: Deployed Perseus v1.0.6 to PyPI. Test suite at 812 tests — all passing (Linux, Python 3.10–3.12).
- 2026-05-24: Completed Hephaestus extensibility — plugin directives, macros, hooks, pipes.
```

The assistant never sees a directive. It sees a document that was already true — including which skills are available, which tasks are open, and what decisions were recently made.

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
        return f"Status: {resp}"
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

---

## Project Memory (Mnēmē)

Mnēmē (Μνήμη) is Perseus's narrative project memory. It distills checkpoints and Pythia recommendations into a per-workspace narrative — so your assistant knows not just what's running, but *how you got here*.

```bash
# Update the narrative from latest checkpoints
perseus memory update

# Query the narrative
perseus memory query "what was the auth decision?"

# Render it inline
perseus render .perseus/context.md --output CLAUDE.md
```

In your context file:

```markdown
@memory                    # full narrative
@memory focus="decisions"  # decisions section only
@memory focus="recent"     # recent activity
```

Mnēmē is LLM-optional: deterministic assembly works zero-dependency; an optional `memory.llm_provider` enables richer distillation. Full docs: [spec/components.md](./spec/components.md) § 4.

---

## Full Documentation

| Document | What it covers |
|---|---|
| [**CLI Reference**](./docs/CLI.md) | Every command and flag |
| [**Directives Reference**](./docs/DIRECTIVES.md) | All directives with modifiers and examples |
| [**Integration Guide**](./docs/HERMES_INTEGRATION.md) | Wire Perseus to Hermes via LLM routing |
| [**Adapter Patterns**](./spec/integration.md) | Wire Perseus to any AI assistant |
| [**Container Runtime**](./docs/CONTAINER.md) | Docker and compose deployment |
| [**Quickstart**](./docs/quickstart.md) | 5-minute setup walkthrough |
| [**Product Contract**](./docs/PRODUCT_CONTRACT.md) | Guarantees, trust model, permissions |
| [**Contributing**](./docs/CONTRIBUTING.md) | Dev setup, test suite, commit conventions |
| [**Examples**](./docs/EXAMPLES.md) | End-to-end workflow recipes |
| [**Use Cases**](./docs/use-cases.md) | Real-world usage patterns |
| [**Performance**](./docs/PERFORMANCE.md) | Benchmark methodology and results |
| [**Agent Surfaces**](./docs/AGENT_SURFACES.md) | JSON contracts for agent consumption |
| [**Deployment**](./docs/DEPLOYMENT.md) | Systemd, launchd, cron, Docker, CI |
| [**Security**](./SECURITY.md) | Trust model, workspace boundaries, secrets |
| [**Roadmap**](./ROADMAP.md) | Living roadmap (live `@perseus` source) |

---

## IP & Legal

**Patent Pending.** A provisional patent application covering Perseus's
resolve-before-context pipeline architecture is on file with the USPTO.
See **[docs/ip/](docs/ip/)** for the public IP portfolio, including
technical disclosures and evidence exhibits.

**PERSEUS™** is a trademark of Thomas Connally. Internal subsystem names
(Pythia, Daedalus, Agora, Mnēmē) are not independently trademarked and
are covered under the PERSEUS mark.

**License:** MIT — see [LICENSE](./LICENSE). This license does not include
a patent grant; patent rights are reserved separately.

**Third-party notices:** see [NOTICE](./NOTICE).
