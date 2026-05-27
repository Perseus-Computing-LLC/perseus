"""
Tests for Mnēmē — in-process BM25 persistent memory.

Covers:
  - resolve_mneme() directive (missing query, results, no hits)
  - resolve_memory() backend routing (file vs mneme)
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mneme_cfg() -> dict:
    """Minimal config with mneme backend enabled."""
    c = cfg()
    c["memory"]["backend"] = "mneme"
    return c


def _file_cfg() -> dict:
    """Minimal config with the default file backend."""
    c = cfg()
    c["memory"]["backend"] = "file"
    return c


# ---------------------------------------------------------------------------
# resolve_mneme() — @mneme directive
# ---------------------------------------------------------------------------

class TestResolveMneme:
    def test_missing_query_returns_warning(self):
        result = perseus.resolve_mneme("", cfg())
        assert "@memory search requires" in result
        assert "query=" in result

    def test_no_hits_returns_info_message(self):
        with patch.object(perseus, "_mneme_recall", return_value=[]):
            result = perseus.resolve_mneme('query="test search"', cfg())
        assert "No Mnēmē memories matched" in result

    def test_hits_rendered_as_list(self):
        hits = [
            {"title": "Use Redis", "summary": "Cache sessions in Redis.", "score": 88, "type": "decision"},
            {"title": "Auth lesson", "summary": "JWT tokens expire in 1h.", "score": 75, "type": "lesson"},
        ]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mneme('query="caching"', cfg())

        assert "Use Redis" in result
        assert "Cache sessions in Redis" in result
        assert "Auth lesson" in result
        assert "decision" in result
        assert "lesson" in result

    def test_k_clamped_to_1_20(self):
        captured = {}

        def fake_recall(cfg_, query, k=5, scope=None, type_filter=None):
            captured["k"] = k
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mneme('query="x" k=50', cfg())
        assert captured["k"] == 20

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mneme('query="x" k=0', cfg())
        assert captured["k"] == 1

    def test_scope_and_type_forwarded(self):
        captured = {}

        def fake_recall(cfg_, query, k=5, scope=None, type_filter=None):
            captured["scope"] = scope
            captured["type_filter"] = type_filter
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mneme('query="x" scope="myproject" type="lesson"', cfg())

        assert captured["scope"] == "myproject"
        assert captured["type_filter"] == "lesson"

    def test_score_rendered_when_present(self):
        hits = [{"title": "T", "summary": "S", "score": 99}]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mneme('query="x"', cfg())
        assert "99" in result

    def test_optional_fields_absent_does_not_crash(self):
        hits = [{"title": "MinimalHit"}]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mneme('query="x"', cfg())
        assert "MinimalHit" in result


# ---------------------------------------------------------------------------
# resolve_memory() — unified mode dispatch (Mnēmē v2)
# ---------------------------------------------------------------------------

class TestResolveMemoryUnified:
    def test_no_query_uses_narrative_mode(self, tmp_path, monkeypatch):
        """Plain @memory with no query → narrative mode, does not call _mneme_recall."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".perseus").mkdir()
        called = []

        def fake_mneme(*a, **kw):
            called.append(True)
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            result = perseus.resolve_memory("", cfg(), workspace=tmp_path)

        assert not called, "_mneme_recall should not be called for narrative mode"

    def test_query_triggers_search_mode(self, tmp_path):
        """@memory query=... → search mode, calls _mneme_recall."""
        called = []

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None):
            called.append({"query": query, "scope": scope})
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            result = perseus.resolve_memory('query="test"', cfg(), workspace=tmp_path)

        assert called, "_mneme_recall should be called for search mode"
        assert "No Mnēmē memories matched" in result

    def test_search_renders_hits(self, tmp_path):
        hits = [{"title": "Arch decision", "summary": "Chose monorepo.", "score": 80, "type": "decision"}]

        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_memory('query="arch"', cfg(), workspace=tmp_path)

        assert "Arch decision" in result
        assert "Chose monorepo" in result

    def test_search_forwards_type_filter(self, tmp_path):
        captured = {}

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None):
            captured["type_filter"] = type_filter
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            perseus.resolve_memory('query="x" type="decision"', cfg(), workspace=tmp_path)

        assert captured.get("type_filter") == "decision"

    def test_search_forwards_scope(self, tmp_path):
        captured = {}

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None):
            captured["scope"] = scope
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            perseus.resolve_memory('query="x" scope="myproject"', cfg(), workspace=tmp_path)

        assert captured.get("scope") == "myproject"

    def test_explicit_mode_search(self, tmp_path):
        called = []

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None):
            called.append(True)
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            perseus.resolve_memory('mode=search query="x"', cfg(), workspace=tmp_path)

        assert called
