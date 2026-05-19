# Directives Reference

Directives appear in standard `.md` files that begin with `@perseus` on the first line. They are resolved at render time. The assistant never sees directive syntax — only the resolved output.

All directives follow the pattern: `@directive [args] [@cache modifier]`

---

## Shell

### `@query`
Run a shell command and embed stdout. Shell execution can be disabled via `render.allow_query_shell`.

```
@query "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
@query "git log --oneline -5" @cache session
```

Options:
- `@cache session` — run once per session, reuse output on subsequent renders
- `@cache ttl=300` — cache for N seconds
- `fallback="text"` — output to show if command fails (non-zero exit),
  returns empty stdout, times out, or raises an exception. Returns the
  literal text as a bare string (no fence). Both `"text"` and `'text'`
  quoting work. Backslash escapes are honored (`\n`, `\t`, etc.). Composes
  with `@cache`: write the fallback BEFORE the cache modifier.

---

## Files

### `@read`
Read a structured file and extract a value.

```
@read ./package.json path="version"
@read .env key="PORT" fallback="3001"
@read config.yaml path="database.host"
```

Supported formats: JSON, YAML, TOML, `.env`, plaintext.

### `@include`
Inline the full contents of a file at the directive site.

```
@include ./CHANGELOG.md
@include ~/.perseus/waypoints/latest.yaml @cache session
```

### `@list`
List directory contents or array data.

```
@list ./packages/ type="dirs" depth=1 as="list"
@list ./package.json path="scripts" columns="key:Command,value:Runs" as="table"
```

### `@tree`
Directory tree, optionally filtered.

```
@tree ./src/ depth=3 match="*.py"
```

---

## Environment

### `@env`
Resolve an environment variable.

```
@env NODE_ENV fallback="development"
@env DATABASE_URL required=true
```

If `required=true` and the var is unset, the rendered output includes a `⚠ MISSING` warning rather than silently omitting it.

---

## Time

### `@date`
Current date/time.

```
@date format="YYYY-MM-DD HH:mm z"
@date format="relative"   → "3 minutes ago" style
```

---

## Session & Assistant State

### `@session`
Digest of recent Hermes sessions — titles, timestamps, brief summaries.

```
@session count=5
@session count=3 topic="ntfy OR webhook"
```

Output is a compact markdown list of recent sessions the assistant can use to understand active threads.

### `@skills`
List available Hermes skills, with optional staleness flags.

```
@skills
@skills category="github"
@skills flag_stale=true   → marks skills not updated in >30 days
```

### `@waypoint`
Include the most recent checkpoint (or a specific one).

```
@waypoint                  → latest
@waypoint ttl=3600         → only if written within the last hour
```

---

## Services

### `@services`
Health-check a list of endpoints or containers. Supports either a YAML block immediately following `@services` or an explicit `@services ... @end` block. `command:` checks are gated by `render.allow_services_command`.

```
@services
  - name: Hermes WebUI
    url: http://localhost:7779/health
  - name: ntfy
    url: http://localhost:8080/v1/health
  - name: Portainer
    url: https://localhost:9443/api/status
  - name: mongo-dev
    docker: mongo-dev
```

Output: structured table with name, status (✅/❌), and latency.

---

## Conditional

### `@if` / `@else` / `@endif`

Malformed or unknown conditions render a visible warning block rather than silently evaluating false.

```
@if env.DATABASE_URL != ""
  Database is configured.
@else
  ⚠ DATABASE_URL is not set — app will not start.
@endif

@if file.exists ".env"
  @include .env
@else
  No .env found.
@endif

@if query("docker ps | grep mongo-test") matches /mongo-test/
  Mongo test container is running on port 27018.
@else
  Port 27018 is clear.
@endif

@if query("git status --porcelain") not matches /./
  Working tree is clean.
@endif

@if query("uname -a") matches /Darwin/i
  Running on macOS.
@endif
```

**Supported condition forms:**

| Form | Description |
|---|---|
| `file.exists "path"` | True if the file/dir exists |
| `file.missing "path"` | True if the file/dir does NOT exist |
| `env.set VAR` | True if `$VAR` is set and non-empty |
| `env.unset VAR` | True if `$VAR` is unset or empty |
| `env.eq VAR "value"` | True if `$VAR` equals the literal value |
| `env.neq VAR "value"` | True if `$VAR` does not equal the literal value |
| `query("cmd") matches /regex/[i]` | Run the command and test stdout against the regex; `i` = case-insensitive |
| `query("cmd") not matches /regex/[i]` | Negated form |

`@if query(...)` honors `render.allow_query_shell` — when false, the
condition evaluates to False and a stderr warning is printed (parsing does
not raise). Invalid regex raises a `ConditionParseError` so the renderer
surfaces a visible warning instead of silently failing.

---

## AI-Native

### `@constraint`
A machine-readable rule rendered as a structured table row. Clearer signal to the assistant than buried prose.

```
@constraint id="no-direct-db" severity="critical"
  NEVER import the database driver directly. All DB access goes through src/db/index.ts.
@end

@constraint id="api-prefix" severity="critical"
  Every route MUST use /api/v1/ prefix.
@end
```

Rendered as:

| ID | Severity | Rule |
|---|---|---|
| no-direct-db | CRITICAL | NEVER import the database driver directly... |
| api-prefix | CRITICAL | Every route MUST use /api/v1/ prefix. |

### `@prompt`
An instruction embedded in the source that is included in AI render mode and stripped in human render mode.

```
@prompt
  This document was rendered live. Do not look up package.json, .env, or
  docker ps — all current values are already below.
@end
```

---

## Project Memory

### `@memory`

Inject the Mnēmē narrative for the current workspace inline. Reads the
narrative file at `~/.perseus/memory/<workspace-hash>.md`. If no narrative
exists yet, renders a warning advising the user to run `perseus memory update`.
If the narrative is stale (age > `checkpoints.ttl_s`), renders a staleness
warning.

```
@memory
@memory focus="decisions"
@memory focus="recent"
@memory ttl=3600
@memory @cache ttl=3600
```

**Arguments:**

| Arg | Values | Description |
|---|---|---|
| `focus` | `"arc"`, `"decisions"`, `"history"` (alias `"tasks"`), `"patterns"`, `"recent"` | Emit only the named `##` section from the narrative body |
| `ttl` | integer (seconds) | Short-form cache — equivalent to `@cache ttl=N` |

See `spec/components.md` § 4 (Mnēmē) for the CLI surface that produces the
narrative file.

### `@memory federation` (task-19, Phase 8.2)

Render a digest of subscribed cross-workspace narratives. Subscriptions are
defined in `~/.perseus/memory/federation.yaml` and managed via the
`perseus memory federation` CLI.

```
@memory federation                  ← all enabled subscriptions
@memory federation alias=hermes     ← single subscription (even if disabled)
@memory include_federation=true     ← local narrative + appended digest
```

**Hard guarantee:** plain `@memory` is local-only forever — federated content
never silently appears in plain `@memory` output even when subscriptions are
configured. Use one of the two forms above to opt in (Q3 decision).

**Failure semantics (Q5):**

| Condition | Behavior |
|---|---|
| Workspace path missing | Inline warning block per alias, render continues |
| Narrative file missing | Inline warning block per alias, render continues |
| Narrative YAML malformed | Inline warning block per alias, render continues |
| Narrative stale (> `checkpoints.ttl_s`) | Body included WITH stale warning |
| Manifest file malformed | Empty digest + stderr warning, no exception |

**Privacy posture (Q6):** subscriber-side only. If workspace A can read
workspace B's narrative file, Perseus cannot meaningfully enforce
publisher-side access control on a shared filesystem. Documented; not
defended.

---

## Maintenance

### `@health`

Inline maintenance suggestions for the current workspace. Same content as
`perseus health` writes to stdout. Read-only — runs deterministic heuristics
and emits a markdown list.

```
@health
```

Heuristics emitted (when applicable):

- **Stale Checkpoints** — checkpoints older than `health.stale_checkpoint_days`
- **Duplicate Checkpoints** — repeated (task, status, next) tuples in the last
  `health.duplicate_checkpoint_window` checkpoints
- **Context Source Size** — `.perseus/context.md` exceeds `health.context_line_warning`
- **Old Completed Tasks** — Agora tasks closed more than
  `health.include_completed_tasks_older_than_days` days ago

When nothing is flagged, emits `_All clear — no maintenance suggestions._`

---

## Tasks (Agora)

### `@agora`

Live task board from `tasks/` directory. Renders a markdown table grouped by
`status` and optionally filtered by `scope`.

```
@agora
@agora status=open
@agora status=in_progress scope=small,medium
```

**Arguments:**

| Arg | Values | Description |
|---|---|---|
| `status` | `open`, `in_progress`, `completed`, `all` (default) | Filter by frontmatter status |
| `scope` | comma list (e.g. `small,medium`) | Filter by frontmatter scope |

Task files live under `cfg.agora.tasks_dir` (default: `tasks/`) and must have
YAML frontmatter with `id`, `title`, `status`, `scope`, optional `claimed_by`,
`opened`, `closed`, `depends_on`.

See `perseus agora list / claim / complete` for managing tasks from the CLI.

---

## Caching

The `@cache` modifier can be appended to any directive:

| Modifier | Behavior |
|---|---|
| `@cache session` | Resolved once per render session; reused for subsequent renders |
| `@cache ttl=N` | Cached for N seconds |
| `@cache persist` | Written to disk cache; survives across sessions until TTL expires |
| `@cache mock` | Returns a static mock value (for testing/offline use) |


---

## Subprocess (Phase 8)

### `@agent`

Run a local subprocess and embed its stdout inline.

```
@agent "echo hello"
@agent "my-script.sh" timeout=30 fallback="(unavailable)"
@agent "git diff --stat HEAD~1" strip=true @cache ttl=300
```

| Arg | Default | Description |
|---|---|---|
| `timeout` | 10 | Seconds before subprocess is killed |
| `strip` | `true` | Strip leading/trailing whitespace from stdout |
| `fallback` | (none) | Substitute text on failure/timeout instead of warning |

Differs from `@query` in three ways:
1. Output is substituted INLINE (no fenced code block by default)
2. Failure with `fallback=` silently substitutes the fallback text
3. Gated by `render.allow_agent_shell` (default `true`)

Composes with `@cache session|ttl=N|persist|mock`.

---

## Messaging (Phase 8)

### `@inbox`

Render pending point-to-point messages from `perseus inbox send`.

```
@inbox
@inbox unread=true
@inbox limit=5
```

Dismissed messages are always excluded. `unread=true` filters to messages that
have not been opened via `perseus inbox read`.

Empty inbox renders `_No new messages._`

See `spec/components.md` § 8 (Inbox) for the CLI surface.
