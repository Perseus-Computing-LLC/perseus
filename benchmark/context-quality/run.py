#!/usr/bin/env python3
"""Context-quality preflight discrimination benchmark (#969).

Offline, deterministic evaluation of the 7-criteria measurement layer:
scores a healthy baseline context and degraded twins (one per criterion,
plus a multi-fault sample) and gates that

1. every degraded sample scores STRICTLY LOWER than the baseline on its
   target criterion (criterion monotonicity — the offline analog of the
   paper's criteria->outcome predictability study);
2. the preflight gate blocks every degraded sample;
3. the preflight gate passes the healthy baseline;
4. every report re-verifies from its payload (replay-first).

Exit code is non-zero when any gate fails, so CI can block a regression.
No network, no API key, no LLM.

Usage:
    python benchmark/context-quality/run.py            # score, write, gate
    python benchmark/context-quality/run.py --dataset other.json
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


def payload_of(sample):
    return {
        "sources": sample["sources"],
        "rendered": sample.get("rendered", ""),
        "request": sample.get("request", ""),
        "budget_tokens": sample.get("budget_tokens", 0),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Context-quality preflight discrimination benchmark (#969)")
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--out-results", default=str(HERE / "results.json"))
    ap.add_argument("--out-report", default=str(HERE / "report.md"))
    args = ap.parse_args()

    perseus = load_perseus()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if dataset.get("schema_version") != "perseus-context-quality-benchmark/v1":
        sys.exit("error: unsupported dataset schema version")

    baseline = None
    per_sample = []
    for sample in dataset["samples"]:
        payload = payload_of(sample)
        report = perseus.score_context_quality(payload, created_by="benchmark")
        check = perseus.verify_quality_report(report, payload)
        row = {
            "id": sample["id"],
            "degrade": sample.get("degrade"),
            "overall": report["overall"]["score"],
            "preflight_pass": report["preflight"]["pass"],
            "blocked": report["preflight"]["blocked"],
            "verifies": check["valid"],
            "criteria": {k: v["score"] for k, v in report["criteria"].items()},
        }
        if sample["id"] == "healthy-baseline":
            baseline = row
        per_sample.append(row)

    assert baseline is not None, "dataset must contain the healthy baseline"
    errors: list[str] = []

    # Gate 1: preflight passes the baseline.
    if not baseline["preflight_pass"]:
        errors.append("healthy baseline blocked by preflight: "
                      + ", ".join(baseline["blocked"]))
    if not baseline["verifies"]:
        errors.append("healthy baseline report failed verification")

    # Gates 2-4: monotonicity + blocking + verification per degraded sample.
    for row in per_sample:
        if row["id"] == "healthy-baseline":
            continue
        degrades = row["degrade"]
        if isinstance(degrades, str):
            degrades = [degrades]
        for criterion in degrades:
            if row["criteria"][criterion] >= baseline["criteria"][criterion]:
                errors.append(
                    f"{row['id']}: {criterion} not strictly below baseline "
                    f"({row['criteria'][criterion]} >= "
                    f"{baseline['criteria'][criterion]})")
        if not row["preflight_pass"]:
            # must block AND the degraded criterion must be among the blocked
            for criterion in degrades:
                if criterion not in row["blocked"]:
                    errors.append(
                        f"{row['id']}: preflight blocked but not for "
                        f"degraded criterion {criterion}")
        else:
            errors.append(f"{row['id']}: preflight passed a degraded sample")
        if not row["verifies"]:
            errors.append(f"{row['id']}: report failed verification")

    results = {
        "schema_version": "perseus-context-quality-benchmark-results/v1",
        "dataset": Path(args.dataset).name,
        "dataset_sha256": hashlib.sha256(
            Path(args.dataset).read_bytes()).hexdigest(),
        "samples": len(per_sample),
        "pass": not errors,
        "errors": errors,
        "per_sample": per_sample,
    }
    Path(args.out_results).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Context-quality preflight discrimination — results (#969)",
        "",
        f"- dataset: `{Path(args.dataset).name}` "
        f"(`{results['dataset_sha256'][:16]}…`, {len(per_sample)} samples)",
        f"- gate: **{'PASS' if not errors else 'FAIL'}**",
        "",
        "| sample | degrade | overall | preflight | blocked criteria |",
        "|---|---|---|---|---|",
    ]
    for row in per_sample:
        degrade = row["degrade"]
        if isinstance(degrade, list):
            degrade = "+".join(degrade)
        lines.append(
            f"| {row['id']} | {degrade} | {row['overall']:.2f} | "
            f"{'PASS' if row['preflight_pass'] else 'BLOCK'} | "
            f"{', '.join(row['blocked']) or '—'} |")
    for err in errors:
        lines.append(f"- ❌ {err}")
    lines.append("")
    Path(args.out_report).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"preflight discrimination: {'PASS' if not errors else 'FAIL'} "
          f"({len(per_sample)} samples)")
    for err in errors:
        print(" -", err)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
