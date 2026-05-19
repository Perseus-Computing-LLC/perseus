---
id: task-45
title: Phase 17A permission profiles
status: closed
priority: high
scope: large
claimed_by: hermes
created: 2026-05-19
closed: 2026-05-19
phase: 17
theme: "Trust, Privacy, and Local Policy"
depends_on:
- task-42
blocks:
- task-46
- task-47
opened: '2026-05-19'
---

## Why

Perseus touches files, shell commands, optional models, serve endpoints, and
agent subprocesses. Product users need named safety modes instead of discovering
individual config flags one at a time.

## What

- Add named permission profiles such as `strict`, `balanced`, and `power-user`.
- Map each profile to render, agent, query, serve, and generation defaults.
- Add CLI/docs showing the active profile and effective permissions.
- Preserve explicit config overrides.

## Acceptance Criteria

1. Permission profiles are documented and testable.
2. Effective config is deterministic and visible in human/JSON output.
3. Existing configs without profiles keep current behavior.
4. Strict mode disables shell, agent subprocesses, unsafe serve binds, and generation.
5. Tests cover profile defaults and override precedence.

## Non-goals

- Do not add OS sandboxing.
- Do not silently change existing user config.
- Do not make generation default-on.

## Completed

**2026-05-19 — closed by hermes.**

Shipped:
- `PERMISSION_PROFILES` registry in `perseus.py` with three profiles:
  `strict` (locks down shell/agent/services/generation), `balanced`
  (mirrors today's defaults so users can pin), `power-user` (enables
  `@services command:` but keeps generation opt-in and workspace
  boundary enforced).
- `permissions.profile` config key (default `null` → no-op, preserving
  existing behavior for all current configs — AC #3).
- `load_config()` layering: DEFAULT_CONFIG → profile → global → workspace.
  Explicit user values always override the profile.
- Unknown profile names are ignored (config still loads), and `perseus
  trust` surfaces the mismatch so the operator can catch typos.
- `perseus trust [profile]` command with human and `--json` output. Reports
  the configured profile, the canonical applied profile, and the *effective*
  per-key permissions after merge.
- New config sections: `permissions:` and `serve:` (the latter promotes
  the previously implicit `serve.bind` default to a first-class key so
  profiles can govern it).
- Spec doc `spec/data-model.md` updated with the new config sections and
  the layering rules.
- 18 new tests in `tests/test_permission_profiles.py` covering: each
  named profile, layering precedence, explicit-override-wins (AC #3),
  unknown-profile fallback (AC #5), workspace-beats-global precedence,
  and `cmd_trust` human + JSON output (AC #2).
- Also bumped `_PERSEUS_VERSION` to 0.9.0 to match the CLI banner;
  previously the constant lagged by one minor.

Test baseline after this task: **355 passed** (was 337). No skips.

Notes for the next contributor:
- `perseus trust` is intentionally extensible — task-47 (audit log trust
  report) should add a sibling subcommand (e.g. `perseus trust audit`).
  The `trust_command` argparse dest is already wired up for that.
- `serve.bind` is now a real config key. Task-48 (authenticated serve)
  can drop authentication/token settings into `serve:` without further
  scaffolding.
