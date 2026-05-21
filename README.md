# Perseus™ 🪞

**Perseus** is a live context engine for AI assistants. It solves the cold-start problem: every new session begins with an assistant that has no idea what's running, what you were working on, or which tools are available. Perseus resolves that state **before it reaches the context window** — so the assistant opens with verified, live facts instead of burning turns on orientation.

Works with any AI assistant that reads a file: **Claude Code, Cursor, Codex, Hermes, Rovo Dev.** Drop in alongside `CLAUDE.md`, `AGENTS.md`, or `.cursorrules` — no migration required.

![Perseus demo — before/after cold-start](demo.gif)

---

> *Athena didn't tell Perseus to fight Medusa. She handed him a shield — polished to a mirror — and let him see the monster clearly without meeting her gaze. The trick was never strength. It was reflection.*

![Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Piazza della Signoria, Florence.](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg/500px-Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg)

*Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Loggia dei Lanzi, Florence. ([Jastrow](https://commons.wikimedia.org/wiki/File:Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg), CC BY-SA 4.0)*

**Status: v1.0.1 — stable. 63 features shipped, 496 tests passing.**

[![CI](https://github.com/tcconnally/perseus/actions/workflows/ci.yml/badge.svg)](https://github.com/tcconnally/perseus/actions/workflows/ci.yml)

---

## TL;DR

```bash
pip install perseus-ctx
perseus init /workspace/myproject
perseus render /workspace/myproject/.perseus/context.md --output <whatever-your-assistant-reads>
```

Your AI assistant now opens every session with a complete, live picture of your workspace — services running, last checkpoint, recent git log, available tools — **without burning a single turn on orientation.**

The output file name is the only assistant-specific detail:

| Assistant | Output file |
|---|---|
| Claude Code | `CLAUDE.md` |
| Hermes Agent | `.hermes.md` |
| Cursor | `.cursorrules` or `.cursor/context.md` |
| Codex | `AGENTS.md` |
| Any other | Whatever your assistant reads at session start |

No pip? One-liner install:
```bash
curl -fsSL https://raw.githubusercontent.com/tcconnally/perseus/main/perseus.py \
  -o ~/.local/bin/perseus && chmod +x ~/.local/bin/perseus
```

---

## Why Not Just Use `.cursorrules` or `CLAUDE.md`?

Static markdown files work when they're fresh. They rot immediately. The port you wrote down has changed, the test suite has grown, the container that was "always running" hasn't started since Tuesday. The assistant either trusts the stale data or burns turns verifying it.

**Perseus's answer is resolve-before-context.** Directives in your `.perseus/context.md` are evaluated at render time — shell commands run, files are read, service health is checked — and the result is a finished, verified document. The AI never sees directive syntax. It sees facts.

```
@query "git log --oneline -5"      →  actual git log, live
@services                          →  which containers are up right now
@waypoint                          →  last checkpoint from the previous session
```

This isn't a replacement for those files — it's a pre-processor you bolt onto any of them. Add `@perseus` to line 1 of any `.md` file and it becomes live. Perseus produces plain markdown output. Any assistant that reads a file benefits.

---

## The Problem

Every AI assistant session starts cold. Before useful work can begin, the assistant spends turns on orientation:

- *What services are running right now?*
- *What were we working on last time?*
- *Which tool is the right one for this?*
- *Where did we leave off when the connection dropped?*

This is the **pre-flight tax** — and it compounds across every session, every developer, every context switch.

Static markdown files (AGENTS.md, CLAUDE.md, READMEs) make it worse. They were accurate when written. By the time they're read, the port has changed, the test suite has grown, and the container that was "always running" hasn't been started since Tuesday. The assistant either trusts stale data or stops to verify it — spawning more tool calls, consuming context, delaying work.

**Stale context isn't neutral. It's drag.**

---

## The Solution: Resolve Before Context

Like Perseus holding up the mirror, the fix is indirection: don't hand the assistant a static document and let it go look things up. Resolve everything first, hand it the reflection.

```
Without Perseus                   With Perseus
──────────────────────────────    ─────────────────────────────────────
"Port is 3001 (check .env)"  →   Port: 3001
"47 tests (may be stale)"    →   Tests: 54 passing (run 8s ago)
"Check docker ps first"      →   mongo-dev: Up 4h 12m
"Where did we leave off?"    →   Checkpoint: webhook handler written,
                                             pending test run
```

Any `.md` file beginning with `@perseus` on the first line becomes live. No special extension. No new toolchain. The file renders to plain markdown — the assistant reads facts, not instructions to go find facts.

---

## Three Components

### 🪞 The Renderer — `perseus render`

Resolves directive blocks in a source document before it hits the context window. Shell output, file values, environment variables, service health, session history — all pulled live at render time.

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

Becomes, by the time the assistant reads it:

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

---

### ⚡ Session Waypoints — `perseus checkpoint` / `perseus diff`

Perseus supports both writing lightweight checkpoints and comparing them with `perseus diff`, which shows field-level changes between two checkpoints or the most recent pair.

The Fates cut the thread when the connection drops. Waypoints are how you pick it back up.

Write a checkpoint at any natural pause point — end of a task, before a large operation, at a logical handoff. The next session recovers immediately, without re-orientation.

```bash
$ perseus checkpoint \
    --task "Implementing webhook integration" \
    --status "handler written, pending test run" \
    --next "run pytest tests/test_webhook.py" \
    --workspace /workspace/myproject

✅ Checkpoint written: ~/.perseus/checkpoints/2026-05-18T0833.yaml
```

`perseus recover` is workspace-aware: it finds the most relevant checkpoint for your current project, prioritising workspace match and recency, with fallback levels that tell you exactly how stale the data is.

---

### 🔮 Pythia — Tool Oracle (`perseus suggest`)

Pythia was the Oracle at Delphi who gave Perseus his mission. She didn't make decisions — she surfaced the truth so the hero could act clearly. That's the Tool Oracle: given a task and the current environment state, it ranks the highest-utility approaches and tells you *why*.

The Medusa of tool selection is the paralysis of facing too many options directly — 90 skills, 12 integrations, 4 possible approaches. Pythia holds up the mirror.

```bash
$ perseus suggest "deploy the staging container" --category devops
```

Emits a structured Pythia prompt with a live environment snapshot — skills table with freshness, service health, recent checkpoint, session digest — which the assistant reads and answers with ranked recommendations. No extra model required. No separate API call. The loop closes in the same context window.

---

## Directives

> **Note on the `@perseus` header:** Source documents start with `@perseus v0.4` on line 1. This is the **directive protocol version** (the syntax revision Perseus parses), not the package version. The package is `v1.0.0`; the current directive protocol is `v0.4`. You don't need to change this header — Perseus reads it to select the right parser.

| Directive | What it does |
|---|---|
| `@query "shell cmd" [fallback="text"] [schema="name"]` | Runs a shell command, embeds stdout as a fenced block; `fallback=` emits literal text on failure or empty output; `schema=` validates YAML stdout |
| `@read <file> [path="key"] [schema="name"]` | Reads a file; dot-notation path for JSON/YAML/TOML; `key=` for `.env` files; `schema=` validates full or extracted output |
| `@env VAR [fallback="x"] [schema="name"]` | Injects an environment variable; `required=true` emits a visible warning if unset; `schema=` validates the value or fallback |
| `@include <file>` | Embeds a file inline; markdown raw, structured files fenced |
| `@if <cond>` / `@else` / `@endif` | Conditional blocks: `file.exists/missing`, `env.set/unset/eq/neq`, `query("cmd") [not] matches /regex/[i]` |
| `@constraint id="..." severity="..."` | Machine-readable rules rendered as a `\| ID \| Severity \| Rule \|` table |
| `@skills [flag_stale=true]` | Scans the Hermes skills dir, reads frontmatter, flags stale entries |
| `@services` (YAML block or `@services ... @end`) | HTTP health checks (`url:`), Docker container status (`docker:`), or optional shell exit check (`command:`) |
| `@session [count=N] [topic="..."]` | Recent session digest from the sessions directory |
| `@date format="YYYY-MM-DD HH:mm z"` | Live date/time, inline or standalone |
| `@waypoint [ttl=N]` | Latest checkpoint rendered inline; `ttl=` skips it if too old |
| `@prompt...@end` | AI instruction callout — visible to the assistant, attributed to Perseus |
| `@validate schema="name"...@end` | Renders a block, validates the payload, and emits a visible warning instead of invalid context |
| `@agora [status=...] [scope=...]` | Live task board from `tasks/` — markdown table by status/scope |
| `@memory [focus="..."] [ttl=N]` | Mnēmē narrative for the workspace; `focus=` slices a single section (`arc`, `decisions`, `recent`, `patterns`, `history`) |
| `@health` | Maintenance suggestions (stale checkpoints, near-duplicates, large context, old completed tasks) |
| `@list <path> [type] [depth] [path] [columns] [as]` | Directory listing OR structured-file table from `path="dot.key"` of JSON/YAML |
| `@tree <path> [depth] [match] [exclude]` | Fenced directory tree with plain indentation |
| `@agent "command" [timeout=N] [strip=true] [fallback="text"]` | Run a local subprocess, embed stdout inline (gated by `render.allow_agent_shell`) |
| `@inbox [unread=true] [limit=N]` | Render pending point-to-point messages from `perseus inbox send` |
| `@memory federation [alias=name]` | Render digest of subscribed cross-workspace narratives (see `perseus memory federation`) |
| `@memory include_federation=true` | Local narrative + appended `## Federated Context` digest |
| `@drift` | Daedalus drift report — acceptance rate, recommendation Jaccard, confidence proxy (see `perseus oracle drift`) |

Any directive accepts a `@cache` modifier:

```markdown
@query "git log --oneline -5" @cache session      ← run once per render, reuse after
@services @cache mock="(stubbed in CI)"           ← bypass execution entirely
@skills flag_stale=true @cache persist             ← survives across processes
```

---

## Safety & Trust Model

Perseus executes local commands intentionally, but shell-backed features can now be gated in config:

```yaml
render:
  allow_query_shell: true
  allow_services_command: false
  allow_outside_workspace: false
```

- `allow_query_shell`: enables or disables `@query` command execution
- `allow_services_command`: enables or disables `command:` checks inside `@services`
- `allow_outside_workspace`: controls whether `@read` / `@include` may escape the workspace

Disk-cached results survive across processes for as long as their TTL allows:

```markdown
@skills flag_stale=true @cache ttl=3600           ← cache to disk for 1 hour
```

## Predictive Prefetch

`perseus prefetch <file>` reads opt-in `prefetch.rules`, builds the static
directive graph, and warms cacheable inline directives without rendering the
source first. Shell-backed prefetches still obey the render trust gates, and
prefetch directives must include `@cache ttl=N`, `@cache persist`, or
`@cache session`. Adaptive prefetching is also opt-in and only scores
predeclared candidates; it does not invent directives or generate context.

```yaml
prefetch:
  rules:
    - name: status-diff
      trigger: '@query "git status"'
      prefetch:
        - '@query "git diff --stat" @cache ttl=300'
  adaptive:
    enabled: true
    backend: deterministic   # or daedalus
    threshold: 0.5
    candidates:
      - id: decision-memory
        prefetch: '@memory focus=decisions @cache ttl=300'
        patterns: ["decision", "memory"]
```

## Cited Synthesis

`perseus synthesize` keeps generation outside ordinary render output and treats any LLM as a drafter, not an authority. The command builds a line-numbered source bundle; when generation is explicitly enabled, only claims with exact source quotes and line citations survive. Uncited claims are dropped. See [Cited Synthesis](./docs/CITED_SYNTHESIS.md).

```bash
perseus synthesize "What is the next allowable action?" \
  --source ROADMAP.md \
  --source HANDOFF.md
```

---

## Documentation

Full documentation lives in [`docs/`](./docs/index.md):

- **[Quickstart](./docs/quickstart.md)** — Install, configure, and render your first context in 5 minutes.
- [Integration guide](./docs/HERMES_INTEGRATION.md) — Wire Perseus to Hermes, Codex, Claude Code, Cursor, or Rovo Dev.
- [Context Packs & Profiles](./docs/CONTEXT_PACKS.md) — Portable workspace context with assistant-specific presets.
- [Container deployment](./docs/CONTAINER.md) — Docker and compose examples.
- [Cited Synthesis](./docs/CITED_SYNTHESIS.md) — `@synthesize` and the citation gate.
- [Contributing](./docs/CONTRIBUTING.md) — How to contribute code, directives, and tests.

> `perseus.py` is generated from `src/perseus/`. Run `python scripts/build.py` to rebuild.

## Real-World Examples

- [Subagent Handover](./docs/EXAMPLES.md#subagent-handover-zero-tax-orientation) — Zero-tax orientation for fresh agents.
- [Automated Verification](./docs/EXAMPLES.md#automated-environment-verification) — Ensuring context health.
- [Renderer Dogfooding](./docs/EXAMPLES.md#renderer-dogfooding-self-documenting-roadmap) — Live roadmaps and docs.

---

## Quick Start

**Requirements:** Python 3.9+ and one dependency (`pyyaml`).

```bash
pip install perseus-ctx
```

The pattern is the same for every assistant — only the output filename changes:

```bash
# Scaffold a source document
perseus init /workspace/myproject

# Render to whatever file your assistant reads at session start
perseus render /workspace/myproject/.perseus/context.md --output <assistant-file>
```

| Assistant | `--output` target | Notes |
|---|---|---|
| Claude Code | `CLAUDE.md` | Read at session start automatically |
| Hermes Agent | `.hermes.md` | Highest-priority context file |
| Cursor | `.cursorrules` or `.cursor/context.md` | Either location works |
| Codex | `AGENTS.md` | Standard agent context file |
| Any other | Whatever your assistant reads | Perseus produces plain markdown |

**Auto-refresh** — add a crontab entry to keep context ≤5 minutes stale:

```bash
*/5 * * * * cd /workspace/myproject && perseus render .perseus/context.md --output CLAUDE.md
```

For Hermes-specific setup (cron watchdog, `.hermes.md` priority order, config paths), see [`docs/HERMES_INTEGRATION.md`](./docs/HERMES_INTEGRATION.md).

---

**Configure** (optional — only needed for `@skills` and `@session` directives):

```bash
mkdir -p ~/.perseus
cat > ~/.perseus/config.yaml << 'EOF'
pythia:
  skill_dir: /home/you/.hermes/skills
assistant:
  sessions_dir: /home/you/.hermes/sessions
EOF
```

**Scaffold and render:**

```bash
# Scaffold a source document for your workspace
perseus init /workspace/myproject

# Or use a built-in profile (generic, claude-code, cursor, codex, hermes, rovodev)
perseus init --profile claude-code /workspace/myproject

# Edit .perseus/context.md to taste, then render
perseus render /workspace/myproject/.perseus/context.md --output /workspace/myproject/CLAUDE.md

# Write a session waypoint
perseus checkpoint \
  --task "Adding @query directive" \
  --status "resolver written, tests pending" \
  --next "add to render loop, test with context.md" \
  --workspace /workspace/myproject

# Recover — workspace-aware
perseus recover --workspace /workspace/myproject

# Get Pythia's ranked recommendations for a task
perseus suggest "best way to search for a pattern across a large Python codebase"
```

Profile outputs and refresh guidance are documented in the
[Context Pack Profile Gallery](./docs/CONTEXT_PACKS.md#profile-gallery).

---

## Development

Run the Python suite with:

```bash
python -m pytest tests/ -q
```

Tests are split by subsystem under `tests/`; shared test loader/helpers live in `tests/conftest.py`.

---

## CLI Reference

Run `perseus <command> --help` for full flags. Summary of the surface:

| Command | What it does |
|---|---|
| `perseus render <file>` | Resolve all directives in a source document and print rendered output. Add `--output <path>` to write to disk. |
| `perseus graph <file> [--json]` | Build a static directive graph without executing directives; foundation for predictive prefetching. |
| `perseus prefetch <file> [--json]` | Apply configured `prefetch.rules` to the static graph and warm directive caches. |
| `perseus synthesize <question> --source FILE [--json]` | Build a cited-synthesis prompt, or explicitly run an LLM drafter with citation validation. Uncited claims are dropped. |
| `perseus pack {validate,show} [--json]` | Inspect and validate `.perseus/pack.yaml` context pack manifests. |
| `perseus watch [--source FILE] [--output FILE] [--interval N]` | Poll context sources and refresh render outputs without platform scheduler dependencies. |
| `perseus validate --schema SCHEMA [payload|-] [--json]` | Validate YAML/JSON payloads against Perseus schemas; omit payload or pass `-` to read stdin. |
| `perseus checkpoint --task ... --status ... --next ...` | Write a YAML waypoint to `~/.perseus/checkpoints/`. Auto-updates Mnēmē narrative. |
| `perseus diff [--from FILE] [--to FILE]` | Show diff between two checkpoints (default: latest two). |
| `perseus recover [--workspace PATH]` | Print the latest checkpoint for the workspace. |
| `perseus agora [--status open\|in_progress\|completed]` | Live task board from `tasks/*.md`. |
| `perseus suggest <prompt> [--llm provider]` | Pythia tool oracle — ranks skills against a prompt, with transparent outcome-weight hints when data exists. |
| `perseus memory {update,compact,show,status,query,federation}` | Mnēmē narrative project memory + cross-workspace federation. |
| `perseus inbox {send,list,read,unread,mark-read}` | Point-to-point messages between agents. |
| `perseus health` | Maintenance report — stale skills, large narrative, Pythia log volume. |
| `perseus oracle {accept,reject,log,export,infer-labels,outcomes,drift}` | Daedalus Pythia log management, inferred labels, outcome signals, and drift checks. |
| `perseus llm ping [--provider hermes\|ollama\|...]` | Verify the configured LLM provider is reachable. |
| `perseus init [--template name | --profile name] <workspace>` | Scaffold `.perseus/context.md`; profiles also write `.perseus/pack.yaml`. |
| `perseus serve [--port N] [--host H] [--generate-token]` | Read-only HTTP view of workspace state on `http://127.0.0.1:7991/`; optional static bearer auth via `serve.auth_token`. |
| `perseus serve --lsp --stdio\|--tcp PORT [--allow-lsp-mutations]` | Run as a Language Server Protocol server for editor integration. Mutation commands are opt-in. |
| `perseus cron SOURCE --output FILE [--every N] [--install]` | POSIX crontab entry generator/installer for macOS, Linux, and BSD cron. |
| `perseus systemd SOURCE --output FILE [--interval 5m] [--install] [--enable]` | Linux-only systemd `--user` service + timer scaffolder. |
| `perseus launchd SOURCE --output FILE [--interval 300] [--label LABEL] [--force]` | macOS-only LaunchAgent plist scaffolder. |

Agent-readable `--json` contracts for synthesis, oracle, memory, federation, drift, and LLM health commands are documented in [Agent JSON Surfaces](./docs/AGENT_SURFACES.md).

---

## Editor integration

Perseus ships a Language Server Protocol server. Any editor that speaks LSP
gets live diagnostics, hover previews of rendered directives, completion,
and a "▶ Render" code lens — without re-implementing the directive system.

```bash
perseus serve --lsp --stdio       # for editor stdin/stdout integration
perseus serve --lsp --tcp 7992    # for editor TCP connection
```

| Editor | Setup |
|---|---|
| **VSCode** | Install the bundled extension from `editors/vscode/` (see its [README](editors/vscode/README.md)). |
| **Helix** | Add to `languages.toml`: `[[language]] name = "markdown"` and `language-servers = ["perseus"]` with `[language-server.perseus] command = "perseus" args = ["serve", "--lsp", "--stdio"]`. |
| **Neovim** | Use `nvim-lspconfig`'s generic config: `vim.lsp.start({name = 'perseus', cmd = {'perseus', 'serve', '--lsp', '--stdio'}})`. |
| **Zed / JetBrains / others** | Any LSP-capable editor — point it at `perseus serve --lsp --stdio`. |

The server implements an LSP 3.17 subset: diagnostics, hover, completion,
codeLens, and `workspace/executeCommand` (render, openCheckpoint, compactMemory).
Hand-rolled JSON-RPC — no `pygls` dependency.

---

## Connecting an LLM (optional)

Perseus is fully usable **without an LLM** — rendering, checkpoints, federation,
agora, health, and inbox are all deterministic. The LLM-augmented surfaces
(Pythia oracle, Mnēmē compaction, Daedalus drift detection) plug into whichever
provider you prefer:

| Provider | Use case |
|---|---|
| **`hermes`** | [NousResearch Hermes Agent](https://github.com/NousResearch/hermes-agent) — autonomous agent with built-in provider routing (Claude/GPT/Grok/local). See [`docs/HERMES_INTEGRATION.md`](docs/HERMES_INTEGRATION.md). |
| **`ollama`** | Local models via Ollama (default; no config needed for `mistral`). |
| **`openai-compat`** / **`llamacpp`** | Any server speaking OpenAI's `/v1/chat/completions` (vLLM, llama.cpp, LocalAI, LiteLLM, etc.). |
| **`daedalus`** | Perseus's own fine-tuned local model for oracle scoring. |

**Verify your setup with one command:**

```bash
perseus llm ping
# ✓ hermes · model=claude-sonnet-4.6 · http://localhost:8080 · 312 ms · 'pong'
```

Full Hermes setup walkthrough: [`docs/HERMES_INTEGRATION.md`](docs/HERMES_INTEGRATION.md).

---

## Auto-Injection

Perseus works with any assistant that can read a file at session start. The general pattern is:

```bash
perseus render .perseus/context.md --output <assistant-specific-file>
```

The output is plain markdown, so the only assistant-specific detail is the filename you choose. Hermes is just one example.
The verified adapter outputs are tracked in the [Adapter Conformance Matrix](./spec/integration.md#adapter-conformance-matrix).


Perseus keeps `.hermes.md` fresh via a `no_agent` cron watchdog (no model tokens, no noise):

```
Cron (every 5 min, silent)
  └─ perseus render .perseus/context.md → .hermes.md
                                               ↓
                                   Hermes session start
                                   reads .hermes.md automatically
                                   (highest priority context file)
                                               ↓
                               Assistant has full live context.
                               No orientation phase. Start working.
```

Hermes reads `.hermes.md` at session start with higher priority than `AGENTS.md`, `CLAUDE.md`, or `.cursorrules`. The cron job keeps it ≤5 minutes stale. The cold-start problem is solved before the session opens.

---


## Scheduled Rendering

Perseus supports the scheduler primitives that already exist on common POSIX
developer machines:

| Platform | Command | Behavior |
|---|---|---|
| POSIX cron | `perseus cron SOURCE --output FILE --every 5` | Prints a crontab line on any host; add `--install` where `crontab` is available. |
| macOS launchd | `perseus launchd SOURCE --output FILE --interval 300` | Writes a LaunchAgent plist under `~/Library/LaunchAgents/`. |
| Linux systemd | `perseus systemd SOURCE --output FILE --interval 5m` | Prints user `.service` / `.timer` units; add `--install` to write them and `--enable` to run `systemctl --user`. |
| Native Windows | Deferred native adapter | No Task Scheduler integration yet. Use WSL cron, the printed `perseus render` command, or invoke `perseus render` from your own scheduler. |

The portable baseline is plain render:

```bash
perseus render .perseus/context.md --output .hermes.md
```

For macOS users, the LaunchAgent helper looks like:

```bash
perseus launchd .perseus/context.md --output .hermes.md
```

This writes a LaunchAgent plist that periodically renders the source document
to the output path.

## Watch Mode

`perseus watch` is the portable polling option for local development,
containers, and CI-like shells where platform scheduler setup is awkward:

```bash
perseus watch --source .perseus/context.md --output .hermes.md
```

If `.perseus/pack.yaml` exists, watch mode refreshes every configured
`renders:` target unless `--source` or `--output` is supplied. It debounces
changes by waiting one additional poll interval before rendering, logs render
failures to stderr, and keeps running unless `--exit-on-error` is set.

Use `perseus render` for one-shot portability, `perseus watch` for a foreground
portable loop, and cron/launchd/systemd when the host scheduler should own the
process lifecycle.

## Authenticated Serve

`perseus serve` remains loopback-first and read-only. To expose it beyond
localhost, set a static bearer token and then bind explicitly:

```bash
perseus serve --generate-token
```

```yaml
serve:
  bind_host: 0.0.0.0
  auth_token: paste-generated-token-here
```

Clients must send:

```text
Authorization: Bearer paste-generated-token-here
```

Unauthenticated non-loopback serve is refused unless
`serve.allow_insecure_remote: true` or `--i-understand-no-auth` is explicitly
set.

## Container Runtime

Perseus can also run as a local OCI-style image without changing the runtime
contract: the container copies `perseus.py` directly, installs only
`requirements.txt`, and exposes the same `perseus` CLI.

```bash
docker build -t perseus:local .
docker compose run --rm render
docker compose --profile serve up serve
```

The compose example mounts the workspace read-only, keeps Perseus state under
`/perseus-home`, and publishes serve mode only to host loopback. Replace the
placeholder token in `examples/container/config.yaml` before using the serve
profile. Full guide: [Container Runtime](./docs/CONTAINER.md).


Pythia config options:

```yaml
pythia:
  llm_provider: ollama
  ollama_model: llama3.1
  llm_timeout_s: 30
  ollama_host: http://127.0.0.1:11434
```

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Pythia skill loop · `@query` · workdir auto-injection via cron | ✅ Complete |
| **Phase 2** | `@read` · `@env` · `@if/@else/@endif` · `@include` — real project opt-in | ✅ Complete |
| **Phase 3** | `@cache session/ttl=N` · smart `recover --workspace` · `@constraint` | ✅ Complete |
| **Phase 4** | `@services command:` · `perseus init` · `--version` · ROADMAP.md goes live | ✅ Complete |
| **Hardening Pass** | parser fixes · trust gates · workspace safety · launchd scaffolding · focused tests | ✅ Complete |
| **Phase 5A** | `suggest --llm` · Pythia log · multi-workspace checkpoint namespacing | ✅ Complete |
| **Phase 5B** | `perseus diff` field-level checkpoint comparison | ✅ Complete |
| **Phase 5C** | Agora task coordination · `perseus agora` · `@agora` directive | ✅ Complete |
| **Phase 5D** | `@cache persist` / `@cache mock` · `@list` / `@tree` · suggest UX flags · systemd | ✅ Complete |
| **Phase 5E** | Context health: `perseus health` + `@health` (deterministic maintenance heuristics) | ✅ Complete |
| **Phase 6** | Daedalus — oracle labeling/export CLI + `--llm daedalus` provider routing | ✅ Complete |
| **Phase 7** | Mnēmē — narrative project memory + `@memory` directive | ✅ Complete |
| **Phase 8** | `@agent` · `@inbox` · template gallery (`perseus init --template`) · `perseus serve` (read-only HTTP view) · POSIX `perseus cron` scaffolder · Mnēmē federation (`@memory federation` + manifest + 4 CLI subcommands) | ✅ Complete |
| **Phase 9** | Daedalus v2: closed-loop autonomy — `perseus oracle infer-labels` (self-rating), `memory.pattern_extractor: daedalus` (trained extraction), `perseus oracle drift` + `@drift` (drift detection) | ✅ Complete |
| **Phase 10** | Editor integration — Perseus LSP server (`perseus serve --lsp --stdio\|--tcp`) + VSCode extension (`editors/vscode/`) | ✅ Complete |
| **Phase 11** | Internal hardening — registry, doctor, JSON surfaces, LSP integration tests, split suite | ✅ Complete |
| **Phase 12** | Schema validation engine — `schema=`, `@validate`, `output_schema`, `perseus validate` | ✅ Complete |
| **Phase 13** | Predictive prefetching — static graph, rule-based cache warming, adaptive deterministic/Daedalus scoring | ✅ Complete |
| **Phase 14** | Adaptive self-optimizing oracle — outcome signals, online scoring, and opt-in A/B exploration | ✅ Complete |
| **Phase 15A** | Cited synthesis contract — `perseus synthesize`, opt-in generation, exact quote citation gate | ✅ Complete |
| **Phase 15B-C** | Cross-source consistency synthesis and `@synthesize` render directive | ✅ Complete |
| **Phase 16** | Product contract, context pack manifest, and init/profile workflow | ✅ Complete |
| **Phase 17** | Trust, privacy, permission profiles, redaction, and audit reporting | ✅ Complete |
| **Phase 18** | Installer, release artifacts, versioning, and scheduler parity | ✅ Complete |
| **Phase 19** | Assistant adapter conformance and profile gallery | ✅ Complete |
| **Phase 20** | Managed runtime: authenticated serve, container, and watch mode | ✅ Complete |
| **Phase 21** | Golden evals, performance budgets, and compatibility gates | ✅ Complete |
| **Phase 22** | Example workspaces, docs hub, contributing guide, and v1.0.0 release | ✅ Complete |

Full detail: [ROADMAP.md](./ROADMAP.md). Product references:
[Product Contract](./docs/PRODUCT_CONTRACT.md),
[Context Packs](./docs/CONTEXT_PACKS.md),
[Container Runtime](./docs/CONTAINER.md), and
[Perseus Product Report](./docs/PERSEUS_PRODUCT_REPORT.md).

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
  Hermes session start
  build_context_files_prompt()
          │
          ▼
  AI context window — complete, accurate, zero pre-flight tax

  Waypoints: ~/.perseus/checkpoints/
  Cache:     ~/.perseus/cache/
  Config:    ~/.perseus/config.yaml
```

---

## Etymology

**Perseus** slew Medusa not by meeting her gaze but by watching her reflection in Athena's polished shield. The Medusa here is the paralysis of facing your environment directly — too many tools, stale docs, no continuity between sessions. The mirror is resolved context: you see the situation clearly without being turned to stone by it.

**Hermes** gave Perseus three gifts for the quest: winged sandals for speed, a kibisis to carry what could not be looked at directly, and guidance through the unknown. This Perseus returns the favor — giving Hermes a way to navigate any workspace without the orientation tax.

**Pythia** was the Oracle at Delphi who spoke for Apollo. Pilgrims came with impossible questions; she gave them the truth in a form they could act on. The Tool Oracle works the same way: you come with a task and a tangled environment; it gives you ranked paths forward. She didn't need to know everything — she needed to know what mattered *now*.

**The Graeae** — the three grey sisters who shared a single eye — are what you're working around. Three sisters who can only see one thing at a time: the current context, the tool choice, or the session history. Perseus stole the eye and made them see all three at once. So does the renderer.

---

## License

MIT — see [LICENSE](./LICENSE).
