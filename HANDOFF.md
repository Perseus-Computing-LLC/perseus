# Perseus — Agent Handoff

**Date:** 2026-05-19  
**From:** Hermes (project owner's assistant)  
**To:** Distinguished Engineer (Rovo Dev or equivalent)  
**Branch:** `main` — commit to main directly, no feature branches needed  
**Scope:** Phases 18C through 21 (tasks 50–59)

---

## State at Handoff

```
411 tests passing (0 failing, 1 skipped — TCP LSP smoke, expected in sandbox)
Version: alpha v0.9.0
Last commit: cfd7016
```

Phase 18B is complete (task-49 ✅). The release artifact machinery
(`scripts/release.sh`, `dist/`, `SHA256SUMS`) is built and tested.

---

## Your Scope

You own **tasks 50–59 in sequence**. Do not touch Phase 22 (tasks 60–62) — those
are reserved for the project owner.

| Task | Phase | Title | Priority | Scope |
|---|---|---|---|---|
| task-50 | 18C | Scheduler parity | medium | medium |
| task-51 | 19A | Adapter conformance harness | high | large |
| task-52 | 19B | Assistant profile gallery | high | medium |
| task-53 | 19C | VSCode extension release polish | medium | medium |
| task-54 | 20A | Authenticated serve mode | high | large |
| task-55 | 20B | Container image and compose | medium | medium |
| task-56 | 20C | Headless watch mode | medium | large |
| task-57 | 21A | Golden eval corpus | high | large |
| task-58 | 21B | Performance budgets | medium | medium |
| task-59 | 21C | Compatibility and migration suite | high | medium |

Work them in order. Each task has `depends_on:` in its frontmatter — respect the
dependency graph. The critical path is: **50 → 56 → 58** and **51 → 52 → 57 → 59**.

---

## Critical Rules (non-negotiable)

1. **`perseus.py` stays a single file.** Do not split it. `patch` not `write_file`.
2. **`pyyaml` is the only runtime dependency.** No new deps.
3. **All tests must pass before committing.** Run `python -m pytest tests/ -q`.
4. **Spec follows code.** Update `spec/*.md` when behavior changes.
5. **No `write_file` on `perseus.py`** — the file is ~6,000+ lines and `write_file`
   will silently truncate it. Use `patch`. If you need to verify line count:
   `wc -l perseus.py` (should be 5,800+). Recovery: `git checkout HEAD -- perseus.py`.
6. **Claim tasks via `perseus agora claim <id> --agent <name>` before starting.**
   Mark complete by adding `## Completed` section to the task file.

---

## Key Implementation Notes per Task

All tasks now have `## Implementation Notes` sections with concrete patterns, config
keys, command signatures, and test approaches. Read the full task file before starting.

### task-50 (scheduler parity)
Audit `perseus cron`, `perseus launchd`, `perseus systemd` outputs against actual
platform schedulers. Windows: document as deferred (not implementing Task Scheduler).
Update README scheduler section to match. Add smoke tests for generated scheduler output.

### task-51 (adapter conformance harness)
Create `tests/fixtures/adapters/<name>/` with `context.md`, `pack.yaml`, expected output
filename for: hermes, codex, claude-code, cursor, rovodev, generic. Add
`tests/test_adapter_conformance.py` parametrized over fixture dirs. Update
`spec/integration.md` with a conformance matrix table. CLI hook optional.

### task-52 (profile gallery)
Profiles already exist via `perseus init --profile`. This task ensures each has a
conformance fixture (from task-51), is discoverable via `--list-profiles`, and that
profile-generated files contain no hardcoded repo-local paths. Tests cover listing
and generation for all 6 profiles.

### task-53 (VSCode extension polish)
Extension is at `editors/vscode/`. Audit `package.json` commands against current LSP
command set (render, checkpoint, suggest, mutation gate). Add packaging doc
(`editors/vscode/RELEASE.md`). Smoke tests for diagnostics, completion, hover
round-trips via the existing LSP subprocess test harness in `tests/test_lsp.py`.
Do not publish to marketplace.

### task-54 (authenticated serve)
Static bearer token via `serve.auth_token` config. Non-loopback binds require
explicit override or token. `--generate-token` helper. Trust report `[serve]` section.
HTTP 401 for unauthorized requests. Full implementation notes in task file.

### task-55 (container image)
Minimal `Dockerfile` using the single-file runtime. `docker-compose.yaml` example
mounting workspace and Perseus home. `docs/CONTAINER.md` with trust implications.
Smoke tests skip if Docker not available (follow `test_installer.py` skip pattern).

### task-56 (headless watch mode)
`perseus watch` as polling loop — no filesystem watcher deps. `watch.poll_interval_s`
config (default 5). Debounce via mtime tracking, not wall-clock timers (keeps tests
deterministic). SIGINT exits cleanly. Context pack support. Full spec in task file.

### task-57 (golden eval corpus)
`tests/golden/<scenario>/` — 7 minimum scenarios documented in task file.
`tests/test_golden.py` parametrized over scenario dirs. `normalize_golden()` strips
volatile lines. `--update-golden` pytest flag to regenerate. Do not commit updated
goldens without reviewing the diff.

### task-58 (performance budgets)
`tests/test_perf_budgets.py` — all tests `@pytest.mark.slow`. Advisory by default
(warnings, not failures). `--enforce-budgets` flag for hard failures. Budget table
and `docs/PERFORMANCE.md`. watch command budget uses task-56 completion.

### task-59 (compatibility suite)
Fixtures for old `hermes:` config key (legacy migration), old checkpoint format,
old oracle log format, old Mnēmē narrative format, old federation manifest. Verify
current commands read them or produce clean migration errors. Document any intentional
breaking changes in `docs/MIGRATION.md`.

---

## Highest-Risk Tasks

**task-54 and task-56 are the two highest-risk tasks in this run.**

- **task-54 (auth serve):** The token check must be wired at all 5 trust-boundary
  sites. Missing any one of them gives a security property that holds in unit tests
  but silently fails in production. Before committing, grep:
  `grep -n "def cmd_render\|def cmd_synthesize\|def _serve_handle_request\|resolve_query\|resolve_agent\|services_command" perseus.py`
  and verify the auth check touches each surface.

- **task-56 (watch mode):** Adds a polling loop to the 6,000+ line file. Use `patch`
  for every edit — do not reconstruct or rewrite `perseus.py` wholesale. If a patch
  fails, use `git checkout HEAD -- perseus.py` and try a narrower patch. Verify after
  every edit: `wc -l perseus.py` (should stay above 5,800).

Both tasks need the full `--json` early-return audit on any new `cmd_*` functions:
search every `return` statement and confirm each one checks `args.json` if the
command supports it.

---

## Things to Watch Out For

- **Ghost completions.** If you think a task is already done, grep `perseus.py` for the
  key function/command before marking complete. Past AI contributors marked tasks done
  without writing code.
- **`--json` early-return audit.** Any command that gets a `--json` flag must check
  `args.json` on **every** return path, not just the happy path. Failure to do this
  is the most common class of bug in Perseus.
- **`_apply_permission_profile` precedence.** Profile applies BEFORE user config keys.
  Explicit user config always wins.
- **Test the `cmd_*` signature.** Every handler is `cmd_<name>(args, cfg)` — two args.
  `load_config(workspace=...)` has no path overload.
- **LSP hover safety.** Shell-executing directives (`@query`, `@agent`, `@services
  command:`) must not execute during LSP hover. They are in the `safe_for_hover=False`
  registry entries. Do not change this.

---

## How to Orient

```bash
# Check current state
python perseus.py --version
python -m pytest tests/ -q

# See open tasks
python perseus.py agora list

# Read a task
cat tasks/task-50-scheduler-parity.md

# Claim it
python perseus.py agora claim task-50 --agent "Rovo Dev"

# Work it, then mark complete
# Add ## Completed section to the task file, commit with:
# git commit -m "feat(task-50): scheduler parity — phase 18C complete"
```

---

## Stop Condition

**Stop after task-59.** Do not start task-60, task-61, or task-62.
Phase 22 (v1 release candidate, docs site, demo packs) is reserved for the
project owner to complete with their assistant. Leave `HANDOFF.md` in place
when you finish — update it with a completion summary at the end.

---

## Progress Update — 2026-05-20

### Completed in this pass

- **task-50 / Phase 18C scheduler parity** is complete.
- Scheduler docs and command help now distinguish the platform-agnostic core
  from platform-specific adapters:
  - `perseus render` remains the universal portable baseline.
  - `perseus cron` prints POSIX crontab entries on any host and installs only
    where `crontab` is available.
  - `perseus launchd` remains macOS-only.
  - `perseus systemd` remains Linux-only.
  - Native Windows Task Scheduler support is explicitly deferred; Windows users
    can use WSL cron, the printed render command, or their own scheduler.
- Added scheduler smoke coverage for cron output, launchd plist content,
  systemd units, and Windows-native deferral.
- Repaired the Phase 18B release script baseline on macOS/BSD shells:
  `_PERSEUS_VERSION` parsing no longer uses a fragile heredoc command
  substitution, and release tarballs use a GNU tar path when available with a
  portable BSD tar + `gzip -n` fallback.

### Current validation

- Focused release/platform suite: `51 passed`
- Full suite target after task-50: `413 passed, 1 skipped`

### Next Entry Point

Continue with **task-51 / Phase 19A adapter conformance harness**. Do not start
Phase 22 tasks 60-62.
