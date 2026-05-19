# Perseus — VSCode extension

Thin Language Server Protocol client for the Perseus context engine. All
real logic lives in the Perseus LSP server (`perseus serve --lsp --stdio`,
shipped inside `perseus.py`); this extension is a launcher + a few VSCode-
specific niceties.

## Features

- **Diagnostics** — unknown directives, malformed `@if/@else/@endif`, bad
  `@cache ttl=`, unsubscribed federation aliases, unclosed `@constraint`
- **Hover** — preview the rendered output of `@waypoint`, `@memory`,
  `@health`, `@agora`, `@inbox`, `@skills`, `@session`, `@drift`, `@date`,
  `@agent` directly inline
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

## Development

```bash
cd editors/vscode
npm install
npm run compile         # tsc → out/extension.js
code --extensionDevelopmentPath="$PWD"   # spawn an Extension Host window
```

Open any `.md` file (or `AGENTS.md`, `.perseus/context.md`) and type
`@` to see completion fire. Hover over `@waypoint ttl=86400` to see the
last checkpoint's rendered summary.

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
