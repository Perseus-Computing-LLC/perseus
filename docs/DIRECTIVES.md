# Perseus Directives Reference

> Full directive system for Perseus context documents. All directives are resolved at render time — the assistant sees only verified facts, never directive syntax.

## Directive Protocol Version

Source documents start with `@perseus v0.4` on line 1. The value after `@perseus` is the **directive protocol version** (the syntax revision Perseus parses), not the package version. Existing v0.4/v0.8 context files remain supported for compatibility. You don't need to change this header when upgrading the package.

## Directive Table

| Directive | What it does |
|---|---|
| `@query "shell cmd" [fallback="text"] [schema="name"]` | Runs a shell command, embeds stdout as a fenced block; `fallback=` emits literal text on failure or empty output; `schema=` validates YAML stdout |
| `@read <file> [path="key"] [schema="name"]` | Reads a file; dot-notation path for JSON/YAML/TOML; `key=` for `.env` files; `schema=` validates full or extracted output |
| `@env VAR [fallback="x"] [schema="name"]` | Injects an environment variable; `required=true` emits a visible warning if unset; `schema=` validates the value or fallback |
| `@include <file>` | Embeds a file inline; markdown raw, structured files fenced |
| `@if <cond>` / `@else` / `@endif` | Conditional blocks: `file.exists/missing`, `env.set/unset/eq/neq`, `query("cmd") [not] matches /regex/[i]` |
| `@constraint id="..." severity="..."` | Machine-readable rules rendered as a `\| ID \| Severity \| Rule \|` table |
| `@skills [flag_stale=true]` | Scans the Hermes skills dir, reads frontmatter, flags stale entries |
| `@services` (YAML block or `@services ... @end`) | HTTP health checks (`url:`), Docker container status (`docker:`), or optional shell exit check (`command:`) |
| `@session [count=N] [topic="..."]` | Recent session digest from the sessions directory |
| `@date format="YYYY-MM-DD HH:mm z"` | Live date/time, inline or standalone |
| `@waypoint [ttl=N]` | Latest checkpoint rendered inline; `ttl=` skips it if too old |
| `@prompt...@end` | AI instruction callout — visible to the assistant, attributed to Perseus |
| `@validate schema="name"...@end` | Renders a block, validates the payload, and emits a visible warning instead of invalid context |
| `@agora [status=...] [scope=...]` | Live task board from `tasks/` — markdown table by status/scope |
| `@memory [focus="..."] [ttl=N]` | Mnēmē narrative for the workspace; `focus=` slices a single section (`arc`, `decisions`, `recent`, `patterns`, `history`) |
| `@health` | Maintenance suggestions (stale checkpoints, near-duplicates, large context, old completed tasks) |
| `@list <path> [type] [depth] [path] [columns] [as]` | Directory listing OR structured-file table from `path="dot.key"` of JSON/YAML |
| `@tree <path> [depth] [match] [exclude]` | Fenced directory tree with plain indentation |
| `@agent "command" [timeout=N] [strip=true] [fallback="text"]` | Run a local subprocess, embed stdout inline (gated by `render.allow_agent_shell`) |
| `@inbox [unread=true] [limit=N]` | Render pending point-to-point messages from `perseus inbox send` |
| `@memory federation [alias=name]` | Render digest of subscribed cross-workspace narratives (see `perseus memory federation`) |
| `@memory include_federation=true` | Local narrative + appended `## Federated Context` digest |
| `@drift` | Daedalus drift report — acceptance rate, recommendation Jaccard, confidence proxy (see `perseus oracle drift`) |

## Cache Modifiers

Any directive accepts a `@cache` modifier:

```markdown
@query "git log --oneline -5" @cache session      ← run once per render, reuse after
@services @cache mock="(stubbed in CI)"           ← bypass execution entirely
@skills flag_stale=true @cache persist             ← survives across processes
@skills flag_stale=true @cache ttl=3600            ← cache to disk for 1 hour
```

## Safety Gates

Shell-backed features can be gated in `~/.perseus/config.yaml`:

```yaml
render:
  allow_query_shell: true
  allow_services_command: false
  allow_outside_workspace: false
```

- `allow_query_shell`: enables or disables `@query` command execution
- `allow_services_command`: enables or disables `command:` checks inside `@services`
- `allow_outside_workspace`: controls whether `@read` / `@include` may escape the workspace

---

See also: [CLI Reference](./CLI.md), [Quickstart](./quickstart.md), [Integration Guide](./HERMES_INTEGRATION.md)
