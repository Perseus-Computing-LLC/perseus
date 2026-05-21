# Perseus™ Quickstart

Get from zero to a live rendered context in under 5 minutes.

---

## 1. Prerequisites

- Python **3.10+**
- `pyyaml` — the only runtime dependency

```bash
python3 -m pip install --user pyyaml
```

---

## 2. Install

**Recommended — installer script:**

```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
./scripts/install.sh
```

This puts `perseus` on `~/.local/bin/`. Make sure that's on your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"   # add to ~/.bashrc or ~/.zshrc
perseus --version                       # should print: perseus v1.0.0
```

**Alternative — run directly from the repo:**

```bash
python3 perseus.py --version
```

---

## 3. Configure

Create a minimal config at `~/.perseus/config.yaml`:

```bash
mkdir -p ~/.perseus
```

```yaml
# ~/.perseus/config.yaml
pythia:
  skill_dir: ~/.hermes/skills       # optional: your Hermes skills directory
assistant:
  sessions_dir: ~/.hermes/sessions  # optional: your Hermes session logs
```

> **Note:** These fields are only needed if you're using Hermes Agent for `@skills` and
> `@session` directives. Leave them unset if you're using a different assistant — the
> renderer, checkpoints, and Pythia all work without them.

---

## 4. Scaffold your first context pack

Pick the profile that matches your assistant:

```bash
perseus init --list-profiles
```

```
Profile       Assistant target   Output file        Trust
─────────────────────────────────────────────────────────────
generic       Any / stdin        live-context.md    balanced
hermes        Hermes Agent       .hermes.md         balanced
codex         Codex              AGENTS.md          balanced
claude-code   Claude Code        CLAUDE.md          balanced
cursor        Cursor             .cursorrules       balanced
rovodev       Rovo Dev           AGENTS.md          balanced
```

Scaffold with the right profile for your workspace:

```bash
cd /path/to/your/project
perseus init --profile hermes    # or codex, claude-code, cursor, rovodev, generic
```

This writes:
- `.perseus/context.md` — your live context source (edit this)
- `.perseus/pack.yaml` — the context pack manifest

---

## 5. Edit the context source

Open `.perseus/context.md`. It's a standard `.md` file beginning with `@perseus`. Add any directives you need:

```markdown
@perseus v0.4

@prompt
This document was rendered live by Perseus. All values below are current.
@end

# Context — @date format="YYYY-MM-DD HH:mm z"

## Last Session
@waypoint ttl=86400

## What's Running
@query "docker ps --format 'table {{.Names}}\t{{.Status}}'" @cache ttl=60

## Environment
@env NODE_ENV fallback="development"
@read .env key="API_PORT" fallback="3001"

## Available Skills
@skills flag_stale=true
```

See [spec/directives.md](../spec/directives.md) for the full directive reference.

---

## 6. Render

```bash
perseus render .perseus/context.md
```

The rendered output goes to stdout (or to the profile's output file with `--output`). Directives are replaced with their resolved values — the assistant only ever sees a finished markdown document.

To write the output directly:

```bash
perseus render .perseus/context.md --output .hermes.md
```

---

## 7. Keep it fresh

### Option A — Watch mode (simplest, foreground)

```bash
perseus watch .perseus/context.md --output .hermes.md
```

Re-renders whenever the source file changes.

### Option B — Cron (background, periodic)

```bash
# Print a crontab entry
perseus cron .perseus/context.md --output .hermes.md --every 5

# Install it (macOS/Linux)
perseus cron .perseus/context.md --output .hermes.md --every 5 --install
```

### Option C — systemd / launchd

```bash
perseus systemd .perseus/context.md --output .hermes.md   # Linux
perseus launchd .perseus/context.md --output .hermes.md   # macOS
```

---

## 8. Write checkpoints

At natural pause points, write a checkpoint so the next session recovers instantly:

```bash
perseus checkpoint \
  --task "Adding webhook handler" \
  --status "resolver written, tests pending" \
  --next "run pytest tests/test_webhook.py" \
  --workspace "$PWD"
```

Recover in the next session:

```bash
perseus recover --workspace "$PWD"
```

---

## 9. Ask Pythia

When you're not sure which tool or approach to use:

```bash
perseus suggest "best way to debug a memory leak in a Node.js service"
```

Pythia assembles a live snapshot of your environment (skills, services, recent work) and ranks paths for you. No API call needed — you and your assistant are the oracle.

---

## 10. Check health

```bash
perseus doctor
```

10 checks: config, context file, render settings, checkpoint age, Mnēmē narrative, federation, oracle log, serve endpoint, directive registry, version. Exit 0 = all ok/warn; exit 1 = any error.

---

## What's next

| Topic | Link |
|---|---|
| All directives | [spec/directives.md](../spec/directives.md) |
| Wiring to your assistant | [spec/integration.md](../spec/integration.md) |
| Context packs and profiles | [docs/CONTEXT_PACKS.md](./CONTEXT_PACKS.md) |
| Trust and permissions | [spec/components.md](../spec/components.md) |
| Container deployment | [docs/CONTAINER.md](./CONTAINER.md) |
| Cited synthesis | [docs/CITED_SYNTHESIS.md](./CITED_SYNTHESIS.md) |
| Real-world examples | [docs/EXAMPLES.md](./EXAMPLES.md) |
