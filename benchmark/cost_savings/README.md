# Historical cost-measurement harness

This directory contains a paired experimental harness for comparing a Perseus Context Engine plus Perseus Vault arm with a full-context arm. It records usage into a local ledger and grades the paired answers when the required dataset and provider configuration are supplied.

The earlier percentage cost-savings result is marked `publishable: false` in [`claims.json`](../../claims.json). It is not a marketing claim, customer outcome, production result, or price guarantee. Do not quote a savings percentage from this directory.

## Research use

```bash
python benchmark/cost_savings/harness.py --data <longmemeval_s_cleaned.json> \
  --limit 10 --mode mock
```

`mock` mode checks harness plumbing; its accuracy and dollar values are not publishable. A live research run requires a pinned dataset, answer model, judge, prompt, price table, and control configuration. Report both arms, their denominators, accuracy, usage, and limitations together. Preserve the generated report and source commit.

The harness does not broker model calls or prove production savings. Current public measurements are listed at [perseus.observer/benchmarks](https://perseus.observer/benchmarks/), with publication status governed by [`claims.json`](../../claims.json).
