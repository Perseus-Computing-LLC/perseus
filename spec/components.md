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

