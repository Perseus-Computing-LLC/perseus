---
id: task-17
title: "Task 17 — Template Gallery: perseus init --template"
status: completed
scope: small-medium
depends_on: []
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: '2026-05-18'
---

# Task 17 — Template Gallery

## Goal

Ship a `templates/` directory at repo root with starter `.perseus/context.md`
files keyed by AI assistant, and extend `perseus init` with a `--template <name>`
flag that copies the chosen template into the new workspace.

## Why

The current `perseus init` scaffolds a generic stub. Most new users have a
specific assistant target (Hermes, Rovo Dev, Claude Code, Cursor) and want a
starting point already tuned for that consumer's conventions
(`AGENTS.md` vs `CLAUDE.md` vs `.cursorrules`, etc.). A small curated gallery
turns "first useful render" into a 5-second affair.

## Spec

### Layout

```
templates/
  generic/.perseus/context.md         ← default; what init writes today
  hermes/.perseus/context.md          ← assumes Hermes Agent reads .hermes.md
  rovodev/.perseus/context.md         ← assumes Rovo Dev reads AGENTS.md
  claude-code/.perseus/context.md     ← assumes Claude Code reads CLAUDE.md
  cursor/.perseus/context.md          ← assumes Cursor reads .cursorrules
```

Each template uses the same directive vocabulary but has a different output
file name baked into a header comment and a different default `@prompt` block
keyed to that assistant's conventions.

### CLI

```bash
perseus init                       # current behavior — writes "generic" template
perseus init --template hermes
perseus init --template rovodev
perseus init --template claude-code
perseus init --template cursor
perseus init --list-templates      # prints available template names
```

### Discovery

`templates/` lives next to `perseus.py` (siblings under the repo root). Lookup
order:

1. `$PERSEUS_TEMPLATE_DIR` if set
2. `<dir-of-perseus.py>/templates/`
3. Fallback to embedded generic stub (current behavior)

## Acceptance criteria

1. `perseus init` without `--template` keeps current behavior (no regression).
2. `perseus init --template hermes` writes the hermes template's contents.
3. `perseus init --list-templates` lists the discovered templates.
4. Unknown template name → clear error message naming available templates.
5. `--template` honours `$PERSEUS_TEMPLATE_DIR`.
6. Each template is self-contained markdown; no embedded shell.

## Constraints

Single file (perseus.py). Templates can live in a sibling `templates/` dir —
that's not "code", that's data. No new dependencies.

## Start here

1. Add `--template` and `--list-templates` to `p_init`.
2. Add `_template_dir()` and `_list_templates()` helpers in perseus.py.
3. Update `cmd_init` to read the selected template if specified.
4. Create the 5 template files under `templates/<name>/.perseus/context.md`.
5. Tests: 4+ — list, default, named template, unknown name.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `templates/{generic,hermes,rovodev,claude-code,cursor}/.perseus/context.md` shipped
- Each assistant-flavored template uses the same directive vocabulary but with assistant-specific @prompt copy and output-file hint
- `perseus init --template <name>` and `perseus init --list-templates`
- Discovery: `$PERSEUS_TEMPLATE_DIR` → `<dir-of-perseus.py>/templates/` → embedded stub
- `{workspace}` placeholder substitution
- 6 tests: list known names, load known, unknown returns None, init with template, init unknown errors, list-templates output, env override
