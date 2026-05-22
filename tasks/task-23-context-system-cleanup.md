---
id: task-23
title: "Perseus context system cleanup: commit Mnēmē diff, fix ROADMAP constraint, homelab context overhaul"
status: open
scope: medium
depends_on: []
claimed_by: null
opened: 2026-05-22
closed: null
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
- [ ] All commits on `origin/main`
