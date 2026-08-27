# Wiring Perseus — Live Context for AI Assistants

Perseus resolves project state before an AI assistant sees it. This guide covers supported integration patterns and documents how each one refreshes its context. Freshness is tool-specific: some paths resolve files at invocation time, while remote compatibility and waypoint features can use bounded caches or persisted snapshots.

## Context, memory, and session terms

Perseus resolves and shapes the active working context; Perseus Vault owns durable-memory persistence and recall.

- **Active working context** is the current, task-relevant workspace state — files, services, tasks, and other facts that can change. Perseus resolves and shapes it at render time before the assistant sees it.
- **Durable memory** is information intended to survive session boundaries. Perseus Vault owns its persistence and recall.
- **Recalled memory** is the subset of durable memory returned for a query and shaped into the rendered context. The public `@memory` directive remains the compatibility API name for Vault-backed recall; existing MCP compatibility names remain unchanged.
- **Session history** is Perseus's recent checkpoint and session-digest record. `@waypoint` and `@session` expose it; it is distinct from durable memory. An explicit capture may persist a checkpoint in Perseus Vault as durable memory.

> **Stable launcher for MCP and schedulers:** Use `~/.local/bin/perseus` in shell commands. In JSON/YAML MCP `command` fields, replace `~` with your home directory because exec-style clients do not perform shell expansion. It remains the same install-managed entry point across upgrades instead of pinning a version-specific Python or Library path. Interactive shell commands may use `perseus`; use `command -v perseus` to discover the resolved executable when diagnosing a path problem.

---

## Quick Reference

| Pattern | Command | Refresh |
|---------|---------|---------|
| **One-shot render** | `perseus render .perseus/context.md --output .hermes.md` | Manual |
| **Watch** | `perseus watch` | Auto on file change |
| **Systemd timer** | `~/.local/bin/perseus systemd create … --install --enable` | Every N minutes |
| **Cron** | `~/.local/bin/perseus cron create … --install` | Every N minutes |
| **MCP server** | `~/.local/bin/perseus mcp serve` | Live on tool call |
| **Editor hook** | `perseus install --target claude-code` | Before session start |

---

## 1. MCP server — tool-specific freshness

Most workspace-reading MCP tools resolve their source when called. Remote compatibility tools, waypoint/session data, and explicitly cache-enabled paths can use bounded cached or persisted state. Check each tool's contract in the generated MCP reference before relying on invocation-time freshness.

### stdio (Claude Desktop, Claude Code, Cursor, Codex)

```bash
~/.local/bin/perseus mcp serve
```

Add to your assistant's MCP config:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "perseus": {
      "command": "/Users/yourname/.local/bin/perseus",
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
      "command": "/Users/yourname/.local/bin/perseus",
      "args": ["mcp", "serve"]
    }
  }
}
```

Print the exact config:
```bash
~/.local/bin/perseus mcp config
```

### SSE (loopback integrations)

The built-in SSE listener binds to `127.0.0.1` and accepts only loopback Host headers. Set a bearer token in the protected Perseus config before launch. The server refuses to bind without authentication unless the operator explicitly sets `mcp.allow_no_auth: true`. For multi-machine use, put a separately reviewed authenticated reverse proxy or tunnel in front of the loopback listener; the direct `<host>:8420` path is not supported.

```yaml
mcp:
  sse_bearer_token: "<secret from your secret manager>"
```

```bash
~/.local/bin/perseus mcp serve --transport sse --port 8420
```

A local client sends that token as an `Authorization: Bearer ***` header to `http://127.0.0.1:8420/sse`.

### Current MCP tools

The generated server card is the source of truth for current tool identifiers. Common entries include:

| Tool | Resolves |
|------|----------|
| `perseus_get_context` | Rendered workspace context |
| `perseus_get_health` | Context-maintenance and doctor reports |
| `perseus_read` | Explicitly allowed workspace file content |
| `perseus_list` | Bounded directory entries |
| `perseus_tree` | Bounded directory trees |
| `perseus_vault` | Scoped Perseus Vault recall |
| `perseus_capture` | Session checkpoint capture to Vault; state-mutating and marked destructive/non-read-only |

Use `perseus mcp register` or inspect [the public server card](./.well-known/mcp/server-card.json) for the complete current registry. Do not copy tool names from historical examples.

---

## 2. Editor Hooks — Context Before Every Session

`perseus install` injects Perseus context rendering into your AI assistant's
startup hook, so every new session starts with a rendered context snapshot.

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
~/.local/bin/perseus systemd create .perseus/context.md --output .hermes.md --interval 5m --install --enable
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
~/.local/bin/perseus systemd uninstall .perseus/context.md
```

### Cron (macOS / Linux)

```bash
# Install a crontab entry
~/.local/bin/perseus cron create .perseus/context.md --output .hermes.md --every 5 --install

# Remove
~/.local/bin/perseus cron uninstall .perseus/context.md
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

## 5. Optional LLM-backed directives

Some opt-in suggestion and cited-synthesis directives can call a configured model provider. They are not part of the default local render path. Configure them through the interactive setup, then verify the selected provider explicitly:

```bash
# Interactive setup
perseus quickstart

# Non-interactive setup with environment-based provider detection
perseus quickstart --non-interactive

# Verify the local setup before enabling LLM-backed directives
perseus doctor
```

Review the provider's data path, credential scope, retention, and egress policy before enabling these directives. See [QUICKSTART.md](./QUICKSTART.md) for supported provider configuration.

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
~/.local/bin/perseus systemd create .perseus/context.md \
  --output CLAUDE.md \
  --interval 5m \
  --install --enable

# 4. Verify everything
perseus doctor
perseus doctor --json
perseus pack validate

# 5. Start coding — Claude Code gets fresh context every session
```

For macOS:
```bash
# Replace step 3 with:
~/.local/bin/perseus watch &  # background, or
~/.local/bin/perseus launchd create .perseus/context.md \
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

# Full setup check
perseus doctor

# Directive coverage in your context
perseus render .perseus/context.md --explain

# Permission posture
perseus trust
```

## 9. Optional usage evidence

Perseus Ledger is the separate public product for provenance and usage evidence. Context Engine does not broker provider calls and this guide does not claim automatic or universal savings.

For a bounded local evaluation, install the published Ledger package and inspect its demo before wiring provider usage:

```bash
python -m pip install perseus-ledger==1.2.4
ledger demo
```

Any deployment that records costs or counterfactuals must bind the provider-reported actual usage, model and pricing version, defensible baseline, workspace scope, and evidence hashes in the same event. Estimated context reduction belongs in a separate estimate arm and must not be reported as provider-billed savings.

Some source-level compatibility APIs and configuration keys retain older internal identifiers. They are compatibility contracts, not separate Perseus products. New public integration guidance should use **Perseus Ledger** and its versioned package documentation.
