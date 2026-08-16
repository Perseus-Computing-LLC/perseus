"""Pluggable submodular context-selection engine over the pooled context (#970)."""
from __future__ import annotations

import pytest

from conftest import perseus

Candidate = perseus.PooledCandidate
select = perseus.select_pooled_context
verify = perseus.verify_selection_trace
relevance = perseus.relevance_score
pool_tokens = perseus.pool_tokens
register = perseus.register_policy


def turn(text, seq=None, cid=""):
    return Candidate(kind="session_turn", content=text, candidate_id=cid,
                     meta={"sequence": seq} if seq is not None else {})


def mem(text, cid=""):
    return Candidate(kind="memory_entry", content=text, candidate_id=cid)


def tool(text, cid=""):
    return Candidate(kind="tool_output", content=text, candidate_id=cid)


def ids(result):
    return result["kept_ids"]


# ── Pool and candidate semantics ──────────────────────────────────────────

def test_candidate_ids_are_content_derived_and_kind_validated():
    a = mem("alice owns the arcade")
    b = mem("alice owns the arcade")
    assert a.candidate_id == b.candidate_id
    assert mem("different").candidate_id != a.candidate_id
    with pytest.raises(perseus.PooledSelectionError):
        Candidate(kind="vibes", content="x")


def test_duplicate_ids_rejected():
    a = mem("x", cid="dup")
    b = mem("y", cid="dup")
    with pytest.raises(perseus.PooledSelectionError):
        select([a, b], query="q", budget_tokens=100)


def test_pool_is_stable_sorted_for_identical_inputs():
    r1 = select([mem("b"), mem("a"), mem("c")], query="", budget_tokens=1000)
    r2 = select([mem("c"), mem("b"), mem("a")], query="", budget_tokens=1000)
    assert r1["pool"] == r2["pool"]
    assert r1["pool_digest"] == r2["pool_digest"]


def test_relevance_score_and_token_estimator():
    c = mem("deploy requires the active service account")
    assert relevance(c, "how do I deploy the stack") > 0.4
    assert relevance(c, "unrelated weather report") == 0.0
    assert relevance(c, "") == 0.0
    assert pool_tokens("") == 1
    assert pool_tokens("x" * 100) == 25


# ── Budget enforcement ────────────────────────────────────────────────────

def test_budget_is_hard_and_trace_explains_drops():
    a = mem("alpha " * 40, cid="a")
    b = mem("beta " * 40, cid="b")
    result = select([a, b], query="alpha beta", budget_tokens=80)
    assert result["tokens_used"] <= 80
    assert result["budget_remaining"] == 80 - result["tokens_used"]
    assert ids(result) == ["a"]  # beta dropped for budget
    dropped = [t for t in result["trace"] if "reason" in t]
    assert dropped and any("budget" in t["reason"] for t in dropped)
    result2 = select([a, b], query="alpha beta", budget_tokens=30)
    assert ids(result2) == []  # both oversized at this budget
    assert any("exceeds token budget" in t.get("reason", "")
               for t in result2["trace"])


def test_oversized_candidate_dropped_not_truncated():
    big = mem("x" * 500)
    small = mem("small")
    result = select([big, small], query="small", budget_tokens=100)
    assert ids(result) == [small.candidate_id]
    assert any("exceeds token budget" in t.get("reason", "")
               for t in result["trace"])


def test_zero_budget_selects_nothing_cleanly():
    result = select([mem("hello")], query="hello", budget_tokens=0)
    assert ids(result) == []
    assert result["objective"] == 0.0
    assert verify(result)["valid"]


def test_negative_budget_and_lambda_rejected():
    with pytest.raises(perseus.PooledSelectionError):
        select([mem("x")], query="x", budget_tokens=-1)
    with pytest.raises(perseus.PooledSelectionError):
        select([mem("x")], query="x", budget_tokens=10, lambda_coverage=-0.1)


def test_unknown_policy_rejected():
    with pytest.raises(perseus.UnknownPolicy):
        select([mem("x")], query="x", budget_tokens=10, policy="vibes")


# ── Submodular behavior: relevance + diminishing-returns coverage ─────────

def test_submodular_policy_keeps_old_but_relevant_memory():
    # An old memory entry (sequence 1) carries the answer; recent turns
    # (sequences 8, 9) are verbose but irrelevant.
    old_fact = mem("The service account id is svc-4471.", cid="old-fact")
    recent_noise_1 = turn("smalltalk about the weather and sports " * 6, seq=8)
    recent_noise_2 = turn("another irrelevant tangent about coffee " * 6, seq=9)
    query = "what is the service account id"
    result = select([old_fact, recent_noise_1, recent_noise_2],
                    query=query, budget_tokens=60)
    assert "old-fact" in ids(result)
    recency = select([old_fact, recent_noise_1, recent_noise_2],
                     query=query, budget_tokens=60, policy="recent_first")
    assert "old-fact" not in recency["kept_ids"]  # recency truncation loses it
    assert recency["kept_ids"]


def test_coverage_term_adds_diverse_sources():
    # Two candidates with equal relevance but disjoint vocabularies: the
    # coverage term prefers picking both (diminishing returns never make a
    # second pick worthless while it adds new tokens).
    a = mem("postgres database migration steps one two three", cid="a")
    b = mem("postgres database backup procedure four five six", cid="b")
    result = select([a, b], query="postgres database", budget_tokens=500)
    assert set(ids(result)) == {"a", "b"}
    # Marginal gains are non-increasing for identical-topic duplicates.
    c = mem("postgres database migration steps one two three", cid="c")
    dup_result = select([a, c], query="postgres database", budget_tokens=500)
    gains = [t["marginal_gain"] for t in dup_result["trace"] if "step" in t]
    assert gains[0] > gains[1]  # second pick adds only relevance, no coverage


def test_relevance_greedy_policy_ignores_coverage():
    a = mem("deploy stack alpha", cid="a")
    b = mem("deploy stack alpha", cid="b")  # duplicate content
    result = select([a, b], query="deploy stack",
                    budget_tokens=500, policy="relevance_greedy")
    # Pure relevance keeps both duplicates at identical gains.
    assert set(ids(result)) == {"a", "b"}
    gains = [t["marginal_gain"] for t in result["trace"] if "step" in t]
    assert gains[0] == gains[1]
    # Submodular policy keeps both too, but the second pick's gain is
    # strictly smaller: its coverage contribution is zero (no new tokens),
    # so only relevance remains — diminishing returns in action.
    sub = select([a, b], query="deploy stack", budget_tokens=500)
    sub_gains = [t["marginal_gain"] for t in sub["trace"] if "step" in t]
    assert set(ids(sub)) == {"a", "b"}
    assert sub_gains[0] > sub_gains[1]


def test_submodularity_marginal_gain_nonincreasing_property():
    # F(S) = relevance + relevance-weighted coverage is monotone
    # submodular: adding c to a smaller set yields a marginal gain >=
    # adding it to a larger set.
    c_new = mem("unique context tokens zebra yak antelope", cid="new")
    base_a = mem("shared context words", cid="a")
    base_b = mem("shared context words two", cid="b")
    only_a = select([base_a, c_new], query="context", budget_tokens=500)
    both = select([base_a, base_b, c_new], query="context", budget_tokens=500)
    gain_in_small = next(t["marginal_gain"] for t in only_a["trace"]
                         if t.get("candidate_id") == "new")
    gain_in_large = next(t["marginal_gain"] for t in both["trace"]
                         if t.get("candidate_id") == "new")
    assert gain_in_small >= gain_in_large


def test_zero_relevance_candidate_never_wins_on_coverage_alone():
    # Regression: a zero-relevance candidate with large distinct vocabulary
    # must never devour the budget via the coverage term.
    noise = mem("casual unrelated chatter about lunch plans " * 8,
                cid="noise")
    fact_c = mem("deploy takes --env staging", cid="fact")
    result = select([noise, fact_c], query="deploy flags",
                    budget_tokens=60)
    assert "fact" in ids(result)
    assert "noise" not in ids(result)
    # ... and the relevant fact is never displaced by noise under any order.
    result2 = select([fact_c, noise], query="deploy flags", budget_tokens=60)
    assert ids(result2) == ["fact"]


# ── Pluggability ──────────────────────────────────────────────────────────

def test_custom_policy_swaps_in_without_compiler_changes():
    calls = []

    def always_nothing(pool, query, budget_tokens, lambda_coverage):
        calls.append((query, budget_tokens, lambda_coverage))
        return [], [{"candidate_id": c.candidate_id, "kind": c.kind,
                     "reason": "policy deliberately keeps nothing"}
                    for c in pool]

    register("always_nothing", always_nothing)
    result = select([mem("data")], query="q", budget_tokens=100,
                    policy="always_nothing", lambda_coverage=0.1)
    assert ids(result) == []
    assert calls == [("q", 100, 0.1)]
    assert result["policy"] == "always_nothing"
    assert verify(result)["valid"]
    register("always_nothing", always_nothing)  # re-register to restore state


# ── Provenance and replay ─────────────────────────────────────────────────

def test_selection_result_verifies_and_is_replayable():
    pool = [mem("alpha beta gamma", cid="a"),
            mem("alpha delta", cid="b"),
            turn("noise " * 10, seq=3)]
    result = select(pool, query="alpha", budget_tokens=50,
                    created_by="test")
    assert result["schema_version"] == "perseus-pooled-selection/v1"
    assert result["token_accounting"] == perseus.POOLED_TOKEN_ACCOUNTING_NOTE
    check = verify(result)
    assert check["valid"], check["errors"]


def test_tampered_trace_fails_verification():
    pool = [mem("alpha beta", cid="a"), mem("gamma", cid="b")]
    result = select(pool, query="alpha gamma", budget_tokens=100)
    result["trace"][0]["marginal_gain"] = 999.0
    check = verify(result)
    assert check["valid"] is False
    assert any("trace" in e for e in check["errors"])


def test_tampered_pool_fails_verification():
    pool = [mem("alpha", cid="a")]
    result = select(pool, query="alpha", budget_tokens=100)
    result["pool"][0]["content"] = "tampered"
    check = verify(result)
    assert check["valid"] is False
    assert any("pool" in e for e in check["errors"])


def test_selection_is_deterministic():
    pool = [mem("alpha beta", cid="a"), mem("alpha", cid="b"),
            turn("noise " * 5, seq=1)]
    r1 = select(pool, query="alpha", budget_tokens=40)
    r2 = select(pool, query="alpha", budget_tokens=40)
    assert r1["selection_digest"] == r2["selection_digest"]
    assert r1["kept_ids"] == r2["kept_ids"]
    assert r1["trace"] == r2["trace"]


def test_verify_rejects_wrong_schema():
    assert verify({"schema_version": "other"})["valid"] is False


def test_objective_recomputed_from_trace():
    pool = [mem("alpha beta", cid="a")]
    result = select(pool, query="alpha", budget_tokens=100)
    assert result["objective"] >= relevance(pool[0], "alpha")
    result["objective"] += 1
    assert verify(result)["valid"] is False
