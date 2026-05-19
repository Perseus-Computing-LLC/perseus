---
id: task-41
title: Phase 15C optional curated render surface
status: closed
priority: medium
scope: large
claimed_by: hermes
created: 2026-05-19
closed: '2026-05-19'
phase: 15
theme: "Cited Synthesis Under Scarcity"
depends_on:
- task-40
blocks: []
opened: '2026-05-19'
---

## Why

Render-time synthesis is the highest-trust-risk part of Phase 15. It should only
exist after the explicit command surface proves useful and the cited-claim
contract has been exercised against cross-source consistency work.

## What

- Add an opt-in way to include curated synthesis beside resolved context.
- Keep generated sections plainly labeled.
- Separate resolved and generated content in any JSON surface.
- Preserve normal render output when generation is disabled or the model fails.
- Reuse `perseus synthesize` validation; do not create a parallel trust path.

## Acceptance Criteria

1. Generated render sections are disabled by default.
2. Resolved directive output is never replaced or edited by generated prose.
3. Every generated render claim has exact source citations.
4. Model failure, parse failure, or citation failure leaves ordinary render
   output unchanged except for an explicit warning if configured.
5. JSON output separates `resolved` and `generated` surfaces.
6. Tests cover disabled mode, enabled mode, model failure, dropped uncited
   claims, and normal render preservation.
7. `python -m pytest tests/ -q` passes.

## Non-goals

- Do not make Perseus a primary prose generator.
- Do not add required dependencies.
- Do not allow uncited generated text into assistant context.
