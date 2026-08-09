"""#864 — checkpoint capture is a durability barrier before narrative compaction."""
import pytest

from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires Python 3.10+ build artifact")


def test_compaction_flushes_capture_before_narrative_rebuild(monkeypatch, tmp_path):
    order = []
    monkeypatch.setattr(perseus, "capture_checkpoints_to_vault", lambda *a, **k: (order.append("capture") or (1, 1, "")))
    monkeypatch.setattr(perseus, "_list_checkpoint_files", lambda cfg: [])
    monkeypatch.setattr(perseus, "_read_all_guide_entries", lambda: [])
    monkeypatch.setattr(perseus, "_vault_path", lambda ws, cfg: tmp_path / "memory.md")
    monkeypatch.setattr(perseus, "_load_narrative", lambda path: ({}, ""))
    monkeypatch.setattr(perseus, "_vault_default_frontmatter", lambda ws: {})
    monkeypatch.setattr(perseus, "_deterministic_narrative", lambda *a: (order.append("compact") or "body"))
    monkeypatch.setattr(perseus, "_enrich_narrative_frontmatter", lambda *a: None)
    monkeypatch.setattr(perseus, "_save_narrative", lambda *a: None)

    perseus._memory_do_compact(tmp_path, {"perseus_vault": {"capture": {"enabled": True}}}, None)
    assert order == ["capture", "compact"]


def test_compaction_continues_when_capture_has_zero_entities(monkeypatch, tmp_path):
    monkeypatch.setattr(perseus, "capture_checkpoints_to_vault", lambda *a, **k: (0, 0, ""))
    monkeypatch.setattr(perseus, "_list_checkpoint_files", lambda cfg: [])
    monkeypatch.setattr(perseus, "_read_all_guide_entries", lambda: [])
    monkeypatch.setattr(perseus, "_vault_path", lambda ws, cfg: tmp_path / "memory.md")
    monkeypatch.setattr(perseus, "_load_narrative", lambda path: ({}, ""))
    monkeypatch.setattr(perseus, "_vault_default_frontmatter", lambda ws: {})
    monkeypatch.setattr(perseus, "_deterministic_narrative", lambda *a: "body")
    monkeypatch.setattr(perseus, "_enrich_narrative_frontmatter", lambda *a: None)
    monkeypatch.setattr(perseus, "_save_narrative", lambda *a: None)

    result = perseus._memory_do_compact(tmp_path, {"perseus_vault": {"capture": {"enabled": True}}}, None)
    assert result.startswith("Compacted")
