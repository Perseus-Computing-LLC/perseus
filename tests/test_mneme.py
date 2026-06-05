"""
Tests for Mnēmē — in-process BM25 persistent memory.

Covers:
  - resolve_mneme() directive (missing query, results, no hits)
  - resolve_memory() backend routing (file vs mneme)
"""

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
    """Minimal config with mneme backend enabled."""
    c = cfg()
    c["memory"]["backend"] = "mneme"
    return c


def _file_cfg() -> dict:
    """Minimal config with the default file backend."""
    c = cfg()
    c["memory"]["backend"] = "file"
    return c


# ---------------------------------------------------------------------------
# resolve_mneme() — @mneme directive
# ---------------------------------------------------------------------------

class TestResolveMneme:
    def test_missing_query_returns_warning(self):
        result = perseus.resolve_mneme("", cfg())
        assert "@memory search requires" in result
        assert "query=" in result

    def test_no_hits_returns_info_message(self):
        with patch.object(perseus, "_mneme_recall", return_value=[]):
            result = perseus.resolve_mneme('query="test search"', cfg())
        assert "No Mnēmē memories matched" in result

    def test_hits_rendered_as_list(self):
        hits = [
            {"title": "Use Redis", "summary": "Cache sessions in Redis.", "score": 88, "type": "decision"},
            {"title": "Auth lesson", "summary": "JWT tokens expire in 1h.", "score": 75, "type": "lesson"},
        ]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mneme('query="caching"', cfg())

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
            perseus.resolve_mneme('query="x" k=50', cfg())
        assert captured["k"] == 20

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mneme('query="x" k=0', cfg())
        assert captured["k"] == 1

    def test_scope_and_type_forwarded(self):
        captured = {}

        def fake_recall(cfg_, query, k=5, scope=None, type_filter=None, sensitivity=None):
            captured["scope"] = scope
            captured["type_filter"] = type_filter
            captured["sensitivity"] = sensitivity
            return []

        with patch.object(perseus, "_mneme_recall", side_effect=fake_recall):
            perseus.resolve_mneme('query="x" scope="myproject" type="lesson" sensitivity="private"', cfg())

        assert captured["scope"] == "myproject"
        assert captured["type_filter"] == "lesson"
        assert captured["sensitivity"] == "private"

    def test_score_rendered_when_present(self):
        hits = [{"title": "T", "summary": "S", "score": 99}]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mneme('query="x"', cfg())
        assert "99" in result

    def test_optional_fields_absent_does_not_crash(self):
        hits = [{"title": "MinimalHit"}]
        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_mneme('query="x"', cfg())
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
            result = perseus.resolve_memory('query="test"', cfg(), workspace=tmp_path)

        assert called, "_mneme_recall should be called for search mode"
        assert "No Mnēmē memories matched" in result

    def test_search_renders_hits(self, tmp_path):
        hits = [{"title": "Arch decision", "summary": "Chose monorepo.", "score": 80, "type": "decision"}]

        with patch.object(perseus, "_mneme_recall", return_value=hits):
            result = perseus.resolve_memory('query="arch"', cfg(), workspace=tmp_path)

        assert "Arch decision" in result
        assert "Chose monorepo" in result

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
        return _h.md5(canonical, usedforsecurity=False).hexdigest()[:12]
    except TypeError:
        return _h.md5(canonical).hexdigest()[:12]


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
    assert sha_fp.read_text() == "current\n", "Current file must be untouched"
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
    assert new_A.exists() and new_A.read_text().endswith("A content\n")
    assert new_B.exists() and new_B.read_text().endswith("B content\n")

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
    assert sha_fp.read_text().endswith("current\n")
