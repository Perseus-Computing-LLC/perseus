"""
Tests for the bastra-recall persistent memory integration.

Covers:
  - _bastra_recall() HTTP client (success, timeout/failure, bad JSON)
  - resolve_bastra() directive (missing query, results, no hits)
  - resolve_memory() backend routing (file vs bastra)
"""

import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bastra_cfg(url: str = "http://127.0.0.1:6723") -> dict:
    """Minimal config with bastra backend enabled."""
    c = cfg()
    c["memory"]["backend"] = "bastra"
    c["memory"]["bastra_url"] = url
    return c


def _file_cfg() -> dict:
    """Minimal config with the default file backend."""
    c = cfg()
    c["memory"]["backend"] = "file"
    return c


def _mock_response(hits: list) -> MagicMock:
    """Return a mock urllib response that yields JSON with the given hits."""
    payload = json.dumps({"hits": hits}).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = payload
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# _bastra_recall() — HTTP client
# ---------------------------------------------------------------------------

class TestBastraRecall:
    def test_returns_hits_on_success(self, monkeypatch):
        hits = [{"title": "Decision A", "summary": "Use postgres", "score": 92, "type": "decision"}]
        mock_resp = _mock_response(hits)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = perseus._bastra_recall(_bastra_cfg(), query="database choice", k=5)

        assert result == hits

    def test_returns_empty_list_on_timeout(self, monkeypatch):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            result = perseus._bastra_recall(_bastra_cfg(), query="anything", k=5)
        assert result == []

    def test_returns_empty_list_on_connection_error(self):
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            result = perseus._bastra_recall(_bastra_cfg(), query="anything", k=5)
        assert result == []

    def test_returns_empty_list_on_bad_json(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not-json{{{"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = perseus._bastra_recall(_bastra_cfg(), query="anything", k=5)
        assert result == []

    def test_passes_scope_and_type_in_payload(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _mock_response([])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            perseus._bastra_recall(
                _bastra_cfg(), query="auth bug", k=3, scope="perseus", type_filter="lesson"
            )

        assert captured["body"]["query"] == "auth bug"
        assert captured["body"]["k"] == 3
        assert captured["body"]["scope"] == "perseus"
        assert captured["body"]["type"] == "lesson"

    def test_omits_optional_fields_when_none(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode())
            return _mock_response([])

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            perseus._bastra_recall(_bastra_cfg(), query="test", k=5)

        assert "scope" not in captured["body"]
        assert "type" not in captured["body"]

    def test_uses_bastra_url_from_cfg(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _mock_response([])

        custom_cfg = _bastra_cfg(url="http://192.168.1.50:9000")
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            perseus._bastra_recall(custom_cfg, query="test", k=1)

        assert "192.168.1.50:9000" in captured["url"]

    def test_missing_hits_key_returns_empty(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"results": []}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = perseus._bastra_recall(_bastra_cfg(), query="test", k=5)
        assert result == []


# ---------------------------------------------------------------------------
# resolve_bastra() — @bastra directive
# ---------------------------------------------------------------------------

class TestResolveBastra:
    def test_missing_query_returns_warning(self):
        result = perseus.resolve_bastra("", cfg())
        assert "@bastra requires" in result
        assert "query=" in result

    def test_no_hits_returns_info_message(self):
        with patch.object(perseus, "_bastra_recall", return_value=[]):
            result = perseus.resolve_bastra('query="test search"', cfg())
        assert "No bastra-recall memories matched" in result

    def test_hits_rendered_as_list(self):
        hits = [
            {"title": "Use Redis", "summary": "Cache sessions in Redis.", "score": 88, "type": "decision"},
            {"title": "Auth lesson", "summary": "JWT tokens expire in 1h.", "score": 75, "type": "lesson"},
        ]
        with patch.object(perseus, "_bastra_recall", return_value=hits):
            result = perseus.resolve_bastra('query="caching"', cfg())

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

        with patch.object(perseus, "_bastra_recall", side_effect=fake_recall):
            perseus.resolve_bastra('query="x" k=50', cfg())
        assert captured["k"] == 20

        with patch.object(perseus, "_bastra_recall", side_effect=fake_recall):
            perseus.resolve_bastra('query="x" k=0', cfg())
        assert captured["k"] == 1

    def test_scope_and_type_forwarded(self):
        captured = {}

        def fake_recall(cfg_, query, k=5, scope=None, type_filter=None):
            captured["scope"] = scope
            captured["type_filter"] = type_filter
            return []

        with patch.object(perseus, "_bastra_recall", side_effect=fake_recall):
            perseus.resolve_bastra('query="x" scope="myproject" type="lesson"', cfg())

        assert captured["scope"] == "myproject"
        assert captured["type_filter"] == "lesson"

    def test_score_rendered_when_present(self):
        hits = [{"title": "T", "summary": "S", "score": 99}]
        with patch.object(perseus, "_bastra_recall", return_value=hits):
            result = perseus.resolve_bastra('query="x"', cfg())
        assert "99" in result

    def test_optional_fields_absent_does_not_crash(self):
        hits = [{"title": "MinimalHit"}]
        with patch.object(perseus, "_bastra_recall", return_value=hits):
            result = perseus.resolve_bastra('query="x"', cfg())
        assert "MinimalHit" in result


# ---------------------------------------------------------------------------
# resolve_memory() — backend routing
# ---------------------------------------------------------------------------

class TestResolveMemoryBackendRouting:
    def test_file_backend_does_not_call_bastra(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".perseus").mkdir()
        called = []

        def fake_bastra(*a, **kw):
            called.append(True)
            return []

        with patch.object(perseus, "_bastra_recall", side_effect=fake_bastra):
            # file backend — bastra should never be called
            result = perseus.resolve_memory("", _file_cfg(), workspace=tmp_path)

        assert not called, "_bastra_recall should not be called with file backend"

    def test_bastra_backend_calls_bastra(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        called = []

        def fake_bastra(cfg_, query, k=5, scope=None, type_filter=None):
            called.append({"query": query, "scope": scope})
            return []

        with patch.object(perseus, "_bastra_recall", side_effect=fake_bastra):
            result = perseus.resolve_memory("", _bastra_cfg(), workspace=tmp_path)

        assert called, "_bastra_recall should be called with bastra backend"
        assert "No bastra-recall memories found" in result

    def test_bastra_backend_renders_hits(self, tmp_path):
        hits = [{"title": "Arch decision", "summary": "Chose monorepo.", "score": 80, "type": "decision"}]

        with patch.object(perseus, "_bastra_recall", return_value=hits):
            result = perseus.resolve_memory("", _bastra_cfg(), workspace=tmp_path)

        assert "Arch decision" in result
        assert "Chose monorepo" in result

    def test_bastra_backend_focus_decisions_uses_type_filter(self, tmp_path):
        captured = {}

        def fake_bastra(cfg_, query, k=8, scope=None, type_filter=None):
            captured["type_filter"] = type_filter
            return []

        with patch.object(perseus, "_bastra_recall", side_effect=fake_bastra):
            perseus.resolve_memory("focus=decisions", _bastra_cfg(), workspace=tmp_path)

        assert captured.get("type_filter") == "decision"

    def test_bastra_backend_focus_patterns_uses_lesson_type(self, tmp_path):
        captured = {}

        def fake_bastra(cfg_, query, k=8, scope=None, type_filter=None):
            captured["type_filter"] = type_filter
            return []

        with patch.object(perseus, "_bastra_recall", side_effect=fake_bastra):
            perseus.resolve_memory("focus=patterns", _bastra_cfg(), workspace=tmp_path)

        assert captured.get("type_filter") == "lesson"
