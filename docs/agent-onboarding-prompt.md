# Perseus Agent Onboarding Prompt

Paste this into any fresh LLM chat to bootstrap a Perseus-powered agent
from zero. The agent will self-install, self-configure, and join the
shared checkpoint store so other agents can discover and resume its work.

---

You are being initialized as a Perseus-powered agent. You do not have Perseus
yet. Your first task is to install it, configure it for multi-agent
coordination, and prove you're operational.

## Step 1 — Install Perseus

```bash
pip install perseus
# or from source:
# git clone https://github.com/tcconnally/perseus.git && cd perseus && pip install -e .
```

Verify:
```bash
perseus --version
# Should print: perseus v1.0.2 or later
```

## Step 2 — Configure for shared coordination

Perseus uses `~/.perseus/config.yaml`. Create or update it:

```yaml
render:
  allow_services_command: true
checkpoints:
  store: /workspace/appdata/labyrinth/checkpoints
  ttl_s: 86400
  max_keep: 30
```

If your container has the labyrinth at a different path (e.g.
`/mnt/user/appdata/labyrinth`), use that path instead. The important thing
is that `checkpoints.store` points to the same shared directory every other
Perseus agent uses.

The checkpoint store is lock-protected — `os.O_CREAT | os.O_EXCL` atomic
file lock, NFS-safe. Two agents writing at the same time won't clobber.

## Step 3 — Bootstrap your context document

Create `.perseus/context.md` (or `.hermes.md` if your target assistant is
Hermes) in your workspace root. Start with the minimal template:

```markdown
# Workspace Context — $(date)

@query "whoami"
@query "hostname"
@query "pwd && ls"
@query "git rev-parse --abbrev-ref HEAD 2>/dev/null || echo no-git"
@query "git status --porcelain 2>/dev/null | head -20"
@query "pip freeze 2>/dev/null | grep perseus"
```

## Step 4 — Render and verify

```bash
perseus render .perseus/context.md --output .hermes.md
```

Verify the output:
- No error blocks (Perseus degrades gracefully — a `⚠` warning is fine)
- `@query` directives resolved to real output
- File size is reasonable (shouldn't be megabytes)

## Step 5 — Write your first checkpoint

```bash
perseus checkpoint \
  --task "agent-onboarding" \
  --status "online" \
  --workspace "$(pwd)"
```

This is how other agents discover you. `perseus recover` reads the latest
checkpoint from the shared store and prints the workspace, task, and status
of whoever wrote last.

## Step 6 — Confirm multi-agent visibility

```bash
perseus recover
```

You should see your own checkpoint. If you see someone else's, that means
another agent is already in the shared store — and you can pick up where
they left off.

## What you now have

- **`perseus render`** — resolves `@query`, `@services`, `@skills`,
  `@memory`, `@include` directives into a pre-resolved context document
  your LLM reads at session start instead of making dozens of discovery
  calls.
- **`perseus checkpoint`** — writes your current task/status/workspace
  to the shared store so other agents can resume.
- **`perseus recover`** — reads the latest checkpoint from the shared
  store so you can resume another agent's work without asking the user
  "where were we?"

## If anything fails

- `@query` timeout? The default is 30s. Bump it per-directive:
  `@query "slow-command" timeout=120`
- Stdout too large? `render.max_query_bytes` defaults to 256 KB.
  Output is truncated with a visible marker.
- Lock contention on checkpoint write? The agent retries for ~11s
  then fails gracefully. Try `perseus checkpoint` again.
