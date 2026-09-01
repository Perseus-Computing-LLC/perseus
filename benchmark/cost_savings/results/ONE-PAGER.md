# Historical Perseus + Vault: cost-savings measurement record

> Historical run record. These dated results are preserved for reproducibility; they are not a current benchmark, product-quality, production, or customer-outcome claim.

**75.1% fewer LLM dollars and +11.7 points on this 60-question sample. Read from the meter, not a marketing model.**

We ran the same 60 memory-recall tasks two ways, with the same model
(`gpt-4o-2024-08-06`) answering and the same official benchmark judge grading both:

| | LLM spend | tokens billed | accuracy |
|---|---:|---:|---:|
| Without Perseus (full context every call) | $15.71 | 6,250,823 | 55.0% |
| **With Perseus + Vault** | **$3.91** | **1,529,807** | **66.7%** |

Perseus + Vault loads only the context each task needs (4.1x fewer
tokens). On this historical sample, the product arm used fewer tokens and scored higher;
 that observation is not a general accuracy or production guarantee.

| task type | n | full context | Perseus + Vault |
|---|---:|---:|---:|
| Multi\-session aggregation | 16 | 31% | **38%** |
| Temporal reasoning | 16 | 38% | **69%** |
| Updated facts \(latest wins\) | 9 | **89%** | 67% |
| Facts the user stated | 8 | 88% | **100%** |
| Facts the assistant stated | 7 | 86% | **100%** |
| User preferences | 4 | 25% | **50%** |

## Why you can trust this number

1. **Dollars came from a meter, not a spreadsheet.** Every model call in both
   arms was recorded as a usage event in a Perseus Ledger. The dated public
   bundle preserves the integer report totals and content hash, but not the
   companion Ledger database; re-querying this historical run from the bundle
   is therefore unavailable. Verify savings against your own provider invoice,
   which is the strongest baseline anyway.
2. **Accuracy is graded by the benchmark's own judge**, not ours: LongMemEval's
   official per-question-type prompts, pinned `gpt-4o-2024-08-06`, temperature 0,
   `answer_prompt: official-cot`.
3. **The task sample is stratified, not cherry-picked**: 60 questions drawn
   proportionally from all six LongMemEval question types, first-N per type in
   dataset order. Full methodology, immutable report and QA content hashes (55fc3a90f7a9ccb1... /
   efee76f95ae0cc63... / ec25c09864301fc9...), and the harness that reproduces the run are public:
   `benchmark/cost_savings/` in the Perseus repo.

## Stated limits (we would rather you check than take our word)

- Sample size is 60 questions; per-task-type cells are small. Older full-500
  QA reports are historical engineering evidence only; they are not current benchmark
  claims and are not promoted by this record.
- The dated report is content-hash verifiable, but its companion Ledger database was not
  retained. The original run record therefore cannot be re-queried from this historical
  bundle, and it did not establish tamper evidence for the Ledger events. That limitation
  applies to this historical file only and must not be read as a statement about the current
  Ledger implementation. Verify savings against your own provider invoice and a current
  Ledger run with its database retained.
- Prices from the public price table as of 2026\-06\-26; the savings
  PERCENTAGE is rate-invariant (same model both arms).

---
*Perseus Computing LLC · perseus.observer · perseus@perseus.observer ·
generated 2026\-07\-11 from content-hashed report 55fc3a90f7a9ccb1...*
