#!/usr/bin/env python3
"""TRACE adapted simulation benchmark (#968).

Offline, deterministic evaluation of the trajectory-mined context-source
failure attribution pipeline against a hand-authored six-category fault
taxonomy corpus. For every planted-fault episode it:

1. mines dissatisfaction signals from the trajectory records;
2. attributes the failure to a context source (top-1 source accuracy is
   scored on the UPDATE episodes, where ground truth names the source);
3. classifies remediation as CREATE vs UPDATE before any patch;
4. cross-layer-verifies every diagnosis: evidence steps are cited, span IDs
   resolve to real spans, and the sealed report re-verifies.

Gates (non-zero exit on failure, so CI can block a regression):
  attribution top-1 accuracy >= 0.70  (paper baseline: 72.7% across 60 traces)
  CREATE/UPDATE accuracy    >= 0.90  (paper baseline: 96% operation accuracy)

No network, no API key, no LLM — the same deterministic path callers use.

Usage:
    python benchmark/trace/run.py            # score, write results/report, gate
    python benchmark/trace/run.py --dataset other.json --min-attribution 0.60
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="TRACE attribution benchmark (#968)")
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--out-results", default=str(HERE / "results.json"))
    ap.add_argument("--out-report", default=str(HERE / "report.md"))
    ap.add_argument("--min-attribution", type=float, default=0.70)
    ap.add_argument("--min-create-update", type=float, default=0.90)
    args = ap.parse_args()

    perseus = load_perseus()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if dataset.get("schema_version") != "perseus-trace-benchmark/v1":
        sys.exit("error: unsupported dataset schema version")
    groups = dataset["groups"]
    episodes = dataset["episodes"]

    per_episode = []
    n_update = n_attr_correct = 0
    n_cu = n_cu_correct = 0
    structural_errors = 0

    for ep in episodes:
        group = groups[ep["group"]]
        records = ep["records"]
        sources = group["sources"]
        expected = ep["expected"]
        report = perseus.run_trace_analysis(records, sources,
                                            created_by="trace-benchmark")

        check = perseus.verify_trace_report(report)
        structural_ok = True
        issues = []
        if not check["valid"]:
            structural_ok = False
            issues.append("report verification failed: "
                          + "; ".join(check["errors"]))
        # Cross-layer verification: every diagnosis must cite evidence steps
        # and every cited span must resolve to a real span of a source.
        source_spans = {
            sp["span_id"]
            for s in sources
            for sp in perseus.ContextSource(**s).spans
            for sp in [sp.to_dict()]
        }
        diagnoses = report["attribution"]["diagnoses"]
        if not diagnoses:
            structural_ok = False
            issues.append("no diagnosis produced")
        for diag in diagnoses:
            ev = diag.get("evidence") or {}
            if not ev.get("evidence_steps"):
                structural_ok = False
                issues.append("diagnosis cites no evidence steps")
            for rank in diag.get("ranking", []):
                unknown = set(rank.get("span_ids", [])) - source_spans
                if unknown:
                    structural_ok = False
                    issues.append(f"unresolved span ids: {sorted(unknown)}")
        if not structural_ok:
            structural_errors += 1

        # CREATE/UPDATE decision: the highest-confidence classification wins.
        classification = sorted(
            report["classification"],
            key=lambda c: (-(c.get("confidence") or 0.0), c["signal_id"]))
        decision = classification[0]["decision"] if classification else ""
        fault = classification[0]["fault_category"] if classification else ""

        n_cu += 1
        cu_correct = decision == expected["action"]
        if cu_correct:
            n_cu_correct += 1

        attr_correct = None
        if expected["action"] == "update" and expected.get("source_id"):
            n_update += 1
            attr_correct = (
                diagnoses[0].get("attributed_source_id") == expected["source_id"]
                if diagnoses else False)
            if attr_correct:
                n_attr_correct += 1

        per_episode.append({
            "id": ep["id"],
            "expected": expected,
            "decision": decision,
            "fault_category": fault,
            "decision_correct": cu_correct,
            "attributed_source_id": (diagnoses[0].get("attributed_source_id")
                                     if diagnoses else ""),
            "attribution_correct": attr_correct,
            "structural_ok": structural_ok,
            "issues": issues,
            "signals": [s["kind"] for s in report["signals"]],
            "report_digest": report["report_digest"],
        })

    attribution_accuracy = (n_attr_correct / n_update) if n_update else 0.0
    create_update_accuracy = n_cu_correct / n_cu if n_cu else 0.0
    attribution_pass = attribution_accuracy >= args.min_attribution
    create_update_pass = create_update_accuracy >= args.min_create_update
    structural_pass = structural_errors == 0

    results = {
        "schema_version": "perseus-trace-benchmark-results/v1",
        "dataset": Path(args.dataset).name,
        "dataset_sha256": sha256_bytes(Path(args.dataset).read_bytes()),
        "episodes": len(episodes),
        "attribution": {
            "top1_accuracy": round(attribution_accuracy, 4),
            "scored_episodes": n_update,
            "gate": round(args.min_attribution, 2),
            "pass": attribution_pass,
        },
        "create_update": {
            "accuracy": round(create_update_accuracy, 4),
            "scored_episodes": n_cu,
            "gate": round(args.min_create_update, 2),
            "pass": create_update_pass,
        },
        "structural_verification": {
            "episodes_with_errors": structural_errors,
            "pass": structural_pass,
        },
        "per_episode": per_episode,
    }
    Path(args.out_results).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")

    report_lines = [
        "# TRACE attribution benchmark — results (#968)",
        "",
        f"- dataset: `{Path(args.dataset).name}` "
        f"(`{results['dataset_sha256'][:16]}…`, {len(episodes)} episodes)",
        f"- attribution top-1 accuracy: **{attribution_accuracy:.1%}** "
        f"(gate ≥ {args.min_attribution:.0%}, {'PASS' if attribution_pass else 'FAIL'})",
        f"- CREATE/UPDATE accuracy: **{create_update_accuracy:.1%}** "
        f"(gate ≥ {args.min_create_update:.0%}, {'PASS' if create_update_pass else 'FAIL'})",
        f"- cross-layer verification: "
        f"{'PASS' if structural_pass else 'FAIL'} "
        f"({structural_errors} episodes with structural errors)",
        "",
        "## Per-episode",
        "",
        "| episode | expected | decision | attributed source | signals |",
        "|---|---|---|---|---|",
    ]
    for pe in per_episode:
        mark = "✅" if (pe["decision_correct"]
                       and pe["attribution_correct"] is not False) else "❌"
        report_lines.append(
            f"| {mark} {pe['id']} | {pe['expected']['category']} "
            f"({pe['expected']['action']}) | {pe['decision']} "
            f"({pe['fault_category']}) | "
            f"`{pe['attributed_source_id'] or '—'}` | {','.join(pe['signals'])} |")
    report_lines.append("")
    Path(args.out_report).write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"attribution top-1: {attribution_accuracy:.1%} "
          f"(gate {args.min_attribution:.0%}) "
          f"{'PASS' if attribution_pass else 'FAIL'}")
    print(f"create/update:     {create_update_accuracy:.1%} "
          f"(gate {args.min_create_update:.0%}) "
          f"{'PASS' if create_update_pass else 'FAIL'}")
    print(f"cross-layer:       {'PASS' if structural_pass else 'FAIL'} "
          f"({structural_errors} episodes with errors)")
    if not (attribution_pass and create_update_pass and structural_pass):
        sys.exit(1)


if __name__ == "__main__":
    main()
