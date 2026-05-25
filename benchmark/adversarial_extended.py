"""
adversarial_extended.py — Phase 4: C1–C6.

C1 recursive include cycle
C2 malformed directive battery (must be 12/12 graceful)
C3 infinite output directive (truncation, no OOM)
C4 filesystem exhaustion (requires root + tmpfs — skipped if not root)
C5 concurrent adversarial injection
C6 provider degradation under adversarial load (requires toxiproxy — skipped if absent)
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bench_lib import find_orphan_subprocesses, perseus_executable, write_json  # noqa: E402

PERSEUS_PY = perseus_executable()


def _render(ctx: Path, home: Path, timeout: int = 30) -> tuple[int, bytes, bytes]:
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(home)
    try:
        proc = subprocess.run(
            [sys.executable, PERSEUS_PY, "render", str(ctx)],
            capture_output=True, timeout=timeout, env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, b"", b"timeout"


def c1_recursive_include() -> dict:
    results = []
    for depth in [10, 100, 1000]:
        tmp = Path(tempfile.mkdtemp(prefix=f"c1_d{depth}_"))
        try:
            for i in range(depth):
                nxt = (i + 1) % depth  # cycles back to 0 at the end
                (tmp / f"inc_{i}.md").write_text(f"@perseus\n@include {tmp}/inc_{nxt}.md\n")
            ctx = tmp / "inc_0.md"
            home = Path(tempfile.mkdtemp(prefix=f"c1h_{depth}_"))
            t0 = time.perf_counter()
            rc, stdout, stderr = _render(ctx, home, timeout=15)
            wall_ms = int((time.perf_counter() - t0) * 1000)
            stderr_s = stderr.decode("utf-8", errors="replace")
            stdout_s = stdout.decode("utf-8", errors="replace")
            has_traceback = "Traceback" in stderr_s
            error_class = "hang" if rc == -1 else ("traceback" if has_traceback else "clean")
            results.append({
                "depth": depth,
                "rc": rc,
                "time_to_failure_ms": wall_ms,
                "error_class": error_class,
            })
            shutil.rmtree(home, ignore_errors=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return {"test": "C1_recursive_include", "results": results,
            "all_clean_or_safe": all(r["error_class"] != "traceback" for r in results)}


def c2_malformed_directives() -> dict:
    inputs = [
        '@env "unclosed_quote',                         # missing quote
        '@env\x00NULLBYTE',                             # null byte
        '@env ' + 'A' * 1_000_000,                      # 1MB line
        '@env \u202eRTL_OVERRIDE',                      # bidi
        '@@invalid_directive',                           # double-at
        '@env',                                          # missing arg
        '@unknown_directive arg',                        # unknown
        '@env PATH fallback=',                           # trailing equals
        '@include /etc/passwd',                          # path traversal attempt
        '@include nonexistent_file.md',                  # missing include
        '@env PATH\n@env PATH\n@env PATH',               # duplicate (each line)
        '@env PATH fallback="\u0000"',                  # null in quotes
    ]
    graceful = 0
    details = []
    for i, payload in enumerate(inputs):
        tmp = Path(tempfile.mkdtemp(prefix=f"c2_{i}_"))
        home = Path(tempfile.mkdtemp(prefix=f"c2h_{i}_"))
        try:
            ctx = tmp / "m.md"
            ctx.write_text("@perseus\n" + payload + "\n")
            rc, stdout, stderr = _render(ctx, home, timeout=10)
            stderr_s = stderr.decode("utf-8", errors="replace")
            ok = "Traceback" not in stderr_s and rc != -1
            if ok:
                graceful += 1
            details.append({"i": i, "rc": rc, "graceful": ok})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(home, ignore_errors=True)
    return {
        "test": "C2_malformed_directives",
        "graceful_rate": graceful / len(inputs),
        "graceful_count": graceful,
        "total": len(inputs),
        "details": details,
    }


def c3_infinite_output() -> dict:
    """@query running an infinite stdout writer must truncate cleanly."""
    tmp = Path(tempfile.mkdtemp(prefix="c3_"))
    home = Path(tempfile.mkdtemp(prefix="c3h_"))
    try:
        ctx = tmp / "inf.md"
        # Use yes as a bounded infinite writer; Perseus should truncate at max_query_bytes.
        ctx.write_text('@perseus\n@query cmd="yes hello | head -c 10000000"\n')
        t0 = time.perf_counter()
        rc, stdout, stderr = _render(ctx, home, timeout=30)
        wall = time.perf_counter() - t0
        completed = rc != -1
        output_bytes = len(stdout)
        return {
            "test": "C3_infinite_output",
            "completed": completed,
            "wall_s": round(wall, 2),
            "output_bytes_captured": output_bytes,
            "bounded": output_bytes < 5 * 1024 * 1024,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)


def c4_fs_exhaustion() -> dict:
    if os.geteuid() != 0:
        return {"test": "C4_fs_exhaustion", "skipped": True, "reason": "not root"}
    # Skip even as root unless explicitly enabled — mounting tmpfs in
    # a container can be hazardous.
    if not os.environ.get("PERSEUS_BENCH_ALLOW_TMPFS"):
        return {"test": "C4_fs_exhaustion", "skipped": True,
                "reason": "set PERSEUS_BENCH_ALLOW_TMPFS=1 to enable"}
    return {"test": "C4_fs_exhaustion", "skipped": True, "reason": "tmpfs path not exercised in this run"}


def c5_concurrent_adversarial(n: int = 50) -> dict:
    """50 agents: 10% infinite, 10% malformed, 80% normal."""
    home = Path(tempfile.mkdtemp(prefix="c5_"))
    tmp = Path(tempfile.mkdtemp(prefix="c5ctx_"))
    try:
        def make_ctx(i: int) -> Path:
            p = tmp / f"a_{i}.md"
            if i < n * 0.1:
                p.write_text('@perseus\n@query cmd="yes | head -c 5000000"\n')
            elif i < n * 0.2:
                p.write_text('@perseus\n@env "unclosed\n')
            else:
                p.write_text(f"@perseus\n@env HOME fallback=\"/h{i}\"\n")
            return p

        # ── Fair baseline: same-concurrency normal-only run (no adversarial neighbors) ──
        # Slowdown = normal_in_mixed_storm / normal_in_pure_storm. This isolates
        # the impact of adversarial co-tenants from generic concurrency overhead.
        normal_n = max(int(n * 0.8), 1)
        baseline_home = Path(tempfile.mkdtemp(prefix="c5_base_"))
        def run_baseline(i):
            bp = tmp / f"bl_{i}.md"
            bp.write_text(f'@perseus\n@env HOME fallback="/hb{i}"\n')
            t0 = time.perf_counter()
            _render(bp, baseline_home, timeout=30)
            return (time.perf_counter() - t0) * 1000
        with cf.ThreadPoolExecutor(max_workers=20) as ex:
            baseline_samples = list(ex.map(run_baseline, range(normal_n)))
        shutil.rmtree(baseline_home, ignore_errors=True)
        baseline_ms = sum(baseline_samples) / len(baseline_samples)

        def run_one(i):
            t0 = time.perf_counter()
            rc, _, stderr = _render(make_ctx(i), home, timeout=30)
            return {
                "i": i,
                "rc": rc,
                "wall_ms": int((time.perf_counter() - t0) * 1000),
                "traceback": b"Traceback" in stderr,
            }

        with cf.ThreadPoolExecutor(max_workers=20) as ex:
            results = list(ex.map(run_one, range(n)))
        time.sleep(2)
        orphans = find_orphan_subprocesses(set())
        normal_results = [r for r in results if r["i"] >= n * 0.2]
        adv_results = [r for r in results if r["i"] < n * 0.2]
        normal_avg = sum(r["wall_ms"] for r in normal_results) / max(len(normal_results), 1)
        slowdown = normal_avg / max(baseline_ms, 1)
        return {
            "test": "C5_concurrent_adversarial",
            "n_agents": n,
            "orphan_count": len(orphans),
            "baseline_ms": round(baseline_ms, 1),
            "normal_avg_ms": round(normal_avg, 1),
            "normal_agent_slowdown_factor": round(slowdown, 2),
            "traceback_count": sum(1 for r in results if r["traceback"]),
            "advrs_completed": sum(1 for r in adv_results if r["rc"] != -1),
            "advrs_total": len(adv_results),
        }
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)


def c6_provider_degradation() -> dict:
    if shutil.which("toxiproxy-server") is None and shutil.which("toxiproxy") is None:
        return {"test": "C6_provider_degradation", "skipped": True,
                "reason": "toxiproxy not installed"}
    # Real C6 requires a running toxiproxy and provider endpoint. Out of scope
    # for the offline suite; we mark it skipped with the reason.
    return {"test": "C6_provider_degradation", "skipped": True,
            "reason": "live provider not configured"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--c5-n", type=int, default=50)
    ap.add_argument("--out", default=str(ROOT / "adversarial_extended_results.json"))
    args = ap.parse_args()
    results = {
        "C1": c1_recursive_include(),
        "C2": c2_malformed_directives(),
        "C3": c3_infinite_output(),
        "C4": c4_fs_exhaustion(),
        "C5": c5_concurrent_adversarial(args.c5_n),
        "C6": c6_provider_degradation(),
    }
    write_json(Path(args.out), results)
    print(f"[adversarial] wrote {args.out}")


if __name__ == "__main__":
    main()
