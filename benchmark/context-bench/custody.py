#!/usr/bin/env python3
"""Custody verification for a Context-Bench results envelope (#961).

Fail-closed public-evidence checks per the benchmark custody discipline:

1. every committed input (pilot, corpus files, rubric) matches its recorded
   SHA-256;
2. the results envelope digest recomputes;
3. no forbidden payload leaks into results (prompts, submissions, judge raw
   text beyond the 200-char bound, credential-shaped strings);
4. aggregate denominators match row counts.

Exit 0 only when every check passes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

FORBIDDEN = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9\-_\.]{20,}|"
    r"AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"api[_-]?key[=:]\s*['\"]?[A-Za-z0-9]{16,})", re.I)


def _sha_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def verify(results_path: str) -> dict:
    failures: list[str] = []
    results = json.load(open(results_path, encoding="utf-8"))
    manifest = results.get("manifest") or {}

    # 1. input commitments
    pilot_path = os.path.join(HERE, "pilot.json")
    if manifest.get("pilot_sha256") != _sha_file(pilot_path):
        failures.append("pilot.json hash mismatch")
    for name, digest in (manifest.get("corpus_sha256") or {}).items():
        fp = os.path.join(HERE, "files", name)
        if not os.path.exists(fp) or _sha_file(fp) != digest:
            failures.append(f"corpus file {name} hash mismatch")
    rubric_path = os.path.join(HERE, "upstream", "rubric.txt")
    if manifest.get("rubric_sha256") != _sha_file(rubric_path):
        failures.append("rubric.txt hash mismatch")

    # 2. envelope digest
    body = {k: v for k, v in results.items() if k != "results_digest"}
    digest = hashlib.sha256(
        json.dumps(body, indent=2, sort_keys=True).encode()).hexdigest()
    if digest != results.get("results_digest"):
        failures.append("results_digest does not recompute")

    # 3. forbidden payload scan
    flat = json.dumps(results, sort_keys=True)
    for m in FORBIDDEN.finditer(flat):
        failures.append(f"credential-shaped payload detected near {m.group(0)[:24]}...")
    # prompts must not appear (answer prompts contain the corpus bodies)
    if '"prompt"' in flat:
        failures.append("raw prompt bodies present in results")
    # raw judge/submission text bound
    for sid, arms in (results.get("rows") or {}).items():
        for name, row in arms.items():
            judge = (row or {}).get("judge") or {}
            if len(judge.get("raw", "")) > 200:
                failures.append(f"{sid}/{name}: judge raw exceeds 200 chars")

    # 4. aggregate denominators
    rows = results.get("rows") or {}
    agg = results.get("aggregate") or {}
    for name, cell in agg.items():
        n = cell.get("n", 0)
        actual = sum(1 for arms in rows.values()
                     if name in arms and not arms[name].get("skipped")
                     and not arms[name].get("answer_error")
                     and ((arms[name].get("judge") or {}).get("score") is not None
                          or (arms[name].get("judge") or {}).get("mock")))
        if n != actual:
            failures.append(f"aggregate[{name}].n={n} != {actual} scored rows")

    ok = not failures
    report = {
        "verified": ok,
        "failures": failures,
        "pilot_sha256": _sha_file(pilot_path),
        "rubric_sha256": _sha_file(rubric_path),
        "results_digest": results.get("results_digest"),
        "rows": len(rows),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(HERE, "results", "live", "results.json")
    report = verify(path)
    sys.exit(0 if report["verified"] else 1)
