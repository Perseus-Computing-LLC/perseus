# Perseus Assistant Profile Example

Shows how to use a context pack with an assistant profile. The Hermes profile is used
here — swap `profile: hermes` in `pack.yaml` to target Codex, Claude Code, Cursor, or
any other assistant.

## What this demonstrates

| Feature | What it shows |
|---|---|
| `pack.yaml` | Context pack manifest — controls profile, output path, and render settings |
| `perseus init --profile` | Scaffold a profile-specific context source from a template |
| `@memory` | Project narrative distilled from accumulated checkpoints |
| `@agora` | Live task board — open and in-progress tasks injected at render time |
| `@services` | Running service health pinged at render time |
| `@health` | Workspace health snapshot |
| `perseus pack validate` | Validate the pack manifest before rendering |
| Profile routing | How Perseus maps `profile: hermes` → `.hermes.md`, `profile: cursor` → `.cursorrules`, etc. |

## Run it

```bash
bash examples/assistant-profile/smoke.sh
```

Or step through manually:

```bash
cd examples/assistant-profile

# Validate the pack manifest
perseus pack validate

# Render to the profile output path
# (hermes profile → .hermes.md)
perseus render .perseus/context.md --output .hermes.md

# Inspect the rendered output
cat .hermes.md
```

## Profiles

| Profile | Output path | Target assistant | Notes |
|---|---|---|---|
| `hermes` | `.hermes.md` | Hermes Agent | Loaded as project context at session start |
| `codex` | `AGENTS.md` | OpenAI Codex | Codex reads `AGENTS.md` from the repo root |
| `claude-code` | `CLAUDE.md` | Claude Code | Claude Code reads `CLAUDE.md` at session start |
| `cursor` | `.cursorrules` | Cursor | Cursor reads `.cursorrules` from the project root |
| `rovodev` | `AGENTS.md` | Rovo Dev | Rovo Dev reads `AGENTS.md` at session start |
| `generic` | `live-context.md` | Any / stdin | Pass to any assistant via `< live-context.md` or file attachment |

## Adapting for your project

**Switch the target assistant:**
```yaml
# pack.yaml
profile: claude-code   # was hermes — now writes CLAUDE.md instead of .hermes.md
```

**Add project-specific directives to `.perseus/context.md`:**
```
## Test Coverage
@query "python3 -m pytest --tb=no -q 2>&1 | tail -2" @cache session

## Dependencies
@query "pip list --outdated 2>/dev/null | head -10" @cache session
```

**Set up automatic refresh so the output file stays current:**
```bash
# Refresh every 30 minutes via cron
perseus cron --schedule "*/30 * * * *" \
  --source .perseus/context.md \
  --output .hermes.md
```

**Build up the project narrative over time:**
```bash
# Write checkpoints as you work — Mnēmē distils them into @memory
perseus checkpoint \
  --task "Implement auth" \
  --status "complete" \
  --next "Write integration tests"

perseus memory update  # Distil into narrative
perseus render .perseus/context.md --output .hermes.md  # Refresh output
```

## Notes

- The output file (`.hermes.md`, `CLAUDE.md`, `.cursorrules`, etc.) is a rendered snapshot — **commit it only if your assistant reads from the repo**. Most workflows run `perseus render` on session start instead.
- `@memory` requires at least one checkpoint to produce output. Run `perseus checkpoint` a few times to see it populate.
- `@agora` requires an Agora task board — run `perseus agora init` to create one.
- See [`docs/CONTEXT_PACKS.md`](../../docs/CONTEXT_PACKS.md) for the full profile gallery and pack manifest reference.
