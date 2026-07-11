# Cost-savings certification results (#749)

Live runs of the Perseus+Vault vs full-context cost-savings harness, with
dollars read back from a Plutus ledger and accuracy graded by the official
LongMemEval per-type judge. All numbers below are reproduced from the signed
artifacts in this directory.

**Headline (stratified run, the representative number): Perseus+Vault spent
75.1% fewer dollars AND scored 11.7 points higher than full-context stuffing
on a proportional sample of all six LongMemEval question types.**

## The stratified run (2026-07-11) — quote this one

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
- Signatures: cost-savings report `aa6533853096dfbe...`, qa report
  `efee76f95ae0cc63...`. Artifacts:
  [`cost_savings_stratified_2026-07-11.json`](cost_savings_stratified_2026-07-11.json),
  [`qa_report_stratified_2026-07-11.json`](qa_report_stratified_2026-07-11.json).

Caveats that remain (stated so nobody overquotes): n=60 means per-type cells
are noisy (4–16 questions each); the deterministic first-N-per-type subset
skews slightly harder than the full mix (product arm 66.7% here vs the signed
79.0% full-500 CoT mean — both arms face the same questions, so the DELTA is
the robust stat); and the ledger tamper-evidence gap below applies to every
run.

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
| Plutus price table | as of `2026-06-26` |
| metering | every answer and judge call recorded via `plutus_agent.metering.record_usage`, one workspace per arm |

## Result

| arm | dollars (from ledger) | tokens | accuracy |
|---|---:|---:|---:|
| baseline: full-context stuffing | **$6.5273** | 2,603,042 | 84.0% (21/25) |
| product: Perseus + Vault (k=10) | **$1.3891** | 548,614 | 96.0% (24/25) |

- **Dollar savings: 78.72% fewer dollars** for the product arm.
- **Accuracy delta: +0.12** (the product arm scored higher, not lower, on this slice).
- 50 metered events per arm (25 answer + 25 judge), 0 errors, 0 dropped events.

Signatures: cost-savings report `d217876646fb814a...`, underlying qa report
`1db193ec77f9f243...`.

## Independent verification

The dollars are not hand-computed. They are summed from the per-event
`cost_micros` written to the ledger at ingest, and the same figure reproduces
three independent ways:

1. The signed `cost_savings_report.json` (`spend_by(dimension="workspace")`).
2. A raw SQL sum over `usage_events` grouped by workspace in `plutus_ledger.db`.
3. A recomputation from token counts at the gpt-4o rate ($2.50 / 1M input,
   $10.00 / 1M output): $6.527300 and $1.389085, matching the ledger to the
   micro-dollar.

Anyone with the ledger file can re-run step 2 and confirm the number without
trusting this report.

## What is trustworthy here, and what is not

Trustworthy and robust:

- **The dollar savings (~78%).** It is driven by the token ratio between the
  two arms (2.60M vs 0.55M input tokens, about 4.75x), which is a structural
  property of full-context stuffing versus top-k recall, not an artifact of
  question difficulty. The same ratio shows up in the offline dry-run (4.4x)
  and the CPST run (4.1x), so it holds across configs.
- **The accuracy gate passed.** Under the official judge, the product arm did
  not lose accuracy on this task set; it gained.

Not yet trustworthy as a headline, and stated plainly so it is never overquoted:

- **n = 25 is a small sample.** The signed full-500 reference for the product
  arm is 79.0% CoT mean (see the vault repo `benchmark/longmemeval/COMPARISON.md`).
  The 96.0% here is real for this subset but is not the benchmark-wide number.
- **All 25 questions are the `single-session-user` type.** That is the easiest
  LongMemEval category. This subset is a favorable, non-stratified slice. The
  accuracy half of the claim should be re-run stratified across all five
  question types, and ideally on the full 500, before any accuracy figure is
  published next to a dollar figure. **(Done — see the stratified run above,
  which is now the quotable one.)**
- **The dollars are re-queryable but not tamper-evident.** The Plutus ledger is
  append-only by convention and integer-exact, but it has no hash chain, MAC, or
  signature over its rows, so an operator with database access could rewrite
  history undetectably. For a savings figure that both a customer and Perseus
  must trust, that gap has to be closed. See the methodology and architecture
  decision record in the strategy docs.

## Reproduce

```
pip install plutus-agent
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
`plutus_ledger.db` produced by the run and sum `cost_micros` grouped by
workspace.
