# Claims Audit — perseus

**Date:** 2026-07-03 (refreshed) · **Audited:** README.md, perseus.observer, code on `main`

## Verified claims (source-checked)

- **Perseus MCP directive surface** — the `@`-directive registry and default `tools/list` policy are source-checked; no fixed public tool count is advertised because the surface evolves. ✓
- **Perseus Vault MCP surface** — canonical names and compatibility aliases are maintained in the Vault source; no fixed public tool count is advertised because the surface evolves. ✓
- **MCTS 31 analyzers** — `MCTS/src/mcts/core/scanner.py::_build_analyzers()` wires 31. Website corrected from the marketing "120" ("12 categories x 10"); MCTS README says "25+". ✓
- **Perseus itself** (live context engine, MCP server, directives) — running in production. ✓

## History

- 2026-06-12/13: earlier revisions had a methodology error (fork search omission) and
  cited 23 Mimir tools / 120 MCTS analyzers. Superseded by the 2026-06-28 source-verified
  figures above.
