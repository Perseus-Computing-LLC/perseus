---
id: task-56
title: Phase 20C headless watch mode
status: completed
priority: medium
scope: large
claimed_by: Codex
created: 2026-05-19
closed: '2026-05-20'
phase: 20
theme: Managed Runtime and Deployment Modes
depends_on:
- task-43
- task-50
blocks:
- task-58
opened: '2026-05-19'
---
## Why

Schedulers are platform-specific. A portable watch mode gives users a simple
way to keep context outputs fresh in local development, containers, and CI-like
environments.

## What

- Add a headless `perseus watch` or equivalent mode.
- Watch a context pack or source file and refresh configured outputs.
- Debounce file changes and report failures without exiting unless configured.
- Keep behavior local and non-mutating except for configured render outputs.

## Acceptance Criteria

1. Watch mode works from a source file or context pack.
2. It refreshes outputs when inputs change.
3. It has clear logging and exit behavior.
4. Tests cover debounce logic and render failure handling without flaky sleeps.
5. Docs compare watch mode to cron/launchd/systemd.

## Non-goals

- Do not replace authenticated serve.
- Do not add filesystem watcher dependencies.
- Do not watch outside the workspace unless explicitly allowed.

## Implementation Notes

**No filesystem watcher deps.** Constraint #2 (pyyaml only). Implement as a polling loop:
check source file mtimes on a configurable interval (default 5s, config key
`watch.poll_interval_s`). Track mtime per source file; re-render on change.

**Command:** `perseus watch [--source FILE] [--output FILE] [--interval N]`
- `--source` defaults to `.perseus/context.md` in cwd (same as render default)
- `--output` defaults to `.hermes.md` (mirrors `render --output` default)
- Logs to stderr: `[watch] rendered → <output> (changed: <source>)` on each render
- Logs to stderr: `[watch] render error: <msg>` on failure; keeps watching unless
  `--exit-on-error` is passed
- SIGINT/SIGTERM exits cleanly with a final log line

**Debounce:** After a detected change, wait one additional poll interval before
rendering to avoid rapid successive renders when editors write multiple times.
Track the last-rendered mtime rather than using wall-clock timers to keep tests
deterministic (monkeypatch mtime, no `time.sleep` in tests).

**Context pack support:** If a `pack.yaml` exists in the workspace, resolve source
files from the pack's `sources:` list rather than a single `--source` file.

**Test approach:** Monkeypatch `os.path.getmtime` and `cmd_render` rather than
creating real file watchers or sleeping. Cover: initial render on startup, re-render
on mtime change, no re-render when mtime unchanged, error handling with continue,
SIGINT exit path (mock with KeyboardInterrupt).

## Completed

- Added `perseus watch` with `--source`, `--output`, `--workspace`,
  `--manifest`, `--interval`, `--exit-on-error`, and
  `--allow-outside-workspace`.
- Added `watch.poll_interval_s` config with a default of 5 seconds.
- Implemented a dependency-free polling loop around `cmd_render`; it refreshes
  either a single source/output pair or every `renders:` target in
  `.perseus/pack.yaml` when no single-target override is provided.
- Implemented deterministic debounce by requiring changed source mtimes to stay
  stable for one additional poll cycle before rendering.
- Render failures log to stderr and continue by default; `--exit-on-error`
  returns non-zero after the first failure.
- SIGINT/SIGTERM request clean shutdown and emit `[watch] stopped`.
- Updated README, component spec, data model spec, container docs, product
  contract, roadmap, changelog, and product report.
- Added `tests/test_watch.py` covering default and pack targets, debounce,
  unchanged mtimes, failure behavior, keyboard interrupt shutdown, and
  outside-workspace gating.

Validation:

- `python3 -m pytest tests/test_watch.py -q` → `8 passed`
- `python3 -m pytest tests/test_watch.py tests/test_container.py tests/test_platform_misc.py -q` → `54 passed, 1 skipped`
- `python3 -m pytest tests/ -q` → `466 passed, 2 skipped`
