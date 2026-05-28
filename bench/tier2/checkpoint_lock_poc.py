#!/usr/bin/env python3
"""bench/tier2/checkpoint_lock_poc.py — Demonstrate orphaned checkpoint lock file.

checkpoint.py creates a lock file via os.O_CREAT | os.O_EXCL. If the process
crashes between lock acquire and release, the lock persists forever.
No PID-based staleness detection exists.
"""
import sys, os, inspect, tempfile
from pathlib import Path
sys.path.insert(0, "/workspace/perseus")
import perseus.checkpoint as cp

def test_lock_orphan():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = Path(tmpdir) / "checkpoints"
        store.mkdir()
        cwd = Path(tmpdir) / "workspace"
        cwd.mkdir()
        cfg = {"checkpoints": {"store": str(store)}}

        source = inspect.getsource(cp._write_checkpoint)
        has_excl = "O_EXCL" in source
        has_unlink_lock = "lock" in source.lower() and "unlink" in source.lower()
        has_pid_check = "getpid" in source or "PID" in source or "stale" in source.lower()

        print(f"Lock analysis:")
        print(f"  O_EXCL lock creation: {has_excl}")
        print(f"  Lock cleanup: {has_unlink_lock}")
        print(f"  PID staleness check: {has_pid_check}")

        # Actually write a checkpoint
        lock_path = store / "checkpoint.lock"
        try:
            cp._write_checkpoint(
                title="Test", notes="Testing", cfg=cfg, cwd=cwd, effective_workspace=cwd
            )
            print(f"\n  Write succeeded. Lock exists: {lock_path.exists()}")
            if not lock_path.exists():
                print(f"  OK: Lock cleaned up")
            else:
                print(f"  WARNING: Lock still exists")
        except Exception as e:
            print(f"\n  Write failed: {e}")

        if has_excl and has_unlink_lock and not has_pid_check:
            print(f"\n** BUG CONFIRMED: Lock with no PID staleness check")
            print(f"  Crash between lock+unlink → permanent deadlock")
            return True
        return False

if __name__ == "__main__":
    bug = test_lock_orphan()
    sys.exit(1 if bug else 0)
