# Claims Audit — perseus

**Date:** 2026-06-12 (corrected 2026-06-13) · **Audited:** README.md, MCTS/index.html vs reality

> **Correction (2026-06-13):** an earlier revision of this file claimed MCTS did
> not exist. That was wrong — a methodology error: GitHub's repo search omits
> forks by default, so a `user:tcconnally` search didn't surface
> [`tcconnally/MCTS`](https://github.com/tcconnally/MCTS) (a fork of the canonical
> [`MCP-Audit/MCTS`](https://github.com/MCP-Audit/MCTS)), even though the README
> linked straight to it and a full checkout exists locally. The MCTS section
> below is rewritten to reflect the real, verified state.

## Findings (ranked by judge visibility)

### MEDIUM — Mimir tool names in the README don't exist

- **Claim:** README: "v0.5.0 provides 23 MCP tools … `mimir_recall`, `mimir_store`, `mimir_entity_*`, `mimir_layer_*`, `mimir_decay_config`, …"
- **Reality:** 23 tools is correct, but `mimir_store`, `mimir_entity_*`, `mimir_layer_*`, and `mimir_decay_config` are not among them. Actual names: `mimir_remember`, `mimir_link`/`mimir_traverse`, `mimir_journal`, `mimir_state_*`, `mimir_vault_*`, `mimir_decay`, etc. A reader configuring an assistant from this README will call tools that don't exist.
- **Fix:** replace the example list with real tool names (see mimir/CLAIMS-AUDIT.md for the full surface).

## Verified claims

- **MCTS — "120 analyzers, one command", scan output, self-testing.** ✓ Verified against [`MCP-Audit/MCTS`](https://github.com/MCP-Audit/MCTS) (canonical) / [`tcconnally/MCTS`](https://github.com/tcconnally/MCTS) (fork the README links to) and a local checkout. It's a substantial product: ~120 analyzers, static AST + snapshot + live MCP probe discovery, SARIF/HTML/JSON output, a REST API, and a GitHub Action. The "every analyzer has a regression test" claim is corroborated by the `eval/behavioral/` regression-fixture harness. Test suite: 365 passing, 3 skipped, 4 Windows-only environment failures (encoding/venv-layout assumptions in tests, not product code) — see `code-reviews/MCTS-review.md`. The self-verification invariant in `RiskScoringEngine.verify()` (scan fails loudly on score mismatch) is real and rare. Recent commits already landed the per-analyzer error-isolation and SARIF-URI-normalization fixes from that review.
- **Mimir: 23 MCP tools, SQLite + FTS5, fully local** — verified against `tcconnally/mimir` v0.5.0 source. ✓
- **Perseus itself** (live context engine, MCP server, directives) — running in production in this very session. ✓

## Note on the registry-scan campaign

The "we scanned the top 20 MCP servers — X% have HIGH findings" campaign is
*feasible*: the scanner exists and runs. Per the user, scans have already been
run and issues filed against real MCP repos. The anchor stat should be computed
from those actual scan results (in `code-reviews/` and the MCTS repo), not
treated as blocked.
