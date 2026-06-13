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
- [Perseus @skills directive](https://github.com/tcconnally/perseus)
- [Micromatch glob syntax](https://github.com/micromatch/micromatch)
