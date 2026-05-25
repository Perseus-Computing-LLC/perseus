---
id: task-39
title: Phase 15A cited synthesis guardrails
status: completed
priority: high
scope: medium
claimed_by: codex
created: 2026-05-19
closed: 2026-05-19
phase: 15
theme: "Cited Synthesis Under Scarcity"
depends_on:
- task-38
blocks:
- task-40
- task-41
opened: '2026-05-19'
---

## Why

Phase 15 must not turn Perseus into a generic prose generator. The useful
bounded-curator surface is cited synthesis: compact claims that preserve
relationships across sources the consuming assistant may not otherwise receive
in full.

The governing rule is stronger than a contradiction check:

> The LLM is a drafter, not an authority. No citation, no claim.

## What

- Add an explicit `perseus synthesize` command.
- Accept a question and one or more source files.
- Build a line-numbered source bundle for an LLM drafter.
- Keep LLM drafting disabled by default.
- Validate model output as structured claims with exact source quotes.
- Drop claims with missing, malformed, or non-matching citations.
- Leave normal `perseus render` output unchanged.

## Acceptance Criteria

1. `generation.enabled` defaults to `false`.
2. `perseus synthesize` without `--llm` prints the prompt and does not generate
   claims.
3. `perseus synthesize --llm ...` refuses to run generation unless
   `generation.enabled: true` or `--enable-generation` is present.
4. Accepted claims contain text plus at least one exact quote citation with
   source id, path/label, and line range.
5. Uncited or invalid claims are dropped and reported separately.
6. JSON output separates `claims`, `dropped_claims`, `sources`, model metadata,
   and guardrail metadata.
7. Tests cover prompt construction, disabled generation, accepted citations, and
   dropped claims.

## Non-goals

- Do not add `@read` elaboration.
- Do not add a render-time generated section.
- Do not replace resolved directive output.
- Do not treat confidence scores as a substitute for citation validation.

## Completed

- Added `generation` config with default-off LLM drafting.
- Added `perseus synthesize <question> --source FILE` with optional
  `--llm`, `--model`, `--model-url`, `--enable-generation`, and `--json`.
- Added source safety checks, line-numbered source prompt construction, JSON
  extraction, exact quote citation validation, and dropped-claim reporting.
- Added focused tests in `tests/test_synthesis.py`.
- Documented the Phase 15A contract in `docs/CITED_SYNTHESIS.md`, the roadmap,
  README, handoff, and specs.
