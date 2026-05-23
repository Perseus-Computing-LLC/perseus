# Perseus — AI Assistant Integrations

Perseus is assistant-agnostic. It produces plain markdown. Every integration below just
points the markdown at the file your assistant already reads.

| Integration | Surface | Install | Distribution |
|---|---|---|---|
| **[VS Code / Cursor](./vscode/)** | Every dev using Copilot, Cursor, Codex, Claude | `.vsix` or Marketplace | VS Code Marketplace |
| **[Claude Code](./claude-code/)** | Session-start hook | One curl command | README snippet |
| **[GitHub Action](./github-action/)** | Every repo on GitHub | One workflow file | GitHub Actions Marketplace |

## Pattern

All three follow the same pattern:

1. **Before** assistant session: `perseus render .perseus/context.md --output <target>`
2. **Assistant opens**: reads `<target>` (CLAUDE.md, AGENTS.md, .cursorrules, .hermes.md)
3. **Zero discovery calls** — context is live, verified, pre-resolved

## Quickstart

```bash
# 1. Install Perseus
pip install perseus-ctx

# 2. Scaffold your workspace
cd my-project
perseus init . --output CLAUDE.md

# 3. Pick your integration:
#    VS Code → install from integrations/vscode/
#    Claude Code → curl integrations/claude-code/on_session_start.sh
#    GitHub Actions → copy integrations/github-action/ workflow
```
