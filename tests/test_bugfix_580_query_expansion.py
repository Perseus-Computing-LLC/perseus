"""#580 — optional LLM query expansion (multi-query fusion) in MnemeConnector.

When `mneme.expansion.enabled` is off (the default), recall is a single verbatim
query — byte-identical to before (covered by test_bugfix_699). When on, the
question is planned into sub-queries, each recalled, and the hits RRF-fused —
lifting weak-category recall. Validated end-to-end on LongMemEval; these are the
unit-level guarantees (fusion math, dedup, fail-safe fallback, off-by-default).
"""
import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


class _StubClient:
    is_connected = True

    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return ({"memories": []}, None)


def _conn(expansion=False, monkeypatch=None):
    c = cfg()
    c["perseus_vault"].update(enabled=True)
    if expansion:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        c["perseus_vault"]["expansion"] = {"enabled": True, "api_key_env": "OPENAI_API_KEY"}
    conn = perseus.MnemeConnector(c)
    conn._client = _StubClient()
    return conn


# ---- pure helpers ----------------------------------------------------------
def test_rrf_fuse_orders_by_reciprocal_rank():
    # 'b' is highly ranked in all three lists -> should win.
    fused = perseus.rrf_fuse([["a", "b", "c"], ["b", "a"], ["b"]])
    assert fused[0] == "b"
    assert set(fused) == {"a", "b", "c"}


def test_query_set_dedups_and_appends_original():
    qp = perseus.QueryPlan(sub_queries=["film festival", "Film Festival ", "attended"],
                           aggregation=True, topic="festivals")
    qs = qp.query_set("how many movie festivals")
    assert qs[-1] == "how many movie festivals"       # original always last
    assert "festivals" in qs                            # aggregation topic added
    # case-insensitive dedup of the two "film festival" variants
    assert sum(1 for q in qs if q.lower() == "film festival") == 1


# ---- connector behavior ----------------------------------------------------
def test_expansion_off_is_single_query(monkeypatch):
    conn = _conn(expansion=False)
    seg = conn.recall(query="what do you know")
    assert seg.strategy_used == "mimir_recall"
    assert len(conn._client.calls) == 1  # exactly one recall, unchanged behavior


def test_expansion_fuses_subqueries(monkeypatch):
    conn = _conn(expansion=True, monkeypatch=monkeypatch)
    monkeypatch.setattr(perseus, "plan_query",
                        lambda q, d, cfg: perseus.QueryPlan(sub_queries=["a", "b"]))

    table = {
        "a": [perseus.MemoryHit(id="s3"), perseus.MemoryHit(id="s1")],
        "b": [perseus.MemoryHit(id="s2"), perseus.MemoryHit(id="s3")],
        "what": [perseus.MemoryHit(id="s1"), perseus.MemoryHit(id="s2")],
    }
    calls = []

    def fake_once(query, limit, min_decay, ws, tp, tf):
        calls.append(query)
        return table.get(query, []), None

    monkeypatch.setattr(conn, "_recall_once", fake_once)
    seg = conn.recall(query="what", max_results=10)

    assert seg.strategy_used == "mimir_recall_expanded"
    assert set(calls) == {"a", "b", "what"}            # one recall per query
    ids = {h.id for h in seg.items}
    assert ids == {"s1", "s2", "s3"}                   # s3 only came from sub-queries


def test_expansion_falls_back_when_planner_unavailable(monkeypatch):
    conn = _conn(expansion=True, monkeypatch=monkeypatch)
    monkeypatch.setattr(perseus, "plan_query", lambda q, d, cfg: None)  # planner fails
    seg = conn.recall(query="q")
    # falls through to the unchanged single-query path
    assert seg.strategy_used == "mimir_recall"
    assert len(conn._client.calls) == 1


def test_expansion_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = cfg()
    c["perseus_vault"].update(enabled=True)
    c["perseus_vault"]["expansion"] = {"enabled": True, "api_key_env": "OPENAI_API_KEY"}
    conn = perseus.MnemeConnector(c)
    assert conn._expansion.enabled is False  # no key -> fail safe, expansion off
