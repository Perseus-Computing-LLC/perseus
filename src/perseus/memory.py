# stdlib imports available from build artifact header


def _vault_path(cfg: dict) -> Path:
    """Resolve the Perseus Vault v2 vault directory the FTS5 indexer scans.

    Resolution order:
      1. memory.vault_path from config (if set)
      2. memory.store — the directory where per-workspace narrative .md files
         are actually written (see _vault_memory_path / vault_narrative.py)
      3. $PERSEUS_HOME/memory as a final fallback

    The default deliberately tracks ``memory.store`` rather than a ``vault/``
    subdirectory. Narratives are written to ``memory.store`` (default
    ``$PERSEUS_HOME/memory``); if the indexer scanned ``$PERSEUS_HOME/memory/
    vault`` instead, ``rglob("*.md")`` would find no narratives and recall
    would silently return nothing on a stock install.
    """
    raw = cfg.get("memory", {}).get("vault_path", "").strip()
    if raw:
        return Path(raw).expanduser()

    store = str(cfg.get("memory", {}).get("store", "") or "").strip()
    if store:
        return Path(store).expanduser()

    return PERSEUS_HOME / "memory"


def _vault_index_path(cfg: dict) -> Path:
    """Resolve the SQLite FTS5 index path."""
    raw = cfg.get("memory", {}).get("vault_index_path", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _vault_path(cfg) / "vault.index"


def _vault_recall(cfg: dict, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None,
                   sensitivity: str | None = None) -> list[dict]:
    """Recall memories via SQLite FTS5 BM25 index.

    Uses a process-lifetime cached connection (WAL mode handles concurrency).
    Refreshes the incremental index before searching so newly added, changed,
    corrupt, renamed, or deleted vault files cannot leave recall stale.
    Falls back to empty list on any failure.
    """
    conn = _vault_open_index(cfg)
    if conn is None:
        return []
    try:
        _vault_build_index(cfg)
        count = conn.execute("SELECT COUNT(*) FROM vault_fts").fetchone()[0]
        if count == 0:
            return []

        return _vault_search(conn, query, k, scope, type_filter, sensitivity)
    except Exception as exc:
        sys.stderr.write(f"> ⚠ Perseus Vault recall failed (FTS5 index may be corrupt): {exc}\n")
        # #645: page-level corruption that surfaces at query time (the file
        # header still parses, so _vault_open_index succeeded). Quarantine so
        # the NEXT recall recreates + reindexes instead of failing forever.
        # OperationalError (locks, missing FTS5 module) is transient/
        # environmental — never quarantine for it.
        if isinstance(exc, sqlite3.DatabaseError) and not isinstance(exc, sqlite3.OperationalError):
            try:
                _vault_quarantine_corrupt_index(_vault_index_path(cfg), exc)
            except Exception:
                pass
        return []
