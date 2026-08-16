#!/usr/bin/env python3
"""PACMS pooled-selection benchmark (#970).

Offline, deterministic evaluation of the pluggable submodular selection
engine over the pooled context: for each multi-turn scenario with planted
ground-truth-relevant candidates and a budget <= 50% of the pooled tokens,

1. the ``submodular_greedy`` policy must keep every required candidate
   (kept-set recall = 1.0, the selection-quality gate convention);
2. the ``recent_first`` recency-truncation baseline is measured to show it
   loses the old-but-relevant facts this engine exists to preserve;
3. every selection trace must re-verify (replay-first);
4. budgets are hard: tokens_used <= budget_tokens on every run.

Exit code is non-zero when the recall gate or verification fails, so CI can
block a regression. No network, no API key, no LLM.

Usage:
    python benchmark/pooled-selection/run.py            # score, write, gate
    python benchmark/pooled-selection/run.py --dataset other.json
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def load_perseus():
    artifact = REPO / "perseus.py"
    if not artifact.is_file():
        sys.exit("error: perseus.py not found. Build it (`python scripts/build.py`).")
    spec = importlib.util.spec_from_file_location("perseus", artifact)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser(description="PACMS pooled-selection benchmark (#970)")
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--out-results", default=str(HERE / "results.json"))
    ap.add_argument("--out-report", default=str(HERE / "report.md"))
    args = ap.parse_args()

    perseus = load_perseus()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if dataset.get("schema_version") != "perseus-pooled-selection-benchmark/v1":
        sys.exit("error: unsupported dataset schema version")

    per_scenario = []
    errors: list[str] = []
    for scn in dataset["scenarios"]:
        pool = scn["pool"]
        query = scn["query"]
        budget = scn["budget_tokens"]
        required = set(scn["required"])
        full_tokens = sum(perseus.pool_tokens(c["content"]) for c in pool)

        sub = perseus.select_pooled_context(
            pool, query=query, budget_tokens=budget, created_by="benchmark")
        rec = perseus.select_pooled_context(
            pool, query=query, budget_tokens=budget, policy="recent_first",
            created_by="benchmark")

        kept_sub = set(sub["kept_ids"])
        kept_rec = set(rec["kept_ids"])
        recall_sub = len(kept_sub & required) / len(required) if required else 1.0
        recall_rec = len(kept_rec & required) / len(required) if required else 1.0
        sub_verify = perseus.verify_selection_trace(sub)
        rec_verify = perseus.verify_selection_trace(rec)

        row = {
            "id": scn["id"],
            "budget_tokens": budget,
            "pool_tokens": full_tokens,
            "budget_fraction": round(budget / full_tokens, 3) if full_tokens else 0.0,
            "submodular_recall": round(recall_sub, 3),
            "recent_first_recall": round(recall_rec, 3),
            "submodular_kept": sorted(kept_sub),
            "submodular_verifies": sub_verify["valid"],
            "recent_first_verifies": rec_verify["valid"],
            "submodular_tokens_used": sub["tokens_used"],
        }
        if recall_sub != 1.0:
            errors.append(
                f"{scn['id']}: submodular recall {recall_sub:.2%} < 1.0 "
                f"(missing {sorted(required - kept_sub)})")
        if sub["tokens_used"] > budget:
            errors.append(f"{scn['id']}: budget violated "
                          f"({sub['tokens_used']} > {budget})")
        if not sub_verify["valid"]:
            errors.append(f"{scn['id']}: submodular trace failed verification: "
                          + "; ".join(sub_verify["errors"]))
        if not rec_verify["valid"]:
            errors.append(f"{scn['id']}: recent_first trace failed verification: "
                          + "; ".join(rec_verify["errors"]))
        per_scenario.append(row)

    results = {
        "schema_version": "perseus-pooled-selection-benchmark-results/v1",
        "dataset": Path(args.dataset).name,
        "dataset_sha256": hashlib.sha256(
            Path(args.dataset).read_bytes()).hexdigest(),
        "scenarios": len(per_scenario),
        "pass": not errors,
        "errors": errors,
        "per_scenario": per_scenario,
    }
    Path(args.out_results).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")

    sub_recall_avg = (sum(r["submodular_recall"] for r in per_scenario)
                      / len(per_scenario)) if per_scenario else 0.0
    rec_recall_avg = (sum(r["recent_first_recall"] for r in per_scenario)
                      / len(per_scenario)) if per_scenario else 0.0
    lines = [
        "# PACMS pooled-selection benchmark — results (#970)",
        "",
        f"- dataset: `{Path(args.dataset).name}` "
        f"(`{results['dataset_sha256'][:16]}…`, {len(per_scenario)} scenarios)",
        f"- gate: **{'PASS' if not errors else 'FAIL'}**",
        f"- mean submodular recall: **{sub_recall_avg:.1%}** "
        f"(recency-truncation baseline: {rec_recall_avg:.1%})",
        "",
        "| scenario | budget | budget % | submodular recall | "
        "recent_first recall | verifies |",
        "|---|---|---|---|---|---|",
    ]
    for row in per_scenario:
        lines.append(
            f"| {row['id']} | {row['budget_tokens']}/{row['pool_tokens']} | "
            f"{row['budget_fraction']:.0%} | {row['submodular_recall']:.0%} | "
            f"{row['recent_first_recall']:.0%} | "
            f"{'✅' if row['submodular_verifies'] else '❌'} |")
    for err in errors:
        lines.append(f"- ❌ {err}")
    lines.append("")
    Path(args.out_report).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"submodular recall: {sub_recall_avg:.1%} "
          f"(baseline recent_first: {rec_recall_avg:.1%}) "
          f"— gate {'PASS' if not errors else 'FAIL'}")
    for err in errors:
        print(" -", err)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
