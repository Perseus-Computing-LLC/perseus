#!/usr/bin/env python3
"""Small, offline semantic-density benchmark for served-memory compression."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DATASET = HERE / "dataset.json"
LOAD_BEARING_CATEGORIES = frozenset({
    "constraint", "contradiction", "correction", "keystone",
    "policy", "prohibition",
})


def load_perseus():
    artifact = REPO / "perseus.py"
    spec = importlib.util.spec_from_file_location("perseus_semantic_density", artifact)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def load_dataset() -> dict:
    return json.loads(DATASET.read_text(encoding="utf-8"))


def _make_hit(perseus, item: dict):
    return perseus.MemoryHit(
        id=item["id"],
        content=item["content"],
        summary=item["content"],
        relevance=item["relevance"],
        category=item["category"],
        key=item["key"],
        external_refs=item.get("external_refs", []),
        why_served={"source_evidence_ids": item.get("source_evidence_ids", [])},
    )


def _legacy_budget(perseus, hits, budget: int):
    """Pre-slice baseline: relevance only, in-place shortening, no decoder."""
    selected = []
    spent = 0
    for hit in sorted(hits, key=lambda item: item.relevance, reverse=True):
        size = len(hit.content)
        if spent + size <= budget:
            selected.append(hit)
            spent += size
        elif not selected:
            hit.content = hit.summary[: max(1, budget - 2)].rstrip() + "…"
            hit.summary = hit.content
            selected.append(hit)
            spent += len(hit.content)
    return selected, {"decoder_refs": [], "trimmed_ids": []}


def _text(hits):
    return "\n".join(hit.content or hit.summary for hit in hits)


def _tokens(perseus, text: str) -> int:
    return perseus.estimate_tokens(text)


def evaluate_case(perseus, case: dict, method: str = "production") -> dict:
    hits = [_make_hit(perseus, item) for item in case["items"]]
    uncompressed = _text(hits)
    if method == "production":
        selected, diagnostics = perseus.apply_recall_budget(hits, case["budget_chars"])
    elif method == "legacy":
        selected, diagnostics = _legacy_budget(perseus, hits, case["budget_chars"])
    else:
        raise ValueError(f"unknown method: {method}")
    text = _text(selected)
    required = case["required_facts"]
    present = [fact for fact in required if fact.lower() in text.lower()]
    load_ids = set(case["load_bearing_ids"])
    selected_ids = {hit.id for hit in selected}
    retained = load_ids & selected_ids
    decoder_ids = {
        ref.get("id") for ref in diagnostics.get("decoder_refs", [])
        if isinstance(ref, dict)
    }
    load_bearing_retention = float(load_ids <= (retained | decoder_ids))
    decoder_recovery = float(load_ids <= (retained | decoder_ids))
    omitted_ids = sorted(
        item["id"] for item in case["items"] if item["id"] not in selected_ids
    )
    return {
        "prompt_tokens": _tokens(perseus, text),
        "uncompressed_tokens": _tokens(perseus, uncompressed),
        "task_resumption": float(len(present) == len(required)),
        "exact_fact_accuracy": len(present) / len(required) if required else 1.0,
        "load_bearing_retention": load_bearing_retention,
        "decoder_recovery": decoder_recovery,
        "selected_ids": [hit.id for hit in selected],
        "omitted_ids": omitted_ids,
        "decoder_ids": sorted(decoder_ids),
        "trimmed_ids": diagnostics.get("trimmed_ids", []),
        "raw_text": text,
    }


def _aggregate(rows: list[dict]) -> dict:
    keys = (
        "prompt_tokens", "uncompressed_tokens", "task_resumption",
        "exact_fact_accuracy", "load_bearing_retention", "decoder_recovery",
    )
    return {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in keys}


def run_benchmark(perseus, dataset: dict) -> dict:
    production = [evaluate_case(perseus, case, "production") for case in dataset["cases"]]
    legacy = [evaluate_case(perseus, case, "legacy") for case in dataset["cases"]]
    methods = {"production": _aggregate(production), "legacy": _aggregate(legacy)}
    methods["production"]["cases"] = production
    methods["legacy"]["cases"] = legacy
    gate = {
        "pass": (
            methods["production"]["task_resumption"] == 1.0
            and methods["production"]["load_bearing_retention"] == 1.0
            and methods["production"]["decoder_recovery"] == 1.0
        ),
        "requirements": [
            "production task_resumption == 1.0",
            "production load_bearing_retention == 1.0",
            "production decoder_recovery == 1.0",
        ],
    }
    report = {
        "benchmark": dataset["benchmark"],
        "version": dataset["version"],
        "offline": True,
        "network_calls": 0,
        "cases": len(dataset["cases"]),
        "methods": methods,
        "gate": gate,
    }
    payload = json.dumps(report, sort_keys=True).encode("utf-8")
    report["signature_sha256"] = hashlib.sha256(payload).hexdigest()
    return report


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(HERE / "results.json"))
    args = parser.parse_args(argv)
    report = run_benchmark(load_perseus(), load_dataset())
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    p = report["methods"]["production"]
    print(f"semantic density: {report['cases']} cases, offline, network_calls=0")
    print(f"production: resumption={p['task_resumption']:.4f} "
          f"load_bearing={p['load_bearing_retention']:.4f} "
          f"decoder={p['decoder_recovery']:.4f}")
    print(f"gate: {'PASS' if report['gate']['pass'] else 'FAIL'} -> {args.out}")
    return 0 if report["gate"]["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
