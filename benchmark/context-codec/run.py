#!/usr/bin/env python3
"""Context Codec commitment-preservation benchmark (#971).

Offline, deterministic evaluation of commitment-preserving verifiable
compression: for each long-session corpus entry with planted commitments,

1. extraction recovers the expected typed atoms (safety boundaries and
   critical atoms at minimum, tool results/evidence/decisions via
   structured records);
2. deterministic compression preserves every commitment — Critical Atom
   Recall == 1.0 (gate >= 0.99), Weighted Atom Recall >= 0.99, round-trip
   recoverability == 1.0, zero safety-boundary atoms lost;
3. the fail-closed path fires with an injected lossy compressor (drops the
   commitment table): output reverts to the ORIGINAL text on every session;
4. every compaction report re-verifies from its inputs.

Exit code is non-zero when any gate fails, so CI can block a regression.
No network, no API key, no LLM.

Usage:
    python benchmark/context-codec/run.py            # score, write, gate
    python benchmark/context-codec/run.py --dataset other.json
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
    ap = argparse.ArgumentParser(description="Context Codec benchmark (#971)")
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--out-results", default=str(HERE / "results.json"))
    ap.add_argument("--out-report", default=str(HERE / "report.md"))
    args = ap.parse_args()

    perseus = load_perseus()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    if dataset.get("schema_version") != "perseus-context-codec-benchmark/v1":
        sys.exit("error: unsupported dataset schema version")

    per_session = []
    errors: list[str] = []
    for ses in dataset["sessions"]:
        sources = [{"source_id": "ctx:main", "content": ses["text"]}]
        registry = perseus.extract_commitments(
            sources, explicit_atoms=ses.get("atoms", []))
        atoms = list(registry.atoms.values())
        critical = [a for a in atoms if a.risk == "critical"]
        safety = [a for a in atoms if a.atom_type == "safety_boundary"]
        exp = ses["expected"]

        out = perseus.compress_with_commitments(
            registry, ses["text"], created_by="benchmark")
        v = out["report"]["verification"]
        m = v["metrics"]
        replay = perseus.verify_codec_report(
            out["report"], registry=registry, original=ses["text"],
            output=out["text"])

        # Fail-closed path: a lossy compressor that destroys the table.
        def lossy(candidate):
            return candidate.split("<!-- commitment-table:end -->")[-1]
        out_lossy = perseus.compress_with_commitments(
            registry, ses["text"], body_compressor=lossy, created_by="benchmark")

        row = {
            "id": ses["id"],
            "atoms": len(atoms),
            "critical": len(critical),
            "safety": len(safety),
            "critical_atom_recall": m["critical_atom_recall"],
            "weighted_atom_recall": m["weighted_atom_recall"],
            "round_trip": m["round_trip_recoverability"],
            "tokens_before": out["report"]["tokens_before"],
            "tokens_after": out["report"]["tokens_after"],
            "fallback": out["report"]["fallback"],
            "lossy_fell_back": out_lossy["report"]["fallback"],
            "lossy_returned_original": out_lossy["text"] == ses["text"],
            "replay_verifies": replay["valid"],
        }
        per_session.append(row)

        if len(critical) < exp["critical"]:
            errors.append(f"{ses['id']}: extracted {len(critical)} critical "
                          f"atoms < expected {exp['critical']}")
        if len(safety) < exp["safety"]:
            errors.append(f"{ses['id']}: extracted {len(safety)} safety "
                          f"atoms < expected {exp['safety']}")
        if len(atoms) < exp["total_min"]:
            errors.append(f"{ses['id']}: extracted {len(atoms)} atoms < "
                          f"expected {exp['total_min']}")
        if out["report"]["fallback"]:
            errors.append(f"{ses['id']}: deterministic path fell back "
                          f"unexpectedly")
        if m["critical_atom_recall"] < 0.99:
            errors.append(f"{ses['id']}: CAR {m['critical_atom_recall']} < 0.99")
        if m["weighted_atom_recall"] < 0.99:
            errors.append(f"{ses['id']}: WAR {m['weighted_atom_recall']} < 0.99")
        if m["round_trip_recoverability"] != 1.0:
            errors.append(f"{ses['id']}: round-trip "
                          f"{m['round_trip_recoverability']} < 1.0")
        if any(e["code"] == "safety_boundary_loss" for e in v["errors"]):
            errors.append(f"{ses['id']}: safety-boundary atom lost")
        if not out_lossy["report"]["fallback"] or \
                out_lossy["text"] != ses["text"]:
            errors.append(f"{ses['id']}: fail-closed path did not restore "
                          f"the original")
        if not replay["valid"]:
            errors.append(f"{ses['id']}: report replay failed: "
                          + "; ".join(replay["errors"]))

    results = {
        "schema_version": "perseus-context-codec-benchmark-results/v1",
        "dataset": Path(args.dataset).name,
        "dataset_sha256": hashlib.sha256(
            Path(args.dataset).read_bytes()).hexdigest(),
        "sessions": len(per_session),
        "pass": not errors,
        "errors": errors,
        "per_session": per_session,
    }
    Path(args.out_results).write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Context Codec benchmark — results (#971)",
        "",
        f"- dataset: `{Path(args.dataset).name}` "
        f"(`{results['dataset_sha256'][:16]}…`, {len(per_session)} sessions)",
        f"- gate: **{'PASS' if not errors else 'FAIL'}**",
        "",
        "| session | atoms (crit/safety) | CAR | WAR | round-trip | "
        "tokens | fail-closed |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in per_session:
        lines.append(
            f"| {row['id']} | {row['atoms']} ({row['critical']}/"
            f"{row['safety']}) | {row['critical_atom_recall']:.0%} | "
            f"{row['weighted_atom_recall']:.0%} | {row['round_trip']:.0%} | "
            f"{row['tokens_before']}→{row['tokens_after']} | "
            f"{'✅' if row['lossy_returned_original'] else '❌'} |")
    for err in errors:
        lines.append(f"- ❌ {err}")
    lines.append("")
    Path(args.out_report).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"context-codec gate: {'PASS' if not errors else 'FAIL'} "
          f"({len(per_session)} sessions)")
    for err in errors:
        print(" -", err)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
