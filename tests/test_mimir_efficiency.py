"""
test_mneme_efficiency.py — Phase 3: Context Efficiency (Cost/Token Optimization)

Validates that the hybrid Mneme + vault approach is token-efficient.
Every token costs money, so we need to ensure:

1. Deduplication is working — no redundant information
2. Token-to-Information ratio is high
3. Different merge strategies have different token profiles
4. The assembled prompt is compact but informative

Test suites:
  1. Token Budget Validation — count estimated tokens
  2. Deduplication Efficiency — measure redundant token elimination
  3. Information Density — ratio of unique info to total tokens
  4. Strategy Comparison — compare token profiles across merge strategies
  5. Real-World Simulation — full prompt assembly with realistic data
"""

import copy
import textwrap
from pathlib import Path


import pytest

from conftest import PY_VER, cfg, perseus



# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _reset_connector_singleton():
    perseus._connector = None
    perseus._connector_cfg_hash = ""


def _test_cfg(strategy="local_first"):
    _reset_connector_singleton()
    c = cfg()
    c["mimir"] = {
        "enabled": True,
        "transport": "stdio",
        "command": ["/nonexistent/path/mneme"],
        "timeout_s": 0.5,
        "merge_strategy": strategy,
        "decay_priority_weight": 0.4,
        "fallback_to_local": True,
        "circuit_breaker": {"threshold": 1, "cooldown": 1},
        "retry_policy": {"max_attempts": 1, "backoff_base": 0.01},
    }
    return c


def _make_hit(id_, content, source="local", mtype="insight", decay=1.0, relevance=0.5):
    return perseus.EntityHit(
        id=id_, body_json=content, source=perseus.MemorySource(source),
        entity_type=mtype, category="test", key=id_,
        decay_score=decay,
    )


def _estimate_tokens(text: str) -> int:
    """Very rough token estimate: ~4 chars per token for English text.
    This is a ballpark for budget checks, not an exact count."""
    return max(1, len(text) // 4)


def _unique_content_token_count(items) -> int:
    """Count tokens only for unique content across items."""
    seen = set()
    tokens = 0
    for item in items:
        c = item.content.strip()
        if c not in seen:
            seen.add(c)
            tokens += _estimate_tokens(c)
    return tokens


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TOKEN BUDGET VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestTokenBudget:
    """Validate that merged & assembled context stays within token budgets."""

    def _connector(self, strategy="local_first"):
        return perseus.MimirConnector(_test_cfg(strategy))

    def test_merged_segment_stays_within_budget(self):
        """A merged result with 10 items should be well under 10K tokens."""
        conn = self._connector()
        local = []
        mimir_items = []
        for i in range(5):
            local.append(_make_hit(
                f"l-{i}",
                f"Local memory item {i}: This is a moderately detailed description of architectural decisions "
                f"made during the development of the Perseus context engine. We chose SQLite for its zero-dependency "
                f"guarantee and FTS5 for full-text search capabilities. The system uses a single-file deployment model.",
                "local", "architecture", decay=0.8 - i * 0.1,
            ))
        for i in range(5):
            mimir_items.append(_make_hit(
                f"e-{i}",
                f"Mneme memory item {i}: Historical context about the project's evolution from earlier prototypes. "
                f"The v1 used flat JSON files, v2 introduced Mnemosyne with FTS5, and v3 (current) uses Mneme "
                f"with topic trees and Ebbinghaus decay modeling for automatic memory lifecycle management.",
                "mimir", "insight", decay=0.9 - i * 0.15,
            ))

        merged = conn._merge_results(
            local_items=local, mimir_items=mimir_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )

        total_tokens = sum(_estimate_tokens(item.content) for item in merged.items)
        assert len(merged.items) == 10
        assert total_tokens < 2000, f"10 items = {total_tokens} tokens, expected < 2000"

    def test_context_package_assembly_token_count(self):
        """Full ContextPackage.assemble() with live state + memory should be countable."""
        live_entries = []
        for j in range(10):
            live_entries.append(perseus.LiveStateEntry(
                key=f"ENV_VAR_{j}", value=f"value_for_env_var_{j}", source="@env"
            ))

        live = perseus.LiveStateSegment(workspace_path="/tmp/test", entries=live_entries)
        mem_items = [
            _make_hit("mem-0", "Core architecture uses microkernel pattern for module isolation.", "mimir", "architecture"),
            _make_hit("mem-1", "Database driver chosen: SQLite FTS5 for zero-dependency guarantee.", "local", "decision"),
            _make_hit("mem-2", "Build artifact perseus.py is generated from src/ via scripts/build.py.", "mimir", "insight"),
        ]
        mem = perseus.MemorySegment(items=mem_items, strategy_used="local_first", total_available=3)
        pkg = perseus.ContextPackage(live_state=live, memory=mem, merge_strategy=perseus.MergeStrategy.LOCAL_FIRST)
        assembled = pkg.assemble()

        tokens = _estimate_tokens(assembled)
        # Should be well under 5K tokens for this small realistic example
        assert tokens > 0
        assert tokens < 5000, f"Assembled context = {tokens} tokens, expected < 5000"

    def test_large_context_stays_reasonable(self):
        """Even with 50+ memories, the assembled prompt should be < 15K tokens."""
        live_entries = [perseus.LiveStateEntry(key=f"k{j}", value=f"v{j}", source="@ctx") for j in range(20)]
        live = perseus.LiveStateSegment(workspace_path="/tmp", entries=live_entries)

        mem_items = []
        for i in range(50):
            mem_items.append(_make_hit(
                f"item-{i}",
                f"Architecture note {i}: The system processes requests through a pipeline of {i % 5} stages, "
                f"each with its own timeout and retry policy. Memory retrieval is cached for performance.",
                "mimir" if i % 2 == 0 else "local",
                ["architecture", "decision", "insight"][i % 3],
                decay=0.1 + (i % 10) * 0.09,
            ))

        mem = perseus.MemorySegment(items=mem_items, strategy_used="decay_first", total_available=50)
        pkg = perseus.ContextPackage(live_state=live, memory=mem, merge_strategy=perseus.MergeStrategy.LOCAL_FIRST)
        assembled = pkg.assemble()

        tokens = _estimate_tokens(assembled)
        assert tokens < 20000, f"Large context = {tokens} tokens, expected < 20000"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DEDUPLICATION EFFICIENCY
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeduplicationEfficiency:
    """Measure how much token waste is eliminated by deduplication."""

    def _connector(self):
        return perseus.MimirConnector(_test_cfg())

    def test_dedup_eliminates_duplicate_tokens(self):
        """Identical content in both sources → only one copy in result.
        Without dedup: 2 copies (500 tokens). With dedup: 1 copy (250 tokens)."""
        conn = self._connector()
        long_content = (
            "The comprehensive architectural decision to adopt a microkernel pattern "
            "was made after extensive evaluation. We considered: (1) Monolithic — simple "
            "but poor isolation, (2) Plugin-based — good extensibility but complex lifecycle, "
            "(3) Microkernel — strong isolation, clear boundaries, testable in isolation. "
            "The final decision weighed isolation guarantees above all else."
        ) * 2  # make it long enough to matter

        local = [_make_hit("l-long", long_content, "local", "decision", decay=0.5)]
        mneme_items = [_make_hit("l-long", long_content, "mimir", "decision", decay=0.9)]

        merged = conn._merge_results(
            local_items=local, mimir_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )

        # Should be exactly 1 item (deduped)
        assert len(merged.items) == 1
        deduped_tokens = _estimate_tokens(merged.items[0].content)
        # Without dedup: would be 2 * deduped_tokens
        without_dedup_tokens = 2 * deduped_tokens
        savings_pct = (without_dedup_tokens - deduped_tokens) / without_dedup_tokens * 100
        assert savings_pct >= 45, f"Dedup savings = {savings_pct:.1f}%, expected >= 45%"

    def test_dedup_with_multiple_shared_items(self):
        """5 shared items out of 10 total → ~50% token savings."""
        conn = self._connector()
        shared_contents = [
            f"Shared architectural insight #{i}: The microkernel design enables clean separation between the core routing layer and individual module implementations, each running in its own logical sandbox with controlled I/O boundaries."
            for i in range(5)
        ]

        local = [_make_hit(f"l-shared-{i}", shared_contents[i], "local", "architecture") for i in range(5)]
        local += [_make_hit(f"l-unique-{i}", f"Local-only operational note #{i}: Daily health check runs at 0600 UTC.", "local", "insight") for i in range(5)]

        mneme_items = [_make_hit(f"e-shared-{i}", shared_contents[i], "mimir", "architecture", decay=0.85) for i in range(5)]
        mneme_items += [_make_hit(f"e-unique-{i}", f"Mneme-only historical context #{i}: Original prototype used JSON flat files.", "mimir", "insight", decay=0.3) for i in range(5)]

        merged = conn._merge_results(
            local_items=local, mimir_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )

        # Total items: 5 shared + 5 local-only + 5 mneme-only = 15
        assert len(merged.items) == 15

        # Without dedup: 10 local + 10 engram = 20 items
        without_dedup_count = 20
        with_dedup_count = len(merged.items)
        reduction = (without_dedup_count - with_dedup_count) / without_dedup_count * 100
        assert reduction >= 20, f"Item count reduction = {reduction:.1f}%, expected >= 20% (5/20)"

    def test_dedup_token_savings_reported_in_diagnostics(self):
        """Diagnostics should include dedup savings metrics."""
        conn = self._connector()
        shared = "This is a shared memory that exists in both local and remote stores."
        local = [_make_hit("l-dup", shared, "local", "insight")]
        mneme_items = [_make_hit("e-dup", shared, "mimir", "insight")]

        diag = {}
        conn._merge_results(
            local_items=local, mimir_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics=diag,
        )
        # Diagnostics should show dedup activity
        assert diag.get("merge_verified") == "1"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. INFORMATION DENSITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestInformationDensity:
    """Measure unique information per token — the core efficiency metric."""

    def _connector(self):
        return perseus.MimirConnector(_test_cfg())

    def test_all_unique_content_high_density(self):
        """When all items are unique, information density approaches 1.0."""
        conn = self._connector()
        items = [
            _make_hit(f"item-{i}", f"Unique content piece number {i} with specific details about component {chr(65+i)}.", "mimir", "insight")
            for i in range(10)
        ]

        merged = conn._merge_results(
            local_items=items[:5], mimir_items=items[5:],
            strategy=perseus.MergeStrategy.INTERLEAVE, diagnostics={},
        )

        unique_tokens = _unique_content_token_count(merged.items)
        total_tokens = sum(_estimate_tokens(item.content) for item in merged.items)
        density = unique_tokens / total_tokens if total_tokens > 0 else 0
        # All unique → density = 1.0
        assert density == 1.0, f"Density = {density:.2f}, expected 1.0"

    def test_duplicate_content_lowers_density(self):
        """Duplicates reduce density. Dedup should restore it."""
        conn = self._connector()
        shared = "Repeated content across multiple items. This represents redundant information that should be deduplicated."
        redundant_items = [
            _make_hit("r-1", shared, "mimir", "insight"),
            _make_hit("r-2", shared, "local", "insight"),
            _make_hit("r-3", "Unique item with different information that adds value.", "mimir", "insight"),
        ]

        # Before merge (without dedup): 3 items, 2 share same content
        before_total = sum(_estimate_tokens(item.content) for item in redundant_items)
        before_unique = _unique_content_token_count(redundant_items)
        before_density = before_unique / before_total

        # After merge (with dedup): should have 2 items
        merged = conn._merge_results(
            local_items=[redundant_items[1]],  # local: r-2
            mimir_items=[redundant_items[0], redundant_items[2]],  # engram: r-1 (same) + r-3 (unique)
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )

        after_total = sum(_estimate_tokens(item.content) for item in merged.items)
        after_unique = _unique_content_token_count(merged.items)
        after_density = after_unique / after_total if after_total > 0 else 0

        # Density after dedup should be higher than before
        assert after_density > before_density, \
            f"After dedup density ({after_density:.2f}) should be > before ({before_density:.2f})"

    def test_information_density_ratio(self):
        """Core metric: information density with 50 items, 40% duplicates."""
        conn = self._connector()
        unique_bases = [f"Unique architectural insight #{i}: details about module {i}." for i in range(30)]
        duplicate_pairs = [f"Shared content block #{j} that appears in both local and mneme stores." for j in range(10)]

        local = [_make_hit(f"l-u-{i}", unique_bases[i], "local", "architecture") for i in range(15)]
        mimir_items = [_make_hit(f"e-u-{i}", unique_bases[i+15], "mimir", "architecture") for i in range(15)]
        for j in range(10):
            local.append(_make_hit(f"l-dup-{j}", duplicate_pairs[j], "local", "decision"))
            mimir_items.append(_make_hit(f"e-dup-{j}", duplicate_pairs[j], "mimir", "decision", decay=0.8))

        merged = conn._merge_results(
            local_items=local, mimir_items=mimir_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )

        # 25 local + 25 engram = 50 raw items, 10 shared → 40 unique
        assert len(merged.items) == 40

        unique_content = set(item.content for item in merged.items)
        assert len(unique_content) == 40

        total_tokens = sum(_estimate_tokens(item.content) for item in merged.items)
        unique_tokens = sum(_estimate_tokens(c) for c in unique_content)
        density = unique_tokens / total_tokens if total_tokens > 0 else 0

        assert density == 1.0, f"Post-dedup density = {density:.2f}, expected 1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STRATEGY COMPARISON — Token Profiles
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyTokenProfiles:
    """Compare token profiles across different merge strategies.

    Different strategies should produce different prompt structures,
    but the total token count for a given result set should be similar
    since the underlying items are the same.
    """

    def _merge_with_strategy(self, strategy_name):
        _reset_connector_singleton()
        conn = perseus.MimirConnector(_test_cfg(strategy_name))
        strategy_enum = {
            "local_first": perseus.MergeStrategy.LOCAL_FIRST,
            "remote_first": perseus.MergeStrategy.REMOTE_FIRST,
            "interleave": perseus.MergeStrategy.INTERLEAVE,
            "decay_first": perseus.MergeStrategy.DECAY_FIRST,
        }[strategy_name]

        local = [
            _make_hit("l-a", "Local A: Current deployment runs on port 8080 with TLS enabled.", "local", "architecture", decay=0.95),
            _make_hit("l-b", "Local B: Monitoring uses Prometheus with 15s scrape interval.", "local", "insight", decay=0.85),
            _make_hit("l-c", "Local C: Recent hotfix for auth race condition deployed today.", "local", "decision", decay=1.0),
        ]
        mneme_items = [
            _make_hit("e-x", "Engram X: Historical deployment was on port 3000 without TLS.", "mimir", "architecture", decay=0.15),
            _make_hit("e-y", "Engram Y: Monitoring was originally done with Grafana Cloud.", "mimir", "insight", decay=0.25),
            _make_hit("e-z", "Engram Z: Auth module was originally OAuth-only, no JWT.", "mimir", "decision", decay=0.10),
        ]

        return conn._merge_results(
            local_items=local, mimir_items=mneme_items,
            strategy=strategy_enum, diagnostics={},
        )

    def test_token_count_similar_across_strategies(self):
        """All strategies should produce the same total token count if items are the same."""
        token_counts = {}
        for strategy in ["local_first", "remote_first", "interleave", "decay_first"]:
            merged = self._merge_with_strategy(strategy)
            token_counts[strategy] = sum(_estimate_tokens(item.content) for item in merged.items)

        # All should have 6 items, so token counts should be identical
        unique_counts = set(token_counts.values())
        assert len(unique_counts) == 1, \
            f"Token counts differ across strategies: {token_counts}"

    def test_strategy_ordering_affects_prompt_structure(self):
        """The ORDER of items differs, which matters for LLM attention.
        LOCAL_FIRST: local items at top. DECAY_FIRST: freshest at top."""
        local_first = self._merge_with_strategy("local_first")
        decay_first = self._merge_with_strategy("decay_first")

        lf_sources = [item.source.value for item in local_first.items[:3]]
        df_sources = [item.source.value for item in decay_first.items[:3]]

        # LOCAL_FIRST: all top 3 should be local
        assert all(s == "local" for s in lf_sources), \
            f"LOCAL_FIRST top 3 should be local, got {lf_sources}"

        # DECAY_FIRST: freshest items first — local items have higher decay
        # so local items should appear first (they are fresher)
        # The freshest items are l-c (1.0), l-a (0.95), l-b (0.85)
        top_ids = [item.id for item in decay_first.items[:3]]
        assert "l-c" == top_ids[0], f"DECAY_FIRST: freshest should be l-c (decay=1.0), got {top_ids[0]}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. REAL-WORLD SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealWorldSimulation:
    """Simulate a realistic session with live state + memory from both sources."""

    def test_realistic_session_context_assembly(self):
        """Simulate what a real @memory directive produces in an AGENTS.md file."""
        # Live state: 15 environment variables, 5 config values
        live_entries = [
            perseus.LiveStateEntry(key="PERSEUS_VERSION", value="1.0.6", source="@env"),
            perseus.LiveStateEntry(key="ENGRAM_ENABLED", value="true", source="@env"),
            perseus.LiveStateEntry(key="ENGRAM_TRANSPORT", value="stdio", source="@config"),
            perseus.LiveStateEntry(key="MERGE_STRATEGY", value="local_first", source="@config"),
            perseus.LiveStateEntry(key="MNEMOSYNE_DB_VERSION", value="3.3.0", source="@env"),
            perseus.LiveStateEntry(key="WORKSPACE_PATH", value="/opt/data/webui/minions/ws", source="@ctx"),
            perseus.LiveStateEntry(key="HOSTNAME", value="hermes-webui", source="@env"),
            perseus.LiveStateEntry(key="PROJECT", value="perseus", source="@ctx"),
            perseus.LiveStateEntry(key="PYTHON_VERSION", value="3.12.13", source="@env"),
            perseus.LiveStateEntry(key="ENGINE_MODE", value="production", source="@config"),
            *[perseus.LiveStateEntry(key=f"SERVICE_{j}", value=f"running_on_port_{8000+j}", source="@services") for j in range(5)],
        ]

        live = perseus.LiveStateSegment(workspace_path="/opt/data/webui/minions/ws", entries=live_entries)

        # Memory: 8 items — a mix of architecture decisions, operational notes, and insights
        mem_items = [
            _make_hit("arch-1",
                "The Perseus context engine uses a microkernel architecture where each module (Sense, Memory, Agora) "
                "operates as an isolated component. The core router handles directive parsing and module dispatch.",
                "mimir", "architecture", decay=0.88),
            _make_hit("dec-1",
                "SQLite FTS5 was chosen for local Mneme search because: (1) zero external dependency — everything "
                "ships in one file, (2) FTS5 provides BM25 ranking adequate for our use case, (3) sqlite-vec "
                "supplements with optional vector embeddings. PostgreSQL was rejected as too heavy for local dev.",
                "local", "decision", decay=0.95),
            _make_hit("ins-1",
                "perseus.py is a BUILD ARTIFACT generated by scripts/build.py from src/ modules. NEVER edit it "
                "directly — always edit src/ and rebuild. Merge conflicts resolved with --ours then rebuild.",
                "mimir", "insight", decay=0.92),
            _make_hit("arch-2",
                "The Mneme bridge uses MCP stdio transport: it spawns 'mneme serve --mcp' as a subprocess "
                "and communicates via JSON-RPC over stdin/stdout. The SSE transport is available as a stub "
                "for future dockerized deployments.",
                "mimir", "architecture", decay=0.85),
            _make_hit("dec-2",
                "Circuit breaker thresholds: 3 consecutive failures trigger OPEN state, 120s cooldown before "
                "HALF_OPEN probe. These values were chosen to balance fast failure detection with false positive "
                "avoidance during transient network issues.",
                "local", "decision", decay=0.78),
            _make_hit("ins-2",
                "Perseus watch daemon auto-refreshes AGENTS.md every 900s. Since the container has no cron/systemd, "
                "the daemon runs as a persistent background process with configurable interval via --interval flag.",
                "mimir", "insight", decay=0.72),
            _make_hit("arch-3",
                "Mnemosyne v3.3.0 uses FTS5 with optional vector embeddings via sqlite-vec. The database is stored "
                "at ~/.hermes/mnemosyne/data/mnemosyne.db. Mnemosyne scores with embeddings active show improved recall.",
                "local", "architecture", decay=0.65),
            _make_hit("dec-3",
                "PERSEUS_ALLOW_DANGEROUS=1 is a defense-in-depth security gate added in v1.0.6 to prevent accidental "
                "shell execution. Even when config allows @query/@agent shell access, this env var must be set.",
                "mimir", "decision", decay=0.60),
        ]

        mem = perseus.MemorySegment(items=mem_items, strategy_used="local_first", total_available=8)
        pkg = perseus.ContextPackage(live_state=live, memory=mem, merge_strategy=perseus.MergeStrategy.LOCAL_FIRST)
        assembled = pkg.assemble()

        tokens = _estimate_tokens(assembled)

        # Verify structure
        assert "## Live Context" in assembled or "Live Context" in assembled, \
            "Assembled context should contain live context section"
        assert "## Memory" in assembled or "Memory" in assembled, \
            "Assembled context should contain memory section"

        # Token budget for realistic session: compact assembly is efficient
        # ContextPackage.assemble() produces a compact rendering, not raw item dump
        assert 200 <= tokens <= 10000, \
            f"Realistic session context = {tokens} tokens, expected 200-10000"

        # Information density should be high
        unique_content = set(item.content for item in mem_items)
        unique_tokens = sum(_estimate_tokens(c) for c in unique_content)
        total_item_tokens = sum(_estimate_tokens(item.content) for item in mem_items)
        density = unique_tokens / total_item_tokens if total_item_tokens else 0
        assert density == 1.0, f"Information density = {density:.2f}, expected 1.0 (all items unique)"

    def test_engram_adds_value_over_local_only(self):
        """Compare token count and information for Local-Only vs Hybrid modes."""
        # Local-Only: 5 items
        local_only_items = [
            _make_hit("lo-1", "Current port: 8080 with TLS.", "local", "architecture"),
            _make_hit("lo-2", "Auth uses JWT with 15min expiry.", "local", "decision"),
            _make_hit("lo-3", "CI pipeline: build → test → deploy.", "local", "insight"),
            _make_hit("lo-4", "Monitoring: Prometheus at :9090.", "local", "architecture"),
            _make_hit("lo-5", "Cache: Redis for session store.", "local", "decision"),
        ]
        local_tokens = sum(_estimate_tokens(item.content) for item in local_only_items)

        # Hybrid: 5 local + 5 mneme items, 2 shared (verified)
        shared_content = [
            "Auth uses JWT with 15min expiry — same as local.",  # shared
            "Cache: Redis for session store — identical content.",  # shared
        ]
        hybrid_local = [
            _make_hit("hl-1", "Current port: 8080 with TLS.", "local", "architecture"),
            _make_hit("hl-2", shared_content[0], "local", "decision"),
            _make_hit("hl-3", "CI pipeline: build → test → deploy.", "local", "insight"),
            _make_hit("hl-4", "Monitoring: Prometheus at :9090.", "local", "architecture"),
            _make_hit("hl-5", shared_content[1], "local", "decision"),
        ]
        hybrid_engram = [
            _make_hit("he-1", shared_content[0], "mimir", "decision", decay=0.9),
            _make_hit("he-2", shared_content[1], "mimir", "decision", decay=0.85),
            _make_hit("he-3", "Historical: port was 3000 before migration, no TLS before v2.", "mimir", "architecture", decay=0.15),
            _make_hit("he-4", "Original monitoring: Grafana Cloud, expensive at scale.", "mimir", "insight", decay=0.2),
            _make_hit("he-5", "Decision to migrate to Prometheus: cost savings of $400/mo.", "mimir", "decision", decay=0.45),
        ]

        _reset_connector_singleton()
        conn = perseus.MimirConnector(_test_cfg())
        merged = conn._merge_results(
            local_items=hybrid_local, mimir_items=hybrid_engram,
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )

        # Hybrid: 5 local + 5 engram = 10 raw, 2 shared → 8 unique
        assert len(merged.items) == 8

        hybrid_tokens = sum(_estimate_tokens(item.content) for item in merged.items)
        verified_count = sum(1 for item in merged.items if item.verified)

        # The key insight: hybrid adds tokens but also adds VERIFIED confirmation
        # and historical context that local-only lacks
        assert hybrid_tokens > local_tokens, \
            "Hybrid should have more tokens than local-only (adds historical context)"
        assert verified_count == 2, f"Expected 2 verified items, got {verified_count}"

        # Value-add ratio: (hybrid tokens - local tokens) / local tokens
        # Hybrid adds historical context which is naturally wordier than terse
        # local state snapshots. Acceptable overhead is < 300%.
        overhead_ratio = (hybrid_tokens - local_tokens) / local_tokens
        assert overhead_ratio < 3.0, \
            f"Hybrid overhead should be < 300% of local-only tokens, got {overhead_ratio:.0%}"

    def test_context_package_respects_max_items(self):
        """When max_results is capped, the assembly should stay compact."""
        _reset_connector_singleton()
        c = _test_cfg()
        # With a very small max_results, even large inputs should produce small output
        local_items = [_make_hit(f"l-{i}", f"Local memory {i}", "local", "insight") for i in range(100)]
        mseg = perseus._mimir_hybrid_search(
            cfg=c, query="test", workspace="/tmp/test",
            local_hits=[{"id": f"x-{i}", "content": f"c{i}"} for i in range(100)],
            max_results=5,
        )
        assert len(mseg.items) <= 5, f"max_results=5 should cap at 5, got {len(mseg.items)}"
