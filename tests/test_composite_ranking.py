"""test_composite_ranking.py — golden-vector tests for perseus#831.

Spec: docs/composite-retrieval-ranking.md §3 — the scoring function is pure
over (candidate features, weights) so these behaviors are pinned without a
database:

- exact/local facts outrank fuzzy semantic matches
- well-supported claims outrank one-offs (within a tier)
- verified outranks unverified
- fresh outranks stale
- weights are tunable without code changes
- disabled config is a byte-identical passthrough
"""

import importlib.util
import sys
import time
from pathlib import Path

# Load composite_ranking.py directly by path: the repo-root perseus.py
# artifact shadows the src/perseus package on sys.path under pytest, and
# this module is stdlib-only so direct loading is equivalent.
_CR_PATH = Path(__file__).resolve().parents[1] / "src" / "perseus" / "composite_ranking.py"
_spec = importlib.util.spec_from_file_location("composite_ranking", _CR_PATH)
composite_ranking = importlib.util.module_from_spec(_spec)
sys.modules["composite_ranking"] = composite_ranking  # dataclass annotation resolution
_spec.loader.exec_module(composite_ranking)

CompositeRankingConfig = composite_ranking.CompositeRankingConfig
DEFAULT_WEIGHTS = composite_ranking.DEFAULT_WEIGHTS
composite_rerank = composite_ranking.composite_rerank
composite_score = composite_ranking.composite_score

NOW_MS = int(time.time() * 1000)
DAY_MS = 86_400_000


class FakeLink:
    def __init__(self, relationship, target_id="t"):
        self.relationship = relationship
        self.target_id = target_id
        self.weight = 0.5


class FakeHit:
    def __init__(self, *, summary="", content="", key="", category="",
                 relevance=0.5, decay_score=1.0, workspace_hash="",
                 verified=False, links=None, age_days=0):
        self.summary = summary
        self.content = content
        self.key = key
        self.category = category
        self.relevance = relevance
        self.decay_score = decay_score
        self.workspace_hash = workspace_hash
        self.verified = verified
        self.links = links or []
        self.last_accessed_unix_ms = NOW_MS - int(age_days * DAY_MS)
        self.created_at_unix_ms = NOW_MS - int(age_days * DAY_MS)


def cfg(enabled=True, **weight_overrides):
    c = CompositeRankingConfig(enabled=enabled)
    c.weights.update(weight_overrides)
    return c


class TestGoldenVectors:
    def test_exact_local_beats_fuzzy_global(self):
        """Spec §2: an exact/local fact outranks a fuzzy semantic match."""
        local = FakeHit(summary="deploy procedure for plutus",
                        key="deploy-procedure", workspace_hash="ws-1",
                        relevance=0.4)
        fuzzy_global = FakeHit(summary="general infrastructure notes",
                               content="some plutus-adjacent rambling",
                               workspace_hash="", relevance=0.9)
        out = composite_rerank([fuzzy_global, local], "plutus deploy procedure",
                               "ws-1", cfg(), now_ms=NOW_MS)
        assert out[0] is local

    def test_supported_beats_one_off(self):
        """Spec §3: evidence strength ranks within a tier."""
        supported = FakeHit(summary="claim", relevance=0.5,
                            links=[FakeLink("evidence_for"),
                                   FakeLink("derived_from"),
                                   FakeLink("promoted_to")])
        one_off = FakeHit(summary="claim", relevance=0.5)
        out = composite_rerank([one_off, supported], "claim", None, cfg(),
                               now_ms=NOW_MS)
        assert out[0] is supported
        assert out[0].score_components["support"] == 1.0
        assert out[1].score_components["support"] == 0.0

    def test_verified_beats_unverified(self):
        verified = FakeHit(summary="fact", relevance=0.5, verified=True)
        unverified = FakeHit(summary="fact", relevance=0.5, verified=False)
        out = composite_rerank([unverified, verified], "fact", None, cfg(),
                               now_ms=NOW_MS)
        assert out[0] is verified

    def test_fresh_beats_stale(self):
        fresh = FakeHit(summary="status", relevance=0.5, age_days=1)
        stale = FakeHit(summary="status", relevance=0.5, age_days=300)
        out = composite_rerank([stale, fresh], "status", None, cfg(),
                               now_ms=NOW_MS)
        assert out[0] is fresh
        assert out[1].score_components["staleness"] > \
            out[0].score_components["staleness"]

    def test_identifier_terms_weighted_double(self):
        """Issue keys / PR numbers: exact identifier hits dominate."""
        exact = FakeHit(summary="fixed in perseus-vault#730", relevance=0.3)
        vague = FakeHit(summary="various vault updates and fixes and docs",
                        relevance=0.8)
        out = composite_rerank([vague, exact], "perseus-vault#730 status",
                               None, cfg(), now_ms=NOW_MS)
        assert out[0] is exact

    def test_weights_are_tunable(self):
        """Same vectors, different weights → different winner (spec §3)."""
        a = FakeHit(summary="alpha", relevance=0.9, decay_score=0.1)
        b = FakeHit(summary="beta", relevance=0.2, decay_score=1.0)
        sem_first = composite_rerank([b, a], "", None,
                                     cfg(semantic=2.0, freshness=0.0),
                                     now_ms=NOW_MS)
        assert sem_first[0] is a
        fresh_first = composite_rerank([a, b], "", None,
                                       cfg(semantic=0.0, freshness=2.0),
                                       now_ms=NOW_MS)
        assert fresh_first[0] is b

    def test_components_inspectable(self):
        h = FakeHit(summary="x", relevance=0.5)
        score, components = composite_score(h, "x", None, DEFAULT_WEIGHTS,
                                            now_ms=NOW_MS)
        assert isinstance(score, float)
        for name in ("lexical", "structural", "semantic", "freshness",
                     "support", "confidence", "staleness", "contradiction"):
            assert 0.0 <= components[name] <= 1.0, name

    def test_disabled_passthrough(self):
        hits = [FakeHit(summary="a"), FakeHit(summary="b")]
        out = composite_rerank(hits, "q", None, cfg(enabled=False))
        assert out is hits  # untouched, same object


class TestConfigParsing:
    def test_defaults(self):
        c = CompositeRankingConfig.from_dict(None)
        assert c.enabled is False
        assert c.weights == DEFAULT_WEIGHTS

    def test_from_dict(self):
        c = CompositeRankingConfig.from_dict(
            {"enabled": True, "weights": {"lexical": 2.5, "bogus": 9}})
        assert c.enabled is True
        assert c.weights["lexical"] == 2.5
        assert "bogus" not in c.weights
        # untouched weights keep spec defaults
        assert c.weights["contradiction"] == 1.2
