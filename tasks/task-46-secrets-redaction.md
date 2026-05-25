---
id: task-46
title: Phase 17B secrets and redaction
status: closed
priority: high
scope: large
claimed_by: hermes
created: 2026-05-19
closed: 2026-05-19
phase: 17
theme: "Trust, Privacy, and Local Policy"
depends_on:
- task-45
blocks:
- task-47
- task-54
opened: '2026-05-19'
---

## Why

Resolved context may include environment variables, config files, logs, or model
prompts. Product deployments need deterministic redaction before data enters
rendered files, synthesis prompts, logs, or HTTP responses.

## What

- Add configurable secret patterns and default high-signal detectors.
- Apply redaction to render output, synthesis prompt construction, oracle logs,
  and serve responses where appropriate.
- Report redaction counts without revealing secrets.
- Keep raw local source files unchanged.

## Acceptance Criteria

1. Common token/key/password shapes are redacted in output.
2. Redaction applies consistently across render, synthesize, logs, and serve fixtures.
3. Users can add workspace-specific redaction patterns.
4. JSON output reports redaction metadata without secret values.
5. Tests cover default and configured redactions.

## Non-goals

- Do not promise perfect DLP.
- Do not mutate source files.
- Do not log original secret values.

## Completed

**2026-05-19 — closed by hermes.**

Shipped:
- `DEFAULT_REDACTION_RULES` table in `perseus.py` covering OpenAI / Anthropic
  / GitHub / AWS / Slack / Authorization-Bearer / JWT / PEM-private-key /
  long-hex-secret. Anthropic is checked before OpenAI via a negative lookahead
  so `sk-ant-...` never gets misclassified.
- `redact_text(text, cfg) -> (str, report)` — the single redaction entry point.
  Report is JSON-safe: `{enabled, total, counts: {rule_name: n}, rules_active}`.
  Counts only; never the secret value (AC #4).
- `_compile_redaction_rules(cfg)` merges defaults + workspace `redaction.patterns`;
  invalid regexes are silently skipped so config typos don't break rendering.
- `redaction:` config section in DEFAULT_CONFIG: `enabled: True`,
  `include_defaults: True`, `patterns: []`. Opt-out is per-workspace.
- Trust-boundary wiring:
    - `cmd_render` → output (file or stdout) is redacted; source file on disk
      is **not** modified (non-goal #2 verified by test).
    - `cmd_synthesize` → answer / rendered / prompt / raw_response strings
      and string fields inside `claims`/`sources`/`accepted`/`dropped` are
      redacted. JSON output gains a `result["redaction"]` block.
    - `perseus serve` → `/context`, `/narrative`, `/health`, `/agora`,
      `/checkpoint/latest`, `/oracle/log` all pass through `redact_text`
      before returning a body (AC #2).
- `perseus trust [--json]` now reports the redaction subsection
  (`enabled / include_defaults / custom_patterns / rules_active`) alongside
  the permission profile (Phase 17A/B integration).
- Bearer-header rule preserves the `Authorization: Bearer ` prefix via a
  capture group, so consumers can still see the header shape for debugging
  while the token is wiped.
- 19 new tests in `tests/test_redaction.py` covering all default rules,
  workspace pattern merge, `include_defaults: false`, custom replacement
  strings, invalid-pattern skip, no-secret-in-report guarantee (AC #4),
  cmd_render source-immutability, trust-json shape, and strict-profile
  interaction (strict does not silently disable redaction).

Test baseline after this task: **374 passed** (was 355 after task-45).
No skips.

Notes for the next contributor:
- The redaction layer is `text → text + counts`. For task-47 (audit
  log/trust report) we can emit a `redactions_total` aggregate per command
  invocation simply by capturing the report when each trust-boundary path
  calls `redact_text`.
- `redaction.patterns` accepts arbitrary user regex. For task-54 (golden
  eval) we'll want a golden fixture covering each default rule plus a
  workspace-pattern example, so the regression bar is concrete.
