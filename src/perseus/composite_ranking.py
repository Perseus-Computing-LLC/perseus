"""composite_ranking.py — explicit composite retrieval ranking (perseus#831).

Spec: docs/composite-retrieval-ranking.md. Retrieval ranking is a composite,
inspectable policy rather than a single server-side signal:

    rank = w_lex·lexical + w_str·structural + w_sem·semantic
         + w_fresh·freshness + w_sup·support + w_conf·confidence
         − w_stale·staleness − w_contra·contradiction

Components the client cannot observe (server-side contradiction pairs) are
fixed at 0 and documented; everything else is computed from MemoryHit
fields already returned by the vault. Every re-ranked hit carries
`composite_score` and per-component `score_components` for debugging.

Off by default (`mneme.composite_ranking.enabled`); weights live in one
config block so ranking can be tuned without code changes.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

# Spec §4 starting defaults. Contradiction is the only component > 1.0: a
# live-contradicted memory should almost never outrank a clean one.
DEFAULT_WEIGHTS: dict[str, float] = {
    "lexical": 1.0,
    "structural": 0.8,
    "semantic": 1.0,
    "freshness": 0.6,
    "support": 0.5,
    "confidence": 0.4,
    "staleness": 0.7,
    "contradiction": 1.2,
}

# Link relationships counted as independent support (mirrors the vault
# belief overlay's evidence set).
EVIDENCE_RELS = frozenset({"evidence_for", "derived_from", "promoted_to"})

# Support is capped: 3+ independent supporters is maximal signal.
SUPPORT_SATURATION = 3

# Staleness horizon: a memory untouched for this many days is fully stale.
STALENESS_HORIZON_DAYS = 365.0

# Tokens with digits, symbols, or path/PR/KEY-123 shapes behave as
# identifiers: exact hits on them dominate the lexical component.
_IDENTIFIER_RE = re.compile(r"(?:[\w-]*\d[\w-]*|[^\w\s])")


@dataclass
class CompositeRankingConfig:
    """Tuning contract for composite ranking. One config block, no code
    changes required to re-tune (spec §3)."""

    enabled: bool = False
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    @classmethod
    def from_dict(cls, d: dict | None) -> "CompositeRankingConfig":
        if not isinstance(d, dict):
            return cls()
        cfg = cls(enabled=bool(d.get("enabled", False)))
        raw = d.get("weights") or {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in cfg.weights:
                    try:
                        cfg.weights[k] = float(v)
                    except (TypeError, ValueError):
                        pass
        return cfg


def _hit_text(hit: Any) -> str:
    return " ".join(
        str(p) for p in (
            getattr(hit, "summary", ""),
            getattr(hit, "content", ""),
            getattr(hit, "key", ""),
            getattr(hit, "category", ""),
        ) if p
    ).lower()


def _lexical(query: str, hit: Any) -> float:
    """Exact-term coverage of the query in the hit text, with identifier
    tokens (issue keys, PR numbers, paths) weighted double — when an
    identifier matters, exact hits must dominate (spec §1)."""
    terms = [t for t in re.split(r"\s+", (query or "").lower().strip()) if t]
    if not terms:
        return 0.5  # no query: neutral, semantic rank order decides
    text = _hit_text(hit)
    got = 0.0
    total = 0.0
    for t in terms:
        w = 2.0 if _IDENTIFIER_RE.search(t) else 1.0
        total += w
        if t in text:
            got += w
    return got / total if total else 0.0


def _structural(hit: Any, workspace_hash: str | None) -> float:
    """Scope proximity: same workspace > global > other (spec §1)."""
    scope = getattr(hit, "workspace_hash", "") or ""
    if workspace_hash:
        if scope == workspace_hash:
            return 1.0
        if scope == "":
            return 0.5
        return 0.0
    return 0.5  # unscoped caller: all scopes neutral


def _freshness(hit: Any) -> float:
    try:
        return max(0.0, min(1.0, float(getattr(hit, "decay_score", 1.0))))
    except (TypeError, ValueError):
        return 0.5


def _support(hit: Any) -> float:
    links = getattr(hit, "links", None) or []
    n = sum(1 for l in links if getattr(l, "relationship", "") in EVIDENCE_RELS)
    return min(1.0, n / SUPPORT_SATURATION)


def _confidence(hit: Any) -> float:
    return 1.0 if getattr(hit, "verified", False) else 0.5


def _staleness(hit: Any, now_ms: int) -> float:
    """Age past last revalidation, saturating at the horizon. Distinct from
    freshness (decay): a memory can resist decay via reinforcement yet still
    be old — the penalty reads last_accessed directly."""
    touched = getattr(hit, "last_accessed_unix_ms", None) or getattr(
        hit, "created_at_unix_ms", None)
    try:
        touched = int(touched)
    except (TypeError, ValueError):
        return 0.0
    age_days = max(0.0, (now_ms - touched) / 86_400_000.0)
    return min(1.0, age_days / STALENESS_HORIZON_DAYS)


def composite_score(
    hit: Any,
    query: str,
    workspace_hash: str | None,
    weights: dict[str, float],
    now_ms: int | None = None,
) -> tuple[float, dict[str, float]]:
    """Compute the composite score for one hit. Returns (score, components)
    with every component individually inspectable (spec §3)."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    try:
        semantic = max(0.0, min(1.0, float(getattr(hit, "relevance", 0.0))))
    except (TypeError, ValueError):
        semantic = 0.5
    components = {
        "lexical": _lexical(query, hit),
        "structural": _structural(hit, workspace_hash),
        "semantic": semantic,
        "freshness": _freshness(hit),
        "support": _support(hit),
        "confidence": _confidence(hit),
        "staleness": _staleness(hit, now_ms),
        # Not derivable client-side (server-side conflict pairs); fixed 0
        # per spec until the vault surfaces contradiction flags on recall.
        "contradiction": 0.0,
    }
    score = (
        weights["lexical"] * components["lexical"]
        + weights["structural"] * components["structural"]
        + weights["semantic"] * components["semantic"]
        + weights["freshness"] * components["freshness"]
        + weights["support"] * components["support"]
        + weights["confidence"] * components["confidence"]
        - weights["staleness"] * components["staleness"]
        - weights["contradiction"] * components["contradiction"]
    )
    return score, components


def composite_rerank(
    hits: list,
    query: str,
    workspace_hash: str | None,
    config: CompositeRankingConfig,
    now_ms: int | None = None,
) -> list:
    """Re-rank hits by composite score. Each returned hit is annotated with
    `composite_score` and `score_components`. Ties keep the server order
    (stable sort), so an all-equal score vector is byte-identical to the
    unranked list. No-op passthrough when disabled."""
    if not config.enabled or not hits:
        return hits
    scored = []
    for idx, hit in enumerate(hits):
        score, components = composite_score(
            hit, query, workspace_hash, config.weights, now_ms)
        hit.composite_score = round(score, 4)
        hit.score_components = components
        scored.append((idx, score, hit))
    scored.sort(key=lambda t: (-t[1], t[0]))
    return [h for _, _, h in scored]
