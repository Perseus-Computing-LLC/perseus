# Perseus — VS Code / Cursor Extension

Live context for your AI coding assistant. Zero cold-start discovery calls.

## Install

1. Copy this directory to `~/.vscode/extensions/perseus-context/`
2. Reload VS Code (`Ctrl+Shift+P` → "Developer: Reload Window")
3. Open a workspace with `.perseus/context.md` — Perseus activates automatically

Or from the marketplace (coming soon):
```bash
code --install-extension tcconnally.perseus-context
```

## How it works

1. **Auto-render** — When you save `.perseus/context.md`, Perseus renders live context to your assistant's file
2. **Status bar** — "Perseus: 722 lines · 48KB · 1.7s" — always visible
3. **Assistant auto-detect** — Finds CLAUDE.md, .cursorrules, AGENTS.md, or .hermes.md automatically
4. **Commands**: `Perseus: Render Context Now` · `Perseus: Init Workspace`

## Configuration

| Setting | Default | Description |
|---|---|---|
| `perseus.autoRender` | `true` | Auto-render on context file changes |
| `perseus.outputFile` | `.hermes.md` | Output file name |
| `perseus.assistant` | `auto` | Target assistant (claude, cursor, codex, hermes, copilot) |
| `perseus.showStatusBar` | `true` | Show render status in status bar |

## Publish to Marketplace

```bash
npm install -g @vscode/vsce
cd integrations/vscode
vsce package  # → perseus-context-1.0.0.vsix
vsce publish  # → live on marketplace
```

Requires a Visual Studio Marketplace publisher account. Create one at https://marketplace.visualstudio.com/manage
