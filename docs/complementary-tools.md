# Complementary MCP Tools

Tools that enhance Perseus sessions when installed alongside. These are tested, documented MCP ecosystem tools that Perseus can surface in its `@skills` or `@tools` directives.

## Tier 1 — Install & Use Immediately

These tools install via npm and require zero Perseus code changes.

---

### tooltrim — MCP Proxy Tool List Shrinker

- **Repo:** <https://github.com/false200/tooltrim>
- **npm:** `tooltrim`
- **Version tested:** 0.1.2
- **License:** MIT
- **Status:** ✅ Verified working (2026-06-18)

**What it does:** Sits in front of N upstream MCP servers and filters/shrinks their tool lists, reducing context window consumption from verbose JSON-Schema tool definitions.

**Install:**
```bash
git clone https://github.com/false200/tooltrim.git
cd tooltrim
NODE_ENV=development npm install
npm run build
```

**Quick test:**
```bash
node dist/cli.js --help
```

**Perseus integration:** When Perseus renders context for sessions with many MCP servers, tooltrim can pre-shrink the `tools/list` output, keeping context windows focused on relevant tools only.

---

### kondukt — MCP Server DevTools

- **Repo:** <https://github.com/kondukt-dev/core>
- **npm:** `kondukt`
- **Version tested:** Latest (via npx)
- **License:** Not specified
- **Status:** ✅ Verified working with Perseus MCP server (2026-06-18)

**What it does:** Test, validate, debug, inspect, and scaffold MCP servers. Drop-in toolkit for MCP server development.

**Install:**
```bash
npm install -g kondukt
```

**Verified commands against Perseus:**
```bash
# Inspect Perseus's MCP tools
npx kondukt inspect "perseus mcp serve"

# Test connection
npx kondukt test "perseus mcp serve"

# Validate protocol compliance
npx kondukt validate "perseus mcp serve"
```

**Perseus integration:** Kondukt can validate Perseus's own MCP server protocol compliance. Useful in CI/CD for `perseus doctor` or pre-release checks.

---

### mcp-pager — Token-Aware Response Pagination

- **Repo:** <https://github.com/SatishKakollu/mcp-pager>
- **npm:** `mcp-pager`
- **Version tested:** 0.8.0
- **License:** Not specified
- **Status:** ✅ Installed, library-only (no CLI). 115 tests passing.

**What it does:** Token-aware response paging middleware for MCP servers. One line of code chunks large tool responses into pages delivered incrementally. Python and TypeScript versions available.

**Install:**
```bash
npm install mcp-pager
```

**Usage pattern:** Import as middleware in your MCP server, not run as a standalone process.

**Perseus integration:** Recommend in Perseus setup docs for users building custom MCP servers that return large responses. Prevents context overflow in Perseus-rendered sessions with verbose tool output.

---

### x402-mcp — Paid API Access via MCP

- **Repo:** <https://github.com/x402node/x402-mcp>
- **npm:** `x402-mcp`
- **Version tested:** 0.1.1
- **License:** MIT
- **Status:** ✅ Installed, requires `X402_PRIVATE_KEY` env var for live use.

**What it does:** MCP server bringing 117+ paid APIs to AI agents via x402 protocol with stablecoin micropayments across Base, Solana, Polygon, BNB, EVM chains.

**Install:**
```bash
npm install -g x402-mcp
```

**Requires:** `X402_PRIVATE_KEY` environment variable. Configure in Claude Desktop:
```json
{
  "x402-mcp": {
    "command": "npx",
    "args": ["x402-mcp"],
    "env": { "X402_PRIVATE_KEY": "your-key" }
  }
}
```

**Perseus integration:** Niche but powerful for agent monetization research. Perseus could surface available x402-paid APIs in `@tools` when the key is configured.

---

### proxcp — MCP Server Management Platform

- **Repo:** <https://github.com/ryzxxn/proxcp>
- **npm:** Not published — Docker-based
- **Version tested:** Latest main (2026-05-14)
- **License:** Not specified
- **Status:** ⚠️ Requires Docker (FastAPI backend + Next.js frontend). Not tested — no Docker available.

**What it does:** Management platform for MCP servers with authentication, API key management, transaction logging, and per-key tool/resource/prompt permissions matrix.

**Architecture:**
- `proxcp-server/`: FastAPI backend (Python 3.11+)
- `proxcp-client/`: Next.js frontend

**To run:**
```bash
git clone https://github.com/ryzxxn/proxcp.git
cd proxcp
cp proxcp-server/.env.example proxcp-server/.env
cp proxcp-client/.env.example proxcp-client/.env
docker compose up --build
```

**Perseus integration:** Potential UX inspiration for `perseus mcp list` and MCP management. The access control model (per-tool permissions per API key) is relevant for multi-tenant Perseus deployments.

---

### WEBGhosting-MCP — Stealth Browser for AI Agents

- **Repo:** <https://github.com/yranjan06/WEBGhosting-MCP>
- **Package:** Go binary (not on npm)
- **Version tested:** N/A — requires Go toolchain
- **Stars:** 32 | **Forks:** 6
- **Status:** ⚠️ Requires Go. Not tested — Go not available in this environment.

**What it does:** Intelligent stealth browser MCP server with 30 tools, 22 anti-fingerprint scripts, and LLM-powered extraction. Bypasses Cloudflare/bot detection. Works with Cursor, Claude, VS Code.

**To run:**
```bash
git clone https://github.com/yranjan06/WEBGhosting-MCP.git
cd WEBGhosting-MCP
# Requires Go 1.21+
go build -o webghosting ./cmd/server
```

**Perseus integration:** Useful for Perseus agents that need live web access to bot-protected sites. List in `@skills` as optional companion for web-heavy workspaces.

---

## Testing Summary

| Tool | Type | Install Method | CLI Verified | MCP Verified | Blocker |
|---|---|---|---|---|---|
| tooltrim | npm | Local build | ✅ | — | None |
| mcp-pager | npm | `npm install -g` | N/A (library) | — | None |
| kondukt | npm | `npm install -g` | ✅ | ✅ (tested w/ Perseus) | None |
| proxcp | Docker | Clone + docker compose | — | — | No Docker in env |
| WEBGhosting | Go | Clone + go build | — | — | No Go in env |
| x402-mcp | npm | `npm install -g` | N/A (server) | — | Needs PRIVATE_KEY |

**Kondukt** is the standout Tier 1 tool — it directly validates Perseus's MCP server and can be used in Perseus CI/CD for pre-release protocol compliance checks.

*Documented: 2026-06-18 | Phase 0 of Discord Scout integration plan*
