# Claims Audit — perseus

**Date:** 2026-07-03 (refreshed) · **Audited:** README.md, perseus.observer, code on `main`

## Verified claims (source-checked)

- **Perseus 29 MCP directive tools** — the `@`-directive registry exposes 29 resolver-backed inline/block tools in v1.0.15 (`DIRECTIVE_REGISTRY`, kind in inline/block with a resolver). Default `tools/list` filters the 2 sensitive tools (`@query`, `@agent`) until allowlisted and adds legacy aliases. ✓
- **Perseus Vault 55 distinct MCP tools, v2.14.0** — verified against `Perseus-Computing-LLC/perseus-vault` source (55 distinct base tool names in `src/mcp.rs`, `Cargo.toml` = 2.14.0). Each is exposed under three name aliases (`perseus_vault_*`, `mimir_*`, `mneme_*`), so a raw `tools/list` handshake reports ~165. Supersedes the 2026-07-01 "48 tools / v2.12.0" figure. ✓
- **MCTS 31 analyzers** — `MCTS/src/mcts/core/scanner.py::_build_analyzers()` wires 31. Website corrected from the marketing "120" ("12 categories x 10"); MCTS README says "25+". ✓
- **Perseus itself** (live context engine, MCP server, directives) — running in production. ✓

## History

- 2026-06-12/13: earlier revisions had a methodology error (fork search omission) and
  cited 23 Mimir tools / 120 MCTS analyzers. Superseded by the 2026-06-28 source-verified
  figures above.
