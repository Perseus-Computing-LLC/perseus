# Components

## Priority Order

The oracle is the MVP — the thing that actually solves the Medusa problem. The renderer and waypoints are supporting infrastructure that feed it live environment data to score against. Build order:

1. **Oracle** — tool/skill selection with scored recommendations
2. **Renderer** — live context injection (feeds the oracle's env awareness)
3. **Checkpoints** — lightweight session recovery (feeds the oracle's recency signal)

---

## 1. Tool Oracle (`perseus suggest`) — **MVP / Alpha**

Given a task description and the current environment state, returns a ranked list of approaches: which Hermes skill to load, which integration to prefer, which path minimizes latency and maximizes fidelity.

This is the core value prop. Every other component exists to make this answer more accurate.

### Interface

```bash
perseus suggest "download and summarize recent arxiv papers on RAG"
perseus suggest "download and summarize recent arxiv papers on RAG" --llm ollama
```

### Output

```
Suggested approaches for: "download and summarize recent arxiv papers on RAG"
Environment: 2026-05-18 06:49 CT | Hermes WebUI ✅ | 87 skills loaded

1. ★★★  skill:arxiv + web_extract
   Load the arxiv skill, search by keyword, fetch papers via web_extract.
   Why: arxiv skill handles structured search + metadata; web_extract handles PDF→markdown.
   Deps: all present. No service issues detected.

2. ★★☆  web_search + web_extract
   Generic fallback. Works but loses structured arxiv metadata (categories, authors, IDs).
   Use if: arxiv skill is unavailable or you need broader source coverage.

3. ★☆☆  skill:dspy RAG pipeline
   Overkill for a one-off. Worth it if this becomes a recurring automated job.
```

### Scoring Factors

| Factor | Signal Source | Weight |
|---|---|---|
| Skill availability | `~/.hermes/skills/` directory scan | High |
| Skill freshness | Last-modified date vs. 30-day threshold | Medium |
| Service health | `@services` render (live health checks) | High |
| Task complexity match | Heuristic: one-off vs. recurring, structured vs. ad-hoc | Medium |
| Recency signal | Last waypoint — what tools worked in recent sessions | Medium |
| Token/latency estimate | Rough cost model per approach type | Low |

### Alpha / Phase 5A Scope

Perseus still supports the original **structured prompt** flow over live environment state. In addition, the current implementation supports an optional local-model path via `perseus suggest --llm ollama[:model]`. This keeps prompt generation as the core interface while allowing local inference when available.

Full autonomous scoring and learned ranking remain future milestones.

---

## 2. Renderer (`perseus render`)

Processes a source `.md` file with a `@perseus` header and produces plain markdown with all directives resolved. The assistant never sees directive syntax — only resolved values.

### Source Format

Any standard `.md` file. Perseus activates when `@perseus` appears on the first line:

```markdown
@perseus v0.4

@prompt
This document was rendered live. All values are current.
@end

# Session Context — @date format="YYYY-MM-DD HH:mm z"
...
```

No specialized file extension. Compatible with all markdown tooling, renderable as-is by GitHub, editors, and existing AI context systems. Existing `AGENTS.md` / `CLAUDE.md` files can opt in by adding `@perseus` to the first line.

### Rendering Pipeline

```
source.md  (@perseus header)
    │
    ▼
[Parse] — tokenize directives vs. passthrough markdown
    │
    ▼
[Resolve] — execute each directive (shell, file, http, env...)
    │  ↕ cache layer (session / ttl / persist)
    ▼
[Conditional eval] — @if/@else blocks collapsed to one branch
    │
    ▼
[Assemble] — stitch resolved values into final markdown
    │
    ▼
rendered output  →  injected into assistant context
```

See [`directives.md`](directives.md) for the full directive reference.

---

## 3. Checkpoints (`perseus checkpoint`)

Checkpoint state can now also be compared with `perseus diff`, which renders a field-level diff between two checkpoints or the latest pair.

Lightweight resumption snapshots. Written explicitly by the assistant at natural pause points — end of a task, before a large operation, at a logical handoff. Not automatic, not a log.

### Design Principles

- **Explicit over automatic.** The assistant calls `perseus checkpoint` as a tool at the right moment. This keeps the implementation simple and the data meaningful — checkpoints are written when there's actually something worth resuming, not on a timer.
- **Lightweight.** A checkpoint is a YAML file with 5-8 fields. It should take one tool call to write and one to read.
- **Resumption-focused.** Contains only what's needed to continue without re-orientation. Not a log, not an audit trail.

### Write (assistant tool call)

```bash
perseus checkpoint \
  --task "Rewriting webhook handler to validate Bearer token" \
  --status "done — handler written and tested" \
  --next "update .env.example with HERMES_WEBHOOK_SECRET placeholder" \
  --workspace /workspace/hermes-ntfy \
  --notes "JWT lib is python-jose; secret lives in .env as HERMES_WEBHOOK_SECRET"
```

All fields except `--task` are optional. Short and fast.

### Recover

On session start, if a recent checkpoint exists, the renderer includes it under `## Last Session`. The assistant sees task, status, next action, and notes — and can continue immediately.

### Schema

```yaml
version: 1
written: 2026-05-18T06:49:00-05:00
task: "Rewriting webhook handler to validate Bearer token"
status: "done — handler written and tested"
next: "update .env.example with HERMES_WEBHOOK_SECRET placeholder"
workspace: /workspace/hermes-ntfy
notes: "JWT lib is python-jose; secret lives in .env as HERMES_WEBHOOK_SECRET"
```

---

## Configuration

Perseus reads `~/.perseus/config.yaml` (global) with workspace-local `.perseus/config.yaml` taking precedence.

```yaml
render:
  cache_dir: ~/.perseus/cache
  session_digest_count: 5
  services_timeout_s: 3
  shell: /bin/bash

checkpoints:
  store: ~/.perseus/checkpoints
  ttl_s: 86400        # stale after 24h; still kept, just not injected as live
  max_keep: 30

oracle:
  skill_dir: ~/.hermes/skills
  stale_skill_days: 30
  llm_provider: ollama
  ollama_model: llama3.1
  llm_timeout_s: 30
  ollama_host: http://127.0.0.1:11434

assistant:
  session_search_available: true
  skills_list_available: true
```


---

## 4. Mnēmē (`perseus memory`) — Narrative Project Memory

Mnēmē distills checkpoints and oracle log entries into a per-workspace narrative
markdown file stored at `~/.perseus/memory/<workspace-hash>.md`. Snapshots tell you
where you are now; Mnēmē tells you how you got here.

### Modes

- **Deterministic (default):** rule-based extraction. No LLM required. Sections:
  Project Arc, Key Decisions, Task History, Patterns & Anti-patterns, Recent Activity.
- **LLM-assisted (opt-in):** set `memory.llm_provider` to `ollama` or `openai-compat`.
  The narrative is distilled by a local model via the existing `run_llm` infrastructure.

### CLI

```bash
perseus memory update    # incremental — only new checkpoints + oracle entries
perseus memory compact   # full re-distillation; increments compaction_count
perseus memory show      # print the narrative file
perseus memory status    # high-water marks, age, mode, size
perseus memory query "<question>"  # grep (deterministic) or LLM Q&A
```

### Auto-update

When `memory.auto_update` is true (default), `perseus checkpoint` calls the silent
Mnēmē update path after writing the checkpoint. A failure in Mnēmē prints a warning
and never aborts the checkpoint write.

### Directive

`@memory [focus="decisions|recent|patterns|arc"] [ttl=N]` injects the narrative inline
(or a single named section) when a Perseus source file is rendered. See
`spec/directives.md` for the full reference.



---

## 5. Health (`perseus health`) — Context Maintenance Heuristics

Read-only deterministic maintenance report. Same content backs the `@health`
inline directive.

### CLI

```bash
perseus health [--workspace <path>]
```

### Heuristics

- **Stale Checkpoints** — older than `health.stale_checkpoint_days`
- **Duplicate Checkpoints** — repeated (task, status, next) in the last
  `health.duplicate_checkpoint_window`
- **Context Source Size** — `.perseus/context.md` line count exceeds
  `health.context_line_warning`
- **Old Completed Tasks** — Agora tasks closed more than
  `health.include_completed_tasks_older_than_days` days ago

### Config

```yaml
health:
  stale_checkpoint_days: 7
  duplicate_checkpoint_window: 5
  context_line_warning: 400
  include_completed_tasks_older_than_days: 14
```

Read-only by design — never modifies files.

---

## 6. Agora (`perseus agora`) — Task Coordination Substrate

A flat-file task board. Each `tasks/task-NN-*.md` file owns YAML frontmatter
(`id`, `title`, `status`, `scope`, `depends_on`, `claimed_by`, `opened`, `closed`).

### CLI

```bash
perseus agora list                                # group by status
perseus agora claim <task-id> --agent <name>      # mark in_progress
perseus agora complete <task-id>                  # mark completed
```

### Directive

`@agora [status=...] [scope=...]` renders the same view inline.

---

## 7. Daedalus (`perseus oracle` + `--llm daedalus`)

Two related surfaces:

### Dataset curation

```bash
perseus oracle accept <log-id>          # label as accepted
perseus oracle reject <log-id>          # label as rejected
perseus oracle log [--limit N] [--unlabeled]
perseus oracle export [--output FILE] [--format jsonl|alpaca]
```

- `log-id` accepts `latest`, full timestamp, or timestamp prefix
- `export` writes ONLY entries with `accepted=true`
- Atomic rewrite (`.tmp` + `os.replace`); original log never partially mutated

### Local model routing

```bash
perseus suggest "task" --llm daedalus
```

Routes through Ollama using `llm.daedalus_model` (default `perseus-daedalus`) at
`llm.daedalus_url` (default `http://localhost:11434`). The fine-tuned model is a
user concern; Perseus only handles data export and request routing.



---

## 8. Inbox (`perseus inbox`) — Point-to-Point Messages

Per-workspace message store, parallel to checkpoints.

Storage: `~/.perseus/inbox/<workspace-hash>/<timestamp>-<sender>.yaml`

### CLI

```bash
perseus inbox send "subject" --body "..." [--recipient X] [--from Y] [--workspace .]
perseus inbox list [--unread] [--all]
perseus inbox read <id-prefix|latest>
perseus inbox dismiss <id-prefix>
```

### Directive

`@inbox [unread=true] [limit=N]` — renders pending messages inline. Dismissed
messages are always excluded. `unread=true` filters to unread.

### Config

```yaml
inbox:
  store: ~/.perseus/inbox
  default_recipient: anyone
  default_sender: perseus
```

---

## 9. Templates (`perseus init --template`)

Curated starter `.perseus/context.md` files keyed by AI assistant.

Shipped templates: `generic`, `hermes`, `rovodev`, `claude-code`, `cursor`.

### CLI

```bash
perseus init --template hermes
perseus init --list-templates
```

### Discovery

1. `$PERSEUS_TEMPLATE_DIR` if set
2. `<dir-of-perseus.py>/templates/`
3. Embedded `INIT_CONTEXT_TEMPLATE` (legacy default — used when no `--template`)

---

## 10. Serve (`perseus serve`) — Read-Only HTTP View

Stdlib HTTP server for browsing rendered workspace state.

### CLI

```bash
perseus serve [--port 7991] [--host 127.0.0.1] [--workspace .]
```

### Endpoints

| Path | Returns |
|---|---|
| `/` | HTML index linking to other endpoints |
| `/context` | `text/markdown` — `perseus render .perseus/context.md` output |
| `/narrative` | `text/markdown` — Mnēmē narrative body |
| `/health` | `text/markdown` — health report |
| `/agora` | `text/markdown` — Agora list |
| `/checkpoint/latest` | `text/yaml` — workspace pointer or global latest |
| `/oracle/log?limit=N` | `application/json` — recent oracle log entries |

POST returns 405. No auth — bind to localhost by default.

---

## 11. LSP (`perseus serve --lsp`) — Editor Integration

The same `serve` command can run a Language Server Protocol server over stdio
or a loopback TCP port. The LSP surface is read-only by default and derives
directive names, completions, and hover safety from `DIRECTIVE_REGISTRY`.

### CLI

```bash
perseus serve --lsp --stdio
perseus serve --lsp --tcp 7992
perseus serve --lsp --stdio --allow-lsp-mutations
```

### Supported LSP Features

- `initialize`, `shutdown`, and `exit`
- full-document sync via `didOpen` / `didChange` / `didClose`
- diagnostics for unknown directives, malformed cache TTLs, unclosed blocks,
  and unsubscribed federation aliases
- completion for directive names and registered directive arguments
- hover previews only for directives marked safe for hover
- `workspace/executeCommand` for render/openCheckpoint, with mutation commands
  gated behind `--allow-lsp-mutations`

---

## 12. Doctor (`perseus doctor`) — Readiness Probe

`perseus doctor` reports whether the workspace and global state are ready for a
healthy render/session. It is intentionally read-only and supports JSON output
for CI or agent callers.

### CLI

```bash
perseus doctor [--workspace <path>] [--json]
```

### Checks

- config parseability
- workspace context file presence
- render trust gates
- latest checkpoint age
- Mnēmē narrative health
- federation manifest/subscription health
- oracle log readability
- serve loopback default
- directive registry invariants

---

## 13. Schema Validation (`schema=`, `@validate`, `perseus validate`)

Phase 12 adds a pure-Python schema validation engine. `pyyaml` remains the only
required dependency; the schema subset is documented in `spec/data-model.md`.

### Render-Time Validation

- `@query ... schema="name"` validates YAML stdout before injecting it.
- `@read ... schema="name"` validates a full file, extracted `path=`, `.env`
  `key=`, or fallback.
- `@env ... schema="name"` validates environment values and fallbacks.
- `@validate schema="name" ... @end` renders a block, parses the payload, and
  emits a visible warning instead of invalid context.
- `DirectiveSpec.output_schema` can declare directive-wide rendered-output
  invariants. Per-invocation `schema=` takes precedence.

### CLI

```bash
perseus validate --schema service payload.yaml
perseus validate --schema service --json payload.yaml
cat payload.yaml | perseus validate --schema service -
```

Exit codes are `0` for valid payloads, `1` for validation failures, and `2` for
schema/input read or parse errors.

---

## 14. Directive Graph (`perseus graph`) — Static Dependency Substrate

`perseus graph` scans a source document without rendering it and emits the
directives it contains. It is the Phase 13 read-only substrate for predictive
pre-fetching.

### CLI

```bash
perseus graph .perseus/context.md
perseus graph .perseus/context.md --json
```

The graph skips fenced code blocks and derives directive metadata from
`DIRECTIVE_REGISTRY`: directive kind, safety flags, cacheability, and summary.
It also includes static resource hints for file/path/env-style directives such
as `@read`, `@include`, `@list`, `@tree`, and `@env`.

The command never executes shell-backed directives.

---

## 15. Pattern Prefetch (`perseus prefetch`) — Rule-Based Cache Warming

`perseus prefetch` applies explicit `prefetch.rules` to the static directive
graph and warms the existing directive cache before a render. It does not
render the source document first.

### CLI

```bash
perseus prefetch .perseus/context.md
perseus prefetch .perseus/context.md --json
```

### Config

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
    max_candidates: 5
    candidates:
      - id: decision-memory
        prefetch: '@memory focus=decisions @cache ttl=300'
        patterns: ["decision", "memory"]
```

Rules can use a string trigger such as `@query "git status"` or a mapping with
`directive`, `kind`, `args`, `args_pattern`, `args_contains`,
`resource_kind`, and `resource`. Prefetch directives must be inline,
cacheable directives and must include `@cache ttl=N`, `@cache persist`, or
`@cache session`.

Adaptive prefetch is disabled by default. When enabled, it scores only
predeclared `adaptive.candidates`. The deterministic backend reads recent
accepted oracle entries and the workspace Mnēmē narrative for pattern matches.
The `daedalus` backend routes through existing LLM plumbing and falls back to
deterministic scoring on transport, provider, or parse errors. Daedalus may
rank candidates; it must not generate new directives or context prose.

The command reports every ran, skipped, or failed prefetch. It respects existing
render trust gates such as `render.allow_query_shell`; cache writes are the only
intended side effect.

---

## 16. Cron (`perseus cron`) — Cross-platform Scheduling

Generates a crontab entry for periodic rendering. Works on macOS, Linux, BSD.
Recommended over `perseus launchd` / `perseus systemd` when portability matters.

### CLI

```bash
perseus cron .perseus/context.md -o AGENTS.md --every 5
perseus cron .perseus/context.md -o AGENTS.md --every 5 --install
```

`--every` accepts minutes; `1`, `60`, and `>60` are translated to the
appropriate `* * * * *` / `0 * * * *` / `0 */N * * *` schedule.

`--install` appends the entry to the user's crontab via
`crontab -l` → edit → `crontab -`. Entries are tagged `# perseus-render` for
easy lookup.


---

## 17. Mnēmē Federation (task-19, Phase 8.2)

Cross-workspace narrative aggregation. Lets one workspace subscribe to
another workspace's Mnēmē narrative so curated project memory flows across
related projects on the same filesystem.

**Storage:** `~/.perseus/memory/federation.yaml` (path configurable via
`memory.federation_manifest`). Schema:

```yaml
version: 1
subscriptions:
  - alias: support
    path: /workspace/support-agent
    enabled: true
  - alias: hermes
    path: /workspace/hermes
    enabled: true
    notes: primary mentor agent      # reserved field — preserved on round-trip
```

The list-of-objects shape is intentional (per Q1) so v2 fields like
`share:`, `stale_after:`, `include_sections:` can be added without
migrating existing manifests.

**CLI:**

| Command | Effect |
|---|---|
| `perseus memory federation list` | Table of aliases + status (ok / stale / ⚠ unavailable) + paths |
| `perseus memory federation subscribe <alias> <path>` | Add a subscription. Validates alias against `[a-zA-Z0-9_-]+`; warns (does not refuse) on missing path or duplicate resolved path |
| `perseus memory federation unsubscribe <alias>` | Remove a subscription. Exits 1 if alias not found |
| `perseus memory federation pull` | Re-read all narratives — diagnostic only, never mutates the manifest |

**Directive:** see `spec/directives.md` § `@memory federation`.

**Scope (per Q2):** federation reads `~/.perseus/memory/<hash>.md` only.
Checkpoints, oracle logs, inboxes, task files, health reports, and
rendered full context are **out of scope** for v1.

**Synchronisation (Q4):** the directive re-reads narratives on every render.
There is no cache and no daemon. The CLI is side-effect-free except for
`subscribe` and `unsubscribe`, which mutate the manifest atomically (tmp file
+ `os.replace`).

**Failure modes (Q5):** missing/unreadable narratives produce inline
warning blocks; render never silently skips and never hard-fails.

**Privacy (Q6):** subscriber-side only. No publisher-side ACLs. Any
filesystem-trust assumption the user already makes between two workspaces
is the trust assumption federation inherits.
