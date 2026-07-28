"""#865 — derived knowledge sections in served-memory rendering."""
import pytest

from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def _hit(identifier, category, content, refs=None):
    return perseus.MemoryHit(
        id=identifier, category=category, content=content, summary=content,
        external_refs=refs or [],
    )


def test_derived_surface_renders_conventions_corrections_and_scoped_rules():
    segment = perseus.MemorySegment(items=[
        _hit("mem-convention", "convention", "Use migrations for schema changes."),
        _hit("mem-correction", "correction", "Do not expose private evidence."),
        _hit("mem-rule", "keystone", "Every release requires a quality gate.", [{"ref_value": "github:org/repo#42"}]),
    ])
    rendered = segment.as_markdown
    assert "### Conventions" in rendered
    assert "### Corrections" in rendered
    assert "### Scoped Operating Rules" in rendered
    assert "Use migrations" in rendered
    assert "Do not expose" in rendered
    assert "github:org/repo#42" in rendered


def test_derived_surface_keeps_unclassified_memories_in_normal_sections():
    segment = perseus.MemorySegment(items=[_hit("mem-insight", "insight", "A normal insight.")])
    rendered = segment.as_markdown
    assert "### Insights" in rendered
    assert "### Conventions" not in rendered
    assert "### Corrections" not in rendered
    assert "### Scoped Operating Rules" not in rendered
