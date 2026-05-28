#!/usr/bin/env python3
"""
run_extreme_suite.py — Phase 7 unified orchestrator.

Runs Phases 0–6 in order, merges all output JSONs into ultimate_suite_results.json,
prints a Discord-ready summary, and exits with the value of `pass`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bench_lib import perseus_executable, write_json  # noqa: E402


def _phase_validate_bench_shim() -> dict:
    """Phase 0 validation: PERSEUS_BENCH=1 must emit BENCH| stderr."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="p0_"))
    try:
        ctx = tmp / "v.md"
        ctx.write_text('@perseus\n@env HOME fallback="/h"\n')
        env = os.environ.copy()
        env["PERSEUS_BENCH"] = "1"
        proc = subprocess.run(
            [sys.executable, perseus_executable(), "render", str(ctx)],
            capture_output=True, env=env, timeout=15,
        )
        bench_line = any(
            line.startswith("BENCH|")
            for line in proc.stderr.decode("utf-8", errors="replace").splitlines()
        )
        return {"phase": 0, "bench_shim_emits": bench_line, "pass": bench_line}
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _run(label: str, args: list[str]) -> dict:
    t0 = time.perf_counter()
    print(f"[runner] ▶ {label}", flush=True)
    proc = subprocess.run(args, cwd=str(ROOT))
    duration = time.perf_counter() - t0
    print(f"[runner] ✓ {label} ({duration:.1f}s, rc={proc.returncode})", flush=True)
    if proc.returncode != 0:
        print(f"[runner] ❌ {label} failed with exit code {proc.returncode}", file=sys.stderr, flush=True)
        sys.exit(proc.returncode)
    return {"label": label, "rc": proc.returncode, "duration_s": round(duration, 1)}


def _discord_summary(results: dict) -> str:
    gates = results.get("gates", {}).get("gates", [])
    overall = "PASS ✅" if results.get("pass") else "FAIL ❌"
    lines = [
        "```",
        "Perseus Ultimate Benchmark Suite",
        f"Status: {overall}",
        f"Gates: {results.get('gates', {}).get('passed', 0)}/{results.get('gates', {}).get('total', 0)}",
        "",
        f"{'Gate':<55} {'Result':<6}",
        f"{'-'*55} {'-'*6}",
    ]
    for g in gates:
        mark = "PASS" if g["pass"] else "FAIL"
        lines.append(f"{g['name'][:55]:<55} {mark:<6}")
    lines.append("```")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quick", action="store_true",
                    help="Smaller scales for fast smoke run")
    ap.add_argument("--skip-semantic", action="store_true", default=True)
    ap.add_argument("--include-semantic", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "ultimate_suite_results.json"))
    args = ap.parse_args()

    plan = []
    swarm_scales = "10,50" if args.quick else "10,50,100"
    t4_scales = "100,1000" if args.quick else "100,1000,10000"
    harness_n = 50 if args.quick else 200
    c5_n = 20 if args.quick else 50

    plan.append(("phase-0 BENCH shim", None))  # special handling
    plan.append(("phase-3 cache_thrash", [sys.executable, str(ROOT / "cache_thrash.py"), "--t4-scales", t4_scales]))
    plan.append(("phase-2 swarm_chaos", [sys.executable, str(ROOT / "swarm_chaos.py"), "--scales", swarm_scales]))
    plan.append(("phase-4 adversarial_extended", [sys.executable, str(ROOT / "adversarial_extended.py"), "--c5-n", str(c5_n)]))
    plan.append(("phase-5 harness replayer", [sys.executable, str(ROOT / "harness/replayer.py"), "--n", str(harness_n)]))
    # Phase 7 — extreme enterprise benchmark (cold/warm A/B, regression probes,
    #            concurrency stress, enterprise day sim, cache pathology)
    xeb_args = [sys.executable, str(ROOT / "extreme_enterprise_benchmark.py")]
    if args.quick:
        xeb_args += ["--quick", "--skip-memory"]
    else:
        # Full run: execute memory hygiene when possible.
        # If psutil is unavailable, XEB now marks status as PARTIAL in its own report.
        pass
    plan.append(("phase-7 extreme_enterprise", xeb_args))
    plan.append(("phase-6 gate_runner", [sys.executable, str(ROOT / "eval/gate_runner.py"), "--dir", str(ROOT)]))
    if args.include_semantic:
        plan.append(("phase-6 semantic_judge", [
            sys.executable, str(ROOT / "eval/semantic_judge.py"),
            "--out", str(ROOT / "semantic_results.json"),
            "--enable", "--n", "20", "--control-n", "5",
        ]))
    else:
        plan.append(("phase-6 semantic_judge", [sys.executable, str(ROOT / "eval/semantic_judge.py"), "--out", str(ROOT / "semantic_results.json")]))

    if args.dry_run:
        print("[dry-run] Execution plan:")
        for label, cmd in plan:
            print(f"  - {label}: {' '.join(cmd) if cmd else '(internal)'}")
        return 0

    # Delete stale output files before run so merges only use current artifacts
    _stale_outputs = [
        ROOT / "swarm_results.json",
        ROOT / "thrash_results.json",
        ROOT / "adversarial_extended_results.json",
        ROOT / "harness_results.json",
        ROOT / "gates_results.json",
        ROOT / "semantic_results.json",
        ROOT / "extreme_enterprise_results.json",
    ]
    for _p in _stale_outputs:
        if _p.exists():
            _p.unlink()
            print(f"[runner] 🗑  Removed stale {_p.name}", flush=True)

    timings = []
    p0 = _phase_validate_bench_shim()
    if not p0["pass"]:
        print("[runner] ❌ Phase 0 failed: PERSEUS_BENCH shim not emitting", file=sys.stderr)
        return 2
    timings.append({"label": "phase-0 BENCH shim", "rc": 0, "duration_s": 0.1})

    # P0 #2: Invalidate stale output files from prior runs so we never
    # merge artifacts from old runs as if they were current.
    _OUTPUT_FILES = [
        ROOT / "swarm_results.json",
        ROOT / "thrash_results.json",
        ROOT / "adversarial_extended_results.json",
        ROOT / "harness_results.json",
        ROOT / "gates_results.json",
        ROOT / "semantic_results.json",
        ROOT / "extreme_enterprise_results.json",
    ]
    for _of in _OUTPUT_FILES:
        _of.unlink(missing_ok=True)

    for label, cmd in plan[1:]:
        result = _run(label, cmd)
        timings.append(result)
        if result["rc"] != 0:
            print(f"[runner] ❌ Phase failed: {label} (rc={result['rc']})", file=sys.stderr)
            print("[runner] Aborting suite — fix phase failure before proceeding.", file=sys.stderr)
            return result["rc"]

    # Merge — only load files actually written by this run
    def load(p): return json.loads(p.read_text()) if p.is_file() else {}
    swarm = load(ROOT / "swarm_results.json")
    thrash = load(ROOT / "thrash_results.json")
    advrs = load(ROOT / "adversarial_extended_results.json")
    harness = load(ROOT / "harness_results.json")
    gates = load(ROOT / "gates_results.json")
    semantic = load(ROOT / "semantic_results.json")
    xeb = load(ROOT / "extreme_enterprise_results.json")

    suite_pass = bool(gates.get("pass", False))
    final = {
        "suite_version": "ultimate-v2",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pass": suite_pass,
        "semantic_pass": semantic.get("pass") if semantic.get("skipped") is False else None,
        "phase_0_bench_shim": p0,
        "swarm": swarm,
        "thrash": thrash,
        "adversarial": advrs,
        "harness": harness,
        "gates": gates,
        "semantic": semantic,
        "extreme_enterprise": {
            "overall_pass": xeb.get("overall_pass"),
            "overall_status": xeb.get("overall_status"),
            "overall_partial": xeb.get("overall_partial"),
            "total_duration_s": xeb.get("total_duration_s"),
            "hard_gates": xeb.get("phase_10", {}).get("hard", {}),
            "soft_gates": xeb.get("phase_10", {}).get("soft", {}),
            "partial_reasons": xeb.get("phase_10", {}).get("partial_reasons", []),
            "enterprise_day_roi_pct": xeb.get("phase_7", {}).get("estimated_roi_pct"),
            "fleet_p99_ms": xeb.get("phase_7", {}).get("fleet_latency_ms", {}).get("p99"),
        } if xeb else {"skipped": True},
        "timings": timings,
        "summary": {
            "pass": suite_pass,
            "gates_passed": gates.get("passed", 0),
            "gates_total": gates.get("total", 0),
            "failed_gates": gates.get("failed", []),
            "xeb_hard_pass": xeb.get("phase_10", {}).get("hard", {}).get("passed") ==
                             xeb.get("phase_10", {}).get("hard", {}).get("total") if xeb else None,
        },
    }
    write_json(Path(args.out), final)
    print()
    print(_discord_summary(final))
    print(f"\n[runner] Output → {args.out}")
    return 0 if suite_pass else 1


if __name__ == "__main__":
    sys.exit(main())
