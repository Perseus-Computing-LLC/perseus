# Perseus + Claude Code Example

Keep your `CLAUDE.md` always current with Perseus's live context engine.

Claude Code reads `CLAUDE.md` at session start. With Perseus, that file is
rendered from a live source — not hand-edited and forgotten.

## How it works

```
.perseus/context.md   ← your live source (directives, queries, waypoints)
        │
        │  perseus render .perseus/context.md --output CLAUDE.md
        ▼
    CLAUDE.md         ← what Claude Code reads at session start
```

Perseus resolves shell queries, git state, service health, and checkpoint
waypoints before Claude Code ever sees the file. No stale data; no pre-flight
tool calls burning context.

## What this demonstrates

| Directive / command | What it shows |
|---|---|
| `@date` | Timestamp injected at render time |
| `@env` | Live environment variable |
| `@query` + `@cache session` | Shell output (git log, versions) cached within one pass |
| `@waypoint` | Last checkpoint restored into context |
| `@services` | Health checks for local dev servers |
| `@session` | Recent work digest |
| `@health` | Workspace health snapshot |
| `perseus render --output CLAUDE.md` | Write rendered output to the file Claude Code reads |

## Quick start

```bash
# Install Perseus
pip install perseus-ctx

# Render once to bootstrap CLAUDE.md
perseus render .perseus/context.md --output CLAUDE.md

# Open your project in Claude Code — it reads CLAUDE.md automatically
```

## Keep it fresh automatically

Add a cron entry to re-render every 5 minutes so `CLAUDE.md` is always
current before you open a new Claude Code session:

```
*/5 * * * * cd /path/to/your/project && perseus render .perseus/context.md --output CLAUDE.md
```

With `hermes` installed, use the built-in cron integration instead:

```bash
hermes cron add "*/5 * * * *" \
  --script "cd /path/to/your/project && perseus render .perseus/context.md --output CLAUDE.md" \
  --no-agent
```

## Run the smoke test

```bash
bash examples/claude-code/smoke.sh
```

The smoke test renders `.perseus/context.md` → `CLAUDE.md`, verifies the
output contains the expected heading, writes a checkpoint, and runs
`perseus doctor`.

## Adapting for your project

1. **Switch the profile** — edit `.perseus/context.md` and tailor the
   `@query` directives to your stack (Node, Rust, Go, etc.).

2. **Add project-specific queries:**

   ```
   @query "npm test -- --passWithNoTests 2>&1 | tail -5" @cache ttl=300
   @query "cat src/version.ts | grep export" @cache session
   ```

3. **Wire up your services** — update the `@services` block with real
   health-check URLs for your local dev stack.

4. **Build up narrative** — after a few sessions, run:

   ```bash
   perseus memory update
   ```

   Subsequent renders include a distilled project narrative so Claude Code
   always knows what you've been working on.

## Notes

- `CLAUDE.md` is generated output — add it to `.gitignore`.
- The `.perseus/context.md` source file is what you commit and version.
- This same pattern works for any assistant that reads a context file:
  replace `--output CLAUDE.md` with `--output AGENTS.md`, `--output .cursorrules`, etc.
- See [docs/quickstart.md](../../docs/quickstart.md) for the full walkthrough.
- See [docs/HERMES_INTEGRATION.md](../../docs/HERMES_INTEGRATION.md) for the
  Hermes-specific setup (renders to `.hermes.md` automatically).
