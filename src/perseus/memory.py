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
                   type_filter: str | None = None) -> list[dict]:
    """Recall memories via SQLite FTS5 BM25 index.

    Opens a fresh connection per call (WAL mode handles concurrency).
    Falls back to empty list on any failure.

    Returns list of hit dicts (id, type, scope, summary, score), ordered
    by score ascending (lower BM25 = better match), limited to k.
    """
    conn = _mneme_open_index(cfg)
    if conn is None:
        return []
    try:
        return _mneme_search(conn, query, k, scope, type_filter)
    except Exception:
        return []
    finally:
        conn.close()
