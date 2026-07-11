# Cost-savings benchmark — Perseus+Vault vs full-context, metered by Plutus (#749)

The chargeable claim, made verifiable: **running Perseus+Vault costs a fraction
of full-context stuffing at equivalent accuracy** — with the dollars read back
from a [Plutus](https://github.com/Perseus-Computing-LLC/plutus) ledger rather
than hand-computed token math, and the accuracy graded by LongMemEval's
official judge.

## How it works

One run of the vault's signed QA harness
(`perseus-vault/benchmark/longmemeval/qa.py --systems fullcontext mimir`)
produces both arms under one config — same questions, same pinned
answerer+judge. This harness then meters every answer/judge call into a fresh
Plutus ledger (`plutus_agent.metering.record_usage`, one workspace per arm) and
builds the report by querying the ledger back (`spend_by(dimension=
"workspace")`). The ledger file ships next to the report so anyone can re-query
the dollars.

```
python benchmark/cost_savings/harness.py --data <longmemeval_s_cleaned.json> \
    --limit 10 --mode mock            # free: real retrieval, estimated dollars
python benchmark/cost_savings/harness.py --data ... \
    --limit 25 --mode live --cot --yes  # paid: billed tokens, official judge
```

Requires `pip install plutus-agent`, a perseus-vault checkout (sibling dir or
`PERSEUS_VAULT_REPO`) with a release binary, and the public LongMemEval
dataset.

## Modes

| | dollars | accuracy | cost |
|---|---|---|---|
| `--mode mock` | estimated prompt tokens × Plutus price table | stub-graded (meaningless — plumbing only) | free |
| `--mode live` | provider-billed tokens × Plutus price table | official LongMemEval per-type judge | real (qa.py prints the estimate first) |

**Quote only live-mode numbers, and quote both halves together** — a savings
figure without its accuracy gate is meaningless. Full-500 reference accuracy
for the product arm lives in
[perseus-vault COMPARISON.md](https://github.com/Perseus-Computing-LLC/perseus-vault/blob/main/benchmark/longmemeval/COMPARISON.md)
(73.8% plain / 79.0% official-CoT mean, signed).

## Report

`cost_savings_report.json`: per-arm ledger dollars/tokens/events, per-arm
accuracy, `savings_pct`, `accuracy_delta`, the full config (models, k,
`answer_prompt`, price-table date), the underlying qa.py report signature, and
a sha256 signature over the result set. Guardrails: same pinned model both
arms by construction; the harness aborts if Plutus drops any usage event.

## From lab to production (#755)

The numbers above are produced by the **offline harness**. In a real
deployment the same ledger is produced at runtime by the observe-model meter
(`perseus.meter_response` / `perseus.meter_usage`, see `src/perseus/metering.py`),
enabled per deployment via the `plutus` config block:

```yaml
plutus:
  enabled: true
  db_path: /var/lib/perseus/plutus_ledger.db   # local ledger (or set `endpoint` for a remote Plutus)
  org: acme
  workspace: prod-agent                        # default tag; per-call override wins
  task_type: serving
```

Perseus does not broker LLM calls — the deploying agent keeps making its own
provider calls and hands each response to the meter, which records the
provider-reported `usage` (authoritative tokens; `cost_usd` when the provider
supplies it) into the same `usage_events` table. So a production ledger is
byte-for-byte the shape this harness emits, and the one-pager / savings-statement
generators run against it unchanged. Metering is opt-in, adds no dependency when
off, and never fails the serving call (`fail_open`); dropped events are counted
(`perseus.metering_dropped_events()`) so an understated ledger is visible.

Provider usage is still **re-queryable but not tamper-evident** until
[plutus#108](https://github.com/Perseus-Computing-LLC/plutus/issues/108) (ledger
hash-chain) ships — the same caveat this harness prints.
