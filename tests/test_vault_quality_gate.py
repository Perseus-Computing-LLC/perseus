import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("gate", Path(__file__).parents[1] / "scripts" / "check_vault_quality_scorecard.py")
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)


def test_ready_scorecard_is_accepted():
    scorecard = {"scorecard_version": gate.EXPECTED, "verdict": "release_ready", "blocking": True, "accuracy": 1.0, "failed_categories": [], "missing_categories": []}
    assert gate.validate(scorecard) == []


def test_regressed_scorecard_is_blocked_with_clear_reasons():
    errors = gate.validate({"scorecard_version": gate.EXPECTED, "verdict": "blocked", "blocking": True, "accuracy": 0.75, "failed_categories": ["adversarial"], "missing_categories": ["shared"]})
    assert "Vault quality verdict is not release_ready" in errors
    assert "accuracy below 1.0" in errors
    assert "failed_categories present" in errors
    assert "missing_categories present" in errors


def test_unknown_contract_version_is_blocked():
    assert "unsupported scorecard_version" in gate.validate({"scorecard_version": "v0"})
