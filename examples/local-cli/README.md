# Perseus Local CLI Example

The simplest possible Perseus setup — no assistant integration, no containers.
Install Perseus, scaffold a context source, render it, write a checkpoint, ask Pythia.

## What this demonstrates

| Directive / command | What it shows |
|---|---|
| `@date` | Timestamp injected at render time |
| `@env` | Live environment variable |
| `@query` + `@cache session` | Shell command output, cached within one render pass |
| `@waypoint` | Last checkpoint restored into context |
| `@health` | Workspace health snapshot (stale checkpoints, oversized narratives) |
| `@read` | Inline file snippet |
| `perseus checkpoint` | Write a named session waypoint |
| `perseus recover` | Restore the last checkpoint to stdout |
| `perseus suggest` | Ask Pythia which tool or approach to use |
| `perseus doctor` | Run all health checks and get a readiness summary |

## Run it

```bash
# From the repo root
bash examples/local-cli/smoke.sh
```

Or step through manually:

```bash
cd examples/local-cli

# Render the context source to stdout
perseus render .perseus/context.md
```

You'll see something like:

```
# Local CLI Demo — 2026-05-20 14:32 CDT

**Workspace:** /home/user/myproject
**User:** user

---

## Last Session
> No checkpoint found for this workspace yet.

---

## Environment

| Variable | Value |
|---|---|
| Python | Python 3.12.2 |
| Perseus | perseus v1.0.0 |
| Shell | /bin/bash |
| OS | Linux 6.8.0 |

---

## Workspace State

` ` `
a1b2c3d feat: add auth middleware
9e8f7a6 chore: update deps
3c2b1a0 fix: handle empty input
` ` `
...
```

```bash
# Write a checkpoint
perseus checkpoint \
  --task "Exploring Perseus local CLI demo" \
  --status "Smoke test — render works" \
  --next "Try checkpoint and recover" \
  --workspace "$PWD"

# Recover the checkpoint to stdout
perseus recover --workspace "$PWD"

# Ask Pythia for a recommendation
perseus suggest "how do I keep context fresh across sessions" --quick

# Run all readiness checks
perseus doctor
```

## What to try next

**Add a project-specific query:**  
Edit `.perseus/context.md` and add a line like:

```
@query "cat package.json | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[\"name\"], d[\"version\"])'" @cache session
```

**Write multiple checkpoints and watch the narrative grow:**

```bash
perseus checkpoint --task "Feature A" --status "complete" --next "Start feature B"
perseus checkpoint --task "Feature B" --status "in progress" --next "Write tests"
perseus memory update   # Distil checkpoints into a narrative
perseus render .perseus/context.md  # @waypoint now shows the latest
```

**Render to a file instead of stdout:**

```bash
perseus render .perseus/context.md --output live-context.md
cat live-context.md
```

## Notes

- `~/.perseus/config.yaml` is optional for this demo — render, checkpoint, and doctor all work without it.
- The `@query` directives in `context.md` run real shell commands. Adjust them to match your project.
- `@cache session` means the command runs once per render pass — safe for slow or idempotent commands.
- See [docs/quickstart.md](../../docs/quickstart.md) for the full installation walkthrough.
- See [spec/directives.md](../../spec/directives.md) for every available directive.
