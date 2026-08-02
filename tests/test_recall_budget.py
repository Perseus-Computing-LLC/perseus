"""#863 — selective served-memory recall budget controller."""
import pytest

from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def _hit(identifier, content, relevance):
    return perseus.MemoryHit(id=identifier, content=content, summary=content, relevance=relevance)


def _metadata_hit(identifier, content, relevance, *, category="", key="", refs=None, why_served=None):
    return perseus.MemoryHit(
        id=identifier,
        content=content,
        summary=content,
        relevance=relevance,
        category=category,
        key=key,
        external_refs=refs or [],
        why_served=why_served or {},
    )


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


def test_recall_budget_prioritizes_load_bearing_memory_over_relevance():
    ordinary = _metadata_hit("ordinary", "ordinary context", 0.99)
    correction = _metadata_hit(
        "correction",
        "Never expose private evidence.",
        0.01,
        category="correction",
    )

    selected, diagnostics = perseus.apply_recall_budget(
        [ordinary, correction], max_chars=len(correction.content)
    )

    assert [item.id for item in selected] == ["correction"]
    assert diagnostics["load_bearing_ids"] == ["correction"]
    assert diagnostics["trimmed_ids"] == ["ordinary"]


def test_recall_budget_keeps_relevance_order_when_everything_fits():
    ordinary = _metadata_hit("ordinary", "ordinary context", 0.99)
    correction = _metadata_hit(
        "correction",
        "Never expose private evidence.",
        0.01,
        category="correction",
    )

    selected, diagnostics = perseus.apply_recall_budget(
        [ordinary, correction], max_chars=1000
    )

    assert [item.id for item in selected] == ["ordinary", "correction"]
    assert diagnostics["budget_exhausted"] is False


def test_recall_budget_preserves_decoder_reference_and_does_not_mutate_source_hit():
    raw_content = "Private evidence must remain inside the authorized workspace. " * 20
    hit = _metadata_hit(
        "mem-long",
        raw_content,
        0.9,
        category="keystone",
        key="private-evidence-boundary",
        refs=[{"ref_type": "repo", "ref_value": "github:Org/private"}],
        why_served={"source_evidence_ids": ["mem-source"]},
    )

    selected, diagnostics = perseus.apply_recall_budget([hit], max_chars=80)

    assert hit.content == raw_content
    assert diagnostics["demoted_to_explanation_ids"] == ["mem-long"]
    assert diagnostics["decoder_refs"] == [{
        "id": "mem-long",
        "category": "keystone",
        "key": "private-evidence-boundary",
        "external_refs": [{"ref_type": "repo", "ref_value": "github:Org/private"}],
        "source_evidence_ids": ["mem-source"],
    }]
    assert raw_content not in str(diagnostics["decoder_refs"])
    assert len(selected[0].content) < 80


def test_recall_budget_diagnostic_exposes_decoder_ids():
    rendered = perseus._recall_budget_diagnostic({
        "budget_exhausted": True,
        "included_ids": ["mem-a"],
        "trimmed_ids": ["mem-b"],
        "demoted_to_explanation_ids": [],
        "decoder_refs": [{"id": "mem-b"}],
        "load_bearing_ids": [],
    })

    assert "decoder_ids=mem-b" in rendered
