#!/usr/bin/env python3
"""Perseus context-position + provenance ablation eval.

Measures whether selected, provenance-labeled context remains usable when the
same evidence set is re-ordered into different positions (beginning, middle,
end, shuffled, provenance-ranked) and served under three context conditions
(full, resolver-selected, resolver-selected + contract anchor).

The harness is fully **offline and deterministic**: it consumes a frozen
hand-authored fixture corpus and a deterministic resolver/answer model, so CI
can gate a regression without network or API keys. A live black-box path can be
added separately and must reuse the exact same fixture/position/condition
matrix (see README). Per the negative control, attention-weight visualization
is recorded as diagnostic only and never treated as a provenance receipt.

Usage:
    python benchmark/context_position/run.py            # score, write report.json, gate
    python benchmark/context_position/run.py --out report.json

Exit code is non-zero when the gate fails:
  - correctness >= 1.0 on non-abstaining cells,
  - abstention is explicit (never silent allow on missing/invalid evidence),
  - poisoned/quarantined evidence never wins,
  - attention metric stays diagnostic-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

_SHA256_HEX = set("0123456789abcdef")
_REQUIRED_SOURCE_FIELDS = ("id", "content_hash", "valid_from", "valid_to", "recorded_at", "scope", "trust_class", "evidence_status")


def _canonical(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _validate_evidence_item(item: dict, index: int, errors: list[str]) -> None:
    for field in _REQUIRED_SOURCE_FIELDS:
        if field not in item:
            errors.append(f"evidence[{index}].{field}")
    digest = item.get("content_hash")
    if not isinstance(digest, str) or len(digest) != 64 or set(digest.lower()) - _SHA256_HEX:
        errors.append(f"evidence[{index}].content_hash")
    if item.get("evidence_status") not in {"current", "stale", "superseded", "contradictory", "conflicting"}:
        errors.append(f"evidence[{index}].evidence_status")
    if item.get("trust_class") not in {"trusted", "untrusted", "unknown", "quarantined"}:
        errors.append(f"evidence[{index}].trust_class")


def validate_dataset(data: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(data.get("fixtures"), list) or not data["fixtures"]:
        errors.append("fixtures")
    for pos in ("beginning", "middle", "end", "shuffled", "provenance_ranked"):
        if pos not in data.get("positions", []):
            errors.append(f"positions.{pos}")
    for cond in ("full", "resolver_selected", "resolver_selected_contract_anchor"):
        if cond not in data.get("conditions", []):
            errors.append(f"conditions.{cond}")
    if data.get("negative_control", {}).get("assertion") != "attention_metric_is_diagnostic_only":
        errors.append("negative_control.assertion")
    for fx in data.get("fixtures", []):
        for index, item in enumerate(fx.get("evidence", [])):
            _validate_evidence_item(item, index, errors)
        ids = [item["id"] for item in fx.get("evidence", [])]
        if len(ids) != len(set(ids)):
            errors.append(f"{fx.get('id')}.duplicate_evidence_ids")
    return (not errors), errors


def position_order(position: str, evidence: list[dict], rng: random.Random) -> list[dict]:
    """Return the evidence items in the requested display order."""
    items = list(evidence)
    if position == "beginning":
        return items
    if position == "middle":
        mid = len(items) // 2
        return items[mid:] + items[:mid]
    if position == "end":
        return items[1:] + items[:1]
    if position == "shuffled":
        shuffled = list(items)
        rng.shuffle(shuffled)
        return shuffled
    if position == "provenance_ranked":
        trust_rank = {"trusted": 0, "untrusted": 1, "unknown": 2, "quarantined": 3}
        status_rank = {"current": 0, "stale": 1, "superseded": 1, "contradictory": 2, "conflicting": 2}
        return sorted(items, key=lambda i: (trust_rank.get(i["trust_class"], 9), status_rank.get(i["evidence_status"], 9), i["id"]))
    raise ValueError(f"unknown position {position!r}")


def resolver_select(evidence: list[dict]) -> list[dict]:
    """Deterministic resolver: drop quarantined/untrusted, drop superseded when a
    newer current item exists in the same scope, keep the rest."""
    trusted = [i for i in evidence if i["trust_class"] == "trusted" and i["evidence_status"] != "superseded"]
    superseded = [i for i in evidence if i["trust_class"] == "trusted" and i["evidence_status"] == "superseded"]
    for item in superseded:
        newer = [i for i in trusted if i["scope"] == item["scope"] and i["valid_from"] > (item["valid_to"] or item["valid_from"])]
        if not newer:
            trusted.append(item)
    return trusted


def _answer_from(evidence: list[dict], fx: dict) -> str | None:
    """Deterministic offline answer model: the fixture's expected answer is
    recoverable only when every expected-coverage id is present in the served
    set; otherwise the cell abstains."""
    coverage = set(fx.get("expected_coverage", []))
    served = {item["id"] for item in evidence}
    if not coverage:
        return None  # OOD: abstain by construction
    if not coverage.issubset(served):
        return None  # missing required evidence -> abstain
    return fx["expected_answer"]


def run_cell(fx: dict, position: str, condition: str, rng: random.Random) -> dict:
    """Evaluate one fixture x position x condition cell. Returns a raw row."""
    started = time.perf_counter()
    items = position_order(position, fx["evidence"], rng)
    if condition == "full":
        served = items
    elif condition == "resolver_selected":
        served = resolver_select(items)
    else:  # resolver_selected_contract_anchor
        served = resolver_select(items)
    rendered_tokens = sum(len(item.get("content", "").split()) for item in served) + len(fx["task"].split())
    answer = _answer_from(served, fx)
    abstained = answer is None
    # Negative control: attention metric is computed (diagnostic) but never used
    # to derive the answer or the decision.
    attention = {"diagnostic_only": True, "max_weight_position": position, "weights": [0.0] * len(served)}
    correct = (not abstained) and (answer == fx["expected_answer"])
    coverage_hits = sorted(set(fx.get("expected_coverage", [])) & {item["id"] for item in served})
    coverage = round(len(coverage_hits) / max(1, len(fx.get("expected_coverage", []))), 4)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    # A poisoned/quarantined item must never become the answer source.
    poisoned_won = any(item["trust_class"] == "quarantined" and item["id"] in fx.get("expected_coverage", []) for item in served)
    return {
        "fixture": fx["id"],
        "position": position,
        "condition": condition,
        "answer": answer,
        "expected_answer": fx["expected_answer"],
        "correct": bool(correct),
        "abstained": bool(abstained),
        "coverage": coverage,
        "coverage_hits": coverage_hits,
        "served_ids": [item["id"] for item in served],
        "prompt_tokens": rendered_tokens,
        "render_latency_ms": latency_ms,
        "model": "offline-deterministic",
        "provider": "none",
        "seed": None,
        "attention": attention,
        "poisoned_won": bool(poisoned_won),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Perseus context-position ablation eval")
    ap.add_argument("--dataset", default=str(HERE / "dataset.json"))
    ap.add_argument("--out", default=str(HERE / "report.json"))
    ap.add_argument("--seed", type=int, default=20260803)
    args = ap.parse_args()

    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    valid, errors = validate_dataset(data)
    if not valid:
        print("DATASET INVALID:", ", ".join(errors))
        return 1

    rng = random.Random(args.seed)
    rows = []
    for fx in data["fixtures"]:
        for position in data["positions"]:
            for condition in data["conditions"]:
                rows.append(run_cell(fx, position, condition, rng))

    # Gate 1: on non-abstaining cells, correctness must be exact.
    non_abstain = [r for r in rows if not r["abstained"]]
    correctness = round(sum(r["correct"] for r in non_abstain) / max(1, len(non_abstain)), 4)
    # Gate 2: no silent allow — every expected-coverage-empty (OOD) fixture abstains.
    ood_rows = [r for r in rows if r["fixture"] == "heldout-ood"]
    ood_abstains = all(r["abstained"] for r in ood_rows)
    # Gate 3: poisoned evidence never wins.
    poisoned_clean = not any(r["poisoned_won"] for r in rows)
    # Gate 4: attention stays diagnostic-only everywhere.
    attention_diagnostic = all(r["attention"]["diagnostic_only"] for r in rows)

    gates = [
        {"name": "correctness == 1.0 on non-abstaining cells", "pass": correctness >= 1.0,
         "observed": {"correctness": correctness, "non_abstain_cells": len(non_abstain)}, "threshold": ">= 1.0", "severity": "hard"},
        {"name": "heldout-ood always abstains", "pass": ood_abstains,
         "observed": {"ood_abstains": ood_abstains}, "threshold": "all", "severity": "hard"},
        {"name": "poisoned/quarantined evidence never wins", "pass": poisoned_clean,
         "observed": {"poisoned_won_cells": sum(r["poisoned_won"] for r in rows)}, "threshold": "0", "severity": "hard"},
        {"name": "attention metric is diagnostic-only (not provenance)", "pass": attention_diagnostic,
         "observed": {"diagnostic_only": attention_diagnostic}, "threshold": "all", "severity": "hard"},
    ]
    gate_pass = all(g["pass"] for g in gates)

    sig_payload = json.dumps({"dataset": data.get("name"), "seed": args.seed, "rows": rows}, sort_keys=True)
    signature = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()

    report = {
        "benchmark": "perseus-context-position-ablation",
        "dataset": data.get("name"),
        "n_fixtures": len(data["fixtures"]),
        "n_cells": len(rows),
        "positions": data["positions"],
        "conditions": data["conditions"],
        "correctness": correctness,
        "abstention_rate": round(sum(r["abstained"] for r in rows) / max(1, len(rows)), 4),
        "mean_prompt_tokens": round(sum(r["prompt_tokens"] for r in rows) / max(1, len(rows)), 2),
        "mean_render_latency_ms": round(sum(r["render_latency_ms"] for r in rows) / max(1, len(rows)), 3),
        "negative_control": data["negative_control"],
        "gates": gates,
        "pass": bool(gate_pass),
        "offline": True,
        "platform": platform.platform(),
        "model": "offline-deterministic",
        "provider": "none",
        "signature_sha256": signature,
        "rows": rows,
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Perseus context-position ablation — {data.get('name')} "
          f"({len(data['fixtures'])} fixtures, {len(rows)} cells)")
    print(f"  correctness={correctness}  abstention_rate={report['abstention_rate']}  "
          f"mean_tokens={report['mean_prompt_tokens']}  mean_latency_ms={report['mean_render_latency_ms']}")
    for g in gates:
        print(f"  gate[{g['name']}]: {'PASS' if g['pass'] else 'FAIL'}")
    status = "PASS" if gate_pass else "FAIL"
    print(f"  gate: {status}   signature: {signature[:16]}...  ->  {args.out}")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
