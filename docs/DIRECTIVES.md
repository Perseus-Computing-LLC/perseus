# Perseus Directives Reference — v1.0.6

> Full directive system for Perseus context documents. All directives are resolved at render time — the assistant sees only verified facts, never directive syntax.

## Directive Protocol Version

Source documents start with `@perseus v1.0.8` on line 1. The value after `@perseus` is the **directive protocol version** (the syntax revision Perseus parses). Existing v0.4/v0.8 context files remain supported for backward compatibility.

## Directive Table

| Directive | What it does |
|---|---|
| `@query "shell cmd" [fallback="text"] [schema="name"]` | Runs a shell command, embeds stdout as a fenced block; requires `render.allow_query_shell=true` and `PERSEUS_ALLOW_DANGEROUS=1`; `fallback=` emits literal text on failure or empty output; `schema=` validates YAML stdout |
| `@read <file> [path="key"] [schema="name"]` | Reads a file; dot-notation path for JSON/YAML/TOML; `key=` for `.env` files; `schema=` validates full or extracted output |
| `@env VAR [fallback="x"] [schema="name"]` | Injects an environment variable; `required=true` emits a visible warning if unset; `schema=` validates the value or fallback |
| `@include <file> [last=N] [since=14d] [mode=reference]` | Embeds a file inline; markdown raw, structured files fenced. `last=N` keeps only the final N lines; `since=14d`/`2w`/`24h` keeps only dated sections (markdown headings containing an ISO date) within the window — both bound an appended log so the rendered file does not grow unbounded. **Do not `@include` files the host agent already ingests natively** (its own memory files, `~/AGENTS.md` discovery chains): the content lands in model context 2-4×. Use `mode=reference` to emit a one-line pointer instead, or list such files once in `render.host_loaded_paths` so every `@include` of them refuses to inline (#715) |
| `@if <cond>` / `@else` / `@endif` | Conditional blocks: `file.exists/missing`, `env.set/unset/eq/neq`, `query("cmd") [not] matches /regex/[i]` |
| `@constraint id="..." severity="..."` | Machine-readable rules rendered as a `\| ID \| Severity \| Rule \|` table |
| `@skills [flag_stale=true] [category=comma,list]` | Scans the assistant's skills dir, reads frontmatter, flags stale entries; `category=` filters to specific skill categories (e.g. `category=devops,github`). Use this to keep the skills table focused — omit `category=` to list all skills. |
| `@services` (YAML block or `@services ... @end`) | HTTP health checks (`url:`), Docker container status (`docker:`), or optional shell exit check (`command:`); command checks also require `PERSEUS_ALLOW_DANGEROUS=1` |
| `@session [count=N] [topic="..."]` | Recent session digest from the sessions directory |
| `@date format="YYYY-MM-DD HH:mm z"` | Live date/time, inline or standalone |
| `@waypoint [ttl=N]` | Latest checkpoint rendered inline; `ttl=` skips it if too old |
| `@prompt...@end` | AI instruction callout — visible to the assistant, attributed to Perseus |
| `@validate schema="name"...@end` | Renders a block, validates the payload, and emits a visible warning instead of invalid context |
| `@agora [status=...] [scope=...]` | Live task board from `tasks/` — markdown table by status/scope |
| `@memory [focus="..."] [ttl=N]` | Mnēmē narrative for the workspace; `focus=` slices a single section (`arc`, `decisions`, `recent`, `patterns`, `history`) |
| `@memory mode=search query="terms" [k=5] [scope=...] [type=...]` | Mnēmē v2 FTS5 BM25 search over the vault (`~/.perseus/memory/vault/*.md`). Returns ranked results with snippet highlights. Use single-word queries for best recall — multi-word queries are matched as exact FTS5 phrases. |
| `@mimir query="terms" [k=5] [scope=...] [type=...]` | Mimir FTS5 recall — same backend as `@memory mode=search`. Shorthand alias for memory search without the narrative/federation modes. |
| `@capture [limit=N]` | **Write** side of the memory loop (#713): pushes up to N recent session checkpoints for this workspace to Perseus Vault as durable, provenance-tagged memories. Idempotent (keyed per checkpoint — re-renders upsert, never duplicate). Automatic capture at session boundaries (checkpoint write, `memory update`) is opt-in via `perseus_vault.capture.enabled` |
| `@health` | Maintenance suggestions (stale checkpoints, near-duplicates, large context, old completed tasks) |
| `@list <path> [type] [depth] [path] [columns] [as]` | Directory listing OR structured-file table from `path="dot.key"` of JSON/YAML |
| `@tree <path> [depth] [match] [exclude]` | Fenced directory tree with plain indentation |
| `@agent "command" [timeout=N] [strip=true] [fallback="text"]` | Run a local subprocess, embed stdout inline; requires `render.allow_agent_shell=true` and `PERSEUS_ALLOW_DANGEROUS=1` |
| `@inbox [unread=true] [limit=N]` | Render pending point-to-point messages from `perseus inbox send` |
| `@memory federation [alias=name]` | Render digest of subscribed cross-workspace narratives (see `perseus memory federation`) |
| `@memory include_federation=true` | Local narrative + appended `## Federated Context` digest |
| `@mimir  query=\"topic\"` | Recall persistent memories via Mimir (entities, journal, state). Category-filtered, FTS5 keyword search with LIKE fallback. |
| `@drift` | Daedalus drift report — acceptance rate, recommendation Jaccard, confidence proxy (see `perseus oracle drift`) |
| `@tool "\"<path>\"" [args...]` | Run an allowlisted external tool. Unlike `@agent` (ad-hoc), `@tool` requires explicit approval in `tools.allowlist` per path, with argument restrictions, timeouts, and output size caps. Accepts `@cache ttl=N`. |
| `@synthesize question="..." source="file" [label="..."]` | Optional curated synthesis section. Requires `generation.enabled: true` in config. LLM-powered summarization with provenance claims — every assertion traces back to a cited source. |
| `@perseus <url>` | Fetch rendered context from a remote Perseus serve instance. Gated by `foreign_resolver.allowlist` and `render.allow_remote_services_health`. Accepts `@cache ttl=N`. |

## Cache Modifiers

Any directive accepts a `@cache` modifier:

```markdown
@query "git log --oneline -5" @cache session      ← run once per render, reuse after
@services @cache mock="(stubbed in CI)"           ← bypass execution entirely
@skills flag_stale=true @cache persist             ← survives across processes
@skills flag_stale=true @cache ttl=3600            ← cache to disk for 1 hour
@read config.yaml @cache fingerprint               ← auto-invalidates when config.yaml changes
@read archive.json @cache nofingerprint ttl=86400  ← opt-out: pure TTL, ignores file changes
```

**New in v1.0.5+:** `@cache ttl=N` and `@cache persist` now include a **dependency fingerprint** by default. When a directive reads a file (e.g., `@read data.txt`), the cache key includes a hash of that file's content. If the file changes, the cache invalidates automatically — no need to wait for TTL expiry. Use `@cache nofingerprint` to opt out and keep pure TTL-based caching.

| Modifier | Behavior |
|----------|----------|
| `@cache session` | In-memory only, this process. No fingerprint. |
| `@cache ttl=N` | Disk cache, N seconds TTL. **Includes fingerprint** for @read/@include. |
| `@cache persist` | Disk cache with `persist_cache_ttl_s` TTL. **Includes fingerprint.** |
| `@cache fingerprint` | Explicit opt-in (same as ttl/persist default). |
| `@cache nofingerprint [ttl=N]` | Opt out of fingerprinting. Pure TTL-based expiry. |

## Safety Gates

Shell-backed features can be gated in `~/.perseus/config.yaml`:

```yaml
render:
  allow_query_shell: true
  allow_agent_shell: false
  allow_services_command: false
  allow_outside_workspace: false
```

- `allow_query_shell`: enables or disables `@query` command execution
- `allow_agent_shell`: enables or disables `@agent` command execution
- `allow_services_command`: enables or disables `command:` checks inside `@services`
- `allow_outside_workspace`: controls whether `@read` / `@include` may escape the workspace

Even when the config enables ad-hoc shell execution, `@query`, `@agent`, and
`@services command:` require `PERSEUS_ALLOW_DANGEROUS=1` in the process
environment. This second gate is intentional friction for copied configs and
automation profiles.

---

See also: [CLI Reference](./CLI.md), [Quickstart](./quickstart.md), [Integration Guide](./HERMES_INTEGRATION.md)
