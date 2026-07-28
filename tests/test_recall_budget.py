"""#863 — selective served-memory recall budget controller."""
import pytest

from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def _hit(identifier, content, relevance):
    return perseus.MemoryHit(id=identifier, content=content, summary=content, relevance=relevance)


def test_recall_budget_prefers_high_signal_items_and_reports_trimmed_ids():
    selected, diagnostics = perseus.apply_recall_budget(
        [_hit("a", "short high signal", 0.9), _hit("b", "x" * 100, 0.2)],
        max_chars=40,
    )
    assert [item.id for item in selected] == ["a"]
    assert diagnostics["included_ids"] == ["a"]
    assert diagnostics["trimmed_ids"] == ["b"]
    assert diagnostics["budget_exhausted"] is True


def test_recall_budget_large_budget_keeps_all_items_without_demotion():
    items = [_hit("a", "short", 0.9), _hit("b", "also short", 0.2)]
    selected, diagnostics = perseus.apply_recall_budget(items, max_chars=1000)
    assert [item.id for item in selected] == ["a", "b"]
    assert diagnostics["trimmed_ids"] == []
    assert diagnostics["budget_exhausted"] is False


def test_recall_budget_keeps_concise_explanation_when_raw_content_exceeds_budget():
    selected, diagnostics = perseus.apply_recall_budget(
        [_hit("a", "x" * 500, 0.9)], max_chars=80
    )
    assert [item.id for item in selected] == ["a"]
    assert diagnostics["demoted_to_explanation_ids"] == ["a"]
    assert len(selected[0].content) < 80
