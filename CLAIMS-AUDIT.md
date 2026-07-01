# Claims Audit — perseus

**Date:** 2026-07-01 (refreshed) · **Audited:** README.md, perseus.observer, code on `main`

## Verified claims (source-checked)

- **Perseus 27 MCP tools** — `_generate_directive_tools()` returns exactly 27 in perseus-ctx v1.0.14 (the `@research` directive added one since the 2026-06-28 count of 26). Default `tools/list` exposes 29 (27 directive tools − 2 sensitive filtered until allowlisted + 4 legacy aliases). ✓
- **Mimir/Perseus Vault 48 MCP tools, v2.12.0** — verified against `Perseus-Computing-LLC/perseus-vault` source (48 distinct `mimir_*` names in `src/mcp.rs`, `Cargo.toml` = 2.12.0). Supersedes the 2026-06-28 "43 tools / v2.6.0" figure. ✓
- **MCTS 31 analyzers** — `MCTS/src/mcts/core/scanner.py::_build_analyzers()` wires 31. Website corrected from the marketing "120" ("12 categories x 10"); MCTS README says "25+". ✓
- **Perseus itself** (live context engine, MCP server, directives) — running in production. ✓

## History

- 2026-06-12/13: earlier revisions had a methodology error (fork search omission) and
  cited 23 Mimir tools / 120 MCTS analyzers. Superseded by the 2026-06-28 source-verified
  figures above.
