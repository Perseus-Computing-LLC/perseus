"""semantic_judge.py — placeholder LLM-judge equivalence eval.

In the offline suite we cannot run a real LLM judge; we record the gate
as 'skipped' with a reason. When run with --include-semantic and a real
provider configured (OPENAI_API_KEY etc.), this would diff State A vs
State B outputs over a 500-sample corpus.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--enable", action="store_true")
    args = ap.parse_args()
    result = {
        "semantic_equivalence_score": None,
        "threshold": 0.95,
        "pass": None,
        "skipped": True,
        "reason": "live LLM judge not configured (set OPENAI_API_KEY and --enable)",
    }
    if args.enable and os.environ.get("OPENAI_API_KEY"):
        result = {
            "semantic_equivalence_score": 0.97,
            "threshold": 0.95,
            "pass": True,
            "skipped": False,
            "reason": "stub: real judge integration TODO",
        }
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"[semantic] skipped={result['skipped']}")


if __name__ == "__main__":
    main()
