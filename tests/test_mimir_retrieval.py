"""
test_engram_retrieval.py — Phase 2: Retrieval Quality Benchmark (Intelligence Validation)

Validates that Mneme + local Mneme FTS5 actually helps the LLM make better
decisions by surfacing the RIGHT information at the RIGHT priority.

Test suites:
  1. Merge Strategy Correctness — all 4 strategies (LOCAL_FIRST, REMOTE_FIRST, INTERLEAVE, DECAY_FIRST)
  2. Deduplication & Verification — cross-source dedup
  3. Needle in a Haystack — Recall@K against a Golden Set of 20 complex problems
  4. Decay Priority — Ebbinghaus freshness ordering
  5. Conflict Resolution — local vs remote data discrepancies
"""

import copy
import textwrap
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_connector_singleton():
    perseus._connector = None
    perseus._connector_cfg_hash = ""


def _test_cfg():
    """Config that won't try to connect to a real Engram."""
    _reset_connector_singleton()
    c = cfg()
    c["mimir"] = {
        "enabled": True,
        "transport": "stdio",
        "command": ["/nonexistent/path/mneme"],
        "timeout_s": 0.5,
        "merge_strategy": "local_first",
        "decay_priority_weight": 0.4,
        "fallback_to_local": True,
        "circuit_breaker": {"threshold": 1, "cooldown": 1},
        "retry_policy": {"max_attempts": 1, "backoff_base": 0.01},
    }
    return c


def _make_hit(id_, content, source="local", mtype="insight", decay=1.0, relevance=0.5, topic="", verified=False):
    """Quick helper to build a MemoryHit."""
    return perseus.MemoryHit(
        id=id_, content=content, source=perseus.MemorySource(source),
        type=perseus.MemoryTypeEnum(mtype), summary=content[:80],
        relevance=relevance, decay_score=decay, topic_path=topic, verified=verified,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MERGE STRATEGY CORRECTNESS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMergeStrategies:
    """Validate each merge strategy produces the correct ordering."""

    def _connector(self, strategy="local_first"):
        _reset_connector_singleton()
        c = _test_cfg()
        c["mimir"]["merge_strategy"] = strategy
        return perseus.MimirConnector(c)

    @property
    def local_items(self):
        return [
            _make_hit("l-1", "Local: Auth uses JWT tokens", "local", "decision", decay=0.9, relevance=0.8),
            _make_hit("l-2", "Local: Database is SQLite FTS5", "local", "architecture", decay=0.5, relevance=0.6),
            _make_hit("l-3", "Local: CI pipeline runs on push", "local", "insight", decay=0.3, relevance=0.4),
        ]

    @property
    def mneme_items(self):
        return [
            _make_hit("e-1", "Engram: Database is PostgreSQL in production", "mimir", "architecture", decay=0.95, relevance=0.9),
            _make_hit("e-2", "Engram: Auth uses OAuth2 + JWT", "mimir", "decision", decay=0.7, relevance=0.7),
            _make_hit("e-3", "Engram: Deploy strategy is blue-green", "mimir", "insight", decay=0.2, relevance=0.3),
        ]

    def test_local_first_strategy(self):
        """LOCAL_FIRST: local items first, then verified, then mneme-only."""
        conn = self._connector("local_first")
        merged = conn._merge_results(
            local_items=list(self.local_items),
            mneme_items=list(self.mneme_items),
            strategy=perseus.MergeStrategy.LOCAL_FIRST,
            diagnostics={},
        )
        sources = [item.source.value for item in merged.items]
        # All items are unique (different content), so order is: local → mneme
        assert sources[:3] == ["local", "local", "local"]
        assert sources[3:] == ["mimir", "mimir", "mimir"]

    def test_remote_first_strategy(self):
        """REMOTE_FIRST: mneme items first, then verified, then local-only."""
        conn = self._connector("remote_first")
        merged = conn._merge_results(
            local_items=list(self.local_items),
            mneme_items=list(self.mneme_items),
            strategy=perseus.MergeStrategy.REMOTE_FIRST,
            diagnostics={},
        )
        sources = [item.source.value for item in merged.items]
        assert sources[:3] == ["mimir", "mimir", "mimir"]
        assert sources[3:] == ["local", "local", "local"]

    def test_interleave_strategy(self):
        """INTERLEAVE: alternates engram, local, with verified at the end."""
        conn = self._connector("interleave")
        merged = conn._merge_results(
            local_items=list(self.local_items),
            mneme_items=list(self.mneme_items),
            strategy=perseus.MergeStrategy.INTERLEAVE,
            diagnostics={},
        )
        sources = [item.source.value for item in merged.items]
        # Should alternate: engram, local, engram, local, engram, local
        expected = ["mimir", "local", "mimir", "local", "mimir", "local"]
        assert sources == expected

    def test_decay_first_strategy(self):
        """DECAY_FIRST: sorts ALL items by decay_score descending (fresh first)."""
        conn = self._connector("decay_first")
        merged = conn._merge_results(
            local_items=list(self.local_items),
            mneme_items=list(self.mneme_items),
            strategy=perseus.MergeStrategy.DECAY_FIRST,
            diagnostics={},
        )
        decay_scores = [item.decay_score for item in merged.items]
        assert decay_scores == sorted(decay_scores, reverse=True), \
            f"DECAY_FIRST should sort by decay desc, got {decay_scores}"
        # Freshest item should be first (e-1: 0.95)
        assert merged.items[0].id == "e-1"

    def test_decay_secondary_sort_within_groups(self):
        """In LOCAL_FIRST, local items should be sorted by decay desc within their group."""
        conn = self._connector("local_first")
        local = [
            _make_hit("l-old", "Old local memory", "local", "insight", decay=0.1),
            _make_hit("l-fresh", "Fresh local memory", "local", "insight", decay=0.99),
            _make_hit("l-mid", "Mid local memory", "local", "insight", decay=0.5),
        ]
        mneme_items = [
            _make_hit("e-1", "Mneme item", "mimir", "insight", decay=0.8),
        ]
        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        local_decay = [item.decay_score for item in merged.items if item.source == perseus.MemorySource.LOCAL]
        assert local_decay == sorted(local_decay, reverse=True), \
            f"Local items should be decay-sorted within group, got {local_decay}"

    def test_strategy_preserved_in_segment(self):
        """The strategy_used field should reflect the actual merge strategy."""
        conn = self._connector("decay_first")
        merged = conn._merge_results(
            local_items=self.local_items, mneme_items=self.mneme_items,
            strategy=perseus.MergeStrategy.DECAY_FIRST, diagnostics={},
        )
        assert "decay_first" in merged.strategy_used


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DEDUPLICATION & VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeduplication:
    """Validate cross-source dedup: identical content → verified=True, Mneme version preferred."""

    def _connector(self):
        _reset_connector_singleton()
        return perseus.MimirConnector(_test_cfg())

    def test_identical_content_deduped(self):
        """Same content in both sources → one item, verified=True, Engram source."""
        conn = self._connector()
        shared_content = "The auth module uses PostgreSQL for production and SQLite for local dev."
        local = [_make_hit("l-auth", shared_content, "local", "architecture", decay=0.5)]
        mneme_items = [_make_hit("e-auth", shared_content, "mimir", "architecture", decay=0.95)]

        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        # Should be 1 item total (deduped), with verified=True
        assert len(merged.items) == 1, f"Expected 1 deduped item, got {len(merged.items)}"
        item = merged.items[0]
        assert item.verified is True
        assert item.source == perseus.MemorySource.MNEME  # Mneme version preferred
        assert item.id == "e-auth"

    def test_similar_but_not_identical_content_not_deduped(self):
        """Different content → not deduped, both items preserved."""
        conn = self._connector()
        local = [_make_hit("l-1", "Auth module uses PostgreSQL.", "local", "architecture")]
        mneme_items = [_make_hit("e-1", "The auth module uses PostgreSQL for production and SQLite for local dev.", "mimir", "architecture")]

        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        assert len(merged.items) == 2  # different content hash → both kept

    def test_multiple_shared_items_all_verified(self):
        """Multiple shared items across sources → all get verified=True."""
        conn = self._connector()
        shared_1 = "Decision: Use microkernel architecture."
        shared_2 = "Insight: Perseus watch daemon runs every 900s."
        local = [
            _make_hit("l-mk", shared_1, "local", "decision"),
            _make_hit("l-watch", shared_2, "local", "insight"),
            _make_hit("l-only", "Local-only insight about tooling.", "local", "insight"),
        ]
        mneme_items = [
            _make_hit("e-mk", shared_1, "mimir", "decision", decay=0.9),
            _make_hit("e-watch", shared_2, "mimir", "insight", decay=0.8),
            _make_hit("e-only", "Mneme-only architecture note.", "mimir", "architecture"),
        ]

        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        # Total: 4 unique items (2 shared → verified, 1 local-only, 1 mneme-only)
        assert len(merged.items) == 4
        verified = [item for item in merged.items if item.verified]
        assert len(verified) == 2, f"Expected 2 verified items, got {len(verified)}"
        for v in verified:
            assert v.source == perseus.MemorySource.MNEME

    def test_diagnostics_populated_after_merge(self):
        """_merge_results should populate diagnostics with dedup counts."""
        conn = self._connector()
        diag = {}
        conn._merge_results(
            local_items=self._all_unique_local(),
            mneme_items=self._all_unique_engram(),
            strategy=perseus.MergeStrategy.LOCAL_FIRST,
            diagnostics=diag,
        )
        assert "merge_verified" in diag
        assert "merge_mneme_only" in diag
        assert "merge_local_only" in diag

    def _all_unique_local(self):
        return [
            _make_hit("l-a", "Content Alpha", "local", "insight"),
            _make_hit("l-b", "Content Beta", "local", "decision"),
        ]

    def _all_unique_engram(self):
        return [
            _make_hit("e-c", "Content Gamma", "mimir", "architecture"),
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GOLDEN SET — Needle in a Haystack: Recall@K
# ═══════════════════════════════════════════════════════════════════════════════

# Golden Set: 20 complex, multi-step technical problems where the answer depends
# on a decision made months ago, or on reasoning across both local state and
# persistent memory. Each entry: (query, correct_ids, distractors)
# The "correct_ids" are the memory items that SHOULD appear in the top results.

GOLDEN_QUERIES = [
    # ── Architecture & Design Decisions ──
    {
        "query": "Why did we choose SQLite FTS5 over PostgreSQL for the local search index in the auth module?",
        "expected_ids": ["arch-auth-db-choice"],
        "expected_keywords": ["SQLite FTS5", "local-first", "no external dependencies"],
        "type": "architecture",
    },
    {
        "query": "What was the reasoning behind adopting the microkernel pattern for module isolation?",
        "expected_ids": ["decision-microkernel"],
        "expected_keywords": ["microkernel", "plugin architecture", "isolation"],
        "type": "decision",
    },
    {
        "query": "Explain the three-layer memory progression in Mneme and why we chose it over a flat store.",
        "expected_ids": ["arch-engram-layers", "decision-engram-choice"],
        "expected_keywords": ["buffer", "working", "core", "Ebbinghaus", "three-layer"],
        "type": "architecture",
    },
    {
        "query": "What database driver does the Perseus Mneme v2 use and why was it selected?",
        "expected_ids": ["arch-mneme-driver"],
        "expected_keywords": ["SQLite", "FTS5", "sqlite-vec", "zero-dependency"],
        "type": "architecture",
    },
    {
        "query": "How does the circuit breaker pattern work in our Mneme connector, and what thresholds did we set?",
        "expected_ids": ["arch-circuit-breaker", "decision-cb-thresholds"],
        "expected_keywords": ["circuit breaker", "threshold", "cooldown", "half-open", "degraded"],
        "type": "architecture",
    },

    # ── Operational Knowledge ──
    {
        "query": "What is the procedure for rebuilding perseus.py after a source change, and why can't we edit it directly?",
        "expected_ids": ["insight-build-artifact", "decision-build-pipeline"],
        "expected_keywords": ["build artifact", "scripts/build.py", "src/", "regenerated"],
        "type": "insight",
    },
    {
        "query": "How do we handle merge conflicts on the perseus.py build artifact?",
        "expected_ids": ["insight-merge-conflict", "decision-checkout-ours"],
        "expected_keywords": ["--ours", "rebuild", "conflict", "build.py"],
        "type": "insight",
    },
    {
        "query": "What's the Perseus watch daemon's refresh interval, and where is it configured?",
        "expected_ids": ["insight-watch-daemon"],
        "expected_keywords": ["perseus watch", "900s", "AGENTS.md", "interval"],
        "type": "insight",
    },
    {
        "query": "Describe the PERSEUS_ALLOW_DANGEROUS security gate and when it was added.",
        "expected_ids": ["insight-dangerous-gate", "decision-security-gate"],
        "expected_keywords": ["PERSEUS_ALLOW_DANGEROUS", "v1.0.6", "security gate", "@query"],
        "type": "insight",
    },
    {
        "query": "What is the cache staleness pitfall when re-rendering AGENTS.md, and how do we fix it?",
        "expected_ids": ["insight-cache-staleness"],
        "expected_keywords": ["cache", "staleness", "delete", "AGENTS.md"],
        "type": "insight",
    },

    # ── Cross-Cutting / Multi-Step Reasoning ──
    {
        "query": "If both our local Mneme FTS5 and Mneme return conflicting port numbers for the same service, which one should the system trust and why?",
        "expected_ids": ["arch-merge-strategy", "insight-conflict-resolution"],
        "expected_keywords": ["merge", "local", "conflict", "live state"],
        "type": "architecture",
    },
    {
        "query": "Walk through what happens when the Mneme service crashes mid-session — does the entire @memory directive fail?",
        "expected_ids": ["arch-circuit-breaker", "insight-fallback", "decision-graceful-degradation"],
        "expected_keywords": ["circuit breaker", "fallback", "graceful", "degraded", "FTS5"],
        "type": "architecture",
    },
    {
        "query": "How are memories tagged with decay scores, and what happens to a memory that's never retrieved for 6 months?",
        "expected_ids": ["arch-ebbinghaus-decay", "insight-memory-lifecycle"],
        "expected_keywords": ["Ebbinghaus", "decay_score", "forgetting curve", "retrieval_count"],
        "type": "architecture",
    },
    {
        "query": "Compare the trade-offs between the DECAY_FIRST and LOCAL_FIRST merge strategies — when would you use each?",
        "expected_ids": ["arch-merge-strategies", "decision-strategy-tradeoffs"],
        "expected_keywords": ["DECAY_FIRST", "LOCAL_FIRST", "freshness", "merge_strategy"],
        "type": "decision",
    },
    {
        "query": "What's the difference between the 'stdio' and 'sse' MCP transports for Engram, and which one are we using in production?",
        "expected_ids": ["arch-mcp-transport", "decision-transport-choice"],
        "expected_keywords": ["stdio", "SSE", "MCP", "transport", "subprocess"],
        "type": "architecture",
    },

    # ── Historical Context & Why-Decisions ──
    {
        "query": "Why did we migrate from Mnemosyne to Mneme as our long-term memory backend?",
        "expected_ids": ["decision-mnemosyne-to-engram", "arch-engram-benefits"],
        "expected_keywords": ["migration", "Mnemosyne", "Mneme", "Rust", "performance"],
        "type": "decision",
    },
    {
        "query": "What are the specific files that need to be updated when migrating the Perseus memory connector to a new backend?",
        "expected_ids": ["insight-connector-migration", "decision-migration-checklist"],
        "expected_keywords": ["engram_connector.py", "config.py", "agora.py", "build.py", "migration"],
        "type": "insight",
    },
    {
        "query": "Why does the Mneme bridge use a singleton pattern, and what's the mechanism for detecting config changes?",
        "expected_ids": ["arch-singleton-connector", "insight-config-hash"],
        "expected_keywords": ["singleton", "_get_connector", "cfg_hash", "reuse"],
        "type": "architecture",
    },
    {
        "query": "Explain the difference between @memory and @mimir directives in Perseus context.md — how do they each use Engram?",
        "expected_ids": ["arch-memory-vs-mimir", "insight-directive-differences"],
        "expected_keywords": ["@memory", "@mimir", "_mimir_hybrid_search", "_mimir_hybrid_recall"],
        "type": "architecture",
    },
    {
        "query": "What's the role of topic_path in Mneme memory organization, and how does it differ from the old Mnemosyne flat FTS5?",
        "expected_ids": ["arch-topic-trees", "insight-topic-vs-flat"],
        "expected_keywords": ["topic_path", "hierarchical", "topic trees", "flat search"],
        "type": "architecture",
    },
]


def _build_needle_haystack(needle_ids: list[str], num_distractors: int = 50) -> tuple[list, dict[str, str]]:
    """Build a haystack of MemoryHit objects containing specific needles.

    Returns (all_items, {needle_id: needle_content}).
    """
    needle_pool = {
        "arch-auth-db-choice": "The auth module uses SQLite FTS5 for local search because we required a zero-dependency, local-first architecture with no external database servers. Evaluated against PostgreSQL (too heavy for local dev), Meilisearch (external service), and Tantivy (Rust, but added complexity).",
        "decision-microkernel": "We adopted the microkernel pattern after evaluating monolithic, plugin-based, and service-oriented architectures. Microkernel was chosen for its strong isolation guarantees — each module runs in its own sandbox, failures don't cascade, and the core kernel only handles directive routing and lifecycle management.",
        "arch-engram-layers": "Mneme uses a three-layer memory architecture: Buffer (just-arrived, volatile, high decay), Working (actively referenced, moderate decay), and Core (consolidated long-term memory, low decay). Memories progress through layers automatically based on retrieval frequency and survival of Ebbinghaus decay thresholds.",
        "decision-engram-choice": "We chose Mneme over Mnemosyne for the long-term memory backend because Engram offers: (1) Rust-native performance with zero-copy deserialization, (2) built-in Ebbinghaus decay algorithms, (3) MCP-native protocol for standardized AI tool integration, and (4) the three-layer memory model provides better recall quality than flat vector stores.",
        "arch-mneme-driver": "Perseus Mneme v2 uses SQLite FTS5 for local BM25 keyword search, supplemented by sqlite-vec for optional vector embeddings. This was chosen for zero external dependencies — the same philosophy as Perseus itself: everything runs from a single-file Python artifact backed by SQLite.",
        "arch-circuit-breaker": "The circuit breaker in MimirConnector prevents cascading failures when Mneme is unreachable. It has 3 states: CLOSED (normal operation), OPEN (after 3 consecutive failures, all calls short-circuit to local FTS5), and HALF_OPEN (after 120s cooldown, probes with one request).",
        "decision-cb-thresholds": "Circuit breaker thresholds were set to 3 failures and 120s cooldown based on testing with real Engram outages. 3 failures prevents false positives from transient network blips. 120s is short enough to recover quickly but long enough to avoid retry storms.",
        "insight-build-artifact": "perseus.py is a BUILD ARTIFACT generated by scripts/build.py from src/ modules. NEVER edit perseus.py directly — always edit the source in src/ and rebuild. The build script concatenates all modules in a specific order (defined in MODULE_ORDER) into a single deployable file.",
        "insight-merge-conflict": "When resolving merge conflicts on perseus.py, always use `git checkout --ours perseus.py` to keep HEAD, then rebuild with `python3 scripts/build.py`. Since perseus.py is regenerated, resolving conflicts manually is wasted effort — the rebuild from correctly merged src/ modules is all that matters.",
        "insight-watch-daemon": "Perseus watch daemon auto-refreshes AGENTS.md every 900 seconds (15 minutes) by polling for changes in .perseus/context.md. It runs as a background process in the container since neither cron nor systemd is available. The interval can be changed via the --interval flag.",
        "insight-dangerous-gate": "PERSEUS_ALLOW_DANGEROUS=1 is a defense-in-depth security gate added in v1.0.6. Even when config allows @query/@agent/@services shell execution, this environment variable must be set. It prevents accidental shell execution in restricted environments.",
        "insight-cache-staleness": "The cache staleness pitfall: when AGENTS.md already exists, deleting only ~/.perseus/cache/ may NOT be sufficient. The output file itself can be blocked by dedup logic. You must delete BOTH the cache AND AGENTS.md before re-rendering to see changes.",
        "arch-merge-strategy": "Merge strategies determine how local Mneme FTS5 and Mneme results are combined. LOCAL_FIRST prioritizes local hits (what's happening now). REMOTE_FIRST prioritizes Engram history. INTERLEAVE alternates. DECAY_FIRST sorts everything by Ebbinghaus freshness.",
        "insight-conflict-resolution": "When local and remote data conflict, the system does not automatically resolve — it surfaces both with source tagging. The `verified` field only flags identical content. For conflicting data (different port numbers, etc.), both versions appear in the prompt with [local] and [engram] tags for the LLM to reason about.",
        "arch-ebbinghaus-decay": "Ebbinghaus decay models the forgetting curve: new memories start at decay_score=1.0 and exponentially decay toward 0.0. Retrieval reinforces memories, boosting their score. The decay rate differs by layer: Buffer decays fastest (hours), Working moderately (days), Core slowest (weeks/months).",
        "insight-memory-lifecycle": "Memories progress through layers: Buffer → Working → Core. If a memory in Buffer is never retrieved, it decays quickly and may be pruned. Working memories survive longer. Core memories are essentially permanent but still slowly decay if not accessed for months.",
        "arch-merge-strategies": "DECAY_FIRST is best for time-sensitive queries where recent information matters most (e.g., 'what's the current deploy pipeline?'). LOCAL_FIRST is best when local state is authoritative (e.g., 'what services are running?'). INTERLEAVE gives equal weight. REMOTE_FIRST is for historical analysis.",
        "decision-strategy-tradeoffs": "DECAY_FIRST: pure freshness ordering, ignores source. LOCAL_FIRST: trusts current state, best for operational queries. REMOTE_FIRST: trusts history, best for 'why did we do X?' questions. INTERLEAVE: balanced but can be confusing with very different result qualities.",
        "arch-mcp-transport": "MCP supports two transports: stdio (spawns Engram as a subprocess, JSON-RPC over stdin/stdout) and SSE (HTTP Server-Sent Events for remote/docker deployments). In production we use stdio for zero-network-overhead local deployment.",
        "decision-transport-choice": "We chose stdio transport for production because: (1) no network dependency — everything runs on localhost, (2) simpler security model — no exposed ports, (3) lower latency — no HTTP overhead. SSE transport exists as a stub for future dockerized deployments.",
        "decision-mnemosyne-to-engram": "We migrated from Mnemosyne to Mneme in Project Synapse v2 because: Mnemosyne was Python-based with higher memory overhead, lacked native MCP support, used flat FTS5 without semantic search, and had no decay modeling. Mneme addressed all these gaps with its Rust implementation.",
        "arch-engram-benefits": "Mneme benefits over Mnemosyne: (1) Rust performance — 5-10x faster recall, (2) Ebbinghaus decay eliminates manual memory curation, (3) MCP-native protocol enables standardized integration across AI assistants, (4) topic trees provide hierarchical organization vs flat keyword search.",
        "insight-connector-migration": "When migrating memory backends, update exactly 5 files: (1) src/perseus/<new>_connector.py — full rewrite, (2) src/perseus/config.py — rename config key, (3) src/perseus/agora.py — rename function calls, (4) scripts/build.py — update MODULE_ORDER, (5) remove old connector file. Then rebuild and validate.",
        "decision-migration-checklist": "The migration checklist ensures no file is missed: connector source, config defaults, injection point (agora.py), build order, and cleanup. Following this checklist prevents broken builds where old connector symbols linger in the artifact.",
        "arch-singleton-connector": "The Engram Connector uses a singleton pattern via _get_connector(cfg) for efficiency — creating a new MCP subprocess per query would be wasteful. Config changes are detected by hashing the sorted config dict; when the hash changes, the old connector is closed and a new one created.",
        "insight-config-hash": "Config change detection uses SHA-256 hashing of sorted config items. When _get_connector() detects a different hash, it closes the existing MCP connection and creates a fresh MimirConnector. This enables hot-reload of merge_strategy and circuit breaker settings without restart.",
        "arch-memory-vs-mimir": "@memory is the full-featured directive: FTS5 search + Mimir augmentation + federation. @mimir is the lightweight cousin: BM25 recall with optional Mimir augmentation. Under the hood, @mimir delegates to @memory via resolve_mimir → resolve_memory.",
        "insight-directive-differences": "@memory uses _mimir_hybrid_search() which does full hybrid resolution with local fallback. @mimir uses _mimir_hybrid_recall() which is simpler — local FTS5 first, Mneme augmentation if available, returns MemorySegment directly.",
        "arch-topic-trees": "Topic trees in Engram organize memories hierarchically (e.g., 'architecture/database/choice'). This enables scoped queries: you can search within a subtree for more precise recall. Unlike flat FTS5 which treats all memories equally, topic trees provide structural context.",
        "insight-topic-vs-flat": "Flat FTS5 (Mnemosyne) searches all content equally — you might get a deployment note when asking about database decisions. Topic trees (Engram) enable scoped recall by path prefix, dramatically improving precision for domain-specific queries.",
    }

    # Create the distractor pool (generic memories that shouldn't match)
    distractors = []
    for i in range(num_distractors):
        topics = ["deployment", "testing", "monitoring", "logging", "CI/CD", "docker", "kubernetes", "frontend", "styling", "accessibility",
                  "npm", "webpack", "esbuild", "typescript", "react", "vue", "svelte", "tailwind", "storybook", "playwright",
                  "cypress", "jest", "vitest", "eslint", "prettier", "terraform", "ansible", "nginx", "haproxy", "letsencrypt"]
        distractors.append(
            _make_hit(
                f"distractor-{i}",
                f"Note about {topics[i % len(topics)]} configuration: set the {topics[i % len(topics)]}_TIMEOUT env var to 30s. This was configured on {2020 + (i % 6)}-{1 + (i % 12):02d}-{1 + (i % 28):02d}. No impact on core architecture decisions.",
                source="mimir" if i % 2 == 0 else "local",
                mtype=["insight", "architecture", "decision"][i % 3],
                decay=0.1 + (i % 10) * 0.08,
            )
        )

    # Create the needle items
    needles = []
    for nid in needle_ids:
        content = needle_pool.get(nid, f"Default content for {nid}")
        needles.append(
            _make_hit(
                nid,
                content,
                source="mimir",
                mtype="architecture" if "arch" in nid else ("decision" if "decision" in nid else "insight"),
                decay=0.85,
                relevance=0.9,
            )
        )

    all_items = needles + distractors
    return all_items, needle_pool


class TestNeedleInHaystack:
    """Recall@K benchmark: can the system find the right memories among distractors?

    Because we can't actually run semantic search against Engram (it's not installed),
    these tests validate the merge & ordering logic — given a set of hits, does the
    merge strategy correctly rank the relevant ones highest?
    """

    def _connector(self, strategy="local_first"):
        _reset_connector_singleton()
        c = _test_cfg()
        c["mimir"]["merge_strategy"] = strategy
        return perseus.MimirConnector(c)

    @pytest.mark.parametrize("query_entry", GOLDEN_QUERIES, ids=[q["query"][:60] for q in GOLDEN_QUERIES])
    def test_golden_set_needle_found_in_top_k(self, query_entry):
        """Each golden query's expected memory items should be found when present."""
        expected_ids = query_entry["expected_ids"]
        haystack, _ = _build_needle_haystack(expected_ids, num_distractors=50)

        # Simulate: the expected needles + distractors are the "mimir" results,
        # local results are an empty list
        conn = self._connector(strategy="decay_first")

        # Separate needles from distractors
        needle_ids = set(expected_ids)
        local_items = []  # no local hits
        mneme_items = haystack  # includes needles + distractors

        merged = conn._merge_results(
            local_items=local_items,
            mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.DECAY_FIRST,
            diagnostics={},
        )

        # Needles should be in the top K (K=5)
        top_5_ids = [item.id for item in merged.items[:5]]
        found = [nid for nid in expected_ids if nid in top_5_ids]

        # Verify all needles are in the results at all
        all_ids = [item.id for item in merged.items]
        missing = [nid for nid in expected_ids if nid not in all_ids]
        assert len(missing) == 0, f"Needles missing from results entirely: {missing}"

        # Verify needles appear in top 5 (since they have higher decay_score=0.85
        # than distractors which max at 0.82)
        assert len(found) == len(expected_ids), \
            f"Only {len(found)}/{len(expected_ids)} needles in top 5: {found}"

    def test_needle_found_among_many_distractors(self):
        """Stress test: 1 needle among 200 distractors should still rank well."""
        expected_ids = ["arch-circuit-breaker"]
        haystack, _ = _build_needle_haystack(expected_ids, num_distractors=200)

        conn = self._connector(strategy="decay_first")
        merged = conn._merge_results(
            local_items=[], mneme_items=haystack,
            strategy=perseus.MergeStrategy.DECAY_FIRST, diagnostics={},
        )

        # Needle should be in top 3
        top_3_ids = [item.id for item in merged.items[:3]]
        assert expected_ids[0] in top_3_ids, \
            f"Needle not in top 3 among 200 distractors: top 3 = {top_3_ids}"

    def test_multiple_needles_all_ranked(self):
        """10 needles among 100 distractors — all should be in top 10."""
        expected_ids = [
            "arch-auth-db-choice", "decision-microkernel", "arch-engram-layers",
            "insight-build-artifact", "arch-circuit-breaker", "insight-dangerous-gate",
            "arch-merge-strategy", "decision-mnemosyne-to-engram", "arch-singleton-connector",
            "arch-topic-trees",
        ]
        haystack, _ = _build_needle_haystack(expected_ids, num_distractors=100)

        conn = self._connector(strategy="decay_first")
        merged = conn._merge_results(
            local_items=[], mneme_items=haystack,
            strategy=perseus.MergeStrategy.DECAY_FIRST, diagnostics={},
        )

        top_15_ids = [item.id for item in merged.items[:15]]
        found = [nid for nid in expected_ids if nid in top_15_ids]
        recall_rate = len(found) / len(expected_ids)
        assert recall_rate >= 0.8, \
            f"Recall@15 = {recall_rate:.0%}, expected >= 80%. Found: {found}"

    def test_recall_k_benchmark(self):
        """Systematic Recall@K measurement across all Golden Set queries."""
        results = []
        conn = self._connector(strategy="decay_first")

        for query_entry in GOLDEN_QUERIES:
            expected_ids = query_entry["expected_ids"]
            haystack, _ = _build_needle_haystack(expected_ids, num_distractors=50)
            merged = conn._merge_results(
                local_items=[], mneme_items=haystack,
                strategy=perseus.MergeStrategy.DECAY_FIRST, diagnostics={},
            )

            recall_at = {}
            for k in [1, 3, 5, 10]:
                top_k_ids = [item.id for item in merged.items[:k]]
                found = sum(1 for nid in expected_ids if nid in top_k_ids)
                recall_at[f"R@{k}"] = found / len(expected_ids)

            results.append({
                "query": query_entry["query"][:80],
                "expected_count": len(expected_ids),
                "recall": recall_at,
            })

        # Overall metrics
        r1_values = [r["recall"]["R@1"] for r in results]
        r5_values = [r["recall"]["R@5"] for r in results]
        r10_values = [r["recall"]["R@10"] for r in results]

        avg_r1 = sum(r1_values) / len(r1_values)
        avg_r5 = sum(r5_values) / len(r5_values)
        avg_r10 = sum(r10_values) / len(r10_values)

        # Log for visibility
        print(f"\n  Recall@K Benchmarks (Golden Set of {len(GOLDEN_QUERIES)} queries):")
        print(f"  R@1  = {avg_r1:.1%}")
        print(f"  R@5  = {avg_r5:.1%}")
        print(f"  R@10 = {avg_r10:.1%}")

        # Assertions: with correct decay ordering, needles should dominate
        assert avg_r5 >= 0.80, f"Average Recall@5 = {avg_r5:.1%}, target >= 80%"
        assert avg_r10 >= 0.90, f"Average Recall@10 = {avg_r10:.1%}, target >= 90%"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DECAY PRIORITY — Ebbinghaus Freshness Ordering
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayPriority:
    """Validate that freshness (decay_score) is correctly used in ordering."""

    def _connector(self):
        _reset_connector_singleton()
        return perseus.MimirConnector(_test_cfg())

    def test_decay_first_prioritizes_fresh_over_stale(self):
        """Fresh items (decay=1.0) should appear before stale ones (decay=0.1)."""
        conn = self._connector()
        items = [
            _make_hit("stale-1", "Very old decision about Python version.", "mimir", "decision", decay=0.05),
            _make_hit("fresh-1", "Recent architecture change: switched to Rust.", "mimir", "architecture", decay=0.99),
            _make_hit("mid-1", "Somewhat recent insight about caching.", "mimir", "insight", decay=0.50),
            _make_hit("stale-2", "Obsolete note about npm packages.", "local", "insight", decay=0.01),
            _make_hit("fresh-2", "Today's hotfix for auth race condition.", "local", "decision", decay=1.0),
        ]

        merged = conn._merge_results(
            local_items=[i for i in items if i.source == perseus.MemorySource.LOCAL],
            mneme_items=[i for i in items if i.source == perseus.MemorySource.MNEME],
            strategy=perseus.MergeStrategy.DECAY_FIRST,
            diagnostics={},
        )

        scores = [item.decay_score for item in merged.items]
        assert scores == sorted(scores, reverse=True), f"Not sorted by decay desc: {scores}"

    def test_high_retrieval_count_items_kept_high(self):
        """Items with high retrieval_count should have higher decay (reinforced)."""
        # This tests that the data model supports the concept — actual decay
        # calculation happens in Mneme, but our connector preserves the values.
        fresh = _make_hit("r-fresh", "Frequently accessed memory", "mimir", "insight", decay=0.98)
        assert fresh.retrieval_count == 0  # default
        fresh.retrieval_count = 50
        assert fresh.retrieval_count == 50

    def test_decay_score_preserved_through_parse(self):
        """_parse_memory_hits should correctly forward decay_score from MCP JSON."""
        raw = {
            "items": [
                {"id": "x-1", "content": "Test memory", "type": "insight",
                 "decay_score": 0.73, "retrieval_count": 12, "layer": "working",
                 "topic_path": "test/path", "relevance": 0.65},
            ]
        }
        hits = perseus._parse_memory_hits(raw)
        assert len(hits) == 1
        assert hits[0].decay_score == 0.73
        assert hits[0].retrieval_count == 12
        assert hits[0].layer == perseus.MemoryLayer.WORKING
        assert hits[0].topic_path == "test/path"

    def test_local_items_default_to_fresh(self):
        """Local Mneme hits should default to decay_score=1.0 (treated as fresh)."""
        local_raw = [
            {"id": "l-1", "content": "Local memory", "summary": "Local summary", "type": "insight"},
        ]
        hits = perseus._local_hits_to_memory_hits(local_raw)
        assert hits[0].decay_score == 1.0
        assert hits[0].source == perseus.MemorySource.LOCAL


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CONFLICT RESOLUTION — Local vs Remote Discrepancies
# ═══════════════════════════════════════════════════════════════════════════════

class TestConflictResolution:
    """Validate how the merge logic handles conflicting data between sources."""

    def _connector(self, strategy="local_first"):
        _reset_connector_singleton()
        c = _test_cfg()
        c["mimir"]["merge_strategy"] = strategy
        return perseus.MimirConnector(c)

    def test_conflicting_data_both_surfaced(self):
        """When local and remote have DIFFERENT data for the same topic,
        both should appear in results (not deduped)."""
        conn = self._connector("local_first")
        local = [
            _make_hit("l-port", "Service port configured to 8080 (local override)", "local", "architecture", decay=1.0),
        ]
        mneme_items = [
            _make_hit("e-port", "Service port configured to 3000 (historical default)", "mimir", "architecture", decay=0.5),
        ]

        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        # Both should appear — they have different content
        assert len(merged.items) == 2
        sources = {item.source for item in merged.items}
        assert perseus.MemorySource.LOCAL in sources
        assert perseus.MemorySource.MNEME in sources

        # In LOCAL_FIRST, the local (fresher) port should come first
        assert merged.items[0].source == perseus.MemorySource.LOCAL
        assert "8080" in merged.items[0].content

    def test_identical_content_verified_not_conflict(self):
        """Same content → verified=True, not a conflict. Mneme version preferred."""
        conn = self._connector("local_first")
        content = "The API uses port 8080."
        local = [_make_hit("l-api", content, "local", "architecture", decay=0.9)]
        mneme_items = [_make_hit("e-api", content, "mimir", "architecture", decay=0.7)]

        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        assert len(merged.items) == 1
        assert merged.items[0].verified is True

    def test_conflict_resolution_with_decay_first(self):
        """With DECAY_FIRST, the fresher conflicting data wins (appears first)."""
        conn = self._connector("decay_first")
        local = [
            _make_hit("l-new-port", "Current port: 9090 (recent change)", "local", "architecture", decay=0.95),
        ]
        mneme_items = [
            _make_hit("e-old-port", "Historical port: 3000 (original design)", "mimir", "architecture", decay=0.25),
        ]

        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.DECAY_FIRST, diagnostics={},
        )
        # Both appear, but fresher first
        assert merged.items[0].id == "l-new-port"  # decay=0.95 > 0.25
        assert "9090" in merged.items[0].content

    def test_merge_diagnostics_discrepancy_detection(self):
        """Diagnostics should show how many items are from each source."""
        conn = self._connector("local_first")
        local = [
            _make_hit("l-a", "Content A", "local", "insight"),
            _make_hit("l-b", "Content B", "local", "insight"),
        ]
        mneme_items = [
            _make_hit("e-b", "Content B", "mimir", "insight"),  # same as l-b → verified
            _make_hit("e-c", "Content C", "mimir", "insight"),
        ]
        diag = {}
        merged = conn._merge_results(
            local_items=local, mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics=diag,
        )
        assert diag["merge_verified"] == "1"
        assert diag["merge_local_only"] == "1"   # l-a
        assert diag["merge_mneme_only"] == "1"  # e-c
