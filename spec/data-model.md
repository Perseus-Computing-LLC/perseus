# Data Model

## Directory Layout

```
~/.perseus/
  config.yaml           ← global config
  bin/
    render-session-context.sh
  cache/
    <hash>.json         ← cached directive outputs (keyed by directive + args)
  checkpoints/
    latest.yaml         ← most recent checkpoint (symlink when supported, file fallback otherwise)
    2026-05-18T0649.yaml
    2026-05-17T2231.yaml
    ...
  memory/
    <workspace-hash>.md ← Mnēmē per-workspace narrative file
  oracle_log.jsonl      ← Pythia recommendation log (append-only)

/workspace/<project>/
  .perseus/
    config.yaml         ← workspace-local config (overrides global)
    context.md          ← workspace-specific live context source (@perseus header)
```

---

## Checkpoint Schema

```yaml
# checkpoints/2026-05-18T0649.yaml
version: 1
written: 2026-05-18T06:49:00-05:00
task: "Rewriting webhook handler to validate Bearer token"
status: "done — handler written and tested"
next: "update .env.example with HERMES_WEBHOOK_SECRET placeholder"
workspace: /workspace/hermes-ntfy
notes: "JWT lib is python-jose; secret lives in .env as HERMES_WEBHOOK_SECRET"
stale_after: 2026-05-19T06:49:00-05:00
```

---

## Cache Schema

```json
{
  "expires": 1747621800,
  "value": "actual output of the @query"
}
```

> **Note:** The current cache implementation is minimal. A future enhancement will expand this to store the full directive metadata (directive name, args, scope, etc.) for more robust cache invalidation.

---

## Config Schema

```yaml
# ~/.perseus/config.yaml

render:
  cache_dir: ~/.perseus/cache
  session_digest_count: 5
  services_timeout_s: 3
  shell: /bin/bash
  allow_query_shell: true
  allow_services_command: false
  allow_outside_workspace: false

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

llm:                                     # task-02 / task-06
  provider: ollama
  model: mistral
  url: http://localhost:11434
  timeout_s: 30
  daedalus_model: perseus-daedalus       # routed by --llm daedalus
  daedalus_url: http://localhost:11434

agora:                                   # task-04
  tasks_dir: tasks                       # default; can be absolute

health:                                  # task-05
  stale_checkpoint_days: 7
  duplicate_checkpoint_window: 5
  context_line_warning: 400
  include_completed_tasks_older_than_days: 14

memory:                                  # task-12 (Mnēmē)
  store: ~/.perseus/memory
  recent_keep: 5
  auto_update: true
  compact_threshold: 20
  llm_provider: null
  llm_model: null
  max_narrative_lines: 300

inbox:                           # task-16 (Phase 8)
  store: ~/.perseus/inbox
  default_recipient: anyone
  default_sender: perseus

assistant:                               # task-01 (legacy `hermes:` migrated here)
  sessions_dir: ~/.hermes/sessions
```

Render block also accepts:

- `persist_cache_ttl_s: 3600` (task-09 — TTL for `@cache persist`)
- `allow_agent_shell: true` (task-15 — gates `@agent` execution; mirrors `allow_query_shell`)

---

## Checkpoint Diff Output

`perseus diff` renders a simple field-level markdown table showing changed keys between an older and newer checkpoint. Unchanged fields are omitted.


---

## Mnēmē Narrative Schema

Per-workspace narrative file at `~/.perseus/memory/<workspace-hash>.md`. Standard
markdown with YAML frontmatter. Human-readable, GitHub-renderable, Perseus-parseable.

### Workspace Hash

```python
sha256(str(workspace_path.resolve()).encode()).hexdigest()[:12]
```

12-char hex; stable for the same resolved path. Shared with `task-07`
(multi-workspace checkpoint namespacing) when that lands.

### File Format

```markdown
---
schema: 1
workspace: /workspace/perseus
workspace_hash: a3f9c12b8e44
updated: 2026-05-18T14:32:00-05:00
checkpoints_processed: 47
oracle_entries_processed: 312
compaction_count: 2
last_compaction_at_update: 2
last_compact_processed: 47
---

# Mnēmē — /workspace/perseus

> Narrative last updated 2026-05-18 14:32 CT.
> Source: 47 checkpoints, 312 oracle entries.
> Run `perseus memory compact` for a full re-distillation.

## Project Arc
...

## Key Decisions
...

## Task History
...

## Patterns & Anti-patterns
...

## Recent Activity
...
```

### Frontmatter Keys

| Key | Type | Description |
|---|---|---|
| `schema` | int | Format version (currently `1`) |
| `workspace` | str | Resolved absolute workspace path |
| `workspace_hash` | str | 12-char sha256 hex of workspace |
| `updated` | ISO ts | Last write timestamp |
| `checkpoints_processed` | int | High-water mark (count of checkpoints) |
| `oracle_entries_processed` | int | High-water mark (count of oracle log entries) |
| `compaction_count` | int | Number of full re-distillations |
| `last_compact_processed` | int | Checkpoints processed at last compact (used for advisory) |

### Atomic Writes

`_save_narrative` writes to a sibling `<file>.tmp` and `os.replace`s it into
place. Partial writes never corrupt the narrative.

### Memory Config Block

```yaml
memory:
  store: /Users/.../.perseus/memory
  recent_keep: 5            # raw checkpoints in Recent Activity
  auto_update: true         # silent update on every checkpoint write
  compact_threshold: 20     # advisory: compact after N incremental updates
  llm_provider: null        # null = deterministic; "ollama" / "openai-compat" = LLM
  llm_model: null           # inherits from llm: block if null
  max_narrative_lines: 300  # advisory cap
```
