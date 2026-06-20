---
id: task-99
title: "Access Control & Capability Grants for Federation"
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-06-19
phase: 27
theme: Decentralized Federation — Access Control
depends_on:
- task-96
- task-97
blocks: []
opened: '2026-06-19'
closed: null
---
## Why

Phase 27A/B/C let workspaces pull and push narratives. But there's only one
auth token for the entire serve instance — every subscriber uses the same key.
Real decentralized federation needs per-subscriber access control: grant Beta
read access for 30 days, revoke Gamma's access when a contract ends, issue
short-lived tokens that don't expose the master key.

## What

Add capability-based access control to `perseus serve` federation endpoints.
A "grant" is a signed capability: "workspace sha256:abc may read the
narrative for 30 days." Tokens are bearer tokens scoped to specific grants.

### 1. `perseus identity grant`

```
perseus identity grant <workspace_id> --scope narrative --ttl 30d
perseus identity grant <workspace_id> --scope narrative --ttl 7d --output token
```

- Creates a grant record in `~/.perseus/keys/grants.yaml`:
  ```yaml
  - grant_id: "gnt_abc123"
    workspace_id: "sha256:def456"
    scope: "narrative"
    ttl_days: 30
    issued: "2026-06-19T..."
    expires: "2026-07-19T..."
    token_hash: "sha256:<hex>"
    revoked: false
  ```
- With `--output token`: prints the bearer token to stdout. The token is a
  base64-encoded JSON payload including `grant_id` + random nonce, HMAC-signed
  with the issuer's workspace key.
- Token format: `perseus_gnt_<base64>` — recognizable prefix for logging/audit.

### 2. `perseus identity revoke`

```
perseus identity revoke <grant_id>
```

- Sets `revoked: true` on the grant record.
- Tokens derived from that grant are rejected on the next request.
- No need to rotate tokens — serve checks grant status on each request.

### 3. Serve middleware

`perseus serve` checks bearer tokens on `/federation/*` endpoints:

1. Parse token → extract `grant_id`
2. Look up grant in `grants.yaml`
3. Check: not revoked, not expired, scope matches endpoint
4. Check: token HMAC matches (proves token was issued by this workspace)
5. Reject with 401 if any check fails

Auth precedence: `serve.auth_token` (master key) → grant tokens → reject.
If `serve.auth_token` is configured, it still works as the master key.

### 4. `federation.d/` directory

As an alternative to a single monolithic `federation.yaml`, Perseus discovers
per-subscription files in `~/.perseus/federation.d/`:

```
~/.perseus/federation.d/
  beta.yaml     → alias: beta, remote.url: https://beta:7991, verify_key: ...
  gamma.yaml    → alias: gamma, remote.url: https://gamma:7991, verify_key: ...
```

- Each file is a single-subscription YAML fragment
- If `federation.d/` exists, its files are merged with `federation.yaml`
  subscriptions (directory wins on alias collision)
- `perseus memory federation subscribe --alias X` writes to the directory
  if it exists, otherwise to the monolithic manifest
- Reduces merge conflicts when multiple tools manage subscriptions

### Verification

- Grant → token → serve accepts request
- Revoke grant → same token rejected
- Expired grant → token rejected
- Wrong scope → token rejected
- `federation.d/` files discovered and merged correctly
