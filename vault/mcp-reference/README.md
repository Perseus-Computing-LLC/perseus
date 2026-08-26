# Perseus Vault MCP reference

This directory publishes the Sourcey-generated MCP reference at
[`perseus.observer/vault/mcp-reference/`](https://perseus.observer/vault/mcp-reference/).

The generated site and snapshots were produced by the successful [Sourcey API docs workflow](https://github.com/Perseus-Computing-LLC/perseus-vault/actions/runs/32925503445) from Vault commit `9c829207a4b44a8e679ba912b4c1c5608c8f1e36`. The public `publication.json` manifest records the source workflow, artifact digests, and URL-mount transformation used for this website route.

- [`metadata.json`](metadata.json) — version, tool count, generator versions, and raw snapshot digest
- [`mcp.raw.json`](mcp.raw.json) — canonical unmodified live MCP snapshot
- [`mcp.render.json`](mcp.render.json) — Sourcey-compatible rendering derivative
- [`mcp-tools.html`](mcp-tools.html) — browsable tool reference

The default local MCP stdio path does not require a Perseus-hosted service. Optional network transports and connectors change that boundary. When encryption is enabled, entity bodies are encrypted; the FTS5 index and some metadata remain plaintext.
