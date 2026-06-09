45|[![Status: Patent Pending](https://img.shields.io/badge/status-patent_pending-blue)](./docs/ip/README.md)
46|[**perseus.observer →**](https://perseus.observer)
47|
48|<!-- mcp-name: io.github.tcconnally/perseus -->
49|
50|---
51|
52|### Sibyl Memory MCP Server
53|
54|Perseus includes an **optional** standalone MCP server for Sibyl Memory — structured five-tier local memory with three tools: `sibyl_search` (FTS5 across all tiers), `sibyl_recall` (fetch by category + name), and `sibyl_remember` (create or update).
55|
56|**Hermes Agent** — add to `~/.hermes/config.yaml`:
57|
58|```yaml
59|mcp_servers:
60|  sibyl:
61|    command: "python3"
62|    args: ["/path/to/perseus-repo/src/sibyl_mcp_server.py"]
63|    env:
64|      SIBYL_DB_PATH: "~/.sibyl-memory/memory.db"
65|    timeout: 30
66|    connect_timeout: 15
67|```
68|
69|**Claude Desktop / Cursor** — add to your MCP settings:
70|
71|```json
72|{
73|  "mcpServers": {
74|    "sibyl": {
75|      "command": "uvx",
76|      "args": ["--from", "perseus-ctx[mcp]", "sibyl-mcp-server"],
77|      "env": {
78|        "SIBYL_DB_PATH": "/home/yourname/.sibyl-memory/memory.db"
79|      }
80|    }
81|  }
82|}
83|```
84|
85|Works with any MCP-compatible assistant: Claude Desktop, Claude Code, Cursor, Codex, Hermes Agent, Rovo Dev. [Full setup guide →](./SETUP-GUIDE.md)
86|
87|## Wire Perseus to Your Assistant (MCP)
88|
89|Perseus implements the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), exposing tools over stdio or SSE transport. Every tool resolves live workspace state at invocation time — no stale cache, no pre-computed snapshots.
90|
91|> **⚠️ v1.0.6+ Security Gate:** Shell-executing directives (`@query`, `@agent`, `@services command:`) require `export PERSEUS_ALLOW_DANGEROUS=1`. Without it, shell directives are silently skipped.
92|
93|### Quick Start (MCP Server)
94|
95|```bash
96|pip install perseus-ctx
97|perseus mcp serve                          # stdio (Claude Desktop, Claude Code, Cursor, Codex)
98|perseus mcp serve --transport sse --port 8420  # SSE (remote agents, multi-machine)
99|```
100|
101|### Assistant-Specific Wiring
102|
103|Pick your assistant and add the config block shown:
104|
105|**Hermes Agent** (`~/.hermes/config.yaml`):
106|
107|```yaml
108|mcp_servers:
109|  perseus:
110|    command: perseus
111|    args: ["mcp", "serve", "--workspace", "/path/to/workspace"]
112|```
113|
114|Then verify with `hermes mcp test perseus`. Tools appear as `mcp_perseus_*` in your session.
115|
116|> Use an absolute path for `--workspace`. Perseus's non-interactive shell context has a limited PATH — a bare `perseus` command works in the Hermes MCP config because Hermes resolves it from the user's environment, but the workspace path must be absolute.
117|
118|**Claude Desktop** (`claude_desktop_config.json`):
119|
120|```json
121|{
122|  "mcpServers": {
123|    "perseus": {
124|      "command": "perseus",
125|      "args": ["mcp", "serve", "--workspace", "/path/to/workspace"]
126|    }
127|  }
128|}
129|```
130|
131|**Claude Code** (`.mcp.json` in your project root):
132|
133|```json
134|{
135|  "mcpServers": {
136|    "perseus": {
137|      "command": "perseus",
138|      "args": ["mcp", "serve"]
139|    }
140|  }
141|}
142|```
143|
144|**Cursor** (`.cursor/mcp.json`):
145|
146|```json
147|{
148|  "mcpServers": {
149|    "perseus": {
150|      "command": "perseus",
151|      "args": ["mcp", "serve"]
152|    }
153|  }
154|}
155|```
156|
157|**Codex** (`~/.codex/config.toml` or per-project `.mcp.json`):
158|
159|```json
160|{
161|  "mcpServers": {
162|    "perseus": {
163|      "command": "perseus",
164|      "args": ["mcp", "serve"]
165|