# stdlib imports available from build artifact header
# ─────────────────────── Mnēmē v2 — SQLite FTS5 Index ────────────────────────
# Persistent BM25 index over Perseus-native vault .md files.
# Uses SQLite FTS5 (stdlib sqlite3) — zero dependencies beyond Python.
#
# Architecture:
#   - One SQLite database per vault: {vault_path}/mneme.index
#   - FTS5 virtual table with 'porter unicode61' tokenizer (stemming)
#   - Field weighting via text repetition in a single search_text column
#   - WAL mode for concurrent readers during writes
#   - Incremental updates tracked via mneme_files table (path + mtime)

_MNEME_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mneme_files (
    path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS mneme_fts USING fts5(
    id,
    title,
    search_text,
    type,
    scope,
    summary,
    updated,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS mneme_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Field weight multipliers for the search_text column.
# Higher weights = field text repeated more times before concatenation.
_MNEME_FIELD_WEIGHTS = {
    "title": 3,
    "summary": 2,
    "tags": 2,
    "topic_path": 1,
    "body": 1,
}


def _mneme_open_index(cfg: dict):
    """Open (or create) the SQLite FTS5 index. Returns sqlite3.Connection.

    Enables WAL mode for concurrent reads. Creates tables on first open.
    Returns None if the vault directory cannot be determined.
    """
    try:
        index_path = _mneme_index_path(cfg)
    except Exception:
        return None

    index_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(index_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row

        # Create tables if needed
        conn.executescript(_MNEME_SCHEMA_SQL)
        return conn
    except Exception:
        return None


def _mneme_build_field_text(doc: dict) -> str:
    """Build the search_text column with field weighting via repetition.

    Repeats high-weight fields (title 3×, summary 2×) before concatenation
    so FTS5's BM25 naturally weights them higher.
    """
    parts = []
    title = str(doc.get("title", "") or "")
    if title:
        parts.append(" ".join([title] * _MNEME_FIELD_WEIGHTS["title"]))
    summary = str(doc.get("summary", "") or "")
    if summary:
        parts.append(" ".join([summary] * _MNEME_FIELD_WEIGHTS["summary"]))
    tags = " ".join(str(t) for t in (doc.get("tags") or []) if t)
    if tags:
        parts.append(" ".join([tags] * _MNEME_FIELD_WEIGHTS["tags"]))
    topic = " ".join(str(t) for t in (doc.get("topic_path") or []) if t)
    if topic:
        parts.append(" ".join([topic] * _MNEME_FIELD_WEIGHTS["topic_path"]))
    body = str(doc.get("body", "") or "")
    if body:
        parts.append(body)
    return " ".join(parts)


def _mneme_parse_vault_file(file_path: Path) -> dict | None:
    """Parse a single vault .md file and return structured fields.

    Returns None on error or missing required fields (id, title).
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    fm, body = _parse_frontmatter(text)
    if not fm:
        return None

    doc_id = str(fm.get("id", "") or "")
    title = str(fm.get("title", "") or "")
    if not doc_id or not title:
        return None

    return {
        "id": doc_id,
        "title": title,
        "type": str(fm.get("type", "") or ""),
        "scope": str(fm.get("scope", "") or ""),
        "summary": str(fm.get("summary", "") or ""),
        "tags": [str(t) for t in (fm.get("tags") or []) if t],
        "topic_path": [str(t) for t in (fm.get("topic_path") or []) if t],
        "updated": str(fm.get("updated", "") or ""),
        "body": body,
        "confidence": float(fm.get("confidence", 1.0)),
        "sensitivity": str(fm.get("sensitivity", "team") or "team"),
    }


def _mneme_build_index(cfg: dict, force: bool = False) -> int:
    """Build (or rebuild) the FTS5 index from all vault .md files.

    Returns the number of documents indexed. Skips already-indexed files
    unless force=True.
    """
    conn = _mneme_open_index(cfg)
    if conn is None:
        return 0

    vault_path = _mneme_vault_path(cfg)
    if not vault_path.is_dir():
        conn.close()
        return 0

    try:
        # Load currently indexed files (path → mtime)
        indexed = {}
        for row in conn.execute("SELECT path, mtime FROM mneme_files"):
            indexed[row["path"]] = row["mtime"]

        count = 0
        for md_file in sorted(vault_path.rglob("*.md")):
            file_path_str = str(md_file.resolve())
            try:
                mtime = md_file.stat().st_mtime
            except Exception:
                continue

            if not force and file_path_str in indexed and indexed[file_path_str] == mtime:
                continue

            doc = _mneme_parse_vault_file(md_file)
            if doc is None:
                continue

            search_text = _mneme_build_field_text(doc)
            now = datetime.now().astimezone().isoformat(timespec="seconds")

            # Remove old entry if it exists
            conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc["id"],))
            conn.execute("DELETE FROM mneme_files WHERE path = ?", (file_path_str,))

            # Insert new entry
            conn.execute(
                "INSERT INTO mneme_fts (id, title, search_text, type, scope, summary, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc["id"], doc["title"], search_text, doc["type"], doc["scope"], doc["summary"], doc["updated"]),
            )
            conn.execute(
                "INSERT INTO mneme_files (path, mtime, indexed_at) VALUES (?, ?, ?)",
                (file_path_str, mtime, now),
            )
            count += 1

        # Rebuild FTS5 index (necessary after DELETE + INSERT)
        if count > 0:
            conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")

        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

    return count


def _mneme_search(conn, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None) -> list[dict]:
    """Search the FTS5 index. Returns top-k results as list of dicts.

    Uses FTS5's built-in BM25 ranking. Filters by scope and type if provided.
    """
    if not query or not query.strip():
        return []

    # Escape special FTS5 characters and build query
    safe_query = query.replace('"', '""')
    where_clauses = [f"mneme_fts MATCH '\"{safe_query}\"'"]
    params = []

    if scope:
        where_clauses.append("mneme_fts.scope = ?")
        params.append(scope)
    if type_filter:
        where_clauses.append("mneme_fts.type = ?")
        params.append(type_filter)

    sql = (
        "SELECT mneme_fts.id, mneme_fts.title, mneme_fts.type, mneme_fts.scope, "
        "mneme_fts.summary, mneme_fts.updated, "
        "bm25(mneme_fts) AS score "
        "FROM mneme_fts "
        "WHERE " + " AND ".join(where_clauses) + " "
        "ORDER BY score "
        f"LIMIT {max(1, min(k, 100))}"
    )

    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        return []

    results = []
    for row in rows:
        results.append({
            "id": row["id"],
            "title": row["title"] or "",
            "type": row["type"] or "",
            "scope": row["scope"] or "",
            "summary": row["summary"] or "",
            "score": round(float(row["score"]), 2) if row["score"] is not None else 0.0,
        })
    return results


def _mneme_index_document(cfg: dict, file_path: Path) -> bool:
    """Index (or re-index) a single vault document. Returns True on success."""
    conn = _mneme_open_index(cfg)
    if conn is None:
        return False

    try:
        doc = _mneme_parse_vault_file(file_path)
        if doc is None:
            conn.close()
            return False

        search_text = _mneme_build_field_text(doc)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        file_path_str = str(file_path.resolve())

        # Upsert
        conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc["id"],))
        conn.execute("DELETE FROM mneme_files WHERE path = ?", (file_path_str,))
        conn.execute(
            "INSERT INTO mneme_fts (id, title, search_text, type, scope, summary, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc["id"], doc["title"], search_text, doc["type"], doc["scope"], doc["summary"], doc["updated"]),
        )
        conn.execute(
            "INSERT INTO mneme_files (path, mtime, indexed_at) VALUES (?, ?, ?)",
            (file_path_str, file_path.stat().st_mtime, now),
        )
        conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _mneme_delete_document(cfg: dict, doc_id: str) -> bool:
    """Remove a document from the index by id. Returns True if deleted."""
    conn = _mneme_open_index(cfg)
    if conn is None:
        return False

    try:
        cursor = conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc_id,))
        deleted = cursor.rowcount > 0
        conn.execute("DELETE FROM mneme_files WHERE path LIKE ?", (f"%/{doc_id}.md",))
        if deleted:
            conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")
        conn.commit()
        return deleted
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def _mneme_index_stats(cfg: dict) -> dict:
    """Return diagnostic stats about the index."""
    conn = _mneme_open_index(cfg)
    if conn is None:
        return {"doc_count": 0, "indexed_files": 0, "index_path": "", "available": False}

    try:
        doc_count = conn.execute("SELECT COUNT(*) FROM mneme_fts").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM mneme_files").fetchone()[0]
        index_path = str(_mneme_index_path(cfg))
        return {
            "doc_count": doc_count,
            "indexed_files": file_count,
            "index_path": index_path,
            "available": True,
        }
    except Exception:
        return {"doc_count": 0, "indexed_files": 0, "index_path": "", "available": False}
    finally:
        conn.close()


# ─────────────────────────── CLI: perseus memory index ────────────────────────

def _cmd_memory_index(args, cfg) -> None:
    """Handle `perseus memory index {stats,rebuild,search}`."""
    sub = getattr(args, "index_command", None)

    if sub == "stats":
        stats = _mneme_index_stats(cfg)
        if not stats["available"]:
            print("Index not available. Vault may not exist yet.")
            return
        print(f"Index: {stats['index_path']}")
        print(f"Documents: {stats['doc_count']}")
        print(f"Files tracked: {stats['indexed_files']}")
        # Get file size
        try:
            size_bytes = Path(stats["index_path"]).stat().st_size
            print(f"Index size: {_mneme_fmt_bytes(size_bytes)}")
        except Exception:
            pass
        return

    if sub == "rebuild":
        force = getattr(args, "force", False)
        print(f"{'Force-rebuilding' if force else 'Rebuilding'} Mnēmē FTS5 index...")
        count = _mneme_build_index(cfg, force=force)
        print(f"Indexed {count} document{'s' if count != 1 else ''}.")
        stats = _mneme_index_stats(cfg)
        print(f"Total indexed: {stats['doc_count']}")
        return

    if sub == "search":
        query = (getattr(args, "query", "") or "").strip()
        if not query:
            print("Error: --query is required for index search.", file=sys.stderr)
            sys.exit(2)
        k = max(1, min(20, int(getattr(args, "k", 5) or 5)))
        scope = getattr(args, "scope", None) or None
        type_filter = getattr(args, "type", None) or None
        results = _mneme_recall(cfg, query, k=k, scope=scope, type_filter=type_filter)
        if not results:
            print("No results.")
            return
        print(f"Top {len(results)} results for \"{query}\":")
        for i, r in enumerate(results, 1):
            title = r.get("title", "untitled")
            summary = r.get("summary", "")
            score = r.get("score", 0)
            mem_type = r.get("type", "")
            scope_val = r.get("scope", "")
            print(f"  {i}. {title} [{mem_type}] ({scope_val}) score={score:.1f}")
            if summary:
                print(f"     {summary}")
            print()
        return

    print(f"perseus memory index: unknown subcommand '{sub}'.", file=sys.stderr)
    print("Available: stats, rebuild, search", file=sys.stderr)
    sys.exit(2)


def _mneme_fmt_bytes(n: int) -> str:
    """Format bytes for human display."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
