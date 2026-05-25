# README Update Briefing — Phase 24 (Hephaestus Extensibility)

> **For the next session.** This document maps every Phase 24 feature to specific
> README sections and provides the copy. Work through top to bottom — each item
> has the exact location, the new text, and what existing text to replace or
> augment. After the README, update `docs/DIRECTIVES.md` (new directives only).

---

## 1. Directives Count (3 locations)

Line 157 and line 241 both say "20 directives." Now there are **22 inline + block directives** (added `@tool`, `@perseus`). The `docs/DIRECTIVES.md` header note should also bump.

**Line 157 — find:**
```
Full directive reference: [`docs/DIRECTIVES.md`](./docs/DIRECTIVES.md) (20 directives: ...
```
**Replace `20` with `22`.**

**Line 241 — find:**
```
- [**Directives Reference**](./docs/DIRECTIVES.md) — All 20 directives with modifiers and examples
```
**Replace `20` with `22`.**

Also add `@tool` and `@perseus` to the parenthetical list on line 157 — append `, `@tool`, `@perseus`` after `@synthesize`.

---

## 2. New Section: Extensibility (after "Architecture", before the quote block)

Insert after line 218 (after the architecture ASCII diagram) and before the Athena quote:

```markdown
---

## Extensibility (Hephaestus)

Perseus is extensible without source patching. Drop Python files into
`~/.perseus/` and the renderer discovers them at startup.

### Plugins

```python
# ~/.perseus/plugins/my_plugin.py
from perseus.registry import DirectiveSpec

def _resolve_service_status(args, cfg, workspace):
    import urllib.request
    try:
        resp = urllib.request.urlopen(args.strip(), timeout=5)
        return f"Status: {resp.status}"
    except Exception as e:
        return f"Error: {e}"

REGISTER = {
    "@service-status": DirectiveSpec(
        name="@service-status",
        resolver=_resolve_service_status,
        args=["url"],
        kind="inline",
        call_sig="acw",
        executes_shell=False,
        safe_for_hover=True,
        cacheable=True,
        summary="Check HTTP status of a URL",
    )
}
```

Use it in context files: `@service-status https://api.example.com/health`

Built-in directives always win collisions. Plugins respect the same permission
profile as built-ins (`executes_shell` gates behind `allow_query_shell`).

### Macros

Reusable directive compositions — no Python needed:

```markdown
@macro deploy %env% %version%
@query "kubectl rollout status deploy/app -n %env%"
@services
  - name: app-%env%
    url: https://%env%.example.com/health
@endmacro

@deploy production 2.3.1
```

Macros expand before directive resolution. Chaining supported up to depth 5 with
cycle detection. Define them in your context file or at `.perseus/macros.md`.

### Render Pipeline Hooks

Shell scripts or Python callbacks fire at render lifecycle points —
`on_render_start`, `on_directive_resolved`, `on_cache_hit`, `on_cache_miss`,
`on_render_complete`, `on_directive_error`:

```yaml
# ~/.perseus/config.yaml
hooks:
  enabled: true
  on_render_complete:
    - cmd: "notify-send 'Context refreshed'"
  on_directive_error:
    - plugin: "my_error_handler"
```

### Pipe Syntax

Chain directives with `|` for lightweight composition (max 3 stages):

```markdown
@query "ls services/" | @cache ttl=300
@read config.yaml path="endpoints" | @validate schema="endpoint-list"
```

Output of each stage becomes the first positional argument to the next.

### Directive Aliases

Config-driven shorthand — single-pass, no recursive expansion:

```yaml
# ~/.perseus/config.yaml
directives:
  aliases:
    "@q": "@query"
    "@svc": "@services"
    "@stale-skills": "@skills flag_stale=true category=all"
```

Pre-defined aliases: `@q→@query`, `@r→@read`, `@svc→@services`, `@mb→@memory`,
`@ag→@agora`, `@wp→@waypoint`, `@sess→@session`. Config aliases override them.

### Custom Schema Validators

Plugin validators for domain-specific schemas:

```markdown
@query "cat endpoints.yaml" schema="plugin:endpoint_list"
```

Validator modules in `~/.perseus/validators/` export a `validate(value, schema_def)`
function returning `(valid: bool, message: str)`.

### Event Webhooks

POST render lifecycle events to an external URL with optional HMAC-SHA256 signing:

```yaml
webhooks:
  enabled: true
  url: "https://hooks.example.com/perseus-events"
  secret: "your-hmac-key"
  events:
    - on_render_start
    - on_render_complete
    - on_directive_error
```

### Structured JSON Output

```bash
perseus render .perseus/context.md --format json
```

Returns `{meta, resolved, directives, integrity}` — consumable by agents, CI
pipelines, and format plugins in `~/.perseus/formats/`.

### Allowlisted External Tools

`@tool` runs external executables with an explicit allowlist, argument
restrictions, timeouts, and output size caps — safer than ad-hoc `@agent`:

```yaml
tools:
  enabled: true
  allowlist:
    - path: "/usr/local/bin/scanner"
      args_allowlist: ["--workspace", "--format"]
      timeout_s: 30
      max_output_bytes: 65536
```

```markdown
@tool "/usr/local/bin/scanner" --workspace . --format json @cache ttl=3600
```

### Remote Context Fetching

`@perseus <url>` fetches rendered context from a remote Perseus serve instance:

```markdown
@persus https://team-server:8420/workspace/infra @cache ttl=300
```

Gated by `foreign_resolver.allowlist` and `render.allow_remote_services_health`.
```

---

## 3. "How It Works" Example — Add Macros + Pipes

After line 155 (`The assistant never sees a directive...`), add a short subsection
showing the new syntax in action:

```markdown
### Extensibility in Practice

Macros reduce repetition. Pipes compose. Aliases keep things short:

```markdown
@macro health-check %service%
@query "curl -s http://%service%:8080/health"
@services
  - name: %service%
    url: http://%service%:8080/health
@endmacro

@q "git log --oneline -5" | @cache ttl=300
@health-check my-api
```

The assistant sees resolved output — never a directive.
```

---

## 4. Architecture Diagram — Add Plugin Layer

The ASCII architecture diagram (lines 196-218) should show the new plugin
discovery layer. Insert before the `Source document` line:

```diff
+  Plugins:  ~/.perseus/plugins/        ─┐  Discovered at render time.
+            ~/.perseus/validators/       │  Macros, hooks, webhooks,
+            ~/.perseus/formats/          ┘  and aliases load from config.
+
   Source document (.perseus/context.md)
```

And add to the sidebar:
```diff
+  Plugins:   ~/.perseus/plugins/
+  Validators:~/.perseus/validators/
+  Formats:   ~/.perseus/formats/
   Waypoints: ~/.perseus/checkpoints/
   Cache:     ~/.perseus/cache/
   Config:    ~/.perseus/config.yaml
```

---

## 5. "Hardened" Section — Plugin Sandboxing

After line 105 (`...these four config knobs live under render:`), append:

```markdown
- **Plugin sandboxing** — Plugin directives with `executes_shell=True` are gated
  behind `allow_query_shell`, same as built-ins. Plugin errors are caught and
  surfaced as inline warnings — a broken plugin never breaks a render.
```

---

## 6. `docs/DIRECTIVES.md` — Add Two New Directives

Add entries for `@tool` and `@perseus`. Follow the existing format in that file.
Minimal entries:

### `@tool`

```
### `@tool "<path>" [args...]`

Run an allowlisted external tool. Unlike `@agent` (ad-hoc commands), `@tool`
requires explicit approval in `tools.allowlist` per path, with optional argument
restrictions, timeouts, and output size caps.

**Modifiers:** `@cache ttl=N`

**Config gate:** `tools.enabled` (default true). Each tool entry supports
`args_allowlist`, `timeout_s`, and `max_output_bytes`.

**Example:**
@tool "/usr/local/bin/scanner" --workspace . --format json @cache ttl=3600
```

### `@perseus`

```
### `@perseus <url>`

Fetch rendered context from a remote Perseus serve instance.

**Modifiers:** `@cache ttl=N`

**Config gate:** `foreign_resolver.enabled` and `render.allow_remote_services_health`.
Optional `foreign_resolver.allowlist` restricts allowed URLs.
Optional `foreign_resolver.hmackey` enables HMAC verification.

**Example:**
@perseus https://team-server:8420/workspace/infra @cache ttl=300
```

---

## 7. `docs/CLI.md` — `--format json`

In the `render` command section, add `json` to the format list and document:

```markdown
- `--format json` — structured output with metadata, directive details, and
  integrity report. Consumable by agents and CI pipelines. Custom format plugins
  in `~/.perseus/formats/<name>.py` are also supported.
```

---

## 8. Check Numbers in Other Files

These files may reference directive counts or feature counts that are now stale:

- `docs/DIRECTIVES.md` — header count
- `docs/CLI.md` — format list, directive count
- `docs/PERFORMANCE.md` — may reference directive count
- `ROADMAP.md` — already live via `@perseus`; Phase 24 tasks should be marked complete
- `AGENTS.md` — contributor guide may reference task count
- `PKG-INFO` or `setup.py` — description string may mention feature count

Search for `20 directives` across the repo and bump to `22`. Also search for
`12,000 lines` (now ~12,750) and `62 features` (now 73+).

---

## Execution Order

1. README: directive counts (3 spots) — quick win
2. README: Extensibility section (new, between Architecture and quote)
3. README: Architecture diagram (add plugin layer)
4. README: "How It Works" example (macros + pipes)
5. README: Hardened section (plugin sandboxing line)
6. `docs/DIRECTIVES.md`: `@tool` and `@perseus` entries
7. `docs/CLI.md`: `--format json`
8. Repo-wide sweep for stale numbers (directives, line count, feature count)
