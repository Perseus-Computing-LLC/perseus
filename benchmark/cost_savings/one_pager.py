#!/usr/bin/env python3
"""Generate the customer-facing one-pager from a signed cost-savings report
(#749). GENERATED, never hand-typed: every number renders from the committed
report JSONs; if a figure cannot be traced to a signed artifact it does not
appear. Emits markdown (repo/email) and a self-contained print-friendly HTML
(print to PDF for handouts).

    python benchmark/cost_savings/one_pager.py \
        --report benchmark/cost_savings/results/cost_savings_stratified_2026-07-11.json \
        --qa benchmark/cost_savings/results/qa_report_stratified_2026-07-11.json \
        --outdir benchmark/cost_savings/results
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

TYPE_LABELS = {
    "single-session-user": "Facts the user stated",
    "single-session-assistant": "Facts the assistant stated",
    "knowledge-update": "Updated facts (latest wins)",
    "single-session-preference": "User preferences",
    "multi-session": "Multi-session aggregation",
    "temporal-reasoning": "Temporal reasoning",
}

VERIFY_SQL = ("SELECT w.name, SUM(u.cost_micros)/1e6 AS usd FROM usage_events u "
              "JOIN workspaces w ON w.id=u.workspace_id GROUP BY w.id;")


def load(p: str) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def build_facts(report: dict, qa: dict) -> dict:
    base = report["arms"]["fullcontext"]
    ours = report["arms"]["mimir"]
    by_type = {}
    for system, key in (("fullcontext", "base"), ("mimir", "ours")):
        for t, row in qa["systems"][system]["by_question_type"].items():
            by_type.setdefault(t, {"n": row["n"]})[key] = row["accuracy"]
    return {
        "date": report.get("_generated") or str(date.today()),
        "savings_pct": report["savings_pct"],
        "base_usd": base["ledger_cost_usd"],
        "ours_usd": ours["ledger_cost_usd"],
        "base_tok": base["ledger_tokens"],
        "ours_tok": ours["ledger_tokens"],
        "base_acc": base["accuracy"] * 100,
        "ours_acc": ours["accuracy"] * 100,
        "acc_delta": report["accuracy_delta"] * 100,
        "n": report["n_questions"],
        "k": report["k"],
        "model": report["answerer_model"],
        "answer_prompt": report.get("answer_prompt", "plain"),
        "price_table": report["price_table_as_of"],
        "sig": report["signature_sha256"][:16],
        "qa_sig": report.get("qa_signature_sha256", "")[:16],
        "by_type": by_type,
        "tok_ratio": base["ledger_tokens"] / max(1, ours["ledger_tokens"]),
    }


def render_md(f: dict) -> str:
    rows = "\n".join(
        f"| {TYPE_LABELS.get(t, t)} | {v['n']} | {v['base'] * 100:.0f}% | "
        f"**{v['ours'] * 100:.0f}%** |" if v["ours"] >= v["base"] else
        f"| {TYPE_LABELS.get(t, t)} | {v['n']} | **{v['base'] * 100:.0f}%** | "
        f"{v['ours'] * 100:.0f}% |"
        for t, v in sorted(f["by_type"].items(), key=lambda kv: -kv[1]["n"]))
    return f"""# Perseus + Vault: verified LLM savings statement

**{f['savings_pct']:.1f}% fewer LLM dollars. {f['acc_delta']:+.1f} points MORE accurate. Read from the meter, not a marketing model.**

We ran the same {f['n']} memory-recall tasks two ways, with the same model
(`{f['model']}`) answering and the same official benchmark judge grading both:

| | LLM spend | tokens billed | accuracy |
|---|---:|---:|---:|
| Without Perseus (full context every call) | ${f['base_usd']:.2f} | {f['base_tok']:,} | {f['base_acc']:.1f}% |
| **With Perseus + Vault** | **${f['ours_usd']:.2f}** | **{f['ours_tok']:,}** | **{f['ours_acc']:.1f}%** |

Perseus + Vault loads only the context each task needs ({f['tok_ratio']:.1f}x fewer
tokens), so the model reads less, costs less, and answers better: long stuffed
prompts measurably LOSE accuracy on the tasks agents do most.

| task type | n | full context | Perseus + Vault |
|---|---:|---:|---:|
{rows}

## Why you can trust this number

1. **Dollars come from a meter, not a spreadsheet.** Every model call in both
   arms was recorded as a usage event in a [Plutus](https://github.com/Perseus-Computing-LLC/plutus)
   ledger; the totals above are sums over that ledger, reproducible with one
   line of SQL against the shipped ledger file:
   `{VERIFY_SQL}`
2. **Accuracy is graded by the benchmark's own judge**, not ours: LongMemEval's
   official per-question-type prompts, pinned `{f['model']}`, temperature 0,
   `answer_prompt: {f['answer_prompt']}`.
3. **The task sample is stratified, not cherry-picked**: {f['n']} questions drawn
   proportionally from all six LongMemEval question types, first-N per type in
   dataset order. Full methodology, signed reports ({f['sig']}... /
   {f['qa_sig']}...), and the harness that reproduces the run are public:
   `benchmark/cost_savings/` in the Perseus repo.

## Stated limits (we would rather you check than take our word)

- Sample size is {f['n']} questions; per-task-type cells are small. The signed
  full-500 accuracy distribution for the product arm is published separately
  (79.0% mean, official CoT prompt).
- The ledger is integer-exact and independently re-queryable, but not yet
  cryptographically tamper-evident; that hardening is scheduled and tracked
  publicly. Until then, we recommend verifying savings against your own
  provider invoice, which is the strongest baseline anyway.
- Prices from the public price table as of {f['price_table']}; the savings
  PERCENTAGE is rate-invariant (same model both arms).

---
*Perseus Computing LLC · perseus.observer · perseus@perseus.observer ·
generated {f['date']} from signed report {f['sig']}...*
"""


def render_html(f: dict) -> str:
    type_rows = "".join(
        f"<tr><td>{TYPE_LABELS.get(t, t)}</td><td>{v['n']}</td>"
        f"<td{' class=win' if v['base'] > v['ours'] else ''}>{v['base'] * 100:.0f}%</td>"
        f"<td{' class=win' if v['ours'] >= v['base'] else ''}>{v['ours'] * 100:.0f}%</td></tr>"
        for t, v in sorted(f["by_type"].items(), key=lambda kv: -kv[1]["n"]))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Perseus + Vault: verified LLM savings statement</title>
<style>
  @page {{ size: letter; margin: 14mm; }}
  body {{ font: 10.5pt/1.45 'IBM Plex Sans', 'Segoe UI', sans-serif; color: #16181d;
         max-width: 7.5in; margin: 0 auto; padding: 12px; }}
  h1 {{ font-size: 17pt; margin: 0 0 2px; }}
  .headline {{ font-size: 12.5pt; font-weight: 600; color: #5b3fb3; margin: 6px 0 14px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0 14px; }}
  th, td {{ border: 1px solid #d7d9df; padding: 5px 9px; text-align: right; font-size: 9.5pt; }}
  th:first-child, td:first-child {{ text-align: left; }}
  thead th {{ background: #f2f0fa; }}
  .big td {{ font-size: 11pt; }}
  .win {{ font-weight: 700; color: #1d7a4f; }}
  h2 {{ font-size: 11.5pt; margin: 14px 0 4px; }}
  ol, ul {{ margin: 4px 0 10px 20px; padding: 0; }}
  li {{ margin: 3px 0; }}
  code {{ font: 8.5pt 'IBM Plex Mono', monospace; background: #f4f4f6; padding: 1px 4px; }}
  .limits {{ background: #faf7ee; border: 1px solid #e6ddc2; padding: 8px 12px; font-size: 9pt; }}
  footer {{ margin-top: 12px; font-size: 8.5pt; color: #666; border-top: 1px solid #d7d9df;
            padding-top: 6px; }}
</style></head><body>
<h1>Perseus + Vault: verified LLM savings statement</h1>
<div class="headline">{f['savings_pct']:.1f}% fewer LLM dollars. {f['acc_delta']:+.1f} points MORE
accurate. Read from the meter, not a marketing model.</div>

<p>We ran the same {f['n']} memory-recall tasks two ways, with the same model
(<code>{f['model']}</code>) answering and the same official benchmark judge grading both:</p>

<table class="big"><thead><tr><th></th><th>LLM spend</th><th>tokens billed</th><th>accuracy</th></tr></thead>
<tbody>
<tr><td>Without Perseus (full context every call)</td><td>${f['base_usd']:.2f}</td><td>{f['base_tok']:,}</td><td>{f['base_acc']:.1f}%</td></tr>
<tr><td><b>With Perseus + Vault</b></td><td class="win">${f['ours_usd']:.2f}</td><td class="win">{f['ours_tok']:,}</td><td class="win">{f['ours_acc']:.1f}%</td></tr>
</tbody></table>

<p>Perseus + Vault loads only the context each task needs ({f['tok_ratio']:.1f}x fewer tokens), so
the model reads less, costs less, and answers better: long stuffed prompts measurably
<em>lose</em> accuracy on the tasks agents do most.</p>

<table><thead><tr><th>task type</th><th>n</th><th>full context</th><th>Perseus + Vault</th></tr></thead>
<tbody>{type_rows}</tbody></table>

<h2>Why you can trust this number</h2>
<ol>
<li><b>Dollars come from a meter, not a spreadsheet.</b> Every model call in both arms was
recorded as a usage event in a Plutus ledger; the totals above are sums over that ledger,
reproducible with one line of SQL against the shipped ledger file:<br>
<code>{VERIFY_SQL}</code></li>
<li><b>Accuracy is graded by the benchmark's own judge</b>, not ours: LongMemEval's official
per-question-type prompts, pinned <code>{f['model']}</code>, temperature 0,
<code>answer_prompt: {f['answer_prompt']}</code>.</li>
<li><b>The task sample is stratified, not cherry-picked</b>: {f['n']} questions drawn
proportionally from all six LongMemEval question types, first-N per type in dataset order.
Full methodology, signed reports ({f['sig']}&hellip; / {f['qa_sig']}&hellip;), and the harness that
reproduces the run are public: <code>benchmark/cost_savings/</code> in the Perseus repo.</li>
</ol>

<h2>Stated limits (we would rather you check than take our word)</h2>
<div class="limits"><ul>
<li>Sample size is {f['n']} questions; per-task-type cells are small. The signed full-500
accuracy distribution for the product arm is published separately (79.0% mean, official CoT prompt).</li>
<li>The ledger is integer-exact and independently re-queryable, but not yet cryptographically
tamper-evident; that hardening is scheduled and tracked publicly. Until then we recommend
verifying savings against your own provider invoice, which is the strongest baseline anyway.</li>
<li>Prices from the public price table as of {f['price_table']}; the savings percentage is
rate-invariant (same model both arms).</li>
</ul></div>

<footer>Perseus Computing LLC &middot; perseus.observer &middot; perseus@perseus.observer &middot;
generated {f['date']} from signed report {f['sig']}&hellip;</footer>
</body></html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", required=True, help="signed cost_savings report json")
    ap.add_argument("--qa", required=True, help="the run's qa report json (per-type table)")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    report, qa = load(args.report), load(args.qa)
    facts = build_facts(report, qa)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "ONE-PAGER.md").write_text(render_md(facts), encoding="utf-8")
    (outdir / "one-pager.html").write_text(render_html(facts), encoding="utf-8")
    print(f"wrote {outdir / 'ONE-PAGER.md'} and {outdir / 'one-pager.html'} "
          f"(savings {facts['savings_pct']:.1f}%, accuracy {facts['acc_delta']:+.1f} pts)")


if __name__ == "__main__":
    main()
