---
id: task-65
title: Phase 24A — Plugin Directive System
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-24
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on: []
blocks:
- task-66
- task-67
- task-68
- task-69
- task-70
opened: '2026-05-24'
closed: null
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
- Load order: built-in registry first, then plugins. Plugin directives that
  collide with built-in names are **silently overridden by built-ins** (built-ins
  always win)
- Plugin directives that collide with each other: **last loaded wins**, with
  a warning

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
