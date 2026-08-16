"""Pluggable submodular context-selection engine over the pooled context (#970).

Replaces topic-blind recency truncation with a pluggable selection engine
that treats conversation turns, memory entries, and tool outputs as one
pooled candidate set and selects by a submodular objective — relevance +
coverage under a token budget, with diminishing returns — at
prompt-assembly time. PACMS borrow (arXiv:2606.20047): neither RAG (external
docs only) nor lossy compression (query-blind) arbitrates the agent's
already-present pooled context; the selector does.

Design constraints (matches the sibling context modules):

* **Deterministic and stdlib-only.** Candidate normalization, relevance
  scoring, and greedy selection are pure functions of the pooled candidates
  plus the current query. Tie-breaking is stable (candidate id), so the same
  pool + query + budget always selects the same set, byte-for-byte.
* **Pluggable policy registry.** The engine ships three policies —
  ``submodular_greedy`` (relevance + diminishing-returns coverage, the
  default), ``relevance_greedy`` (relevance only, no coverage term), and
  ``recent_first`` (the recency-truncation baseline this engine replaces) —
  and ``register_policy`` lets future policies (e.g. causal-evidence-
  supervised pruning, arXiv:2607.21692) swap in with zero compiler changes.
* **Replay-first provenance.** Every selection emits a digest-sealed trace:
  what was kept/dropped, the marginal gain of each pick, the objective value,
  and the budget ledger. ``verify_selection_trace`` recomputes every entry —
  the trace feeds the #962 auditable DAG and efficiency-frontier analysis.
* **Fail-closed budgets.** The budget is a hard cap on rendered tokens;
  selection never exceeds it. Candidates individually over budget are dropped
  with an explicit reason, never silently truncated.

Objective: ``F(S) = sum(relevance(c) for c in S)
+ lambda * sum(relevance(c) * |new_tokens(c)| for c in S)`` — coverage
contributions are weighted by the candidate's own relevance, so a
zero-relevance candidate can never be picked on coverage alone. The weighted
coverage term is monotone submodular with diminishing returns, so the greedy
policy carries the classic (1-1/e) guarantee for the unit-cost case; the
budgeted (knapsack) variant is documented as an approximation.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

CANDIDATE_KINDS = frozenset({"session_turn", "memory_entry", "tool_output"})
POOLED_TOKEN_ACCOUNTING_NOTE = "rendered token accounting; not provider-billed savings"
DEFAULT_LAMBDA_COVERAGE = 0.5


# ── Errors ─────────────────────────────────────────────────────────────────

class PooledSelectionError(ValueError):
    """Base error for pooled-selection construction or verification."""


class UnknownPolicy(PooledSelectionError):
    """A selection policy was requested that is not registered."""


# ── Deterministic helpers ─────────────────────────────────────────────────

def _psha(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def _pjson(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def pool_tokens(text: str) -> int:
    """Deterministic rendered-token estimate (chars//4, ceil). Same convention
    as ``dag_tokens`` — an estimate for budget accounting, never billed."""
    return max(1, (len(text or "") + 3) // 4)


_pool_token_re = re.compile(r"[a-z0-9_@./-]{3,}")
_STOPWORDS = frozenset("""
the for and that this with from your you are was were have has had but nor its
his her our their they them she he him we us it all any can could should would
will may might must shall does do did not no dont never is be been being to of
in on at by an a or as if then than so into about over after before what which
who whom when where why how use there here i me my
""".split())


def _ptokens(text: str) -> set[str]:
    out: set[str] = set()
    for m in _pool_token_re.findall((text or "").lower()):
        cleaned = m.strip("./-")
        if len(cleaned) >= 3 and cleaned not in _STOPWORDS:
            out.add(cleaned)
    return out


def _p_shingles(tok: str) -> frozenset[str]:
    t = "^" + tok + "$"
    return frozenset(t[i:i + 3] for i in range(len(t) - 2))


def _p_soft_match(a: str, b: str) -> bool:
    if a == b:
        return True
    sa, sb = _p_shingles(a), _p_shingles(b)
    if not sa or not sb:
        return False
    return len(sa & sb) / len(sa | sb) >= 0.5


def _p_soft_overlap(a: set[str], b: set[str]) -> set[str]:
    bl = sorted(b)
    return {t for t in a if any(_p_soft_match(t, u) for u in bl)}


# ── Pooled candidates ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PooledCandidate:
    """One unit of the pooled candidate set: a session turn, a memory-store
    entry, or a tool output. ``candidate_id`` defaults to a content-derived
    ID so identical content always pools to the same candidate."""

    kind: str
    content: str
    candidate_id: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in CANDIDATE_KINDS:
            raise PooledSelectionError(f"unknown candidate kind: {self.kind!r}")
        if not self.candidate_id:
            object.__setattr__(
                self, "candidate_id",
                _psha(self.kind, self.content, _pjson(self.meta))[:16])

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "content": self.content,
            "meta": dict(self.meta),
        }


def _norm_pool(candidates: Iterable[dict | PooledCandidate]) -> list[PooledCandidate]:
    out: list[PooledCandidate] = []
    seen: set[str] = set()
    for c in candidates:
        if isinstance(c, PooledCandidate):
            cand = c
        elif isinstance(c, dict):
            cand = PooledCandidate(
                kind=str(c.get("kind", "")),
                content=str(c.get("content", "")),
                candidate_id=str(c.get("candidate_id", "")),
                meta=dict(c.get("meta") or {}),
            )
        else:
            raise PooledSelectionError(f"invalid pooled candidate: {c!r}")
        if cand.candidate_id in seen:
            raise PooledSelectionError(
                f"duplicate candidate id: {cand.candidate_id!r}")
        seen.add(cand.candidate_id)
        out.append(cand)
    # Stable, deterministic order for identical pools.
    out.sort(key=lambda c: c.candidate_id)
    return out


def relevance_score(candidate: PooledCandidate | dict, query: str) -> float:
    """Deterministic lexical relevance: fraction of the candidate's content
    tokens that overlap (stem-tolerant) the query tokens. 0.0 when there is
    no query."""
    cand = candidate if isinstance(candidate, PooledCandidate) \
        else PooledCandidate(**{k: v for k, v in candidate.items()
                                if k in ("kind", "content", "candidate_id",
                                         "meta")})
    if not (query or "").strip():
        return 0.0
    cand_tokens = _ptokens(cand.content)
    if not cand_tokens:
        return 0.0
    query_tokens = _ptokens(query)
    if not query_tokens:
        return 0.0
    denominator = min(len(cand_tokens), len(query_tokens))
    return round(len(_p_soft_overlap(cand_tokens, query_tokens)) / denominator, 4)


# ── Policies ──────────────────────────────────────────────────────────────

def _policy_submodular_greedy(pool: list[PooledCandidate],
                              query: str,
                              budget_tokens: int,
                              lambda_coverage: float) -> tuple[list[PooledCandidate], list[dict]]:
    """Greedy maximization of F(S) = relevance + lambda * coverage.

    Lazy-greedy with stable tie-breaking: at each step, pick the candidate
    with the highest marginal gain per remaining budget step; ties break on
    candidate id so the run is deterministic. Coverage gain is the number of
    NEW distinct content tokens the candidate adds to the selected set.
    """
    rel = {c.candidate_id: relevance_score(c, query) for c in pool}
    remaining = [c for c in pool if pool_tokens(c.content) <= budget_tokens]
    skipped_over = [c for c in pool
                    if pool_tokens(c.content) > budget_tokens]
    trace: list[dict] = []
    kept: list[PooledCandidate] = []
    covered: set[str] = set()
    budget_left = budget_tokens
    objective = 0.0

    while remaining:
        best: Optional[PooledCandidate] = None
        best_gain = -1.0
        best_new: set[str] = set()
        for cand in remaining:
            if pool_tokens(cand.content) > budget_left:
                continue
            new = _ptokens(cand.content) - covered
            # Coverage is weighted by the candidate's own relevance:
            # irrelevant candidates contribute nothing to the objective.
            gain = (rel[cand.candidate_id]
                    + lambda_coverage * rel[cand.candidate_id] * len(new))
            if gain > best_gain or (gain == best_gain and best is not None
                                    and cand.candidate_id < best.candidate_id):
                best_gain, best, best_new = gain, cand, new
        if best is None or best_gain <= 0:
            break
        kept.append(best)
        remaining.remove(best)
        covered |= best_new
        budget_left -= pool_tokens(best.content)
        objective += best_gain
        trace.append({
            "step": len(trace) + 1,
            "candidate_id": best.candidate_id,
            "kind": best.kind,
            "relevance": rel[best.candidate_id],
            "coverage_gain": len(best_new),
            "marginal_gain": round(best_gain, 4),
            "tokens_used": pool_tokens(best.content),
            "budget_remaining": budget_left,
        })
    reasons: list[dict] = []
    for cand in remaining:
        if pool_tokens(cand.content) > budget_left:
            reasons.append({"candidate_id": cand.candidate_id, "kind": cand.kind,
                            "reason": "insufficient remaining budget"})
        else:
            reasons.append({"candidate_id": cand.candidate_id, "kind": cand.kind,
                            "reason": "objective gain <= 0 (irrelevant or fully covered)"})
    for cand in skipped_over:
        reasons.append({"candidate_id": cand.candidate_id, "kind": cand.kind,
                        "reason": "candidate exceeds token budget"})
    return kept, trace + reasons


def _policy_relevance_greedy(pool: list[PooledCandidate],
                             query: str,
                             budget_tokens: int,
                             lambda_coverage: float) -> tuple[list[PooledCandidate], list[dict]]:
    """Relevance-only greedy (no coverage term): the submodular objective
    with lambda = 0. Useful as an ablation policy."""
    del lambda_coverage
    rel = sorted(((relevance_score(c, query), c) for c in pool),
                 key=lambda rc: (-rc[0], rc[1].candidate_id))
    kept: list[PooledCandidate] = []
    trace: list[dict] = []
    budget_left = budget_tokens
    for score, cand in rel:
        if score <= 0:
            trace.append({"candidate_id": cand.candidate_id, "kind": cand.kind,
                          "reason": "objective gain <= 0 (irrelevant or fully covered)"})
            continue
        cost = pool_tokens(cand.content)
        if cost > budget_left:
            trace.append({"candidate_id": cand.candidate_id, "kind": cand.kind,
                          "reason": "insufficient remaining budget"})
            continue
        kept.append(cand)
        budget_left -= cost
        trace.append({
            "step": len(trace) + 1,
            "candidate_id": cand.candidate_id,
            "kind": cand.kind,
            "relevance": score,
            "coverage_gain": len(_ptokens(cand.content)),
            "marginal_gain": round(score, 4),
            "tokens_used": cost,
            "budget_remaining": budget_left,
        })
    return kept, trace


def _policy_recent_first(pool: list[PooledCandidate],
                         query: str,
                         budget_tokens: int,
                         lambda_coverage: float) -> tuple[list[PooledCandidate], list[dict]]:
    """Recency truncation baseline: newest candidates first, until budget.

    Order comes from ``meta.sequence`` (largest = most recent); candidates
    without a sequence sort last. This is the policy PACMS replaces."""
    del query, lambda_coverage

    def seq(c: PooledCandidate) -> float:
        try:
            return float(c.meta.get("sequence", 0.0))
        except (TypeError, ValueError):
            return 0.0

    ordered = sorted(pool, key=lambda c: (-seq(c), c.candidate_id))
    kept: list[PooledCandidate] = []
    trace: list[dict] = []
    budget_left = budget_tokens
    for cand in ordered:
        cost = pool_tokens(cand.content)
        if cost > budget_left:
            trace.append({"candidate_id": cand.candidate_id, "kind": cand.kind,
                          "reason": "insufficient remaining budget"})
            continue
        kept.append(cand)
        budget_left -= cost
        trace.append({
            "step": len(trace) + 1,
            "candidate_id": cand.candidate_id,
            "kind": cand.kind,
            "relevance": relevance_score(cand, ""),
            "coverage_gain": len(_ptokens(cand.content)),
            "marginal_gain": 0.0,
            "tokens_used": cost,
            "budget_remaining": budget_left,
        })
    return kept, trace


_POLICIES: dict[str, Callable] = {
    "submodular_greedy": _policy_submodular_greedy,
    "relevance_greedy": _policy_relevance_greedy,
    "recent_first": _policy_recent_first,
}


def register_policy(name: str, policy: Callable) -> None:
    """Register a custom selection policy (e.g. causal-evidence-supervised
    pruning). ``policy`` must be a pure function
    ``(pool, query, budget_tokens, lambda_coverage) -> (kept, trace)``."""
    if not isinstance(name, str) or not name.strip():
        raise PooledSelectionError("policy name must be a non-empty string")
    if not callable(policy):
        raise PooledSelectionError("policy must be callable")
    _POLICIES[name.strip()] = policy


# ── Selection ─────────────────────────────────────────────────────────────

def select_pooled_context(
    candidates: Iterable[dict | PooledCandidate],
    *,
    query: str,
    budget_tokens: int,
    policy: str = "submodular_greedy",
    lambda_coverage: float = DEFAULT_LAMBDA_COVERAGE,
    created_by: str = "",
    meta: Optional[dict] = None,
) -> dict:
    """Select the budgeted context subset from the pooled candidate set.

    Returns a digest-sealed selection result: kept candidates (in pick
    order), a trace of kept/dropped with reasons and marginal gains, the
    objective value, and the budget ledger. ``verify_selection_trace``
    replays the selection deterministically.
    """
    if budget_tokens < 0:
        raise PooledSelectionError("budget_tokens must be >= 0")
    if lambda_coverage < 0:
        raise PooledSelectionError("lambda_coverage must be >= 0")
    if policy not in _POLICIES:
        raise UnknownPolicy(f"unknown selection policy: {policy!r} "
                            f"(registered: {sorted(_POLICIES)})")
    pool = _norm_pool(candidates)
    kept, trace = _POLICIES[policy](pool, query, budget_tokens,
                                    lambda_coverage)
    kept_ids = [c.candidate_id for c in kept]
    used = sum(pool_tokens(c.content) for c in kept)
    if used > budget_tokens:  # hard budget, fail closed — never truncate
        raise PooledSelectionError(
            f"policy {policy!r} violated the token budget: {used} > {budget_tokens}")
    objective = round(
        sum(t["marginal_gain"] for t in trace if "step" in t), 4)
    result = {
        "schema_version": "perseus-pooled-selection/v1",
        "created_by": created_by,
        "meta": dict(meta or {}),
        "policy": policy,
        "lambda_coverage": lambda_coverage,
        "query": query,
        "budget_tokens": budget_tokens,
        "pool": [c.to_dict() for c in pool],
        "pool_digest": _psha(*[_pjson(c.to_dict()) for c in pool]),
        "kept_ids": kept_ids,
        "kept": [c.to_dict() for c in kept],
        "trace": trace,
        "tokens_used": used,
        "budget_remaining": budget_tokens - used,
        "objective": objective,
        "token_accounting": POOLED_TOKEN_ACCOUNTING_NOTE,
        "generated_at_unix_s": round(time.time(), 3),
    }
    result["selection_digest"] = _psha(
        "pool", result["pool_digest"],
        "policy", policy,
        "lambda", lambda_coverage,
        "query", query,
        "budget", budget_tokens,
        "kept", _pjson(kept_ids),
        "trace", _pjson(trace),
        "objective", objective)
    return result


def verify_selection_trace(result: dict) -> dict:
    """Replay a selection result and recompute every commitment."""
    errors: list[str] = []
    if not isinstance(result, dict):
        return {"valid": False, "errors": ["result is not an object"]}
    if result.get("schema_version") != "perseus-pooled-selection/v1":
        return {"valid": False, "errors": ["unsupported schema version"]}
    try:
        pool = _norm_pool(result.get("pool") or [])
    except PooledSelectionError as exc:
        return {"valid": False, "errors": [f"pool invalid: {exc}"]}
    expected_digest = _psha(*[_pjson(c.to_dict()) for c in pool])
    if expected_digest != result.get("pool_digest"):
        errors.append("pool_digest mismatch")
    policy = result.get("policy", "")
    if policy not in _POLICIES:
        errors.append(f"unknown policy: {policy!r}")
    else:
        try:
            kept, trace = _POLICIES[policy](
                pool, result.get("query", ""),
                int(result.get("budget_tokens", 0)),
                float(result.get("lambda_coverage", DEFAULT_LAMBDA_COVERAGE)))
        except Exception as exc:
            return {"valid": False, "errors": [f"replay failed: {exc}"]}
        if [c.candidate_id for c in kept] != result.get("kept_ids"):
            errors.append("kept set does not recompute under the policy")
        if trace != result.get("trace"):
            errors.append("trace does not recompute under the policy")
        used = sum(pool_tokens(c.content) for c in kept)
        if used > int(result.get("budget_tokens", 0)):
            errors.append("budget exceeded")
        if used != result.get("tokens_used"):
            errors.append("tokens_used mismatch")
        objective = round(
            sum(t["marginal_gain"] for t in trace if "step" in t), 4)
        if objective != result.get("objective"):
            errors.append("objective does not recompute")
    expected = _psha(
        "pool", result.get("pool_digest"),
        "policy", result.get("policy"),
        "lambda", result.get("lambda_coverage"),
        "query", result.get("query"),
        "budget", result.get("budget_tokens"),
        "kept", _pjson(result.get("kept_ids")),
        "trace", _pjson(result.get("trace")),
        "objective", result.get("objective"))
    if expected != result.get("selection_digest"):
        errors.append("selection_digest mismatch")
    return {"valid": not errors, "errors": errors}


__all__ = [
    "CANDIDATE_KINDS", "POOLED_TOKEN_ACCOUNTING_NOTE", "DEFAULT_LAMBDA_COVERAGE",
    "PooledSelectionError", "UnknownPolicy", "PooledCandidate",
    "pool_tokens", "relevance_score", "register_policy",
    "select_pooled_context", "verify_selection_trace",
]


# Keep the source module importable from the generated single-file artifact.

def _pooled_selection_module_exports() -> tuple[str, ...]:
    return tuple(__all__)
