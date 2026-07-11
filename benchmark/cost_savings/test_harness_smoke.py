"""Smoke test for the cost-savings harness (#749): mock mode end-to-end —
qa.py two-arm run -> journal -> Plutus ledger -> report — asserting the
plumbing invariants (both arms metered, ledger dollars nonzero, savings
computed, signature present). Skips when the local prerequisites (vault
checkout + binary, LongMemEval dataset, plutus-agent) are absent, so CI
without the ~277 MB dataset stays green.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _data_path():
    for cand in (os.environ.get("LME_DATA", ""),
                 str(Path.home() / "lme-data" / "longmemeval_s_cleaned.json")):
        if cand and Path(cand).exists():
            return cand
    return None


def _prereqs():
    try:
        import plutus_agent  # noqa: F401
    except ImportError:
        return "plutus-agent not installed"
    if _data_path() is None:
        return "LongMemEval dataset not present (set LME_DATA)"
    env = os.environ.get("PERSEUS_VAULT_REPO")
    roots = [Path(env)] if env else [HERE.parent.parent.parent / "perseus-vault",
                                     Path.home() / "perseus-vault"]
    if not any((r / "benchmark" / "longmemeval" / "qa.py").exists() for r in roots):
        return "perseus-vault checkout not found"
    return None


@pytest.mark.skipif(_prereqs() is not None, reason=str(_prereqs()))
def test_mock_mode_meters_both_arms(tmp_path):
    outdir = tmp_path / "out"
    rc = subprocess.run(
        [sys.executable, "-X", "utf8", str(HERE / "harness.py"),
         "--data", _data_path(), "--limit", "3", "--mode", "mock",
         "--outdir", str(outdir)],
        capture_output=True, text=True, timeout=1200)
    assert rc.returncode == 0, rc.stdout + rc.stderr

    report = json.loads((outdir / "cost_savings_report.json").read_text())
    assert report["mode"] == "mock"
    assert report["signature_sha256"]
    assert (outdir / "plutus_ledger.db").exists(), "ledger must ship with the report"

    base = report["arms"]["fullcontext"]
    ours = report["arms"]["mimir"]
    for arm in (base, ours):
        assert arm["ledger_events"] == 3, f"every question metered once: {arm}"
        assert arm["ledger_cost_usd"] > 0
        assert arm["accuracy"] is not None
    assert base["ledger_tokens"] > ours["ledger_tokens"], \
        "full-context must feed more tokens than top-k retrieval"
    assert report["savings_pct"] > 0
