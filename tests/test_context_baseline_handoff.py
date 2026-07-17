import sys
import unittest
from pathlib import Path

# The repository root contains the generated `perseus.py` launcher. Put the
# source package first so this test exercises src/perseus on every platform.
_SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SOURCE))
sys.modules.pop("perseus", None)

from perseus.metering import (
    consume_context_baseline,
    publish_context_baseline,
)


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
