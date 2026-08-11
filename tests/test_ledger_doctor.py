import importlib.util
import sys
from pathlib import Path

_GENERATED = Path(__file__).resolve().parents[1] / "perseus.py"
_SPEC = importlib.util.spec_from_file_location("perseus_generated_doctor", _GENERATED)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


def test_ledger_doctor_disabled_is_ok(tmp_path):
    result = _MOD._doctor_check_ledger_metering({}, tmp_path)
    assert result.status == "ok"
    assert result.value == "disabled"


def test_ledger_doctor_missing_target_is_error(tmp_path):
    result = _MOD._doctor_check_ledger_metering({"ledger": {"enabled": True}}, tmp_path)
    assert result.status == "error"
    assert "no endpoint" in result.value
