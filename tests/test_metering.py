"""#755 — observe-model runtime cost metering.

Verifies the acceptance criterion: an opt-in Perseus deployment observes its
agent's provider responses and produces a Plutus ledger whose totals a customer
can re-derive by raw SQL — and that when unconfigured the meter is a no-op that
imports nothing and never touches the caller.
"""
import copy
import sqlite3
import sys
import types

import pytest

from conftest import perseus

pytestmark = pytest.mark.skipif(perseus is None, reason="requires built perseus.py")

# plutus-agent is the meter Perseus records into; skip if it isn't installed
# (the module itself must still import — that's asserted separately below).
plutus_agent = pytest.importorskip("plutus_agent")


def _obj(**kw):
    """A stand-in for a provider SDK response (attribute access, like the real
    openai/anthropic client objects)."""
    return types.SimpleNamespace(**kw)


def _openai_resp(prompt=1000, completion=200, model="gpt-4o"):
    return _obj(model=model,
                usage=_obj(prompt_tokens=prompt, completion_tokens=completion,
                           completion_tokens_details=None))


def _anthropic_resp(inp=1500, out=300, model="claude-opus-4-8"):
    return _obj(model=model,
                usage=_obj(input_tokens=inp, output_tokens=out,
                           cache_read_input_tokens=0))


def _enabled_cfg(ledger):
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["plutus"].update({"enabled": True, "db_path": str(ledger),
                        "org": "acme", "workspace": "prod-agent"})
    return c


@pytest.fixture(autouse=True)
def _reset():
    perseus._mtr_reset_for_tests()
    yield
    perseus._mtr_reset_for_tests()


# ── opt-in guarantees ─────────────────────────────────────────────────────────

def test_disabled_by_default():
    assert perseus.metering_enabled(perseus.DEFAULT_CONFIG) is False


def test_noop_when_unconfigured(tmp_path):
    # default config: no target, disabled → meter_response is a silent no-op,
    # returns None, records nothing, drops nothing, and writes no ledger.
    res = perseus.meter_response(perseus.DEFAULT_CONFIG, _openai_resp())
    assert res is None
    assert perseus.metering_dropped_events() == 0
    assert not list(tmp_path.iterdir())  # nothing written anywhere


def test_enabled_requires_a_target():
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["plutus"]["enabled"] = True  # but no db_path / endpoint
    assert perseus.metering_enabled(c) is False


# ── the acceptance criterion: live session → SQL-rederivable ledger ───────────

def test_session_produces_sql_rederivable_ledger(tmp_path):
    ledger = tmp_path / "plutus_ledger.db"
    cfg = _enabled_cfg(ledger)

    r1 = perseus.meter_response(cfg, _openai_resp(), task_type="longmemeval-qa")
    r2 = perseus.meter_response(cfg, _anthropic_resp(), task_type="longmemeval-qa")

    # provider auto-detected from the usage shape, not the model string
    assert r1.recorded and r1.provider == "openai"
    assert r2.recorded and r2.provider == "anthropic"
    assert perseus.metering_dropped_events() == 0

    # a customer re-derives the totals with raw SQL — no Perseus/Plutus code
    con = sqlite3.connect(str(ledger))
    try:
        # (ledger id is a UUID, not insertion-ordered — compare as a set)
        rows = con.execute(
            "SELECT provider, task_type, input_tokens, output_tokens "
            "FROM usage_events").fetchall()
        assert set(rows) == {
            ("openai", "longmemeval-qa", 1000, 200),
            ("anthropic", "longmemeval-qa", 1500, 300),
        }
        total_micros = con.execute(
            "SELECT SUM(cost_micros) FROM usage_events").fetchone()[0]
        # both events priced from provider tokens; totals are integer-exact
        assert total_micros > 0
        assert total_micros == r1.cost_usd * 1e6 + r2.cost_usd * 1e6
    finally:
        con.close()


def test_workspace_and_task_type_tags_land(tmp_path):
    ledger = tmp_path / "l.db"
    cfg = _enabled_cfg(ledger)
    # per-call workspace overrides the config default
    perseus.meter_response(cfg, _openai_resp(), task_type="chat",
                           workspace="agent-b")
    con = sqlite3.connect(str(ledger))
    try:
        prov, tt, ws = con.execute(
            "SELECT e.provider, e.task_type, w.name FROM usage_events e "
            "LEFT JOIN workspaces w ON w.id = e.workspace_id").fetchone()
        assert (prov, tt, ws) == ("openai", "chat", "agent-b")
    finally:
        con.close()


def test_raw_usage_path(tmp_path):
    ledger = tmp_path / "l.db"
    cfg = _enabled_cfg(ledger)
    res = perseus.meter_usage(cfg, "openai", model="gpt-4o",
                              input_tokens=10, output_tokens=5,
                              task_type="tool")
    assert res.recorded
    con = sqlite3.connect(str(ledger))
    try:
        n = con.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0]
        assert n == 1
    finally:
        con.close()


# ── never breaks the caller ───────────────────────────────────────────────────

def test_fail_open_swallows_errors_and_counts_drop(tmp_path):
    # point at a directory (not a file) so opening the ledger fails; fail_open
    # (default) means meter_response returns None instead of raising, and the
    # meter degrades to a cached no-op.
    bad = tmp_path / "adir"
    bad.mkdir()
    cfg = _enabled_cfg(bad)
    res = perseus.meter_response(cfg, _openai_resp())
    assert res is None  # did not raise, did not crash the "serving call"


def test_fail_closed_raises_when_configured(tmp_path):
    # with fail_open false and a working ledger, a malformed response (negative
    # tokens are rejected by plutus) surfaces as an exception instead of a
    # silent drop, for callers that want metering to be load-bearing.
    ledger = tmp_path / "l.db"
    cfg = _enabled_cfg(ledger)
    cfg["plutus"]["fail_open"] = False
    bad = _obj(model="x", usage=_obj(prompt_tokens=-1, completion_tokens=0,
                                     completion_tokens_details=None))
    with pytest.raises(Exception):
        perseus.meter_response(cfg, bad)


# ── #805: savings baselines through the bridge ────────────────────────────────

def _baselines_supported():
    import inspect as _inspect
    from plutus_agent import Meter
    return "baseline_input_tokens" in _inspect.signature(Meter.track).parameters


needs_baselines = pytest.mark.skipif(
    not _baselines_supported(),
    reason="installed plutus-agent predates savings baselines (plutus #134)")


@needs_baselines
def test_meter_usage_carries_token_reduction_baseline(tmp_path):
    ledger = tmp_path / "l.db"
    cfg = _enabled_cfg(ledger)
    res = perseus.meter_usage(
        cfg, "anthropic", model="claude-opus-4-8",
        input_tokens=100_000, output_tokens=10_000, task_type="serving",
        baseline_input_tokens=1_000_000, baseline_output_tokens=10_000)
    assert res.recorded
    assert res.savings_usd > 0
    con = sqlite3.connect(str(ledger))
    try:
        bl = con.execute(
            "SELECT baseline_micros FROM usage_events").fetchone()[0]
        assert bl is not None and bl > 0
    finally:
        con.close()


@needs_baselines
def test_meter_response_carries_baseline(tmp_path):
    ledger = tmp_path / "l.db"
    cfg = _enabled_cfg(ledger)
    res = perseus.meter_response(
        cfg, _openai_resp(prompt=25_000, completion=500),
        baseline_input_tokens=100_000)
    assert res.recorded
    assert res.savings_usd > 0
    assert perseus.metering_dropped_events() == 0


@needs_baselines
def test_context_reduction_lands_in_estimates_workspace(tmp_path):
    ledger = tmp_path / "l.db"
    cfg = _enabled_cfg(ledger)
    res = perseus.meter_context_reduction(
        cfg,
        actual_text="short pointer block " * 10,
        baseline_text="the full memory dump this replaced " * 400)
    assert res is not None and res.recorded
    assert res.savings_usd >= 0
    con = sqlite3.connect(str(ledger))
    try:
        src, tt, ws, bl = con.execute(
            "SELECT e.source, e.task_type, w.name, e.baseline_micros "
            "FROM usage_events e LEFT JOIN workspaces w ON w.id=e.workspace_id"
        ).fetchone()
        # estimate-arm events never land in the real-spend workspace, and the
        # source records whether the count was tokenizer-exact or heuristic.
        assert ws == "perseus-render-estimates"
        assert src in ("estimate-exact", "estimate-heuristic")
        assert tt == "context-reduction"
        assert bl is not None and bl > 0
    finally:
        con.close()


def test_context_reduction_noop_when_disabled(tmp_path):
    res = perseus.meter_context_reduction(
        perseus.DEFAULT_CONFIG, actual_text="a", baseline_text="b " * 100)
    assert res is None
    assert not list(tmp_path.iterdir())


def test_old_plutus_agent_drops_baselines_not_spend():
    # A meter whose track() predates #134: baselines must be silently dropped
    # (one warning), never passed as unexpected kwargs that would fail the
    # whole event and lose real spend data.
    class _OldMeter:
        def track(self, provider, *, model=None, task_type="general",
                  workspace=None, input_tokens=0, output_tokens=0,
                  cache_read_tokens=0, reasoning_tokens=0, cost_usd=None,
                  source="sdk"):
            raise AssertionError("track should not be called by this test")

    kw = perseus._mtr_baseline_kwargs(_OldMeter(), None, None, 1000, 0)
    assert kw == {}
    # and a modern signature passes them through
    class _NewMeter:
        def track(self, provider, *, baseline_cost_usd=None,
                  baseline_model=None, baseline_input_tokens=None,
                  baseline_output_tokens=None, **rest):
            raise AssertionError("track should not be called by this test")

    kw = perseus._mtr_baseline_kwargs(_NewMeter(), None, "gpt-5", 1000, 0)
    assert kw == {"baseline_model": "gpt-5", "baseline_input_tokens": 1000,
                  "baseline_output_tokens": 0}
