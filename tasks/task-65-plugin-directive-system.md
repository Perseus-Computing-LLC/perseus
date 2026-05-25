---
id: task-65
title: "Phase 24A \xE2\u20AC\u201D Plugin Directive System"
status: completed
priority: high
scope: large
claimed_by: claude-opus-4-7
created: 2026-05-24
phase: 24
theme: "Extensibility Architecture \xE2\u20AC\u201D Hephaestus"
depends_on: []
blocks:
- task-66
- task-67
- task-68
- task-69
- task-70
opened: '2026-05-24'
closed: '2026-05-25'
---
## Why

The `DIRECTIVE_REGISTRY` is clean internally but every extension requires editing
`src/perseus/registry.py`, adding a resolver to the source tree, and rebuilding
the artifact. A plugin system makes Perseus a *platform* rather than a closed
tool. Users can add directives without source patching, no fork required, no
rebuild needed.

**Hephaestus** forged the automata — self-operating bronze servants, the golden
maiden assistants, Talos the bronze guardian. Extensibility is Hephaestus's
domain: giving Perseus the ability to forge its own tools.

This task is the foundation for all of Phase 24. Everything else — macros,
hooks, format adapters, custom validators — depends on plugin discovery landing
first.

## What

Auto-discovered Python plugins from `~/.perseus/plugins/`. Each module exports a
`REGISTER` dict of `DirectiveSpec` entries. `_bind_registry()` scans and merges
them before building the inline regex.

### Plugin contract

```python
# ~/.perseus/plugins/my_directive.py

from perseus.registry import DirectiveSpec

REGISTER = {
    "my-directive": DirectiveSpec(
        name="my-directive",
        pattern=r"@my-directive\s+(?P<arg>.*)",
        resolver=resolve_my_directive,
        description="My custom directive",
        category="custom",
    )
}

def resolve_my_directive(match, ctx):
    arg = match.group("arg").strip()
    return f"Resolved: {arg}"
```

### Discovery

- Scan `~/.perseus/plugins/*.py` on startup (before registry binding)
- `importlib.util` — no `pip install`, no `setup.py`
- Plugin import errors are **warnings**, not fatal — a broken plugin never
  breaks render
- Load order: built-in registry first, then plugins (sorted by filename).
  Plugin directives that collide with built-in names are **overridden by
  built-ins** (built-ins always win), with a warning to stderr
- Plugin directives that collide with each other: **first loaded wins**
  (sorted-filename order), with a warning to stderr

### Config gates

- `plugins.enabled` (default: `true`) — master kill switch
- `plugins.directory` (default: `~/.perseus/plugins/`) — configurable scan path
- No per-plugin enable/disable in v1 — scope creep. Add later if needed

### Trust boundaries

- Plugin directives inherit the workspace permission profile
- Plugin directives **cannot** override safety gates (`allow_query_shell`,
  `allow_agent`, `trust.profile`)
- Plugin resolvers run in the same process — no sandboxing in v1. Document this
  as a trust consideration

## Acceptance Criteria

1. `~/.perseus/plugins/` is scanned on Perseus startup (import, not render)
2. Any `.py` file exporting a `REGISTER` dict of `DirectiveSpec` entries is
   merged into the directive registry
3. Plugin directives appear in `perseus graph --json` output with
   `source: plugin` metadata
4. Plugin directives render correctly in source documents
5. Plugin with syntax error → warning on stderr, all other directives still work
6. Plugin with name collision with built-in → built-in wins, plugin ignored
   with warning
7. `plugins.enabled: false` → no plugin scan, no plugins loaded
8. Existing directive security gates (shell, agent, file read) apply to plugin
   resolvers
9. Tests:
   - Plugin loads and directive resolves
   - Plugin with import error → warning, render succeeds
   - Plugin with name collision → built-in wins
   - `plugins.enabled: false` → plugins not loaded
   - Plugin resolver blocked by trust gate (e.g., `allow_query_shell: false`)
10. No new dependencies. `importlib.util` is stdlib.

## Non-goals

- Do not add per-plugin enable/disable config
- Do not add plugin sandboxing or process isolation
- Do not add a plugin marketplace or registry
- Do not support non-Python plugins (WASM, Lua, etc.)
- Do not add hot-reload of plugins without restart

## Completed

The plugin discovery scaffolding (`_discover_plugins`, the `plugins.enabled` / `plugins.dir` config keys, and an 8-test harness in `tests/test_plugin.py`) was already present from earlier Phase-24 work. This task closed the gaps that prevented those tests from reflecting real production behavior.

**Changes landed:**
- `src/perseus/registry.py`
  - Added `source: str = "builtin"` field to `DirectiveSpec` (default keeps every existing entry source-tagged as `"builtin"`).
  - `_discover_plugins` now wraps each discovered spec with `._replace(source="plugin")` so plugin-loaded specs are distinguishable.
  - New `register_plugins(cfg, force=False)` — idempotent merge into `DIRECTIVE_REGISTRY` with explicit built-in-wins (warn) and plugin-vs-plugin first-loaded-wins (warn) semantics; rebuilds `INLINE_DIRECTIVE_RE` when a new inline directive is added. Backed by `_PLUGIN_LOADED_DIRS` to avoid re-importing plugin modules on every render. `_reset_plugin_cache()` exposed for test isolation.
- `src/perseus/directives/query.py`
  - `_directive_graph_node` now emits `"source": spec.source` on each node — satisfies AC #3 (plugin directives show `source: plugin` in `perseus graph --json`).
- `src/perseus/renderer.py`
  - `render_source` and `render_source_with_meta` call `register_plugins(cfg)` once per top-level render before any directive matching.
- `src/perseus/serve.py`
  - `cmd_graph` now loads config and calls `register_plugins(cfg)` so plugin directives appear in `perseus graph` output.
  - `cmd_prefetch` calls `register_plugins(cfg)` so prefetch rules can target plugin directives.
- `tests/test_plugin.py`
  - `_reset_registry` fixture now also calls `perseus._reset_plugin_cache()`.
  - `_discover_and_register` helper rewritten to call `register_plugins(cfg, force=True)` so the production code path is exercised end-to-end.
  - Added `test_plugin_import_error_continues_render` — covers AC #5 (true `import` error in a plugin file logs to stderr, render of subsequent plugin still succeeds).
  - Added `test_plugin_directive_has_source_metadata_in_graph` — covers AC #3.
- `scripts/build.py` — incidental fix: `read_text` / `write_text` now pass `encoding="utf-8"` so the artifact regenerates on Windows (built-in cp1252 default could not decode em-dashes in the source).
- `perseus.py` — regenerated artifact (12,876 lines).

**Acceptance criteria audit:**

| AC | Status |
|---|---|
| 1. `~/.perseus/plugins/` scanned on startup | ✅ `register_plugins` invoked from all directive-resolution entry points |
| 2. `.py` files exporting `REGISTER` merged into registry | ✅ |
| 3. Plugin directives in graph with `source: plugin` | ✅ |
| 4. Plugin directives render correctly | ✅ |
| 5. Plugin import error → warning, render works | ✅ + new test |
| 6. Plugin name collides with built-in → built-in wins | ✅ + explicit warning now |
| 7. `plugins.enabled: false` → no scan | ✅ |
| 8. Security gates apply to plugin resolvers | ✅ |
| 9. All 5 specified tests covered | ✅ (10 tests total now in `test_plugin.py`) |
| 10. No new dependencies | ✅ |

**Spec change (heads-up):** the spec previously read "Plugin directives that collide with each other: last loaded wins". The implemented and tested behavior is first-loaded-wins (sorted-filename order — symmetric with built-ins-first-wins, and `test_plugin_duplicate_name_first_wins` already locked this in). Per AGENTS.md constraint #4 ("code is the truth"), I updated the spec text to match.

**Test impact:** baseline `pytest tests/ -q` was 47 fail / 578 pass / 7 skip. After this change: 46 fail / 581 pass / 7 skip. The 2 new tests pass; 1 pre-existing test flipped from fail→pass (collateral from the source-field rollout — graph schema is now strictly more informative). The remaining 46 failures are all pre-existing Windows compat issues (`/bin/bash` not on PATH, socket binding for LSP TCP transport, release-tarball platform assumptions) unrelated to plugins.

**Notes for the owner:**
- Built-in-vs-plugin collision now emits a warning to stderr (the original spec said "silently overridden"; warning is more debuggable and matches the plugin-vs-plugin case). If silent is preferred, the warning is one line to remove.
- `register_plugins` is keyed by `plugins.dir` for idempotency. Long-running processes that load multiple workspaces would currently see the first workspace's plugins "stick" — out of scope here, but worth a follow-up task if multi-workspace daemon/serve mode becomes important (overlaps with the task-64 spike).
