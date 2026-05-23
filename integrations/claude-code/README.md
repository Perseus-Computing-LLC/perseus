# Perseus — Claude Code Hook

Pre-resolves live workspace state before every Claude Code session.

## Install (one line)

```bash
mkdir -p .claude/hooks && \
curl -fsSL https://raw.githubusercontent.com/tcconnally/perseus/main/integrations/claude-code/on_session_start.sh \
  -o .claude/hooks/on_session_start.sh && \
chmod +x .claude/hooks/on_session_start.sh
```

## What happens

Every time you run `claude` in this repo:

1. Perseus reads `.perseus/context.md`
2. Resolves all `@query`, `@services`, `@skills`, `@waypoint` directives
3. Writes live, verified facts to `CLAUDE.md`
4. Claude opens with the workspace already oriented — zero discovery calls

## Verify

```bash
bash .claude/hooks/on_session_start.sh
# → [Perseus] → 298 lines · 20KB · 1251ms
# → [Perseus] Claude will open with live context
cat CLAUDE.md | head -20
```

## Requirements

- `pip install perseus-ctx` or `perseus.py` in repo root
- `.perseus/context.md` in workspace (run `perseus init` to scaffold)

Works on macOS, Linux, and Windows (Git Bash / WSL).
