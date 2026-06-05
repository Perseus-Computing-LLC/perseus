# Perseus Setup & Configuration Guide
*Model-agnostic · Environment-agnostic · Tested with Hermes Agent, Rovo Dev (Claude Sonnet), Rovo web agent, and Claude Code*

> **Last updated:** 2026-06-03  
> **Perseus version tested:** v1.0.6  
> **Platforms verified:** macOS · Linux · Windows 10 (git-bash) · Docker  
> **Source:** https://github.com/tcconnally/perseus · https://pypi.org/project/perseus-ctx/

---

## What Perseus Is

Perseus is a **compile-before-context engine** — it runs a set of directives in a `.perseus/context.md` file and produces a fully-resolved markdown document that AI assistants read at session start. It is:

- **Deterministic** — same inputs produce the same output
- **Cacheable** — directives can cache results with TTLs
- **Assistant-agnostic** — output is plain markdown; works with any AI (Claude, GPT-4, Gemini, Ollama, etc.)
- **Environment-agnostic** — runs on macOS, Linux, Windows (native git-bash or WSL), Docker, CI/CD pipelines

The key insight: **the AI reads the rendered output, not the directives**. Perseus solves the problem of giving an AI accurate "what is happening right now" context without relying on the AI to go fetch it.

---

## Installation

### Option A — pip / uv (recommended)

```bash
# via uv (fastest, isolated)
uv tool install perseus-ctx

# via pip
pip install perseus-ctx

# verify
perseus --version
```

> **Windows note:** `uv` may warn that `~/.local/bin` is not on your PATH. Add this to your shell rc:
> ```bash
> # bash (~/.bashrc) or zsh (~/.zshrc)
> export PATH="$HOME/.local/bin:$PATH"
> ```
> Restart your terminal or run `source ~/.bashrc` after adding it.

### Option B — pipx

```bash
pipx install perseus-ctx
perseus --version
```

### Option C — from source

```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
pip install -e .
```

---

## Quick Start

```bash
# 1. Initialize a workspace
cd ~/your-project
perseus init

# 2. Render context.md to stdout
perseus render .perseus/context.md

# 3. Render to AGENTS.md (for Hermes Agent, Rovo Dev, Claude Code, etc.)
perseus render .perseus/context.md --output AGENTS.md
```

> **Scaffold quality note:** `perseus init` generates a starter `context.md` with
> `@waypoint`, `@query`, `@skills`, `@services`, and `@session` directives. The
> scaffold is functional but minimal — it includes one example `@services` check and
> a few `@query` probes. After init, you'll want to customize the `@services` block
> with your actual services, replace the example `@query` commands with your own
> helpers (see helper script guidance below), and add `@memory`, `@agora`, `@inbox`,
> and `@health` directives if you need them.
>
> Also check the `@prompt` block — on some versions the final sentence may be
> truncated. A working template with all 11 directives is available in the
> [Context Template section](#context-template-perseuscontextmd).

---

## Directory Structure

```
~/.perseus/                        # Global Perseus home (auto-created)
  config.yaml                      # Global configuration
  pack.yaml                        # Home-workspace pack config
  context.md                       # Home-workspace context template
  checkpoints/                     # Session checkpoint files (YAML)
  cache/                           # Directive output cache
  memory/                          # Mnēmē narrative files (per-workspace)
    <sha256_hash>.md               # Narrative for workspace at that hash
    vault/                         # Backup copies and aliases
  inbox/                           # Inter-agent messages

~/AGENTS.md                        # Rendered output (read by Hermes Agent, Claude Code,
                                   #   Rovo web agent, and any AGENTS.md-compatible tool)
                                   #   Hermes auto-injects this from the working directory
                                   #   at session start (priority: .hermes.md > AGENTS.md > CLAUDE.md)

~/.rovodev/                        # [Rovo Dev users only]
  AGENTS.md                        # Rovo Dev CLI reads this copy
  mcp.json                         # MCP server config (includes Perseus MCP)
```

> **Hermes Agent users:** Hermes scans the working directory for context files at session start
> (`.hermes.md` → `AGENTS.md` → `CLAUDE.md`). Render Perseus output to `AGENTS.md` and it's
> injected automatically — no MCP or hooks needed. For higher priority (overriding other context
> files), render to `.hermes.md` instead.
>
> **Rovo Dev users:** The "two-file problem" — Rovo Dev CLI reads `~/.rovodev/AGENTS.md` while
> the Rovo web agent reads `~/AGENTS.md`. Keep them in sync via the automation section below.
>
> **Cross-platform paths:** All examples below use macOS-style `/Users/yourname/...` paths.
> Substitute as needed:
> - **Windows (git-bash):** `C:/Users/yourname/...` or `/c/Users/yourname/...`
> - **Linux:** `/home/yourname/...`
> - **Docker:** `/opt/data/...` or wherever `$HERMES_HOME` points

---

## Configuration (`~/.perseus/config.yaml`)

### Minimal working config

```yaml
checkpoints_dir: /Users/yourname/.perseus/checkpoints
cache_dir: /Users/yourname/.perseus/cache

memory:
  compaction_threshold: 200

agora:
  task_dir: /Users/yourname/tasks
  default_owner: yourname

render:
  allow_query_shell: true        # ← REQUIRED to enable @query directives
  allow_agent_shell: true        # ← REQUIRED to enable @agent directives
  allow_remote_services_health: true
  allow_services_command: true   # ← REQUIRED to enable command-type service checks
  parallel_services: true
  services_timeout_s: 3

trust:
  allow_query_shell: true        # ← controls audit display only (NOT the render gate)
  allow_outside_workspace: false
  redact_secrets: true
```

> ⚠️ **Critical:** `render.allow_query_shell` and `trust.allow_query_shell` are **separate namespaces**.
> - `render.allow_query_shell` — the actual gate for `@query` directives during render
> - `trust.allow_query_shell` — controls what `perseus trust profile` displays
> - Both must be `true`. Setting only `trust.allow_query_shell` will NOT enable `@query`.
> - See GitHub issue [#129](https://github.com/tcconnally/perseus/issues/129) for full details.
>
> ⚠️ **v1.0.6+ requirement:** `@query`, `@agent`, and `@services command:` directives now also require `PERSEUS_ALLOW_DANGEROUS=1` in the process environment. This is an intentional second gate for security. Add this to your shell rc or prepend it to commands:
> ```bash
> export PERSEUS_ALLOW_DANGEROUS=1
> # or per-command:
> PERSEUS_ALLOW_DANGEROUS=1 perseus render ~/.perseus/context.md --output ~/AGENTS.md
> ```
> If missing, these directives will render as disabled even when `render.allow_query_shell: true`.

### Full annotated config (production)

```yaml
pythia:
  skill_dir: /Users/yourname/rovodev/.agents/skills
  ollama_model: phi3:latest           # local LLM for Pythia (optional)
  llm_timeout_s: 300

hermes:
  sessions_dir: /Users/yourname/.rovodev/sessions

checkpoints_dir: /Users/yourname/.perseus/checkpoints
cache_dir: /Users/yourname/.perseus/cache

memory:
  # llm_provider: ollama              # DISABLED — local models hallucinate; use deterministic
  # llm_model: phi3:latest            # See GitHub issue #131 (compact hangs indefinitely)
  llm_timeout_s: 300
  compaction_threshold: 200
  # narrative_file and mneme_vault_path are legacy fields; current versions use
  # ~/.perseus/memory/<sha256_hash>.md (see Workspace Hash section below)

agora:
  task_dir: /Users/yourname/tasks
  default_owner: yourname

serve:
  host: 127.0.0.1
  port: 7842
  open_browser: false

federation:
  subscriptions:
    - /Users/yourname/project-a
    - /Users/yourname/project-b

trust:
  allow_query_shell: true
  allow_outside_workspace: false
  redact_secrets: true

render:
  allow_query_shell: true            # ← THE authoritative gate for @query
  allow_agent_shell: true
  allow_remote_services_health: true
  allow_services_command: true       # ← REQUIRED for command-type @services checks
  parallel_services: true
  services_timeout_s: 3

update:
  repo_path: /Users/yourname/perseus
  auto: true

llm:
  timeout_s: 300
  model: phi3:latest                 # fallback model for general LLM calls

rovo:
  default_agent: chief-of-staff
  timeout_s: 30
  agents:
    chief-of-staff:
      agent_id: YOUR_AGENT_ID
      cloud_id: YOUR_CLOUD_ID
```

---

## Pack Config (`~/.perseus/pack.yaml` or `<workspace>/.perseus/pack.yaml`)

```yaml
version: 1
name: rovodev-context
profile: rovodev
trust_profile: power-user          # ← use "power-user" to allow @query; "balanced" disables it
renders:
  - name: default
    source: .perseus/context.md
    output: AGENTS.md
    assistant: rovodev
```

> ⚠️ **Critical:** `trust_profile: balanced` in pack.yaml **overrides** `render.allow_query_shell: true`
> in config.yaml, disabling `@query` silently. Always use `power-user` if you need shell queries.
> See GitHub issue [#129](https://github.com/tcconnally/perseus/issues/129).

### Trust profile comparison

| Profile | `@query` | `@agent` | Notes |
|---|---|---|---|
| `strict` | ❌ | ❌ | Read-only renders only |
| `balanced` | ❌ | ❌ | Default for new workspaces |
| `power-user` | ✅ | ✅ | Required for live data queries |

---

## Context Template (`.perseus/context.md`)

### All available directives

```markdown
@perseus v1.0.6

@prompt
Your system prompt goes here. This is injected before the rendered content.
@end

# Session Context
**Rendered:** @date format="YYYY-MM-DD HH:mm z"

## Last Session
@waypoint ttl=86400

## Live Data (shell queries)
@cache ttl=3600
@query "/full/path/to/script.sh" fallback="unavailable"
@end

## Services Health
@services
- name: My Service
  url: http://localhost:8080/health
- name: Docker Container
  docker: my-container-name
- name: CLI Tool
  command: mytool --version 2>&1
@end

## Available Skills
@skills flag_stale=true

## Project Memory
@memory ttl=300

## Recent Sessions
@session count=5 format=digest

> **Note:** `@session` reads from Perseus's own session store (`~/.perseus/sessions/`).
> It does not automatically ingest Hermes Agent sessions, Claude Code sessions, or any
> external session DB. If you see "No recent sessions found" on a system that has sessions
> in another tool, that's expected — use `@waypoint` and `@memory` (via checkpoints) for
> cross-tool session continuity instead.

## Task Board
@agora

## Agent Inbox
@inbox unread=true

## Context Health
@health
```

> **Header version:** Use `@perseus v1.0.6` (the version `perseus init` generates). Older guides
> may show `@perseus v1.0` — both work within v1.x, but always use the version that matches your
> installed Perseus. A mismatched header won't error, but new directive features may not activate.
>
> **Service command gotcha:** Command-type service checks (`command:`) run in Perseus's shell
> context, which may have minimal `PATH` and a different `$HOME` than your interactive shell.
> Use **absolute paths** for executables and avoid relying on `$HOME` expansion. If a service
> shows `⚠ command checks disabled by config`, verify `render.allow_services_command: true`
> in your config — this is separate from `allow_remote_services_health`.
> ```yaml
> # ❌ WRONG — $HOME may expand incorrectly in Perseus's shell
> command: test -d "$HOME/.hermes" && echo "ok"
>
> # ✅ CORRECT — use absolute paths
> command: test -d "/Users/yourname/.hermes" && echo "ok"
> ```

### Critical: Always use full paths in `@query`

When Perseus renders via launchd or any non-interactive shell, `PATH` is minimal.
**Always use absolute paths** for executables in `@query` directives:

```markdown
# ❌ WRONG — will fail in launchd / cron
@query "twg jira workitem query ..." fallback="unavailable"

# ✅ CORRECT — use full path
@query "/Users/yourname/.local/bin/twg jira workitem query ..." fallback="unavailable"

# ✅ CORRECT — use a helper script (recommended for complex queries)
@query "/bin/bash /Users/yourname/scripts/my-query.sh" fallback="unavailable"
```

**Use helper scripts for any `@query` that is not a single command with no pipes.** Even a single pipe through `awk`, `grep`, or `head` can silently trigger the fallback in Perseus's shell context — including seemingly trivial commands like `df -h / | tail -1 | awk '{print $5}'`. If a `@query` fallback triggers and the command works fine in your interactive shell, move it into a helper script. Three real-world examples that failed inline but work perfectly as helpers:

```bash
#!/bin/bash
# ~/scripts/perseus-query-disk.sh — works as helper, fails as inline @query
df -h / | tail -1 | awk '{print "Disk: " $3 "/" $2 " (" $5 " used)"}'
```

```bash
#!/bin/bash
# ~/scripts/perseus-query-uptime.sh — works as helper, fails as inline @query
uptime -p 2>/dev/null || cat /proc/uptime | \
  awk '{d=int($1/86400); h=int(($1%86400)/3600); printf "up %d days, %d hours\n", d, h}'
```

For complex queries:

```bash
#!/bin/bash
# ~/scripts/my-query.sh
/Users/yourname/.local/bin/twg jira workitem query \
  --site hello \
  --jql 'project = MYPROJ AND assignee = currentUser() AND statusCategory != Done' \
  --first 10 \
  -o json 2>/dev/null | \
/usr/bin/python3 -c "
import json, sys
data = json.load(sys.stdin)
for issue in data.get('data', {}).get('issues', []):
    print(f\"- [{issue['key']}] {issue['summary']} [{issue['status']['name']}]\")
"
```

---

### Finding correct absolute paths (containers, Docker, CI)

Container environments have minimal `PATH` and tooling installed by version managers (uv, nvm, asdf) often lives under `~/.local/bin/` rather than system paths like `/usr/local/bin/`. Before writing `@services` or `@query` blocks, run this probe to discover actual binary locations:

```bash
# Run once before wiring — outputs the real paths Perseus will use
for cmd in node python3 git uv docker perseus pip3 npm; do
  found=$(command -v "$cmd" 2>/dev/null || echo "NOT FOUND")
  echo "$cmd → $found"
done
```

> **Real-world gotcha:** In a Docker-based Hermes Agent deployment, `node` was at
> `/home/hermeswebui/.local/bin/node` (installed via uv's node version management),
> not `/usr/local/bin/node` as assumed. The `@services` check for Node showed ❌
> until the correct absolute path was used. Always probe, never assume.

---

## Workspace Hash & Memory

Perseus identifies each workspace by a **12-character SHA256 hex digest** of the resolved absolute path:

```python
import hashlib
from pathlib import Path
workspace = Path("~").expanduser().resolve()
hash = hashlib.sha256(str(workspace).encode()).hexdigest()[:12]
# → e.g. "a7b1f892fc76"
```

The narrative file lives at: `~/.perseus/memory/<hash>.md`

> ⚠️ **Upgrade note (pre-v1.0.3 → v1.0.3+):** Older Perseus versions used **MD5** for workspace hashes.
> If `@memory` returns "No Mnēmē narrative found" after upgrading, you have a hash mismatch.
> See [#128](https://github.com/tcconnally/perseus/issues/128) for the migration workaround.

### Manual migration (MD5 → SHA256)

```python
import hashlib
from pathlib import Path
import shutil

workspace = Path("~").expanduser().resolve()

md5_hash   = hashlib.md5(str(workspace).encode()).hexdigest()[:12]
sha256_hash = hashlib.sha256(str(workspace).encode()).hexdigest()[:12]

old_path = Path(f"~/.perseus/memory/{md5_hash}.md").expanduser()
new_path = Path(f"~/.perseus/memory/{sha256_hash}.md").expanduser()

if old_path.exists() and not new_path.exists():
    shutil.copy(old_path, new_path)
    print(f"Migrated: {old_path} → {new_path}")
    print("Update workspace_hash in frontmatter manually or run: perseus memory update")
else:
    print(f"old={old_path.exists()} new={new_path.exists()} — check manually")
```

---

## Memory Management

### Initialize / update narrative (deterministic — no LLM)

```bash
# First time or after writing new checkpoints
perseus memory update

# Show current narrative
perseus memory show

# Check status
perseus memory status
```

### LLM-based narrative (optional — use with caution)

> ⚠️ **Warning:** Local models (Ollama/phi3) hallucinate names, dates, and facts in narratives.
> The recommended approach is **deterministic mode** (no `llm_provider` set in config).
> Only enable LLM narrative if you are using a high-quality hosted model (GPT-4o, Claude 3.5+).

```yaml
# config.yaml — to enable LLM narrative synthesis
memory:
  llm_provider: openai-compat        # or: ollama, llamacpp, hermes, daedalus
  llm_model: gpt-4o                  # use a capable model
  llm_timeout_s: 120
```

> ⚠️ `perseus memory compact` hangs indefinitely with slow models. See [#131](https://github.com/tcconnally/perseus/issues/131).
> If using LLM, always set `llm_timeout_s` and be prepared to kill the process.

> ⚠️ `perseus memory update --llm none` crashes. See [#130](https://github.com/tcconnally/perseus/issues/130).
> To force deterministic mode: omit `--llm` flag (leave `llm_provider` unset in config).

### Writing checkpoints (the right way)

Checkpoints feed the deterministic narrative. Write one at the end of every significant session:

```bash
cat > ~/.perseus/checkpoints/$(date +%Y%m%dT%H%M%S).yaml << 'EOF'
version: 1
written: "2026-06-03T15:30:00-05:00"
stale_after: "2026-06-04T15:30:00-05:00"
workspace: /Users/yourname              # absolute path, no ~
status: completed                       # or in_progress
task: "Brief one-line description"
next: |
  - Follow-up action 1
  - Follow-up action 2
notes: |
  Full narrative paragraph. What was done, what was found, decisions made,
  Confluence URLs, Jira keys, Slack threads for traceability.
EOF

# Then merge into narrative
perseus memory update
```

---

## Wiring to AI Assistants

Perseus output is plain markdown — it works with any AI tool that reads a context file.
The most common wiring patterns:

### Hermes Agent (auto-injection)

Hermes automatically scans for context files at session start:

```
Priority: .hermes.md → AGENTS.md → CLAUDE.md → .cursorrules
```

**No configuration needed** — render Perseus to `AGENTS.md` (or `.hermes.md` for higher
priority) and Hermes injects it automatically. This is the simplest wiring path.

```bash
# Render to AGENTS.md (Hermes reads this from the working directory)
perseus render ~/.perseus/context.md --output ~/AGENTS.md

# Or render to .hermes.md for higher priority (overrides other context files)
perseus render ~/.perseus/context.md --output ~/.hermes.md
```

Set up a recurring render job (see Automation section below) to keep it fresh.

#### Hermes + Perseus MCP (22 callable tools)

In addition to AGENTS.md auto-injection, Hermes can wire Perseus as an MCP server — giving AI agents direct access to all 22 Perseus tools (`perseus_memory`, `perseus_services`, `perseus_query`, etc.) without re-rendering the context file. Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  perseus:
    command: /home/yourname/.local/bin/perseus   # Linux/Docker; use /Users/… on macOS
    args:
      - mcp
      - serve
      - --workspace
      - /home/yourname                           # absolute path, no ~
    enabled: true
```

> **Config write protection:** Hermes protects `~/.hermes/config.yaml` from direct
> file writes by AI tools for security. Edit it in your terminal or use
> `hermes config set` — the AI can provide the YAML block above, but you'll paste
> it yourself.
>
> **Verification:** After adding the MCP server, restart Hermes or trigger a config
> reload. Smoke-test with:
> ```bash
> echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | \
>   timeout 3 /home/yourname/.local/bin/perseus mcp serve --workspace /home/yourname
> ```

### Claude Code (hooks-based injection)

```bash
cd your-project
perseus install --target claude-code
```

This creates `SessionStart` + `UserPromptSubmit` hooks in `.claude/settings.json` that auto-render context before every session.

### Rovo Dev CLI (`.rovodev/config.yml`)

Add Perseus MCP to your MCP config at `~/.rovodev/mcp.json`:

```json
{
  "mcpServers": {
    "perseus": {
      "command": "/Users/yourname/Library/Python/3.13/bin/perseus",
      "args": ["mcp", "serve", "--workspace", "/Users/yourname"]
    }
  }
}
```

Perseus also auto-renders AGENTS.md at session start if the launchd job is configured (see below).

### Claude Desktop / Cursor / Continue

```bash
# Print MCP client config for your editor
perseus mcp config

# Or use the MCP server directly in any MCP-compatible client:
# command: perseus mcp serve --workspace /path/to/workspace
```

---

## Automation

Keep AGENTS.md fresh with a recurring render job. Choose the approach that fits your platform.

### Hermes Cronjob (recommended — works everywhere Hermes runs)

If you're already using Hermes Agent, its built-in cron scheduler is the simplest option:

**1. Create the render script** at `~/.hermes/scripts/perseus-render.sh`:

```bash
#!/bin/bash
# Silent on success, alerts on failure (designed for no_agent=true cron)
export PATH="$HOME/.local/bin:$PATH"
PERSEUS_ALLOW_DANGEROUS=1 perseus render "$HOME/.perseus/context.md" --output "$HOME/AGENTS.md" >/dev/null 2>&1
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo "Perseus render FAILED (exit $exit_code)"
    exit 1
fi
exit 0
```

**2. Create the cron job** (from a Hermes session or via `hermes cron create`):

```bash
hermes cron create "every 30m" \
  --name "Perseus context render" \
  --script perseus-render.sh \
  --no-agent
```

Or via the `cronjob` tool from within Hermes: `cronjob(action='create', schedule='every 30m', script='perseus-render.sh', no_agent=true, name='Perseus context render')`

**3. Verify:**

```bash
hermes cron list | grep perseus
```

> **Why `no_agent=true`:** The render script is a simple shell command — no LLM needed.
> Empty stdout = silent (no delivery to user). Non-zero exit = error alert.
> This is the "watchdog pattern" — silent when healthy, loud when broken.

### Windows Task Scheduler

On Windows without Hermes cron:

```powershell
# PowerShell (run as Administrator)
$Action = New-ScheduledTaskAction -Execute "bash" `
  -Argument "-c `"$env:USERPROFILE\.local\bin\perseus render $env:USERPROFILE\.perseus\context.md --output $env:USERPROFILE\AGENTS.md`""
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "Perseus Render" -Action $Action -Trigger $Trigger `
  -Description "Render Perseus context every 30 minutes"
```

Or via GUI: `taskschd.msc` → Create Basic Task → Trigger: Daily, repeat every 30 minutes → Action: Start a program → `bash` with argument `-c "~/.local/bin/perseus render ~/.perseus/context.md --output ~/AGENTS.md"`

### launchd (macOS)

Create `~/Library/LaunchAgents/com.yourname.perseus.render.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourname.perseus.render</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/sh</string>
        <string>-c</string>
        <string>/Users/yourname/.local/bin/perseus render /Users/yourname/.perseus/context.md --output /Users/yourname/AGENTS.md</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/yourname/logs/perseus-render.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yourname/logs/perseus-render.err.log</string>
</dict>
</plist>
```

> **Rovo Dev users:** If you need to sync two copies (Rovo Dev reads `~/.rovodev/AGENTS.md`
> while the web agent reads `~/AGENTS.md`), add `&& cp ~/AGENTS.md ~/.rovodev/AGENTS.md`
> to the render command.

Load the job:
```bash
launchctl load ~/Library/LaunchAgents/com.yourname.perseus.render.plist
```

### systemd (Linux)

```ini
# ~/.config/systemd/user/perseus-render.service
[Unit]
Description=Perseus context render

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/home/yourname/.local/bin/perseus render /home/yourname/.perseus/context.md --output /home/yourname/AGENTS.md'

# ~/.config/systemd/user/perseus-render.timer
[Unit]
Description=Perseus render every 30 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable --now perseus-render.timer
```

### cron (universal)

```bash
crontab -e
# Add:
*/30 * * * * /full/path/to/perseus render /home/yourname/.perseus/context.md --output /home/yourname/AGENTS.md
```

---

## EOD Workflow — Perseus Checkpoint

At the end of every significant work session or EOD intelligence sweep:

**1. Write a checkpoint:**

```bash
cat > ~/.perseus/checkpoints/$(date +%Y%m%dT%H%M%S).yaml << 'EOF'
version: 1
written: "TIMESTAMP"
stale_after: "TIMESTAMP+24h"
workspace: /Users/yourname
status: completed
task: "EOD Customer Intelligence Sweep — RTX & SpaceX"
next: |
  - Top follow-up action 1
  - Top follow-up action 2
notes: |
  Scope: [what was swept]. Key findings: [bullet per customer].
  Actions taken: Confluence page at [URL], Jira tickets [keys], Slack [channel].
EOF
```

Or ask your AI CoS: *"Write a Perseus checkpoint for this session"* — it will draft `notes` and `next` from the conversation.

**2. Merge into Mnēmē:**

```bash
perseus memory update
```

**3. Verify:**

```bash
perseus memory status
# Should show updated timestamp and new checkpoint count
```

---

## MCP Server Mode

Perseus can run as an MCP server, exposing all directives as callable tools:

```bash
# Start the server (stdio, JSON-RPC 2.0)
perseus mcp serve --workspace /path/to/workspace

# Print config for Claude Desktop / Cursor
perseus mcp config
```

Available MCP tools: `perseus_query`, `perseus_services`, `perseus_memory`, `perseus_waypoint`, `perseus_agora`, `perseus_inbox`, `perseus_health`, `perseus_session`, and more.

---

## Troubleshooting

### `@query` shows "disabled by config" even though `trust.allow_query_shell: true`

**Cause:** Two separate config namespaces. `trust.allow_query_shell` is for audit display; `render.allow_query_shell` is the actual gate.

**Fix:** Add to `config.yaml`:
```yaml
render:
  allow_query_shell: true
  allow_agent_shell: true
```

Also check `pack.yaml` — `trust_profile: balanced` overrides both. Use `power-user`.

See [#129](https://github.com/tcconnally/perseus/issues/129).

---

### `@services` command checks show "disabled by config"

**Cause:** `render.allow_services_command` is separate from `render.allow_remote_services_health`.
`allow_remote_services_health` only gates HTTP health checks (`url:`); `allow_services_command`
gates shell-command checks (`command:`).

**Fix:** Add to `config.yaml` under `render:`:
```yaml
render:
  allow_services_command: true    # ← missing from many config templates
```

---

### `@memory` shows "No Mnēmē narrative found" after running `memory update`

**Cause:** The `@memory` directive cached the "not found" result from a previous render
(before you ran `memory update`). The cache TTL hasn't expired yet.

**Fix:** Clear the stale cache and re-render. During initial setup (when you're actively writing checkpoints and running `memory update`), the safest approach is to clear all cache files — the grep approach may miss entries where the cache format differs:

```bash
# Option A: Clear all caches (recommended during initial setup)
rm -f ~/.perseus/cache/*.json
perseus render ~/.perseus/context.md --output ~/AGENTS.md

# Option B: Targeted approach — find and remove only the stale entry
grep -l "No Mn.*m.* narrative\|not found" ~/.perseus/cache/*.json 2>/dev/null | xargs rm -f
perseus render ~/.perseus/context.md --output ~/AGENTS.md
```

> **Prevention:** During initial setup, use a low TTL on `@memory` so stale caches expire quickly:
> ```markdown
> @memory ttl=60    # 1 minute while you're still configuring
> ```
> Increase to `ttl=300` or higher once your Mnēmē narrative stabilizes.

---

### `@memory` returns "No Mnēmē narrative found" after upgrade

**Cause:** Workspace hash algorithm changed from MD5 (older versions) to SHA256 (v1.0.3+).

**Fix:** Compute both hashes and copy the file:
```python
import hashlib, shutil
from pathlib import Path
ws = Path("~").expanduser().resolve()
old = Path(f"~/.perseus/memory/{hashlib.md5(str(ws).encode()).hexdigest()[:12]}.md").expanduser()
new = Path(f"~/.perseus/memory/{hashlib.sha256(str(ws).encode()).hexdigest()[:12]}.md").expanduser()
if old.exists() and not new.exists():
    shutil.copy(old, new)
    print(f"Migrated: {old.name} → {new.name}")
```
Then update `workspace_hash` in the frontmatter and run `perseus memory update`.

See [#128](https://github.com/tcconnally/perseus/issues/128).

---

### `@memory focus=recent` shows "section not found"

**Cause:** The narrative was generated deterministically and doesn't have a `## Recent Activity` heading yet.

**Fix:** Remove `focus=recent` to show the full narrative:
```markdown
@memory ttl=300    # no focus= modifier
```

See [#135](https://github.com/tcconnally/perseus/issues/135).

---

### `perseus memory compact` hangs indefinitely

**Cause:** Ollama/phi3 is slow and there's no timeout enforcement in the CLI.

**Fix:** Kill the process (`Ctrl+C` or `kill PID`), disable `llm_provider` in config, and use deterministic mode.

See [#131](https://github.com/tcconnally/perseus/issues/131).

---

### `@query` fallback triggers even though the command works interactively

**Cause:** launchd / cron environments have minimal `PATH`. The executable is not found.

**Fix:** Use full absolute paths in `@query` and in all scripts called by `@query`:
```markdown
# Use full path
@query "/Users/yourname/.local/bin/mycommand arg1 arg2" fallback="unavailable"
```

---

### `~/AGENTS.md` is stale — AI sees old context

**Cause:** The render job (cron, launchd, Task Scheduler) isn't running, or the output path is wrong.

**Fix:** Verify the render job is active and writing to the correct path:
```bash
# Check when AGENTS.md was last updated
ls -la ~/AGENTS.md

# Run a manual render to confirm it works
perseus render ~/.perseus/context.md --output ~/AGENTS.md

# Check your cron/scheduler status
# Hermes:  hermes cron list | grep perseus
# macOS:   launchctl list | grep perseus
# Linux:   systemctl --user status perseus-render.timer
# Windows: Get-ScheduledTask -TaskName "Perseus Render" | Select State
```

**Rovo-specific:** If Rovo Dev CLI reads `~/.rovodev/AGENTS.md` but you're only rendering to
`~/AGENTS.md`, add `&& cp ~/AGENTS.md ~/.rovodev/AGENTS.md` to your render command.

---

## Known Issues (as of v1.0.6)

| # | Type | Summary |
|---|---|---|
| [#128](https://github.com/tcconnally/perseus/issues/128) | 🐛 Bug | MD5→SHA256 hash migration breaks `@memory` silently on upgrade |
| [#129](https://github.com/tcconnally/perseus/issues/129) | 🐛 Bug | `trust_profile: balanced` silently disables `@query` despite global config |
| [#130](https://github.com/tcconnally/perseus/issues/130) | 🐛 Bug | `memory update --llm none` crashes with RuntimeError |
| [#131](https://github.com/tcconnally/perseus/issues/131) | 🐛 Bug | `memory compact` hangs indefinitely with slow Ollama models |
| [#132](https://github.com/tcconnally/perseus/issues/132) | ✨ Feature | `perseus memory migrate` command for hash migration |
| [#133](https://github.com/tcconnally/perseus/issues/133) | ✨ Feature | `--deterministic` flag for `memory update` and `memory compact` |
| [#134](https://github.com/tcconnally/perseus/issues/134) | 📖 Docs | Document `render:` vs `trust:` config namespace distinction |
| [#135](https://github.com/tcconnally/perseus/issues/135) | ✨ Feature | `@memory focus=recent` fallback when section not found |

---

## Quick Reference Card

```bash
# Install
uv tool install perseus-ctx
# Windows: add ~/.local/bin to PATH (see Installation section)

# Initialize a workspace
cd ~/my-project && perseus init

# Render context to AGENTS.md (Hermes, Claude Code, Rovo web agent)
# Requires PERSEUS_ALLOW_DANGEROUS=1 for @query, @agent, @services command: directives
PERSEUS_ALLOW_DANGEROUS=1 perseus render ~/.perseus/context.md --output ~/AGENTS.md
perseus render ~/.perseus/context.md --output ~/AGENTS.md

# Render to .hermes.md (Hermes high-priority context)
perseus render ~/.perseus/context.md --output ~/.hermes.md

# Check trust/permissions
perseus trust profile
perseus doctor

# Write a checkpoint (cross-platform date format)
cat > ~/.perseus/checkpoints/$(date +%Y%m%dT%H%M%S).yaml << 'EOF'
version: 1
written: "2026-06-03T14:30:00-05:00"
stale_after: "2026-06-04T14:30:00-05:00"
workspace: /home/yourname          # macOS: /Users/yourname · Windows: C:\Users\yourname
status: completed
task: "Session description"
next: |
  - Follow-up action 1
notes: |
  What was done, decisions made, URLs for traceability.
EOF

# Update Mnēmē narrative (deterministic)
perseus memory update

# Show narrative
perseus memory show

# Memory status
perseus memory status

# MCP server
perseus mcp serve --workspace ~

# Hermes cronjob (automated render every 30 min)
hermes cron create "every 30m" --name "Perseus render" --script perseus-render.sh --no-agent

# Health check
perseus health
perseus doctor
```

---

*Built from production experience wiring Perseus v1.0.6 into Hermes Agent, Rovo Dev CLI, and Rovo web agent.*  
*Issues filed: [#128](https://github.com/tcconnally/perseus/issues/128) – [#135](https://github.com/tcconnally/perseus/issues/135)*  
*Guide maintained at: `~/rovodev/docs/perseus-setup-guide.md` (canonical) · this copy: `~/Downloads/perseus-setup-guide.md`*
