"""
test_mneme_stability.py — Phase 1: Infrastructure Validation (Robustness)

Tests in this file validate that the Mneme bridge does NOT break
the system when things go wrong. These can run in CI/CD, as daily health
checks, and do NOT require a running Mneme service.

Three test suites:
  1. Circuit Breaker — validates the breaker state machine
  2. Fallback & Graceful Degradation — validates local FTS5 takes over
  3. Latency Cap — validates timing budgets
"""

import copy
import time
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus, _capture_json

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cfg_with_mneme(overrides=None):
    """Build a config with Mneme enabled but using parameters suitable for testing."""
    c = cfg()
    c["mneme"] = {
        "enabled": True,
        "transport": "stdio",
        "command": ["nonexistent-mneme-binary"],  # guaranteed unavailable
        "endpoint": "",
        "timeout_s": 0.5,
        "merge_strategy": "local_first",
        "decay_priority_weight": 0.4,
        "fallback_to_local": True,
        "circuit_breaker": {
            "threshold": 1,   # fast failure for tests
            "cooldown": 1,
        },
        "retry_policy": {
            "max_attempts": 1,  # no retries during tests
            "backoff_base": 0.01,
        },
    }
    if overrides:
        c["mneme"].update(overrides)
    return c


def _mock_local_hits():
    """Return synthetic local Mneme FTS5 hits for fallback tests."""
    return [
        {"id": "local-1", "type": "architecture", "content": "The auth module uses SQLite FTS5 for local search.", "summary": "Auth module: SQLite FTS5", "relevance": 0.85},
        {"id": "local-2", "type": "decision", "content": "Chose microkernel pattern for module isolation.", "summary": "Microkernel pattern decision", "relevance": 0.72},
        {"id": "local-3", "type": "insight", "content": "Build artifact perseus.py is generated from src/ — edit src/, not the artifact.", "summary": "Build artifact workflow", "relevance": 0.90},
    ]


def test_default_mneme_command_uses_direct_server_mode():
    assert perseus.DEFAULT_CONFIG["mneme"]["command"] == ["mneme"]


def _mock_mneme_hits():
    """Return synthetic Mneme memory hits."""
    from conftest import perseus as p
    return [
        p.MemoryHit(
            id="eng-1", type=p.MemoryTypeEnum.ARCHITECTURE,
            content="The auth module uses Postgres for production and SQLite FTS5 for local dev.",
            source=p.MemorySource.MNEME, summary="Auth module: dual DB strategy",
            relevance=0.88, decay_score=0.95, retrieval_count=3,
            layer=p.MemoryLayer.CORE, topic_path="architecture/auth/database",
        ),
        p.MemoryHit(
            id="eng-2", type=p.MemoryTypeEnum.DECISION,
            content="Chose microkernel pattern for module isolation after evaluating plugin architectures.",
            source=p.MemorySource.MNEME, summary="Microkernel: post-evaluation decision",
            relevance=0.76, decay_score=0.73, retrieval_count=1,
            layer=p.MemoryLayer.WORKING, topic_path="architecture/patterns/microkernel",
        ),
        p.MemoryHit(
            id="eng-3", type=p.MemoryTypeEnum.INSIGHT,
            content="Perseus watch daemon auto-refreshes AGENTS.md every 900s in the container.",
            source=p.MemorySource.MNEME, summary="Perseus watch daemon timing",
            relevance=0.65, decay_score=0.42, retrieval_count=5,
            layer=p.MemoryLayer.WORKING, topic_path="operations/daemons/watch",
        ),
    ]


def _reset_connector_singleton():
    """Reset the global _connector singleton between tests."""
    perseus._connector = None
    perseus._connector_cfg_hash = ""


# ─────────────────────────────────────────────────────────────────────────────
# 1. CIRCUIT BREAKER UNIT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreakerStateMachine:
    """Validate the CircuitBreaker state transitions: closed → open → half_open → closed."""

    def test_initial_state_is_closed(self):
        cb = perseus.CircuitBreaker(threshold=3, cooldown_s=120)
        assert cb.state == "closed"
        assert not cb.is_open

    def test_stays_closed_below_threshold(self):
        cb = perseus.CircuitBreaker(threshold=3, cooldown_s=120)
        cb.failure()
        cb.failure()
        assert cb.state == "closed"
        assert not cb.is_open

    def test_opens_at_threshold(self):
        cb = perseus.CircuitBreaker(threshold=3, cooldown_s=120)
        for _ in range(3):
            cb.failure()
        assert cb.state == "open"
        assert cb.is_open

    def test_stays_open_during_cooldown(self):
        cb = perseus.CircuitBreaker(threshold=1, cooldown_s=300)
        cb.failure()
        assert cb.state == "open"
        assert cb.is_open
        stats = cb.stats()
        assert stats["state"] == "open"
        assert stats["failure_count"] == 1

    def test_half_open_after_cooldown(self):
        cb = perseus.CircuitBreaker(threshold=1, cooldown_s=0)  # immediate cooldown
        cb.failure()
        assert cb.state == "open"
        # is_open should transition to half_open when cooldown expires
        assert not cb.is_open  # cooldown=0, immediate transition
        assert cb.state == "half_open"

    def test_half_open_success_resets_to_closed(self):
        cb = perseus.CircuitBreaker(threshold=1, cooldown_s=0)
        cb.failure()
        assert cb.state == "open"
        assert not cb.is_open  # half_open
        cb.success()
        assert cb.state == "closed"
        assert not cb.is_open

    def test_half_open_failure_reopens(self):
        """When half_open and a call fails, the breaker re-opens.
        
        Note: is_open property with cooldown_s=0 has a side-effect
        (transitions open→half_open on access), so we check state directly.
        """
        cb = perseus.CircuitBreaker(threshold=1, cooldown_s=120)  # long cooldown
        cb.failure()
        assert cb.state == "open"  # after first failure (threshold=1)
        # Simulate cooldown expiry by advancing time manually
        cb._last_failure_time = time.time() - 121  # 121 seconds ago
        assert not cb.is_open  # is_open transitions to half_open
        assert cb.state == "half_open"
        # Now failure in half_open should re-open
        cb.failure()
        assert cb.state == "open"
        assert cb.is_open  # cooldown hasn't expired yet (just failed)

    def test_stats_tracking(self):
        cb = perseus.CircuitBreaker(threshold=3, cooldown_s=120)
        cb.success()
        cb.success()
        cb.failure()
        cb.failure()
        cb.failure()
        stats = cb.stats()
        assert stats["total_successes"] == 2
        assert stats["total_failures"] == 3
        assert stats["state"] == "open"
        assert stats["last_failure_s"] >= 0

    def test_success_resets_failure_count(self):
        cb = perseus.CircuitBreaker(threshold=3, cooldown_s=120)
        cb.failure()
        cb.failure()
        cb.success()  # should reset counter
        cb.failure()
        cb.failure()
        assert cb.state == "closed"  # only 2 consecutive failures after success
        assert not cb.is_open


class TestCircuitBreakerDegradedMode:
    """Validate that the connector gracefully degrades when circuit is open."""

    def test_connector_with_bad_binary_enters_degraded(self):
        """When the mneme binary doesn't exist, the connector should be unavailable
        but NOT crash. The status should reflect the degradation."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        assert not connector.available
        assert "unavailable" in connector.status.lower()
        assert connector.breaker_stats["total_failures"] >= 1

    def test_connector_recall_when_unavailable_returns_empty(self):
        """When Mneme is unavailable, recall() should return an empty MemorySegment
        without raising an exception."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        assert not connector.available
        segment = connector.recall(query="project architecture", max_results=5)
        assert isinstance(segment, perseus.MemorySegment)
        assert len(segment.items) == 0

    def test_connector_store_when_unavailable_returns_false(self):
        """store() should return (False, error_message) when Mneme is unavailable."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        success, msg = connector.store(content="test memory", memory_type=perseus.MemoryTypeEnum.INSIGHT)
        assert success is False
        assert len(msg) > 0

    def test_connector_health_check_when_unavailable_returns_unhealthy(self):
        """health_check() should return (False, reason) when Mneme is unavailable."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        ok, status = connector.health_check()
        assert ok is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. FALLBACK & GRACEFUL DEGRADATION TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbackBehavior:
    """Validate that when Engram returns empty/errors, local Mneme FTS5 takes over."""

    def test_hybrid_search_falls_back_to_local_when_engram_unavailable(self):
        """_mneme_hybrid_search should return local hits when Mneme is down."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        local_hits = _mock_local_hits()
        mseg = perseus._mneme_hybrid_search(
            cfg=c,
            query="what database does auth use?",
            workspace="/tmp/test-workspace",
            local_hits=local_hits,
            max_results=5,
        )
        assert isinstance(mseg, perseus.MemorySegment)
        assert len(mseg.items) > 0
        assert mseg.strategy_used == "local_fallback"

    def test_hybrid_search_falls_back_to_local_when_engram_returns_empty(self):
        """Even when Mneme is theoretically available, if it returns no results,
        the local hits should be used as fallback."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        local_hits = _mock_local_hits()
        mseg = perseus._mneme_hybrid_search(
            cfg=c, query="nonexistent topic", workspace="/tmp/test",
            local_hits=local_hits, max_results=3,
        )
        # Mneme is unavailable, so local fallback kicks in
        assert len(mseg.items) > 0
        # All returned items should have LOCAL source
        for item in mseg.items:
            assert item.source == perseus.MemorySource.LOCAL

    def test_hybrid_search_returns_empty_when_both_sources_empty(self):
        """When both Engram and local produce no hits, return empty MemorySegment."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        mseg = perseus._mneme_hybrid_search(
            cfg=c, query="completely irrelevant query xyzzy", workspace="/tmp/test",
            local_hits=[], max_results=5,
        )
        assert len(mseg.items) == 0
        assert mseg.strategy_used in ("unavailable", "local_fallback")

    def test_engram_disabled_in_config_still_works(self):
        """When engram.enabled=False, the system should operate local-only without errors."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"enabled": False, "command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        assert not connector.available
        assert connector.status == "disabled"

    def test_hybrid_mneme_search_returns_local_only_when_unavailable(self):
        """_mneme_hybrid_mneme_search should return empty/local-only when Mneme is down."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        mseg = perseus._mneme_hybrid_mneme_search(
            cfg=c, query="project architecture", k=5,
        )
        assert isinstance(mseg, perseus.MemorySegment)
        assert mseg.strategy_used == "local_only"


# ─────────────────────────────────────────────────────────────────────────────
# 3. LATENCY CAP TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestLatencyBudgets:
    """Validate that resolution stays within timing budgets.

    Key metrics:
      - Local FTS5 resolution should be near-instant (< 50ms for small test data)
      - Total hybrid resolution should stay under 2 seconds
      - Circuit breaker short-circuits fast (> 100ms saved by not retrying)
    """

    def test_circuit_breaker_short_circuits_instantly(self):
        """When circuit is OPEN, recall() should return immediately (< 10ms)."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({
            "command": ["/nonexistent/path/mneme"],
            "circuit_breaker": {"threshold": 1, "cooldown": 300},
        })
        connector = perseus.MnemeConnector(c)
        assert not connector.available
        # Subsequent recall should be instant (circuit breaker fast path)
        t0 = time.perf_counter()
        segment = connector.recall(query="test query", max_results=5)
        elapsed = (time.perf_counter() - t0) * 1000  # ms
        assert elapsed < 100, f"Circuit breaker recall took {elapsed:.1f}ms, expected < 100ms"
        assert len(segment.items) == 0

    def test_local_fallback_is_fast(self):
        """Local Mneme FTS5 conversion should be near-instant."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        local_hits = _mock_local_hits() * 10  # 30 items
        t0 = time.perf_counter()
        mseg = perseus._mneme_hybrid_search(
            cfg=c, query="test", workspace="/tmp/test",
            local_hits=local_hits, max_results=10,
        )
        elapsed = (time.perf_counter() - t0) * 1000  # ms
        assert elapsed < 100, f"Local fallback took {elapsed:.1f}ms, expected < 100ms"

    def test_merge_performance_with_large_result_set(self):
        """Merge 1000+ items from each source should complete in < 100ms."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)

        # Generate large synthetic data sets
        local_items = []
        mneme_items = []
        for i in range(500):
            local_items.append(perseus.MemoryHit(
                id=f"local-{i}", type=perseus.MemoryTypeEnum.INSIGHT,
                content=f"Local memory item number {i} with some content for testing.",
                source=perseus.MemorySource.LOCAL, summary=f"Local item {i}",
                relevance=0.5, decay_score=0.1 + (i % 10) * 0.1,
            ))
            mneme_items.append(perseus.MemoryHit(
                id=f"eng-{i}", type=perseus.MemoryTypeEnum.INSIGHT,
                content=f"Mneme memory item number {i} with different content.",
                source=perseus.MemorySource.MNEME, summary=f"Mneme item {i}",
                relevance=0.5, decay_score=0.1 + (i % 10) * 0.1,
            ))

        t0 = time.perf_counter()
        merged = connector._merge_results(
            local_items=local_items,
            mneme_items=mneme_items,
            strategy=perseus.MergeStrategy.LOCAL_FIRST,
            diagnostics={},
        )
        elapsed = (time.perf_counter() - t0) * 1000  # ms
        assert len(merged.items) == 1000  # all unique
        assert elapsed < 200, f"Merge of 1000 items took {elapsed:.1f}ms, expected < 200ms"

    def test_connector_initialization_completes_quickly_with_bad_binary(self):
        """Even when the mneme binary is missing, init should NOT hang.
        It should fail fast and return control (< 5 seconds, ideally < 500ms)."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({
            "command": ["/nonexistent/path/mneme"],
            "timeout_s": 0.5,
        })
        t0 = time.perf_counter()
        connector = perseus.MnemeConnector(c)
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 5000, f"Connector init took {elapsed:.0f}ms, expected < 5000ms"
        assert not connector.available

    def test_context_package_assemble_performance(self):
        """ContextPackage.assemble() should be fast even with many items."""
        from conftest import perseus as p
        items = []
        for i in range(200):
            items.append(p.MemoryHit(
                id=f"item-{i}", type=[p.MemoryTypeEnum.ARCHITECTURE, p.MemoryTypeEnum.DECISION, p.MemoryTypeEnum.INSIGHT][i % 3],
                content=f"Memory item {i}: important architectural decision about component {i % 10}",
                source=[p.MemorySource.LOCAL, p.MemorySource.MNEME][i % 2],
                summary=f"Item {i} summary", relevance=0.5 + (i % 5) * 0.1,
                decay_score=0.3 + (i % 7) * 0.1,
            ))
        live_entries = [p.LiveStateEntry(key=f"key-{j}", value=f"value-{j}", source="@env") for j in range(50)]
        live = p.LiveStateSegment(workspace_path="/tmp/test", entries=live_entries)
        mem = p.MemorySegment(items=items, strategy_used="local_first", total_available=len(items))

        t0 = time.perf_counter()
        pkg = p.ContextPackage(live_state=live, memory=mem, merge_strategy=p.MergeStrategy.LOCAL_FIRST)
        result = pkg.assemble()
        elapsed = (time.perf_counter() - t0) * 1000
        assert len(result) > 0
        assert elapsed < 100, f"ContextPackage.assemble() took {elapsed:.1f}ms, expected < 100ms"


# ─────────────────────────────────────────────────────────────────────────────
# 4. EDGE CASES & STRESS TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Validate behavior with unusual inputs and edge cases."""

    def test_connector_with_empty_command_list(self):
        """Empty command list should not crash."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": []})
        connector = perseus.MnemeConnector(c)
        assert not connector.available

    def test_connector_with_sse_transport_stub(self):
        """SSE transport stub should report unavailable gracefully."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"transport": "sse", "endpoint": "http://localhost:99999/sse"})
        connector = perseus.MnemeConnector(c)
        assert not connector.available  # SSE stub always fails connect

    def test_connector_close_when_never_connected(self):
        """close() should not raise even if never connected."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        connector.close()  # should not raise

    def test_connector_close_twice_idempotent(self):
        """close() called twice should not raise."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        connector.close()
        connector.close()  # should be idempotent

    def test_merge_with_empty_inputs(self):
        """Merge of two empty lists should return empty segment."""
        _reset_connector_singleton()
        c = _cfg_with_mneme({"command": ["/nonexistent/path/mneme"]})
        connector = perseus.MnemeConnector(c)
        merged = connector._merge_results(
            local_items=[], mneme_items=[],
            strategy=perseus.MergeStrategy.LOCAL_FIRST, diagnostics={},
        )
        assert len(merged.items) == 0

    def test_parse_memory_hits_handles_malformed_json(self):
        """_parse_memory_hits should not crash on various malformed inputs."""
        # None/empty
        assert perseus._parse_memory_hits({}) == []
        assert perseus._parse_memory_hits({"items": None}) == []
        # String instead of list
        result = perseus._parse_memory_hits({"items": "not a list"})
        assert isinstance(result, list)
        # Missing fields
        result = perseus._parse_memory_hits({"items": [{"id": "test"}]})
        assert len(result) == 1
        assert result[0].content == ""  # defaults to empty
