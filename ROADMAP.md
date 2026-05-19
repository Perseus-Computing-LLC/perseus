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
**Workspace:** current repo checkout  
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
| **Agora** | Async agent coordination substrate — task queue + `@agora` directive | ✅ Phase 5C |
| **Health** | Deterministic context maintenance heuristics — `perseus health` + `@health` directive (Daedalus v1) | ✅ Phase 5E |
| **Daedalus** | Local autonomous scoring model — Pythia without a round-trip (dataset + routing shipped; model training is a user step) | ✅ Phase 6 |
| **Mnēmē** | Narrative project memory — distills checkpoints + oracle log into a per-workspace narrative | ✅ Phase 7 |
| **Federation** | Cross-workspace Mnēmē narrative aggregation via subscribable manifest | ✅ Phase 8.2 |
| **Templates** | Starter scaffolds for generic/hermes/rovodev/claude-code/cursor via `perseus init --template` | ✅ Phase 8 |
| **Serve** | Read-only HTTP view of workspace state | ✅ Phase 8 |
| **Inbox** | Per-workspace point-to-point message store + `@inbox` directive | ✅ Phase 8 |
| **Cron** | Cross-platform scheduler (macOS/Linux/BSD) — bridges launchd + systemd | ✅ Phase 8 |

---

## What's Built

### `perseus.py` — full CLI

@query "grep -o 'perseus alpha v[0-9.]*' perseus.py | head -1" fallback="perseus version unavailable"

| Command | What it does |
|---|---|
| `perseus render <file.md>` | Resolves `@perseus` source doc → plain markdown |
| `perseus validate --schema SCHEMA [payload|-]` | Validates a payload against a Perseus schema; `--json` for CI/agents |
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
  perseus.py                    ← single-file CLI; entire implementation lives here
  requirements.txt              ← pyyaml only; no other deps
  tests/
    conftest.py                 ← shared Perseus loader and test helpers
    test_*.py                   ← subsystem pytest files; must pass before any commit
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

@query "git log --oneline -5" fallback="git log unavailable"
@query "git status --short" fallback="clean"

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

### Phase 6 — Daedalus ← COMPLETE ✅

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
Phase 12:         Schema Validation Engine — formalized context quality assurance
Phase 13:         Predictive Pre-fetching — anticipate next-needed context from patterns
Phase 14:         Adaptive Self-Optimizing Oracle — RL-driven Pythia scoring
              ════════════════════════════════════════════════════════
              STOP: Product identity decision — resolver vs generator
              ════════════════════════════════════════════════════════
Phase 15:         Generative Context Enhancement (if decided yes)
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
checkpoint age, Mnēmē narrative, federation, oracle log, serve loopback,
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
The suite now collects 272 tests and the latest run is 271 passed, 1 skipped
(sandbox-blocked TCP bind; the same TCP smoke passes outside the sandbox).
- `test_oracle.py` — suggest, oracle log, drift, infer-labels
- `test_memory.py` — Mnēmē narrative, federation
- `test_lsp.py` — LSP helpers, framing, diagnostics

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

### 13A: Directive dependency graph

The registry declares what each directive reads and produces. Build a static
dependency graph: if `@query "git status"` is in the doc, and the oracle log
shows it's almost always followed by `git diff`, pre-cache the diff output.

### 13B: Pattern-based pre-fetch rules

Use the oracle log + Mnēmē narrative patterns to identify recurring directive
sequences. Configurable pre-fetch rules in `config.yaml`:

```yaml
prefetch:
  rules:
    - trigger: "@query \"git status\""
      prefetch: "@query \"git diff --stat\""
    - trigger: "@agora status=open"
      prefetch: "@memory focus=decisions"
```

### 13C: Daedalus-powered adaptive pre-fetch

When a fine-tuned Daedalus model exists, it scores which pre-fetch rules to
activate based on the current task context. This is where Daedalus transitions
from "label UI + export" to an active runtime component.

---

## Phase 14 — Adaptive Self-Optimizing Oracle

**Goal:** Pythia's recommendations improve autonomously from real usage signals.

### 14A: Reinforcement signal collection

The oracle log already captures accept/reject. Extend it with:
- Task completion signal (did the accepted recommendation lead to a completed
  checkpoint?)
- Error rate (did the session hit errors after following the recommendation?)
- Time-to-completion

### 14B: Online scoring adjustment

Daedalus updates its scoring weights incrementally as new labeled data arrives.
No full retrain needed — moving average over recent accept/reject ratios per
tool/skill path.

### 14C: A/B recommendation testing

Occasionally present alternative recommendations alongside the primary one.
Track which the user follows. Exploration/exploitation tradeoff for the oracle.

---

## ═══════════════════════════════════════════
## DECISION GATE — Resolver vs Generator
## ═══════════════════════════════════════════

**Phases 11–14 keep Perseus as a *resolver* — it takes live environment state
and presents it faithfully. The value proposition is trust: what Perseus gives
you is true.**

Phase 15 makes Perseus a *generator*. It starts putting words in the context
window that didn't come directly from the environment. Even with guardrails,
this is a philosophical shift:

- **Resolver Perseus:** "Here are the facts."
- **Generator Perseus:** "Here are the facts, and here's what I think they mean."

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

---

## Phase 15 — Generative Context Enhancement (Contingent)

**Goal:** Perseus can *elaborate* sparse context using an LLM, with strict
verification guardrails. **Only proceed if the decision gate above is resolved.**

### 15A: Verified elaboration for `@read`

When `@read` pulls a config value, Perseus can optionally explain *what it
means* by cross-referencing the project's docs or README. The elaboration is
verified against the raw value — if it contradicts the source, it's dropped.

### 15B: Guardrail framework

Every generated elaboration must pass:
1. Source citation (which raw context was the basis?)
2. Contradiction check (does the elaboration contradict any resolved directive?)
3. Confidence threshold (below threshold → omit, don't guess)

---

## Future Direction: Decentralized Federation

Deepen federation to securely share context across decentralized workspaces or
organizations. Dynamic access control, conflict resolution, provable data lineage.
This changes the deployment model from single-node to distributed — an
infrastructure and trust boundary question separate from the resolver/generator
decision above.

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
Phase 13A ─── Directive dependency graph ────────────────┤
Phase 13B ─── Pattern-based pre-fetch rules ─────────────┤
Phase 13C ─── Daedalus-powered adaptive pre-fetch ───────┤
                                                         │
Phase 14A ─── RL signal collection ──────────────────────┤
Phase 14B ─── Online scoring adjustment ─────────────────┤
Phase 14C ─── A/B recommendation testing ────────────────┤
                                                         │
              ══════════════════════════════════          │
              STOP: Product identity decision             │
              ══════════════════════════════════          │
                                                         │
Phase 15  ─── Generative Context (if decided yes) ───────┘
```

**Estimated scope:** Phase 11 and Phase 12 are complete. Phase 13 is 2 sessions.
Phase 14 is 2-3 sessions. Then the decision gate.

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
