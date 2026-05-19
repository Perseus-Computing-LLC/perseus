---
id: task-23
title: Task 23 — Perseus LSP Server (Phase 10.1)
status: completed
scope: large
depends_on:
  - task-12
  - task-15
  - task-18
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: 2026-05-18
phase: 10.1
---

# Task 23 — Perseus LSP Server

## Context

Today Perseus is a CLI + a read-only HTTP view. Editor users get value by
running `perseus render` in a terminal and re-rendering after every change.
That works but loses the immediate feedback loop that makes structured
markdown documents like `.perseus/context.md` painful to write.

A Language Server Protocol implementation gives editors a standard way to
get **diagnostics, hover info, autocomplete, code lenses, and "go to
definition"** for Perseus directives — without each editor needing a
custom extension that re-implements the parser.

## Hard architectural constraint

The single-file rule still applies. The LSP server lives in `perseus.py`
under `perseus serve --lsp [--stdio | --tcp PORT]`. No new files. No new
dependencies beyond pyyaml.

This means **implementing LSP by hand** — there's no `pygls` allowed.
The LSP protocol is small enough (JSON-RPC over stdio or TCP with a
content-length header) to implement directly in ~300-400 LOC.

## Design

### Surface
```
perseus serve --lsp --stdio          # for editor stdin/stdout integration
perseus serve --lsp --tcp 7992       # for editor TCP connection
```

### Protocol scope (LSP 3.17 subset)

1. **`initialize` / `initialized` / `shutdown` / `exit`** — lifecycle
2. **`textDocument/didOpen`, `didChange`, `didClose`** — document tracking
3. **`textDocument/publishDiagnostics`** — push warnings/errors for:
   - Unknown directives
   - Invalid directive arguments
   - Malformed `@if/@else/@endif` blocks
   - `@cache ttl=` with non-integer
   - Unsubscribed federation alias referenced in `@memory federation alias=...`
   - Stale `@waypoint` (older than configured TTL)
4. **`textDocument/hover`** — show the resolved output for the directive
   under the cursor (e.g. hover on `@waypoint` → the actual rendered
   checkpoint summary)
5. **`textDocument/completion`** — directive name + argument completion
   (e.g. typing `@me<TAB>` offers `@memory`, then `@memory <TAB>` offers
   `focus=`, `federation`, `include_federation=`, etc.)
6. **`textDocument/codeLens`** — "▶ Render" inline lens above the first
   `@` directive of each document; clicking triggers `workspace/executeCommand`
7. **`workspace/executeCommand`** — handle commands:
   - `perseus.render` — render the current document and show the result
   - `perseus.openCheckpoint` — open the latest checkpoint file
   - `perseus.compactMemory` — run `perseus memory compact` for current workspace

### Document model

The server holds an in-memory document store keyed by URI. On every
`didChange`, re-parse and re-publish diagnostics. Parsing reuses the
existing `INLINE_DIRECTIVE_RE` and block-directive logic — refactor as
needed but DON'T duplicate.

### Hover implementation

Hovering on `@waypoint ttl=86400` runs `resolve_waypoint("ttl=86400", cfg, ws)`
and returns the result as a markdown code block. This means the LSP is
effectively a live previewer. Cache hover results for 2 seconds per
directive instance to avoid hammering the resolvers.

### Workspace detection

The LSP needs a workspace path to resolve directives like `@waypoint` and
`@memory`. Resolution order:
1. `initialize`'s `workspaceFolders` (LSP standard)
2. `rootUri` (deprecated but widely used)
3. Walk upward from the document's `uri` looking for `.perseus/` or
   `AGENTS.md`
4. Fall back to the document's directory

## Acceptance criteria

1. `perseus serve --lsp --stdio` and `--lsp --tcp PORT` both work
2. Implements the LSP 3.17 subset above
3. Diagnostics fire on at least the 5 error classes listed
4. Hover returns directive output for `@waypoint`, `@memory`, `@health`,
   `@agora`, `@inbox`, `@skills`, `@session`
5. Completion offers all directive names + per-directive arg keys
6. CodeLens "▶ Render" appears above the first directive
7. `workspace/executeCommand` handles the 3 listed commands
8. Stdio transport works with at least one real editor (test with
   `helix-editor`'s LSP support since it's the simplest)
9. Tests: JSON-RPC framing parser, each handler in isolation, full
   round-trip with a fake client
10. spec/components.md gets a § 12 (LSP) section
11. README gets a "Editor integration" section

## Non-goals

- LSP semantic tokens / syntax highlighting (markdown editors already
  highlight; tokens are for languages without that)
- Formatting (`textDocument/formatting`) — Perseus documents are
  hand-authored markdown; auto-formatting is risky
- Refactoring (`textDocument/codeAction`) — defer to Phase 11
- Auth/encryption — LSP is local-only by convention; stdio is unauthenticated
  by design

## Start here

1. Claim the task: flip frontmatter `status: in_progress` and
   `claimed_by: <model name>`.
2. Extend `cmd_serve` to accept `--lsp`, `--stdio`, `--tcp PORT` flags.
3. Implement the JSON-RPC framing layer (content-length header + JSON body)
   as `_lsp_read_message` / `_lsp_write_message`.
4. Implement the lifecycle handlers (`initialize` etc.) — return server
   capabilities matching the scope above.
5. Implement document store: dict[uri] → text + parse cache.
6. Implement `publishDiagnostics` driven by re-parse on every didChange.
7. Implement hover, completion, codeLens in that order — each is small
   and independent.
8. Implement `workspace/executeCommand` last.
9. Tests with synthetic LSP messages over a fake stdio pair.
10. Manual smoke test with helix or VSCode (record commands used).
11. Docs + commit + push.
12. Add a `# Completed` section.

# Completed

Shipped 2026-05-18 with tasks 20/21/22/24.

- `perseus serve --lsp --stdio` and `--lsp --tcp PORT` both work
- Hand-rolled JSON-RPC framing (`_lsp_read_message` / `_lsp_write_message`) — no `pygls`, single-file constraint preserved
- LSP 3.17 subset: initialize, initialized, shutdown, exit, textDocument/didOpen, didChange, didClose, publishDiagnostics, hover, completion, codeLens, workspace/executeCommand
- Diagnostics for 5 classes: unknown directives, unmatched @else/@endif, unclosed @if, unclosed @constraint, `@cache ttl=` non-integer, unsubscribed federation alias
- Hover for @waypoint, @memory, @health, @agora, @inbox, @skills, @session, @drift, @date, @agent
- Completion: 21 directive names + per-directive arg keys
- CodeLens "▶ Render" above first directive
- executeCommand: perseus.render, perseus.openCheckpoint, perseus.compactMemory
- Workspace resolution: workspaceFolders → rootUri → walk for `.perseus/` or `AGENTS.md` → cwd
- 11 new tests
