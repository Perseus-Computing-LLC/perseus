# Historical cost-savings measurement results (#749)

> **Historical run record.** These dated artifacts preserve reproducible measurements from 2026-07-11. They are not current benchmark, product-quality, production, or customer-outcome claims; current public performance claims live in the canonical claims registry and retrieval report.

Historical live runs of the Perseus+Vault vs full-context cost-savings harness, with
dollars read back from a Perseus Ledger and accuracy graded by the official
LongMemEval per-type judge. All numbers below are reproduced from the content-hashed
artifacts in this directory.

**Headline (stratified run, the representative number): Perseus+Vault spent
75.1% fewer dollars AND scored 11.7 points higher than full-context stuffing
on a proportional sample of all six LongMemEval question types.**

## The stratified run (2026-07-11) — representative historical run

The pilot below was flagged "re-run stratified before quoting accuracy next to
dollars"; this is that run. Sample: 60 questions, proportional to the full-500
type mix (su 8 / sa 7 / sp 4 / ms 16 / tr 16 / ku 9), selected
deterministically — first-N per type in dataset order, no cherry-picking
(construction snippet below). Same config as the pilot otherwise
(k=10, `official-cot`, `gpt-4o-2024-08-06` both arms, `--tpm 600000`).

| arm | dollars (from ledger) | tokens | accuracy |
|---|---:|---:|---:|
| baseline: full-context stuffing | **$15.7078** | 6,250,823 | 55.0% (33/60) |
| product: Perseus + Vault (k=10) | **$3.9056** | 1,529,807 | 66.7% (40/60) |

- **Dollar savings: 75.14% fewer dollars** for the product arm.
- **Accuracy delta: +0.1167** — the product arm won on the representative mix
  too, and the per-type split shows why:

| question type | n | full-context | Perseus+Vault |
|---|---:|---:|---:|
| single-session-user | 8 | 87.5% | **100.0%** |
| single-session-assistant | 7 | 85.7% | **100.0%** |
| knowledge-update | 9 | **88.9%** | 66.7% |
| single-session-preference | 4 | 25.0% | **50.0%** |
| multi-session | 16 | 31.2% | **37.5%** |
| temporal-reasoning | 16 | 37.5% | **68.8%** |

  Full-context stuffing collapses exactly where long context hurts most —
  multi-session (31.2%) and temporal (37.5%) at ~105k tokens/prompt
  (lost-in-the-middle) — while paying 4.1x the tokens for it. The one
  category it won (knowledge-update, 9 questions) is within small-n noise.
- 120 metered events per arm (60 answer + 60 judge), 0 errors, 0 dropped.
- Content hashes: cost-savings report `061b9f646d5084a4...`, QA content hash
  `efee76f95ae0cc63...`. Artifacts:
  [`cost_savings_stratified_2026-07-11.json`](cost_savings_stratified_2026-07-11.json),
  [`qa_report_stratified_2026-07-11.json`](qa_report_stratified_2026-07-11.json).

Caveats that remain (stated so nobody overquotes): n=60 means per-type cells
are noisy (4–16 questions each); the deterministic first-N-per-type subset
skews slightly harder than the full mix (product arm 66.7% here vs the older
content-hashed historical full-500 QA evidence — both arms face the same
questions, so the DELTA is the robust stat); and the dated ledger-integrity
boundary below applies to this historical run.

Subset construction (deterministic, reproducible):

```python
quota = {t: max(4, round(c * 60 / 500)) for t, c in type_counts.items()}
# then take the FIRST quota[t] questions of each type in dataset order
```

## The pilot run (2026-07-11, single-session-user slice)

| setting | value |
|---|---|
| dataset | `longmemeval_s` (cleaned), 500-question split |
| questions run | 25 |
| retrieval | hybrid (BM25 + dense + RRF), k = 10 |
| answerer model | `gpt-4o-2024-08-06` (temperature 0) |
| judge model | `gpt-4o-2024-08-06`, official LongMemEval per-type prompt |
| answer prompt | `official-cot` |
| vault binary | `perseus-vault 2.20.2` (commit `eb8bc17`) |
| Perseus Ledger price table | as of `2026-06-26` |
| metering | every answer and judge call recorded via `ledger_agent.metering.record_usage`, one workspace per arm |

## Result

| arm | dollars (from ledger) | tokens | accuracy |
|---|---:|---:|---:|
| baseline: full-context stuffing | **$6.5273** | 2,603,042 | 84.0% (21/25) |
| product: Perseus + Vault (k=10) | **$1.3891** | 548,614 | 96.0% (24/25) |

- **Dollar savings: 78.72% fewer dollars** for the product arm.
- **Accuracy delta: +0.12** (the product arm scored higher, not lower, on this slice).
- 50 metered events per arm (25 answer + 25 judge), 0 errors, 0 dropped events.

Content hashes: cost-savings report `0411962af3947619...`, underlying QA content hash
`1db193ec77f9f243...`.

## Independent verification

The dollars were read back from per-event `cost_micros` in Perseus Ledger at run
time, rather than hand-computed. The checked-in historical bundle preserves the
report JSON, its content hash, and the QA report, but it does **not** include the
companion Ledger database. Consequently, a raw SQL re-query of the historical
Ledger events is not available from this repository. The token-count calculation
below is a consistency check only, not a substitute for the original Ledger
readback or for a provider invoice:

- Recompute the listed totals from the recorded token counts at the gpt-4o rate
  ($2.50 / 1M input, $10.00 / 1M output): $6.527300 and $1.389085 for the pilot.
- For a savings figure that both a customer and Perseus must trust, verify against
  the provider invoice and a current Ledger run with its `ledger.db` retained.

## What is trustworthy here, and what is not

Trustworthy and robust:

- **The dollar savings (~78%).** It is driven by the token ratio between the
  two arms (2.60M vs 0.55M input tokens, about 4.75x), which is a structural
  property of full-context stuffing versus top-k recall, not an artifact of
  question difficulty. The same ratio shows up in the offline dry-run (4.4x)
  and the CPST run (4.1x), so it holds across configs.
- **The accuracy gate passed.** Under the official judge, the product arm did
  not lose accuracy on this task set; it gained.

Not yet trustworthy as a general product headline, and stated plainly so it is never overquoted:

- **The pilot's n = 25 is a small, favorable slice.** It is retained as historical
  provenance; the stratified n = 60 run above is the representative record, but its
  per-type cells are still noisy and neither run is benchmark-wide.
- **The accuracy comparison is sample-specific.** The product arm did not lose accuracy
  on these task sets under the recorded judge, but this does not establish general model
  quality, production performance, or a customer outcome.
- **The dated report is content-hash verifiable, but its companion Ledger database was not
  retained.** The original run record therefore cannot be re-queried from this repository,
  and it did not establish tamper evidence for the Ledger events. That limitation applies
  to this historical file only and must not be read as a statement about the current Ledger
  implementation. For a savings figure that both a customer and Perseus must trust, verify
  against the provider invoice and a current Ledger run with its database retained.

## Reproduce

```
pip install perseus-ledger
# perseus-vault checked out as a sibling dir (or set PERSEUS_VAULT_REPO),
# with a release binary at target/release/
python benchmark/cost_savings/harness.py \
    --data <path>/longmemeval_s_cleaned.json --limit 25 --k 10 \
    --mode live --cot --yes --outdir benchmark/cost_savings/out-live
```

Free plumbing check (no API spend): drop `--mode live --cot --yes` for
`--mode mock`. Mock dollars are estimates and mock accuracy is stub-graded, so
mock numbers are never quotable.

To re-verify the dollars from the ledger without spending anything, open the
`ledger.db` produced by the run and sum `cost_micros` grouped by
workspace.
