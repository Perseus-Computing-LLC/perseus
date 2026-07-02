# Perseus™ 🪞 — One command. Zero orientation.

[![smithery badge](https://smithery.ai/badge/Perseus-Computing-LLC/perseus)](https://smithery.ai/servers/Perseus-Computing-LLC/perseus)
**`pip install perseus-ctx && cd your-project && perseus quickstart`**

![Perseus demo — before/after cold-start](demo.gif)

[![CI](https://github.com/Perseus-Computing-LLC/perseus/actions/workflows/test.yml/badge.svg)](https://github.com/Perseus-Computing-LLC/perseus/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/perseus-ctx)](https://pypi.org/project/perseus-ctx/)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-blue)](https://registry.modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Status: Patent Pending](https://img.shields.io/badge/status-patent_pending-blue)](./docs/ip/README.md)
[**perseus.observer →**](https://perseus.observer)

<!-- mcp-name: io.github.Perseus-Computing-LLC/perseus -->

---

## 🛡️ Product Family

Perseus is the live context engine. Seven specialized products extend it:

| Product | Description | Page |
|---|---|---|
| **Mimir** | 48 MCP tools — persistent memory with FTS5, entities, layers, confidence decay | [/mimir/](https://perseus.observer/mimir/) |
| **MCTS** | 31 security analyzers for MCP servers — tool poisoning, prompt injection, credential leaks | [/mcts/](https://perseus.observer/mcts/) |
| **PR Pilot** | 5-agent autonomous PR review pipeline — graduated autonomy L1→L3 | [/pr-pilot/](https://perseus.observer/pr-pilot/) |
| **Blast Radius** | GitLab-native dependency impact analysis — 1 mention, instant risk report | [/blast-radius/](https://perseus.observer/blast-radius/) |
| **Rapid Agent** | Dual-backend memory agent (Elastic ↔ Engram-rs) — Google Cloud Hackathon | [/rapid-agent/](https://perseus.observer/rapid-agent/) |
| **Qwen Memory** | Agent that gets smarter every session — Qwen Cloud Hackathon | [/qwen-memory/](https://perseus.observer/qwen-memory/) |
| **CrewAI Memory** | Persistent cross-session memory backend for CrewAI (54K stars) — community PR #6208 | [/crewai/](https://perseus.observer/crewai/) |

---

### Mimir — Persistent Memory (MCP)

[Mimir](https://github.com/Perseus-Computing-LLC/mimir) is the persistent memory backend for Perseus — a lightweight Rust MCP server with SQLite + FTS5. Zero network calls, no API keys. As of **v2.7.0**, offline dense/hybrid embeddings are **bundled by default** (the model is compiled into the binary), so semantic recall works zero-config with no external model download. v2.12.0 provides **48 MCP tools** across structured entities, hybrid vector search, RAG, connectors, confidence decay, journal events, and state management: `mimir_remember`, `mimir_recall`, `mimir_context`, `mimir_traverse`, `mimir_decay`, `mimir_stats`, `mimir_health`, and more.

📄 [Product page →](https://perseus.observer/mimir/) | ⭐ [GitHub →](https://github.com/Perseus-Computing-LLC/mimir)

**Install:**
```bash
curl -sSL https://raw.githubusercontent.com/Perseus-Computing-LLC/mimir/main/scripts/bootstrap.sh | bash
```

**Hermes Agent** — add to `~/.hermes/config.yaml`:
```yaml
mcp_servers:
  mimir:
    command: "mimir"
    args: ["--db", "~/.mimir/data/mimir.db"]
```

**Claude Desktop / Cursor** — add to your MCP settings:
```json
{
  "mcpServers": {
    "mimir": {
      "command": "mimir",
      "args": ["--db", "/home/YOU/.mimir/data/mimir.db"]
    }
  }
}
```

**Perseus integration** — add to `.perseus/config.yaml`:
```yaml
mimir:
  enabled: true
  command: ["mimir", "serve", "--db", "~/.mimir/data/mimir.db"]
```
Then add `@memory mode=search query="your terms"` to `.perseus/context.md` and Perseus resolves live recall at render time.

Works with any MCP-compatible assistant.

## 🏆 Hackathons — 3 Entries Submitted

### Google Cloud Rapid Agent (Elastic Partner Track)
**Status:** Submitted | **Deadline:** June 11, 2026 | **Devpost:** [perseus-cmzeu9](https://devpost.com/software/perseus-cmzeu9)
📄 [Product page →](https://perseus.observer/rapid-agent/)

Perseus is entered in the Google Cloud Rapid Agent Hackathon (Elastic Partner Track).
The submission demonstrates persistent agent memory across three consecutive sessions,
with live backend swap from Elastic Cloud to Engram-rs (self-hosted).

### Qwen Cloud Hackathon (MemoryAgent Track)
**Status:** Submitted | 📄 [Product page →](https://perseus.observer/qwen-memory/)

Agent that gets smarter every session. Persistent memory, confidence decay, cross-session compounding. Track requirements checklist with contradiction demo beat.

### GitLab Transcend Hackathon (Showcase Track)
**Status:** Submitted | 📄 [Product page →](https://perseus.observer/blast-radius/)

Blast Radius — GitLab-native dependency impact analysis via Orbit knowledge graph. One @mention, instant risk report.

### Build with Gemini XPRIZE
**Status:** Submitted | 📄 [Product page →](https://perseus.observer/pr-pilot/)

PR Pilot — 5-agent autonomous PR review pipeline. Gemini API, Google Cloud Run, Stripe integration.

## Wire Perseus to Your Assistant (MCP)

Perseus implements the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), exposing tools over stdio or SSE transport. Every tool resolves live workspace state at invocation time — no stale cache, no pre-computed snapshots.

> **⚠️ Security Gate:** Shell-executing directives (`@query`, `@agent`, `@services command:`) require `export PERSEUS_ALLOW_DANGEROUS=1`. Without it, shell directives are silently skipped.

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
    command: perseus
    args: ["mcp", "serve", "--workspace", "/path/to/workspace"]
```

Then verify with `hermes mcp test perseus`. Tools appear as `mcp_perseus_*` in your session.

> Use an absolute path for `--workspace`. Perseus's non-interactive shell context has a limited PATH — a bare `perseus` command works in the Hermes MCP config because Hermes resolves it from the user's environment, but the workspace path must be absolute.

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve", "--workspace", "/path/to/workspace"]
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

Published as [`io.github.Perseus-Computing-LLC/perseus`](https://registry.modelcontextprotocol.io/) on the official MCP Registry (search \"perseus\"). Includes `server.json` for zero-config discovery.

---

### MCP Tools

<!-- test-count: 1440 — recount with: grep -rE "^\s*def test_" tests/ | wc -l -->
<!-- The table below is the exact default output of _get_all_mcp_tools({}) — 29 rows. Recount before editing. -->
29 MCP tools resolve live state at invocation time (including the legacy aliases `perseus_get_context`/`perseus_get_health`). Two additional sensitive tools — `perseus_query` (run a shell command) and `perseus_agent` (execute a local agent subprocess) — are **not** part of this default set: they require explicit `mcp.tool_allowlist` opt-in because they execute commands in the user's local shell (**not sandboxed, full user permissions apply**).

| Tool | Description |
|---|---|
| `perseus_services` | Health-check running services |
| `perseus_read` | Read file contents |
| `perseus_list` | List directory or structured data |
| `perseus_tree` | Tree view of directory |
| `perseus_env` | Read environment variables |
| `perseus_date` | Current date/time |
| `perseus_waypoint` | Latest checkpoint summary |
| `perseus_session` | Recent session digests |
| `perseus_health` | Context maintenance report |
| `perseus_drift` | Oracle drift report |
| `perseus_memory` | Mnēmē narrative memory (+ persistent store) |
| `perseus_mimir` | Recall persistent memories via BM25 (legacy name of `perseus_mneme`) |
| `perseus_mneme` | Recall persistent memories from the external Mneme server via BM25 |
| `perseus_skills` | List available skills with staleness flags |
| `perseus_include` | Include and render another file |
| `perseus_agora` | Task board from tasks/*.md |
| `perseus_inbox` | Agent message inbox |
| `perseus_prompt` | System prompt block |
| `perseus_validate` | Validate rendered block against schema |
| `perseus_tool` | Run allowlisted external tool |
| `perseus_perseus` | Fetch context from remote Perseus instance |
| `perseus_auto_skill` | Instruct the agent to load a specific skill before starting work |
| `perseus_profile` | Resolve a per-model context profile (context target + memory posture) |
| `perseus_mason` | Query the Mason code architecture concept map |
| `perseus_research` | Per-paper Methods/Results blocks from an external paper-search MCP server (external server is opt-in via config) |
| `perseus_tokens` | Embed token budget for rendered context |
| `perseus_tooltrim` | Filtered toolset metadata and usage statistics |
| `perseus_get_context` | Full rendered workspace context (legacy alias) |
| `perseus_get_health` | Daedalus context-maintenance heuristics (legacy alias) |

Opt-in only (excluded from the default set until added to `mcp.tool_allowlist`):

| Tool | Description |
|---|---|
| `perseus_query` | Run a shell command and return stdout |
| `perseus_agent` | Execute local agent subprocess |

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
perseus quickstart          # auto-detects project, scaffolds context, renders
```

Smart init detects your stack and tailors the setup:
- **Python** → `@memory` queries for test patterns, type annotations
- **Rust** → trait bounds, lifetime annotations, cargo config
- **Node.js/TS** → npm scripts, ESLint config, component patterns
- **Go, Java, C/C++, Docker** — all detected automatically
- Falls back to a sensible generic query when unknown

The output file name is the only assistant-specific detail:

| Assistant | Output file |
|---|---|
| Claude Code | `CLAUDE.md` |
| Hermes Agent | `.hermes.md` (top priority) or `AGENTS.md` |
| Cursor | `.cursorrules` or `.cursor/context.md` |
| Codex | `AGENTS.md` |
| Rovo Dev | `AGENTS.md` |
| Any other | Whatever your assistant reads at session start |

> **Hermes priority order:** `.hermes.md` → `AGENTS.md` → `CLAUDE.md`. Render to `.hermes.md` for highest priority.

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
- **Mnēmē persistent memory** — In-process BM25 recall, zero daemon. **37ms search P50 at 10,000 docs**, flat across all scales. Perseus `@mimir` renders: **51× cold→warm speedup** with @cache. **2,700 docs/sec** write throughput, **0.4ms P50** saves. v1.0.7 adds **Mimir** (Project Synapse) — MCP-based remote memory with Ebbinghaus time-decay and FTS5 + LIKE hybrid search, circuit-breaker protected. Local Mnēmē remains the default. [Full results →](benchmark/mneme_hardcore.json)
- **94% token reduction, 0ms overhead** — live 200-request A/B harness: 488 → 27 avg prompt tokens per request. P99 latency overhead: **0ms** — Perseus adds nothing to response time. [Full harness results →](benchmark/ultimate_suite_results.json)
- **Enterprise Ready** — Cost analysis shows that for a 500-developer team, Perseus can save significant token costs per year. [Cost analysis →](benchmark/titan_cost.json)
- **Extreme Enterprise Benchmark** — 10-phase suite (reps=10, 50 devs, 250 concurrent agents): **10/10 hard gates · 6/6 soft gates · 0 errors at 250 concurrent · 90% enterprise ROI · fleet P99 1,169ms**. The benchmark is designed to surface regressions, not hide them. [Full methodology →](benchmark/README_EXTREME.md) · [Raw results →](benchmark/extreme_enterprise_results_full.json)

![Perseus v1.0.6 — Performance Benchmarks](https://raw.githubusercontent.com/Perseus-Computing-LLC/perseus/main/benchmark/infographic/perseus-benchmarks.svg)

### Reliability & Security

Perseus is tested against edge cases that challenge the "resolve before context" claim. **v1.0.6** completed a deep-dive architectural review (O(n²)→O(n), regex parser, shell hardening, retry classification) and a full security review against the MCP transport and foreign resolver surface (Phase 26):

- **MCP SSE bearer-token auth** — `POST /message` requires Bearer token via `mcp.sse_bearer_token` config key (falls back to `serve.auth_token` for backward compat). Unauthenticated requests receive 401.
- **Platform-portable MCP timeout** — `_call_tool()` uses `ThreadPoolExecutor` + `Future.result(timeout=...)` instead of Unix-only SIGALRM. Works on Windows, macOS, and Linux.

**Platform support:** Perseus is developed and CI-tested on Linux (Ubuntu, Python 3.10–3.12). macOS is supported but not in CI. Windows is supported with caveats: the MCP transport and core render pipeline work cross-platform, but approximately 8% of the test suite currently fails on Windows due to POSIX-specific shell assumptions, path handling differences, and missing `select` support in the LSP module. Native Windows scheduling (Task Scheduler) is deferred — use WSL cron or invoke `perseus render` from your own scheduler. Windows improvements are tracked but not the primary target.
- **Foreign resolver SSRF protection** — URL allowlist via `foreign_resolver.url_allowlist`, private-IP blocking (`block_private_ips`, default true), HMAC signature verification (`verify_signatures` now defaults to true, minimum 32-char secret). Redirects re-check destination IPs. Localhost (127.0.0.1, ::1) explicitly allowed for local testing.

- **16/16 hard gates passed — Gauntlet v2: 100.0/100** — Full 10-phase enterprise torture test on Perseus v1.0.8: cold/warm renders, memory retrieval, single/multi-agent tasks, 5-day enterprise week, 12 adversarial scenarios, 2-hour sustained torture, and token efficiency. All 16 gates passed with zero failures. [Full results →](benchmark/gauntlet/v2/gauntlet_v2_report.md)
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
@perseus v1.0.8

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
- 2026-06-05: Deep-dive code review — O(n²)→O(n) macro expansion, regex parser, webhook retry classification, shell injection hardening. Test suite at 894 tests (Linux, Python 3.10–3.12), all passing.
- 2026-05-27: Shipped MCP deep integration (Phase 25). 24 directives exposed as MCP tools by default.
- 2026-05-26: Deployed Perseus v1.0.6 to PyPI. Test suite at 894 tests — all passing (Linux, Python 3.10–3.12).
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
  @perseus v1.0.8
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

## Context Profiles & Recall-First Memory (`@profile`)

**A context engine should retrieve, not pre-load.** As of v1.0.14, Perseus is **recall-first by default**: the automatic long-term-memory dump that used to be stapled into every rendered context is replaced by a short, static retrieval pointer plus the recall tools. On a 200k-context model, a fixed memory blob on every turn is a permanent token tax that poisons prefix-cache stability the moment any fact changes — Perseus already has the retrieval layer (`@memory`, `@mimir`, `perseus_mneme`), so the default context now spends the budget on the task.

Per-model **context profiles** make the posture first-class and model-aware:

```yaml
# ~/.perseus/config.yaml
profiles:
  default:            { context_target: 200000,  memory: on_demand }
  claude-sonnet-4-6:  { context_target: 200000,  memory: on_demand }
  claude-opus-4-8:    { context_target: 1000000, memory: on_demand }   # big window is not an excuse to bloat
  legacy-dump:        { context_target: 200000,  memory: always, inject_limit: 5 }
```

Select a profile per document with the `@profile` directive (unknown names fall back to `default` deterministically):

```markdown
@profile claude-sonnet-4-6
```

Three memory postures:

| Posture | Behavior |
|---|---|
| `on_demand` (**default**) | Inject a static retrieval pointer + tools. **No pre-materialized memory dump.** The fixed prompt prefix stays byte-stable across vault writes (prefix-cache friendly). |
| `relevant` | Inject only entities whose `recall_when` triggers match the current render context (via the vault's trigger matching). No match → no dump. |
| `always` | **Legacy opt-in.** The pre-v1.0.14 unconditional dump on every render. Kept for back-compat; documented as an anti-pattern. `always_inject: true` is accepted as an alias. |

Injection hygiene (all postures that inject content):

- **De-duplicated** — if the rendered document already contains a memory section (an explicit `@memory` directive, a template section, or a previous injection pass), the automatic block is skipped. The same memory content can never appear twice in one context.
- **Workspace-scoped** — recall calls that support it receive the active workspace hash, so personal and project memories don't share one undifferentiated pool at the render layer.
- **Budgeted per profile** — a 200k-class profile admits at most a handful of entities (`inject_limit`, default 5; 10 for larger windows).
- **Advisory framing** — injected memory carries a note that it may be stale or tangential and that live workspace state wins on conflict, instead of asserting authority.

To suppress the automatic section entirely (pointer included) set `mimir.auto_inject: false`; to restore the old behavior globally set `profiles.default.memory: always`.

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
| [**Setup & Config Guide**](./SETUP-GUIDE.md) | The definitive setup, config, automation, and troubleshooting guide |
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

## Government & Federal Procurement

Perseus is built for government deployment from the ground up.

| Capability | Status |
|---|---|
| **License** | MIT — no copyleft, no GPL/AGPL |
| **SBOM** | [Published](./docs/SBOM.md) — NTIA minimum elements |
| **Air-gapped** | Zero cloud dependencies |
| **Encryption** | N/A (read-only context engine) |
| **Telemetry** | None — no phoning home, no tracking |
| **Supply chain** | SLSA attestation in progress |

**For federal buyers:** See [docs/federal-buyers.md](./docs/federal-buyers.md) for
procurement information, compliance status, and deployment models (air-gapped,
on-premises, classified environments).

Perseus Computing LLC is a US-owned small business. SAM.gov registration in progress.
NAICS: 541715, 541511, 541512.

---

## IP & Legal

**Patent Pending.** A provisional patent application covering Perseus's
resolve-before-context pipeline architecture is on file with the USPTO.
See **[docs/ip/](docs/ip/)** for the public IP portfolio, including
technical disclosures and evidence exhibits.

**PERSEUS™** is a trademark of Thomas Connally. Internal subsystem names
(Pythia, Daedalus, Agora, Mnēmē) are not independently trademarked and
are covered under the PERSEUS mark.

## Privacy Policy

Perseus is a **local-first context engine** — it runs entirely on your machine.

### Data Collection
- **No data collection.** Perseus does not collect, transmit, or phone home any user data, usage statistics, or telemetry.
- All context resolution happens locally on your filesystem.

### Data Usage & Storage
- Perseus reads project files, git state, and environment variables to resolve context directives.
- No project data leaves your machine. Perseus does not cache or store file contents beyond the render pipeline.
- When paired with Mimir for persistent memory, memory data is stored locally per Mimir's privacy policy.

### Third-Party Sharing
- **None.** Perseus is fully offline by default — no API calls, no cloud services, no external network requests.
- Optional MCP server connections (e.g., to remote services) are explicitly configured by the user and only made when that server is declared in your configuration.

### Data Retention
- Perseus does not retain data independently. Rendered context is ephemeral and regenerated on each invocation.
- For persistent memory, see [Mimir's privacy policy](https://github.com/Perseus-Computing-LLC/mimir#privacy-policy).

### Contact
- **Email:** privacy@perseus.observer
- **GitHub:** [Perseus-Computing-LLC/perseus](https://github.com/Perseus-Computing-LLC/perseus)

## License

**License:** MIT — see [LICENSE](./LICENSE). This license does not include
a patent grant; patent rights are reserved separately.

**Third-party notices:** see [NOTICE](./NOTICE).
