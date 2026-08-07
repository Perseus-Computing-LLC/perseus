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


def test_nan_and_overrange_accuracy_are_blocked():
    for accuracy in (float("nan"), 1.1, -0.1):
        errors = gate.validate({"scorecard_version": "perseus-vault-memory-quality-scorecard/v2", "verdict": "release_ready", "blocking": True, "accuracy": accuracy, "failed_categories": [], "missing_categories": []})
        assert errors


def test_malformed_evidence_lists_are_blocked():
    errors = gate.validate({"scorecard_version": "perseus-vault-memory-quality-scorecard/v2", "verdict": "release_ready", "blocking": True, "accuracy": 1.0, "failed_categories": "", "missing_categories": [], "invalid_cases": ["bad"]})
    assert errors


def test_malformed_json_and_overflow_are_blocked(tmp_path):
    assert gate.validate({"scorecard_version": gate.EXPECTED, "verdict": "release_ready", "blocking": True, "accuracy": 10 ** 10000, "failed_categories": [], "missing_categories": []})
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    import subprocess, sys
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "scripts" / "check_vault_quality_scorecard.py"), str(malformed)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "BLOCKED" in result.stdout
