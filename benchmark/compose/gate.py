#!/usr/bin/env python3
"""CI gate for Perseus's headline context-compiler claim.

Runs the reproducible compose benchmark (run.py) and asserts the published
numbers hold: the Perseus-compiled context is a large, deterministic token
reduction with full answer coverage. If a change regresses the compiler so the
context bloats or drops a required fact, this fails loudly.

Conservative thresholds (current actuals: 76.3% reduction, 4/4 coverage,
deterministic over 5 renders) so normal corpus/tokenizer drift does not flake.

Exit 0 on pass, 1 on failure. Usage: python benchmark/compose/gate.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

MIN_REDUCTION_PCT = 70.0   # Perseus-compiled context must be >=70% smaller than naive
REQUIRE_FULL_COVERAGE = True   # and must still contain every gold fact
REQUIRE_DETERMINISTIC = True   # and be byte-identical across renders


def main():
    out = os.path.join(tempfile.gettempdir(), "perseus-compose-gate.json")
    r = subprocess.run([sys.executable, str(HERE / "run.py"), "--json", out],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print("FAIL: benchmark run.py exited nonzero")
        print(r.stdout[-1000:]); print(r.stderr[-1000:])
        return 1
    data = json.loads(Path(out).read_text(encoding="utf-8"))

    perseus_row = next((row for row in data["rows"] if row["path"].startswith("perseus")), None)
    pmeta = data.get("perseus", {})
    if perseus_row is None:
        print("FAIL: no perseus row in benchmark output")
        return 1

    reduction = perseus_row["reduction_pct"]
    coverage = perseus_row["answer_coverage"]   # e.g. "4/4"
    deterministic = pmeta.get("deterministic")
    print(f"perseus: reduction={reduction}%  coverage={coverage}  deterministic={deterministic}  "
          f"(token_method={data.get('token_method')})")

    ok = True
    if reduction < MIN_REDUCTION_PCT:
        print(f"FAIL: token reduction {reduction}% < {MIN_REDUCTION_PCT}% (compiler is bloating context)")
        ok = False
    if REQUIRE_FULL_COVERAGE:
        try:
            got, total = (int(x) for x in coverage.split("/"))
        except Exception:
            got, total = 0, 1
        if got < total:
            print(f"FAIL: answer coverage {coverage} is not full (compiler dropped a required fact)")
            ok = False
    if REQUIRE_DETERMINISTIC and not deterministic:
        print("FAIL: perseus compile is not byte-deterministic across renders")
        ok = False
    if ok:
        print("PASS: Perseus compiles a deterministic, high-reduction, full-coverage context.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
