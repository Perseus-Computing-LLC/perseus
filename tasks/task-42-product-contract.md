---
id: task-42
title: Phase 16A product contract
status: open
priority: high
scope: medium
claimed_by: null
created: 2026-05-19
closed: null
phase: 16
theme: "Product Contract and Context Packs"
depends_on:
- task-41
blocks:
- task-43
- task-45
- task-48
- task-51
opened: '2026-05-19'
---

## Why

Perseus has many powerful surfaces, but a product needs a crisp promise. Before
installation, deployment, adapters, or release work, define what v1 guarantees,
what is intentionally out of scope, and where the trust boundary sits.

## What

- Create a v1 product contract document.
- Define supported platforms, assistant flows, and stable CLI surfaces.
- Define resolver-first behavior and how optional cited synthesis fits.
- Identify what counts as deployable for CLI, service, and container modes.
- Link the contract from README, ROADMAP, and HANDOFF.

## Acceptance Criteria

1. A new user can read one document and understand what Perseus v1 promises.
2. The contract lists stable commands, config files, state directories, and trust defaults.
3. The contract distinguishes local CLI, adapter, and managed-runtime deployments.
4. Non-goals are explicit, including no uncited generated context and no required LLM.
5. Docs render cleanly and tests pass.

## Non-goals

- Do not change runtime behavior.
- Do not add packaging or installer code.
- Do not weaken the single-file or `pyyaml` constraints.
