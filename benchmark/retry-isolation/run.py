#!/usr/bin/env python3
"""CCRM retry-isolation benchmark (#972).

Offline, seeded evaluation of clean-restart attempt isolation:

1. **CCRM simulation** — the IID model vs the contaminated cascade vs
   clean-restart fencing, at the paper's ~7.1x cascade ratio. Gates: the
   IID overestimate of pass@K is >= 8 points (paper: 17.4 on SWE-bench
   Verified) and clean restart recovers it (clean-restart dominance).
2. **Closed-form allocation** — the attempt-budget helper must match
   ``T* = sqrt(B * log(1/(1-eps1)) / log(1/(1-eps0)))`` exactly.
3. **Fence demonstration** — a concrete failed attempt with contaminated
   turns: the retry context restores the pre-attempt snapshot, carries the
   bounded summary, and contains NONE of the failed attempt's turns in its
   restored portion (verifiable in the context trace).

Exit code is non-zero when any gate fails, so CI can block a regression.
No network, no API key, no LLM.

Usage:
    python benchmark/retry-isolation/run.py            # score, write, gate
    python benchmark/retry-isolation/run.py --trials 8000
"""
import argparse
import hashlib
import importlib.util
import json
import math
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
    ap = argparse.ArgumentParser(description="CCRM retry-isolation benchmark (#972)")
    ap.add_argument("--trials", type=int, default=4000)
    ap.add_argument("--out-results", default=str(HERE / "results.json"))
    ap.add_argument("--out-report", default=str(HERE / "report.md"))
    args = ap.parse_args()

    perseus = load_perseus()
    errors: list[str] = []

    # ── 1. CCRM simulation at the paper's ~7.1x cascade ratio ──
    total_budget, eps0, eps1 = 1000.0, 0.025, 0.1775
    report = perseus.run_ccrm_analysis(
        total_budget=total_budget, eps0=eps0, eps1=eps1,
        trials=args.trials, seed=42, created_by="benchmark")
    over_pp = report["iid_overestimate_pp"]
    recovery_pp = report["clean_restart_recovery_pp"]
    if over_pp < 8.0:
        errors.append(f"IID overestimate only {over_pp}pp (gate >= 8; "
                      f"paper: 17.4pp)")
    if recovery_pp < 8.0:
        errors.append(f"clean-restart recovery only {recovery_pp}pp "
                      f"(gate >= 8)")

    # ── 2. Closed-form allocation exactness ──
    alloc = perseus.attempt_budget_allocation(total_budget, eps0, eps1)
    log0 = math.log(1 / (1 - eps0))
    log1 = math.log(1 / (1 - eps1))
    expected_t = math.sqrt(total_budget * log1 / log0)
    if alloc["t_star_continuous"] != round(expected_t, 4):
        errors.append("allocation deviates from the closed form")

    # ── 3. Fence demonstration ──
    base = ("You are a deployment assistant.\n\n"
            "Goal: ship the release.\n\n"
            "The deploy tool takes --env staging.")
    snap = perseus.snapshot_context(base, attempt_id="bench-attempt-0")
    turns = [
        "deploy --env prod",
        "error: permission denied for environment prod",
        "trying prod credentials instead",
    ]
    event = perseus.build_retry_context(
        snap,
        {"attempt_id": "bench-attempt-1", "failed_step": "deploy --env prod",
         "observed_error": "error: permission denied for environment prod",
         "failure_kind": "tool_error"},
        attempt_turns=turns, created_by="benchmark")
    restored = event["retry_context"].replace(event["failure_summary"], "")
    leaked = [t for t in turns if t in restored]
    if leaked:
        errors.append(f"fence leak: {leaked}")
    if not event["contamination_fenced"]:
        errors.append("contamination flag not set")
    check = perseus.verify_isolation_event(event, snapshot=snap)
    if not check["valid"]:
        errors.append("isolation event failed verification: "
                      + "; ".join(check["errors"]))

    results = {
        "schema_version": "perseus-retry-isolation-benchmark-results/v1",
        "pass": not errors,
        "errors": errors,
        "simulation": {
            "trials": args.trials,
            "eps0": eps0,
            "eps1": eps1,
            "cascade_ratio": round(eps1 / eps0, 3),
            "iid_pass_at_3": report["pass_at_k"]["iid"],
            "contaminated_pass_at_3": report["pass_at_k"]["contaminated"],
            "clean_restart_pass_at_3": report["pass_at_k"]["clean_restart"],
            "iid_overestimate_pp": over_pp,
            "clean_restart_recovery_pp": recovery_pp,
        },
        "allocation": alloc,
        "fence": {
            "quarantined_turns": event["quarantined_turn_count"],
            "summary_tokens": event["summary_tokens"],
            "retry_tokens": event["retry_tokens"],
            "event_digest": event["event_digest"],
        },
    }
    Path(args.out_results).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# CCRM retry-isolation benchmark — results (#972)",
        "",
        f"- simulation: {args.trials} seeded trials, cascade ratio "
        f"{round(eps1/eps0, 2)}x (paper: ~7.1x)",
        f"- gate: **{'PASS' if not errors else 'FAIL'}**",
        "",
        "| policy | pass@3 |",
        "|---|---|",
        f"| IID (overestimate) | {report['pass_at_k']['iid']:.1%} |",
        f"| contaminated cascade | {report['pass_at_k']['contaminated']:.1%} |",
        f"| clean restart (fenced) | {report['pass_at_k']['clean_restart']:.1%} |",
        "",
        f"- IID overestimate: **{over_pp}pp** (paper: 17.4pp on SWE-bench "
        f"Verified; gate ≥ 8pp)",
        f"- clean-restart recovery: **{recovery_pp}pp** (gate ≥ 8pp)",
        f"- allocation: T* = {alloc['t_star_continuous']} → "
        f"{alloc['optimal_attempts']} attempts from budget "
        f"{alloc['total_budget']}",
        f"- fence demo: {event['quarantined_turn_count']} turns quarantined, "
        f"summary {event['summary_tokens']} tokens, event digest "
        f"`{event['event_digest'][:16]}…`",
    ]
    for err in errors:
        lines.append(f"- ❌ {err}")
    lines.append("")
    Path(args.out_report).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"retry-isolation gate: {'PASS' if not errors else 'FAIL'}")
    print(f"  IID overestimate {over_pp}pp | clean-restart recovery "
          f"{recovery_pp}pp | fence {'clean' if not leaked else 'LEAK'}")
    for err in errors:
        print(" -", err)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
