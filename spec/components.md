# Components

## 1. Renderer (`perseus render`)

The renderer processes a source document (`.pctx` or annotated `.md`) and produces a plain markdown output with all directives resolved. The output is what the assistant actually receives — it never sees directive syntax.

### Rendering pipeline

```
source.pctx
    │
    ▼
[Parse] — tokenize directives vs. passthrough markdown
    │
    ▼
[Resolve] — execute each directive (shell, file read, http, etc.)
    │  ↕ cache layer (session/ttl/persist)
    ▼
[Conditional eval] — @if/@else blocks collapsed to one branch
    │
    ▼
[Assemble] — stitch resolved values into final markdown
    │
    ▼
rendered.md  →  injected into assistant context
```

### Source format

Source files use the `.pctx` extension (Perseus ConTeXt). Any `.md` file with `@perseus` on the first line is also valid.

### Directive categories

See [`directives.md`](directives.md) for full reference. Summary:

| Category | Directives |
|---|---|
| Shell | `@query` |
| Files | `@read`, `@list`, `@tree`, `@include` |
| Environment | `@env` |
| Time | `@date` |
| Session | `@session` — digest of recent Hermes sessions |
| Services | `@services` — health check a list of endpoints/containers |
| Skills | `@skills` — list available Hermes skills, flag stale ones |
| Conditional | `@if`, `@else`, `@endif` |
| Constraints | `@constraint` — rendered as structured table, not prose |
| Caching | `@cache` modifier on any directive |
| Meta | `@prompt` — embedded instruction stripped in non-AI render mode |

---

## 2. Waypoint Store (`perseus checkpoint` / `recover`)

Waypoints are structured resumption snapshots written during a session. They are not logs — they contain only what's needed to resume without re-orientation.

### Write path

```
perseus checkpoint --task "..." --status "..." --next "..." --context "..."
```

Or called automatically via Hermes session hooks.

### Recovery path

On session start, if a waypoint newer than N minutes exists:
1. `perseus recover` emits a waypoint block
2. Renderer includes it in the context document under `## Last Session`
3. Assistant sees: task, status, next action, working paths — and can continue

### Waypoint schema (draft)

```yaml
waypoint:
  written: 2026-05-18T06:49:00-05:00
  task: "Setting up ntfy webhook integration"
  status: "handler written, pending test run"
  next: "run pytest tests/test_webhook.py"
  workspace: /workspace/hermes-ntfy
  branch: feature/webhook-auth
  open_files:
    - src/webhook_handler.py
    - tests/test_webhook.py
  notes: "JWT secret not yet set in .env — will cause test failure"
```

### Staleness

Waypoints older than a configurable TTL (default: 24h) are surfaced as stale context, not live resumption state. They remain in `waypoints/` history for reference.

---

## 3. Tool Oracle (`perseus suggest`)

Given a task description and the current environment state, returns a ranked list of approaches — which Hermes skill to load, which integration to prefer, which command path is fastest.

### Input

```
perseus suggest "download and summarize recent arxiv papers on RAG"
```

### Output (draft)

```
Suggested approaches (ranked):

1. skill:arxiv + skill:youtube-content [HIGH confidence]
   → arxiv skill handles search/fetch; summarization pattern from youtube-content
   → All deps present. No network issues detected.

2. web_search + web_extract [MEDIUM]
   → Generic fallback. Works but no structured metadata.

3. skill:dspy pipeline [LOW — overkill for one-off]
   → Worth it if recurring; setup cost high for single task.
```

### Scoring factors

- Skill availability and freshness (recently patched vs. stale)
- Required service health (is the integration actually live?)
- Task complexity match (don't suggest DSPy for a one-liner)
- Historical effectiveness (from session search patterns — future)
- Token/latency cost estimate

---

## Cross-cutting: Configuration

Perseus reads from `~/.perseus/config.yaml` (global) and `.perseus/config.yaml` (workspace-local, takes precedence).

```yaml
# ~/.perseus/config.yaml
render:
  cache_dir: ~/.perseus/cache
  session_digest_count: 5      # how many recent sessions to summarize
  services_timeout: 3          # seconds per health check

waypoints:
  auto: true                   # write checkpoints automatically
  interval: 300                # seconds between auto-checkpoints
  ttl: 86400                   # seconds before waypoint is considered stale
  store: ~/.perseus/waypoints

oracle:
  skill_dir: ~/.hermes/skills
  hermes_session_search: true  # use session_search for historical scoring
```
