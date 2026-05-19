---
id: task-21
title: Task 21 — Trained Pattern Extraction (Phase 9.2)
status: in_progress
scope: large
depends_on:
  - task-12
  - task-20
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: null
phase: 9.2
---

# Task 21 — Trained Pattern Extraction

## Context

Mnēmē today distills a narrative deterministically. The `## Patterns &
Anti-patterns` section is currently produced by simple rules:
- count repeated tool/skill names across checkpoints
- count repeated failure/recovery sequences
- flag near-duplicates

This works for obvious patterns (the same skill used 10 times in a week)
but misses subtle ones (the user's *style* — "always pairs database
migrations with a schema diff page" or "writes the test BEFORE the fix
for security tasks, AFTER the fix for feature work").

P9.2 replaces the rule-based pattern extractor with a Daedalus-trained
model output that captures these signals. The training data is the labeled
oracle log (task-06 + task-20) joined with the checkpoint stream.

## Design

This is the **first task where Perseus expects an actual trained model to
exist**. The work splits into two halves:

### Half 1 — Plumbing (in scope; this task)

1. Add `memory.pattern_extractor` config key with values:
   - `"deterministic"` (default — current behavior, no model required)
   - `"daedalus"` (requires `llm.daedalus_model` to be configured + serving)
2. Refactor `_extract_patterns_from_checkpoints()` to dispatch on this key
3. Implement the `"daedalus"` path: build a prompt from recent checkpoints +
   oracle log, call `run_llm("daedalus", ...)`, parse the response as a
   markdown bullet list, validate, return
4. **Graceful fallback:** if the daedalus call fails (model not running,
   timeout, etc.) emit a stderr warning AND fall through to the
   deterministic path. Mnēmē must never break because a model is unavailable.
5. New CLI flag: `perseus memory compact --pattern-extractor daedalus` overrides config

### Half 2 — Model training (OUT OF SCOPE for this task)

Training a model is a user concern (compute, dataset curation, eval). This
task does NOT:
- ship a training script
- prescribe a model architecture
- bundle a pre-trained model
- assume any specific framework (HF, llama.cpp, mlx, etc.)

What it DOES:
- document the expected prompt shape in spec/components.md § 6
- document the expected response shape (markdown bullet list, one pattern
  per line, ≤ 80 chars per bullet)
- document the dataset export that produces the training set
  (`perseus oracle export --include-inferred --format daedalus-patterns`)

## Acceptance criteria

1. `memory.pattern_extractor` config key with two valid values
2. `_extract_patterns_from_checkpoints()` dispatches based on the key
3. Daedalus path falls back to deterministic on any failure with stderr warning
4. `perseus memory compact --pattern-extractor daedalus` overrides config
5. `perseus oracle export --format daedalus-patterns` exports a JSONL file
   with `{prompt: ..., completion: ...}` pairs derived from labeled checkpoints
6. Tests: dispatch routing, fallback path, override CLI flag, export shape
7. spec/components.md § 6 (Daedalus) extended with the prompt/response contract

## Non-goals

- Shipping or recommending a specific model
- Training automation
- Multi-model A/B comparison (Phase 10+)

## Start here

1. Claim the task: flip frontmatter `status: in_progress` and
   `claimed_by: <model name>`.
2. Verify task-20 is complete (inferred labels need to exist for the
   export to be useful).
3. Add `pattern_extractor: deterministic` to the `memory:` config block.
4. Find the existing pattern extractor function in `perseus.py` and refactor
   to a dispatch point.
5. Implement the daedalus path with try/except → deterministic fallback.
6. Add `--format daedalus-patterns` to `perseus oracle export`.
7. Tests + docs + commit + push.
8. Add a `# Completed` section.
