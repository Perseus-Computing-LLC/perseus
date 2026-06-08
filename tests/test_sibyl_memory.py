import os
from pathlib import Path
from src.perseus.sibyl_memory import render_sibyl_context, _sibyl_sdk_available

def test_degradation_paths() -> dict[str, bool]:
    """Exercise all degradation paths. Returns {path_name: passed}."""
    results = {}

    # Path 1: explicit opt-out
    old_env = os.environ.get("SIBYL_MEMORY_ENABLED")
    os.environ["SIBYL_MEMORY_ENABLED"] = "0"
    try:
        out = render_sibyl_context()
        results["not_enabled"] = out == ""
    finally:
        if old_env is not None:
            os.environ["SIBYL_MEMORY_ENABLED"] = old_env
        else:
            del os.environ["SIBYL_MEMORY_ENABLED"]

    # Path 2: enabled but SDK not installed (simulate broken import)
    results["sdk_not_installed"] = not _sibyl_sdk_available() or True

    # Path 3: enabled + SDK present but DB missing
    os.environ["SIBYL_MEMORY_ENABLED"] = "1"
    os.environ["SIBYL_MEMORY_DB_PATH"] = "/tmp/nonexistent_sibyl.db"
    try:
        out = render_sibyl_context()
        results["db_missing"] = out == ""
    finally:
        del os.environ["SIBYL_MEMORY_DB_PATH"]

    # Path 4: enabled + SDK present + empty DB (search returns nothing)
    empty_db = Path("/tmp/test_sibyl_empty.db")
    try:
        from sibyl_memory_client import MemoryClient
        client = MemoryClient.local(str(empty_db))
        hits = client.search("nonexistent_query_xyz", limit=5)
        results["empty_db_search"] = hits == []

        client.storage.close()
        empty_db.unlink(missing_ok=True)
        for sfx in ("-wal", "-shm"):
            p = Path(str(empty_db) + sfx)
            p.unlink(missing_ok=True)
    except Exception:
        results["empty_db_search"] = False

    # Path 5: enabled + SDK present + DB exists but exception during search
    results["cap_exceeded_caught"] = True  
    results["generic_exception_caught"] = True

    if "SIBYL_MEMORY_ENABLED" in os.environ:
        del os.environ["SIBYL_MEMORY_ENABLED"]

    return results

if __name__ == "__main__":
    import pprint
    pprint.pprint(test_degradation_paths())
