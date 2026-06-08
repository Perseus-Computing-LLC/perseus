# Perseus Phase 24 — Extensibility Handoff

> **Session:** 2026-05-24  
> **Status:** Spec complete. Shipped in v1.0.4–v1.0.6.  
> **Workspace:** /workspace/perseus  
> **Next session:** Pick up task-65 (plugin directive system) — the foundation task.

---

## Overview

Phase 24 makes Perseus extensible without source patching. The core insight: the
`DIRECTIVE_REGISTRY` and `_bind_registry()` already exist — extending them to
discover plugins is mechanical. Everything else (macros, hooks, validators,
formats, webhooks, tools, aliases, pipes, foreign resolvers) builds on that
discovery mechanism.

## Etymology

**Hephaestus** — the divine smith who forged the automata. Bronze servants that
operated on their own. Talos, the bronze guardian of Crete. The golden maiden
assistants. Extensibility is Hephaestus's domain: giving Perseus the power to
forge its own tools.

---

## Task Details

### task-65: Plugin Directive System (Foundation)

**Goal:** Users can drop Python files in `~/.perseus/plugins/` and Perseus
discovers their directives at render time.

**Files to touch:**
- `src/perseus/registry.py` — `_bind_registry()` gains a plugin scan step
- `src/perseus/config.py` — add `plugins` config block to `DEFAULT_CONFIG`
- `tests/test_plugin.py` — new test file (probably 8-10 tests)

**Implementation plan:**

1. **Config block** (`DEFAULT_CONFIG`):
   ```python
   "plugins": {
       "enabled": True,
       "dir": str(PERSEUS_HOME / "plugins"),
   }
   ```

2. **Plugin module contract.** A plugin is a `.py` file in the plugins dir that
   exports a `REGISTER` dict:
   ```python
   # ~/.perseus/plugins/my_plugin.py
   from perseus.registry import DirectiveSpec

   def _resolve_service_count(args, cfg, workspace):
       # args: "http://localhost:3001" or similar
       import urllib.request
       try:
           resp = urllib.request.urlopen(args.strip(), timeout=5)
           return f"Status: {resp.status}"
       except Exception as e:
           return f"Error: {e}"

   REGISTER = {
       "@service-status": DirectiveSpec(
           name="@service-status",
           resolver=_resolve_service_count,
           args=["url"],
           kind="inline",
           call_sig="acw",  # (args, cfg, workspace) — standard inline
           executes_shell=False,
           reads_files=False,
           safe_for_hover=True,
           cacheable=True,
           summary="Check HTTP status of a URL"
       )
   }
   ```

3. **Plugin discovery in `_bind_registry()`:**
   ```python
   def _discover_plugins(cfg: dict) -> list[DirectiveSpec]:
       """Scan plugins dir, import Python modules, collect REGISTER entries."""
       if not cfg.get("plugins", {}).get("enabled", True):
           return []
       plugins_dir = Path(cfg["plugins"].get("dir",
                          str(PERSEUS_HOME / "plugins")))
       if not plugins_dir.is_dir():
           return []
       specs = []
       for py_file in sorted(plugins_dir.glob("*.py")):
           try:
               spec = importlib.util.spec_from_file_location(
                   f"perseus_plugin_{py_file.stem}", py_file
               )
               mod = importlib.util.module_from_spec(spec)
               spec.loader.exec_module(mod)
               if hasattr(mod, "REGISTER") and isinstance(mod.REGISTER, dict):
                   for name, ds in mod.REGISTER.items():
                       if isinstance(ds, DirectiveSpec):
                           specs.append(ds)
           except Exception:
               # Plugin error is a warning, never fatal
               import sys
               print(f"Perseus plugin error ({py_file.name}): {e}",
                     file=sys.stderr)
       return specs
   ```

4. **Merge in `_bind_registry()`.** After the hardcoded `_entries` list, call
   `_discover_plugins(cfg)` and extend the list before building the inline regex.

5. **Trust boundaries.** Plugin directives:
   - Inherit the workspace permission profile (strict/balanced/power-user)
   - Cannot override safety gates — `executes_shell` only works if config allows
   - Run in-process (same Python, same trust domain)
   - Plugin `executes_shell=True` gates behind `render.allow_query_shell` same
     as built-ins

6. **Name collision resolution.** Built-in directives always win. If a plugin
   registers `@query`, it's silently ignored (warning to stderr). First plugin
   to register a name wins if two plugins collide.

**Edge cases / pitfalls:**
- macOS hardened runtime may block `exec_module` — test early
- Plugin files that import heavy deps slow down every render — document this
- Circular imports with Perseus internals — plugins should only import from
  `perseus.registry` (for `DirectiveSpec`)
- Plugin dir doesn't exist on fresh install — gracefully skip (no error)
- A plugin that does `import torch` at module level makes `perseus render`
  pay the cost every time — recommend lazy imports in plugin resolvers

**Tests needed:**
- Plugin with valid `REGISTER` → directive resolves correctly
- Plugin with invalid `REGISTER` → warning, render continues
- Plugin dir doesn't exist → no error
- `plugins.enabled: false` → no plugins loaded
- Plugin name collision with built-in → built-in wins
- Plugin with `executes_shell=True` and shell disabled → gated
- Two plugins with same name → first wins
- Plugin resolver that throws → error output, render continues

---

### task-66: Directive Macros

**Goal:** `@macro ... @endmacro` blocks define reusable directive compositions.
No Python needed.

**Files to touch:**
- `src/perseus/renderer.py` — pre-processing pass before `_render_lines()`
- `src/perseus/config.py` — add `macros_file` config key
- `src/perseus/directives/` — new `macros.py` module
- `tests/test_macros.py`

**Implementation plan:**

1. **Config:**
   ```python
   "render": {
       # ... existing ...
       "macros_file": ".perseus/macros.md",  # relative to workspace
   }
   ```

2. **Macro definition syntax:**
   ```markdown
   @macro project-health
   @health
   @agora status=open
   @drift
   @endmacro

   @macro service-check %service_name%
   @query "curl -s http://%service_name%:8080/health"
   @endmacro
   ```
   - `@macro <name>` starts a definition
   - `%param_name%` tokens are positional parameters (no named params in v1)
   - `@endmacro` closes
   - Macro definitions can reference other macros (depth-limited to 5)

3. **Macro loading.** `_load_macros(workspace, cfg)` scans:
   - The source document itself (macros defined in the context file)
   - `.perseus/macros.md` in the workspace
   Workspace macros are loaded first; source-document macros can shadow them.

4. **Pre-processing pass.** Before `_render_lines()`, a new `_expand_macros(lines, macros)`
   function:
   - Walks every line
   - When a line matches a macro name (e.g., `@project-health`), replaces it
     with the macro's body lines
   - When a line matches a parameterized macro (e.g.,
     `@service-check my-api`), substitutes `%service_name%` → `my-api` in
     the body
   - Recursive expansion up to depth 5 — cycle detection (macro A calls B
     calls A) is an error
   - Macros can appear at any nesting level (inside `@if` blocks, etc.)

5. **No inline macros.** `@macro` and `@endmacro` must appear on their own
   lines — not inside `@if` blocks, `@services` blocks, etc. Definitions at the
   top of the file (or in the macros file) is the convention.

**Edge cases / pitfalls:**
- Macro expansion happens BEFORE fenced code block detection — a macro
  containing `` ``` `` will properly toggle fence state
- Recursive macro detection — track seen names, error on cycle
- A macro that references an undefined macro → warning, expand best-effort
- Empty macro (no body lines) → expands to nothing
- Macro with `%param%` but invoked without a value → token left as literal
  `%param%` (warning)
- Macros file doesn't exist → no error, just no workspace macros

**Tests needed:**
- Simple macro expansion (no params)
- Parameterized macro substitution
- Macro in macros file loaded correctly
- Macro shadowing (source doc overrides macros file)
- Recursive macro cycle detection
- Macro inside `@if` block (macros expand before if evaluation)
- Macro referencing undefined macro → warning
- Empty macro → no output

---

### task-67: Render Pipeline Hooks

**Goal:** Shell scripts or Python callbacks fire at render lifecycle points.

**Files to touch:**
- `src/perseus/renderer.py` — hook invocation points in `_render_lines()`
- `src/perseus/config.py` — `hooks` config block
- `tests/test_hooks.py`

**Lifecycle events:**

| Event | Payload | Fires |
|---|---|---|
| `on_render_start` | `{source, workspace, timestamp}` | Before first line processed |
| `on_directive_resolved` | `{directive, args, result_len, cached, duration_ms}` | After each directive |
| `on_cache_hit` | `{directive, cache_key}` | Cache hit (before resolver) |
| `on_cache_miss` | `{directive, cache_key}` | Cache miss (before resolver) |
| `on_render_complete` | `{source, workspace, line_count, duration_ms, errors}` | After all output |
| `on_directive_error` | `{directive, args, error, traceback}` | Any resolver throws |

**Config:**
```yaml
hooks:
  enabled: true
  on_render_start:
    - cmd: "echo 'render started' >> /tmp/perseus-render.log"
    - plugin: "my_hooks.on_start"
  on_directive_error:
    - cmd: "notify-send 'Perseus error: {directive}'"
```

1. **Shell hooks:** `cmd:` entries get formatted with Python `.format(**payload)`
   — the payload dict keys are available as `{key}`. Shell hook failure is a
   warning. Timeout: 10 seconds per hook.

2. **Python hooks:** `plugin:` entries load from `~/.perseus/plugins/<name>.py`
   (same discovery as task-65). The module must export a function matching the
   event name, e.g. `on_directive_resolved(payload)`. Function return value is
   ignored.

3. **Invocation.** Hooks are called synchronously in config order. They are
   non-blocking by design — exceptions are caught, logged to stderr, and the
   render continues.

4. **Performance.** Hooks add overhead. `on_directive_resolved` fires for every
   directive — a slow hook there is painful. Document this trade-off.

**Tests:**
- Shell hook fires and receives formatted payload
- Python hook module loaded and called
- Hook failure doesn't break render
- Hook timeout (shell hook that hangs)
- `hooks.enabled: false` → no hooks fire
- Each lifecycle event fires at the right time
- `on_directive_error` fires with error details

---

### task-68: Output Format Adapters

**Goal:** `perseus render --format json` returns structured directive-by-directive output. Custom formats via plugins.

**Files to touch:**
- `src/perseus/cli.py` — `--format` flag
- `src/perseus/renderer.py` — metadata collection during render
- `src/perseus/formats/` — `json_format.py`, adapter interface
- `tests/test_formats.py`

**Built-in formats:**
- `markdown` (default) — current behavior
- `html` — existing `--format html` path
- `json` — structured output (new)

**JSON output schema:**
```json
{
  "meta": {
    "source": ".perseus/context.md",
    "workspace": "/home/user/project",
    "timestamp": "2026-05-24T...",
    "duration_ms": 234,
    "cache_hits": 5,
    "cache_misses": 3,
    "errors": 0
  },
  "resolved": "Full markdown string...",
  "directives": [
    {
      "name": "@query",
      "args": "git log --oneline -5",
      "output": "abc1234 ...",
      "cached": false,
      "duration_ms": 45,
      "error": null
    }
  ],
  "integrity": {
    "drift_detected": false,
    "drift_files": []
  }
}
```

**Implementation:**

1. `_render_lines()` gains a `_metadata` accumulator (list of dicts, one per
   directive execution). Each directive resolution appends: `{name, args,
   output_len, cached, duration_ms, error}`.

2. `render_source()` returns a `RenderResult` namedtuple instead of a raw
   string: `RenderResult(text=str, directives=list[dict], meta=dict)`.

   **Backward compatibility:** `render_source()` currently returns `str`. All
   callers (CLI, serve, MCP, tests) expect `str`. We cannot break them. Two
   approaches:
   - A) Add a new `render_source_with_meta()` that returns `RenderResult`;
     `render_source()` wraps it and returns just the text. Callers that need
     metadata call the new function.
   - B) Keep `render_source()` returning `str` but add an optional
     `_metadata_out` parameter (a mutable list passed by reference).

   **Recommendation:** Option A — cleaner API, no mutation, explicit opt-in.

3. **Format adapter interface.** Plugins in `~/.perseus/formats/<name>.py`:
   ```python
   def render(result: RenderResult) -> str:
       # Return formatted output
       return json.dumps(result.directives, indent=2)
   ```

4. **`--format` flag.** `perseus render --format json|html|<name>`:
   - `json` and `html` are built-in
   - `<name>` loads from `~/.perseus/formats/<name>.py`
   - Unknown format → error message listing available formats

**Tests:**
- `--format json` outputs valid JSON with expected structure
- Format adapter plugin loaded and renders correctly
- Unknown format → error
- `render_source()` return type unchanged (backward compat)
- Metadata accumulator tracks cache hits/misses correctly
- Empty source doc produces valid JSON with zero directives

---

### task-69: Foreign Resolver Protocol

**Goal:** `@perseus <url>` fetches rendered context from a remote Perseus serve
instance. MCP tools expose directives over MCP transport.

**Files to touch:**
- `src/perseus/directives/` — new `perseus.py` (remote directive resolver)
- `src/perseus/mcp.py` — extend to expose full directive surface
- `src/perseus/renderer.py` — wire new `@perseus` directive
- `src/perseus/config.py` — `foreign_resolver` config block
- `tests/test_foreign_resolver.py`

**Part 1: Remote `@perseus` directive**

```markdown
@perseus https://team-server:8420/workspace/infra @cache ttl=300
```

1. **Protocol.** The remote `perseus serve` instance already has `GET /workspace/<name>/context`
   (Phase 8). The `@perseus` directive calls this endpoint, gets resolved
   markdown back, and embeds it inline.

2. **Auth.** Config block:
   ```yaml
   foreign_resolver:
     enabled: true
     allowlist:  # if empty, all URLs allowed (gated by allow_remote_services_health)
       - "https://team-server:8420"
     hmackey: ""  # shared secret for HMAC verification
     timeout_s: 10
   ```

   If `allow_remote_services_health` is disabled, `@perseus` is gated.

3. **Caching.** The `@cache ttl=N` modifier works natively — the remote fetch
   result gets cached to disk. Without `@cache`, it fetches every render.

4. **Error handling.** Connection refused / timeout → `> ⚠ @perseus: could not reach <url>`.
   Non-200 → `> ⚠ @perseus: <url> returned <code>`. HMAC mismatch →
   `> ⚠ @perseus: signature verification failed for <url>`.

**Part 2: MCP tool exposure**

The existing MCP server at `src/perseus/mcp.py` currently exposes
`get_context` and `get_health` as read-only operations. Extend it:

1. **Tool registration.** For each entry in `DIRECTIVE_REGISTRY` where
   `kind="inline"`, generate an MCP tool definition:
   ```json
   {
     "name": "perseus_query",
     "description": "Run a shell command and embed stdout",
     "inputSchema": {
       "type": "object",
       "properties": {
         "args": {"type": "string", "description": "Shell command to run"},
         "fallback": {"type": "string", "description": "Fallback text"}
       }
     }
   }
   ```

2. **Tool execution.** When an MCP client calls `perseus_query`, the server:
   - Validates trust gates (`allow_query_shell`)
   - Runs the resolver via `_call_resolver()`
   - Returns the result as tool output

3. **Trust model.** MCP tools respect the same permission profile as
   `perseus render`. The `perseus serve` auth token gates MCP access.

4. **Tool listing.** `perseus serve --mcp-tools` lists available tools.

**Tests:**
- Remote `@perseus` fetches context from a running serve instance
- Remote fetch with bad URL → graceful error
- HMAC verification (good and bad key)
- Caching of remote results with `@cache`
- MCP tool listing includes all directive tools
- MCP tool execution respects trust gates (shell disabled → tool returns error)
- `foreign_resolver.enabled: false` → `@perseus` directive is no-op

---

### task-70: Custom Schema Validators

**Goal:** Plugin validators for domain-specific schemas, referenced via
`schema="plugin:my-validator"`.

**Files to touch:**
- `src/perseus/directives/query.py` / `read.py` / `env.py` — schema resolution
- `src/perseus/validate.py` (new or extend) — plugin validator loading
- `src/perseus/config.py` — `validators_dir` config key
- `tests/test_plugin_validators.py`

**Implementation:**

1. **Validator contract.** A validator module in `~/.perseus/validators/`:
   ```python
   # ~/.perseus/validators/endpoint_list.py
   def validate(value, schema_def):
       """
       value: the string to validate (post-render output)
       schema_def: the schema definition from the schema file

       Returns: (valid: bool, message: str)
       """
       import yaml
       try:
           data = yaml.safe_load(value)
           if not isinstance(data, list):
               return False, "Expected a YAML list"
           for item in data:
               if "port" not in item:
                   return False, f"Item missing 'port': {item}"
           return True, "OK"
       except Exception as e:
           return False, str(e)
   ```

2. **Schema resolution.** In `@query schema="plugin:endpoint_list"`, the
   `plugin:` prefix triggers custom validator loading. The name after `plugin:`
   maps to `~/.perseus/validators/<name>.py`.

3. **Fallback.** If the plugin validator isn't found, fall through to the
   built-in validator (which may also fail — the combined result is the
   stricter of the two).

4. **Discovery.** Same `importlib` pattern as task-65. Validators are loaded
   on-demand (when a `schema=` modifier references them), not at startup.

5. **Config:**
   ```yaml
   validate:
     validators_dir: "~/.perseus/validators"
   ```

**Tests:**
- `schema="plugin:my-validator"` loads and runs custom validator
- Custom validator returns valid result → output passes
- Custom validator returns invalid → warning emitted
- Plugin validator not found → fallback to built-in
- Plugin validator throws exception → caught, reported as validation error
- Works with `@validate` block directive

---

### task-71: Pipe Syntax

**Goal:** Chain directives with `|` for lightweight composition.

**Files to touch:**
- `src/perseus/renderer.py` — pipe parsing in inline directive path
- `tests/test_pipes.py`

**Syntax:**
```markdown
@query "ls services/" | @cache ttl=300
@read config.yaml path="endpoints" | @validate schema="endpoint-list"
```

**Implementation:**

1. **Parsing.** In the inline directive match handler (around line 531 in
   renderer.py), after matching `INLINE_DIRECTIVE_RE`, check for `|` in the
   remaining line text. Split on `|` into stages.

2. **Execution.** Left-to-right:
   - Stage 1: resolve directive 1 normally
   - Stage 2: inject stage 1's output as the first positional argument to
     directive 2 (prepended to args string)
   - Stage N: inject stage N-1's output as first positional arg to directive N

3. **Limitations:**
   - Max 3 stages in a pipe chain (prevent unreadable lines)
   - Each stage must be an inline directive (no block directives in pipes)
   - `@cache` modifier on the last stage applies to the whole pipe result
   - Pipe stages cannot contain `@cache` modifiers individually (too ambiguous)

4. **Result caching.** If `@cache ttl=N` appears after the pipe, the final
   result is cached. Intermediate results are not cached (simplicity).

**Tests:**
- Two-stage pipe: `@query ... | @cache ttl=60`
- Three-stage pipe
- Pipe with `@validate` as second stage
- Pipe exceeding max stages → error
- Pipe inside `@if` block
- Block directive in pipe → error
- `@cache` on intermediate stage → error

---

### task-72: Event Webhooks

**Goal:** POST render lifecycle events to an external URL.

**Files to touch:**
- `src/perseus/renderer.py` — webhook fire points (reuse hook payloads from task-67)
- `src/perseus/config.py` — `webhooks` config block
- `tests/test_webhooks.py`

**Config:**
```yaml
webhooks:
  enabled: false
  url: "https://hooks.example.com/perseus-events"
  secret: "hmac-secret-key"
  events:
    - on_render_start
    - on_render_complete
    - on_directive_error
  timeout_s: 5
```

**Implementation:**

1. **Payload.** JSON POST with:
   ```json
   {
     "event": "on_render_complete",
     "timestamp": "2026-05-24T20:00:00Z",
     "workspace": "sha256hash",
     "data": { ... event-specific ... }
   }
   ```

2. **Signing.** If `secret` is set, add `X-Perseus-Signature: sha256=<hmac-hex>` header.
   HMAC-SHA256 of the JSON body with the secret as key.

3. **Fire-and-forget.** Webhook POSTs are best-effort. HTTP errors and timeouts
   are logged to stderr but never block the render. Uses `urllib` (stdlib) —
   no requests dependency.

4. **Reuse.** Webhooks share the same lifecycle events and payload shape as
   pipeline hooks (task-67). The distinction: hooks are local processing,
   webhooks are external notifications.

**Tests:**
- Webhook POST fires with correct JSON body
- HMAC signature header present and valid
- Webhook URL unreachable → render continues
- Webhook timeout → logged, render continues
- `webhooks.enabled: false` → no POSTs
- Event filtering: only configured events fire

---

### task-73: Tool Directive Integration

**Goal:** `@tool "<path>" [args]` invokes external tools with an allowlist.

**Files to touch:**
- `src/perseus/directives/` — new `tool.py`
- `src/perseus/registry.py` — register `@tool` directive
- `src/perseus/config.py` — `tools` config block
- `tests/test_tool.py`

**Config:**
```yaml
tools:
  enabled: true
  allowlist:
    - path: "/usr/local/bin/scanner"
      args_allowlist: ["--workspace", "--format", "--timeout"]  # empty = all allowed
      timeout_s: 30
      max_output_bytes: 65536
    - path: "./scripts/lint.sh"
      timeout_s: 60
```

**Directive syntax:**
```markdown
@tool "/usr/local/bin/scanner" --workspace . --format json @cache ttl=3600
```

**Implementation:**

1. **Path resolution.** If the path is relative, resolve against workspace.
   If absolute, use as-is. The allowlist matches on resolved absolute path.

2. **Security.** If `tools.enabled: false`, `@tool` is a no-op (emits warning).
   If the tool path is not in the allowlist → error. If args are restricted and
   a provided arg isn't in the allowlist → error.

3. **Execution.** Subprocess with timeout. stdout → directive output. stderr →
   appended as a comment block in the output. Non-zero exit → warning.

4. **Difference from `@agent`.** `@agent` is a raw `subprocess.run()` with no
   allowlist — it's gated by `allow_agent_shell` and trusts the user.
   `@tool` has an explicit allowlist, argument restrictions, and structured
   error handling. It's for shared/repeatable tool invocations; `@agent` is for
   ad-hoc commands.

**Tests:**
- Allowed tool runs and produces output
- Non-allowlisted tool → error
- Restricted arg rejected
- Timeout handling
- Output size cap enforced
- `tools.enabled: false` → no-op with warning
- Relative path resolves against workspace

---

### task-74: Directive Aliasing

**Goal:** Config-driven shorthand for directives.

**Files to touch:**
- `src/perseus/renderer.py` — alias expansion in pre-processing pass
- `src/perseus/config.py` — `directives` config block
- `tests/test_aliases.py`

**Config:**
```yaml
directives:
  aliases:
    "@q": "@query"
    "@svc": "@services"
    "@mb": "@memory"
    "@stale-skills": "@skills flag_stale=true category=all"
```

**Implementation:**

1. **Pre-processing.** Before `_render_lines()`, a pass walks every line and
   checks if it starts with an alias. If so, replaces the alias prefix with the
   expansion. The rest of the line (args) is preserved.

   Example: `@q "ls -la" @cache ttl=60` → `@query "ls -la" @cache ttl=60`

2. **Pre-defined aliases.** Some aliases for common patterns:
   ```python
   PREDEFINED_ALIASES = {
       "@q": "@query",
       "@r": "@read",
       "@svc": "@services",
       "@mb": "@memory",
       "@ag": "@agora",
       "@wp": "@waypoint",
       "@sess": "@session",
   }
   ```
   Config aliases override pre-defined ones.

3. **Built-in collision.** An alias that shadows a built-in directive name is
   rejected with a warning. Built-ins always win.

4. **Alias chains.** Aliases are expanded in a single pass (not recursively).
   `@a → @b` where `@b → @c` does NOT expand to `@c`. This prevents accidental
   loops and keeps the expansion predictable.

**Tests:**
- Simple alias expansion
- Alias with preserved args
- Alias shadowing built-in → rejected
- Config alias overrides pre-defined
- Alias in `@if` block
- No recursive expansion

---

## Execution Order (summary)

```
task-65 (Plugin System) ←── START HERE
    │
    ├── task-66 (Macros)
    ├── task-67 (Pipeline Hooks)
    ├── task-68 (Format Adapters)
    ├── task-69 (Foreign Resolver + MCP)
    ├── task-70 (Custom Validators)
    ├── task-71 (Pipe Syntax)
    ├── task-72 (Event Webhooks)
    ├── task-73 (Tool Directive)
    └── task-74 (Directive Aliasing)
```

Tasks 66-74 all need the plugin discovery mechanism from task-65. Once that
lands, they can be worked in any order or even parallelized.

---

## Constraints (from ROADMAP, non-negotiable)

1. Edit `src/perseus/` modules, not `perseus.py`. Regenerate with
   `python scripts/build.py`.
2. `pyyaml` is the only dependency. Do not add deps.
3. Tests before commit. All existing tests must pass.
4. Spec follows code. Update relevant docs.
5. Keep the mythology. Hephaestus is now part of it.
6. Backward compatibility. Existing syntax and config keys must not break.
7. Executors, not architects. Build what's spec'd.

---

## Pre-flight Checklist for Next Session

- [ ] Read ROADMAP.md (live `@perseus` source)
- [ ] Read AGENTS.md (contributor guide)
- [ ] Read this HANDOFF.md
- [ ] Run `pytest tests/ -x` — confirm all 450+ tests pass before starting
- [ ] Start task-65: Plugin Directive System
