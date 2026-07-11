# Perseus + Vault: verified LLM savings statement

**75.1% fewer LLM dollars. +11.7 points MORE accurate. Read from the meter, not a marketing model.**

We ran the same 60 memory-recall tasks two ways, with the same model
(`gpt-4o-2024-08-06`) answering and the same official benchmark judge grading both:

| | LLM spend | tokens billed | accuracy |
|---|---:|---:|---:|
| Without Perseus (full context every call) | $15.71 | 6,250,823 | 55.0% |
| **With Perseus + Vault** | **$3.91** | **1,529,807** | **66.7%** |

Perseus + Vault loads only the context each task needs (4.1x fewer
tokens), so the model reads less, costs less, and answers better: long stuffed
prompts measurably LOSE accuracy on the tasks agents do most.

| task type | n | full context | Perseus + Vault |
|---|---:|---:|---:|
| Multi-session aggregation | 16 | 31% | **38%** |
| Temporal reasoning | 16 | 38% | **69%** |
| Updated facts (latest wins) | 9 | **89%** | 67% |
| Facts the user stated | 8 | 88% | **100%** |
| Facts the assistant stated | 7 | 86% | **100%** |
| User preferences | 4 | 25% | **50%** |

## Why you can trust this number

1. **Dollars come from a meter, not a spreadsheet.** Every model call in both
   arms was recorded as a usage event in a [Plutus](https://github.com/Perseus-Computing-LLC/plutus)
   ledger; the totals above are sums over that ledger, reproducible with one
   line of SQL against the shipped ledger file:
   `SELECT w.name, SUM(u.cost_micros)/1e6 AS usd FROM usage_events u JOIN workspaces w ON w.id=u.workspace_id GROUP BY w.id;`
2. **Accuracy is graded by the benchmark's own judge**, not ours: LongMemEval's
   official per-question-type prompts, pinned `gpt-4o-2024-08-06`, temperature 0,
   `answer_prompt: official-cot`.
3. **The task sample is stratified, not cherry-picked**: 60 questions drawn
   proportionally from all six LongMemEval question types, first-N per type in
   dataset order. Full methodology, signed reports (aa6533853096dfbe... /
   efee76f95ae0cc63...), and the harness that reproduces the run are public:
   `benchmark/cost_savings/` in the Perseus repo.

## Stated limits (we would rather you check than take our word)

- Sample size is 60 questions; per-task-type cells are small. The signed
  full-500 accuracy distribution for the product arm is published separately
  (79.0% mean, official CoT prompt).
- The ledger is integer-exact and independently re-queryable, but not yet
  cryptographically tamper-evident; that hardening is scheduled and tracked
  publicly. Until then, we recommend verifying savings against your own
  provider invoice, which is the strongest baseline anyway.
- Prices from the public price table as of 2026-06-26; the savings
  PERCENTAGE is rate-invariant (same model both arms).

---
*Perseus Computing LLC · perseus.observer · perseus@perseus.observer ·
generated 2026-07-11 from signed report aa6533853096dfbe...*
