# Perseus Context Engine integrations

Perseus Context Engine renders plain markdown for the files that compatible assistant hosts already read.

| Integration | Surface | Installation boundary |
|---|---|---|
| [VS Code / Cursor](./vscode/) | Editor context | Install a reviewed `.vsix` or use the Marketplace listing |
| [Claude Code](./claude-code/) | Session-start hook | Install the checked-in hook from a reviewed checkout |
| [GitHub Action](./github-action/) | Repository workflow | Copy and review the checked-in workflow; commit and push remain off unless explicitly enabled |
| [Invarium](./invarium.md) | Context regression testing | Follow its versioned package documentation |

## Pattern

1. The integration runs `perseus render .perseus/context.md --output <target>`.
2. The assistant host reads the rendered target file.
3. Shell and network directives remain subject to the Context Engine security gates and current-user permissions.

## Start from a reviewed checkout

```bash
python -m pip install perseus-ctx==1.0.26
cd my-project
perseus quickstart

# Choose one reviewed integration source:
# VS Code: integrations/vscode/
# Claude Code: integrations/claude-code/on_session_start.sh
# GitHub Actions: integrations/github-action/
```

Do not download and execute mutable scripts from a branch tip. Review the checked-in integration before installing it.
