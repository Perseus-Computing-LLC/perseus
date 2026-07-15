# Startup-Memory Benchmark Pack

Copy this into `.perseus/benchmarks/startup-pack.md` in your workspace (or keep
it here) and run it in a **fresh** session that has your startup block loaded.
Replace `<TODAY'S TASK>` with the actual task. Score each answer 0–2 using the
rubric in [`../docs/startup-memory-benchmark.md`](../docs/startup-memory-benchmark.md)
(8 = excellent). Re-run after Perseus / Vault upgrades to catch regressions.

> Before running: re-render the block (`perseus render <source> --format
> agents-md`), confirm wiring with `perseus doctor`, and prune low-signal
> entries with `perseus_vault_hygiene`.

---

## 1. Startup-context quality
From the startup context you already have (do **not** retrieve anything yet),
what high-value facts are present, and what important gaps remain for
**<TODAY'S TASK>**? List facts and gaps separately.

## 2. Retrieval-plan quality
Turn those gaps into a **minimal** retrieval plan — the fewest lookups that
would close them. No lookup should duplicate a fact already in startup context.

## 3. First-move discipline
What one lookup would you do **first**, and what are you intentionally
**deferring** (and why)?

## 4. First-command quality
Assuming tool/command discovery is already done, what is the single best first
retrieval command/query? Give the exact tool, query text, and filters
(category / scope / date). Prefer a targeted query over a broad scan.

---

### Score sheet

| Run date | P1 | P2 | P3 | P4 | Total | Perseus / Vault version | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |

A falling total across runs after a change = a startup-memory regression;
bisect the change (block content, context profile, Vault ranking).
