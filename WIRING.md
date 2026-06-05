# Wiring Perseus — Live Context for AI Assistants

Perseus resolves your project state *before* the AI assistant sees it. This
guide covers every way to wire Perseus into your workflow so context stays
live-loaded — no stale files, no "discover what's running" preambles.

---

## Quick Reference

| Pattern | Command | Refresh |
|---------|---------|---------|
| **One-shot render** | `perseus render .perseus/context.md --output .hermes.md` | Manual |
| **Watch** | `perseus watch` | Auto on file change |
| **Systemd timer** | `perseus systemd create … --install --enable` | Every N minutes |
| **Cron** | `perseus cron create … --install` | Every N minutes |
| **MCP server** | `perseus mcp serve` | Live on tool call |
| **Editor hook** | `perseus install --target claude-code` | Before session start |

---

## 1. MCP Server — Live Tools at Invocation Time

Every MCP tool resolves live workspace state when called — no stale cache, no
pre-computed snapshots.

### stdio (Claude Desktop, Claude Code, Cursor, Codex)

```bash
perseus mcp serve
```

Add to your assistant's MCP config:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve"]
    }
  }
}
```

**Claude Code** or **Cursor** (`.mcp.json` in your project root):
```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["mcp", "serve"]
    }
  }
}
```

Print the exact config:
```bash
perseus mcp config
```

### SSE (remote agents, multi-machine)

```bash
perseus mcp serve --transport sse --port 8420
```

Then point remote assistants at `http://<host>:8420/sse`.

### Available MCP Tools

After wiring, the assistant gets these tools:

| Tool | Resolves |
|------|----------|
| `perseus_render_source` | Full context rendering with all directives |
| `perseus_memory_search` | Mnēmē vault (FTS5 semantic search) |
| `perseus_memory_narrative` | Project narrative |
| `perseus_health_report` | Maintenance suggestions |
| `perseus_oracle_suggest` | Pythia tool/skill recommendations |
| `perseus_synthesize` | Cited synthesis claims across sources |
| `perseus_read_file` | File contents with size guards |
| `perseus_list_directory` | Directory listing |
| `perseus_run_query` | Shell command execution (gated) |
| … and 12+ more | Check `perseus mcp register` for the full registry |

---

## 2. Editor Hooks — Context Before Every Session

`perseus install` injects Perseus context rendering into your AI assistant's
startup hook, so every new session starts with live context.

```bash
# Claude Code
perseus install --target claude-code

# Cursor
perseus install --target cursor

# GitHub Copilot
perseus install --target copilot

# Gemini CLI
perseus install --target gemini-cli
```

**What it does:**
1. Creates `.perseus/context.md` (if missing)
2. Writes a hook that runs `perseus render` before each assistant session
3. The hook produces `.hermes.md` / `CLAUDE.md` / `AGENTS.md` / `.cursorrules`
   depending on the target

**Dry run** — see what files would be written without writing them:
```bash
perseus install --target claude-code --dry-run
```

---

## 3. Live Auto-Refresh — Continuous Context Updates

### Watch (poll-based, zero config)

Watches source files for changes and re-renders on every save. Ideal for
development.

```bash
# Start watching — re-renders .hermes.md whenever .perseus/context.md changes
perseus watch

# Custom source/output
perseus watch --source .perseus/context.md --output CLAUDE.md

# Custom interval
perseus watch --interval 10
```

Runs in the foreground. For background operation, use systemd or cron.

### systemd Timer (Linux, background)

```bash
# Create, install, and enable a systemd timer for every-5-minute refresh
perseus systemd create .perseus/context.md --output .hermes.md --interval 5m --install --enable
```

This creates:
- `~/.config/systemd/user/perseus-render-context.service` — the render job
- `~/.config/systemd/user/perseus-render-context.timer` — the timer

```bash
# Check status
systemctl --user status perseus-render-context.timer

# Manual trigger
systemctl --user start perseus-render-context.service

# Remove
perseus systemd uninstall .perseus/context.md
```

### Cron (macOS / Linux)

```bash
# Install a crontab entry
perseus cron create .perseus/context.md --output .hermes.md --every 5 --install

# Remove
perseus cron uninstall .perseus/context.md
```

---

## 4. Context Packs — Multiple Outputs, One Source

A context pack defines multiple render targets from a single context source,
each formatted for a different assistant.

```bash
# Create a pack for Hermes Agent
perseus init --profile hermes --workspace /path/to/project
```

This creates `.perseus/pack.yaml`:
```yaml
version: 1
assistant: hermes
label: Hermes Agent
source: .perseus/context.md
output: .hermes.md
trust_profile: balanced
```

Once configured, `perseus watch` auto-detects the pack and renders all targets.

**Supported profiles:**
```bash
perseus init --list-profiles
```

| Profile | Output | For |
|---------|--------|-----|
| `hermes` | `.hermes.md` | Hermes Agent |
| `claude-code` | `CLAUDE.md` | Claude Code |
| `codex` | `AGENTS.md` | OpenAI Codex |
| `cursor` | `.cursorrules` | Cursor IDE |
| `rovodev` | `AGENTS.md` | Atlassian Rovo Dev |
| `generic` | `live-context.md` | Any assistant / stdin flow |

**Validate:**
```bash
perseus pack validate
```

**Show summary:**
```bash
perseus pack show
```

---

## 5. LLM Backend — Pythia & Synthesis

Pythia (task suggestions) and Synthesis (cited claims) need an LLM. Quick setup:

```bash
# Interactive (recommended)
perseus quickstart

# Non-interactive with auto-detection
perseus quickstart --non-interactive

# Verify
perseus llm ping
```

See [QUICKSTART.md](./QUICKSTART.md) for Gemini free tier, Groq, and
llama.cpp setup details.

---

## 6. Full Workflow — End-to-End Example

Here's the complete wiring for a project where you use Claude Code and want
live context auto-refreshing every 5 minutes:

```bash
# 1. One-command bootstrap
perseus quickstart

# 2. Wire Claude Code
perseus install --target claude-code

# 3. Set up auto-refresh (Linux)
perseus systemd create .perseus/context.md \
  --output CLAUDE.md \
  --interval 5m \
  --install --enable

# 4. Verify everything
perseus doctor
perseus llm ping
perseus pack validate

# 5. Start coding — Claude Code gets fresh context every session
```

For macOS:
```bash
# Replace step 3 with:
perseus watch &  # background, or
perseus launchd create .perseus/context.md \
  --output CLAUDE.md \
  --interval 300
```

---

## 7. Trust & Security

Perseus defaults to the `balanced` permission profile, which keeps shell
execution disabled. Review and adjust:

```bash
# See what's in effect
perseus trust

# See audit log
perseus trust audit --tail 20

# Switch to power-user (enables shell)
# Add to .perseus/config.yaml:
#   render:
#     allow_query_shell: true
#     allow_agent_shell: true
#     allow_services_command: true
#   trust:
#     allow_query_shell: true
#
# Also set in your environment:
#   export PERSEUS_ALLOW_DANGEROUS=1
```

---

## 8. Verification

```bash
# Full health check
perseus doctor

# LLM reachability
perseus llm ping

# Directive coverage in your context
perseus render .perseus/context.md --explain

# Permission posture
perseus trust
```
