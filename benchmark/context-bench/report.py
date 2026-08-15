#!/usr/bin/env python3
"""Generate the Context-Bench pilot report from a results envelope (#961)."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(HERE, "results", "live", "results.json")
    results = json.load(open(path, encoding="utf-8"))
    manifest = results["manifest"]
    agg = results["aggregate"]
    rows = results["rows"]

    full_tokens = agg.get("full_context", {}).get("mean_tokens_rendered")
    run_kind = "DRY (mock)" if manifest["dry_run"] else "LIVE"
    pilot_n = manifest["pilot_n"]
    answer_model = manifest["answer_provider"]["model"]
    judge_model = manifest["judge_provider"]["model"]
    lines = [
        "# Context-Bench pilot — Perseus assembly adapter (perseus#961)",
        "",
        "**Run:** %s · pilot %s questions · answer %s · judge %s "
        "(official 0/0.5/1.0 rubric)" % (run_kind, pilot_n, answer_model,
                                        judge_model),
        "",
        "## Framing",
        "",
        "Adapter-based reproduction of the letta-evals filesystem suite. "
        "**Not leaderboard-identical** (the official target is Letta Code); "
        "public questions are **not** a hidden holdout. Numbers below are "
        "adapter evidence, not statistical validation.",
        "",
        "## Aggregate",
        "",
        "| arm | n | mean rubric | mean tokens (rendered) | vs full-context |",
        "|---|---:|---:|---:|---:|",
    ]
    order = ["full_context", "naive_rag_k3", "naive_rag_k5",
             "perseus_dag", "mem0_rag_k5"]
    for name in order:
        if name not in agg:
            continue
        cell = agg[name]
        red = cell.get("reduction_vs_full_context_pct")
        red_s = "—" if red is None else "−%s%%" % red
        tok_s = cell.get("mean_tokens_rendered", "—")
        lines.append(
            "| %s | %s | %s | %s | %s |" % (name, cell["n"],
                                            cell["mean_score"], tok_s,
                                            red_s))
    lines += [
        "",
        "## Claim labels",
        "",
        "- rubric scores: observed judge outputs under the official rubric "
        "contract;",
        "- tokens rendered: derived estimate (chars//4); provider usage "
        "reported per call;",
        "- generalization beyond this 15-question adapter pilot: **not "
        "established**.",
        "",
        "## Per-question rows",
        "",
        "| question | type | full | rag3 | rag5 | dag |",
        "|---|---|---|---|---|---|",
    ]
    pilot = json.load(open(os.path.join(HERE, "pilot.json"),
                           encoding="utf-8"))
    for sample in pilot["samples"]:
        sid = sample["id"]
        arms = rows.get(sid, {})
        cells = []
        for name in ("full_context", "naive_rag_k3", "naive_rag_k5",
                     "perseus_dag"):
            r = arms.get(name) or {}
            j = r.get("judge") or {}
            cells.append(j.get("score", "—"))
        lines.append("| %s… | %s | " % (sample["question"][:48],
                                        sample["question_type"])
                     + " | ".join(cells) + " |")
    pilot_sha = manifest["pilot_sha256"][:16]
    rubric_sha = manifest["rubric_sha256"][:16]
    res_digest = results["results_digest"][:16]
    lines += [
        "",
        "## Custody",
        "",
        "- pilot sha256: `%s…`" % pilot_sha,
        "- rubric sha256: `%s…`" % rubric_sha,
        "- results digest: `%s…`" % res_digest,
        "- verify with: `python3 benchmark/context-bench/custody.py`",
        "",
    ]
    out = os.path.join(os.path.dirname(path), "report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
