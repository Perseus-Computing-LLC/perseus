# Perseus Vault MCP reference

This directory publishes the Sourcey-generated MCP reference at
[`perseus.observer/vault/mcp-reference/`](https://perseus.observer/vault/mcp-reference/).

The generated site and snapshots were produced by the successful [Sourcey API
docs workflow](https://github.com/Perseus-Computing-LLC/perseus-vault/actions/runs/32897532973)
from Vault commit `f48e528f89dfb8ce8c19c4a0714808a9d1fb728c`. The public
`publication.json` manifest records the artifact digests and the small URL
mount transformation needed because the Sourcey site is nested under this
website route.

- [`metadata.json`](metadata.json) — version, tool count, generator versions, and raw snapshot digest
- [`mcp.raw.json`](mcp.raw.json) — canonical unmodified live MCP snapshot
- [`mcp.render.json`](mcp.render.json) — Sourcey-compatible rendering derivative
- [`mcp-tools.html`](mcp-tools.html) — browsable tool reference
