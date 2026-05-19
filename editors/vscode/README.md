# Perseus — VSCode extension

Thin Language Server Protocol client for the Perseus context engine. All
real logic lives in the Perseus LSP server (`perseus serve --lsp --stdio`,
shipped inside `perseus.py`); this extension is a launcher + a few VSCode-
specific niceties.

## Features

- **Diagnostics** — unknown directives, malformed `@if/@else/@endif`, bad
  `@cache ttl=`, unsubscribed federation aliases, unclosed `@constraint`
- **Hover** — preview safe rendered directives such as `@waypoint`,
  `@memory`, `@health`, `@agora`, `@inbox`, `@skills`, `@session`,
  `@drift`, and `@date`; shell-backed directives show a disabled stub
- **Completion** — directive names + per-directive argument keys
- **CodeLens** — "▶ Render" lens at the first directive of each document
- **Commands** — `Perseus: Render Current Document`, `Perseus: Open Latest
  Checkpoint`, `Perseus: Compact Mnēmē Narrative`
- **Status bar** — `$(zap) Perseus` indicator; click to render

## Requirements

- VSCode 1.85.0+
- `perseus` binary installed and on PATH (or configured via
  `perseus.binary`). Get it from the
  [Perseus repository](https://github.com/tcconnally/perseus).

## Configuration

| Setting | Default | Description |
|---|---|---|
| `perseus.binary` | `perseus` | Path to the `perseus` executable. |
| `perseus.tracing` | `off` | LSP trace level (`off`, `messages`, `verbose`). |
| `perseus.allowMutations` | `false` | Start the LSP with mutation commands enabled, including Mneme compaction. |

## Development

The extension is plain TypeScript and must be compiled before the Extension
Host can load it (the entry point in `package.json` is `./out/extension.js`,
not the `.ts` source). The order matters — skip `npm run compile` and
VSCode will fail to activate with `Cannot find module`.

```bash
cd editors/vscode
npm install             # one-time: pulls vscode-languageclient + @types/vscode
npm run compile         # tsc → out/extension.js  ← REQUIRED before launch
code --extensionDevelopmentPath="$PWD"   # spawn an Extension Host window
```

For iterative development, run `npm run watch` in a second terminal so the
TypeScript compiler picks up changes automatically; reload the Extension
Host window (`Cmd-R` / `Ctrl-R`) to pick up the new build.

Open any `.md` file (or `AGENTS.md`, `.perseus/context.md`) and type
`@` to see completion fire. Hover over `@waypoint ttl=86400` to see the
last checkpoint's rendered summary.

## Known issues / pre-publication checklist

- **`publisher: perseus` in `package.json` is a placeholder.** Before
  submitting to the VSCode Marketplace it must be changed to a real
  publisher ID matching a verified Azure DevOps account
  (`vsce create-publisher <name>` if you don't have one). Beta testing
  via `vsce package` + sideload `.vsix` works fine with the placeholder.
- **No `npm run lint`, no tests yet.** This is a thin launcher; the real
  test surface is the LSP server tested in `tests/test_perseus.py`. If the
  extension grows non-trivial logic that's worth covering, add
  `@vscode/test-electron` and a `test/` directory.

---

## Packaging

```bash
npm install -g @vscode/vsce
vsce package
# → produces perseus-vscode-0.1.0.vsix
```

Install the resulting `.vsix` via the VSCode command palette:
`Extensions: Install from VSIX...`

## Why this lives outside `perseus.py`

The single-file constraint in [`AGENTS.md`](../../AGENTS.md) is preserved
in spirit: this extension is a *bridge*, not real logic. It launches the
Perseus LSP and forwards three commands. If the extension stops working,
the LSP still does — and anything else that speaks LSP (Helix, Neovim,
JetBrains via custom plugin, Zed) gets the same features for free.

## License

MIT — see [LICENSE](../../LICENSE).
