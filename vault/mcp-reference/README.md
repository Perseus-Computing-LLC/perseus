# Perseus Vault MCP reference

This directory publishes the Sourcey-generated MCP reference at
[`perseus.observer/vault/mcp-reference/`](https://perseus.observer/vault/mcp-reference/).

The generated site and snapshots originated in the successful [Sourcey API docs workflow](https://github.com/Perseus-Computing-LLC/perseus-vault/actions/runs/32925503445) from Vault commit `9c829207a4b44a8e679ba912b4c1c5608c8f1e36`. The website publication applies one explicit safety correction: `perseus_vault_proof_frame` is marked non-read-only and destructive because `zeroize=true` permanently blanks entity bodies. `metadata.json` and `publication.json` retain the source snapshot digest and bind the corrected public snapshot digest.

- [`metadata.json`](metadata.json) — version, tool count, generator versions, source snapshot digest, corrected public snapshot digest, and safety correction
- [`mcp.raw.json`](mcp.raw.json) — canonical public snapshot with the recorded safety annotation correction
- [`mcp.render.json`](mcp.render.json) — Sourcey-compatible rendering derivative with the same correction
- [`mcp-tools.html`](mcp-tools.html) — browsable tool reference

The default local MCP stdio path does not require a Perseus-hosted service. Optional network transports and connectors change that boundary. When encryption is enabled, entity bodies are encrypted; the FTS5 index and some metadata remain plaintext.
