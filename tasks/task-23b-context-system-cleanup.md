---
id: task-23
title: "Perseus context system cleanup: commit Mnēmē diff, fix ROADMAP constraint, homelab context overhaul"
status: completed
scope: medium
depends_on: []
claimed_by: hermes-agent
opened: 2026-05-22
closed: 2026-05-22
---

# Task 23: Context System Cleanup

## Goal

Three things that are broken or stale, collected into one task:

1. **Commit the uncommitted Mnēmē diff** — 4 files (agora.py, checkpoint.py, cli.py, registry.py) have been sitting unstaged with bugs #1-3 and features #1-4 fixed/added. They need to be built, tested, and pushed.

2. **Fix ROADMAP.md constraint #1** — still says "single file, no package structure" but the project shipped `src/perseus/` module tree. AGENTS.md has the correct wording; ROADMAP.md needs to match.

3. **Homelab context file overhaul** — `/workspace/perseus/.perseus/context.md` renders the homelab `.hermes.md`. Several sections are dead weight or actively noisy:
   - Docker Containers section always blank (no socket access from agent container)
   - Cron Jobs section shows raw `ls` output, not job summaries
   - Skills table is ~100 rows; only ~20 are homelab-relevant
   - `@session count=5` pulls in cron-job sessions as titles
   - Perseus CLI service entry uses source path, not installed path
   - Version tag is `@perseus v0.4`, should be `v0.8`
   - Requires shipping `category=` filter for `@skills` directive first (subtask 3a)

## Implementation Plan

Full plan with step-by-step tasks at:
`.hermes/plans/2026-05-22-context-system-cleanup.md`

## Acceptance Criteria

- [ ] All 4 unstaged files committed and pushed (with regenerated `perseus.py`)
- [ ] `python3 -m pytest tests/ -q` passes (≥ 496 tests)
- [ ] ROADMAP.md constraint #1 matches AGENTS.md wording
- [ ] `@skills` directive supports `category=` / `include=` filter modifier
- [ ] Homelab context renders clean: no Docker section, trimmed skills, useful cron output or no cron section
- [x] All 4 unstaged files committed and pushed (with regenerated `perseus.py`)
- [x] `python3 -m pytest tests/ -q` passes (535 passed, 1 skipped)
- [x] ROADMAP.md constraint #1 matches AGENTS.md wording
- [x] `@skills` directive supports `category=` / `include=` filter modifier (comma-separated multi-value)
- [x] Homelab context renders clean: removed Docker/Cron sections, skills filtered to 5 relevant categories, session count=3, Perseus CLI uses installed path, version bumped to v0.8
- [x] All commits on `origin/main`

## Completed

All three goals delivered in full:

1. **Mnēmē diff committed** — bugs #1-3 and features #1-4 (agora.py, checkpoint.py, cli.py, registry.py) built, tested, and pushed. 535 tests pass.
2. **ROADMAP.md constraint #1 fixed** — now correctly reflects the `src/perseus/` module architecture.
3. **Homelab context overhaul** — removed Docker Containers and Cron Jobs sections (no-signal), added `category=` multi-value filter to `@skills` (subtask 3a: `0e28f28`), context now renders 46 curated skills across 5 categories, `@session count=3`, Perseus CLI entry uses installed `perseus --version` command, version tag bumped to `v0.8`.

**Bonus fix:** Discovered installed `perseus` CLI was running a stale package build without the multi-value `category=` filter. Rebuilt artifact via `python scripts/build.py` and reinstalled via `pip install -e .` — `perseus v1.0.1` is now current on the installed binary.
