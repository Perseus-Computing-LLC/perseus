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

### Alpha Scope

For alpha, the oracle is a **structured prompt** over live environment state — not a trained model. Perseus renders the environment snapshot (skills, services, recent waypoints) and passes it plus the task description to the assistant via a well-structured template. The assistant does the ranking. The value is in the *structured input*, not a separate ML component.

Full autonomous scoring (local model, no round-trip) is a future milestone.

---

## 2. Renderer (`perseus render`)

Processes a source `.md` file with a `@perseus` header and produces plain markdown with all directives resolved. The assistant never sees directive syntax — only resolved values.

### Source Format

Any standard `.md` file. Perseus activates when `@perseus` appears on the first line:

```markdown
@perseus v0.1

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
  use_session_history: true

hermes:
  session_search_available: true
  skills_list_available: true
```
