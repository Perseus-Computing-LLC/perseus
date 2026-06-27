#!/usr/bin/env python3
"""Perseus context-selection eval.

Measures whether Perseus *selects the right context* under a tier limit — not how
fast it renders. Perseus gates directives by tier (1=always, 2=conditional,
3=on-demand): at `--tier N`, every directive above tier N must be skipped and
every directive at or below it must be eligible to resolve. This harness renders
a hand-authored fixture corpus at each tier limit and scores the **precision and
recall of that selection** against frozen ground truth.

It is fully **offline and deterministic**: it imports the built `perseus.py`
artifact and calls `render_source()` with the directive/skip collectors — no
network, no API key, no LLM. (The live LLM-judge equivalence eval lives in
`../eval/semantic_judge.py` and stays opt-in.)

Usage:
    python benchmark/selection/run.py            # score, write report.json, gate
    python benchmark/selection/run.py --dataset other.json --out report.json

Exit code is non-zero when the selection gate fails (precision or recall < 1.0),
so CI can block a tier-gating regression.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import platform
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


def render_skipped(perseus, source, tier, workspace):
    """Return the set of directive names skipped at this tier limit."""
    cfg = copy.deepcopy(perseus.DEFAULT_CONFIG)
    skipped, directives = [], []
    stats = {"directive_count": 0, "cache_hits": 0, "cache_misses": 0}
    perseus.render_source(source, cfg, workspace, max_tier=tier,
                          _directive_collector=directives, _stats=stats,
                          _skipped_directives=skipped)
    return {str(s.get("name", "")).lstrip("@") for s in skipped}


def main():
    ap = argparse.ArgumentParser(description="Perseus context-selection eval")
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--tiers", nargs="+", type=int, default=[1, 2, 3])
    ap.add_argument("--out", default=str(HERE / "report.json"))
    args = ap.parse_args()

    perseus = load_perseus()
    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    fixtures = data["fixtures"]
    tiers = sorted(set(args.tiers))
    workspace = REPO  # a real directory so @tree/@list/@read resolve in-tier

    tp = fp = fn = tn = 0
    per_case = []
    for fx in fixtures:
        declared = {d["name"] for d in fx["directives"]}
        for tier in tiers:
            actual_skipped = render_skipped(perseus, fx["source"], tier, workspace) & declared
            expected_skipped = {d["name"] for d in fx["directives"] if d["tier"] > tier}
            for d in fx["directives"]:
                should = d["tier"] > tier
                did = d["name"] in actual_skipped
                if should and did:
                    tp += 1
                elif should and not did:
                    fn += 1
                elif not should and did:
                    fp += 1
                else:
                    tn += 1
            per_case.append({
                "fixture": fx["id"], "tier": tier,
                "expected_skipped": sorted(expected_skipped),
                "actual_skipped": sorted(actual_skipped),
                "match": expected_skipped == actual_skipped,
            })

    precision = round(tp / (tp + fp), 4) if (tp + fp) else 1.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) else 1.0
    gate_pass = precision >= 1.0 and recall >= 1.0

    gates = [{
        "name": "selection_precision_recall == 1.0",
        "pass": bool(gate_pass),
        "observed": {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "threshold": "precision == 1.0 and recall == 1.0",
        "severity": "hard",
        "note": "tier-gated context selection must be exact",
    }]

    sig_payload = json.dumps({"dataset": data.get("name"), "tiers": tiers,
                              "per_case": per_case}, sort_keys=True)
    signature = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()

    report = {
        "benchmark": "perseus-context-selection",
        "dataset": data.get("name"),
        "n_fixtures": len(fixtures),
        "tiers": tiers,
        "precision": precision,
        "recall": recall,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "gates": gates,
        "pass": bool(gate_pass),
        "offline": True,
        "platform": platform.platform(),
        "signature_sha256": signature,
        "per_case": per_case,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Perseus context selection — {data.get('name')} "
          f"({len(fixtures)} fixtures, tiers {tiers})")
    print(f"  precision={precision}  recall={recall}  "
          f"(tp={tp} fp={fp} fn={fn} tn={tn})")
    for c in per_case:
        if not c["match"]:
            print(f"  MISMATCH [{c['fixture']}] tier={c['tier']}: "
                  f"expected_skipped={c['expected_skipped']} actual={c['actual_skipped']}")
    status = "PASS" if gate_pass else "FAIL"
    print(f"  gate: {status}   signature: {signature[:16]}...  ->  {args.out}")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
