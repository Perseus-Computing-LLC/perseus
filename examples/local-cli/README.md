# Perseus Local CLI Example

The simplest possible Perseus setup. No assistant integration, no containers.

## What this demonstrates

- `perseus render` — resolve directives in a source document
- `perseus checkpoint` / `perseus recover` — session waypoints
- `perseus suggest` — Pythia tool oracle
- `perseus doctor` — readiness probe

## Run it

```bash
# From the repo root
bash examples/local-cli/smoke.sh
```

Or step through manually:

```bash
cd examples/local-cli

# Render the context source
perseus render .perseus/context.md

# Write a checkpoint
perseus checkpoint \
  --task "Exploring Perseus local CLI demo" \
  --status "Running smoke test" \
  --next "Review rendered output" \
  --workspace "$PWD"

# Recover it
perseus recover --workspace "$PWD"

# Ask Pythia
perseus suggest "how do I keep context fresh between sessions" --quick

# Check health
perseus doctor
```

## Notes

- `~/.perseus/config.yaml` is optional for this demo — render, checkpoint, and doctor work without it.
- The `@query` directives in `context.md` run real shell commands. Adjust them to match your project.
- See [docs/quickstart.md](../../docs/quickstart.md) for the full installation walkthrough.
