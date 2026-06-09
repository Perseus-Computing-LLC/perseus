1|# Perseus Directives Reference — v1.0.6
2|
3|> Full directive system for Perseus context documents. All directives are resolved at render time — the assistant sees only verified facts, never directive syntax.
4|
5|## Directive Protocol Version
6|
7|Source documents start with `@perseus v1.0.6` on line 1. The value after `@perseus` is the **directive protocol version** (the syntax revision Perseus parses). Existing v0.4/v0.8 context files remain supported for backward compatibility.
8|
9|## Directive Table
10|
11|| Directive | What it does |
12||---|---|
13|| `@query "shell cmd" [fallback="text"] [schema="name"]` | Runs a shell command, embeds stdout as a fenced block; requires `render.allow_query_shell=true` and `PERSEUS_ALLOW_DANGEROUS=1`; `fallback=` emits literal text on failure or empty output; `schema=` validates YAML stdout |
14|| `@read <file> [path="key"] [schema="name"]` | Reads a file; dot-notation path for JSON/YAML/TOML; `key=` for `.env` files; `schema=` validates full or extracted output |
15|| `@env VAR [fallback="x"] [schema="name"]` | Injects an environment variable; `required=true` emits a visible warning if unset; `schema=` validates the value or fallback |
16|| `@include <file>` | Embeds a file inline; markdown raw, structured files fenced |
17|| `@if <cond>` / `@else` / `@endif` | Conditional blocks: `file.exists/missing`, `env.set/unset/eq/neq`, `query("cmd") [not] matches /regex/[i]` |
18|| `@constraint id="..." severity="..."` | Machine-readable rules rendered as a `\| ID \| Severity \| Rule \|` table |
19|| `@skills [flag_stale=true] [category=comma,list]` | Scans the assistant's skills dir, reads frontmatter, flags stale entries; `category=` filters to specific skill categories (e.g. `category=devops,github`). Use this to keep the skills table focused — omit `category=` to list all skills. |
20|| `@services` (YAML block or `@services ... @end`) | HTTP health checks (`url:`), Docker container status (`docker:`), or optional shell exit check (`command:`); command checks also require `PERSEUS_ALLOW_DANGEROUS=1` |
21|| `@session [count=N] [topic="..."]` | Recent session digest from the sessions directory |
22|| `@date format="YYYY-MM-DD HH:mm z"` | Live date/time, inline or standalone |
23|| `@waypoint [ttl=N]` | Latest checkpoint rendered inline; `ttl=` skips it if too old |
24|| `@prompt...@end` | AI instruction callout — visible to the assistant, attributed to Perseus |
25|| `@validate schema="name"...@end` | Renders a block, validates the payload, and emits a visible warning instead of invalid context |
26|| `@agora [status=...] [scope=...]` | Live task board from `tasks/` — markdown table by status/scope |
27|| `@memory [focus="..."] [ttl=N]` | Mnēmē narrative for the workspace; `focus=` slices a single section (`arc`, `decisions`, `recent`, `patterns`, `history`) |
28|| `@memory mode=search query="terms" [k=5] [scope=...] [type=...]` | Mnēmē v2 FTS5 BM25 search over the vault (`~/.perseus/memory/vault/*.md`). Returns ranked results with snippet highlights. Use single-word queries for best recall — multi-word queries are matched as exact FTS5 phrases. |
29|| `@mneme query="terms" [k=5] [scope=...] [type=...]` | Mnēmē v2 FTS5 recall — same backend as `@memory mode=search`. Shorthand alias for memory search without the narrative/federation modes. |
30|| `@health` | Maintenance suggestions (stale checkpoints, near-duplicates, large context, old completed tasks) |
31|| `@list <path> [type] [depth] [path] [columns] [as]` | Directory listing OR structured-file table from `path="dot.key"` of JSON/YAML |
32|| `@tree <path> [depth] [match] [exclude]` | Fenced directory tree with plain indentation |
33|| `@agent "command" [timeout=N] [strip=true] [fallback="text"]` | Run a local subprocess, embed stdout inline; requires `render.allow_agent_shell=true` and `PERSEUS_ALLOW_DANGEROUS=1` |
34|| `@inbox [unread=true] [limit=N]` | Render pending point-to-point messages from `perseus inbox send` |
35|| `@memory federation [alias=name]` | Render digest of subscribed cross-workspace narratives (see `perseus memory federation`) |
36|| `@memory include_federation=true` | Local narrative + appended `## Federated Context` digest |
37|| `@sibyl [query=\"topic\"] [tiers=entity,state]` | Sibyl Memory structured context marker (opt-in — off by default). Set `sibyl_memory.enabled: true` or `SIBYL_MEMORY_ENABLED=1` to activate. The auto-injected Sibyl block is appended at render time when enabled; `query=` contributes search hints and `tiers=` controls which memory tiers to surface. The directive resolves to empty — the line is stripped from output but its parameters feed the injection. Degrades gracefully when Sibyl SDK is absent. |
38|| `@sibyl_state keys=key1,key2,...` | Surface Sibyl Memory state documents inline. Reads named state keys from the Sibyl database and renders them as label/value pairs for immediate agent orientation. Requires `SIBYL_MEMORY_ENABLED=1`. Degrades gracefully when SDK is absent or key is unset. |
39|| `@drift` | Daedalus drift report — acceptance rate, recommendation Jaccard, confidence proxy (see `perseus oracle drift`) |
40|| `@tool "\"<path>\"" [args...]` | Run an allowlisted external tool. Unlike `@agent` (ad-hoc), `@tool` requires explicit approval in `tools.allowlist` per path, with argument restrictions, timeouts, and output size caps. Accepts `@cache ttl=N`. |
41|| `@synthesize question="..." source="file" [label="..."]` | Optional curated synthesis section. Requires `generation.enabled: true` in config. LLM-powered summarization with provenance claims — every assertion traces back to a cited source. |
42|| `@perseus <url>` | Fetch rendered context from a remote Perseus serve instance. Gated by `foreign_resolver.allowlist` and `render.allow_remote_services_health`. Accepts `@cache ttl=N`. |
43|
44|## Cache Modifiers
45|
46|Any directive accepts a `@cache` modifier:
47|
48|```markdown
49|@query "git log --oneline -5" @cache session      ← run once per render, reuse after
50|@services @cache mock="(stubbed in CI)"           ← bypass execution entirely
51|@skills flag_stale=true @cache persist             ← survives across processes
52|@skills flag_stale=true @cache ttl=3600            ← cache to disk for 1 hour
53|@read config.yaml @cache fingerprint               ← auto-invalidates when config.yaml changes
54|@read archive.json @cache nofingerprint ttl=86400  ← opt-out: pure TTL, ignores file changes
55|```
56|
57|**New in v1.0.5+:** `@cache ttl=N` and `@cache persist` now include a **dependency fingerprint** by default. When a directive reads a file (e.g., `@read data.txt`), the cache key includes a hash of that file's content. If the file changes, the cache invalidates automatically — no need to wait for TTL expiry. Use `@cache nofingerprint` to opt out and keep pure TTL-based caching.
58|
59|| Modifier | Behavior |
60||----------|----------|
61|| `@cache session` | In-memory only, this process. No fingerprint. |
62|| `@cache ttl=N` | Disk cache, N seconds TTL. **Includes fingerprint** for @read/@include. |
63|| `@cache persist` | Disk cache with `persist_cache_ttl_s` TTL. **Includes fingerprint.** |
64|| `@cache fingerprint` | Explicit opt-in (same as ttl/persist default). |
65|| `@cache nofingerprint [ttl=N]` | Opt out of fingerprinting. Pure TTL-based expiry. |
66|
67|## Safety Gates
68|
69|Shell-backed features can be gated in `~/.perseus/config.yaml`:
70|
71|```yaml
72|render:
73|  allow_query_shell: true
74|  allow_agent_shell: false
75|  allow_services_command: false
76|  allow_outside_workspace: false
77|```
78|
79|- `allow_query_shell`: enables or disables `@query` command execution
80|- `allow_agent_shell`: enables or disables `@agent` command execution
81|- `allow_services_command`: enables or disables `command:` checks inside `@services`
82|- `allow_outside_workspace`: controls whether `@read` / `@include` may escape the workspace
83|
84|Even when the config enables ad-hoc shell execution, `@query`, `@agent`, and
85|`@services command:` require `PERSEUS_ALLOW_DANGEROUS=1` in the process
86|environment. This second gate is intentional friction for copied configs and
87|automation profiles.
88|
89|---
90|
91|See also: [CLI Reference](./CLI.md), [Quickstart](./quickstart.md), [Integration Guide](./HERMES_INTEGRATION.md)
92|