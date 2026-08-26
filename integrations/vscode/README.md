# Perseus lightweight VS Code / Cursor adapter

This directory contains a source-only compatibility adapter. The supported LSP extension and its release instructions live in [`editors/vscode`](../../editors/vscode/). Do not publish this adapter as the primary Marketplace extension.

The adapter does not render merely because a repository is opened. VS Code must trust the workspace, and automatic rendering is off by default. It invokes only an executable found on the operator's `PATH` or an explicitly configured absolute executable path. It does not execute a workspace copy of `perseus.py`.

## Local review and install

1. Review `extension.js` and `package.json` from a pinned repository commit.
2. Copy this directory to a local VS Code extension-development location.
3. Reload VS Code and open a trusted workspace containing `.perseus/context.md`.
4. Run `Perseus: Render Context Now`, or explicitly enable automatic rendering after reviewing the context source and output path.

Do not install the unreviewed directory from a mutable branch.

## Configuration

| Setting | Default | Description |
|---|---|---|
| `perseus.autoRender` | `false` | Render after context changes only when explicitly enabled in a trusted workspace |
| `perseus.executable` | empty | Optional absolute path to a reviewed executable; otherwise the adapter searches `PATH` |
| `perseus.outputFile` | `.hermes.md` | Workspace-relative output; traversal outside the workspace is rejected |
| `perseus.assistant` | `auto` | Select a fixed workspace-relative assistant output |
| `perseus.showStatusBar` | `true` | Show render status |

The adapter uses argument arrays rather than a shell command string. Enabled rendering still runs with the current user's permissions and can overwrite the selected file inside the trusted workspace.
