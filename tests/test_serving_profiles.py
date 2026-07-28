"""#867 — serving profiles partition personal, agent, and workspace knowledge."""
import pytest
from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def _hit(identifier, category, workspace="", tags=None):
    return perseus.MemoryHit(id=identifier, category=category, content=identifier, summary=identifier, workspace_hash=workspace, tags=tags or {})


def test_personal_profile_serves_preferences_only():
    items = [_hit("pref", "preference"), _hit("conv", "convention"), _hit("shared", "insight", "ws")]
    selected, trace = perseus.apply_serving_profile(items, "personal", "ws")
    assert [item.id for item in selected] == ["pref"]
    assert trace["excluded_ids"] == ["conv", "shared"]


def test_agent_profile_serves_conventions_and_corrections_not_personal_preferences():
    items = [_hit("pref", "preference"), _hit("conv", "convention"), _hit("fix", "correction"), _hit("shared", "insight", "ws")]
    selected, _ = perseus.apply_serving_profile(items, "agent", "ws")
    assert [item.id for item in selected] == ["conv", "fix"]


def test_shared_profile_serves_workspace_knowledge_not_other_workspace_or_personal():
    items = [_hit("pref", "preference"), _hit("local", "insight", "ws"), _hit("other", "insight", "other")]
    selected, trace = perseus.apply_serving_profile(items, "shared", "ws")
    assert [item.id for item in selected] == ["local"]
    assert trace["profile"] == "shared"


def test_unknown_profile_is_rejected_clearly():
    with pytest.raises(ValueError, match="unknown serving profile"):
        perseus.apply_serving_profile([], "mystery", "ws")
