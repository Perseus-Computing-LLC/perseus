"""#862 — deterministic retrieval-policy selection and fallback order."""
import pytest

from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def test_retrieval_policy_routes_factual_question_to_structured_truth_first():
    policy = perseus.select_retrieval_policy("What is the current release version?")
    assert policy["start"] == "structured_truth"
    assert policy["fallbacks"] == ["targeted_fetch", "broad_search", "synthesis"]


def test_retrieval_policy_routes_specific_task_to_targeted_fetch_before_search():
    policy = perseus.select_retrieval_policy("Find the decision for the Vault release pipeline")
    assert policy["start"] == "targeted_fetch"
    assert policy["fallbacks"] == ["broad_search", "synthesis"]


def test_retrieval_policy_only_selects_synthesis_after_lower_tiers_miss():
    policy = perseus.select_retrieval_policy("Compare the competing migration approaches and recommend one")
    assert policy["start"] == "broad_search"
    assert policy["fallbacks"] == ["synthesis"]
    assert policy["synthesis_requires_lower_tier_miss"] is True


def test_retrieval_policy_defaults_to_targeted_fetch_for_unclassified_work():
    policy = perseus.select_retrieval_policy("Investigate the deployment incident")
    assert policy["start"] == "targeted_fetch"
    assert policy["fallbacks"] == ["broad_search", "synthesis"]
