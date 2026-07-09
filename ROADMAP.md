@perseus v1.0.8
<!-- Last updated: 2026-06-08 · Current Perseus version: v1.0.6 -->

@prompt
This document is the single source of truth for the Perseus project.
Every new session working on Perseus must read this file first.
Do not ask the user what we're working on. Read this file. Then work.
Do not propose architecture, new tasks, or "next steps" not already described here.
The framework and plan belong to the project owner. Your job is to execute tasks.
@end

> **Note to human readers:** This file is a live `@perseus` source document. The raw directive syntax (`@query`, `@prompt`, `@date`) is Perseus input — render with `perseus render ROADMAP.md` for plain markdown output. The phase numbering and task-IDs are internal sprint structure used by Perseus's own build process; treat the "✅ Complete" markers as the authoritative shipping status.

# Perseus — Living Roadmap

**Repo:** https://github.com/Perseus-Computing-LLC/perseus  
**Workspace:** current repo checkout  
**Skill:** `perseus-context-engine` (installed at your assistant's skills directory)  
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
| **Agora** | Async agent coordination substrate — task queue + `@agora` directive | ✅ Phase 5C |
| **Health** | Deterministic context maintenance heuristics — `perseus health` + `@health` directive (Daedalus v1) | ✅ Phase 5E |
| **Daedalus** | Local autonomous scoring model — Pythia without a round-trip (dataset + routing shipped; model training is a user step) | ✅ Phase 6 |
| **Mnēmē** | Narrative project memory — distills checkpoints + Pythia log into a per-workspace narrative | ✅ Phase 7 |
|| **Federation** | Cross-workspace Mnēmē narrative aggregation via subscribable manifest | ✅ Phase 8.2 |
|| **Decentralized Fed.** | Remote transport, cryptographic identity, provenance chains, cross-org context sharing | 🔨 Phase 27 |
|| **Templates** | Starter scaffolds for generic/hermes/rovodev/claude-code/cursor via `perseus init --template` | ✅ Phase 8 |
| **Serve** | Read-only HTTP view of workspace state | ✅ Phase 8 |
| **Inbox** | Per-workspace point-to-point message store + `@inbox` directive | ✅ Phase 8 |
| **Cron** | Cross-platform scheduler (macOS/Linux/BSD) — bridges launchd + systemd | ✅ Phase 8 |
| **Synthesis** | Opt-in cited synthesis claims; uncited LLM output is dropped | ✅ Phase 15A |
| **Hephaestus** | Extensibility architecture — plugin directives, macros, hooks, format adapters, pipe syntax | ✅ Phase 24 |
| **MCP Integration** | Expose every directive as an MCP tool for universal AI client compatibility | ✅ Phase 25 |
| **Security Hardening** | MCP SSE auth, Windows timeout, SSRF protection, build robustness | ✅ Phase 26 |
|| _Exploratory_ | Undated, non-committed directions (federation mesh, context packs, autonomy, model-aware/intent-driven context, enterprise, native apps, …) | 📋 see [Exploratory](#exploratory--directional-not-committed-no-dates) |

---

## What's Built

### `perseus.py` — full CLI

@query "grep -o 'perseus alpha v[0-9.]*' perseus.py | head -1" fallback="perseus version unavailable"

| Command | What it does |
|---|---|
| `perseus render <file.md>` | Resolves `@perseus` source doc → plain markdown |
| `perseus graph <file.md> [--json]` | Builds a static directive graph without executing directives |
| `perseus prefetch <file.md> [--json]` | Applies opt-in pre-fetch rules to the static graph and warms directive caches |
| `perseus synthesize "question" --source FILE [--json]` | Builds cited synthesis prompts and validates LLM-drafted claims |
| `perseus pack {validate,show} [--json]` | Inspects and validates `.perseus/pack.yaml` context pack manifests |
| `perseus validate --schema SCHEMA [payload|-]` | Validates a payload against a Perseus schema; `--json` for CI/agents |
| `perseus checkpoint --task "..."` | Writes timestamped YAML to `~/.perseus/checkpoints/` |
| `perseus recover` | Prints latest checkpoint (workspace + TTL aware) |
| `perseus diff` | Shows what changed between last two checkpoints |
| `perseus suggest "<task>"` | Emits structured Pythia prompt over live env snapshot |
| `perseus suggest "<task>" --llm ollama` | Pipes Pythia prompt to local model, no round-trip |
| `perseus init [--profile name] [workspace]` | Scaffolds `.perseus/context.md`; profiles also write `.perseus/pack.yaml` |
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
| `@query "..." [fallback="text"] [schema="..."]` | ✅ | Runs shell cmd, embeds stdout as fenced code block; `fallback=` returns literal text on failure/empty; `schema=` validates YAML stdout |
| `@read <file> path="..." schema="..."` | ✅ | JSON/YAML/TOML path=, .env key=, fallback=, schema validation |
| `@env <VAR> schema="..."` | ✅ | required=, fallback=, schema validation modifiers |
| `@if/@else/@endif` | ✅ | file.exists/missing, env.set/unset/eq/neq, `query("cmd") [not] matches /regex/[i]` (task-13) |
| `@include <file>` | ✅ | md embedded raw; structured files fenced |
| `@cache session/ttl=N` | ✅ | Two-level cache: in-memory (session) + disk (TTL) |
| `@cache persist` | ✅ | Disk-backed cache; TTL via `render.persist_cache_ttl_s` (task-09) |
| `@cache mock[="value"]` | ✅ | Bypasses execution entirely — substitutes literal value (task-09) |
| `@constraint...@end` | ✅ | Block directive; renders as table at doc end |
| `@validate schema="..."...@end` | ✅ | Renders a block, validates the payload, and emits a warning instead of invalid context |
| `@agora [status=open]` | ✅ | Live task board from tasks/ directory |
| `@memory [focus=...] [ttl=N]` | ✅ | Inline Mnēmē narrative or single focus section — Phase 7 |
| `@list <path> [type] [depth] [path] [columns] [as]` | ✅ | Directory listing OR structured-file table from JSON/YAML (task-08) |
| `@tree <path> [depth] [match] [exclude]` | ✅ | Filtered directory tree (task-08) |
| `@health` | ✅ | Inline context maintenance suggestions (task-05) |
| `@agent "cmd" [timeout=N] [strip] [fallback]` | ✅ | Run a local subprocess, embed stdout inline (task-15) |
| `@inbox [unread=true] [limit=N]` | ✅ | Render pending point-to-point messages (task-16) |
| `@memory federation [alias=name]` | ✅ | Cross-workspace narrative digest (task-19) |
| `@memory include_federation=true` | ✅ | Local narrative + appended federated digest (task-19) |

### Files

```
<workspace>/
  perseus.py                    ← generated single-file artifact; canonical source in src/perseus/
  requirements.txt              ← pyyaml only; no other deps
  tests/
    conftest.py                 ← shared Perseus loader and test helpers
    test_*.py                   ← subsystem pytest files; must pass before any commit
  spec/
    overview.md
    components.md
    directives.md
    pythia.md                   ← Pythia tool recommendation design
    integration.md              ← adapter patterns for wiring to any AI assistant
    data-model.md
  tasks/
    README.md                   ← Agora workflow rules
    task-01-*.md                ← provider-agnostic config
    task-02-*.md                ← Phase 5A: --llm flag + Pythia log
    task-03-*.md                ← Phase 5B: checkpoint diffing
    task-04-*.md                ← Agora: formal task substrate
  AGENTS.md                     ← agent contributor guide (read this before touching code)
  ROADMAP.md                    ← this file (live @perseus source)
  HANDOFF.md                    ← superseded; keep for history

~/.perseus/
  config.yaml
  checkpoints/
  cache/
  pythia_log.jsonl              ← Pythia recommendation log (Phase 5A+)

~/.local/bin/perseus            ← symlink / wrapper

~/.hermes/skills/               ← Hermes Agent skills (default; configurable via assistant.skill_dir)
  perseus-context-engine/
    SKILL.md                    ← `perseus-context-engine` skill
```

---

## Workspace State

@query "git log --oneline -5" fallback="git log unavailable"
@query "git status --short" fallback="clean"

---

## Non-Negotiable Constraints

These apply to every agent working in this repo. They are not up for discussion.

1. **Edit source, regenerate artifact.** Edit `src/perseus/` modules, not `perseus.py`
   directly. Regenerate the single-file artifact with `python scripts/build.py`. Keep the
   generated root artifact committed. Do not add runtime dependencies without explicit approval.
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
Pipe the Pythia prompt directly to a locally running model.
- Primary target: **Ollama** (`http://localhost:11434`, OpenAI-compatible API)
- Secondary: **llama.cpp server** (also OpenAI-compatible)
- No new dependencies — stdlib `urllib` only
- Configurable via `llm:` block in `~/.perseus/config.yaml`
- Flags: `--llm ollama|llamacpp|openai-compat`, `--model <name>`, `--model-url <url>`

**P5A.2 — Pythia recommendation log** (`tasks/task-02`)
Every `perseus suggest` call appends a structured entry to `~/.perseus/pythia_log.jsonl`.
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

### Phase 6 — Daedalus ← COMPLETE ✅

**Daedalus** is the local autonomous scoring model that powers Pythia without any external
round-trip. Named for the master craftsman who built autonomous mechanical intelligences —
the bronze giant Talos, the golden servants — tools that operated on their own once made.

Daedalus is what Pythia runs on when it no longer needs to phone home.

The `pythia_log.jsonl` built in Phase 5A is the training data seed.

**P6.1 — Dataset curation tooling**  
`perseus oracle accept <log-id>` / `reject <log-id>` — flip the `accepted` field in
`pythia_log.jsonl`. Simple CLI for the human to label good recommendations.

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

**Implementation note (2026-05-18):** The Perseus side of Daedalus shipped in task-06.
`perseus oracle accept/reject/log/export` and `--llm daedalus` provider routing are live.
The model itself is a user step — fine-tune your chosen small model on the exported
dataset and push to Ollama under the `llm.daedalus_model` name (default `perseus-daedalus`).

---

### Phase 5C — Context Health (Daedalus v1) ← COMPLETE ✅

Independent of the trained Daedalus model, task-05 shipped **deterministic context
maintenance heuristics** as the first Daedalus-shaped workflow:

- `perseus health [--workspace]` — markdown maintenance report (stdout)
- `@health` directive — embeds the same report inline
- Heuristics: stale checkpoints, near-duplicate checkpoint windows, large `.perseus/context.md`,
  old completed Agora tasks
- Configurable thresholds under the `health:` config block
- Read-only — never modifies files

The naming is intentional: this is the maintenance layer. The trained scoring model in
Phase 6 is the autonomous version.

---

### Phase 7 — Mnēmē: Narrative Project Memory ← COMPLETE ✅

**Mnēmē** (Μνήμη) was the original Muse of Memory — not a log, not a snapshot, but the
*distilled narrative* of experience. She answers the question no snapshot can: *how did we
get here?*

Perseus solves cold-start. Mnēmē solves *arc*: the decisions made three weeks ago, the
approach tried and rejected, the constraint added after a painful bug. The raw material
already exists in checkpoints and the Pythia log. Mnēmē distills it.

**P7.1 — Narrative store and deterministic distillation**  
Per-workspace narrative file at `~/.perseus/memory/<workspace-hash>.md`. Assembled
deterministically from checkpoints (decisions, task history) and Pythia log (patterns,
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
Phase 5 (done):   Track A: Pythia autonomy (--llm, Pythia log, diff)
                  Track B: Agora (task schema, agora subcommand, @agora directive, provider-agnostic)
Spec backfill:    task-07 (multi-workspace namespacing)
                  task-08 (@list + @tree directives)
                  task-09 (@cache persist + mock)
                  task-10 (suggest --quick/--category/--no-services flags)
                  task-11 (linux systemd scaffolding)
                  task-13 (@if query)
                  task-14 (@query fallback)
Phase 5C (done):  task-05 context health + @health directive
Phase 5D (done):  task-08/09/10/11 — @list/@tree, @cache persist/mock, suggest UX flags, systemd
Phase 5A.2 (done):task-07 — multi-workspace checkpoint namespacing
Phase 6 (done):   task-06 Daedalus — dataset curation (oracle accept/reject/log/export) + --llm daedalus routing
Phase 7 (done):   task-12 Mnēmē — narrative project memory, @memory directive, auto-update on checkpoint
Phase 8 (done):   task-15/16/17/18 — @agent, @inbox, template gallery, perseus serve, perseus cron
Phase 8.2 (done): task-19 Mnēmē federation — manifest, 4 CLI subcommands, @memory federation directive
Phase 8.3 (done): Hermes integration — `hermes` provider alias, `perseus llm ping`, docs/HERMES_INTEGRATION.md
Phase 9 (done):   task-20/21/22 — `perseus oracle infer-labels`, `memory.pattern_extractor: daedalus`, `perseus oracle drift` + `@drift`
Phase 10 (done):  task-23/24 — LSP server (`perseus serve --lsp`), VSCode extension (`editors/vscode/`)
Phase 11 (done):   Internal hardening — DIRECTIVE_REGISTRY (task-25 ✅), doctor (task-26 ✅),
                  --json surfaces (task-28 ✅), LSP integration tests (task-27 ✅), split tests (task-29 ✅)
Phase 12 (done):  Schema Validation Engine — schema=, @validate, output_schema, validate CLI
Phase 13 (done):  Predictive Pre-fetching — anticipate next-needed context from patterns
Phase 14 (done):  Adaptive Self-Optimizing Pythia — RL-driven Pythia scoring
              ════════════════════════════════════════════════════════
              STOP: Product identity decision — resolver vs generator
              ════════════════════════════════════════════════════════
Phase 15 (done):  Cited Synthesis Under Scarcity (bounded curator layer)
Phase 16 (done): Product Contract and Context Packs
Phase 17 (done):  Trust, Privacy, and Local Policy
Phase 18 (done):  Distribution and Installation
Phase 19 (done):  Assistant Adapter Ecosystem
Phase 20 (done):  Managed Runtime and Deployment Modes
Phase 21 (done):  Evaluation, Performance, and Compatibility Gates
Phase 22 (done):  v1 Release Candidate
Phase 23 (done):  HTML Output — `perseus render --format html`
Phase 24 (done):   Extensibility Architecture (Hephaestus) — tasks/task-65 through task-74
Phase 25 (done):   MCP Deep Integration — tasks/task-75
Phase 26 (done):   Security Hardening — tasks/task-91 through task-95
Phase 27 (active): Decentralized Federation — tasks/task-96 through task-101 (design phase)
```

---

## Phase 11 — Internal Hardening (Complete)

**Goal:** Make Perseus safe to extend rapidly. No user-facing behavior changes.

### 11A: DIRECTIVE_REGISTRY (task-25) ✅

Single `DirectiveSpec` NamedTuple + `DIRECTIVE_REGISTRY` dict as the canonical
source of truth for all directive metadata. The regex, dispatch chain, LSP
completion tables, and hover safety checks all derive from the registry.

**Why it came first:** Every future directive (schema validation, pre-fetch hooks,
generative context) would have to be added in 5-7 places without this. With it,
one registry entry + one resolver function.

### 11B: `perseus doctor` (task-26) ✅

Readiness probe command with 10 checks (config, context file, render settings,
checkpoint age, Mnēmē narrative, federation, Pythia log, serve loopback,
directive registry). Supports `--json` for CI/agent consumption.

### 11C: `--json` Agent Surfaces (task-28) ✅

Add `--json` flag to 6 commands: `oracle infer-labels`, `oracle drift`,
`llm ping`, `memory status`, `memory federation list`, `memory federation pull`.
Stable JSON contracts for agent consumption, documented in
`docs/AGENT_SURFACES.md` and linked from the README CLI reference.

**Status:** Complete.

### 11D: LSP Integration Tests (task-27) ✅

Real JSON-RPC subprocess tests: spawn `perseus serve --lsp --stdio`, send
`initialize`, `textDocument/didOpen`, verify `publishDiagnostics`, test
completion and hover responses against the DIRECTIVE_REGISTRY.

Also covers shutdown/exit, malformed JSON-RPC, the TCP transport smoke, and the
explicit mutation gate for `perseus.compactMemory`.

### 11E: Split Tests by Subsystem (task-29) ✅

Split `tests/test_perseus.py` into subsystem files plus `tests/conftest.py`.
The test suite is organized by subsystem (oracle, memory, LSP, renderer, etc.) with
shared fixtures in `conftest.py`. Run with `python -m pytest tests/ -q`.

No code changes to `perseus.py`. Mechanical file splitting + `conftest.py`
for shared fixtures. Do this last so all new tests land first.

---

## Phase 12 — Schema Validation Engine

**Goal:** Formalized context quality assurance — Perseus validates that resolved
context is well-formed before injection.

**Why this is next:** It's the most concrete future direction, the proof-of-concept
`@query schema=` modifier already exists, and it directly strengthens the
"resolve-before-context" thesis. If context is resolved but *wrong*, you've
traded the pre-flight tax for a garbage-in problem. Schema validation closes
that gap.

### 12A: Schema DSL & validation engine (task-30) ✅

- Define a YAML-based schema language for context blocks
- Validate `@query`, `@read`, `@env` outputs against declared schemas
- Schema files live in `.perseus/schemas/` per workspace
- New directive: `@validate schema="path" ...@end` wrapping a block

**Decision:** Phase 12 uses option **B** — a minimal built-in schema validator
implemented in pure Python. `pyyaml` remains the only required dependency.

The proof-of-concept added `pykwalify` which violates constraint #2 ("pyyaml is
the only dependency"). Rejected options:

  **A:** Get explicit owner approval for pykwalify as a second dependency
  **C:** Make pykwalify an optional soft dependency — `try: import pykwalify`
  with graceful fallback to a minimal built-in validator

The built-in validator intentionally covers type checks, required fields,
sequences, regex patterns, and enums. It is not full JSON Schema.

**Status:** Complete.

### 12B: Directive-level schema annotations (task-31) ✅

Once the registry exists (✅ done), add an optional `output_schema` field to
`DirectiveSpec`. Directives that declare a schema get automatic validation
on every render — no per-invocation `schema=` modifier needed.

Per-invocation `schema=` remains stronger than registry-level `output_schema`
so local data contracts can override broad directive invariants.

**Status:** Complete.

### 12C: `perseus validate` CLI command (task-32) ✅

Standalone validation: run schemas against a rendered document or a specific
directive's output without a full render pass. Useful for CI gates.

Supports file input or stdin, human output or `--json`, and returns non-zero for
validation failures.

**Status:** Complete.

---

## Phase 13 — Predictive Pre-fetching

**Goal:** Perseus anticipates what context the AI will need *next* and pre-fetches
it, reducing even the render-time latency.

### 13A: Directive dependency graph (task-33) ✅

The registry declares what each directive reads and produces. Build a static
dependency graph: if `@query "git status"` is in the doc, and the Pythia log
shows it's almost always followed by `git diff`, pre-cache the diff output.

**Status:** Complete. `perseus graph <source> [--json]` scans a source document
without executing directives, skips fenced code blocks, and reports registry
metadata plus static resource hints.

### 13B: Pattern-based pre-fetch rules (task-34) ✅

Use explicit, user-configured patterns to identify recurring directive
sequences. Configurable pre-fetch rules in `config.yaml`:

```yaml
prefetch:
  rules:
    - trigger: "@query \"git status\""
      prefetch: "@query \"git diff --stat\" @cache ttl=300"
    - trigger: "@agora status=open"
      prefetch: "@memory focus=decisions @cache ttl=300"
```

**Status:** Complete. `perseus prefetch <source> [--json]` builds the static
graph, matches configured triggers, and executes only cacheable inline
prefetch directives. It reports ran/skipped/failed entries, requires cache
modifiers for prefetch outputs, and respects existing trust gates such as
`render.allow_query_shell`.

### 13C: Daedalus-powered adaptive pre-fetch (task-35) ✅

When a fine-tuned Daedalus model exists, it scores which pre-fetch candidates to
activate based on the current task context. This is where Daedalus transitions
from "label UI + export" to an active runtime component.

**Status:** Complete. Adaptive prefetch is opt-in under `prefetch.adaptive`.
Deterministic scoring uses recent Pythia/Mnēmē pattern text with no LLM. The
Daedalus backend routes through existing LLM plumbing, fails gracefully to the
deterministic scorer, and only scores predeclared cache-warming candidates. It
does not generate new context prose or cross the Phase 14/15 decision gate.

---

## Phase 14 — Adaptive Self-Optimizing Pythia

**Goal:** Pythia's recommendations improve autonomously from real usage signals.

### 14A: Reinforcement signal collection (task-36) ✅

The Pythia log already captures accept/reject. Extend it with:
- Task completion signal (did the accepted recommendation lead to a completed
  checkpoint?)
- Error rate (did the session hit errors after following the recommendation?)
- Time-to-completion

**Status:** Complete. `perseus oracle outcomes [--dry-run] [--json]`
correlates accepted and inferred-accepted Pythia entries with subsequent
checkpoints and writes deterministic `outcome` objects containing completion,
error-rate, checkpoint-count, and time-to-completion signals.

### 14B: Online scoring adjustment (task-37) ✅

Daedalus updates its scoring weights incrementally as new labeled data arrives.
No full retrain needed — moving average over recent accept/reject ratios per
tool/skill path.

**Status:** Complete. `perseus suggest` now computes deterministic
outcome-weight hints from recent Pythia entries with task-36 `outcome` objects.
Successful completed outcomes boost related recommendation tokens; incomplete
or error-heavy outcomes lower them. The hints are transparent in the Pythia
prompt and omitted when no outcome data exists.

### 14C: A/B recommendation testing (task-38) ✅

Occasionally present alternative recommendations alongside the primary one.
Track which the user follows. Exploration/exploitation tradeoff for Pythia.

**Status:** Complete. A/B exploration is off by default. When enabled, Pythia
selects deterministic primary/alternate candidates from outcome-weight signals,
labels the prompt with an exploration id, and records the `ab_test` metadata in
the Pythia log for later accept/reject and outcome attribution.

---

## ═══════════════════════════════════════════
## DECISION GATE — Resolver vs Generator
## ═══════════════════════════════════════════

**Phases 11–14 keep Perseus as a *resolver* — it takes live environment state
and presents it faithfully. The value proposition is trust: what Perseus gives
you is true.**

Phase 15 may add a bounded *curator* layer. It starts putting words in the
context window that did not come directly from one directive, even though every
claim must be backed by exact source citations. Even with guardrails, this is a
philosophical shift:

- **Resolver Perseus:** "Here are the facts."
- **Curator Perseus:** "Here are the cited facts, compressed into claims the
  assistant would otherwise have to rediscover."

This changes the trust model, the error surface, the testing requirements, and
the competitive positioning. It might be the right move — but it's not a
technical decision, it's a product decision.

**Questions to answer before proceeding past Phase 14:**

1. Does Perseus's competitive advantage come from being a *trustworthy resolver*
   or an *intelligent context curator*? These are different products.
2. If Perseus generates context, who is liable when generated context causes
   the AI to make a bad decision? This matters for adoption.
3. Is the generative capability better as a Perseus feature or as something the
   consuming AI does itself with Perseus's resolved context as input?

**Decision brief:** [`docs/RESOLVER_VS_GENERATOR.md`](docs/RESOLVER_VS_GENERATOR.md)
recommends keeping Phase 14 inside the resolver boundary and treating Phase 15
generation as an explicit opt-in product pivot. The accepted Phase 15 direction
is **bounded cited synthesis under context scarcity**, not generic `@read`
elaboration and not an unconstrained generator.

---

## Phase 15 — Cited Synthesis Under Scarcity

**Goal:** Perseus can produce compact, cited synthesis claims only when it has a
pre-assistant advantage: broad source access, context compression, stable reuse,
or cross-source consistency checking. The consuming assistant is already good at
reasoning over facts, so Perseus must not spend trust budget explaining obvious
single-source values.

**Rule:** The LLM is a drafter, not an authority. **No citation, no claim.**
Contradiction checks are secondary; the primary gate is that every generated
claim cites exact source text and invalid or uncited claims are dropped.

### 15A: Cited synthesis contract and CLI (task-39) ✅

Add `perseus synthesize`, an explicit command that builds a line-numbered source
bundle and, only when generation is enabled, lets an LLM draft claims. The
validator keeps only claims with exact source quotes and line citations. Normal
`perseus render` output is unchanged.

### 15B: Cross-source consistency synthesis (task-40) ✅

Use the cited-claim contract for high-value checks such as roadmap/handoff/task
drift, documented-next-action synthesis, and conflicting source summaries. The
output should compress relationships across sources, not restate individual
values.

**Status:** Complete. `perseus synthesize --consistency-mode` with full pipeline:
`build_consistency_prompt` → LLM → `_validate_consistency_conflicts` → separate
`conflicts`/`claims` arrays. Both human and JSON output surfaces work.

### 15C: Optional render surface for curated sections (task-41) ✅

Only after 15B is useful, add an opt-in render surface that places cited
synthesis beside resolved context. Generated sections must be plainly labeled,
JSON surfaces must separate `resolved` from `generated`, and model failure must
leave ordinary render output unchanged.

**Status:** Complete. Verified: `@synthesize` renders labeled generated content,
`generation.enabled` gate respected, graceful degradation on model failure.

---

## Deployable Product Roadmap (Shipped)

The phases below carry Perseus from a powerful local research tool to a
deployable product that can be installed, configured, audited, integrated, and
operated across common assistant/workspace environments. The product line stays
resolver-first: generation is optional, cited, and never allowed to replace
resolved facts.

### Phase 16 — Product Contract and Context Packs ✅

**Goal:** Turn the current feature set into a clear product surface. A new user
should understand what Perseus promises, initialize a workspace profile, and
produce a portable context pack without reading the whole roadmap.

**Status:** Complete. The v1 product promise is documented in
`docs/PRODUCT_CONTRACT.md`, context packs are documented in
`docs/CONTEXT_PACKS.md`, `perseus pack validate/show` validates optional
`.perseus/pack.yaml` manifests, and `perseus init --profile ...` writes
portable profile contexts plus pack manifests for `generic`, `hermes`, `codex`,
`claude-code`, `cursor`, and `rovodev`.

- **16A Product contract (task-42) ✅:** Define the v1 promise, non-goals, trust
  boundaries, supported platforms, and stable CLI surfaces.
- **16B Context pack manifest (task-43) ✅:** Add a workspace manifest that
  names source files, assistant targets, render outputs, trust profile, and
  synthesis packs.
- **16C Init/profile workflow (task-44) ✅:** Extend onboarding so
  `perseus init` can create usable profiles for common assistants and product
  modes.

### Phase 17 — Trust, Privacy, and Local Policy ✅

**Goal:** Make Perseus safe enough for broader deployment. A product user should
be able to see what can execute, what can leave the workspace, what was read,
and what was redacted.

**Status:** Complete. `perseus trust`, permission profiles, deterministic
redaction, audit logging, and `perseus trust audit` are live.

- **17A Permission profiles (task-45) ✅:** Provide named trust profiles such as
  `strict`, `balanced`, and `power-user` over shell, file, serve, agent, and
  generation behavior.
- **17B Secrets and redaction (task-46) ✅:** Add deterministic redaction for
  rendered output, synthesis prompts, logs, and serve endpoints.
- **17C Audit log and trust report (task-47) ✅:** Record local file/shell/model
  access decisions and expose a human/JSON `perseus trust` report.

### Phase 18 — Distribution and Installation

**Goal:** Make Perseus installable without cloning the repo manually. Preserve
the single-file implementation while adding real release artifacts and platform
smoke checks.

**Status:** Complete. Installer bootstrap, release artifacts/versioning, and
scheduler parity are all live. Native Windows Task Scheduler support is
explicitly deferred; platform-agnostic render flows remain available everywhere.

- **18A Installer bootstrap (task-48) ✅:** Add a single-file install/update path
  that places Perseus on PATH and verifies `pyyaml`.
- **18B Release artifacts and versioning (task-49) ✅:** Define version bump,
  changelog, checksum, and signed/hashed release artifact workflow.
- **18C Cross-platform scheduler parity (task-50) ✅:** Close scheduling gaps,
  document cron/launchd/systemd/Windows parity, and defer native Task Scheduler
  while preserving platform-neutral render/cron text generation.

### Phase 19 — Assistant Adapter Ecosystem

**Goal:** Prove Perseus works with multiple downstream assistants through
repeatable adapter contracts instead of one-off docs.

- **19A Adapter conformance harness (task-51) ✅:** Test rendered context outputs
  against expected files and invocation patterns for each supported assistant.
- **19B Assistant profile gallery (task-52) ✅:** Ship maintained profiles for
  Hermes, Codex, Claude Code, Cursor, Rovo Dev, and generic stdin/file flows.
- **19C VSCode extension release polish (task-53) ✅:** Package, document, and
  smoke-test the editor integration as a user-facing adapter.

### Phase 20 — Managed Runtime and Deployment Modes

**Goal:** Let Perseus run as a local service or containerized helper when a team
needs a persistent context endpoint rather than ad hoc CLI execution.

- **20A Authenticated serve mode (task-54) ✅:** Add optional local auth/token gates
  and safe bind defaults for `perseus serve`.
- **20B Container image and compose example (task-55) ✅:** Provide a minimal
  containerized deployment that mounts a workspace and Perseus home.
- **20C Headless watch mode (task-56) ✅:** Add a portable watch/daemon mode that
  refreshes render outputs without depending on platform schedulers.

---

## Planned

### Phase 21 — Evaluation, Performance, and Compatibility Gates

**Goal:** Make releases trustworthy. Product work should have repeatable
fixtures, performance budgets, and migration checks before v1.

- **21A Golden eval corpus (task-57):** Build representative fixture workspaces
  for render, synthesis, trust, memory, serve, and adapter behavior.
- **21B Performance budgets (task-58):** Track render, graph, prefetch,
  synthesize, serve, and LSP latency against documented budgets.
- **21C Compatibility and migration suite (task-59):** Verify old configs,
  checkpoints, cache files, Pythia logs, and memory narratives still work.

### Phase 22 — v1 Release Candidate

**Goal:** Produce a deployable v1 candidate with docs, examples, artifacts,
release gates, and a clear support envelope.

- **22A Documentation site and quickstart (task-60):** Create user-facing docs
  organized around installation, first context pack, trust settings, adapters,
  and operations.
- **22B Example workspace/demo pack (task-61):** Ship realistic demo workspaces
  that show local-only, assistant-profile, and managed-runtime deployments.
- **22C Release candidate checklist (task-62):** Freeze v1 criteria, run the
  full validation matrix, and cut the first release candidate.

At the end of Phase 22, Perseus should be a working product: installable from a
release artifact, configurable through profiles/manifests, safe by default,
integrated with major assistant workflows, operable as CLI/service/container,
and validated by repeatable release gates.

---

### Phase 23 — HTML Output

`perseus render --format html` produces self-contained, zero-dependency HTML
dashboards. Dark theme matches the perseus.observer landing page. `@services`
results are parsed into service-card divs with green/red status dots. Long code
blocks are collapsed behind `<details>` elements. The HTML is fully self-contained —
no CDN, no external fonts, no JavaScript — and opens in any browser offline.

Architecture: post-processing. Directives resolve to markdown as always, then
a new `html_format.py` module converts to semantic HTML and wraps in the
document template. Zero new dependencies. All tests passing.

---

### Phase 24 — Extensibility Architecture ✅ Complete

**Goal:** Perseus becomes extensible without source patching. Users can add
directives, macros, validators, format adapters, pipeline hooks, and remote
resolvers from `~/.perseus/plugins/` — no rebuild, no fork.

**Current gap:** The `DIRECTIVE_REGISTRY` is clean internally but every
extension requires editing `registry.py`, adding a resolver to the source tree,
and rebuilding the artifact. A plugin system makes Perseus a *platform* rather
than a closed tool.

**Etymology:** **Hephaestus** forged the automata — self-operating bronze
servants, the golden maiden assistants, Talos the bronze guardian who patrolled
Crete's shores. Extensibility is Hephaestus's domain: giving Perseus the
ability to forge its own tools.

#### 24A — Plugin Directive System (task-65)

Auto-discovered Python plugins under `~/.perseus/plugins/`. Each module exports
a `REGISTER` dict of `DirectiveSpec` entries. `_bind_registry()` scans and
merges them before building the inline regex. Plugin errors are warnings, not
fatal — a broken plugin never breaks render.

Config gate: `plugins.enabled` (default: `true`). Trust boundaries: plugin
directives inherit the workspace permission profile but cannot override safety
gates.

#### 24B — Directive Macros (task-66)

Declarative composition without code. `@macro name ... @endmacro` blocks in
context documents or in a shared `.perseus/macros.md`. The pre-processing pass
expands macro invocations before the resolver loop, so macros compose existing
directives with zero Python.

```markdown
@macro project-health
@health
@agora status=open
@drift
@endmacro

@project-health  ← expands to the three directives above
```

#### 24C — Render Pipeline Hooks (task-67)

Lifecycle callbacks for observability and CI integration:

| Hook | Fires |
|---|---|
| `on_render_start` | Source doc opened, pre-processing |
| `on_directive_resolved` | After each directive (name, args, result, cache hit/miss) |
| `on_cache_hit` / `on_cache_miss` | Cache layer events with key + directive |
| `on_render_complete` | All output assembled |
| `on_directive_error` | Any resolver throws (directive, error, traceback) |

Hooks are shell commands or Python callbacks (same plugin discovery pattern).
Non-blocking — hook failure is logged but never breaks render. Configurable
per-hook in `config.yaml`.

#### 24D — Output Format Adapters (task-68)

Plugin interface for format adapters beyond the built-in markdown and HTML.
`perseus render --format json` resolves directives and returns structured
`{resolved: ..., directives: [{name, args, output, cached}, ...]}`.

Custom formats live in `~/.perseus/formats/<name>.py` and export a
`render(resolved_markdown, metadata) -> str` function. The `metadata` dict
carries directive execution records, timestamps, cache stats, and integrity
results.

#### 24E — Foreign Resolver Protocol (task-69)

Remote directive that fetches rendered context from another Perseus serve
instance. Enables distributed context: a team server renders shared
infrastructure context; individual workstations pull it inline.

```
@perseus https://team-server:8420/workspace/infra  @cache ttl=300
```

Trust model: HMAC signature verification (opt-in), TTL caching, graceful
degradation on connection failure. Works with authenticated serve mode
from Phase 20A.

MCP deep integration: expose each directive as an MCP tool so any MCP
client can invoke `@query`, `@read`, `@services` through the MCP transport
without touching Perseus syntax. The existing `src/perseus/mcp.py` server
gets extended from read-only `get_context`/`get_health` to the full directive
surface.

#### 24F — Custom Schema Validators (task-70)

Plugin validators co-located with schema files in `.perseus/schemas/`.
Each validator module exports `validate(value, schema) -> (bool, str)`.
Referenced via `schema="plugin:my-validator"` in any `schema=` modifier
or `@validate` block. Works alongside the built-in validator — plugin
validators can enforce domain-specific contracts (e.g., "this YAML must
contain exactly 3 services, each with a `port` field").

#### 24G — Pipe Syntax for Directive Composition (task-71)

Lightweight chaining without macros. Results of one directive feed into
the next:

```markdown
@query "ls services/" | @cache ttl=300
@read config.yaml path="endpoints" | @validate schema="endpoint-list"
```

Pipes are resolved left-to-right. The output of directive N becomes the
input (args) of directive N+1. More natural than separate lines for simple
two-step pipelines. Macros (24B) remain the right tool for 3+ step
compositions.

#### 24H — Event Webhooks (task-72)

POST render lifecycle events to an external URL. Separate from pipeline
hooks (24C) — webhooks are for external observability (dashboards, CI
status, Slack notifications); hooks are for local processing.

Config-driven: `webhooks.url`, `webhooks.events` (subset of lifecycle
events), `webhooks.secret` (HMAC-SHA256 signing). Payload is JSON with
event type, timestamp, workspace hash, and event-specific data.

#### 24I — Tool Directive Integration (task-73)

Generic external tool invocation with an allowlist:

```markdown
@tool "path/to/scanner.py" --workspace . @cache ttl=3600
```

The tool's stdout becomes the directive output. Tools are registered in
config (`tools.allowlist`) with optional argument allowlists. Similar to
`@agent` but with a structured tool contract (exit code semantics, timeout,
output size cap) and explicit allowlist gating.

#### 24J — Directive Aliasing (task-74)

Shorthand and namespacing without code:

```yaml
# config.yaml
directives:
  aliases:
    "@q": "@query"
    "@svc": "@services"
    "@mb": "@memory"
```

Aliases are expanded before the resolver loop. Namespaced to prevent
collisions with built-in directives (built-ins always win). Useful for
teams with domain-specific shorthand conventions.

---

#### Execution Order

```
Phase 24A ─── Plugin directives (task-65)
    │          Foundation — everything else builds on plugin discovery
    │
    ├── 24B ─── Directive macros (task-66)
    ├── 24C ─── Pipeline hooks (task-67)
    ├── 24D ─── Format adapters (task-68)
    ├── 24E ─── Foreign resolver protocol (task-69)
    ├── 24F ─── Custom schema validators (task-70)
    ├── 24G ─── Pipe syntax (task-71)
    ├── 24H ─── Event webhooks (task-72)
    ├── 24I ─── Tool directive integration (task-73)
    └── 24J ─── Directive aliasing (task-74)
```

24A is the dependency — plugins are the substrate that macros, hooks,
validators, and format adapters all use for discovery. 24B–24J can run
in any order once 24A lands.

---

## Phase 25 — MCP Deep Integration ✅ Complete

**Goal:** Bridge Perseus into the broader AI ecosystem by exposing every
directive as a first-class MCP tool. Any MCP-compatible client — Claude Desktop,
Continue, Cursor, Zed, Codex — can invoke `perseus_query`, `perseus_read`,
`perseus_services` as native tools without parsing Perseus syntax.

The existing `src/perseus/mcp.py` already provides read-only `get_context` and
`get_health` MCP tools. This phase extends it to the full directive surface,
making Perseus a universal context provider across the MCP ecosystem.

### 25A — Expose directives as MCP tools (task-75)

Each directive in the `DIRECTIVE_REGISTRY` (built-in + plugin) becomes an MCP
tool named `perseus_<name>`. Tool descriptions and input schemas are
auto-generated from registry metadata. Trust gates are enforced per-tool.

**Status:** Complete. `perseus mcp serve` runs a JSON-RPC 2.0 MCP server over stdio,
exposing all directive registry entries (built-in + plugin) as `perseus_<name>` tools.
Trust gates enforced per-tool. Backward compatible with existing `perseus_get_context` /
`perseus_get_health`. MCP Registry listing published live.

Full spec in the task file. Covers:
- Tool mapping for all built-in directives
- Plugin directive tool exposure
- Stdio and HTTP+SSE transports
- Trust gate enforcement
- Backward compatibility with existing `perseus_get_context` / `perseus_get_health`

---

## Phase 26 — Security Hardening & Review Fixes

**Source:** Claude Code Opus 4.7 Medium review of v1.0.5 (2026-05-27).
All findings verified against `src/perseus/`. See `.claude/review-prompt.txt` for the full review prompt.

### 26A — Fix MCP SSE authentication (task-91)

**Problem:** `POST /message` in the SSE transport (`mcp.py:380`) has no auth layer,
unlike `serve` mode which learned bearer-token auth in Phase 20A. Any local
process can drive the MCP server over the SSE transport.

**Fix:** Add bearer-token auth consistent with `serve` mode. Read token from
`mcp.sse_bearer_token` config key. Reject unauthenticated `POST /message` with 401.

**Status:** ✅ Complete

---

### 26B — MCP timeout: thread-based fallback for Windows (task-92)

**Problem:** `_call_tool()` timeout (`mcp.py:222`) uses `signal.SIGALRM`, which does
not exist on Windows. The `else:` branch has no timeout enforcement — a slow tool
can hang the entire MCP server indefinitely. Also: if the resolver finishes between
`signal.alarm(timeout)` and the handler restore in the `except` arm, a stale
alarm handler is left installed.

**Fix:** Replace SIGALRM with a `threading.Timer`-based timeout that works on all
platforms. Use `concurrent.futures.ThreadPoolExecutor` to run the resolver in a
separate thread with a `Future.result(timeout=...)`. Clean up alarm references.

**Status:** ✅ Complete

---

### 26C — Foreign resolver URL allowlist & SSRF protection (task-93)

**Problem:** `@perseus <url>` (`directives/perseus.py:60`) has no URL allowlist —
any reachable URL is fetched. `verify_signatures` defaults to `False`. No SSRF
protection: `https://169.254.169.254/...` (cloud metadata), RFC1918, and
link-local addresses are reachable. Response data flows directly into rendered
context that an LLM reads — a prompt-injection vector.

**Fix:**
- Add `foreign_resolver.url_allowlist` config key (list of URL prefixes).
- Add `foreign_resolver.block_private_ips` config key (default `true`) —
  block RFC1918, link-local, loopback (non-`127.0.0.1`), and cloud metadata IPs.
- Add `foreign_resolver.verify_signatures` defaulting to `True`.
- Document the prompt-injection risk prominently in README.

**Status:** ✅ Complete

---

### 26D — Build script: multi-line import support (task-94)

**Problem:** `INTERNAL_IMPORT_RE` (`build.py:73`) only matches single-line
`from perseus.x import y` statements. A future multi-line import:
```python
from perseus.x import (
    a,
    b,
)
```
would strip the first line but leave `a,` / `b,` / `)` as orphaned syntax,
producing a broken artifact with no build error.

**Fix:** Extend the regex (or add a multi-line state machine in the build loop)
to consume through the closing `)`. Add a build-correctness test that introduces
a deliberate multi-line internal import in a fixture module and asserts the
build either handles it or fails loudly.

**Status:** ✅ Complete

---

### 26E — Fix `_mneme_delete_document` GLOB test failure (task-95)

**Problem:** `test_delete_document_removes` fails after the Mnēmē connection
cache and transaction changes. The GLOB pattern `*/del.md` doesn't match the
stored absolute path, or the build_index transaction hasn't committed before
the delete queries. Needs investigation.

**Fix:** Debug the `BEGIN IMMEDIATE` commit visibility on the cached connection.
Ensure the FTS5 `rebuild` call flushes before subsequent reads. Verify GLOB
pattern matching against the actual stored path format.

**Status:** ✅ Complete

---

## Phase 27 — Decentralized Federation

**Status:** 🔨 In progress (design phase)  
**Architecture doc:** `docs/DECENTRALIZED_FEDERATION.md`

Decentralized Federation extends Phase 8.2 federation across machine and
organizational boundaries. The existing filesystem-based manifest becomes
one transport among several: HTTP pull from `perseus serve` endpoints,
push notification on checkpoint write, and eventually cross-org capability
grants.

Every narrative carries a cryptographic signature and a provenance chain
back to its source workspace. Trust is explicit key pinning — no CA, no
PKI. When narratives conflict, Perseus shows both with provenance, never
silently resolves.

### 27A — Remote Federation Transport (task-96)

Extend federation to pull narratives over HTTP from `perseus serve`
endpoints. The foundation everything else builds on.

- Extend federation manifest schema with `remote:` block (url, auth_token, verify_key)
- Add `GET /federation/narrative` endpoint to `perseus serve`
- `perseus memory federation pull` learns fetch-from-remote path
- `@memory federation` renders remote narratives inline with provenance badges
- Local caching in `~/.perseus/cache/federation/`
- Graceful degradation: unreachable remote → warning block with last-known-good timestamp

### 27B — Cryptographic Identity & Signing (task-97)

- `perseus identity init` — generate workspace keypair (`~/.perseus/keys/identity.yaml`)
- `perseus identity show` — display public key and workspace ID
- `perseus memory sign` — sign current narrative (HMAC-SHA256 for v1)
- `perseus memory verify <hash>` — verify a received narrative against pinned key
- Auto-sign on checkpoint write when `federation.signing.enabled: true`
- Ed25519 upgrade path documented for when Python nacl bindings stabilize

### 27C — Push Federation (task-98)

- Extend `perseus serve` with `POST /federation/receive` endpoint
- Extend federation manifest with `push_url` and `push_token`
- Fire-and-forget POST on checkpoint write (3 retries, exponential backoff)
- Push failures are warnings, never fatal — pull remains the canonical refresh path

### 27D — Access Control & Capability Grants (task-99)

- Token-scoped access: per-subscriber bearer tokens
- `perseus identity grant <workspace_id> --scope narrative --ttl 30d`
- `perseus identity revoke <grant_id>`
- `serve` middleware checks grants on each `/federation/` request
- `federation.d/` directory of per-subscription YAML as alternative to monolithic manifest

### 27E — Conflict Detection & Merge Assistance (task-100)

- Topic overlap detection via Mnēmē focus tags and FTS5 similarity
- `perseus memory federation diff <a> <b>` — side-by-side conflict view
- `perseus memory federation merge <a> <b>` — Pythia-assisted reconciliation draft
- `@federation conflicts` directive — renders detected conflicts inline
- Merge output uses cited synthesis; never auto-applied

### 27F — Provenance Chain Verification (task-101)

- Narrative frontmatter extended with `prev_signature` and `sequence` fields
- `perseus memory verify --chain <hash>` — verify entire hash chain to genesis
- `perseus memory provenance <hash>` — display full provenance tree
- `@memory provenance` directive — renders provenance inline
- `perseus identity rotate` — key rotation with history chain

#### Execution Order

```
Phase 27A ─── Remote pull via HTTP (task-96)   ← foundation
    │
    ├── 27B ─── Identity + signing (task-97)
    ├── 27C ─── Push federation (task-98)
    ├── 27D ─── Access control (task-99)
    ├── 27E ─── Conflict detection (task-100)
    └── 27F ─── Provenance chain (task-101)
```

27A is the hard dependency. 27B–27F can run in any order after 27A
lands, though 27B (signing) is a natural prerequisite for 27C (push)
and 27F (provenance).

The full architecture is in `docs/DECENTRALIZED_FEDERATION.md`.

---

## 12-Month Delivery Calendar (Jul 2026 → Jun 2027)

Calendar overlay onto the phase backlog above, sequenced with the Mimir and Plutus
roadmaps. Cross-product master doc: `…/workspace/ROADMAP_2026-2027.md`.

| Quarter | Theme | Perseus deliverables |
|---|---|---|
| **Q3 2026** (Jul–Sep) | Federation foundation | Lock Mimir auto-discovery + live context injection as the default Hermes path; publish reproducible Gauntlet v2 score + methodology; CI smoke test; PyPI metadata pass; **Phase 27A: remote federation transport + 27B: identity/signing** |
| **Q4 2026** (Oct–Dec) | IDE & federation push | VS Code + Cursor integration (render `@perseus` context into the editor agent panel); "Built with Perseus" badge program; Perseus-as-MCP-client; **Phase 27C: push federation + 27D: access control/grants** |
| **Q1 2027** (Jan–Mar) | Leaderboard & teams | Public Gauntlet leaderboard site (external submissions); team workspace support — shared checkpoints + federation across a team manifest; **Phase 27E: conflict detection/merge + 27F: provenance chain** |
| **Q2 2027** (Apr–Jun) | Platform | Perseus Cloud groundwork — hosted read-only `perseus serve` for teams; synthesis-as-a-service (cited-claim synthesis behind an API); **Decentralized federation GA** |

---

## Execution Order

```
Phase 11A ─── DIRECTIVE_REGISTRY (task-25) ✅ ──────────┐
              │                                          │
Phase 11B ─── doctor (task-26) ✅ ───────────────────────┤
              │                                          │
Phase 11C ─── --json surfaces (task-28) ✅ ─────────────┤
              │                                          │
Phase 11D ─── LSP integration tests (task-27) ✅ ───────┤
              │                                          │
Phase 11E ─── Split tests (task-29) ✅ ─────────────────┤
              │                                          │
              └── Phase 12A: Schema validation ✅ ────────┤
                  Option B: pure-Python validator         │
                  (pyyaml remains the only dependency)    │
                                                         │
Phase 12B ─── Directive-level schema annotations ✅ ─────┤
Phase 12C ─── `perseus validate` CLI ✅ ─────────────────┤
                                                         │
Phase 13A ─── Directive dependency graph ✅ ─────────────┤
Phase 13B ─── Pattern-based pre-fetch rules ✅ ──────────┤
Phase 13C ─── Daedalus-powered adaptive pre-fetch ✅ ────┤
                                                         │
Phase 14A ─── RL signal collection ✅ ───────────────────┤
Phase 14B ─── Online scoring adjustment ✅ ──────────────┤
Phase 14C ─── A/B recommendation testing ✅ ─────────────┤
                                                         │
              ══════════════════════════════════          │
              STOP: Product identity decision             │
              ══════════════════════════════════          │
                                                         │
Phase 15A ─── Cited synthesis contract ✅ ────────────────┤
Phase 15B ─── Cross-source consistency synthesis ✅ ─────────┤
Phase 15C ─── Optional curated render surface ✅ ──────────────┤
                                                         │
Phase 16A ─── Product contract ✅ ───────────────────────┤
Phase 16B ─── Context pack manifest ✅ ──────────────────┤
Phase 16C ─── Init/profile workflow ✅ ──────────────────┤
                                                         │
Phase 17A ─── Permission profiles ✅ ────────────────────┤
Phase 17B ─── Secrets and redaction ✅ ──────────────────┤
Phase 17C ─── Audit log and trust report ✅ ─────────────┤
                                                         │
Phase 18A ─── Installer bootstrap ✅ ────────────────────┤
Phase 18B ─── Release artifacts/versioning ✅ ───────────┤
Phase 18C ─── Scheduler parity ✅ ───────────────────────┤
                                                         │
Phase 19A ─── Adapter conformance harness ✅ ────────────┤
Phase 19B ─── Assistant profile gallery ✅ ──────────────┤
Phase 19C ─── VSCode extension release polish ✅ ────────┤
                                                         │
Phase 20A ─── Authenticated serve mode ✅ ───────────────┤
Phase 20B ─── Container image and compose example ✅ ────┤
Phase 20C ─── Headless watch mode ✅ ────────────────────┤
                                                         │
Phase 21A ─── Golden eval corpus ✅ ─────────────────────┤
Phase 21B ─── Performance budgets ✅ ────────────────────┤
Phase 21C ─── Compatibility/migration suite ✅ ──────────┤
                                                         │
Phase 22A ─── Documentation site and quickstart ✅ ──────┤
Phase 22B ─── Example workspace/demo pack ✅ ────────────┤
Phase 22C ─── v1 release candidate checklist ✅ ─────────┤
                                                         │
Phase 23  ─── HTML output ✅ ────────────────────────────┤
                                                         │
Phase 24A ─── Plugin directives (task-65) ✅ ───────────┤
    │          Foundation — everything below depends on it │
    ├── 24B ─── Directive macros (task-66) ✅ ────────────┤
    ├── 24C ─── Pipeline hooks (task-67) ✅ ──────────────┤
    ├── 24D ─── Format adapters (task-68) ✅ ─────────────┤
    ├── 24E ─── Foreign resolver protocol (task-69) ✅ ───┤
    ├── 24F ─── Custom schema validators (task-70) ✅ ────┤
    ├── 24G ─── Pipe syntax (task-71) ✅ ─────────────────┤
    ├── 24H ─── Event webhooks (task-72) ✅ ──────────────┤
    ├── 24I ─── Tool directive integration (task-73) ✅ ──┤
    └── 24J ─── Directive aliasing (task-74) ✅ ──────────┘
                                                         │
Phase 25  ─── MCP deep integration (task-75) ✅ ─────────┘
                                                         │
Phase 26A ─── MCP SSE authentication (task-91) ✅ ───────┤
    ├── 26B ─── Windows MCP timeout (task-92) ✅ ─────────┤
    ├── 26C ─── Foreign resolver SSRF (task-93) ✅ ───────┤
    ├── 26D ─── Build multi-line import (task-94) ✅ ─────┤
    └── 26E ─── Delete-doc GLOB test fix (task-95) ✅ ────┘
                                                         │
Phase 27A ─── Remote federation transport (task-96) 🔨 ──┤
    │          Foundation — pull narratives over HTTP      │
    ├── 27B ─── Identity + signing (task-97) ─────────────┤
    ├── 27C ─── Push federation (task-98) ────────────────┤
    ├── 27D ─── Access control + grants (task-99) ────────┤
    ├── 27E ─── Conflict detection + merge (task-100) ────┤
    └── 27F ─── Provenance chain (task-101) ──────────────┘
```

---

## Exploratory — directional, not committed (no dates)

Ideas we may pursue once the foundation work and the near-term calendar above are
settled. Listed to capture intent — **not** commitments — and deliberately without
dates or phase numbers. (An earlier revision of this section invented a
quarter-by-quarter plan through 2031; that false precision has been removed.)

**Federation & sharing**
- Multi-hop federation across organizational trust boundaries, with freshness metadata per hop
- Shareable, versioned, signed context packs and a community directive registry (`perseus pack`, `directives.perseus.observer`)

**Autonomy (Daedalus)**
- Daedalus proposes `context.md` edits and new `@query`/`@memory` directives from observed usage — human-approved by default
- Autonomous context maintenance: prune stale directives, surface broken or never-read ones

**Smarter resolution**
- Model-aware output: per-model token budgets from a single source document
- Intent-driven pre-resolution on session start (active branch, time of day, recent sessions, Mimir hot entities)
- ~~Context diffing — "what changed since last session" as a first-class delta~~ — **shipped as `@context-diff` (#714)**
- Context-aware task routing using Plutus cost data — *cross-product; gated on Plutus reaching 1.0 (see product strategy)*

**Ecosystem & reach**
- Context Adapter SDK (Python/TS/Rust/Go) so any tool can emit `@directive` sources
- Multi-agent context protocol: resolve once, share resolved context across LangGraph/CrewAI/AutoGen/custom orchestrators
- Perseus Enterprise: SSO, audit logging, compliance, on-prem / air-gapped deployment
- Zero-config ambient context as a system service; the `.perseus/context.md` format as an ecosystem standard
- Editor/IDE integration and native desktop/mobile apps

---

## Architecture

```
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
