---
id: task-75
title: MCP Deep Integration — Expose Directives as MCP Tools
status: open
priority: high
scope: large
claimed_by: null
created: 2026-05-24
phase: 25
theme: "MCP Protocol Integration"
depends_on:
- task-65
- task-69
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

Perseus resolves live context for AI assistants that read markdown files. But
the broader AI ecosystem is standardizing on the **Model Context Protocol (MCP)**
as the universal tool-calling transport. Any MCP-compatible client — Claude
Desktop, Continue, Cursor, Zed, Codex — can invoke MCP tools without parsing
Perseus syntax.

Exposing every Perseus directive as an MCP tool bridges the two worlds. An MCP
client can call `perseus_query`, `perseus_read`, `perseus_services` as native
tools and get live resolved context directly in their tool response stream. No
markdown file needed. No file-watching. No context window tax.

The existing `src/perseus/mcp.py` already provides read-only `get_context` and
`get_health` MCP tools. This task extends it to the full directive surface.

## What

Extend the MCP server to expose each directive in the `DIRECTIVE_REGISTRY` as a
first-class MCP tool. Any MCP client can invoke any Perseus directive through
the standard MCP tool-calling transport.

### Tool mapping

Each directive becomes a tool named `perseus_<directive_name>`:

| Directive | MCP Tool | Arguments |
|---|---|---|
| `@query` | `perseus_query` | `command` (string, required), `fallback` (string, optional), `schema` (string, optional) |
| `@read` | `perseus_read` | `path` (string, required), `key` (string, optional), `schema` (string, optional), `fallback` (string, optional) |
| `@env` | `perseus_env` | `var` (string, required), `required` (boolean, optional), `fallback` (string, optional), `schema` (string, optional) |
| `@services` | `perseus_services` | `config` (array of service definitions, optional — if omitted, reads from context doc) |
| `@checkpoint` | `perseus_checkpoint` | `task` (string, required) |
| `@recover` | `perseus_recover` | `workspace` (string, optional), `ttl` (integer, optional) |
| `@suggest` | `perseus_suggest` | `task` (string, required), `llm` (string, optional), `model` (string, optional) |
| `@health` | `perseus_health` | `workspace` (string, optional) |
| `@agora` | `perseus_agora` | `status` (string, optional), `scope` (string, optional) |
| `@memory` | `perseus_memory` | `focus` (string, optional), `ttl` (integer, optional), `include_federation` (boolean, optional) |
| `@drift` | `perseus_drift` | (none) |
| `@skills` | `perseus_skills` | `flag_stale` (boolean, optional), `category` (string, optional), `include` (string, optional) |
| `@list` | `perseus_list` | `path` (string, required), `type` (string, optional), `depth` (integer, optional) |
| `@tree` | `perseus_tree` | `path` (string, required), `depth` (integer, optional), `match` (string, optional), `exclude` (string, optional) |
| `@inbox` | `perseus_inbox` | `unread` (boolean, optional), `limit` (integer, optional) |
| Plugin directives | `perseus_<plugin_name>` | As declared in plugin `DirectiveSpec.args_schema` |

### Tool description generation

Each tool's description is auto-generated from the `DIRECTIVE_REGISTRY` entry's
`description` field. If a directive has an `args_schema` (new optional field on
`DirectiveSpec`), the MCP tool's `inputSchema` is derived from it. Directives
without `args_schema` use a minimal schema with the directive's text as a single
string argument.

### Existing tools preserved

The existing MCP tools remain for backward compatibility:
- `perseus_get_context` — returns the full rendered context (unchanged)
- `perseus_get_health` — returns the health report (unchanged)

New tools are additive.

### Trust and safety

- MCP tools respect the same trust gates as CLI rendering:
  - `allow_query_shell` must be true for `perseus_query` to execute commands
  - `allow_agent_shell` must be true for `perseus_agent`
  - Tool execution that violates a trust gate returns an error in the MCP
    response, not a silent failure
- Tool argument validation uses the same validators as directive parsing
- Timeouts are enforced per-tool (configurable via `mcp.tool_timeout_s`,
  default: 30s)

### MCP server startup

`perseus serve --mcp` starts a combined HTTP+MCP server. The MCP transport
uses stdio (for Claude Desktop, Continue) or HTTP with SSE (for remote clients):

```bash
# Stdio transport (for Claude Desktop config)
perseus serve --mcp --transport stdio

# HTTP+SSE transport (for network clients)
perseus serve --mcp --transport sse --port 8420
```

### Claude Desktop config example

```json
{
  "mcpServers": {
    "perseus": {
      "command": "perseus",
      "args": ["serve", "--mcp", "--transport", "stdio"],
      "cwd": "/workspace/myproject"
    }
  }
}
```

## Acceptance Criteria

1. Every registered directive (built-in + plugin) is exposed as an MCP tool
   named `perseus_<name>`
2. Tool descriptions are auto-generated from registry metadata
3. Tool input schemas are derived from `DirectiveSpec.args_schema` where
   available
4. `tools/list` MCP request returns all directive tools
5. `tools/call` with valid arguments resolves the directive and returns output
6. Trust gates are enforced — blocked operations return errors, not silent
   failures
7. Tool timeouts are enforced
8. `perseus serve --mcp --transport stdio` starts stdio MCP server
9. `perseus serve --mcp --transport sse` starts HTTP+SSE MCP server
10. Existing `perseus_get_context` and `perseus_get_health` tools are preserved
11. Plugin directive tools are included when plugins are loaded
12. `perseus doctor` check includes MCP server readiness
13. Tests:
    - `tools/list` returns all directive tools
    - `tools/call` for `perseus_query` resolves correctly
    - `tools/call` for `perseus_read` resolves correctly
    - `tools/call` for `perseus_services` resolves correctly
    - Trust gate blocks shell execution → error response
    - Tool timeout → error response
    - Plugin directive appears in `tools/list`
    - Stdio transport handshake (initialize → tools/list → tools/call)
    - SSE transport endpoint serves events
    - `perseus_get_context` and `perseus_get_health` still work
14. No new dependencies. MCP protocol is implemented with stdlib `json` +
    `asyncio` (already used by existing `mcp.py`).

## Non-goals

- Do not implement MCP resource or prompt capabilities (tools only in v1)
- Do not add MCP server authentication (relies on transport-level auth)
- Do not add tool result streaming — all results are synchronous
- Do not add MCP server discovery or registry
- Do not implement the full MCP specification — tools capability only
- Do not add bidirectional sync (MCP client → Perseus state changes)
- Do not remove or rename the existing `perseus_get_context` /
  `perseus_get_health` tools
