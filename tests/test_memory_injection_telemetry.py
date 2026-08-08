"""Memory-injection efficiency accounting (#929)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from conftest import perseus


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_telemetry_has_denominators_and_distinguishes_degraded_states():
    telemetry = perseus.MemoryInjectionTelemetry()
    event = telemetry.record(
        session_id="s1", surface="recall", trigger="task", delivered_text="short context",
        baseline_tokens=100, source_count=3, corpus_size=20, profile="relevant",
    )
    assert event["state"] == "measured"
    assert event["tokens_avoided"] == 96
    assert event["savings_ratio"] > 0
    empty = telemetry.record(session_id="s2", surface="recall", trigger="task", delivered_tokens=0, baseline_tokens=0, state="empty", reason="no matches")
    degraded = telemetry.record(session_id="s3", surface="recall", trigger="task", delivered_tokens=4, baseline_tokens=100, state="degraded", reason="vault unavailable")
    assert empty["tokens_avoided"] is None and empty["savings_ratio"] is None
    assert degraded["tokens_avoided"] is None and degraded["state"] == "degraded"
    report = telemetry.report()
    assert report["denominators"]["events"] == 3
    assert report["states"] == {"degraded": 1, "empty": 1, "measured": 1}
    assert "short context" not in str(report)


def test_memory_injection_benchmark_is_offline_and_citation_ready():
    run = _load(Path(__file__).parents[1] / "benchmark" / "memory_injection" / "run.py")
    report = run.run_benchmark()
    assert report["offline"] is True
    assert report["artifact_sha256"]
    assert report["methodology"]["baseline_definition"]
    assert report["summary"]["measured_events"] > 0
    assert report["summary"]["degraded_events"] >= 1
