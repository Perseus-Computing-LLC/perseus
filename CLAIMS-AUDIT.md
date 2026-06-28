# Claims Audit — perseus

**Date:** 2026-06-28 (refreshed) · **Audited:** README.md, perseus.observer, code on `main`

## Verified claims (source-checked)

- **Perseus 26 MCP tools** — `_generate_directive_tools()` returns exactly 26 in perseus-ctx v1.0.12 (verified from the published amalgamation). README and perseus.observer now both say 26. ✓
- **Mimir 43 MCP tools, v2.6.0** — verified against `Perseus-Computing-LLC/mimir` source (43 distinct `mimir_*` names, `Cargo.toml` = 2.6.0). README references corrected from the stale "v2.2 / 40 tools". ✓
- **MCTS 31 analyzers** — `MCTS/src/mcts/core/scanner.py::_build_analyzers()` wires 31. Website corrected from the marketing "120" ("12 categories x 10"); MCTS README says "25+". ✓
- **Perseus itself** (live context engine, MCP server, directives) — running in production. ✓

## History

- 2026-06-12/13: earlier revisions had a methodology error (fork search omission) and
  cited 23 Mimir tools / 120 MCTS analyzers. Superseded by the 2026-06-28 source-verified
  figures above.
