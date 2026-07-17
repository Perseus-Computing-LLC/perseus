import importlib.util
import sys
import unittest
from pathlib import Path

# CI exercises the generated monolith, which is the artifact shipped to
# end-users. Load it explicitly so the repository-root launcher and src/
# package cannot shadow one another during collection.
_GENERATED = Path(__file__).resolve().parents[1] / "perseus.py"
_SPEC = importlib.util.spec_from_file_location("perseus_generated", _GENERATED)
assert _SPEC and _SPEC.loader
_PERSEUS = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PERSEUS
_SPEC.loader.exec_module(_PERSEUS)

publish_context_baseline = _PERSEUS.publish_context_baseline
consume_context_baseline = _PERSEUS.consume_context_baseline


class ContextBaselineHandoffTests(unittest.TestCase):
    def tearDown(self):
        consume_context_baseline()

    def test_publish_then_consume_returns_baseline_once(self):
        publish_context_baseline(
            actual_input_tokens=120,
            baseline_input_tokens=300,
            source="estimate-exact",
        )

        self.assertEqual(
            consume_context_baseline(),
            {
                "actual_input_tokens": 120,
                "baseline_input_tokens": 300,
                "source": "estimate-exact",
            },
        )
        self.assertIsNone(consume_context_baseline())

    def test_stale_baseline_is_not_reused(self):
        publish_context_baseline(
            actual_input_tokens=120,
            baseline_input_tokens=300,
            source="estimate-exact",
        )
        self.assertIsNotNone(consume_context_baseline())
        self.assertIsNone(consume_context_baseline())


if __name__ == "__main__":
    unittest.main()
