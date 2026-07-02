"""Tests for @bandit — adaptive, outcome-driven directive selection (#605).

Covers: ledger round-trip + atomicity, per-workspace keying, seeded-sampler
determinism, safety floors, token budget, the replayed-corpus acceptance
criterion (policy beats include-everything on value/token), feedback CLI
(explicit + verbatim-payload heuristic), explain/decision consistency, and
the default-off zero-behavior-change guarantee.

Determinism: every stochastic assertion uses an injected seed — no wall clock,
no unseeded randomness.
"""
import argparse
import json

import pytest

from conftest import PY_VER, cfg, perseus, _capture_json

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# Deterministic corpus: no @date/@query — only env + file reads.
GOOD_NOTE = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima"
BAD_NOTE = ("verbose low value boilerplate " * 30).strip()
ENV_VALUE = "bandit-env-value-0123456789-abcdefghijklmnop"

SOURCE = '@perseus\n# Bandit corpus\n@env BANDIT_TEST_VAR\n@read "good.txt"\n@read "bad.txt"\n'


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("BANDIT_TEST_VAR", ENV_VALUE)
    w = tmp_path / "ws"
    w.mkdir()
    (w / "good.txt").write_text(GOOD_NOTE, encoding="utf-8")
    (w / "bad.txt").write_text(BAD_NOTE, encoding="utf-8")
    return w


def _cfg(tmp_path, **render_overrides):
    c = cfg()
    c["render"]["cache_dir"] = str(tmp_path / "cache")
    c["render"].update(render_overrides)
    return c


def _ledger_path(c, w):
    return perseus._bandit_ledger_path(c, w)


def _arm(name, args):
    return perseus._bandit_arm_key(name, args)


ARM_GOOD = _arm("@read", '"good.txt"')
ARM_BAD = _arm("@read", '"bad.txt"')
ARM_ENV = _arm("@env", "BANDIT_TEST_VAR")


def _feed(c, w, arm, outcome, n=1):
    """Apply n outcome signals directly to the persisted ledger."""
    ledger = perseus._bandit_load_ledger(c, w)
    for _ in range(n):
        perseus._bandit_apply_outcome(ledger, arm, arm.split("#")[0], outcome)
    perseus._bandit_save_ledger(c, w, ledger)


# ── Default off: zero behavior change ────────────────────────────────────────

def test_default_off_is_byte_identical_and_writes_no_ledger(tmp_path, ws):
    c_off = _cfg(tmp_path)  # bandit unconfigured (DEFAULT_CONFIG: "off")
    assert c_off["render"]["bandit"] == "off"
    out_unset = perseus.render_source(SOURCE, c_off, ws)
    assert GOOD_NOTE in out_unset and "low value boilerplate" in out_unset
    assert not (tmp_path / "cache" / "bandit").exists()

    # record mode learns silently: output stays byte-identical
    out_record = perseus.render_source(SOURCE, _cfg(tmp_path, bandit="record"), ws)
    assert out_record == out_unset
    assert _ledger_path(_cfg(tmp_path), ws).exists()


def test_cold_start_auto_matches_static_tier_behavior(tmp_path, ws):
    """No ledger + mode=auto ⇒ every arm is cold-start ⇒ byte-identical render."""
    out_off = perseus.render_source(SOURCE, _cfg(tmp_path), ws)
    c_auto = _cfg(tmp_path, bandit="auto", bandit_seed=7)
    # point at a fresh cache dir so no ledger exists yet
    c_auto["render"]["cache_dir"] = str(tmp_path / "cache2")
    out_auto = perseus.render_source(SOURCE, c_auto, ws)
    assert out_auto == out_off


# ── Ledger store ─────────────────────────────────────────────────────────────

def test_ledger_round_trip_and_atomic_write(tmp_path, ws):
    c = _cfg(tmp_path)
    ledger = perseus._bandit_empty_ledger(ws)
    ledger["arms"]["@read#deadbeef"] = {"name": "@read", "good": 3, "bad": 1,
                                        "tokens_sum": 400, "tokens_n": 4}
    perseus._bandit_save_ledger(c, ws, ledger)
    loaded = perseus._bandit_load_ledger(c, ws)
    assert loaded["arms"]["@read#deadbeef"]["good"] == 3
    assert loaded["version"] == perseus._BANDIT_LEDGER_VERSION
    # atomic: temp file was os.replace'd — only the ledger remains
    files = sorted(p.name for p in _ledger_path(c, ws).parent.iterdir())
    assert files == [_ledger_path(c, ws).name]


def test_corrupt_or_absent_ledger_degrades_to_empty(tmp_path, ws):
    c = _cfg(tmp_path)
    # absent
    assert perseus._bandit_load_ledger(c, ws)["arms"] == {}
    # corrupt
    path = _ledger_path(c, ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert perseus._bandit_load_ledger(c, ws)["arms"] == {}
    # a render with mode=auto over the corrupt ledger must not crash and
    # must include everything (cold start == static tiers)
    out = perseus.render_source(SOURCE, _cfg(tmp_path, bandit="auto", bandit_seed=1), ws)
    assert GOOD_NOTE in out and "low value boilerplate" in out


def test_ledger_is_keyed_per_workspace(tmp_path, ws):
    c = _cfg(tmp_path, bandit="record")
    other = tmp_path / "other-ws"
    other.mkdir()
    p1, p2 = _ledger_path(c, ws), _ledger_path(c, other)
    assert p1 != p2, "workspace must be folded into the persisted key (#580/#568)"
    perseus.render_source(SOURCE, c, ws)
    assert p1.exists() and not p2.exists()


# ── Identity + render_id ─────────────────────────────────────────────────────

def test_arm_key_is_stable_under_whitespace_and_case():
    assert _arm("@Read", ' "a.txt" ') == _arm("read", '"a.txt"')
    assert _arm("@read", "") == "@read"
    assert _arm("@read", '"a.txt"') != _arm("@read", '"b.txt"')


def test_render_id_is_deterministic_and_workspace_scoped(tmp_path):
    a = perseus._bandit_render_id("@perseus\nX", tmp_path)
    assert a == perseus._bandit_render_id("@perseus\nX", tmp_path)
    assert a != perseus._bandit_render_id("@perseus\nY", tmp_path)
    assert a != perseus._bandit_render_id("@perseus\nX", tmp_path / "sub")


# ── @bandit source line ──────────────────────────────────────────────────────

def test_bandit_line_enables_and_is_stripped_from_output(tmp_path, ws):
    src = SOURCE.replace("# Bandit corpus", "# Bandit corpus\n@bandit tier=auto seed=3")
    out = perseus.render_source(src, _cfg(tmp_path), ws)  # config OFF, doc opts in
    assert "@bandit" not in out
    assert _ledger_path(_cfg(tmp_path), ws).exists(), "doc-level @bandit should activate the ledger"


def test_bandit_line_inside_code_fence_is_literal(tmp_path, ws):
    src = "@perseus\n```\n@bandit tier=auto\n```\n" + "\n".join(SOURCE.splitlines()[1:])
    out = perseus.render_source(src, _cfg(tmp_path), ws)
    assert "@bandit tier=auto" in out
    assert not (tmp_path / "cache" / "bandit").exists()


def test_bandit_registered_as_control_directive_not_mcp_tool():
    spec = perseus.DIRECTIVE_REGISTRY.get("@bandit")
    assert spec is not None and spec.kind == "control" and spec.resolver is None
    tool_names = {t["name"] for t in perseus._get_all_mcp_tools({})}
    assert "perseus_bandit" not in tool_names


# ── Policy: determinism, floors, budget ──────────────────────────────────────

def _seed_arm_stats(c, w, arm, good, bad, tokens_sum=0, tokens_n=0):
    ledger = perseus._bandit_load_ledger(c, w)
    ledger["arms"][arm] = {"name": arm.split("#")[0], "good": good, "bad": bad,
                           "tokens_sum": tokens_sum, "tokens_n": tokens_n}
    perseus._bandit_save_ledger(c, w, ledger)


def _decisions(c, w, arms, seed):
    """Run one seeded policy pass over (name, args) pairs; return decisions."""
    c2 = json.loads(json.dumps(c))  # deep copy without sharing
    c2["render"]["bandit_seed"] = seed
    ctx = perseus.BanditContext(c2, w, "corpus", "auto")
    for name, args in arms:
        ctx.decide(name, args)
    return ctx.decisions


def test_seeded_sampler_is_deterministic(tmp_path, ws):
    c = _cfg(tmp_path)
    _seed_arm_stats(c, ws, ARM_BAD, good=4, bad=4)
    arms = [("@read", '"bad.txt"')] * 10
    d1 = _decisions(c, ws, arms, seed=99)
    d2 = _decisions(c, ws, arms, seed=99)
    assert d1 == d2
    assert any(d["sampled_p"] is not None for d in d1)


def test_safety_floor_never_violated(tmp_path, ws):
    """Tier-1, @constraint-class, and configured-floor arms are never dropped —
    even with a maximally bad ledger, across 200 seeded decisions."""
    c = _cfg(tmp_path, bandit_floor=["@read"])
    _seed_arm_stats(c, ws, ARM_ENV, good=0, bad=100)
    _seed_arm_stats(c, ws, ARM_BAD, good=0, bad=100)
    _seed_arm_stats(c, ws, _arm("@constraint", ""), good=0, bad=100)
    for seed in range(200):
        for d in _decisions(c, ws, [("@env", "BANDIT_TEST_VAR"),
                                    ("@read", '"bad.txt"'),
                                    ("@constraint", "")], seed):
            assert d["decision"] == "include", d
            assert d["reason"] == "safety-floor"


def test_cold_start_arms_are_always_included(tmp_path, ws):
    c = _cfg(tmp_path)
    for seed in range(50):
        (d,) = _decisions(c, ws, [("@tree", '"src" depth=2')], seed)
        assert d["decision"] == "include" and d["reason"] == "cold-start"


def test_token_budget_never_exceeded(tmp_path, ws):
    c = _cfg(tmp_path, bandit_budget=150)
    # three well-learned, high-value arms, ~100 estimated tokens each
    arms = []
    for i in range(3):
        arm = _arm("@read", f'"f{i}.txt"')
        _seed_arm_stats(c, ws, arm, good=50, bad=0, tokens_sum=1000, tokens_n=10)
        arms.append(("@read", f'"f{i}.txt"'))
    for seed in range(50):
        c2 = json.loads(json.dumps(c))
        c2["render"]["bandit_seed"] = seed
        ctx = perseus.BanditContext(c2, ws, "corpus", "auto")
        for name, args in arms:
            ctx.decide(name, args)
        included_cost = sum(d["mean_tokens"] for d in ctx.decisions
                            if d["decision"] == "include")
        assert included_cost <= 150
        assert any(d["reason"] == "over-budget" for d in ctx.decisions)


# ── Replayed corpus: the acceptance criterion ────────────────────────────────

def _include_rate(c, w, name, args, n=300):
    hits = 0
    for seed in range(n):
        (d,) = _decisions(c, w, [(name, args)], seed)
        hits += d["decision"] == "include"
    return hits / n


def test_replayed_corpus_beats_include_everything_on_value_per_token(tmp_path, ws):
    """Replay renders + outcome signals: the low-value expensive arm's inclusion
    probability provably decreases (deterministic under fixed seeds), the
    high-value one stays up, and the resulting selection has strictly better
    value/token than include-everything. Safety arms are untouched."""
    c = _cfg(tmp_path, bandit="record")

    # Replay: 6 recorded renders, feedback after each — good.txt referenced,
    # bad.txt chronically ignored.
    p_bad_trajectory = []
    for _epoch in range(6):
        perseus.render_source(SOURCE, c, ws)  # records token costs
        _feed(c, ws, ARM_GOOD, "good")
        _feed(c, ws, ARM_BAD, "bad")
        p_bad_trajectory.append(_include_rate(c, ws, "@read", '"bad.txt"'))

    # inclusion probability of the chronically-bad arm decreases (converges)
    assert p_bad_trajectory[-1] < p_bad_trajectory[2] <= 1.0
    assert p_bad_trajectory[-1] < 0.15
    # high-value arm stays confidently included
    assert _include_rate(c, ws, "@read", '"good.txt"') > 0.9

    # Final adaptive render: bad arm dropped, good + safety-floor kept.
    c_auto = _cfg(tmp_path, bandit="auto", bandit_seed=5)
    out = perseus.render_source(SOURCE, c_auto, ws)
    assert GOOD_NOTE in out
    assert ENV_VALUE in out  # tier-1 safety floor
    assert "low value boilerplate" not in out

    # Value/token: policy selection vs include-everything, from the ledger.
    ledger = perseus._bandit_load_ledger(c, ws)

    def stats(arm):
        st = ledger["arms"][arm]
        trials = st["good"] + st["bad"]
        value = (st["good"] + 1) / (trials + 2)
        mean_tokens = st["tokens_sum"] / max(st["tokens_n"], 1)
        return value, mean_tokens

    all_arms = [ARM_ENV, ARM_GOOD, ARM_BAD]
    policy_arms = [ARM_ENV, ARM_GOOD]  # what the seeded render included
    everything = sum(stats(a)[0] for a in all_arms) / sum(stats(a)[1] for a in all_arms)
    policy = sum(stats(a)[0] for a in policy_arms) / sum(stats(a)[1] for a in policy_arms)
    assert policy > everything, (
        f"bandit selection value/token {policy:.5f} must beat "
        f"include-everything {everything:.5f}"
    )


# ── Feedback CLI ─────────────────────────────────────────────────────────────

def _record_render(tmp_path, ws):
    c = _cfg(tmp_path, bandit="record")
    perseus.render_source(SOURCE, c, ws)
    return c, perseus._bandit_render_id(SOURCE, ws)


def _feedback_args(rid, ws, **kw):
    base = dict(command="feedback", render_id=rid, directive=None, outcome=None,
                from_payload=None, workspace=str(ws), json=True)
    base.update(kw)
    return argparse.Namespace(**base)


def test_feedback_cli_records_outcome(tmp_path, ws, monkeypatch):
    c, rid = _record_render(tmp_path, ws)
    monkeypatch.setattr(perseus, "load_config", lambda *a, **k: c)
    out, rc = _capture_json(monkeypatch, perseus.cmd_bandit_cli,
                            _feedback_args(rid[:8], ws, directive=ARM_BAD, outcome="bad"), c)
    assert rc == 0 and out["applied"][0]["outcome"] == "bad"
    ledger = perseus._bandit_load_ledger(c, ws)
    assert ledger["arms"][ARM_BAD]["bad"] == 1

    # bare directive name fans out to every arm of that name in the render
    out, rc = _capture_json(monkeypatch, perseus.cmd_bandit_cli,
                            _feedback_args(rid, ws, directive="@read", outcome="good"), c)
    assert rc == 0 and {a["arm"] for a in out["applied"]} == {ARM_GOOD, ARM_BAD}


def test_feedback_cli_rejects_unknown_render_and_directive(tmp_path, ws, monkeypatch):
    c, rid = _record_render(tmp_path, ws)
    monkeypatch.setattr(perseus, "load_config", lambda *a, **k: c)
    assert perseus.cmd_bandit_cli(_feedback_args("ffffffffffff", ws,
                                                 directive="@read", outcome="bad"), c) == 1
    assert perseus.cmd_bandit_cli(_feedback_args(rid, ws,
                                                 directive="@nosuch", outcome="bad"), c) == 1
    assert perseus.cmd_bandit_cli(_feedback_args(rid, ws), c) == 1  # missing outcome


def test_feedback_payload_heuristic_marks_verbatim_blocks_good(tmp_path, ws, monkeypatch):
    """The issue's cheap heuristic: block bytes appearing verbatim in a later
    payload ⇒ referenced (good); recorded blocks that don't appear ⇒ bad."""
    c, rid = _record_render(tmp_path, ws)
    payload = tmp_path / "agent-payload.txt"
    payload.write_text(f"tool call args include: {GOOD_NOTE} — done", encoding="utf-8")
    monkeypatch.setattr(perseus, "load_config", lambda *a, **k: c)
    out, rc = _capture_json(monkeypatch, perseus.cmd_bandit_cli,
                            _feedback_args(rid, ws, from_payload=str(payload)), c)
    assert rc == 0
    outcomes = {a["arm"]: a["outcome"] for a in out["applied"]}
    assert outcomes[ARM_GOOD] == "good"
    assert outcomes[ARM_BAD] == "bad"


# ── Explain ──────────────────────────────────────────────────────────────────

def _explain_args(source, ws, bandit=True):
    return argparse.Namespace(command="explain", source=str(source), bandit=bandit,
                              workspace=str(ws), tier=None, json=True)


def test_explain_bandit_reports_decisions_that_match_the_render(tmp_path, ws, monkeypatch):
    """`perseus explain --bandit` decisions must match actual include/drop
    behavior: same ledger + same seed ⇒ same Thompson samples ⇒ no drift."""
    c = _cfg(tmp_path, bandit="record")
    for _ in range(4):
        perseus.render_source(SOURCE, c, ws)
        _feed(c, ws, ARM_BAD, "bad")
        _feed(c, ws, ARM_GOOD, "good")

    src_file = ws / "ctx.md"
    src_file.write_text(SOURCE, encoding="utf-8")
    c_auto = _cfg(tmp_path, bandit="auto", bandit_seed=5)
    monkeypatch.setattr(perseus, "load_config", lambda *a, **k: json.loads(json.dumps(c_auto)))

    report, rc = _capture_json(monkeypatch, perseus.cmd_bandit_cli,
                               _explain_args(src_file, ws), c_auto)
    assert rc == 0
    assert report["render_id"] == perseus._bandit_render_id(SOURCE, ws)
    b = report["bandit"]
    assert b["enabled"] is True and b["mode"] == "auto"
    decisions = {d["arm"]: d for d in b["decisions"]}
    assert decisions[ARM_ENV]["reason"] == "safety-floor"
    for d in b["decisions"]:
        assert set(d) >= {"arm", "name", "tier", "good", "bad", "posterior_mean",
                          "sampled_p", "mean_tokens", "value_per_token",
                          "decision", "reason"}

    # No drift: an actual render with the same cfg reproduces the decisions.
    out = perseus.render_source(SOURCE, json.loads(json.dumps(c_auto)), ws)
    for d in b["decisions"]:
        marker = {ARM_GOOD: GOOD_NOTE, ARM_BAD: "low value boilerplate",
                  ARM_ENV: ENV_VALUE}[d["arm"]]
        assert (marker in out) == (d["decision"] == "include"), d


# ── Wave-5 hardening (#622–#625) ─────────────────────────────────────────────

def test_aborted_render_clears_stale_bandit_context(tmp_path, ws, monkeypatch):
    """#622: a directive error escaping _render_lines must not leave
    _BANDIT_ACTIVE set — direct _render_lines callers (the LSP hover/render
    path) never go through _bandit_begin and would inherit stale drop
    decisions. The aborted render must also not persist to the ledger."""
    c = _cfg(tmp_path, bandit="record")
    real = perseus._call_resolver
    calls = {"n": 0}

    def _boom_once(spec, args, cfg_, workspace):
        if calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("boom mid-render")
        return real(spec, args, cfg_, workspace)

    monkeypatch.setattr(perseus, "_call_resolver", _boom_once)
    with pytest.raises(RuntimeError, match="boom mid-render"):
        perseus.render_source(SOURCE, c, ws)
    assert perseus._BANDIT_ACTIVE is None, "#622: stale context survived the abort"
    assert not _ledger_path(c, ws).exists(), "aborted render must not persist"

    # A subsequent plain _render_lines render (the LSP path, no _bandit_begin)
    # is unaffected: nothing is dropped.
    out = perseus._render_lines(SOURCE.splitlines()[1:], _cfg(tmp_path), ws)
    assert GOOD_NOTE in out and "low value boilerplate" in out


def test_ledger_arms_are_pruned_with_last_seen_eviction(tmp_path, ws):
    """#623: arms beyond render.bandit_max_arms are evicted oldest-seen-first
    on persist; the current render's arms and the most-recently-seen synthetic
    arms survive."""
    c = _cfg(tmp_path, bandit="record", bandit_max_arms=5)
    ledger = perseus._bandit_empty_ledger(ws)
    ledger["seq"] = 10
    for i in range(10):
        ledger["arms"][f"@read#{i:08d}"] = {"name": "@read", "good": 1, "bad": 0,
                                            "tokens_sum": 10, "tokens_n": 1,
                                            "last_seen": i}
    perseus._bandit_save_ledger(c, ws, ledger)

    perseus.render_source(SOURCE, c, ws)  # prune-on-persist via finish()

    arms = perseus._bandit_load_ledger(c, ws)["arms"]
    assert len(arms) <= 5
    # the render's own arms are the most recently seen — they survive
    assert {ARM_GOOD, ARM_BAD, ARM_ENV} <= set(arms)
    # of the synthetic arms, only the most-recently-seen survive
    assert sorted(a for a in arms if a.startswith("@read#0")) == \
        ["@read#00000008", "@read#00000009"]


def test_prune_arms_treats_legacy_arms_as_oldest(tmp_path, ws):
    """#623: arms from pre-#623 ledgers (no last_seen) are evicted first."""
    c = _cfg(tmp_path, bandit_max_arms=2)
    ledger = perseus._bandit_empty_ledger(ws)
    ledger["arms"]["@read#legacy01"] = {"name": "@read", "good": 1, "bad": 0}
    ledger["arms"]["@read#recent01"] = {"name": "@read", "good": 1, "bad": 0, "last_seen": 3}
    ledger["arms"]["@read#recent02"] = {"name": "@read", "good": 1, "bad": 0, "last_seen": 7}
    perseus._bandit_prune_arms(ledger, c)
    assert set(ledger["arms"]) == {"@read#recent01", "@read#recent02"}
    # garbage cap config falls back to the default (no crash, nothing pruned)
    c_bad = _cfg(tmp_path, bandit_max_arms="lots")
    perseus._bandit_prune_arms(ledger, c_bad)
    assert set(ledger["arms"]) == {"@read#recent01", "@read#recent02"}


def test_malformed_seed_and_budget_fall_back_with_warning(tmp_path, ws, capsys):
    """#624: garbage bandit_seed/bandit_budget config values must not raise
    out of an opted-in render — default + stderr warning, like the sibling
    threshold/min_trials parsing."""
    c = _cfg(tmp_path, bandit="auto", bandit_seed="not-a-number", bandit_budget="lots")
    out = perseus.render_source(SOURCE, c, ws)
    assert GOOD_NOTE in out and "low value boilerplate" in out  # cold start: all included
    err = capsys.readouterr().err
    assert "bandit_seed" in err and "bandit_budget" in err

    ctx = perseus.BanditContext(c, ws, "corpus", "auto")
    assert ctx.budget is None  # malformed budget → unlimited (the default)


def test_prescan_does_not_execute_bandit_dropped_query(tmp_path, ws, monkeypatch):
    """#625 (execution side): a @query arm the bandit drops must not be
    pre-executed by the parallel pre-scan — for @query, execution is the
    expensive/sensitive part. The resolver spy stands in for the subprocess."""
    c = _cfg(tmp_path, bandit="auto", bandit_seed=1, parallel_queries=True)
    src = '@perseus\n# corpus\n@query "spy-dropped"\n@query "spy-kept"\n'
    _seed_arm_stats(c, ws, _arm("@query", '"spy-dropped"'), good=0, bad=100)

    calls: list[str] = []
    spec = perseus.DIRECTIVE_REGISTRY["@query"]

    def _spy(args, cfg_, workspace=None):
        calls.append(args)
        return f"ran:{args}"

    monkeypatch.setitem(perseus.DIRECTIVE_REGISTRY, "@query", spec._replace(resolver=_spy))
    out = perseus.render_source(src, c, ws)
    assert calls == ['"spy-kept"'], "dropped @query must not execute in the pre-scan"
    assert 'ran:"spy-kept"' in out
    assert "spy-dropped" not in out

    # The pre-scan decision and the main-loop decision point are one memoized
    # decision per arm — no re-sampling drift between the two call sites.
    decisions = {d["arm"]: d for d in perseus._BANDIT_LAST.decisions}
    assert decisions[_arm("@query", '"spy-dropped"')]["decision"] == "drop"
    assert decisions[_arm("@query", '"spy-kept"')]["decision"] == "include"
    assert len(perseus._BANDIT_LAST.decisions) == 2


def test_prefetched_query_costs_reach_the_ledger(tmp_path, ws, monkeypatch):
    """#625 (accounting side): @query results resolved by the parallel
    pre-scan must still be charged to the collector/ledger, or future
    include/drop decisions are biased toward arms whose cost the prefetch
    path hid."""
    c = _cfg(tmp_path, bandit="record", parallel_queries=True)
    src = '@perseus\n# corpus\n@query "spy-a"\n@query "spy-b"\n'
    spec = perseus.DIRECTIVE_REGISTRY["@query"]
    monkeypatch.setitem(
        perseus.DIRECTIVE_REGISTRY, "@query",
        spec._replace(resolver=lambda a, c_, w=None: f"prefetched output for {a}"))

    out = perseus.render_source(src, c, ws)
    assert "prefetched output" in out
    arms = perseus._bandit_load_ledger(c, ws)["arms"]
    for args in ('"spy-a"', '"spy-b"'):
        st = arms[_arm("@query", args)]
        assert st["tokens_n"] >= 1 and st["tokens_sum"] > 0, st


def test_explain_is_read_only(tmp_path, ws, monkeypatch):
    """explain must never mutate the ledger (bandit_record=False)."""
    c = _cfg(tmp_path, bandit="record")
    perseus.render_source(SOURCE, c, ws)
    before = perseus._bandit_load_ledger(c, ws)
    src_file = ws / "ctx.md"
    src_file.write_text(SOURCE, encoding="utf-8")
    monkeypatch.setattr(perseus, "load_config", lambda *a, **k: json.loads(json.dumps(c)))
    _capture_json(monkeypatch, perseus.cmd_bandit_cli, _explain_args(src_file, ws), c)
    assert perseus._bandit_load_ledger(c, ws) == before
