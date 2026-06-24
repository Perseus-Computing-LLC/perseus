"""
Tests for Mnēmē v2 — SQLite FTS5 persistent index.

Covers:
  - _mneme_open_index() — create, WAL mode, table creation
  - _mneme_build_index() — bulk import from vault .md files
  - _mneme_search() — BM25 ranking, scope/type filters
  - _mneme_index_document() — single document insert/update
  - _mneme_delete_document() — remove by id
  - _mneme_index_stats() — diagnostic output
  - _mneme_recall() — end-to-end via FTS5
  - Persistence across connections
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

def _write_memory(vault_dir: Path, doc_id: str, title: str, summary: str,
                   scope: str = "test", mem_type: str = "decision",
                   body: str = "") -> Path:
    """Write a Mnēmē v2 memory .md file to the vault directory."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    file_path = vault_dir / f"{doc_id}.md"
    frontmatter = f"""---
schema: 2
id: {doc_id}
title: {title}
type: {mem_type}
summary: {summary}
scope: {scope}
created: '2026-05-27'
tags: [test]
---
{body}
"""
    file_path.write_text(frontmatter, encoding="utf-8")
    return file_path


def _index_cfg(tmp_path: Path) -> dict:
    """Config pointing at a temp vault dir."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    c = cfg()
    c["memory"]["mneme_vault_path"] = str(vault)
    c["memory"]["mneme_index_path"] = str(vault / "mneme.index")
    return c


# ---------------------------------------------------------------------------
# Index open/create
# ---------------------------------------------------------------------------

class TestIndexOpen:
    def test_open_creates_index_file(self, tmp_path):
        c = _index_cfg(tmp_path)
        conn = perseus._mneme_open_index(c)
        assert conn is not None
        conn.close()

        index_path = Path(c["memory"]["mneme_index_path"])
        assert index_path.exists()

    def test_open_creates_tables(self, tmp_path):
        c = _index_cfg(tmp_path)
        conn = perseus._mneme_open_index(c)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {r[0] for r in tables}
        assert "mneme_fts" in table_names
        assert "mneme_files" in table_names
        assert "mneme_meta" in table_names
        conn.close()

    def test_open_uses_wal_mode(self, tmp_path):
        c = _index_cfg(tmp_path)
        conn = perseus._mneme_open_index(c)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        conn.close()


# ---------------------------------------------------------------------------
# Build index
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_build_empty_vault(self, tmp_path):
        c = _index_cfg(tmp_path)
        count = perseus._mneme_build_index(c)
        assert count == 0

    def test_build_indexes_documents(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "test-1", "First Memory", "First summary", scope="test", mem_type="lesson")
        _write_memory(vault, "test-2", "Second Memory", "Second summary", scope="test", mem_type="decision")

        count = perseus._mneme_build_index(c)
        assert count == 2

    def test_build_is_idempotent(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "idem", "Idempotent Test", "Summary")

        count1 = perseus._mneme_build_index(c)
        count2 = perseus._mneme_build_index(c)
        assert count1 == 1
        assert count2 == 0  # no new files

    def test_build_force_reindexes(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "force", "Force Test", "Summary")

        count1 = perseus._mneme_build_index(c)
        count2 = perseus._mneme_build_index(c, force=True)
        assert count1 == 1
        assert count2 == 1  # re-indexed same file

    def test_build_prunes_deleted_files(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        file_path = _write_memory(vault, "stale", "Stale Memory", "delete-me token")
        perseus._mneme_build_index(c)
        file_path.unlink()

        count = perseus._mneme_build_index(c)
        results = perseus._mneme_recall(c, "delete-me", k=5)

        assert count == 0
        assert results == []

    def test_build_removes_corrupt_changed_file(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        file_path = _write_memory(vault, "corrupt", "Corrupt Memory", "corrupt-token")
        perseus._mneme_build_index(c)
        file_path.write_text("---\nschema: 2\nid:\ntitle:\n---\ncorrupt-token\n", encoding="utf-8")

        perseus._mneme_build_index(c)
        results = perseus._mneme_recall(c, "corrupt-token", k=5)

        assert results == []

    def test_build_removes_previous_id_when_frontmatter_id_changes(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        file_path = _write_memory(vault, "old-id", "Old Title", "old-token")
        perseus._mneme_build_index(c)
        file_path.write_text("""---
schema: 2
id: new-id
title: New Title
type: decision
summary: new-token
scope: test
---
body
""", encoding="utf-8")

        perseus._mneme_build_index(c)
        old_results = perseus._mneme_recall(c, "old-token", k=5)
        new_results = perseus._mneme_recall(c, "new-token", k=5)

        assert old_results == []
        assert [r["id"] for r in new_results] == ["new-id"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_returns_results(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "auth", "OAuth Authentication", "OAuth token refresh strategy", scope="perseus")
        _write_memory(vault, "cache", "Redis Caching", "Redis cache invalidation", scope="perseus")
        _write_memory(vault, "unrelated", "Weather Forecast", "Tomorrow will be sunny", scope="weather")
        perseus._mneme_build_index(c)

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "oauth token", k=5)
        conn.close()

        assert len(results) >= 1
        assert results[0]["title"] == "OAuth Authentication"
        assert results[0]["summary"] == "OAuth token refresh strategy"

    def test_search_respects_scope_filter(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "auth", "Auth", "Auth", scope="perseus")
        _write_memory(vault, "weather", "Weather", "Weather", scope="weather")
        perseus._mneme_build_index(c)

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "auth", k=5, scope="perseus")
        conn.close()

        assert len(results) == 1
        assert results[0]["id"] == "auth"

    def test_search_respects_type_filter(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "dec", "Decision about", "A decision about architecture", mem_type="decision")
        _write_memory(vault, "les", "Lesson learned", "A lesson about architecture", mem_type="lesson")
        perseus._mneme_build_index(c)

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "architecture", k=5, type_filter="lesson")
        conn.close()

        assert len(results) >= 1
        assert results[0]["type"] == "lesson"

    def test_search_no_results(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "one", "One", "Summary one")
        perseus._mneme_build_index(c)

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "nonexistent_term_xyz", k=5)
        conn.close()

        assert results == []

    def test_search_returns_score(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "scored", "Scored Memory", "This is scored")
        perseus._mneme_build_index(c)

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "scored", k=5)
        conn.close()

        assert len(results) >= 1
        assert "score" in results[0]
        assert isinstance(results[0]["score"], float)


# ---------------------------------------------------------------------------
# Single document CRUD
# ---------------------------------------------------------------------------

class TestDocumentCRUD:
    def test_index_document_inserts(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        file_path = _write_memory(vault, "insert", "Insert Test", "Inserted")

        success = perseus._mneme_index_document(c, file_path)
        assert success

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "insert", k=5)
        conn.close()
        assert len(results) >= 1
        assert results[0]["title"] == "Insert Test"

    def test_index_document_updates(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        file_path = _write_memory(vault, "update", "Original Title", "Original summary")
        perseus._mneme_index_document(c, file_path)

        # Update the file
        _write_memory(vault, "update", "Updated Title", "Updated summary")
        success = perseus._mneme_index_document(c, file_path)
        assert success

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "updated", k=5)
        conn.close()
        assert len(results) >= 1
        assert results[0]["title"] == "Updated Title"

    def test_index_document_prunes_old_id_when_frontmatter_id_changes(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        file_path = _write_memory(vault, "old_id", "Obsolete Title", "Obsolete summary")
        perseus._mneme_index_document(c, file_path)

        file_path.write_text("""---
schema: 2
id: new_id
title: New Title
type: decision
summary: New summary
scope: test
created: '2026-05-27'
tags: [test]
---
New body
""", encoding="utf-8")
        assert perseus._mneme_index_document(c, file_path)

        conn = perseus._mneme_open_index(c)
        old_results = perseus._mneme_search(conn, "obsolete", k=5)
        new_results = perseus._mneme_search(conn, "new", k=5)
        conn.close()

        assert old_results == []
        assert len(new_results) >= 1
        assert new_results[0]["id"] == "new_id"

    def test_delete_document_removes(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "del", "Delete Me", "To be deleted")
        perseus._mneme_build_index(c)

        deleted = perseus._mneme_delete_document(c, "del")
        assert deleted

        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "delete", k=5)
        conn.close()
        assert results == []

    def test_delete_nonexistent(self, tmp_path):
        c = _index_cfg(tmp_path)
        deleted = perseus._mneme_delete_document(c, "nonexistent")
        assert not deleted


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_empty_index(self, tmp_path):
        c = _index_cfg(tmp_path)
        stats = perseus._mneme_index_stats(c)
        assert stats["available"] is True
        assert stats["doc_count"] == 0
        assert stats["indexed_files"] == 0

    def test_stats_after_build(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "s1", "S1", "Summary 1")
        _write_memory(vault, "s2", "S2", "Summary 2")
        _write_memory(vault, "s3", "S3", "Summary 3")
        perseus._mneme_build_index(c)

        stats = perseus._mneme_index_stats(c)
        assert stats["doc_count"] == 3
        assert stats["indexed_files"] == 3


# ---------------------------------------------------------------------------
# End-to-end via _mneme_recall
# ---------------------------------------------------------------------------

class TestRecallEndToEnd:
    def test_recall_returns_title_and_score(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "e2e-1", "End to End", "This is an end-to-end test", scope="test")
        perseus._mneme_build_index(c)

        results = perseus._mneme_recall(c, "end to end", k=5)
        assert len(results) >= 1
        assert results[0]["title"] == "End to End"
        assert "score" in results[0]
        assert "id" in results[0]
        assert "summary" in results[0]

    def test_recall_empty_vault(self, tmp_path):
        c = _index_cfg(tmp_path)
        results = perseus._mneme_recall(c, "anything", k=5)
        assert results == []

    def test_recall_with_scope_and_type(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "f1", "Project Alpha", "Alpha stuff", scope="alpha", mem_type="decision")
        _write_memory(vault, "f2", "Project Beta", "Beta stuff", scope="beta", mem_type="decision")
        _write_memory(vault, "f3", "Alpha Lesson", "Lesson about alpha", scope="alpha", mem_type="lesson")
        perseus._mneme_build_index(c)

        results = perseus._mneme_recall(c, "alpha", k=5, scope="alpha", type_filter="decision")
        assert len(results) >= 1
        for r in results:
            assert r["scope"] == "alpha"
            assert r["type"] == "decision"

    def test_recall_refreshes_non_empty_index_for_new_files(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "existing", "Existing Memory", "existing-token")
        perseus._mneme_build_index(c)
        _write_memory(vault, "fresh", "Fresh Memory", "fresh-token")

        results = perseus._mneme_recall(c, "fresh-token", k=5)

        assert [r["id"] for r in results] == ["fresh"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_data_survives_reopen(self, tmp_path):
        c = _index_cfg(tmp_path)
        vault = Path(c["memory"]["mneme_vault_path"])
        _write_memory(vault, "persist", "Persistent", "Persists across opens")
        perseus._mneme_build_index(c)

        # Open a new connection — data should still be there
        conn = perseus._mneme_open_index(c)
        results = perseus._mneme_search(conn, "persist", k=5)
        conn.close()
        assert len(results) >= 1
        assert results[0]["title"] == "Persistent"
