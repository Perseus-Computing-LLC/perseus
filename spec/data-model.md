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
    pack.yaml           ← optional Phase 16 context pack manifest
    schemas/
      <name>.yaml       ← validation schemas for @query/@read/@env/@validate
```

---

## Schema Validation DSL

Perseus schema validation is intentionally small and pure Python. `pyyaml` remains
the only required dependency; `pykwalify` and JSON Schema are not required.

Schema references resolve in this order:

1. Absolute path, when an absolute path is provided.
2. `<workspace>/.perseus/schemas/<name>`.
3. `<workspace>/<name>`.
4. The process working directory.

Extensionless references also try `.yaml` and `.yml`.

Supported fields:

```yaml
type: map            # map/object/dict, seq/list/array, str, int, float, bool, any
mapping:             # alias: properties
  name:
    type: str
    required: true
    pattern: "^[a-z0-9-]+$"
  kind:
    type: str
    enum: ["app", "lib"]
  ports:
    type: seq
    items:
      type: int
```

Unsupported schema keys are ignored so future schema versions can grow without
breaking older Perseus versions.

### Directive Output Schemas

`DIRECTIVE_REGISTRY` entries may declare an `output_schema`. Registry-level
schemas validate the rendered directive output automatically during render and
are best for stable, directive-wide invariants such as "this resolver always
returns a non-empty string."

Per-invocation `schema="..."` remains stronger. When a directive call provides
`schema=`, Perseus lets the resolver validate the underlying payload and skips
the registry-level output schema for that invocation. Use per-invocation schemas
for local data contracts; use `output_schema` for global directive contracts.

### Standalone Validation

`perseus validate --schema SCHEMA [payload|-]` validates a payload without
rendering a context file. Payloads are parsed as YAML/JSON, single fenced blocks
are unfenced before parsing, and `.toml` files use Python's TOML parser when
available. Omitting the payload or passing `-` reads stdin.

Human output is concise and returns:

- `0` when the payload matches the schema.
- `1` when schema validation fails.
- `2` when the schema or input cannot be read or parsed.

`--json` emits `{ok, schema, input, errors}` and includes `error` for read/parse
failures.

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

generation:                              # task-39 / Phase 15A
  enabled: false                         # LLM drafting stays opt-in
  model: null                            # optional model override for synthesis
  max_source_bytes: 12000
  max_claims: 6

serve:                                   # task-45 / Phase 17A
  bind: 127.0.0.1                        # serve binds loopback by default

permissions:                             # task-45 / Phase 17A
  # profile: null | strict | balanced | power-user
  # null  → no profile applied; DEFAULT_CONFIG values are used as-is
  # strict → disables every shell, services-command, outside-workspace, and
  #          generation surface. Recommended for shared / unattended hosts.
  # balanced → mirrors current defaults; pin if you don't want future default
  #            changes to surprise you.
  # power-user → enables `@services command:` but keeps generation opt-in;
  #              workspace boundary remains enforced.
  #
  # Layering: DEFAULT_CONFIG → profile → global config.yaml → workspace
  # config.yaml. Explicit keys ALWAYS win over a profile, so a profile is
  # safe to enable without losing existing overrides. Unknown profile names
  # are ignored (defaults stay in force); `perseus trust` surfaces the
  # mismatch so the operator can catch typos.
  profile: null

redaction:                               # task-46 / Phase 17B
  # Redact common secret shapes from output that leaves Perseus's trust
  # boundary (render output, synthesize answer/prompt, serve responses).
  # Source files on disk are NEVER mutated.
  enabled: true
  include_defaults: true
  # Workspace-specific extra rules. Each rule: {name, pattern, replacement?}.
  # Replacement defaults to "[REDACTED:<name>]". Invalid regexes are
  # silently skipped so a typo cannot break rendering.
  patterns:
    # - name: internal_ticket
    #   pattern: "TICKET-\\d+"
    #   replacement: "[ticket]"

audit:                                   # task-47 / Phase 17C
  # Append-only JSONL audit log of sensitive operations and policy denials.
  # Rotated when size exceeds max_log_bytes (single `.1` backup kept).
  # Write failures warn to stderr but never break render (AC #4).
  # Secret values are NEVER written — only counts and rule names (AC #5).
  enabled: true
  log_path: ~/.perseus/audit_log.jsonl
  max_log_bytes: 1048576                 # 1 MiB
# Event types: shell_exec, policy_denied, model_call, redaction, serve_request.
# Inspect with `perseus trust audit [--tail N] [--json]`.

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
  federation_manifest: ~/.perseus/memory/federation.yaml   # task-19 (P8.2)

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

## Context Pack Manifest

Optional workspace manifest at `.perseus/pack.yaml`.

```yaml
version: 1
name: generic-context
profile: generic
trust_profile: balanced
renders:
  - name: default
    source: .perseus/context.md
    output: live-context.md
    assistant: generic
synthesis:
  - name: project-status
    question: What is the current project status and next allowable action?
    sources:
      - ROADMAP.md
      - HANDOFF.md
      - README.md
    enabled: false
```

`renders` is required and must be non-empty. `synthesis` is optional and is
only a source-pack declaration; it does not run generation by itself.

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
workspace: /workspace/example
workspace_hash: a3f9c12b8e44
updated: 2026-05-18T14:32:00-05:00
checkpoints_processed: 47
oracle_entries_processed: 312
compaction_count: 2
last_compaction_at_update: 2
last_compact_processed: 47
---

# Mnēmē — /workspace/example

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
