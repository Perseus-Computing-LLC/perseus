# stdlib imports available from build artifact header


def _mneme_vault_path(cfg: dict) -> Path:
    """Resolve the Mnēmē v2 vault directory from config or auto-detect.

    Resolution order:
      1. memory.mneme_vault_path from config (if set)
      2. Auto-detect: $PERSEUS_HOME/memory/vault
      3. Default path even if it doesn't exist (returns empty list)
    """
    raw = cfg.get("memory", {}).get("mneme_vault_path", "").strip()
    if raw:
        return Path(raw).expanduser()

    # Auto-detect: $PERSEUS_HOME/memory/vault
    vault = PERSEUS_HOME / "memory" / "vault"
    if vault.is_dir():
        return vault

    # Return the default even if it doesn't exist
    return vault


def _mneme_index_path(cfg: dict) -> Path:
    """Resolve the SQLite FTS5 index path."""
    raw = cfg.get("memory", {}).get("mneme_index_path", "").strip()
    if raw:
        return Path(raw).expanduser()
    return _mneme_vault_path(cfg) / "mneme.index"


def _mneme_recall(cfg: dict, query: str, k: int = 5,
                   scope: str | None = None,
                   type_filter: str | None = None,
                   sensitivity: str | None = None) -> list[dict]:
    """Recall memories via SQLite FTS5 BM25 index.

    Uses a process-lifetime cached connection (WAL mode handles concurrency).
    Lazily builds the index if empty (first-call initialization).
    Falls back to empty list on any failure.
    """
    conn = _mneme_open_index(cfg)
    if conn is None:
        return []
    try:
        # Lazy init: build index if no documents indexed yet
        count = conn.execute("SELECT COUNT(*) FROM mneme_fts").fetchone()[0]
        if count == 0:
            _mneme_build_index(cfg)
            count = conn.execute("SELECT COUNT(*) FROM mneme_fts").fetchone()[0]
            if count == 0:
                return []

        return _mneme_search(conn, query, k, scope, type_filter, sensitivity)
    except Exception:
        return []
