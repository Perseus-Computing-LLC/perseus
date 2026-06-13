# Claims Audit — perseus

**Date:** 2026-06-12 · **Audited:** README.md, MCTS/index.html vs reality

## Findings (ranked by judge visibility)

### CRITICAL — MCTS is advertised as a shipping product, but no scanner exists

- **Claim:** README product table: "MCTS — 120 security analyzers for MCP servers — tool poisoning, prompt injection, credential leaks." `MCTS/index.html` goes further: "120 Analyzers. One Command.", scan output mockups, "MCTS tests its own detections. Every analyzer has a matching regression test."
- **Reality:** There is no `tcconnally/MCTS` repository, no MCTS code anywhere in this workspace, and no PyPI/crates package. The only artifact is the landing page. Anyone who clicks through and tries to install discovers the fiction immediately.
- **Fix (pick one):** (a) take the MCTS page down / mark it "in development" until the scanner exists; (b) descope the copy to a roadmap announcement; (c) build at least a minimal working scanner before the page ships. Publishing "we scanned the top 20 MCP servers" stats is impossible until this exists.

### MEDIUM — Mimir tool names in the README don't exist

- **Claim:** README: "v0.5.0 provides 23 MCP tools … `mimir_recall`, `mimir_store`, `mimir_entity_*`, `mimir_layer_*`, `mimir_decay_config`, …"
- **Reality:** 23 tools is correct, but `mimir_store`, `mimir_entity_*`, `mimir_layer_*`, and `mimir_decay_config` are not among them. Actual names: `mimir_remember`, `mimir_link`/`mimir_traverse`, `mimir_journal`, `mimir_state_*`, `mimir_vault_*`, `mimir_decay`, etc. A reader configuring an assistant from this README will call tools that don't exist.
- **Fix:** replace the example list with real tool names (see mimir/CLAIMS-AUDIT.md for the full surface).

## Verified claims

- Mimir: 23 MCP tools, SQLite + FTS5, fully local — verified against `tcconnally/mimir` v0.5.0 source. ✓
- Perseus itself (live context engine, MCP server, directives) — running in production in this very session. ✓
