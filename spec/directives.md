# Directives Reference

Directives appear in `.pctx` source files and are resolved at render time. The assistant never sees directive syntax — only the resolved output.

All directives follow the pattern: `@directive [args] [@cache modifier]`

---

## Shell

### `@query`
Run a shell command and embed stdout.

```
@query "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
@query "git log --oneline -5" @cache session
```

Options:
- `@cache session` — run once per session, reuse output on subsequent renders
- `@cache ttl=300` — cache for N seconds
- `fallback="text"` — output to show if command fails or returns empty

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
Health-check a list of endpoints or containers.

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
```

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

## Caching

The `@cache` modifier can be appended to any directive:

| Modifier | Behavior |
|---|---|
| `@cache session` | Resolved once per render session; reused for subsequent renders |
| `@cache ttl=N` | Cached for N seconds |
| `@cache persist` | Written to disk cache; survives across sessions until TTL expires |
| `@cache mock` | Returns a static mock value (for testing/offline use) |
