---
id: task-54
title: Phase 20A authenticated serve mode
status: completed
priority: high
scope: large
claimed_by: Codex
created: 2026-05-19
closed: 2026-05-20
phase: 20
theme: "Managed Runtime and Deployment Modes"
depends_on:
- task-47
blocks:
- task-55
opened: '2026-05-19'
---

## Why

`perseus serve` is intentionally read-only and loopback-first, but managed
deployments need explicit authentication and safer exposure controls before
teams bind beyond localhost.

## What

- Add optional token authentication for HTTP endpoints.
- Preserve current loopback defaults.
- Require explicit opt-in for non-loopback binds.
- Add audit/trust reporting for serve exposure.

## Acceptance Criteria

1. Existing localhost serve behavior remains backward-compatible.
2. Token-protected mode rejects unauthenticated requests.
3. Non-loopback binds remain explicit and visible in trust reports.
4. JSON endpoints preserve their current shapes.
5. Tests cover auth success, auth failure, and legacy no-auth loopback mode.

## Non-goals

- Do not build multi-user auth.
- Do not expose mutating HTTP endpoints.
- Do not default to remote binds.

## Completed

- Added optional static bearer-token authentication via `serve.auth_token`.
- Added `perseus serve --generate-token` for generating user-managed tokens.
- Preserved unauthenticated loopback behavior for backward compatibility.
- Required non-loopback binds to use `serve.auth_token` or an explicit insecure
  opt-in through `serve.allow_insecure_remote: true` / `--i-understand-no-auth`.
- Added serve auth state to `perseus trust --json` and the human trust report.
- Added tests for legacy no-auth loopback, missing/wrong/valid bearer tokens,
  non-loopback auth behavior, token generation, and trust report serve fields.

## Implementation Notes

**Token mechanism:** Static bearer token in config (`serve.auth_token`). If set,
all endpoints require `Authorization: Bearer <token>` header. Requests without
or with a wrong token return HTTP 401 with a JSON body `{"error": "unauthorized"}`.
No sessions, no cookies, no JWT — single static token only.

**Config schema addition:**
```yaml
serve:
  auth_token: null        # string or null; null = no auth (current behavior)
  bind_host: "127.0.0.1" # "0.0.0.0" requires explicit override + warning
```

**Non-loopback bind warning:** If `bind_host` is set to anything other than `127.0.0.1`
or `::1`, Perseus prints a prominent warning to stderr:
`[serve] WARNING: binding to <host> — set serve.auth_token to protect endpoints`
and logs an audit event. If `bind_host != loopback AND auth_token is null`, exit
with an error unless `serve.allow_insecure_remote: true` is explicitly set.

**Trust report integration:** `perseus trust` report includes a `[serve]` section
showing current `bind_host`, whether `auth_token` is set (not the value), and
whether the last serve session used loopback. `--json` output adds a `serve` key.

**Token generation helper:** `perseus serve --generate-token` prints a
`secrets.token_urlsafe(32)` value to stdout for the user to paste into config.
No storage — user manages the token.

**Test coverage:** Monkeypatch the HTTP handler and `_serve_handle_request`. Cover:
no-auth loopback (backward compat), valid bearer token accepted, missing token 401,
wrong token 401, non-loopback without token exits/errors, trust report shows auth state.
