from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


GAUNTLET_DIR = Path(__file__).resolve().parents[1] / "benchmark" / "gauntlet"
sys.path.insert(0, str(GAUNTLET_DIR))

from gauntlet_lib import GateRunner, _compute_gauntlet_score, budget_gate_threshold  # noqa: E402
import gauntlet_adversarial  # noqa: E402
import gauntlet_node  # noqa: E402


def test_gate_report_does_not_count_skipped_hard_gate_as_passed():
    runner = GateRunner()
    runner.add_gate(
        "Phase 8 semantic judge",
        severity="hard",
        threshold="True",
        threshold_fn=lambda _results: (True, "skipped: missing API key"),
    )

    results = runner.evaluate_all({})
    report = GateRunner.make_report(results)

    assert results[0]["skipped"] is True
    assert report["passed"] == 0
    assert report["active_total"] == 0
    assert report["skipped_count"] == 1
    assert report["pass"] is False
    assert report["by_category"]["environment"]["skipped"] == 1


def test_skipped_hard_gate_does_not_score_as_perfect_certification():
    gate_results = [{
        "name": "Phase 8 semantic judge",
        "pass": False,
        "observed": "skipped: missing API key",
        "threshold": "True",
        "severity": "hard",
        "category": "environment",
        "skipped": True,
    }]
    report = GateRunner.make_report(gate_results)

    score = _compute_gauntlet_score(
        report,
        [{"phase": 8, "name": "Semantic Integrity", "status": "skipped"}],
        gate_results,
    )

    assert score == 0.0


def test_budget_overrun_is_hard_gate_failure():
    runner = GateRunner()
    runner.add_gate(
        "Phase time budgets",
        severity="hard",
        threshold="within_time_budget == True",
        threshold_fn=budget_gate_threshold,
        category="performance",
    )

    results = runner.evaluate_all({
        "phase_2": {
            "phase": 2,
            "name": "Warm Baseline",
            "duration_s": 902.4,
            "max_duration_s": 900,
            "within_time_budget": False,
        }
    })
    report = GateRunner.make_report(results)

    assert report["pass"] is False
    assert report["hard_failed"][0]["name"] == "Phase time budgets"
    assert report["hard_failed"][0]["observed"][0]["over_by_s"] == 2.4
    assert report["by_category"]["performance"]["failed"] == 1


def test_budget_gate_passes_when_all_executed_phases_are_in_budget():
    passed, observed = budget_gate_threshold({
        "phase_1": {"phase": 1, "within_time_budget": True},
        "phase_2": {"phase": 2},
    })

    assert passed is True
    assert observed == "all executed phases within time budget"


def test_render_profile_sets_dangerous_env(monkeypatch, tmp_path):
    captured = {}

    def fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="ok", stderr="BENCH|cache_hits=1|cache_misses=0|")

    monkeypatch.setattr(gauntlet_node, "COLD_HOME", tmp_path / "cold")
    monkeypatch.setattr(gauntlet_node, "WARM_HOME", tmp_path / "warm")
    monkeypatch.setattr(gauntlet_node, "perseus_executable", lambda: "/tmp/perseus.py")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = gauntlet_node.render_profile(tmp_path / "profile.md")

    assert result["success"] is True
    assert captured["env"]["PERSEUS_ALLOW_DANGEROUS"] == "1"
    assert captured["env"]["PERSEUS_BENCH"] == "1"


def test_adversarial_runner_sets_dangerous_env(monkeypatch, tmp_path):
    captured_envs = []

    def fake_run(*args, **kwargs):
        captured_envs.append(kwargs["env"])
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(gauntlet_adversarial, "perseus_executable", lambda: "/tmp/perseus.py")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = gauntlet_adversarial.run_scenario(
        "unit",
        duration_s=0.001,
        perseus_home=tmp_path,
    )

    assert result["recovery_status"] == "clean"
    assert captured_envs
    assert all(env["PERSEUS_ALLOW_DANGEROUS"] == "1" for env in captured_envs)
