"""#695 — /knows serve endpoint + 'What Perseus knows about you' index panel.

Reuses the #692 renderer verbatim; runs through the existing redact + bearer
auth path; index stats use ACTIVE-only Vault counts (perseus-vault #493) and
degrade to "—" (None) when the vault is unreachable or predates the split.
"""
import json
import time

import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

NOW_MS = int(time.time() * 1000)


class _FakeConnector:
    def __init__(self, hits=None, stats=None, error=""):
        self._hits = hits if hits is not None else []
        self._stats = stats
        self._error = error

    def browse(self, limit=500, include_archived=False):
        if self._error:
            return [], self._error
        return self._hits, ""

    def stats(self):
        return self._stats


def _hits():
    return perseus._parse_memory_hits({"items": [{
        "id": "mem-aa0000000001", "category": "user", "key": "name",
        "type": "insight", "body_json": json.dumps({"text": "You are Thomas"}),
        "decay_score": 1.0, "layer": "working", "verified": True,
        "created_at_unix_ms": NOW_MS, "last_accessed_unix_ms": NOW_MS,
    }]})


def _install(monkeypatch, connector):
    monkeypatch.setattr(perseus, "_get_connector", lambda _cfg: connector)


# ── /knows endpoint ───────────────────────────────────────────────────────────

def test_knows_endpoint_renders_markdown(tmp_path, monkeypatch):
    _install(monkeypatch, _FakeConnector(
        _hits(), {"active_entities": 1, "archived_entities": 2}))
    status, ctype, body = perseus._serve_render_endpoint("/knows", cfg(), tmp_path, {})
    assert status == 200
    assert "text/markdown" in ctype
    assert "Perseus knows 1 things" in body
    assert "(2 archived — hidden)" in body
    assert "About you" in body


def test_knows_endpoint_json_format(tmp_path, monkeypatch):
    _install(monkeypatch, _FakeConnector(_hits()))
    status, ctype, body = perseus._serve_render_endpoint(
        "/knows", cfg(), tmp_path, {"format": "json"})
    assert status == 200
    assert "application/json" in ctype
    data = json.loads(body)
    assert data["listed"] == 1
    assert data["bucket_order"][0] == "About you"


def test_knows_endpoint_unreachable_vault_is_503(tmp_path, monkeypatch):
    _install(monkeypatch, _FakeConnector(error="spawn failed"))
    status, _, body = perseus._serve_render_endpoint("/knows", cfg(), tmp_path, {})
    assert status == 503
    assert "unreachable" in body
    assert "perseus doctor" in body


def test_knows_endpoint_disabled_is_404(tmp_path, monkeypatch):
    _install(monkeypatch, _FakeConnector(_hits()))
    local = cfg()
    local["knows"] = {"enabled": False}
    status, _, body = perseus._serve_render_endpoint("/knows", local, tmp_path, {})
    assert status == 404
    assert "disabled" in body


def test_knows_endpoint_requires_bearer_auth(tmp_path, monkeypatch):
    """The new endpoint must gate exactly like every other one — no header,
    wrong token → 401; valid token → 200."""
    _install(monkeypatch, _FakeConnector(_hits()))
    local = cfg()
    local["serve"]["auth_token"] = "secret"
    status, _, _ = perseus._serve_handle_request(
        "/knows", local, tmp_path, {}, headers={"Host": "127.0.0.1"})
    assert status == 401
    status, _, body = perseus._serve_handle_request(
        "/knows", local, tmp_path, {},
        headers={"Authorization": "Bearer secret", "Host": "127.0.0.1"})
    assert status == 200
    assert "Perseus knows" in body


def test_knows_endpoint_output_is_redacted(tmp_path, monkeypatch):
    """Serve is the trust boundary — memory content passes redact_text like
    /context and /narrative do."""
    hits = perseus._parse_memory_hits({"items": [{
        "id": "mem-bb0000000001", "category": "user", "key": "token",
        "type": "insight",
        "body_json": json.dumps({"text": "token is ghp_0123456789abcdef0123456789abcdef0123"}),
        "decay_score": 1.0, "layer": "working", "verified": False,
        "created_at_unix_ms": NOW_MS, "last_accessed_unix_ms": NOW_MS,
    }]})
    _install(monkeypatch, _FakeConnector(hits))
    status, _, body = perseus._serve_render_endpoint("/knows", cfg(), tmp_path, {})
    assert status == 200
    assert "ghp_0123456789abcdef0123456789abcdef0123" not in body


# ── index panel + stats ───────────────────────────────────────────────────────

def test_collect_stats_uses_active_only_vault_counts(tmp_path, monkeypatch):
    _install(monkeypatch, _FakeConnector(
        stats={"active_entities": 42, "archived_entities": 7, "total_entities": 49}))
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["pythia"]["skill_dir"] = str(tmp_path / "skills")
    stats = perseus._serve_collect_stats(local, tmp_path)
    assert stats["vault_active"] == 42
    assert stats["vault_archived"] == 7


def test_collect_stats_leaves_dash_for_pre_split_server(tmp_path, monkeypatch):
    # Older vault: only the archived-inflated total_entities — must NOT be used.
    _install(monkeypatch, _FakeConnector(stats={"total_entities": 49}))
    local = cfg()
    local["memory"]["store"] = str(tmp_path / "memory")
    local["checkpoints"]["store"] = str(tmp_path / "cp")
    local["inbox"]["store"] = str(tmp_path / "inbox")
    local["pythia"]["skill_dir"] = str(tmp_path / "skills")
    stats = perseus._serve_collect_stats(local, tmp_path)
    assert stats["vault_active"] is None
    assert stats["vault_archived"] is None


def test_index_registers_knows_card_and_vault_stat(tmp_path):
    html = perseus._serve_render_index(tmp_path, {"vault_active": 42, "vault_archived": 7})
    assert "href='/knows'" in html
    assert "What Perseus knows about you" in html
    assert "Vault memories" in html
    assert ">42<" in html
