# stdlib imports available from build artifact header
# ─────────────────────── Mnēmē v2 — SQLite FTS5 Index ────────────────────────
# Persistent BM25 index over Perseus-native vault .md files.
# Uses SQLite FTS5 (stdlib sqlite3) — zero dependencies beyond Python.
#
# Architecture:
#   - One SQLite database per vault: {vault_path}/mneme.index
#   - FTS5 virtual table with 'porter unicode61' tokenizer (stemming)
#   - Field weighting via FTS5 native per-column bm25() weights
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
    summary,
    tags,
    topic_path,
    body,
    type,
    scope,
    sensitivity,
    confidence,
    source_path,
    updated,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS mneme_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Schema migration: add sensitivity column to mneme_files if it doesn't exist.
# Runs lazily on first index open — idempotent, safe with existing databases.
_MNEME_MIGRATIONS = [
    "ALTER TABLE mneme_files ADD COLUMN sensitivity TEXT DEFAULT 'team'",
]

# Per-column BM25 weights for FTS5 native weighting (bm25() positional args).
# Column order in CREATE VIRTUAL TABLE: id, title, summary, tags, topic_path, body, type, scope, updated
#   bm25(mneme_fts, 0.0, 3.0, 2.0, 2.0, 1.0, 1.0)  — remaining columns default to 0.0
_MNEME_FIELD_WEIGHTS = {
    "title": 3,
    "summary": 2,
    "tags": 2,
    "topic_path": 1,
    "body": 1,
}


# Process-lifetime connection cache: (index_path, pid) → sqlite3.Connection.
# Avoids paying connect + PRAGMA roundtrips on every operation.
# Keyed by pid so forked processes get their own connection.
_MNEME_CONN_CACHE: dict[tuple[str, int], sqlite3.Connection] = {}


def _mneme_open_index(cfg: dict):
    """Open (or create) the SQLite FTS5 index. Returns sqlite3.Connection.

    Enables WAL mode for concurrent reads. Creates tables on first open.
    Returns None if the vault directory cannot be determined.
    Connections are cached per-process for the lifetime of the interpreter.
    """
    try:
        index_path = _mneme_index_path(cfg)
    except Exception:
        return None

    cache_key = (str(index_path), os.getpid())
    cached = _MNEME_CONN_CACHE.get(cache_key)
    if cached is not None:
        # Check that the cached connection hasn't been closed externally
        # (tests, signal handlers, explicit close). If closed, re-create.
        try:
            cached.execute("SELECT 1")
            return cached
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            del _MNEME_CONN_CACHE[cache_key]

    index_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(index_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row

        # Create tables if needed
        conn.executescript(_MNEME_SCHEMA_SQL)

        # Run schema migrations (idempotent)
        for migration_sql in _MNEME_MIGRATIONS:
            try:
                conn.execute(migration_sql)
            except (sqlite3.OperationalError, sqlite3.IntegrityError):
                pass  # Column already exists — fine

        # M1: Schema migration check — verify the FTS5 table columns match
        # expected schema. If they don't, drop and rebuild.
        # v1 schema: id, title, search_text, type, scope, summary, updated
        # v2 schema: id, title, summary, tags, topic_path, body, type, scope, updated
        expected_columns = {"id", "title", "summary", "tags", "topic_path",
                            "body", "type", "scope", "sensitivity",
                            "confidence", "source_path", "updated"}
        try:
            cursor = conn.execute("PRAGMA table_info(mneme_fts)")
            actual_columns = {row["name"] for row in cursor.fetchall()}
            if actual_columns and actual_columns != expected_columns:
                # Schema mismatch — drop and let re-creation happen on next index
                conn.execute("DROP TABLE IF EXISTS mneme_fts")
                conn.execute("DELETE FROM mneme_files")
                conn.execute("DELETE FROM mneme_meta WHERE key LIKE 'schema_%'")
                conn.executescript(_MNEME_SCHEMA_SQL)
        except Exception:
            pass  # Table doesn't exist yet — fine
        _MNEME_CONN_CACHE[cache_key] = conn
        return conn
    except Exception:
        return None


def _mneme_build_field_columns(doc: dict) -> tuple[str, str, str, str, str]:
    """Return per-field column values for FTS5 native weighting.

    Returns (title, summary, tags, topic_path, body) as a tuple for direct
    column insertion. FTS5's bm25() weights each column at query time via
    _MNEME_FIELD_WEIGHTS, eliminating the need for text repetition.
    """
    title = str(doc.get("title", "") or "")
    summary = str(doc.get("summary", "") or "")
    tags = " ".join(str(t) for t in (doc.get("tags") or []) if t)
    topic = " ".join(str(t) for t in (doc.get("topic_path") or []) if t)
    body = str(doc.get("body", "") or "")
    return (title, summary, tags, topic, body)


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

    # M2: Validate id format at parse time. Must be 1-128 chars of
    # alphanumeric, hyphens, underscores. Reject ids with newlines,
    # NUL bytes, or other characters that break FTS5 / GLOB matching.
    import re as _re
    if not _re.match(r'^[A-Za-z0-9_-]{1,128}$', doc_id):
        return None

    # Body length cap — prevent multi-MB bodies from inflating SQLite memory
    body = body[:1048576] if len(body) > 1048576 else body

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
        return 0

    try:
        # Explicit transaction — all-or-nothing build.
        conn.execute("BEGIN IMMEDIATE")

        # On forced rebuild, clear existing index state so stale
        # entries for deleted files are not left behind.
        if force:
            conn.execute("DELETE FROM mneme_fts")
            conn.execute("DELETE FROM mneme_files")

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

            field_cols = _mneme_build_field_columns(doc)
            now = datetime.now().astimezone().isoformat(timespec="seconds")

            # Remove old entry if it exists
            conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc["id"],))
            conn.execute("DELETE FROM mneme_files WHERE path = ?", (file_path_str,))

            # Insert new entry
            conn.execute(
                "INSERT INTO mneme_fts (id, title, summary, tags, topic_path, body, type, scope, sensitivity, confidence, source_path, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc["id"], field_cols[0], field_cols[1], field_cols[2],
                 field_cols[3], field_cols[4], doc["type"], doc["scope"],
                 doc.get("sensitivity", "team"), str(doc.get("confidence", 1.0)),
                 file_path_str, doc["updated"]),
            )
            conn.execute(
                "INSERT INTO mneme_files (path, mtime, indexed_at, sensitivity) VALUES (?, ?, ?, ?)",
                (file_path_str, mtime, now, doc.get("sensitivity", "team")),
            )
            count += 1

        # Rebuild FTS5 index (necessary after DELETE + INSERT)
        if count > 0:
            conn.execute("INSERT INTO mneme_fts(mneme_fts) VALUES('rebuild')")

        conn.commit()
    except Exception:
        conn.rollback()
        raise  # Let caller handle (mneme_recall catches and returns [])
    finally:
        pass  # Connection is cached for process lifetime; do not close

    return count


def _mneme_search(conn, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None,
                   sensitivity: str | None = None) -> list[dict]:
    """Search the FTS5 index. Returns top-k results as list of dicts.

    Uses FTS5's built-in BM25 ranking. Filters by scope, type, and sensitivity
    if provided. The user query is wrapped as an FTS5 double-quoted phrase to
    prevent operator injection (AND, OR, NOT, NEAR, column prefixes, wildcards).
    """
    if not query or not query.strip():
        return []

    # Wrap the query as an FTS5 phrase to prevent operator injection.
    # FTS5 double-quote escaping: embedded " → "" (two double-quotes).
    stripped = query.strip()
    escaped = stripped.replace('"', '""')
    fts_expr = f'"{escaped}"'

    # Parameterized MATCH — SQL injection is blocked by ? binding.
    # FTS5 expression injection is blocked by phrase-wrapping above.
    params = [fts_expr]

    if scope:
        params.append(scope)
    if type_filter:
        params.append(type_filter)
    if sensitivity:
        params.append(sensitivity)

    scope_clause = "AND mneme_fts.scope = ?" if scope else ""
    type_clause = "AND mneme_fts.type = ?" if type_filter else ""
    sensitivity_clause = "AND mneme_fts.sensitivity = ?" if sensitivity else ""

    sql = (
        "SELECT mneme_fts.id, mneme_fts.title, mneme_fts.type, mneme_fts.scope, "
        "mneme_fts.summary, mneme_fts.updated, mneme_fts.sensitivity, "
        "mneme_fts.confidence, mneme_fts.source_path, "
        "snippet(mneme_fts, 5, '<mark>', '</mark>', '…', 40) AS snippet, "
        "bm25(mneme_fts, 0.0, 3.0, 2.0, 2.0, 1.0, 1.0) AS score "
        "FROM mneme_fts "
        f"WHERE mneme_fts MATCH ? {scope_clause} {type_clause} {sensitivity_clause} "
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
            "sensitivity": row["sensitivity"] or "team",
            "confidence": float(row["confidence"] or 1.0),
            "source_path": row["source_path"] or "",
            "updated": row["updated"] or "",
            "snippet": row["snippet"] or "",
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
            return False

        field_cols = _mneme_build_field_columns(doc)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        file_path_str = str(file_path.resolve())

        # Upsert
        conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc["id"],))
        conn.execute("DELETE FROM mneme_files WHERE path = ?", (file_path_str,))
        conn.execute(
            "INSERT INTO mneme_fts (id, title, summary, tags, topic_path, body, type, scope, sensitivity, confidence, source_path, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc["id"], field_cols[0], field_cols[1], field_cols[2],
             field_cols[3], field_cols[4], doc["type"], doc["scope"],
             doc.get("sensitivity", "team"), str(doc.get("confidence", 1.0)),
             file_path_str, doc["updated"]),
        )
        conn.execute(
            "INSERT INTO mneme_files (path, mtime, indexed_at, sensitivity) VALUES (?, ?, ?, ?)",
            (file_path_str, file_path.stat().st_mtime, now, doc.get("sensitivity", "team")),
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
        # Delete from mneme_fts by document id.
        # mneme_files stores full resolved paths — we match by the filename
        # component (the doc_id with .md suffix). The doc_id is validated
        # to be a safe filesystem name by _mneme_parse_vault_file before
        # it's ever inserted, so a GLOB match with the literal id is safe.
        # We use GLOB (not LIKE) to avoid %/_ metacharacter interpretation.
        escaped_id = doc_id.replace("*", "\\*").replace("?", "\\?").replace("[", "\\[").replace("]", "\\]")
        cursor = conn.execute("DELETE FROM mneme_fts WHERE id = ?", (doc_id,))
        deleted = cursor.rowcount > 0
        # M-5: cross-platform path matching — handle both / and \\ separators.
        # GLOB doesn't have an OR operator, so we OR two separate patterns.
        pattern_fwd = f"*/{escaped_id}.md"
        pattern_bwd = f"*\\\\{escaped_id}.md"
        conn.execute(
            "DELETE FROM mneme_files WHERE path GLOB ? OR path GLOB ?",
            (pattern_fwd, pattern_bwd),
        )
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
        pass  # Connection is cached for process lifetime; do not close


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
        pass  # Connection is cached for process lifetime; do not close


# ─────────────────────────── CLI: perseus memory index ────────────────────────

def _cmd_memory_index(args, cfg) -> None:
    """Handle `perseus memory index {stats,rebuild,search}`."""
    sub = getattr(args, "index_command", None)
    use_json = getattr(args, "json", False)

    if sub == "stats":
        stats = _mneme_index_stats(cfg)
        if use_json:
            import json as _json
            try:
                size_bytes = Path(stats["index_path"]).stat().st_size if stats["available"] else 0
                stats["index_size_bytes"] = size_bytes
            except Exception:
                stats["index_size_bytes"] = 0
            print(_json.dumps(stats, indent=2))
            return
        if not stats["available"]:
            print("Index not available. Vault may not exist yet.")
            return
        print(f"Index: {stats['index_path']}")
        print(f"Documents: {stats['doc_count']}")
        print(f"Files tracked: {stats['indexed_files']}")
        try:
            size_bytes = Path(stats["index_path"]).stat().st_size
            print(f"Index size: {_mneme_fmt_bytes(size_bytes)}")
        except Exception:
            pass
        return

    if sub == "rebuild":
        force = getattr(args, "force", False)
        if not use_json:
            print(f"{'Force-rebuilding' if force else 'Rebuilding'} Mnēmē FTS5 index...")
        count = _mneme_build_index(cfg, force=force)
        stats = _mneme_index_stats(cfg)
        if use_json:
            import json as _json
            print(_json.dumps({
                "indexed": count,
                "total": stats["doc_count"],
                "force": force,
                "available": stats["available"],
            }, indent=2))
        else:
            print(f"Indexed {count} document{'s' if count != 1 else ''}.")
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
        sensitivity = getattr(args, "sensitivity", None) or None
        results = _mneme_recall(cfg, query, k=k, scope=scope, type_filter=type_filter, sensitivity=sensitivity)
        if use_json:
            import json as _json
            print(_json.dumps({
                "query": query,
                "k": k,
                "scope": scope,
                "type": type_filter,
                "sensitivity": sensitivity,
                "count": len(results),
                "results": results,
            }, indent=2, default=str))
            return
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
