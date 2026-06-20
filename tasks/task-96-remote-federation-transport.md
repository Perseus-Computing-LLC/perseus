---
id: task-96
title: "Remote Federation Transport — Pull Narratives Over HTTP"
status: open
priority: high
scope: large
claimed_by: null
created: 2026-06-19
phase: 27
theme: Decentralized Federation — Transport Layer
depends_on: []
blocks:
- task-97
- task-98
- task-99
- task-100
- task-101
opened: '2026-06-19'
closed: null
---
## Why

Current federation (Phase 8.2) reads Mnēmē narratives from local filesystem paths
via `federation.yaml`. This works when all workspaces share a filesystem. It does
not work across machines, containers, or networks.

The first step toward decentralized federation is the simplest possible remote
transport: pull a signed narrative over HTTP from a `perseus serve` instance.
This is the substrate that identity, signing, push, and provenance all build on —
get this right and everything else is additive.

## What

Extend the federation manifest with a `remote:` block so subscriptions can point
at HTTP URLs instead of (or in addition to) local filesystem paths. Extend
`perseus serve` with a `/federation/narrative` endpoint. Teach the existing
`pull` / render pipeline to fetch from remotes, verify (when verification is
enabled), cache locally, and degrade gracefully on failure.

### 1. Manifest schema extension

Extend `federation.yaml` subscriptions to accept a `remote:` block:

```yaml
subscriptions:
  - alias: beta
    remote:
      url: "https://beta-machine:7991"
      auth_token: "${PERSEUS_BETA_TOKEN}"
      verify_key: null       # null = no verification (v1; task-97 fills this)
    enabled: true

  # Backward compatible — existing local-path entries unchanged:
  - alias: gamma
    path: /workspace/gamma
    enabled: true
```

A subscription has EITHER `path` (local filesystem, current behavior) OR
`remote` (HTTP fetch, new behavior), but not both. If both are present,
`remote` takes precedence.

Env-var expansion: `auth_token: "${ENV_VAR}"` is expanded at render/pull
time via `os.path.expandvars()`. Unset env vars log a warning and skip auth
(unauthenticated request).

### 2. Serve endpoint

Add `GET /federation/narrative` to `perseus serve`:

```
GET /federation/narrative?ws=<workspace-hash>&since=<iso-timestamp>
Authorization: Bearer <token>
```

Response (200):
```json
{
  "workspace_id": null,
  "narrative": "# Project Narrative\n\n...",
  "signature": null,
  "updated": "2026-06-19T20:00:00Z",
  "format_version": 1
}
```

- `workspace_id` and `signature` are `null` until task-97 (signing).
- `?ws=` filter: return only the narrative for that workspace hash. If
  omitted or `*`, return the current workspace's narrative.
- `?since=` filter: return `304 Not Modified` if narrative hasn't changed.
  Client should set `If-Modified-Since` header to `since` value.
- Auth: accept `serve.auth_token` as Bearer. No per-subscriber tokens yet
  (task-99).
- CORS: `Access-Control-Allow-Origin: *` (read-only endpoint; no side effects).
- Error responses: `401` (bad/absent token when auth is configured),
  `404` (workspace not found), `500` (narrative read failure).

### 3. Pull from remotes

`perseus memory federation pull` gains a fetch-from-remote path:

- For each subscription with a `remote.url`:
  1. Construct request URL: `{url}/federation/narrative?ws={hash}`
  2. Set `Authorization: Bearer {token}` if `auth_token` is present
  3. GET with 10s connect timeout, 30s read timeout
  4. On 200: write response body to `~/.perseus/cache/federation/{alias}.json`
  5. On 304: use cached copy
  6. On error/timeout/4xx/5xx: log warning, skip
- For local-path subscriptions: existing behavior (unchanged)
- JSON output (`--json`): include `transport: "local" | "remote"` and
  `http_status` fields

### 4. Render-time federation

`_render_federation_digest()` in `mneme_federation.py` is extended:

- Local-path subscriptions: existing behavior (unchanged)
- Remote subscriptions: read from `~/.perseus/cache/federation/{alias}.json`
  (cached by `pull`). If cache is absent or older than `federation.cache_ttl_s`
  (default 3600), attempt a live fetch. If fetch fails, use stale cache with a
  staleness warning. If no cache exists either, render a warning block.
- Warning block format for remote entries (Q5 pattern):

```
> ⚠ Federated memory `beta` unavailable: connection refused (https://beta:7991).
> Last known good: 2026-06-19T18:00:00Z (cached)
> (Manage subscriptions with `perseus memory federation list`.)
```

### 5. Local caching

Cache directory: `~/.perseus/cache/federation/`

- Per-subscription cache file: `{alias}.json`
- Schema:
  ```json
  {
    "alias": "beta",
    "url": "https://beta:7991",
    "workspace_hash": "a1b2c3d4...",
    "narrative": "...",
    "signature": null,
    "updated": "2026-06-19T20:00:00Z",
    "fetched_at": "2026-06-19T20:01:00Z",
    "format_version": 1
  }
  ```
- TTL: `federation.cache_ttl_s` config key (default 3600 = 1 hour)
- Atomic write: write to `.tmp`, `os.replace()` to final path

### 6. Config keys (new)

| Key | Default | Description |
|---|---|---|
| `federation.cache_ttl_s` | 3600 | Max age of cached remote narratives before re-fetch |
| `federation.fetch_timeout_s` | 10 | HTTP connect timeout for remote fetches |
| `federation.read_timeout_s` | 30 | HTTP read timeout for remote fetches |

## Non-goals (deferred to later tasks)

- Cryptographic signing/verification (task-97)
- Push federation (task-98)
- Per-subscriber access control (task-99)
- Conflict detection (task-100)
- Provenance chains (task-101)
- ed25519 keypairs (HMAC-SHA256 only; ed25519 upgrade path in task-97)

## Verification

1. **Unit tests:** `tests/test_federation_remote.py`
   - Manifest parsing with `remote:` block
   - Env-var expansion in `auth_token`
   - Cache read/write round-trip
2. **Integration test:** `tests/test_federation_serve.py`
   - Start `perseus serve --port 17991` in test fixture
   - `perseus memory federation subscribe --alias test --remote-url http://localhost:17991`
   - `perseus memory federation pull` fetches narrative
   - `perseus render` with `@memory federation` includes remote narrative
3. **Smoke test (CI):**
   ```bash
   perseus memory federation pull --json | jq '.[] | select(.transport=="remote") | .status'
   # → "ok"
   ```
4. **Degradation test:** Stop the serve process, pull again — verify warning block,
   not crash.
5. **Backward compat:** Existing local-path-only `federation.yaml` must still work
   with no changes.

## Files to change

- `src/perseus/mneme_federation.py` — manifest parsing + `remote:` block,
  pull-from-remote, cache layer, render-time remote path
- `src/perseus/cli.py` — serve endpoint registration, `--remote-url` arg
  for subscribe
- `src/perseus/serve.py` — `GET /federation/narrative` handler
- `tests/test_federation_remote.py` — new test file
- `tests/test_federation_serve.py` — new integration test file
- `spec/federation.md` — update federation spec with remote transport
