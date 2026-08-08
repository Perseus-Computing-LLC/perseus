"""Citation-ready offline benchmark for #929."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
import perseus  # noqa: E402


def run_benchmark():
    report = perseus.build_memory_injection_report()
    # Recompute the outer commitment after adding benchmark metadata; retaining
    # the product report's inner commitment preserves both provenance layers.
    result = {**report, "benchmark": "memory-injection-efficiency", "methodology": {**report["methodology"], "artifact_command": "python benchmark/memory_injection/run.py --out report.json"}}
    result["artifact_sha256"] = perseus._mit_sha({key: value for key, value in result.items() if key != "artifact_sha256"})
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    report = run_benchmark()
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
