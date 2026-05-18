@perseus v0.4

@prompt
This document is the single source of truth for the Perseus project.
Every new session working on Perseus must read this file first.
Do not ask the user what we're working on. Read this file. Then work.
Do not propose architecture, new tasks, or "next steps" not already described here.
The framework and plan belong to the project owner. Your job is to execute tasks.
@end

# Perseus — Living Roadmap

**Repo:** https://github.com/tcconnally/perseus  
**Workspace:** `/workspace/perseus`  
**Skill:** `perseus-context-engine` (installed at `~/.hermes/skills/`)  
**CLI:** `~/.local/bin/perseus`  
**Last updated:** @date format="YYYY-MM-DD"

---

## What Perseus Is

Perseus is a **live context engine for AI assistants**. It solves the cold-start problem:
instead of burning the first N turns of a session on orientation, Perseus resolves environment
state *before* it enters the context window. The assistant receives facts, not instructions
to go find facts.

Perseus is **assistant-agnostic**. It was built alongside Hermes Agent but is not tied to it.
The renderer output is plain markdown. The checkpoint store is plain YAML. Any AI assistant
that can read a file or receive stdin can use Perseus.

**Core insight:** Resolve environment state *before* it hits the context window.

**Pythia** (renamed from "oracle" — Oracle Corp is litigious) is the MVP. Renderer and
checkpoints feed it.

### Components

| Component | Purpose | Status |
|---|---|---|
| **Renderer** | Resolves `@directive` blocks in `.md` files before context window | ✅ Complete |
| **Checkpoints** | Lightweight explicit session recovery snapshots | ✅ Complete |
| **Pythia** | Tool oracle — ranks approaches given task + live env | ✅ Complete |
| **Agora** | Async agent coordination substrate — task queue + `@agora` directive | 🔲 Phase 5 |
| **Daedalus** | Local autonomous scoring model — Pythia without a round-trip | 🔲 Phase 6 |

---

## What's Built

### `perseus.py` — full CLI

@query "python3 /workspace/perseus/perseus.py --version"

| Command | What it does |
|---|---|
| `perseus render <file.md>` | Resolves `@perseus` source doc → plain markdown |
| `perseus checkpoint --task "..."` | Writes timestamped YAML to `~/.perseus/checkpoints/` |
| `perseus recover` | Prints latest checkpoint (workspace + TTL aware) |
| `perseus diff` | Shows what changed between last two checkpoints |
| `perseus suggest "<task>"` | Emits structured Pythia prompt over live env snapshot |
| `perseus suggest "<task>" --llm ollama` | Pipes oracle prompt to local model, no round-trip |
| `perseus init [workspace]` | Scaffolds `.perseus/context.md` for a new workspace |
| `perseus launchd` | Scaffolds macOS LaunchAgent plist for scheduled render |

### Directives implemented

| Directive | Status | Notes |
|---|---|---|
| `@skills [flag_stale=true]` | ✅ | Scans configured skills dir, reads frontmatter, flags by mtime |
| `@services` (YAML block / explicit block) | ✅ | HTTP health checks (url:), docker status (docker:), optional shell cmd (command:) |
| `@session [count=N]` | ✅ | Recent sessions from sessions dir |
| `@date format="..."` | ✅ | Inline substitution |
| `@waypoint [ttl=N]` | ✅ | Latest checkpoint content |
| `@prompt...@end` | ✅ | AI instruction callout block |
| `@query "..."` | ✅ | Runs shell cmd, embeds stdout as fenced code block |
| `@read <file> path="..."` | ✅ | JSON/YAML/TOML path=, .env key=, fallback= |
| `@env <VAR>` | ✅ | required=, fallback= modifiers |
| `@if/@else/@endif` | ✅ | file.exists/missing, env.set/unset/eq/neq |
| `@include <file>` | ✅ | md embedded raw; structured files fenced |
| `@cache session/ttl=N` | ✅ | Two-level cache: in-memory (session) + disk (TTL) |
| `@cache persist` | 🔲 | Disk-backed cache surviving across sessions — task-09 |
| `@cache mock` | 🔲 | Static mock value; bypasses execution — task-09 |
| `@constraint...@end` | ✅ | Block directive; renders as table at doc end |
| `@agora [status=open]` | ✅ | Live task board from tasks/ directory |
| `@list` | 🔲 | Directory listing or structured-file table — task-08 |
| `@tree` | 🔲 | Filtered directory tree — task-08 |
| `@health` | 🔲 | Inline context maintenance suggestions — task-05 |
| `@memory` | 🔲 | Narrative project memory — task-12 |

### Files

```
/workspace/perseus/
  perseus.py                    ← single-file CLI; entire implementation lives here
  requirements.txt              ← pyyaml only; no other deps
  tests/
    test_perseus.py             ← pytest suite; must pass before any commit
  spec/
    overview.md
    components.md
    directives.md
    oracle.md                   ← named oracle in spec, Pythia in impl
    integration.md              ← adapter patterns for wiring to any AI assistant
    data-model.md
  tasks/
    README.md                   ← Agora workflow rules
    task-01-*.md                ← provider-agnostic config
    task-02-*.md                ← Phase 5A: --llm flag + oracle log
    task-03-*.md                ← Phase 5B: checkpoint diffing
    task-04-*.md                ← Agora: formal task substrate
  AGENTS.md                     ← agent contributor guide (read this before touching code)
  ROADMAP.md                    ← this file (live @perseus source)
  HANDOFF.md                    ← superseded; keep for history

~/.perseus/
  config.yaml
  checkpoints/
  cache/
  oracle_log.jsonl              ← Pythia recommendation log (Phase 5A+)

~/.local/bin/perseus            ← symlink / wrapper

~/.hermes/skills/
  perseus/
    SKILL.md                    ← `perseus-context-engine` skill
```

---

## Workspace State

@query "git -C /workspace/perseus log --oneline -5"
@query "git -C /workspace/perseus status --short"

---

## Non-Negotiable Constraints

These apply to every agent working in this repo. They are not up for discussion.

1. **Single file.** `perseus.py` stays one file. No package structure, no `setup.py`, no
   sub-modules. Internal section headers and grouping are fine. File splits are not.
2. **`pyyaml` is the only dependency.** Do not add deps without explicit approval.
3. **Tests before commit.** All existing tests must pass. New behavior needs new tests.
4. **Spec follows code.** When behavior changes, update the relevant `spec/*.md`. The code
   is the truth.
5. **Keep the mythology.** Perseus, Pythia, Agora, Daedalus, Medusa problem. Don't rename.
6. **Backward compatibility.** Existing `@directive` syntax and config keys must not break.
   New behavior is additive or behind config flags.
7. **Executors, not architects.** Agents implement tasks as specified. Architecture,
   sequencing, and naming decisions belong to the project owner. If a task conflicts with
   a constraint, mark it Blocked — do not resolve it unilaterally.

---

## Roadmap

### Phase 1 — Close the Pythia Loop ← COMPLETE ✅

**P1.1** — Pythia as live Hermes skill call  
**P1.2** — `@query` directive  
**P1.3** — Hermes workdir auto-injection via `no_agent` cron watchdog

---

### Phase 2 — Real Project Opt-In ← COMPLETE ✅

**P2.1** — `@read` directive  
**P2.2** — `@env` directive  
**P2.3** — `@if/@else/@endif`  
**P2.4** — `@include`

---

### Phase 3 — Reliability + Scale ← COMPLETE ✅

**P3.1** — Cache layer (`@cache session` / `@cache ttl=N`)  
**P3.2** — Smart `perseus recover --workspace`  
**P3.3** — `@constraint...@end`

---

### Phase 4 — Self-Bootstrapping ← COMPLETE ✅

Perseus renders its own roadmap live. This file is now a `@perseus` source.

**P4.1** — `command:` variant in `@services`  
**P4.2** — ROADMAP.md converted to live `@perseus` source  
**P4.3** — `perseus init`  
**P4.4** — `--version` flag, v0.4 bump

---

### Hardening Pass ← COMPLETE ✅

Completed after alpha audit by Rovo Dev. Not a named phase — a quality gate.

- Safer workspace inference for `render`
- Quote-aware `@read` and `@include` parsing helpers
- Visible `@if` parse errors and unmatched-block warnings
- Workspace-boundary checks for `@read` / `@include`
- `@query` and `@services command` trust gates
- Structural frontmatter parsing for `@skills`
- `stale_after`-aware recover logic
- `@query` nested-quote parsing fix; `render --output` flag
- macOS `perseus launchd` scaffolding
- 27-test pytest suite

---

### Phase 5 — Pythia Autonomy + Agora ← COMPLETE ✅

Phase 5 has two parallel tracks. Both are complete. One remaining item (P5A.4) is tracked
as task-07.

#### Track A — Pythia Autonomy

Make Pythia self-contained — no assistant round-trip required.

**P5A.1 — `--llm` flag** (`tasks/task-02`)  
Pipe the oracle prompt directly to a locally running model.
- Primary target: **Ollama** (`http://localhost:11434`, OpenAI-compatible API)
- Secondary: **llama.cpp server** (also OpenAI-compatible)
- No new dependencies — stdlib `urllib` only
- Configurable via `llm:` block in `~/.perseus/config.yaml`
- Flags: `--llm ollama|llamacpp|openai-compat`, `--model <name>`, `--model-url <url>`

**P5A.2 — Oracle recommendation log** (`tasks/task-02`)  
Every `perseus suggest` call appends a structured entry to `~/.perseus/oracle_log.jsonl`.
This is the seed of a future fine-tuning dataset for Daedalus (Phase 6).
- Schema: `{version, timestamp, task, env_snapshot, prompt, response, provider, model, accepted}`
- `accepted` is `null` at log time — a future command will flip it
- Append-only JSONL; logging failure is a warning, not a fatal error

**P5A.3 — Checkpoint diffing** (`tasks/task-03`)  
`perseus diff` shows what changed between the last two checkpoints.
- Default: diff two most recent in the store
- `--workspace` filters to a specific workspace
- `--a` / `--b` select by index or filename
- Human-readable output; no machine-parseable format needed

**P5A.4 — Multi-workspace checkpoint namespacing**  
Harden `perseus recover --workspace` with per-workspace `latest-<hash>.yaml` pointers so
recovery is reliable across multiple active workspaces.  
*No task file yet — project owner will write it after P5A.1–3 land.*

#### Track B — Agora

The **Agora** is Perseus's async agent coordination substrate. It makes the `tasks/` directory
a first-class Perseus feature rather than a convention held together by markdown.

Named for the Athenian public square — where free people arrived independently, saw what work
was posted, claimed it, completed it, and moved on. No central dispatcher.

**P5B.1 — Formal task schema** (`tasks/task-04`)  
Task files get YAML frontmatter so tooling can parse state without reading prose:
```yaml
---
id: task-04
title: "..."
status: open          # open | in_progress | completed | blocked
scope: medium         # small | medium | large
depends_on: []
claimed_by: null
opened: 2026-05-18
closed: null
---
```

**P5B.2 — `perseus agora` subcommand** (`tasks/task-04`)  
Thin CLI over the tasks directory:
- `perseus agora list` — grouped by status
- `perseus agora claim <id> --agent <name>` — sets status + claimed_by
- `perseus agora complete <id>` — sets status + closed date
- `perseus agora status` — summary view

**P5B.3 — `@agora` renderer directive** (`tasks/task-04`)  
Embeds a live task board in any rendered context file:
```
@agora [status=open] [scope=small,medium]
```
Renders as a markdown table. Replaces static task lists in `AGENTS.md` and `tasks/README.md`.

**P5B.4 — Provider-agnostic config** (`tasks/task-01`)  
Rename `hermes:` config section → `assistant:`. Make `SKILLS_DIR` and `SESSIONS_DIR`
configurable via `PERSEUS_SKILLS_DIR` / `PERSEUS_SESSIONS_DIR` env vars (old `HERMES_*`
vars remain as fallback). Rewrite `spec/integration.md` as a multi-adapter guide covering
Hermes, Rovo Dev, Claude Code, Cursor, and generic assistants.

---

### Phase 6 — Daedalus ← PLANNED

**Daedalus** is the local autonomous scoring model that powers Pythia without any external
round-trip. Named for the master craftsman who built autonomous mechanical intelligences —
the bronze giant Talos, the golden servants — tools that operated on their own once made.

Daedalus is what Pythia runs on when it no longer needs to phone home.

The `oracle_log.jsonl` built in Phase 5A is the training data seed.

**P6.1 — Dataset curation tooling**  
`perseus oracle accept <log-id>` / `reject <log-id>` — flip the `accepted` field in
`oracle_log.jsonl`. Simple CLI for the human to label good recommendations.

**P6.2 — Dataset export**  
`perseus oracle export` — emit labeled entries as a fine-tuning dataset in a standard format
(JSONL with `prompt`/`completion` pairs). Targets small models: Mistral 7B, Phi-3-mini.

**P6.3 — Local model integration**  
Wire Daedalus as the default `--llm` target once a fine-tuned model exists. The scoring
model runs locally via Ollama. No internet required. No assistant round-trip required.

**P6.4 — Cross-session learning**  
Scores improve with usage patterns. The more `perseus suggest` is used and labeled, the
better Daedalus's recommendations become.

**Design constraint:** Daedalus is a model you run, not a service you call. It must work
offline. The implementation stays inside `perseus.py` — Daedalus is not a separate daemon.

---

### Phase 7 — Mnēmē: Narrative Project Memory ← PLANNED

**Mnēmē** (Μνήμη) was the original Muse of Memory — not a log, not a snapshot, but the
*distilled narrative* of experience. She answers the question no snapshot can: *how did we
get here?*

Perseus solves cold-start. Mnēmē solves *arc*: the decisions made three weeks ago, the
approach tried and rejected, the constraint added after a painful bug. The raw material
already exists in checkpoints and the oracle log. Mnēmē distills it.

**P7.1 — Narrative store and deterministic distillation**  
Per-workspace narrative file at `~/.perseus/memory/<workspace-hash>.md`. Assembled
deterministically from checkpoints (decisions, task history) and oracle log (patterns,
accepted recommendations). No LLM required for v1.

**P7.2 — LLM-assisted distillation**  
Optional `memory.llm_provider` config key enables richer narrative via the existing
`run_llm` infrastructure. Incremental update and full compaction prompts.

**P7.3 — `@memory` renderer directive**  
Injects the narrative inline, with optional `focus=` argument to extract a single section.

**P7.4 — Auto-update on checkpoint write**  
`cmd_checkpoint` silently calls memory update when `memory.auto_update=True`. Every
checkpoint automatically advances the narrative. Compounding value.

**P7.5 — `perseus memory query`**  
Deterministic section search or LLM-answering against the narrative. Read-only.

Full spec: `tasks/task-12-mneme-narrative-memory.md`

---

## Sequencing Summary

```
Phase 1 (done):   Pythia skill loop → @query → workdir auto-injection
Phase 2 (done):   @read → @env → @if/@else → @include
Phase 3 (done):   Cache layer → smart recover → @constraint
Phase 4 (done):   Self-bootstrapping — ROADMAP.md is now live
Hardening (done): Parsing safety, trust gates, tests, launchd
Phase 5 (done):   Track A: Pythia autonomy (--llm, oracle log, diff)
                  Track B: Agora (task schema, agora subcommand, @agora directive, provider-agnostic)
Spec backfill:    task-07 (multi-workspace namespacing)
                  task-08 (@list + @tree directives)
                  task-09 (@cache persist + mock)
                  task-10 (suggest --quick/--category/--no-services flags)
                  task-11 (linux systemd scaffolding)
                  task-13 (@if query)
                  task-14 (@query fallback)
Phase 5C (next):  task-05 context health + @health directive
Phase 6 (later):  task-06 Daedalus — local scoring model, dataset curation, cross-session learning
Phase 7 (planned): task-12 Mnēmē — narrative project memory, @memory directive, auto-update on checkpoint
```

---

## Open Tasks

@query "grep -rl 'status: open' /workspace/perseus/tasks/ 2>/dev/null | xargs -I{} basename {} || echo '(none)'"

---

## Last Session
@waypoint ttl=86400

---

## Recent Sessions
@session count=3 topic="perseus"

---

## CLI Health
@services
  - name: Perseus CLI
    command: python3 /workspace/perseus/perseus.py --version

---

## Environment Reference

| Thing | Where |
|---|---|
| Percy CLI | `~/.local/bin/perseus` |
| Main script | `/workspace/perseus/perseus.py` |
| Skill | `~/.hermes/skills/perseus/SKILL.md` (`perseus-context-engine`) |
| Global config | `~/.perseus/config.yaml` |
| Checkpoints | `~/.perseus/checkpoints/` |
| Oracle log | `~/.perseus/oracle_log.jsonl` |
| Cache | `~/.perseus/cache/` |
| Live context | `/workspace/perseus/.perseus/context.md` |
| Task queue | `/workspace/perseus/tasks/` |
| Spec docs | `/workspace/perseus/spec/` |
| GitHub token | `/home/hermeswebui/.hermes/.env` → `GITHUB_TOKEN` |

**Notes:**
- Container `$HOME` quirk: use absolute paths (`/home/hermeswebui`) not `~` in config
- No `gh` CLI — use `curl` + token from `/home/hermeswebui/.hermes/.env`
- Git push: `https://tcconnally:***@github.com/tcconnally/perseus.git`
- Services health check shows all ❌ URLError — expected (container can't reach host-network `localhost`). Not a bug.
- `@constraint` table flushed at end of document. Inline positioning is a future enhancement.
- Rovo Dev works on the repo asynchronously. Review commits before pulling; check `tasks/` for status.
