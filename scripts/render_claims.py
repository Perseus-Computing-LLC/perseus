#!/usr/bin/env python3
"""
render_claims.py -- regenerate machine-readable fields from the claims registry.

`claims.json` (repo root) is the single source of truth for Perseus public
figures. This script keeps the *machine* fields of the distribution manifests
(version + tool-count strings) in lockstep with that registry.

Usage:
    python scripts/render_claims.py            # --check (default): report drift, exit 1 if any
    python scripts/render_claims.py --check     # same as above
    python scripts/render_claims.py --write     # rewrite the machine fields in place (idempotent)

Stdlib only. Prose/marketing copy is intentionally NOT auto-rewritten here --
that stays under human review and is guarded by tests/test_claims_sync.py.
When a benchmark re-runs, edit claims.json, then run this with --write.
"""

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _claims() -> dict:
    return json.loads((_ROOT / "claims.json").read_text(encoding="utf-8"))["claims"]


# Each target maps a registry claim onto a machine field in a distribution file.
# The regex must expose three groups: (prefix)(current-value)(suffix). Every
# match of the regex in the file is synced to the claim's value.
#   (relative_path, claim_id, regex)
TARGETS = [
    ("manifest.json", "perseus_version", r'("version"\s*:\s*")([^"]*)(")'),
    ("manifest.json", "perseus_tool_count", r'(MCP server with )(\d+)( tools)'),
    ("server.json", "perseus_version", r'("version"\s*:\s*")([^"]*)(")'),
    (
        ".well-known/mcp/server-card.json",
        "perseus_version",
        r'("name"\s*:\s*"perseus"\s*,\s*"version"\s*:\s*")([^"]*)(")',
    ),
]


def _process(write: bool) -> int:
    claims = _claims()
    drifted: list[str] = []
    rewritten: list[str] = []

    for rel_path, claim_id, pattern in TARGETS:
        path = _ROOT / rel_path
        text = path.read_text(encoding="utf-8")
        desired = claims[claim_id]["value"]
        rx = re.compile(pattern)

        matches = list(rx.finditer(text))
        if not matches:
            drifted.append(f"{rel_path}: no field matched pattern for claim '{claim_id}'")
            continue

        file_drift = [m for m in matches if m.group(2) != desired]
        if not file_drift:
            continue

        for m in file_drift:
            drifted.append(
                f"{rel_path}: '{claim_id}' is {m.group(2)!r}, registry says {desired!r}"
            )

        if write:
            text = rx.sub(lambda m: m.group(1) + desired + m.group(3), text)
            path.write_text(text, encoding="utf-8")
            rewritten.append(f"{rel_path}: '{claim_id}' -> {desired!r}")

    if write:
        if rewritten:
            print("Rewrote machine fields from claims.json:")
            for line in rewritten:
                print("  " + line)
        else:
            print("No changes needed -- machine fields already match claims.json.")
        return 0

    # --check
    if drifted:
        print("Claim drift detected (run with --write to fix):", file=sys.stderr)
        for line in drifted:
            print("  " + line, file=sys.stderr)
        return 1
    print("OK -- all machine fields match claims.json.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="report drift only (default)")
    group.add_argument("--write", action="store_true", help="rewrite machine fields from claims.json")
    args = parser.parse_args()
    return _process(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
