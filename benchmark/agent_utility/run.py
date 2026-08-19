#!/usr/bin/env python3
"""Offline CLI for the #992 paired coding-agent utility protocol."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:  # direct ``python benchmark/agent_utility/run.py`` use
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from benchmark.agent_utility import protocol
    from benchmark.agent_utility.runner import run_synthetic_pair
else:
    from . import protocol
    from .runner import run_synthetic_pair


def _default_manifest() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "preregistration.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run provider-free agent-utility protocol gates")
    parser.add_argument("command", choices=("validate", "smoke", "synthetic-pair"))
    parser.add_argument("--manifest", default=str(_default_manifest()))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            output = protocol.load_manifest(args.manifest)
        elif args.command == "smoke":
            output = protocol.run_smoke(args.manifest)
        else:
            output = run_synthetic_pair(args.manifest)
        text = json.dumps(output, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except protocol.ProtocolError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
