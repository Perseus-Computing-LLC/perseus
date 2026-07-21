"""
Tests for Mnēmē — in-process BM25 persistent memory.

Covers:
  - resolve_mimir() directive (missing query, results, no hits)
  - resolve_memory() backend routing (file vs mneme)
"""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mneme_cfg() -> dict:
    """Minimal config with mimir backend enabled."""
    c = cfg()
    c["memory"]["backend"] = "mimir"
    return c


def _file_cfg() -> dict:
    """Minimal config with the default file backend."""
    c = cfg()
    c["memory"]["backend"] = "file"
    return c


def _no_vault_binary_cfg() -> dict:
    """Config whose memory connector points at a guaranteed-absent binary.

    #665: the default connector command is now `["perseus-vault", "serve"]`.
    On a dev machine a `perseus-vault` shim may sit on PATH, which would make
    the connector spuriously "reachable" and defeat tests that assert the
    vault-unreachable copy. Pinning an impossible binary name makes those
    tests hermetic regardless of what's installed.
    """
    c = cfg()
    c["perseus_vault"] = dict(c.get("perseus_vault", {}))
    c["perseus_vault"]["enabled"] = True
    c["perseus_vault"]["command"] = ["perseus-vault-absent-xyz", "serve"]
    return c


# ---------------------------------------------------------------------------
# resolve_mimir() — @mimir directive
# ---------------------------------------------------------------------------

class TestResolveMimir:
    def test_missing_query_returns_warning(self):
        result = perseus.resolve_mimir("", cfg())
        assert "@memory search requires" in result
        assert "query=" in result

    def test_no_hits_returns_info_message(self):
        with patch.object(perseus, "_mneme_recall", return_value=[]):
            result = perseus.resolve_mimir('query="test search"', _no_vault_binary_cfg())
        # #539: the config points at an absent vault binary, so the vault is
        # genuinely unreachable — the message must say so explicitly rather
        # than claiming "fresh install, no memories".
        assert "Vault unreachable" in result

    def test_hits_rendered_as_list(self):
        hits = [
            {"title": "Use Redis", "summary": "Cache sessions in Redis.", "score": 88, "type": "decision"},
            {"title": "Auth lesson", "summary": "JWT tokens expire in 1h.", "score": 75, "type": "lesson"},
        ]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mimir('query="caching"', cfg())

        assert "Use Redis" in result
        assert "Cache sessions in Redis" in result
        assert "Auth lesson" in result
        assert "decision" in result
        assert "lesson" in result

    def test_k_clamped_to_1_20(self):
        captured = {}

        def fake_recall(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            captured["k"] = k
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mimir('query="x" k=50', cfg())
        assert captured["k"] == 20

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mimir('query="x" k=0', cfg())
        assert captured["k"] == 1

    def test_scope_and_type_forwarded(self):
        captured = {}

        def fake_recall(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            captured["scope"] = scope
            captured["type_filter"] = type_filter
            captured["sensitivity"] = sensitivity
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mimir('query="x" scope="myproject" type="lesson" sensitivity="private"', cfg())

        assert captured["scope"] == "myproject"
        assert captured["type_filter"] == "lesson"
        assert captured["sensitivity"] == "private"

    def test_score_rendered_when_present(self):
        hits = [{"title": "T", "summary": "S", "score": 99}]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mimir('query="x"', cfg())
        assert "99" in result

    def test_optional_fields_absent_does_not_crash(self):
        hits = [{"title": "MinimalHit"}]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mimir('query="x"', cfg())
        assert "MinimalHit" in result


# ---------------------------------------------------------------------------
# resolve_memory() — unified mode dispatch (Mnēmē v2)
# ---------------------------------------------------------------------------

class TestResolveMemoryUnified:
    def test_no_query_uses_narrative_mode(self, tmp_path, monkeypatch):
        """Plain @memory with no query → narrative mode, does not call _mneme_recall."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".perseus").mkdir()
        called = []

        def fake_mneme(*a, **kw):
            called.append(True)
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            result = perseus.resolve_memory("", cfg(), workspace=tmp_path)

        assert not called, "_mneme_recall should not be called for narrative mode"

    def test_query_triggers_search_mode(self, tmp_path):
        """@memory query=... → search mode, calls _mneme_recall."""
        called = []

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            called.append({"query": query, "scope": scope})
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            result = perseus.resolve_memory('query="test"', _no_vault_binary_cfg(), workspace=tmp_path)

        assert called, "_mneme_recall should be called for search mode"
        # #539: same reasoning as test_no_hits_returns_info_message — the
        # config points at an absent vault binary, so the message must name
        # that explicitly rather than the generic "fresh install" copy.
        assert "Vault unreachable" in result

    def test_search_renders_hits(self, tmp_path):
        hits = [{"title": "Arch decision", "summary": "Chose monorepo.", "score": 80, "type": "decision"}]

        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_memory('query="arch"', cfg(), workspace=tmp_path)

        assert "Arch decision" in result
        assert "Chose monorepo" in result

    # ── #539 regression: vault-unreachable vs genuinely-no-matches ──────────

    def test_vault_unreachable_is_distinguished_from_no_matches(self, tmp_path):
        """When the vault genuinely errors/is unreachable, the message must
        say so explicitly instead of the generic 'fresh install' copy — the
        core bug in #539 was these two states being indistinguishable."""

        def fake_mneme(*a, **kw):
            return []

        def broken_hybrid_search(*a, **kw):
            raise RuntimeError("MCP handshake timed out")

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme), \
             patch.object(perseus, "_mneme_hybrid_search", side_effect=broken_hybrid_search):
            result = perseus.resolve_memory('query="test"', cfg(), workspace=tmp_path)

        assert "Vault unreachable" in result
        assert "MCP handshake timed out" in result
        # Must NOT claim "fresh install" when the real cause is a live error.
        assert "fresh install" not in result

    def test_genuinely_no_matches_still_shows_fresh_install_message(self, tmp_path):
        """When the vault IS reachable (or cleanly reports zero items, no
        error) and local FTS5 also finds nothing, the original 'fresh
        install' copy is still correct and must be preserved."""

        def fake_mneme(*a, **kw):
            return []

        def clean_empty_segment(*a, **kw):
            return perseus.MemorySegment(items=[], strategy_used="mimir_recall", error="")

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme), \
             patch.object(perseus, "_mneme_hybrid_search", side_effect=clean_empty_segment):
            result = perseus.resolve_memory('query="test"', cfg(), workspace=tmp_path)

        assert "fresh install" in result
        assert "Vault unreachable" not in result

    def test_local_hits_present_but_vault_errored_surfaces_warning(self, tmp_path):
        """Local FTS5 found something, but the vault contribution silently
        failed — the render must still surface that the vault half is
        missing rather than looking like a clean hybrid result."""
        hits = [{"title": "Local only fact", "summary": "x", "score": 50, "type": "insight"}]

        def fake_mneme(*a, **kw):
            return hits

        def broken_hybrid_search(*a, **kw):
            raise RuntimeError("vault subprocess exited")

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme), \
             patch.object(perseus, "_mneme_hybrid_search", side_effect=broken_hybrid_search):
            result = perseus.resolve_memory('query="test"', cfg(), workspace=tmp_path)

        assert "Local only fact" in result
        assert "Vault unreachable" in result
        assert "vault subprocess exited" in result


    def test_search_forwards_type_filter(self, tmp_path):
        captured = {}

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            captured["type_filter"] = type_filter
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            perseus.resolve_memory('query="x" type="decision"', cfg(), workspace=tmp_path)

        assert captured.get("type_filter") == "decision"

    def test_search_forwards_scope(self, tmp_path):
        captured = {}

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            captured["scope"] = scope
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            perseus.resolve_memory('query="x" scope="myproject"', cfg(), workspace=tmp_path)

        assert captured.get("scope") == "myproject"

    def test_explicit_mode_search(self, tmp_path):
        called = []

        def fake_mneme(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            called.append(True)
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_mneme):
            perseus.resolve_memory('mode=search query="x"', cfg(), workspace=tmp_path)

        assert called


# ---------------------------------------------------------------------------
# #128 regression: MD5 → SHA-256 narrative migration
# ---------------------------------------------------------------------------


def _legacy_md5_name(workspace: Path) -> str:
    """Reproduce the pre-1.0.3 hash exactly for fixture setup."""
    import hashlib as _h
    canonical = str(workspace.expanduser().resolve()).encode()
    try:
        return _h.md5(canonical, usedforsecurity=False).hexdigest()[:16]
    except TypeError:
        return _h.md5(canonical).hexdigest()[:16]


def test_mneme_path_auto_migrates_legacy_md5_file(tmp_path):
    """Regression for #128 — opening a workspace with only a legacy MD5
    narrative on disk renames it transparently to the SHA-256 path.

    Without this fix, every pre-1.0.3 user lost their narrative silently
    on the v1.0.3 upgrade (the SHA-256 path didn't exist; Mnēmē reported
    "No narrative yet" and started over, leaving the MD5 file orphaned).
    """
    store = tmp_path / "store"
    store.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_ = {"memory": {"store": str(store)}}

    legacy_name = _legacy_md5_name(workspace)
    legacy_fp = store / f"{legacy_name}.md"
    legacy_fp.write_text(
        f"---\nworkspace: {workspace}\nchecksum: legacy-md5\n---\n\n"
        "## Project Arc\n\nLegacy content from v1.0.2.\n",
        encoding="utf-8",
    )

    # First call should migrate.
    new_fp = perseus._mneme_path(workspace, cfg_)
    assert new_fp.exists(), "SHA-256 path must exist after migration"
    assert not legacy_fp.exists(), "Legacy MD5 file must be renamed away"
    body = new_fp.read_text(encoding="utf-8")
    assert "Legacy content from v1.0.2." in body, (
        "Migration must preserve narrative content verbatim"
    )


def test_mneme_path_no_migration_when_sha256_already_exists(tmp_path):
    """If both files exist, prefer SHA-256 and leave the legacy file alone.

    This protects against double-migration races and ensures we never
    accidentally overwrite a current-scheme narrative.
    """
    store = tmp_path / "store"
    store.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_ = {"memory": {"store": str(store)}}

    legacy_name = _legacy_md5_name(workspace)
    legacy_fp = store / f"{legacy_name}.md"
    legacy_fp.write_text("legacy\n", encoding="utf-8")

    sha_name = perseus._workspace_hash(workspace)
    sha_fp = store / f"{sha_name}.md"
    sha_fp.write_text("current\n", encoding="utf-8")

    result = perseus._mneme_path(workspace, cfg_)
    assert result == sha_fp
    assert sha_fp.read_text(encoding="utf-8") == "current\n", "Current file must be untouched"
    assert legacy_fp.exists(), "Legacy file must NOT be removed in this case"


def test_mneme_path_is_idempotent_after_migration(tmp_path):
    """Calling _mneme_path twice in a row after a migration is a no-op."""
    store = tmp_path / "store"
    store.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg_ = {"memory": {"store": str(store)}}

    legacy_fp = store / f"{_legacy_md5_name(workspace)}.md"
    legacy_fp.write_text(f"---\nworkspace: {workspace}\n---\n\ndata\n", encoding="utf-8")

    p1 = perseus._mneme_path(workspace, cfg_)
    p2 = perseus._mneme_path(workspace, cfg_)
    assert p1 == p2
    assert p1.exists()
    assert p1.read_text(encoding="utf-8").endswith("data\n")


def test_memory_doctor_scan_classifies_files(tmp_path):
    """`memory doctor` (scan-only mode) correctly classifies the store."""
    store = tmp_path / "store"
    store.mkdir()
    cfg_ = {"memory": {"store": str(store)}}

    ws1 = tmp_path / "ws1"; ws1.mkdir()
    ws2 = tmp_path / "ws2"; ws2.mkdir()

    # ws1 has a SHA-256 narrative; ws2 has a legacy MD5 narrative.
    (store / f"{perseus._workspace_hash(ws1)}.md").write_text(
        f"---\nworkspace: {ws1}\n---\n\nsha file\n", encoding="utf-8"
    )
    (store / f"{_legacy_md5_name(ws2)}.md").write_text(
        f"---\nworkspace: {ws2}\n---\n\nmd5 file\n", encoding="utf-8"
    )
    # A pre-Mnēmē README that should be classified as "unknown stem".
    (store / "README.md").write_text("# notes\n", encoding="utf-8")

    scan = perseus._mneme_doctor_scan(cfg_)
    assert len(scan["narrative_files"]) == 3
    assert len(scan["sha256_files"]) == 1
    assert len(scan["legacy_md5_files"]) == 1
    assert len(scan["unknown_files"]) == 1
    assert scan["sha256_files"][0].endswith(f"{perseus._workspace_hash(ws1)}.md")
    assert scan["legacy_md5_files"][0].endswith(f"{_legacy_md5_name(ws2)}.md")


def test_memory_doctor_migrate_renames_legacy_files(tmp_path):
    """`memory doctor --migrate` renames every legacy MD5 file in the store."""
    store = tmp_path / "store"
    store.mkdir()
    cfg_ = {"memory": {"store": str(store)}}

    wsA = tmp_path / "wsA"; wsA.mkdir()
    wsB = tmp_path / "wsB"; wsB.mkdir()
    legacyA = store / f"{_legacy_md5_name(wsA)}.md"
    legacyB = store / f"{_legacy_md5_name(wsB)}.md"
    legacyA.write_text(f"---\nworkspace: {wsA}\n---\n\nA content\n", encoding="utf-8")
    legacyB.write_text(f"---\nworkspace: {wsB}\n---\n\nB content\n", encoding="utf-8")

    result = perseus._mneme_doctor_migrate(cfg_)
    assert len(result["migrated"]) == 2
    assert not legacyA.exists()
    assert not legacyB.exists()

    new_A = store / f"{perseus._workspace_hash(wsA)}.md"
    new_B = store / f"{perseus._workspace_hash(wsB)}.md"
    assert new_A.exists() and new_A.read_text(encoding="utf-8").endswith("A content\n")
    assert new_B.exists() and new_B.read_text(encoding="utf-8").endswith("B content\n")

    # Idempotent: re-running is a no-op.
    second = perseus._mneme_doctor_migrate(cfg_)
    assert second == {"migrated": [], "skipped": [], "errors": []}


def test_memory_doctor_migrate_skips_when_destination_exists(tmp_path):
    """If a SHA-256 file is already there, --migrate skips the legacy file."""
    store = tmp_path / "store"
    store.mkdir()
    cfg_ = {"memory": {"store": str(store)}}

    workspace = tmp_path / "ws"
    workspace.mkdir()
    legacy_fp = store / f"{_legacy_md5_name(workspace)}.md"
    legacy_fp.write_text(f"---\nworkspace: {workspace}\n---\n\nlegacy\n",
                         encoding="utf-8")
    sha_fp = store / f"{perseus._workspace_hash(workspace)}.md"
    sha_fp.write_text(f"---\nworkspace: {workspace}\n---\n\ncurrent\n",
                      encoding="utf-8")

    result = perseus._mneme_doctor_migrate(cfg_)
    assert result["migrated"] == []
    assert len(result["skipped"]) == 1
    old, new, reason = result["skipped"][0]
    assert "exists" in reason
    # Both files still present.
    assert legacy_fp.exists()
    assert sha_fp.exists()
    assert sha_fp.read_text(encoding="utf-8").endswith("current\n")


# ════════════════════════════════════════════════════════════════════════════
# #442 — mimir.auto_inject flag + context_limit=0 suppression
# #441 — per-workspace pack.yaml mimir override
# ════════════════════════════════════════════════════════════════════════════


class TestMimirAutoInject:
    def _cfg(self, **mimir):
        c = cfg()
        # #665: canonical memory key is now `perseus_vault` in DEFAULT_CONFIG.
        c["perseus_vault"].update(mimir)
        # #608: the pre-materialized dump these tests exercise is now the
        # LEGACY opt-in posture (`memory: always`); the default posture is
        # on_demand (retrieval pointer only) — covered by
        # test_memory_posture_profiles.py.
        c["profiles"] = {"default": {"memory": "always"}}
        return c

    def test_auto_inject_false_suppresses_block(self):
        """auto_inject=False returns None without ever consulting the connector."""
        c = self._cfg(enabled=True, auto_inject=False)
        with patch.object(perseus, "_get_connector") as gc:
            assert perseus._mneme_context_inject(c) is None
            gc.assert_not_called()

    def test_context_limit_zero_suppresses_block(self):
        """context_limit=0 means 'inject nothing'; recall is never called."""
        c = self._cfg(enabled=True, auto_inject=True, context_limit=0)
        connector = MagicMock(available=True)
        with patch.object(perseus, "_get_connector", return_value=connector):
            assert perseus._mneme_context_inject(c) is None
            connector.recall.assert_not_called()

    def test_auto_inject_true_injects_block(self):
        """Default path still appends the Persistent Memory block when enabled."""
        c = self._cfg(enabled=True, auto_inject=True, context_limit=5)
        segment = MagicMock(items=[object()], as_markdown="- a durable memory")
        connector = MagicMock(available=True)
        # No hot-entity block available → falls back to recall.
        connector.context.return_value = None
        connector.recall.return_value = segment
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c)
        assert out is not None
        assert out.startswith("## Persistent Memory (Perseus Vault)")
        assert "a durable memory" in out

    def test_hot_entities_injected_via_mimir_context(self):
        """#473: prefer Mimir's mimir_context tool (always_on hot entities first)."""
        c = self._cfg(enabled=True, auto_inject=True, context_limit=5)
        hot_md = (
            "## Mimir Context\n\n"
            "### Always On\n\n"
            "- [always-on] [arch] **db** — SQLite + FTS5 (retrievals: 3, decay: 1.00)\n\n"
            "- [decision] **auth** — JWT tokens (retrievals: 1, decay: 0.80)\n\n"
            "> 2 entities recalled\n"
        )
        connector = MagicMock(available=True)
        connector.context.return_value = hot_md
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c)
        assert out is not None
        assert out.startswith("## Persistent Memory (Perseus Vault)")
        # Hot always_on entity is injected...
        assert "always-on" in out and "db" in out
        # ...the server's own header/footer are stripped...
        assert "## Mimir Context" not in out
        assert "entities recalled" not in out
        # ...and the generic recall fallback is NOT consulted.
        connector.recall.assert_not_called()
        # context() is scoped by configured categories (intent), empty by default.
        connector.context.assert_called_once()
        _, kwargs = connector.context.call_args
        assert kwargs.get("categories") == []
        assert kwargs.get("limit") == 5

    def test_context_categories_scope_hot_injection(self):
        """context_categories is passed through to mimir_context as the intent scope."""
        c = self._cfg(
            enabled=True, auto_inject=True, context_limit=8,
            context_categories=["architecture", "decision"],
        )
        connector = MagicMock(available=True)
        connector.context.return_value = (
            "## Mimir Context\n\n- [architecture] **db** — note (retrievals: 0, decay: 1.00)\n"
        )
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c)
        assert out is not None and "db" in out
        _, kwargs = connector.context.call_args
        assert kwargs.get("categories") == ["architecture", "decision"]

    def test_empty_hot_block_falls_back_to_recall(self):
        """A hot block with no entity bullets falls back to the recall path."""
        c = self._cfg(enabled=True, auto_inject=True, context_limit=5)
        empty_md = "## Mimir Context\n\n\n> 0 entities recalled\n"
        segment = MagicMock(items=[object()], as_markdown="- a recalled memory")
        connector = MagicMock(available=True)
        connector.context.return_value = empty_md
        connector.recall.return_value = segment
        with patch.object(perseus, "_get_connector", return_value=connector):
            out = perseus._mneme_context_inject(c)
        assert out is not None
        assert "a recalled memory" in out
        connector.recall.assert_called_once()

    def test_connector_context_calls_mimir_context_tool(self):
        """MimirConnector.context() calls the mimir_context MCP tool and returns markdown."""
        c = self._cfg(enabled=True)
        connector = perseus.MnemeConnector(c)

        class _StubClient:
            is_connected = True
            calls: list = []

            def call_tool(self, name, arguments):
                self.calls.append((name, arguments))
                return ({"markdown": "## Mimir Context\n\n- [x] **k** — v\n",
                         "total_chars": 24}, None)

        stub = _StubClient()
        connector._client = stub
        md = connector.context(categories=["x"], limit=3)
        assert md is not None and "**k**" in md
        assert stub.calls == [("mimir_context", {"categories": ["x"], "limit": 3})]

    def test_connector_store_calls_mimir_remember_with_typed_fields(self):
        """store() upserts via mimir_remember (not the nonexistent mimir_store),
        with category/key/type/body_json and a string tag list (perseus#525)."""
        c = self._cfg(enabled=True)
        connector = perseus.MnemeConnector(c)

        class _StubClient:
            is_connected = True
            calls: list = []

            def call_tool(self, name, arguments):
                self.calls.append((name, arguments))
                return ({"id": "mem-abc123", "action": "created"}, None)

        stub = _StubClient()
        connector._client = stub
        ok, mem_id = connector.store(
            "we chose postgres 16",
            memory_type=perseus.MemoryTypeEnum.DECISION,
            category="decision",
            key="db-choice",
            tags={"area": "db"},
        )
        assert ok is True and mem_id == "mem-abc123"
        assert len(stub.calls) == 1
        name, args = stub.calls[0]
        assert name == "mimir_remember"
        assert args["category"] == "decision"
        assert args["key"] == "db-choice"
        assert args["type"] == "decision"
        assert args["tags"] == ["area:db"]
        assert json.loads(args["body_json"]) == {"content": "we chose postgres 16"}

    def test_connector_as_of_returns_historical_version(self):
        """MimirConnector.as_of() calls mimir_as_of and returns the past version."""
        c = self._cfg(enabled=True)
        connector = perseus.MnemeConnector(c)

        class _StubClient:
            is_connected = True
            calls: list = []

            def call_tool(self, name, arguments):
                self.calls.append((name, arguments))
                return ({"found": True, "category": "facts", "key": "capital",
                         "body_json": "{\"note\": \"Bonn\"}", "as_of_unix_ms": 123}, None)

        stub = _StubClient()
        connector._client = stub
        got = connector.as_of("facts", "capital", 123)
        assert got is not None and "Bonn" in got["body_json"]
        assert stub.calls == [("mimir_as_of",
                               {"category": "facts", "key": "capital", "as_of_unix_ms": 123})]

    def test_connector_as_of_not_found_returns_none(self):
        """found=false (fact not yet recorded at T) maps to None."""
        c = self._cfg(enabled=True)
        connector = perseus.MnemeConnector(c)

        class _StubClient:
            is_connected = True

            def call_tool(self, name, arguments):
                return ({"found": False, "category": "facts", "key": "capital",
                         "as_of_unix_ms": 1}, None)

        connector._client = _StubClient()
        assert connector.as_of("facts", "capital", 1) is None

    def test_connector_as_of_unavailable_returns_none(self):
        """When Mimir is unavailable, as_of() fails safe to None (never raises)."""
        c = self._cfg(enabled=True)
        connector = perseus.MnemeConnector(c)
        connector._client = None  # not connected → available is False
        assert connector.as_of("facts", "capital", 123) is None


class TestPackMimirMerge:
    def _ws(self, tmp_path, pack_yaml: str) -> Path:
        pdir = tmp_path / ".perseus"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "pack.yaml").write_text(pack_yaml, encoding="utf-8")
        return tmp_path

    # #665: canonical memory key is now `perseus_vault` in DEFAULT_CONFIG; the
    # pack.yaml input still uses the legacy `mimir:` alias to prove the merge
    # accepts it (back-compat read) and lands on the canonical resolved block.
    def test_pack_mimir_overrides_global(self, tmp_path):
        ws = self._ws(tmp_path, "mimir:\n  enabled: false\n  context_limit: 0\n")
        c = cfg()
        c["perseus_vault"]["enabled"] = True
        c["perseus_vault"]["context_limit"] = 10
        perseus._merge_pack_mimir_config(c, ws)
        assert c["perseus_vault"]["enabled"] is False
        assert c["perseus_vault"]["context_limit"] == 0
        # Unrelated global keys survive the merge.
        assert "command" in c["perseus_vault"]

    def test_pack_without_mimir_block_is_noop(self, tmp_path):
        ws = self._ws(tmp_path, "renders:\n  - source: a.md\n    output: b.md\n")
        c = cfg()
        before = copy.deepcopy(c["perseus_vault"])
        perseus._merge_pack_mimir_config(c, ws)
        assert c["perseus_vault"] == before

    def test_pack_deep_merges_nested_dicts(self, tmp_path):
        ws = self._ws(tmp_path, "mimir:\n  circuit_breaker:\n    threshold: 9\n")
        c = cfg()
        c["perseus_vault"].setdefault("circuit_breaker", {"threshold": 3, "cooldown": 120})
        perseus._merge_pack_mimir_config(c, ws)
        assert c["perseus_vault"]["circuit_breaker"]["threshold"] == 9
        # cooldown is preserved (deep merge, not wholesale replace).
        assert c["perseus_vault"]["circuit_breaker"]["cooldown"] == 120

    def test_missing_pack_is_noop(self, tmp_path):
        c = cfg()
        before = copy.deepcopy(c["perseus_vault"])
        perseus._merge_pack_mimir_config(c, tmp_path)  # no .perseus/pack.yaml
        assert c["perseus_vault"] == before


class TestConnectorLaunchHardening:
    """Pre-launch connection-robustness for the Perseus x Vault integration:
    a separate/longer initialize timeout (so the v2.17.0 first-open schema
    migration doesn't spuriously fail the handshake) and a clear exit-code
    diagnostic when the vault refuses to start (bad binary / wrong key)."""

    # enabled=False so __init__ doesn't eagerly spawn a real vault (the default
    # `mimir` command resolves on dev boxes); _init_timeout is read regardless.
    def test_init_timeout_defaults_to_30s(self):
        conn = perseus.MnemeConnector({"perseus_vault": {"enabled": False}})
        assert conn._init_timeout == 30.0

    def test_init_timeout_read_from_config(self):
        conn = perseus.MnemeConnector(
            {"perseus_vault": {"enabled": False, "init_timeout_s": 45}}
        )
        assert conn._init_timeout == 45.0

    def test_stdio_client_carries_separate_init_timeout(self):
        c = perseus._MCPStdioClient(["x"], timeout_s=5.0, init_timeout_s=25.0)
        assert c._timeout == 5.0
        assert c._init_timeout == 25.0
        assert c.last_error is None

    def test_immediate_nonzero_exit_reports_code_not_generic_eof(self):
        # A process that exits non-zero immediately is the shape of a wrong/rotated
        # encryption key (v2.17.0 aborts `serve` on a failed canary) or a broken
        # binary. connect() must fail AND surface the exit code so the failure is
        # diagnosable instead of a silent local-only fallback.
        client = perseus._MCPStdioClient(
            [sys.executable, "-c", "import sys; sys.exit(3)"],
            timeout_s=5.0,
            init_timeout_s=5.0,
        )
        assert client.connect() is False
        assert client.last_error is not None
        assert "code 3" in client.last_error

    def test_tool_compatibility_check_flags_version_skew(self):
        # With dynamic tool-name resolution, a vault that has perseus_vault_*
        # tools is fine — the connector resolves mimir_recall → perseus_vault_recall.
        # The warning fires only when ALL prefix families are missing for a tool.
        conn = perseus.MnemeConnector({"perseus_vault": {"enabled": False}})

        _ALL_TOOLS = [
            "mimir_recall", "mimir_recall_when", "mimir_as_of", "mimir_context",
            "mimir_stats", "mimir_get_entity", "mimir_forget", "mimir_correct",
            "mimir_remember", "mimir_health", "mimir_recall_batch",
            "mimir_promote",
        ]

        class _StubOK:
            def list_tools(self):
                return [{"name": t} for t in _ALL_TOOLS]

        class _StubVault2x:
            def list_tools(self):
                # Vault 2.x with canonical names — should resolve fine
                return [{"name": "perseus_vault_" + t[6:]} for t in _ALL_TOOLS]

        class _StubSkew:
            def list_tools(self):
                # Neither mimir_* nor perseus_vault_* — should warn
                return [{"name": "some_other_tool"}]

        # Legacy names: no warning
        conn._client = _StubOK()
        conn._check_tool_compatibility()
        assert conn._tool_warning is None

        # Vault 2.x canonical names: resolved, no warning
        conn._client = _StubVault2x()
        conn._check_tool_compatibility()
        assert conn._tool_warning is None
        assert conn._tool_names["mimir_recall"] == "perseus_vault_recall"

        # Neither family present: should warn
        conn._client = _StubSkew()
        conn._check_tool_compatibility()
        assert conn._tool_warning is not None
        assert "mimir_recall" in conn._tool_warning          # names the missing tool
