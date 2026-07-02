"""
Tests for the #552 grab-bag fixes:

1. memory_mesh._memorymesh_rest_health — self-contained urllib import.
2. mneme_federation._fetch_remote_narrative — read_timeout_s applied +
   max_fetch_bytes size cap on remote narrative fetches.
3. mneme_connector — bm25 score normalized to 0.0-1.0 relevance (was
   divided by 100 as if a percentage, producing small negative values).
"""

import ast
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

_SRC = Path(__file__).resolve().parents[1] / "src" / "perseus"


# ---------------------------------------------------------------------------
# 1. memory_mesh: _memorymesh_rest_health must not rely on concat ordering
# ---------------------------------------------------------------------------

def test_memorymesh_rest_health_imports_urllib_locally():
    """The src module's own scope must provide urllib — not another module's
    top-level import that happens to precede it in the built artifact."""
    src_text = (_SRC / "memory_mesh.py").read_text(encoding="utf-8")
    tree = ast.parse(src_text)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_memorymesh_rest_health")
    imported = {alias.name for node in ast.walk(fn)
                if isinstance(node, ast.Import) for alias in node.names}
    assert "urllib.request" in imported, (
        "_memorymesh_rest_health lost its local urllib.request import — "
        "it would NameError (silently swallowed) if build order changes"
    )


def test_memorymesh_rest_health_false_on_connection_error(monkeypatch):
    def _boom(*a, **kw):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert perseus._memorymesh_rest_health() is False


def test_memorymesh_rest_health_true_on_200(monkeypatch):
    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _Resp())
    assert perseus._memorymesh_rest_health() is True


# ---------------------------------------------------------------------------
# 2. mneme_federation: read timeout + size cap on remote narrative fetch
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload: bytes, status: int = 200):
        self._data = payload
        self._pos = 0
        self.status = status

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fed_entry():
    return {"alias": "peer", "remote": {"url": "http://peer.example"},
            "_workspace_hash": ""}


def test_federation_fetch_normal_body_under_cap(monkeypatch):
    payload = json.dumps({"narrative": "## Arc\nhello", "workspace_id": "w1"}).encode()
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **kw: _FakeResp(payload))
    c = cfg()
    body, err, ws = perseus._fetch_remote_narrative(_fed_entry(), c)
    assert err is None
    assert body == "## Arc\nhello"
    assert ws == "w1"


def test_federation_fetch_rejects_oversized_body(monkeypatch):
    huge = json.dumps({"narrative": "x" * 5000}).encode()
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **kw: _FakeResp(huge))
    c = cfg()
    c["federation"] = {"max_fetch_bytes": 1000}
    body, err, ws = perseus._fetch_remote_narrative(_fed_entry(), c)
    assert body is None
    assert "max_fetch_bytes" in err
    assert "1000" in err


def test_federation_fetch_applies_read_timeout(monkeypatch):
    """read_timeout_s was parsed but never applied — a peer that streams
    forever must now be cut off at the configured wall-clock deadline."""
    payload = json.dumps({"narrative": "slow"}).encode()
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **kw: _FakeResp(payload))
    # First monotonic() call sets the deadline; the next one is already
    # past it — simulating a read phase that exceeded read_timeout_s.
    seq = iter([0.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(seq, 1e9))
    c = cfg()
    c["federation"] = {"read_timeout_s": 5}
    body, err, ws = perseus._fetch_remote_narrative(_fed_entry(), c)
    assert body is None
    assert "timed out" in err
    assert "5" in err


# ---------------------------------------------------------------------------
# 3. mneme_connector: bm25 → relevance normalization
# ---------------------------------------------------------------------------

def test_bm25_to_relevance_range_and_monotonicity():
    # bm25 is 0.0 or negative; more negative = better match.
    assert perseus._bm25_to_relevance(0.0) == 0.0
    assert perseus._bm25_to_relevance(-1.0) == pytest.approx(0.5)
    strong = perseus._bm25_to_relevance(-20.0)
    weak = perseus._bm25_to_relevance(-0.5)
    assert 0.0 <= weak < strong < 1.0
    # Missing / malformed → neutral; positive (not produced by bm25) clamps.
    assert perseus._bm25_to_relevance(None) == 0.5
    assert perseus._bm25_to_relevance("nan-ish") == 0.5
    assert perseus._bm25_to_relevance(3.7) == 0.0


def test_local_hits_relevance_normalized():
    """A raw negative bm25 score must yield a 0-1 relevance, never negative
    (the old code did score/100 → e.g. -8.5 became -0.085)."""
    hits = perseus._local_hits_to_memory_hits([
        {"id": "a", "content": "strong match", "score": -8.5},
        {"id": "b", "content": "weak match", "score": -0.2},
    ])
    assert len(hits) == 2
    by_id = {h.id: h for h in hits}
    for h in hits:
        assert 0.0 <= h.relevance <= 1.0, f"relevance out of range: {h.relevance}"
    assert by_id["a"].relevance > by_id["b"].relevance


def test_local_hits_explicit_relevance_wins():
    hits = perseus._local_hits_to_memory_hits([
        {"id": "a", "content": "x", "relevance": 0.9, "score": -1.0},
    ])
    assert hits[0].relevance == 0.9
