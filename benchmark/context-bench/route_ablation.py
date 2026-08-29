"""Run the provider-free Context route ablation canary.

This is intentionally a small offline harness. It emits the same
``perseus-context-route-ablation/v1`` envelope as the MCP operation and never
loads answer-session IDs, gold answers, or evaluator labels.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import perseus


def _load_fixture(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("fixture must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline Context route ablation canary")
    parser.add_argument("--fixture", type=Path, default=Path(__file__).with_name("route_ablation_fixture.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    fixture = _load_fixture(args.fixture)
    report = perseus.run_context_route_ablation(
        fixture["task"],
        records=fixture["records"],
        scope=fixture["scope"],
        query_time_unix_ms=fixture["query_time_unix_ms"],
        provider_states=fixture["provider_states"],
        manifest=fixture["manifest"],
        route_scores=fixture.get("route_scores"),
        policy=fixture.get("policy"),
        budget=fixture.get("budget"),
    )
    verification = perseus.verify_route_ablation(report)
    if not verification.get("valid"):
        raise RuntimeError("route-ablation verification failed: " + ", ".join(verification.get("errors", [])))
    rendered = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
