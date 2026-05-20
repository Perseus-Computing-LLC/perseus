# Perseus Assistant Profile Example

Shows how to use a context pack with an assistant profile. The Hermes profile is used here — swap `profile: hermes` in `pack.yaml` to target Codex, Claude Code, Cursor, or Rovo Dev.

## What this demonstrates

- `perseus init --profile <name>` — scaffold a profile-specific context pack
- `pack.yaml` — context pack manifest with assistant target and output path
- `@memory`, `@agora` directives — project memory and live task board in context
- `perseus pack validate` — validate the manifest

## Run it

```bash
bash examples/assistant-profile/smoke.sh
```

Or step through manually:

```bash
cd examples/assistant-profile

# Validate the pack
perseus pack validate

# Render to the profile output path (.hermes.md for hermes profile)
perseus render .perseus/context.md --output .hermes.md

# Check what was written
cat .hermes.md
```

## Profiles

| Profile | Output path | Target assistant |
|---|---|---|
| `hermes` | `.hermes.md` | Hermes Agent |
| `codex` | `AGENTS.md` | Codex |
| `claude-code` | `CLAUDE.md` | Claude Code |
| `cursor` | `.cursorrules` | Cursor |
| `rovodev` | `AGENTS.md` | Rovo Dev |
| `generic` | `live-context.md` | Any / stdin |

See [`docs/CONTEXT_PACKS.md`](../../docs/CONTEXT_PACKS.md) for the full profile gallery.

## Adapting for your project

1. Change `profile:` in `pack.yaml` to match your assistant.
2. Edit `.perseus/context.md` — add the directives your project needs.
3. Set up auto-refresh with `perseus watch` or `perseus cron`.
