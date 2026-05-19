# Perseus 🪞

> *Athena didn't tell Perseus to fight Medusa. She handed him a shield — polished to a mirror — and let him see the monster clearly without meeting her gaze. The trick was never strength. It was reflection.*

![Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Piazza della Signoria, Florence.](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg/500px-Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg)

*Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Loggia dei Lanzi, Florence. ([Jastrow](https://commons.wikimedia.org/wiki/File:Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg), CC BY-SA 4.0)*

**Perseus** is a live context engine for AI assistants. It solves the cold-start problem: every new session begins with an assistant that has no idea what's running, what you were working on, which tools are available, or where things broke. Perseus resolves that state **before it ever reaches the context window** — so the assistant starts with a complete, accurate picture instead of burning turns on orientation.

Built as a companion to [Hermes Agent](https://hermes-agent.nousresearch.com). Designed to be assistant-agnostic.

Provider-agnostic defaults now use `PERSEUS_SKILLS_DIR` and `PERSEUS_SESSIONS_DIR`, with legacy `HERMES_*` environment variables preserved as fallback for backward compatibility.

Perseus dogfoods itself: `ROADMAP.md` is a live `@perseus` source — the project's own documentation resolves its git state, CLI version, recent sessions, and last checkpoint at render time.

**Status: Alpha v0.8.1 — Phases 1-12 complete and Phase 13A landed. Phase 11 stabilization and Phase 12 schema validation are done, and `perseus graph` now provides the static directive graph substrate for predictive prefetching. 33 tasks closed, 2 Phase 13 tasks open. 287 tests passing, 1 sandbox-skipped TCP smoke.**

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

Emits a structured oracle prompt with a live environment snapshot — skills table with freshness, service health, recent checkpoint, session digest — which the assistant reads and answers with ranked recommendations. No extra model required. No separate API call. The loop closes in the same context window.

---

## Directives

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

---

## Real-World Examples

See how Perseus is used in practice:
- [Subagent Handover](./docs/EXAMPLES.md#subagent-handover-zero-tax-orientation) — Zero-tax orientation for fresh agents.
- [Automated Verification](./docs/EXAMPLES.md#automated-environment-verification) — Ensuring context health.
- [Renderer Dogfooding](./docs/EXAMPLES.md#renderer-dogfooding-self-documenting-roadmap) — Live roadmaps and docs.

---

## Quick Start

**Requirements:** Python 3.10+ and `pyyaml`.

Install runtime dependency:

```bash
pip install -r requirements.txt
```

```bash
# Install
cp perseus.py ~/.local/bin/perseus
chmod +x ~/.local/bin/perseus

# Configure (absolute paths required — ~ won't resolve in all environments)
mkdir -p ~/.perseus
cat > ~/.perseus/config.yaml << 'EOF'
oracle:
  skill_dir: /home/you/.hermes/skills
assistant:                              # path to your agent's sessions dir; used by @session
  sessions_dir: /home/you/.hermes/sessions
# Note: the legacy key `hermes:` is still accepted as an alias for
# `assistant:` and is auto-migrated on load (see load_config in perseus.py).
EOF

# Scaffold a source document for your workspace (v0.4+)
perseus init /workspace/myproject

# Edit to taste, then render
perseus render /workspace/myproject/.perseus/context.md

# Write a waypoint
perseus checkpoint \
  --task "Adding @query directive" \
  --status "resolver written, tests pending" \
  --next "add to render loop, test with context.md" \
  --workspace /workspace/myproject

# Recover — workspace-aware
perseus recover --workspace /workspace/myproject

# Get Pythia's recommendations
perseus suggest "best way to search for a pattern across a large Python codebase"
```

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
| `perseus validate --schema SCHEMA [payload|-] [--json]` | Validate YAML/JSON payloads against Perseus schemas; omit payload or pass `-` to read stdin. |
| `perseus checkpoint --task ... --status ... --next ...` | Write a YAML waypoint to `~/.perseus/checkpoints/`. Auto-updates Mnēmē narrative. |
| `perseus diff [--from FILE] [--to FILE]` | Show diff between two checkpoints (default: latest two). |
| `perseus recover [--workspace PATH]` | Print the latest checkpoint for the workspace. |
| `perseus agora [--status open\|in_progress\|completed]` | Live task board from `tasks/*.md`. |
| `perseus suggest <prompt> [--llm provider]` | Pythia tool oracle — ranks skills against a prompt. |
| `perseus memory {update,compact,show,status,query,federation}` | Mnēmē narrative project memory + cross-workspace federation. |
| `perseus inbox {send,list,read,unread,mark-read}` | Point-to-point messages between agents (task-16). |
| `perseus health` | Maintenance report — stale skills, large narrative, oracle log volume. |
| `perseus oracle {accept,reject,log,export,infer-labels,drift}` | Daedalus oracle log management (Phase 9). |
| `perseus llm ping [--provider hermes\|ollama\|...]` | Verify the configured LLM provider is reachable. |
| `perseus init [--template name] <workspace>` | Scaffold a `.perseus/context.md` and `~/.perseus/config.yaml`. |
| `perseus serve [--port N] [--host H]` | Read-only HTTP view of workspace state on `http://127.0.0.1:7991/`. |
| `perseus serve --lsp --stdio\|--tcp PORT [--allow-lsp-mutations]` | Run as a Language Server Protocol server for editor integration (Phase 10.1). Mutation commands are opt-in. |
| `perseus cron [setup\|disable] --interval 5m` | Cross-platform scheduler scaffolder (cron/launchd/Task Scheduler). |
| `perseus systemd [install\|uninstall] --interval 5m` | Linux-only systemd `--user` service + timer scaffolder. |
| `perseus launchd {install,uninstall}` | macOS-only LaunchAgent scaffolder. |

Agent-readable `--json` contracts for oracle, memory, federation, drift, and LLM health commands are documented in [Agent JSON Surfaces](./docs/AGENT_SURFACES.md).

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
| **`daedalus`** | Perseus's own fine-tuned local model (task-06 / Phase 9). |

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


## macOS launchd

Perseus now includes a `launchd` scaffolding command for macOS users:

```bash
perseus launchd .perseus/context.md --output .hermes.md
```

This writes a LaunchAgent plist that periodically renders the source document to the output path.


Oracle config options:

```yaml
oracle:
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
| **Phase 5A** | `suggest --llm` · oracle log · multi-workspace checkpoint namespacing | ✅ Complete |
| **Phase 5B** | `perseus diff` field-level checkpoint comparison | ✅ Complete |
| **Phase 5C** | Agora task coordination · `perseus agora` · `@agora` directive | ✅ Complete |
| **Phase 5D** | `@cache persist` / `@cache mock` · `@list` / `@tree` · suggest UX flags · systemd | ✅ Complete |
| **Phase 5E** | Context health: `perseus health` + `@health` (deterministic maintenance heuristics) | ✅ Complete |
| **Phase 6** | Daedalus — oracle labeling/export CLI + `--llm daedalus` provider routing | ✅ Complete |
| **Phase 7** | Mnēmē — narrative project memory + `@memory` directive | ✅ Complete |
| **Phase 8** | `@agent` · `@inbox` · template gallery (`perseus init --template`) · `perseus serve` (read-only HTTP view) · cross-platform `perseus cron` scaffolder · Mnēmē federation (`@memory federation` + manifest + 4 CLI subcommands) | ✅ Complete |
| **Phase 9** | Daedalus v2: closed-loop autonomy — `perseus oracle infer-labels` (self-rating), `memory.pattern_extractor: daedalus` (trained extraction), `perseus oracle drift` + `@drift` (drift detection) | ✅ Complete |
| **Phase 10** | Editor integration — Perseus LSP server (`perseus serve --lsp --stdio\|--tcp`) + VSCode extension (`editors/vscode/`) | ✅ Complete |
| **Phase 11** | Internal hardening — registry, doctor, JSON surfaces, LSP integration tests, split suite | ✅ Complete |
| **Phase 12** | Schema validation engine — `schema=`, `@validate`, `output_schema`, `perseus validate` | ✅ Complete |
| **Phase 13+** | See "Future development" at the bottom of [ROADMAP.md](./ROADMAP.md) | 🌅 Open canvas |

Full detail: [ROADMAP.md](./ROADMAP.md)

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

MIT
