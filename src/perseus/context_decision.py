"""Deterministic, visibility-safe context routing decisions (#890).

This is policy accounting, not a provider-billing claim. Token values come from
Perseus render metering and must be labeled estimates unless separately matched
to provider usage telemetry.
"""

from __future__ import annotations

from typing import Any

_CONTEXT_ROUTES = {"inline", "reduced_text", "artifact_pointer", "retrieve_on_demand"}
_CONTEXT_FIDELITIES = {"exact", "selective", "summary"}
_CONTEXT_CACHE = {"warm", "cold", "unknown"}


def _ctx_safe_source_refs(source_refs: Any) -> list[str]:
    """Return deterministic public-safe refs; never emit arbitrary metadata."""
    if not isinstance(source_refs, (list, tuple)):
        return []
    allowed = ("file:", "vault:", "artifact:")
    return sorted({str(ref) for ref in source_refs
                   if isinstance(ref, str) and ref.startswith(allowed)})


def decide_context_route(*, actual_tokens: int, counterfactual_tokens: int,
                         fidelity: str = "exact", cache_assumption: str = "unknown",
                         source_refs: Any = None, declared_budget: int | None = None,
                         requires_exact: bool = False, contains_sensitive_data: bool = False,
                         artifact_available: bool = False, retrieval_available: bool = False,
                         reduction_available: bool = False) -> dict:
    """Choose a deterministic representation without transforming user content.

    ``actual_tokens`` is the rendered representation under consideration;
    ``counterfactual_tokens`` is the defined full-inline baseline. Neither is a
    provider-billed saving. Callers are responsible for attaching observed
    provider usage separately.
    """
    actual = max(0, int(actual_tokens))
    counterfactual = max(0, int(counterfactual_tokens))
    fidelity = fidelity if fidelity in _CONTEXT_FIDELITIES else "exact"
    cache = cache_assumption if cache_assumption in _CONTEXT_CACHE else "unknown"
    refs = _ctx_safe_source_refs(source_refs)

    if declared_budget is not None and actual > int(declared_budget):
        route, reason = "retrieve_on_demand", "declared budget rejects inline representation"
    elif contains_sensitive_data:
        route, reason = "retrieve_on_demand", "sensitive content requires explicit retrieval under policy"
    elif requires_exact or fidelity == "exact":
        if artifact_available and retrieval_available and counterfactual > actual:
            route, reason = "artifact_pointer", "exactness preserves source bytes behind a retrievable artifact pointer"
        else:
            route, reason = "inline", "exactness requirement rejects lossy reduction"
    elif cache == "warm" and actual <= counterfactual:
        route, reason = "inline", "warm cached content is no more expensive than transformation or retrieval"
    elif reduction_available and actual < counterfactual:
        route, reason = "reduced_text", "deterministic reduced representation fits the declared fidelity"
    elif artifact_available and retrieval_available:
        route, reason = "retrieve_on_demand", "artifact is available for bounded retrieval when needed"
    else:
        route, reason = "inline", "no safe lower-fidelity or retrieval representation is available"

    return {
        "route": route,
        "reason": reason,
        "fidelity": fidelity,
        "actual_tokens": actual,
        "counterfactual_tokens": counterfactual,
        "cache_assumption": cache,
        "source_refs": refs,
        "token_accounting": "rendered token accounting; not provider-billed savings",
    }


def decision_from_prompt_size(report: dict, **policy: Any) -> dict:
    """Build a decision from existing prompt-size output without replacing it."""
    total = (report or {}).get("total") or {}
    actual = int(total.get("tokens", 0) or 0)
    counterfactual = int(policy.pop("counterfactual_tokens", actual) or 0)
    return decide_context_route(actual_tokens=actual,
                                counterfactual_tokens=counterfactual,
                                **policy)
