import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

_GENERATED = Path(__file__).resolve().parents[1] / "perseus.py"
_SPEC = importlib.util.spec_from_file_location("perseus_generated_status", _GENERATED)
assert _SPEC and _SPEC.loader
_PERSEUS = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PERSEUS
_SPEC.loader.exec_module(_PERSEUS)

_mtr_reset_for_tests = _PERSEUS._mtr_reset_for_tests
_mtr_status_accepted = _PERSEUS._mtr_status_accepted
_mtr_status_attempt = _PERSEUS._mtr_status_attempt
_mtr_status_dropped = _PERSEUS._mtr_status_dropped
metering_status = _PERSEUS.metering_status


class MeteringStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PERSEUS_METERING_STATUS_PATH"] = str(Path(self.tmp.name) / "metering.json")
        _mtr_reset_for_tests()

    def tearDown(self):
        _mtr_reset_for_tests()
        os.environ.pop("PERSEUS_METERING_STATUS_PATH", None)
        self.tmp.cleanup()

    def test_status_persists_redacted_counters_and_coverage(self):
        cfg = {"enabled": True, "endpoint": "http://plutus"}
        _mtr_status_attempt(cfg)
        _mtr_status_accepted(cfg, has_baseline=True)
        _mtr_status_attempt(cfg)
        _mtr_status_accepted(cfg, has_baseline=False)
        _mtr_status_dropped(cfg, "timeout")

        status = metering_status({"plutus": cfg})
        self.assertEqual(status["attempts"], 2)
        self.assertEqual(status["accepted_events"], 2)
        self.assertEqual(status["accepted_with_baseline"], 1)
        self.assertEqual(status["dropped_events"], 1)
        self.assertEqual(status["dropped_by_reason"], {"timeout": 1})
        self.assertEqual(status["coverage_pct"], 50.0)
        self.assertTrue(status["degraded"])
        self.assertNotIn("api_key", str(status).lower())

        _mtr_reset_for_tests()
        restored = metering_status({"plutus": cfg})
        self.assertEqual(restored["accepted_events"], 2)
        self.assertEqual(restored["coverage_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
