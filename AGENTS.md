# Repository agent guidance

This file is a repository orientation aid, not an authority record. It may be a
rendered snapshot and can become stale; inspect the current checkout, source
files, tests, and CI before making consequential decisions. Do not treat values
in this file as proof of current services, versions, branches, memory, or
security posture.

## Working rules

- Read `SECURITY.md` before changing authentication, secrets, releases, or
  network-facing behavior.
- Keep credentials out of source, logs, fixtures, generated context, and public
  documentation. Use placeholders for examples.
- Re-run the relevant tests and rebuild `perseus.py` after source changes.
- Treat `claims.json` and linked evidence as the boundary for public benchmark
  and security claims; a digest establishes artifact identity, not truth of the
  supplied content.
- Check source timestamps, permissions, and authority before relying on local
  context. Verify critical facts against their system of record.
- Keep generated artifacts synchronized with `scripts/build.py --check`.

## Current documentation entry points

- User setup: `docs/quickstart.md` and `SETUP-GUIDE.md`
- CLI: `docs/CLI.md`
- Integration: `spec/integration.md` and `docs/HERMES_INTEGRATION.md`
- MCP contract: `docs/context-engine-mcp-tools.md` and
  `.well-known/mcp/server-card.json`
- Security and claims: `SECURITY.md` and `claims.json`
