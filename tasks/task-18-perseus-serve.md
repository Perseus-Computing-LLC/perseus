---
id: task-18
title: "Task 18 — perseus serve: read-only HTTP view"
status: completed
scope: medium
depends_on: []
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: '2026-05-18'
---

# Task 18 — `perseus serve`

## Goal

A `perseus serve` command that exposes the rendered narrative, health report,
Agora board, recent checkpoints, and oracle log over a local HTTP server for
browser viewing. **Read-only** — no write endpoints, no auth required because
no auth makes sense (bind to localhost only).

## Why

Sharing Perseus state in standup, code review, or pairing sessions today
requires running a sequence of CLI commands and pasting output. A simple
browser view is a much better UX for one specific case: showing other humans
what your workspace state is.

Also: this is the first step toward an editor extension (Phase 10) — the same
endpoints feed an LSP/IDE plugin later.

## Spec

### Command

```bash
perseus serve [--port 7991] [--workspace .] [--host 127.0.0.1]
```

Always binds to `127.0.0.1` by default. `--host 0.0.0.0` is allowed but the
README must warn that there is no auth.

### Endpoints

| Path | Returns |
|---|---|
| `/` | HTML index linking to the other endpoints |
| `/context` | `text/markdown` — `perseus render .perseus/context.md` output |
| `/narrative` | `text/markdown` — Mnēmē narrative body |
| `/health` | `text/markdown` — health report |
| `/agora` | `text/markdown` — Agora list output |
| `/checkpoint/latest` | `text/yaml` — latest checkpoint for the workspace |
| `/oracle/log?limit=N` | `application/json` — recent oracle log entries |

All endpoints are GET-only. POST returns 405.

### Implementation

Use `http.server.HTTPServer` + `BaseHTTPRequestHandler` from stdlib. Each
request fans out to the existing `cmd_*` or `resolve_*` helpers and serializes
the response.

Graceful shutdown on Ctrl-C.

## Acceptance criteria

1. `perseus serve --port 7991` starts a server; `curl http://127.0.0.1:7991/` returns 200.
2. `GET /context` returns the rendered context.md (handle no-context-file gracefully).
3. `GET /narrative` returns the Mnēmē narrative or a 404 if not initialized.
4. `GET /health` returns the maintenance report.
5. `GET /agora` returns the task list.
6. `GET /checkpoint/latest` returns the latest workspace pointer or 404.
7. `POST /` returns 405.
8. Server logs request line + status to stdout (one line per request).

## Constraints

Single file. Stdlib only. No new dependencies.

## Start here

1. Add `cmd_serve(args, cfg)` building an HTTPServer with a request handler class.
2. Implement endpoints by delegating to existing `cmd_*` / `resolve_*` helpers,
   capturing their stdout via `io.StringIO` redirect.
3. Add `serve` subparser with `--port`, `--host`, `--workspace`.
4. Index page is a minimal HTML stub with anchor links — no JavaScript.
5. Tests: 6+ — server start/stop, GET each endpoint via `urllib.request`,
   POST 405, unknown path 404.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `perseus serve [--port 7991] [--host 127.0.0.1] [--workspace .]`
- Read-only HTTP view; POST returns 405
- Endpoints: `/`, `/context`, `/narrative`, `/health`, `/agora`, `/checkpoint/latest`, `/oracle/log`
- Built on stdlib `http.server.HTTPServer` + `BaseHTTPRequestHandler`
- Endpoint logic isolated in `_serve_render_endpoint()` (pure function) for testability
- `/oracle/log?limit=N` returns JSON; other endpoints return text/markdown or text/yaml
- 0.0.0.0 bind allowed with a printed warning (no auth, by design)
- 10 tests covering all endpoints (happy + missing-file paths) — exercise the pure helper directly without spinning up the server
