#!/usr/bin/env python3
"""Cold-start performance gate for the Perseus single-file artifact (#660).

Follow-up anchor from #642 / #659 / #660: pin the residual cold-start numbers
in CI so a regression (e.g. re-introducing an eager import that #659 made lazy,
or a spawn-time blowup) is caught instead of silently drifting.

What it measures (medians over N spawns unless noted):

  * ``python -m perseus --version`` — the .pyc-cached module path, the fast
    invocation for single-file installs (~2x faster than ``python perseus.py``
    because CPython caches the compiled module instead of re-parsing the 1.3MB
    artifact on every spawn). GATING.
  * ``python perseus.py --version`` — the bare-script path. Informational: it
    always pays the full re-parse, so we log it (and the module/script delta)
    for tracking but only gate it loosely to catch gross regressions.
  * ``-X importtime`` total for ``--version`` startup, plus a guard that the
    #659 lazy imports (``traceback``, ``concurrent.futures``) are NOT pulled in
    at startup. Deterministic, so this is the primary GATING signal.
  * spawn -> ``initialize`` JSON-RPC round-trip over stdio, and a first
    ``tools/list`` call. Best-effort: skipped (not failed) if the handshake
    can't be driven; gated loosely when it runs.

Budgets have generous headroom over locally-measured values so the gate flags
real regressions, not CI noise, and every metric prints a ``PERF-GATE |`` row
so a failure is diagnosable from the job log. All budgets are env-overridable
(see BUDGETS below). Exits non-zero iff a GATING metric breaches its budget.

Usage:  python bench/scripts/cold_start_gate.py [path/to/perseus.py]
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ── Budgets (ms unless noted); env-overridable for tuning per runner ─────────
BUDGETS = {
    # GATING
    "version_module_ms": float(os.environ.get("PERF_GATE_VERSION_MODULE_MS", "600")),
    "importtime_total_ms": float(os.environ.get("PERF_GATE_IMPORTTIME_MS", "60")),
    "init_rtt_ms": float(os.environ.get("PERF_GATE_INIT_RTT_MS", "2000")),
    # LOOSE / catch-gross-regression only
    "version_artifact_ms": float(os.environ.get("PERF_GATE_VERSION_ARTIFACT_MS", "1200")),
}
SPAWNS = int(os.environ.get("PERF_GATE_SPAWNS", "9"))
RTT_SPAWNS = int(os.environ.get("PERF_GATE_RTT_SPAWNS", "5"))

# #659: these must stay OUT of the --version startup path. Re-importing them
# eagerly is the exact regression this gate exists to catch.
FORBIDDEN_STARTUP_IMPORTS = ("traceback", "concurrent.futures")


class Gate:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []
        self.failed = False

    def record(self, metric: str, value: str, budget: str, ok: bool | None) -> None:
        verdict = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            self.failed = True
        self.rows.append((metric, value, budget, verdict))

    def dump(self) -> None:
        print()
        for metric, value, budget, verdict in self.rows:
            print(f"PERF-GATE | {metric:<26} | {value:>12} | budget {budget:>10} | {verdict}")
        print()


def _median_spawn_ms(cmd: list[str], n: int) -> float:
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        subprocess.run(cmd, capture_output=True)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


def _importtime_report(artifact: str) -> tuple[float, set[str]]:
    """Return (max cumulative import time in ms, set of imported module names)."""
    r = subprocess.run(
        [sys.executable, "-X", "importtime", artifact, "--version"],
        capture_output=True, text=True,
    )
    max_cum_us = 0
    names: set[str] = set()
    for line in r.stderr.splitlines():
        # Format: "import time:  self [us] | cumulative | imported package"
        m = re.search(r"\|\s*(\d+)\s*\|\s*(\S.*)$", line)
        if not m:
            continue
        max_cum_us = max(max_cum_us, int(m.group(1)))
        names.add(m.group(2).strip())
    return max_cum_us / 1000.0, names


def _spawn_initialize_rtt_ms(artifact: str, workspace: str) -> tuple[float | None, bool | None]:
    """Median spawn->initialize RTT and whether a tools/list call succeeded.

    Best-effort: returns (None, None) if the handshake can't be driven.
    """
    rtts: list[float] = []
    tools_ok: bool | None = None
    for _ in range(RTT_SPAWNS):
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "perseus", "mcp", "serve", "--workspace", workspace],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
        except Exception:
            return None, None
        try:
            init = json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "perf-gate", "version": "0"}},
            })
            t0 = time.perf_counter()
            assert proc.stdin and proc.stdout
            proc.stdin.write(init + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            rtt = (time.perf_counter() - t0) * 1000.0
            if not line.strip():
                proc.terminate()
                return None, None
            rtts.append(rtt)
            # First tools/list call (correctness, not timed strictly).
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
            proc.stdin.flush()
            resp = proc.stdout.readline()
            if tools_ok is None:
                try:
                    tools_ok = "result" in json.loads(resp)
                except Exception:
                    tools_ok = False
        finally:
            try:
                proc.stdin.close()  # type: ignore[union-attr]
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    return (statistics.median(rtts) if rtts else None), tools_ok


def main() -> int:
    artifact = str(Path(sys.argv[1]).resolve()) if len(sys.argv) > 1 else "perseus.py"
    if not Path(artifact).exists():
        print(f"cold_start_gate: artifact not found: {artifact}", file=sys.stderr)
        return 2
    gate = Gate()

    # 1. module-path cold start (GATING) + bare-script (informational-loose).
    mod_ms = _median_spawn_ms([sys.executable, "-m", "perseus", "--version"], SPAWNS)
    gate.record("version_module_ms", f"{mod_ms:.0f}", f"{BUDGETS['version_module_ms']:.0f}",
                mod_ms <= BUDGETS["version_module_ms"])
    art_ms = _median_spawn_ms([sys.executable, artifact, "--version"], SPAWNS)
    gate.record("version_artifact_ms", f"{art_ms:.0f}", f"{BUDGETS['version_artifact_ms']:.0f}",
                art_ms <= BUDGETS["version_artifact_ms"])
    if mod_ms > 0:
        gate.record("module_speedup_x", f"{art_ms / mod_ms:.2f}", "info", None)

    # 2. importtime total (GATING) + forbidden-import guard (GATING).
    it_ms, names = _importtime_report(artifact)
    gate.record("importtime_total_ms", f"{it_ms:.1f}", f"{BUDGETS['importtime_total_ms']:.0f}",
                it_ms <= BUDGETS["importtime_total_ms"])
    leaked = sorted(n for n in FORBIDDEN_STARTUP_IMPORTS if n in names)
    gate.record("lazy_imports_absent", "none" if not leaked else ",".join(leaked),
                "none", not leaked)

    # 3. spawn->initialize RTT (GATING-loose) + tools/list (correctness).
    with tempfile.TemporaryDirectory() as ws:
        rtt_ms, tools_ok = _spawn_initialize_rtt_ms(artifact, ws)
    if rtt_ms is None:
        gate.record("init_rtt_ms", "n/a", f"{BUDGETS['init_rtt_ms']:.0f}", None)
    else:
        gate.record("init_rtt_ms", f"{rtt_ms:.0f}", f"{BUDGETS['init_rtt_ms']:.0f}",
                    rtt_ms <= BUDGETS["init_rtt_ms"])
    gate.record("tools_list_ok", {True: "yes", False: "no", None: "n/a"}[tools_ok],
                "yes", tools_ok)

    gate.dump()
    if gate.failed:
        print("cold_start_gate: FAILED — a gating metric breached its budget.", file=sys.stderr)
        return 1
    print("cold_start_gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
