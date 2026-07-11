# Tooltrim + Perseus Integration

Reduces Perseus's skill list from 76 tools to a task-relevant subset using
[tooltrim](https://github.com/false200/tooltrim), an MCP proxy that filters
and shrinks tool metadata.

## Why

Perseus's `@skills` directive lists all 76 available skills at session start.
That's 4,591 tokens of tool metadata before the first prompt. Tooltrim filters
this to what the agent actually needs for the current task.

## Results (tested 2026-06-13)

| Mode | Tools | Tokens | Savings |
|---|---|---|---|
| No filter | 76 | 4,591 | baseline |
| Shrink only | 76 | 4,306 | 6.2% |
| Common (core+devops+github+swdev) | 53 | 3,010 | 34.4% |
| **Task (core + key tools)** | **13** | **704** | **84.7%** |

## Quick Start

```bash
# 1. Install tooltrim
npm install -g tooltrim

# 2. Copy config
cp integrations/tooltrim/tooltrim.perseus.yaml ./tooltrim.config.yaml

# 3. Edit filters for your task (see comments in config)

# 4. Add tooltrim as your MCP proxy
# In .cursor/mcp.json, claude_desktop_config.json, or .hermes/mcp.json:
{
  "mcpServers": {
    "tooltrim": {
      "command": "npx",
      "args": ["-y", "tooltrim"]
    }
  }
}

# 5. Start your session — Perseus skills are now filtered
perseus render .perseus/context.md
```

## Assistant Wiring

Tooltrim is an MCP proxy: you point your assistant at tooltrim, and tooltrim
points at the real Perseus (and/or Perseus Vault) server upstream. Wiring
differs slightly per host.

### Claude Desktop / Cursor / Codex

Add tooltrim as the MCP server (see Quick Start above) — these hosts read a
single `mcpServers` map and tooltrim proxies whatever you list under `servers:`
in `tooltrim.config.yaml`.

### Rovo Dev (Atlassian `acli rovodev`)

Rovo Dev reads user-declared MCP servers from `~/.rovodev/mcp.json` and gates
them via `allowedMcpServers` in `~/.rovodev/config.yml`. To put a server behind
tooltrim, replace the *direct* stdio entry (e.g. `perseus mcp serve`) with a
tooltrim proxy entry whose upstream is that server.

`~/.rovodev/mcp.json` — declare tooltrim instead of perseus directly:

```json
{
  "mcpServers": {
    "tooltrim": {
      "command": "npx",
      "args": ["-y", "tooltrim"]
    }
  }
}
```

`~/.rovodev/config.yml` — allow the tooltrim server:

```yaml
allowedMcpServers:
  - tooltrim
```

`tooltrim.config.yaml` — point tooltrim's upstream at your local servers. You
can shrink both `perseus` and (optionally) `perseus-vault` (~57 tools) behind
one filtered inbound endpoint instead of loading every tool schema every
session:

```yaml
servers:
  perseus-skills:
    transport: stdio
    command: ["perseus", "mcp", "serve"]
  perseus-vault:            # optional — Perseus Vault's ~57 memory tools
    transport: stdio
    command: ["perseus-vault", "serve"]

filters:
  allow:
    - "*.core/**"
    - "*.devops/**"
    - "perseus-vault.perseus_vault_recall"
    - "perseus-vault.perseus_vault_remember"
    - "perseus-vault.perseus_vault_context"

inbound:
  stdio: true
```

Result: Rovo Dev sees one `tooltrim` server exposing only the filtered subset,
instead of the full Perseus + Perseus Vault tool surface every session.

#### Limitation: Rovo Dev's platform integration bundle is NOT proxyable

Rovo Dev also injects a large **built-in** integration bundle (~21 toolsets:
`google_drive` ~42 tools, `slack` ~23, `jas` ~19, `loom` ~17, plus `s360`,
`c360`, `tap`, `switcheroo`, `socrates`, `feedback`, `atlassian`, `bitbucket`,
`compass`, ...). These are provisioned **server-side by the Rovo Dev platform**,
gated only by the presence of `INTEGRATIONS_SERVICE_MCP_API_TOKEN`, and there is
**no local config hook to route them through an MCP proxy**.

So tooltrim shrinks **self-declared** servers (the ones you list under
`servers:`), but it **cannot** filter the platform bundle — that is all-or-nothing
via the token. Granular filtering of the platform bundle is a Rovo Dev / `acli`
side feature request: the host must expose an upstream/proxy override or a
per-toolset allowlist for its built-in integrations before tooltrim (or any
proxy) can trim them.

If session-token bloat is the concern and you can't drop the whole bundle,
unset `INTEGRATIONS_SERVICE_MCP_API_TOKEN` to remove the platform bundle
entirely, then re-add only the self-declared servers you actually need behind
tooltrim.

## Filter Modes

- **Task mode** (84.7% savings): Uncomment the task filter block in the config.
  Keeps core agent skills + the specific devops/github tools relevant to your workflow.
- **Common mode** (34.4% savings): Default. Keeps all devops, github, and software-dev
  categories. Right for general development work.
- **Shrink only** (6.2%): Remove the filters block entirely. All 76 tools visible,
  but descriptions are compressed.

## How It Works

Tooltrim sits between your AI client and Perseus's MCP server. When the client
calls `tools/list`, tooltrim intercepts the response, filters tools matching
your glob patterns, shrinks descriptions, and returns the reduced list. Tool
calls to filtered-out tools are blocked — the agent literally can't see or call
tools outside the filter.

## Glob Tips

Perseus skill names use `category/name` format (e.g., `devops/perseus`).
Tooltrim matches against `<serverId>.<toolName>` using micromatch globs.

- `*.core/**` — all core skills (the `*` matches the server prefix, `/**` matches across the `/`)
- `*.devops/perseus` — exact match for the perseus skill
- `*.github/*` — all github skills (single level after `github/`)

## Limitations

- Tool names with `/` require `/**` globs (not `*`) — micromatch treats `/` as path separator
- Tooltrim v0.1.0 does not support filtering by tool description content, only by name
- The `shrink.mode: llm` option (LLM-powered description compression) is not yet implemented

## See Also

- [Tooltrim GitHub](https://github.com/false200/tooltrim)
- [Perseus @skills directive](https://github.com/Perseus-Computing-LLC/perseus)
- [Micromatch glob syntax](https://github.com/micromatch/micromatch)
