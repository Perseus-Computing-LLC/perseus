---
id: task-69
title: "Phase 24E \u2014 Foreign Resolver Protocol"
status: completed
priority: medium
scope: large
claimed_by: hermes
created: 2026-05-24
phase: 24
theme: "Extensibility Architecture \u2014 Hephaestus"
depends_on:
- task-65
blocks: []
opened: '2026-05-24'
closed: '2026-05-25'
---
## Why

Perseus works well for local workspaces, but teams often have shared context
that lives on a central server — infrastructure health, deployment status, team
checkpoints. Currently, each workstation must independently resolve the same
shared context.

The foreign resolver protocol lets one Perseus instance (e.g., a team server)
serve rendered context, and other instances (workstations, CI runners) pull
it inline. This enables distributed context without duplicating resolution work.

The roadmap also calls out **MCP deep integration** as a sibling extension:
exposing each directive as an MCP tool so any MCP client can invoke `@query`,
`@read`, `@services` through the MCP transport. This task covers the Perseus-
to-Perseus protocol; MCP tool exposure is deferred to task-75.

## What

A `@perseus` directive that fetches rendered context from another Perseus serve
instance.

### Syntax

```
@perseus https://team-server:8420/workspace/infra  @cache ttl=300
```

The URL points to a `perseus serve` endpoint. The response is rendered markdown
injected inline at the directive's position.

### Protocol

The foreign resolver makes an HTTP GET to `<base_url>/api/context`:

**Request:**
```
GET /api/context HTTP/1.1
Host: team-server:8420
Accept: text/markdown
Authorization: Bearer <token>         # if serve auth is enabled
X-Perseus-Workspace: infra            # workspace identifier
```

**Response (200):**
```json
{
  "resolved": "# Rendered context...",
  "metadata": {
    "workspace": "infra",
    "timestamp": "2026-05-24T20:00:00Z",
    "version": "1.0.1",
    "directive_count": 12
  },
  "integrity": {
    "sha256": "abc123...",
    "algorithm": "sha256"
  }
}
```

### Trust model

- **HMAC signature verification (opt-in):** If `foreign.verify_signatures` is
  enabled, the response must include an `X-Perseus-Signature` header with an
  HMAC-SHA256 of the response body. The shared secret is configured in
  `foreign.shared_secret`
- **TTL caching:** `@cache ttl=N` is **required** for `@perseus` directives.
  Omitting TTL is a render warning; default TTL of 60s is applied
- **Graceful degradation:** Connection failure → `[perseus: could not reach
  team-server:8420]` placeholder + warning. Render continues
- **Timeout:** Configurable via `foreign.timeout_s` (default: 10s)
- **TLS:** HTTPS URLs are verified normally. Self-signed certs require
  `foreign.tls_verify: false` (default: `true`)
- **Content size cap:** Responses over `foreign.max_response_bytes` (default:
  1MB) are truncated with a warning

### Serve endpoint

The existing `perseus serve` needs a new endpoint:

```
GET /api/context?workspace=<name>
```

Returns the latest rendered context for the requested workspace. Workspace
resolution follows the same rules as local rendering. If serve auth is enabled
(Phase 20A), this endpoint requires a valid token.

## Acceptance Criteria

1. `@perseus <url> @cache ttl=N` fetches and injects remote context
2. `@perseus` without `@cache ttl=N` → warning, default 60s TTL applied
3. Connection failure → placeholder text + warning, render continues
4. Timeout respected (`foreign.timeout_s` config)
5. Response over size cap → truncated with warning
6. HMAC signature verification works when `foreign.verify_signatures: true`
7. `perseus serve` exposes `GET /api/context?workspace=<name>`
8. Serve endpoint respects auth token when serve auth is enabled
9. TLS verification is enabled by default, configurable off
10. `perseus graph` reports `@perseus` as a foreign dependency
11. Tests:
    - Successful foreign resolution (mock HTTP)
    - Connection failure → graceful degradation
    - TTL requirement enforcement
    - HMAC verification (valid and invalid signatures)
    - Serve `/api/context` endpoint returns correct workspace context
    - Size cap enforcement
    - TLS config gate
12. No new dependencies. `urllib` is stdlib.

## Non-goals

- Do not implement bidirectional sync (server → client push)
- Do not implement differential/delta context updates
- Do not support non-HTTP transports (gRPC, WebSocket, Unix socket)
- Do not implement MCP tool exposure here — that's task-75
- Do not implement workspace discovery or registry
- Do not support `@perseus` with local file paths (use `@include`)
