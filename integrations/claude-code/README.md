# Perseus Context Engine hook for Claude Code

This hook renders current workspace context before a Claude Code session.

## Install from a reviewed checkout

Clone or check out the repository revision you intend to trust, inspect the hook, then install that checked-in file:

```bash
mkdir -p .claude/hooks
install -m 0755 integrations/claude-code/on_session_start.sh \
  .claude/hooks/on_session_start.sh
```

Do not download and execute a mutable `main`-branch script.

## What happens

The hook reads `.perseus/context.md`, resolves the enabled directives, and writes the rendered artifact to `CLAUDE.md`. Shell and network directives remain subject to the Context Engine security gates and run with the current user's permissions when enabled.

## Verify

```bash
bash .claude/hooks/on_session_start.sh
sed -n '1,20p' CLAUDE.md
```

## Requirements

- `python -m pip install perseus-ctx==1.0.26` available on `PATH`
- The hook deliberately does not execute a workspace-local `perseus.py`; contributors who run from source must install a reviewed wrapper outside the target workspace and place it on `PATH`
- `.perseus/context.md` in the workspace (`perseus quickstart` creates it)

The hook supports macOS and Linux. On Windows, use WSL or another environment that can execute the reviewed shell script.
