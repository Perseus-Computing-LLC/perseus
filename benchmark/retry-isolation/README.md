# Perseus CCRM retry-isolation benchmark (#972)

A **reproducible, fully offline, seeded** evaluation of clean-restart
attempt isolation: the IID retry model vs the contaminated cascade vs
fenced clean restart at the paper's ~7.1x cascade ratio, plus the closed
form attempt-budget allocation and a concrete fence demonstration.

## Run it

```bash
python scripts/build.py                    # ensure perseus.py is in sync with src/
python benchmark/retry-isolation/run.py    # score, write results/report, gate
```

Exit code is **non-zero** when a gate fails, so CI can block a regression:

| gate | requirement |
|---|---|
| IID overestimate | IID pass@3 exceeds the contaminated cascade by ≥ 8 points (paper: 17.4pp on SWE-bench Verified) |
| clean-restart dominance | fenced retries recover the gap (≥ 8 points over the contaminated cascade) |
| closed-form allocation | T* matches `sqrt(B · log(1/(1−ε1)) / log(1/(1−ε0)))` exactly |
| fence demonstration | a failed attempt's turns appear nowhere in the restored portion of the retry context; the contamination flag is set; the event re-verifies |

## What this measures

The CCRM model's quantitative claim, reproduced in seeded simulation:
retry context is ~7.1x more error-prone per step, so replaying the
contaminated trace costs double-digit pass@3 points versus the IID
assumption — and clearing context before retry recovers it. This is the
simulation analog of the paper's SWE-bench Verified experiment; the live
SWE-bench-style workload stays out of this offline gate (the issue's
success criterion calls for closing the gap toward the paper's prediction,
which this harness pins structurally).
