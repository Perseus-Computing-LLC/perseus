"""#692 — `perseus knows`: plain-language memory review + curation.

Covers the connector browse/curation wrappers, bucketing, both renderers,
git-style short-id resolution, and the confirm-before-write curation flows.
"""
import argparse
import json
import time

import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

NOW_MS = int(time.time() * 1000)
DAY_MS = 86400 * 1000


class _StubClient:
    is_connected = True

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.responses.get(name, ({}, None))

    def close(self):
        pass


def _raw(id_suffix, category, key, *, decay=1.0, age_days=0, verified=False,
         body="a fact", type_="insight"):
    return {
        "id": f"mem-{id_suffix}",
        "category": category,
        "key": key,
        "type": type_,
        "body_json": json.dumps({"text": body}),
        "decay_score": decay,
        "layer": "working",
        "verified": verified,
        "created_at_unix_ms": NOW_MS - age_days * DAY_MS,
        "last_accessed_unix_ms": NOW_MS,
    }


def _connector(responses):
    c = perseus.MnemeConnector(cfg())
    c._client = _StubClient(responses)
    return c


def _ns(**kw):
    base = dict(json=False, show=None, forget=None, correct=None, value=None,
                include_archived=False, limit=None, yes=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _knows_cfg(connector, monkeypatch):
    monkeypatch.setattr(perseus, "MnemeConnector", lambda _cfg: connector)
    return cfg()


# ── connector wrappers ────────────────────────────────────────────────────────

def test_browse_sends_canonical_args_and_omits_workspace_hash():
    c = _connector({"mimir_recall": ({"items": [_raw("aa11bb22cc33", "user", "k")]}, None)})
    hits, err = c.browse(limit=25)
    assert err == ""
    name, sent = c._client.calls[0]
    assert name == "mimir_recall"
    assert sent == {"query": "", "limit": 25}
    # workspace_hash="" would be the Vault's STRICT global scope — must be absent.
    assert "workspace_hash" not in sent
    # #692: category/key now survive parsing (needed for mimir_forget).
    assert hits[0].category == "user"
    assert hits[0].key == "k"


def test_browse_include_archived_flag():
    c = _connector({"mimir_recall": ({"items": []}, None)})
    c.browse(limit=10, include_archived=True)
    _, sent = c._client.calls[0]
    assert sent["include_archived"] is True


def test_forget_addresses_by_category_and_key():
    c = _connector({"mimir_forget": ({"archived": True}, None)})
    ok, err = c.forget("user", "shoe-size", reason="wrong")
    assert ok and err == ""
    assert c._client.calls[0] == ("mimir_forget",
        {"category": "user", "key": "shoe-size", "reason": "wrong"})


def test_correct_records_wrong_right_pair():
    c = _connector({"mimir_correct": ({"id": "mem-x"}, None)})
    ok, _ = c.correct("old wrong value", "right value", task_context="ctx", category="user")
    assert ok
    name, sent = c._client.calls[0]
    assert name == "mimir_correct"
    assert sent["wrong_approach"] == "old wrong value"
    assert sent["user_correction"] == "right value"
    assert sent["task_context"] == "ctx"
    assert sent["category"] == "user"


# ── bucketing + model ─────────────────────────────────────────────────────────

def _sample_hits():
    return perseus._parse_memory_hits({"items": [
        _raw("aa0000000001", "user", "name", verified=True, body="You are Thomas"),
        _raw("bb0000000002", "decision", "db-choice", age_days=30, body="Postgres 16"),
        _raw("cc0000000003", "insight", "fresh", age_days=1, body="learned yesterday"),
        _raw("dd0000000004", "convention", "stale", decay=0.1, age_days=90, body="doubtful"),
        _raw("ee0000000005", "conversation", "sess-old", age_days=60, body="old chat"),
        _raw("ff0000000006", "conversation", "sess-new", age_days=2, body="new chat"),
        _raw("0a0000000007", "some-new-category", "misc", age_days=30, body="fallback"),
    ]})


def test_model_buckets_and_conversational_collapse():
    model = perseus._knows_model(_sample_hits(), None, limit=500)
    buckets = model["buckets"]
    by_key = {b: [i["key"] for i in items] for b, items in buckets.items()}
    assert by_key["About you"] == ["name"]
    assert "db-choice" in by_key["Project facts & decisions"]
    assert "misc" in by_key["Project facts & decisions"]      # unknown → fallback
    assert "fresh" in by_key["Recently learned"]
    assert "sess-new" in by_key["Recently learned"]           # recent chat still shows
    assert "stale" in by_key["Low confidence — might be stale"]
    # Old conversational items collapse into a count, not a bucket flood.
    assert model["older_conversational"] == 1
    assert model["active_entities"] is None                    # no stats given


def test_model_prefers_active_only_stats():
    stats = {"total_entities": 1328, "active_entities": 1200, "archived_entities": 128}
    model = perseus._knows_model(_sample_hits(), stats, limit=500)
    assert model["active_entities"] == 1200
    assert model["archived_entities"] == 128


def test_model_ignores_archived_inflated_stats_without_the_split():
    # Pre-#493 server: total_entities counts archived rows — must NOT be used.
    model = perseus._knows_model(_sample_hits(), {"total_entities": 1328}, limit=500)
    assert model["active_entities"] is None


def test_human_render_markers_ids_and_hints():
    stats = {"active_entities": 7, "archived_entities": 2}
    out = perseus._render_knows_human(perseus._knows_model(_sample_hits(), stats, 500))
    assert "Perseus knows 7 things" in out
    assert "(2 archived — hidden)" in out
    assert "✔ [aa000000]" in out          # verified marker + 8-char short id
    assert "~ [bb000000]" in out          # unverified marker
    assert "--forget" in out and "--correct" in out and "--show" in out


def test_json_render_round_trips():
    out = perseus._render_knows_json(perseus._knows_model(_sample_hits(), None, 500))
    data = json.loads(out)
    assert data["bucket_order"][0] == "About you"
    assert data["listed"] == 7


# ── short-id resolution ───────────────────────────────────────────────────────

def test_resolve_unique_prefix_and_full_id():
    hits = _sample_hits()
    hit, err = perseus._knows_resolve_id(hits, "aa00")
    assert err == "" and hit.key == "name"
    hit, err = perseus._knows_resolve_id(hits, "mem-bb0000000002")
    assert err == "" and hit.key == "db-choice"


def test_resolve_ambiguous_and_missing():
    hits = _sample_hits()
    hit, err = perseus._knows_resolve_id(hits, "")
    assert hit is None
    # Every conversation id shares no prefix here; force ambiguity via "0"?
    # ids: aa…, bb…, cc…, dd…, ee…, ff…, 0a… — single char "a" is unambiguous
    # for aa… only; craft two with a shared prefix instead.
    hits2 = perseus._parse_memory_hits({"items": [
        _raw("abc000000001", "user", "one"),
        _raw("abc000000002", "user", "two"),
    ]})
    hit, err = perseus._knows_resolve_id(hits2, "abc")
    assert hit is None and "ambiguous" in err
    hit, err = perseus._knows_resolve_id(hits2, "zzz")
    assert hit is None and "no memory matches" in err


# ── cmd_knows flows ───────────────────────────────────────────────────────────

def test_cmd_knows_lists_buckets(monkeypatch, capsys):
    c = _connector({"mimir_recall": ({"items": [_raw("aa0000000001", "user", "name")]}, None),
                    "mimir_stats": ({"active_entities": 1, "archived_entities": 0}, None)})
    rc = perseus.cmd_knows(_ns(), _knows_cfg(c, monkeypatch))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Perseus knows 1 things" in out
    assert "About you" in out


def test_cmd_knows_unreachable_is_loud_not_empty(monkeypatch, capsys):
    c = perseus.MnemeConnector(cfg())
    c._ensure_connected = lambda: False
    rc = perseus.cmd_knows(_ns(), _knows_cfg(c, monkeypatch))
    out = capsys.readouterr().out
    assert rc == 1
    assert "unreachable" in out
    assert "perseus doctor" in out


def test_cmd_knows_disabled_by_config(monkeypatch, capsys):
    local = cfg()
    local["knows"] = {"enabled": False}
    rc = perseus.cmd_knows(_ns(), local)
    assert rc == 1
    assert "disabled" in capsys.readouterr().out


def test_cmd_knows_forget_confirms_then_archives(monkeypatch, capsys):
    c = _connector({
        "mimir_recall": ({"items": [_raw("aa0000000001", "user", "shoe-size")]}, None),
        "mimir_forget": ({"archived": True}, None),
    })
    rc = perseus.cmd_knows(_ns(forget="aa00", yes=True), _knows_cfg(c, monkeypatch))
    assert rc == 0
    forgets = [(n, a) for n, a in c._client.calls if n == "mimir_forget"]
    assert forgets == [("mimir_forget", {
        "category": "user", "key": "shoe-size",
        "reason": "user request via `perseus knows --forget`"})]
    out = capsys.readouterr().out
    assert "reversible" in out


def test_cmd_knows_forget_cancelled_writes_nothing(monkeypatch, capsys):
    c = _connector({
        "mimir_recall": ({"items": [_raw("aa0000000001", "user", "shoe-size")]}, None),
    })
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    rc = perseus.cmd_knows(_ns(forget="aa00"), _knows_cfg(c, monkeypatch))
    assert rc == 1
    assert not [n for n, _ in c._client.calls if n == "mimir_forget"]
    assert "cancelled" in capsys.readouterr().out


def test_cmd_knows_correct_passes_old_content_as_wrong_approach(monkeypatch, capsys):
    c = _connector({
        "mimir_recall": ({"items": [_raw("aa0000000001", "user", "editor",
                                         body="uses emacs")]}, None),
        "mimir_correct": ({"id": "mem-new"}, None),
    })
    rc = perseus.cmd_knows(_ns(correct="aa00", value="uses neovim", yes=True),
                           _knows_cfg(c, monkeypatch))
    assert rc == 0
    corrections = [a for n, a in c._client.calls if n == "mimir_correct"]
    assert corrections and corrections[0]["wrong_approach"] == "uses emacs"
    assert corrections[0]["user_correction"] == "uses neovim"
    assert corrections[0]["category"] == "user"


def test_cmd_knows_show_prints_full_provenance(monkeypatch, capsys):
    c = _connector({
        "mimir_recall": ({"items": [_raw("aa0000000001", "user", "name")]}, None),
        "mimir_get_entity": ({"id": "mem-aa0000000001",
                              "body_json": "{\"note\": \"full body\"}",
                              "source": "bridge", "status": "active"}, None),
    })
    rc = perseus.cmd_knows(_ns(show="aa00"), _knows_cfg(c, monkeypatch))
    assert rc == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["short_id"] == "aa000000"
    assert "full body" in detail["body_json"]
    assert detail["source"] == "bridge"
    gets = [a for n, a in c._client.calls if n == "mimir_get_entity"]
    assert gets == [{"id": "mem-aa0000000001"}]
