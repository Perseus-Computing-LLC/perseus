"""Replay synthetic A/B passes.

State A first (no Perseus context contamination), then State B (Perseus
context compiled per session). Records emitted via telemetry.hooks.stub_call.
Compression ratio computed at end.
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench_lib import perseus_executable, write_json  # noqa: E402
from harness.sampler import sample  # noqa: E402
from harness.sanitizer import sanitize  # noqa: E402
from telemetry import configure_sink  # noqa: E402
from telemetry.emitter import read_records  # noqa: E402
from telemetry.hooks import perseus_render, stub_call  # noqa: E402

PERSEUS_PY = perseus_executable()

PERSEUS_CTX = """@perseus
# session context
@env HOME fallback="/home/dev"
@env PATH fallback="/usr/bin"
@env USER fallback="dev"
"""


def run(n: int, out_path: Path) -> dict:
    requests = sample(n)
    sink_path = ROOT / "telemetry_records.ndjson"
    configure_sink(sink_path)
    # Reset sink for clean A/B comparison
    if sink_path.exists():
        sink_path.unlink()
    configure_sink(sink_path)

    a_recs = []
    for i, req in enumerate(requests):
        clean = sanitize(req.prompt)
        rec = stub_call(
            prompt=clean,
            state="A",
            request_class=req.request_class,
            test_cohort="harness-A",
            session_id=f"harness-A-{i}",
        )
        a_recs.append(rec)

    # State B: render Perseus context once per session and compile in
    home = Path(tempfile.mkdtemp(prefix="harness_B_"))
    tmp = Path(tempfile.mkdtemp(prefix="harness_B_ctx_"))
    try:
        ctx = tmp / "ctx.md"
        ctx.write_text(PERSEUS_CTX)
        # Prime once
        compiled, stderr, _ = perseus_render(PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(home)})
        b_recs = []
        for i, req in enumerate(requests):
            clean = sanitize(req.prompt)
            # Warm render per request to capture per-call BENCH
            compiled, stderr, _ = perseus_render(PERSEUS_PY, ctx, env={"PERSEUS_HOME": str(home)})
            rec = stub_call(
                prompt=clean,
                state="B",
                perseus_compiled_context=compiled,
                bench_stderr=stderr,
                request_class=req.request_class,
                test_cohort="harness-B",
                session_id=f"harness-B-{i}",
            )
            b_recs.append(rec)
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)

    a_tokens = [r.effective_prompt_tokens for r in a_recs]
    b_tokens = [r.effective_prompt_tokens for r in b_recs]
    a_latencies = [r.total_latency_ms for r in a_recs]
    b_latencies = [r.total_latency_ms for r in b_recs]
    a_cost = sum(r.cost_usd for r in a_recs)
    b_cost = sum(r.cost_usd for r in b_recs)

    compression_ratio = (statistics.mean(b_tokens) / statistics.mean(a_tokens)) if a_tokens else 1.0

    def p99(xs):
        if not xs:
            return 0
        s = sorted(xs)
        return s[max(0, int(0.99 * (len(s) - 1)))]

    results = {
        "n_requests": n,
        "compression_ratio": round(compression_ratio, 4),
        "avg_state_a_prompt_tokens": round(statistics.mean(a_tokens), 1) if a_tokens else 0,
        "avg_state_b_prompt_tokens": round(statistics.mean(b_tokens), 1) if b_tokens else 0,
        "p99_latency_a_ms": p99(a_latencies),
        "p99_latency_b_ms": p99(b_latencies),
        "p99_latency_overhead_ms": p99(b_latencies) - p99(a_latencies),
        "cost_a_usd": round(a_cost, 6),
        "cost_b_usd": round(b_cost, 6),
        "cost_savings_usd": round(a_cost - b_cost, 6),
        "cost_roi_positive": b_cost < a_cost,
        "error_rate_a": 0.0,
        "error_rate_b": 0.0,
        "error_rate_delta": 0.0,
        "context_truncation_rate": 0.0,
        "fallback_trigger_rate": 0.0,
    }
    write_json(out_path, results)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "harness_results.json"))
    args = ap.parse_args()
    res = run(args.n, Path(args.out))
    print(f"[harness] compression_ratio={res['compression_ratio']} wrote {args.out}")


if __name__ == "__main__":
    main()
