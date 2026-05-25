---
id: task-63
title: Task 63 — Oracle → Pythia Rename
status: completed
priority: medium
scope: medium
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: housekeeping
theme: "Pythia naming consistency"
depends_on: []
blocks: []
opened: '2026-05-19'
---

# Task 63 — Oracle → Pythia Rename

**Status:** completed
**Claimed by:** codex
**Closed:** 2026-05-19

**Phase:** Housekeeping  
**Size:** Medium (2–4 hours)  
**Risk:** Low — internal naming only, no user-facing CLI surface changes  
**Depends on:** None  
**Blocks:** None (cosmetic consistency only)

---

## Background

Perseus's tool-recommendation subsystem was originally called "the oracle." During branding work, it was renamed **Pythia** — after the Oracle of Delphi — in user-facing surfaces, documentation, and the spec narrative. However, the rename was never completed in the codebase internals.

The result is a split identity:
- **User-facing / conceptual:** "Pythia" (spec narrative, README mythology section)
- **Internal / config / code:** "oracle" (config keys, log filenames, function names, spec filenames)

This task closes that gap by completing the rename throughout the codebase. It is purely cosmetic — no behavior changes, no API changes, no CLI surface changes.

---

## Scope

### Files to rename

| Current | Target |
|---|---|
| `spec/oracle.md` | `spec/pythia.md` |

### Config key rename (`.perseus/context.md` and `config.yaml` schema)

| Current key | New key |
|---|---|
| `oracle.skill_dir` | `pythia.skill_dir` |
| `oracle.stale_skill_days` | `pythia.stale_skill_days` |
| `oracle.backend` | `pythia.backend` |
| `oracle.provider` | `pythia.provider` |
| `oracle.model` | `pythia.model` |

**Backward compatibility required:** Read both `pythia.*` (new) and `oracle.*` (legacy) from config. If `oracle.*` keys are present, use them and emit a deprecation warning to stderr: `[perseus] config: 'oracle' key is deprecated, rename to 'pythia'`. Do not hard-break existing configs.

### Internal identifiers in `perseus.py`

The following internal identifiers should be renamed. These are not part of any public API or CLI surface — they are internal Python names only.

| Current | New |
|---|---|
| `cfg["oracle"]` | `cfg["pythia"]` (with legacy fallback — see above) |
| `_read_all_oracle_entries()` | `_read_all_pythia_entries()` |
| `_deterministic_patterns_body(oracle_entries, ...)` | keep param name or rename to `pythia_entries` |
| `_daedalus_patterns_body(oracle_entries, ...)` | same |
| `_extract_patterns_section(oracle_entries, ...)` | same |
| `_truncate_oracle_for_llm(...)` | `_truncate_pythia_for_llm(...)` |
| `oracle_entries_processed` (key in Mnēmē return dict) | `pythia_entries_processed` |
| `PERSEUS_HOME / "oracle_log.jsonl"` | `PERSEUS_HOME / "pythia_log.jsonl"` |

**Migration note for `oracle_log.jsonl`:** On first run after rename, if `~/.perseus/oracle_log.jsonl` exists and `~/.perseus/pythia_log.jsonl` does not, rename the file automatically and emit: `[perseus] migrated oracle_log.jsonl → pythia_log.jsonl`. Do not silently lose existing log data.

### Documentation

| File | Change needed |
|---|---|
| `spec/oracle.md` → `spec/pythia.md` | Rename file; update title `# Tool Oracle` → `# Pythia — Tool Oracle`; replace `the oracle` with `Pythia` throughout |
| `spec/overview.md` | Update references from `oracle.md` → `pythia.md`; `oracle` subsystem → `Pythia` |
| `spec/components.md` | Same |
| `spec/data-model.md` | Update config schema docs: `oracle:` key → `pythia:` (document both for compat) |
| `docs/HERMES_INTEGRATION.md` | Already uses "Pythia oracle" in prose — update any remaining `oracle` config key examples |
| `docs/EXAMPLES.md` | Update any `oracle:` config blocks to `pythia:` |
| `docs/AGENT_SURFACES.md` | Update any `oracle` references |
| `docs/RESOLVER_VS_GENERATOR.md` | Prose references |
| `docs/PERSEUS_PRODUCT_REPORT.md` | Prose references |
| `docs/PRODUCT_CONTRACT.md` | Prose references |
| `docs/use-cases.md` | Prose references |
| `README.md` | Line 16: `perseus oracle drift` etc. — CLI surface stays `perseus oracle` (see below) |
| `AGENTS.md` | Line 51: `oracle.md ← Pythia (tool oracle) design` → update path to `pythia.md` |

### CLI surface — **do NOT change**

The `perseus oracle` subcommand family (`accept`, `reject`, `log`, `export`, `infer-labels`, `outcomes`, `drift`) stays as `perseus oracle`. This is a user-facing CLI surface. Renaming it would be a breaking change requiring a deprecation cycle. Out of scope for this task.

Similarly, `@drift` directive description referencing "Daedalus drift report" is intentional — Daedalus is the drift-detection backend name and stays.

---

## Acceptance Criteria

1. `grep -r '"oracle"' perseus.py` returns only CLI subcommand strings (e.g. `"oracle"` as an argparse command name), not config key lookups
2. `grep -rn 'oracle_log' perseus.py` returns zero results (log file is now `pythia_log.jsonl`)
3. `~/.perseus/oracle_log.jsonl` is auto-migrated to `~/.perseus/pythia_log.jsonl` on first run if it exists
4. Existing configs with `oracle:` keys still work with a deprecation warning
5. `spec/pythia.md` exists; `spec/oracle.md` is removed
6. `AGENTS.md` references `spec/pythia.md`
7. All 393+ existing tests pass
8. New tests:
   - `test_oracle_config_legacy_compat` — config with `oracle:` key works and emits deprecation warning
   - `test_pythia_log_migration` — if `oracle_log.jsonl` exists and `pythia_log.jsonl` does not, migration runs automatically
9. No deferred cleanup markers left behind

---

## Notes for the developer

- The `oracle` name in the **`perseus oracle` CLI subcommand** is intentionally preserved. Don't touch argparse command names.
- Daedalus is a separate internal component (the local fine-tuned scoring model). Don't conflate with Pythia. The `_daedalus_patterns_body()` function and `backend: daedalus` config key are correct and stay.
- The `oracle_entries` parameter in internal helper functions is purely a Python local variable name — rename these as you go but they carry no external contract.
- Run `python -m pytest tests/ -x` frequently. The test suite is fast (< 2s collection).
- This is a `chore` commit, not a `feat`. Commit message: `chore: rename oracle internals to pythia (cosmetic consistency)`

---

## Completed

- Renamed the spec file to `spec/pythia.md` and updated current docs/spec references.
- Moved internal config reads/writes to `pythia`, with legacy `oracle:` config accepted and warned.
- Moved the recommendation log to `pythia_log.jsonl`, with one-time migration from the legacy filename.
- Renamed Mnēmē's Pythia high-water mark to `pythia_entries_processed` while reading legacy frontmatter.
- Added tests for legacy config compatibility and log migration.
