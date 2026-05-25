---
id: task-40
title: Phase 15B cross-source consistency synthesis
status: completed
priority: medium
scope: medium
created: 2026-05-22
phase: 15
theme: Cited Synthesis Under Scarcity
depends_on:
- task-39
blocks:
- task-41
opened: '2026-05-22'
closed: '2026-05-22'
claimed_by: null
---
## Why

Task-39 shipped the cited-claim contract and `perseus synthesize`. This task
implemented cross-source consistency mode — detecting contradictions across
sources via `perseus synthesize --consistency-mode`.

**Status: Complete.** The consistency pipeline is fully implemented:
`build_consistency_prompt` → LLM → `_validate_consistency_conflicts` →
separate `conflicts`/`claims` arrays in output. The `@synthesize` directive
passes `consistency_mode` through, the CLI supports `--consistency-mode`,
and both human and JSON output surfaces work.

## What

- ✅ `perseus synthesize --consistency-mode` compares sources for agreement/conflict
- ✅ `build_consistency_prompt` generates a cross-source audit prompt
- ✅ `_validate_consistency_conflicts` validates the conflicts array
- ✅ Conflict outputs cite both conflicting sources with line numbers
- ✅ Non-conflicting cross-source relationships surfaced as cited claims
- ✅ Citation gate enforced: every claim must cite exact source lines
