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

Use the published package unless you are actively contributing from a source checkout. Prefer verifying the resolved binary path after install:

```bash
which perseus
perseus --version
```

If you previously used the legacy `scripts/install.sh` shim installer, remove the old shim before switching to `perseus-ctx`:

```bash
rm -f ~/.local/bin/perseus
rm -f ~/.local/share/perseus/perseus.py
```

**Recommended — package install:**

```bash
# fast isolated install
uv tool install perseus-ctx

# or standard pip install
pip install perseus-ctx

which perseus
perseus --version
```

**Alternative — contributor source checkout:**

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git
cd perseus
pip install -e .
which perseus
perseus --version
```

> `./scripts/install.sh` still exists for compatibility, but package install is the preferred path for most users.

---

## 3. Configure

Create a minimal config at `~/.perseus/config.yaml`:

```bash
mkdir -p ~/.perseus
```

```yaml
# ~/.perseus/config.yaml
# ⚠ CRITICAL: render.allow_query_shell must be true for @query to work.
# trust.allow_query_shell controls audit display only — NOT the render gate.
render:
  allow_query_shell: true        # ← REQUIRED to enable @query directives
  allow_agent_shell: true        # ← REQUIRED to enable @agent directives
  allow_remote_services_health: true
  allow_services_command: true   # ← REQUIRED for command-type @services checks
  parallel_services: true
  services_timeout_s: 3

trust:
  allow_query_shell: true        # controls audit display only
  allow_outside_workspace: false
  redact_secrets: true

# Optional: assistant integration (Hermes Agent)
pythia:
  skill_dir: ~/.hermes/skills
assistant:
  sessions_dir: ~/.hermes/sessions
```

> **Note:** Starting with v1.0.6, `@query`, `@agent`, and `@services command:` also require `PERSEUS_ALLOW_DANGEROUS=1` in your environment. See the [Setup & Configuration Guide](../SETUP-GUIDE.md) for full details.

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

See [docs/DIRECTIVES.md](./DIRECTIVES.md) for the full directive reference.

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
| All directives | [docs/DIRECTIVES.md](./DIRECTIVES.md) |
| Wiring to your assistant | [spec/integration.md](../spec/integration.md) |
| Context packs and profiles | [docs/CONTEXT_PACKS.md](./CONTEXT_PACKS.md) |
| Trust and permissions | [docs/PRODUCT_CONTRACT.md](./PRODUCT_CONTRACT.md) |
| Container deployment | [docs/CONTAINER.md](./CONTAINER.md) |
| Cited synthesis | [docs/CITED_SYNTHESIS.md](./CITED_SYNTHESIS.md) |
| Real-world examples | [docs/EXAMPLES.md](./EXAMPLES.md) |
| 30-second install | [QUICKSTART.md](../QUICKSTART.md) |
