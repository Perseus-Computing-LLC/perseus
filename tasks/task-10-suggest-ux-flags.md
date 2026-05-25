---
id: task-10
title: "Task 10 — Pythia Suggest UX Flags: --quick, --category, --no-services"
status: completed
scope: small
depends_on:
  - task-02
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: 2026-05-18
---

# Task 10 — Pythia Suggest UX Flags: `--quick`, `--category`, `--no-services`

**Status: Open**  
**Scope: Small** — additive flags on an existing command; no architectural changes  
**Depends-on: task-02** (`--llm` and oracle log infrastructure must be in place)

---

## Context

`spec/oracle.md` defines three optional flags for `perseus suggest` that are not yet
implemented:

```bash
perseus suggest "..." --quick           # lightweight local summary
perseus suggest "..." --category github  # limit skill search to a category
perseus suggest "..." --no-services      # skip live service health checks (faster)
```

These are quality-of-life flags that make Pythia faster and more targeted in common usage
patterns. They don't change the oracle's core behavior — they tune what goes into the
environment snapshot.

---

## Flags to Implement

### `--quick`

Emit a lightweight oracle prompt: skills list only, no service health checks, no session
digest, no checkpoint summary. Intended for rapid "just tell me which skill" queries where
the user doesn't want to wait for HTTP health checks or session lookups.

Equivalent to `--no-services` with a shortened prompt format. The oracle prompt template
used in `--quick` mode should omit the services and session sections entirely, not just
leave them empty.

### `--category <name>`

Restrict the skills scan to a single category directory. Instead of scanning all of
`~/.hermes/skills/`, only scan `~/.hermes/skills/<category>/`.

```bash
perseus suggest "open a PR for this branch" --category github
```

The ranked output should reflect only skills in that category. If the category directory
doesn't exist, emit a warning and fall back to the full scan.

### `--no-services`

Skip the live service health check phase entirely. Useful when:
- Services are known to be running and the user wants a faster response
- Running in CI or a context where services aren't accessible
- The task is purely skill-selection and service state is irrelevant

When `--no-services` is set, the `Services:` section of the oracle prompt is replaced with
a single line: `(service health check skipped — use without --no-services for live status)`

---

## Config Defaults

These flags override behavior per-invocation. No config-file equivalents are needed for v1.
A future task could add `oracle.default_flags` to config if this becomes a common request.

---

## Oracle Log

All three flags must be reflected in the oracle log entry when `--llm` is also used. Add
an optional `flags` array to the log entry schema:

```json
{
  "version": 1,
  "timestamp": "...",
  "task": "...",
  "flags": ["--quick"],
  "env_snapshot": {...},
  ...
}
```

`flags` is `[]` when none are set. This is additive to the existing log schema — existing
entries without `flags` are valid.

---

## Design Constraints

- Single-file rule in force
- No new dependencies
- No behavior changes to existing `perseus suggest` invocations without these flags
- Backward compatible oracle log: new `flags` field is optional; old entries remain valid

---

## Acceptance Criteria

- [ ] `--quick` produces oracle prompt with no services or session sections
- [ ] `--category <name>` restricts skills scan to the named subdirectory
- [ ] `--category` emits warning and falls back to full scan when directory not found
- [ ] `--no-services` skips HTTP/docker health checks; replaces services section with
  a "(skipped)" note
- [ ] When `--llm` is also passed, oracle log entry includes `flags` array
- [ ] Tests: `--quick` prompt structure, `--category` scan restriction, `--category`
  fallback, `--no-services` prompt content, `flags` in log entry
- [ ] `spec/oracle.md` interface section marked as implemented (no spec changes needed;
  these flags are already specified)

---

## Notes

- `--quick` is the most-used of the three in practice. Make it snappy. The point is that
  it should feel near-instant compared to a full `suggest` with service checks.
- `--no-services` and `--quick` are not mutually exclusive, but `--quick` implies
  `--no-services`. If both are passed, treat as `--quick`.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `--quick` emits a stripped prompt (skills only); implies `--no-services`
- `--no-services` replaces Services section with `(service health check skipped — use without --no-services for live status)`
- `--category <name>` restricts skill scan; falls back to full scan with `> ⚠` warning when directory absent
- Oracle log entries now include `flags: [...]` array (backward compatible — legacy entries valid without it)
- `--quick` no longer takes an early-return shortcut; same code path serves `--llm` callers
- Tests cover prompt shape, flag-array, fallback warning
