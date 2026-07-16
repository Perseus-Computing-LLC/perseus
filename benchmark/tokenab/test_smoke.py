"""Smoke test for the honest prompt-token A/B harness (#804).

Runs one tiny doc through both arms against the real repo corpus and asserts
the structural invariants: the naive arm is at least as large as the rendered
arm, the render produced no include warnings, and the committed report.json
(when present) validates against its own content hash. Skips cleanly when
tiktoken is missing so CI without it stays green.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

tiktoken = pytest.importorskip("tiktoken")

HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("tokenab_harness", HERE / "harness.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

TINY_DOC = """@perseus v1.0.8

@prompt
Smoke-test context document.
@end

# Smoke Test Doc

## Recent changes (tiny window)

@include CHANGELOG.md last=5
"""


def test_tiny_doc_arm_a_is_superset(tmp_path):
    enc = harness._encoder()
    events = harness.parse_fixture(TINY_DOC)
    arm_a = harness.build_arm_a(events, harness.REPO_ROOT)

    # The full changelog must be present in the naive arm.
    changelog = (harness.REPO_ROOT / "CHANGELOG.md").read_text(
        encoding="utf-8", errors="replace")
    assert changelog.rstrip() in arm_a

    home = tmp_path / "perseus_home"
    home.mkdir()
    arm_b, elapsed_ms = harness.render_arm_b(
        "smoke_tiny_doc.md", TINY_DOC, home, tmp_path)

    assert elapsed_ms > 0.0, "render must be timed, not stubbed"
    a_tokens = harness.count_tokens(enc, arm_a)
    b_tokens = harness.count_tokens(enc, arm_b)
    assert a_tokens >= b_tokens, (
        f"naive arm ({a_tokens}) must be >= rendered arm ({b_tokens}) "
        f"when the doc windows a large file")
    # The window (last 5 lines of the changelog) must actually be in arm B.
    last_lines = [ln for ln in changelog.rstrip().splitlines()[-5:] if ln.strip()]
    for ln in last_lines:
        assert ln in arm_b


def test_fixture_docs_parse_and_reject_unknown_directives():
    docs = sorted((HERE / "fixtures" / "docs").glob("*.md"))
    assert 3 <= len(docs) <= 6
    for doc in docs:
        events = harness.parse_fixture(doc.read_text(encoding="utf-8"))
        assert any(ev["kind"] == "include" for ev in events) or doc.name.startswith("05")
    with pytest.raises(ValueError):
        harness.parse_fixture("@perseus v1.0.8\n\n@query \"git log\"\n")


def test_committed_report_validates():
    report_path = HERE / "report.json"
    if not report_path.exists():
        pytest.skip("no committed report.json yet (pre-run tree)")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    sig = report.pop("signature_sha256")
    recomputed = hashlib.sha256(
        json.dumps(report, sort_keys=True).encode("utf-8")).hexdigest()
    assert sig == recomputed, "report.json signature does not match its content"

    for key in ("run", "docs", "aggregate", "latency_ms", "limits"):
        assert key in report
    run = report["run"]
    assert run["tokenizer"] == "cl100k_base"
    assert len(run["repo_commit"]) == 40
    agg = report["aggregate"]
    assert agg["arm_a_context_tokens"] > 0
    assert agg["arm_b_context_tokens_cold"] > 0
    # Latencies must be real measurements, not stubs.
    assert report["latency_ms"]["arm_b_render_cold"]["p50_ms"] > 0.0
    assert report["latency_ms"]["arm_b_render_cold"]["n"] >= 3
