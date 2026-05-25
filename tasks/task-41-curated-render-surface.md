---
id: task-41
title: Phase 15C optional curated render surface
status: completed
priority: medium
scope: medium
created: 2026-05-22
phase: 15
theme: Cited Synthesis Under Scarcity
depends_on:
- task-40
blocks: []
opened: '2026-05-22'
closed: '2026-05-22'
claimed_by: null
---
## Why

The `@synthesize` directive exists in the renderer and the curated render surface
implementation was verified. Generated sections are plainly labeled, model
failure leaves ordinary render output unchanged, and the citation gate drops
uncited claims.

**Status: Complete.** All acceptance criteria verified:
- `@synthesize` renders labeled generated content beside resolved context
- `perseus render --json` separates `resolved` and `generated` keys
- Missing LLM produces clean render output, no crash
- `generation.enabled: false` suppresses all synthesis
- Model failure reports error inline, doesn't break the render

## What

- ✅ `@synthesize question="..." source="a,b"` renders labeled generated content
- ✅ Generated sections marked "(generated — not resolver output)"
- ✅ Conflicts surfaced as "Source disagreements" section
- ✅ Uncited claims dropped with count reported
- ✅ `generation.enabled` gate respected (silent skip when disabled)
- ✅ Graceful degradation: missing source → warning, LLM failure → error without crash
