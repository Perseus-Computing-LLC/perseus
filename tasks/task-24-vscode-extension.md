---
id: task-24
title: Task 24 — VSCode Extension (Phase 10.2)
status: in_progress
scope: medium
depends_on:
  - task-23
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: null
phase: 10.2
---

# Task 24 — VSCode Extension

## Context

task-23 ships the LSP. That alone gives VSCode (and Cursor, Windsurf,
Helix, Zed, Neovim, Sublime LSP, JetBrains LSP, etc.) most of what they
need.

A thin VSCode extension that activates the LSP + adds a few
VSCode-specific affordances (tree view, statusbar item, command palette
entries) is the polished path most users will see.

## Hard architectural constraint (modified)

This is the FIRST task that necessarily introduces a second deliverable
outside `perseus.py`. The VSCode extension is a TypeScript project
under `editors/vscode/` — it's a separate package by VSCode's design.

The justification for the exception is mechanical, not philosophical:
VSCode extensions must be `.vsix` bundles with `package.json`. There is
no way to ship one as part of `perseus.py`.

The extension itself stays minimal:
- < 500 LOC TypeScript
- Only `vscode-languageclient` as a runtime dep
- All real logic lives in the LSP — the extension just wires VSCode → LSP

## Design

### Repo layout addition
```
perseus.py                              # unchanged
editors/
  vscode/
    package.json                        # extension manifest
    src/
      extension.ts                      # activate() + LSP client wiring
      treeView.ts                       # workspace tree provider
      statusBar.ts                      # workspace state in status bar
    tsconfig.json
    README.md                           # install + dev instructions
    .vscodeignore
```

### Activation events
- `onLanguage:markdown` (Perseus directives live in markdown)
- `workspaceContains:.perseus/context.md`
- `workspaceContains:AGENTS.md`

### Features

1. **LSP client** — launches `perseus serve --lsp --stdio` and routes
   markdown buffers through it
2. **Tree view** (Perseus sidebar):
   - Workspace context (one node, expandable to checkpoints, oracle log,
     narrative)
   - Federation subscriptions (one node per subscription, expandable to
     show the federated narrative inline)
   - Open tasks (from `tasks/*.md`)
3. **Status bar item** — shows last checkpoint age, click → `perseus
   checkpoint` command
4. **Command palette entries** (all just trigger LSP commands):
   - "Perseus: Render Current Document"
   - "Perseus: Write Checkpoint"
   - "Perseus: Compact Narrative"
   - "Perseus: Show Workspace Health"
   - "Perseus: Federation List"

### Settings (VSCode `settings.json`)
```jsonc
{
  "perseus.binary": "perseus",          // or absolute path
  "perseus.serverArgs": ["serve", "--lsp", "--stdio"],
  "perseus.statusBar.enabled": true,
  "perseus.treeView.refreshIntervalSec": 30
}
```

## Acceptance criteria

1. `editors/vscode/` package builds with `npm run package` → produces a
   `.vsix`
2. Extension activates on markdown files in workspaces containing
   `.perseus/` or `AGENTS.md`
3. LSP client connects to `perseus serve --lsp --stdio` and surfaces
   diagnostics + hover + completion correctly
4. Tree view shows workspace state with live refresh
5. Status bar item shows checkpoint age (color-coded: green/yellow/red by
   staleness)
6. All 5 command palette entries work
7. README.md in `editors/vscode/` covers: install (dev + marketplace),
   configuration, troubleshooting
8. Top-level Perseus README gets an "Editor support" section
   pointing to `editors/vscode/README.md`
9. Repo CI doesn't need to build the extension (VSCode-specific tooling
   complicates things) — manual `npm run package` is acceptable for v1

## Non-goals

- Publishing to the VSCode marketplace (cert/publisher setup is a separate
  arc — not blocking)
- JetBrains plugin (different platform; revisit if there's demand)
- Webview previews of rendered output (status-quo `perseus serve` HTTP
  view covers this)
- Theme/icon contributions

## Start here

1. Verify task-23 (LSP) is complete and stable.
2. Claim this task.
3. Scaffold `editors/vscode/` with `npm init @vscode-extension` or
   equivalent.
4. Wire `vscode-languageclient` to launch `perseus serve --lsp --stdio`.
5. Add tree view, status bar, commands in that order.
6. Manual test: install the `.vsix`, open a workspace with Perseus,
   verify the 9 acceptance criteria.
7. Docs + commit + push.
8. Add a `# Completed` section.
