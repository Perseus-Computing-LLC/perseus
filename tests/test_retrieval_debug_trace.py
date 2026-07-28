"""#866 — stable retrieval debug trace vocabulary."""
import pytest
from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def test_trace_reports_structured_truth_tier_and_descent_order():
    trace = perseus.build_retrieval_debug_trace("What is the current release version?")
    assert trace["answering_tier"] == "structured_truth"
    assert trace["descent_order"] == ["targeted_fetch", "broad_search", "synthesis"]
    assert trace["synthesis_only_after_lower_tier_miss"] is True
    assert trace["precedence_override"] == "none"


def test_trace_reports_broad_search_and_synthesis_descent_reason():
    trace = perseus.build_retrieval_debug_trace("Compare the migration approaches")
    assert trace["answering_tier"] == "broad_search"
    assert trace["descent_order"] == ["synthesis"]
    assert "comparison" in trace["tier_reason"]


def test_trace_renders_as_opt_in_html_comment():
    rendered = perseus.render_retrieval_debug_trace("Find the deployment decision")
    assert rendered.startswith("<!-- retrieval-trace:")
    assert "targeted_fetch" in rendered
    assert "precedence_override=none" in rendered
