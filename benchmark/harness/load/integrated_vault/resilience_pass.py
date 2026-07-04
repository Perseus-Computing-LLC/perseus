#!/usr/bin/env python3
"""Integrated resilience + soak pass: vault dies mid-load, under concurrency.

Validates the connector hardening arc on the live path:
  perseus#676  init-timeout / exit-diagnostics / singleton-lock
  perseus#678  degraded-signal in active-recall postures
  circuit breaker + retry/backoff

  Phase R1  8 readers hammering recall; kill the vault subprocess mid-flight.
            Assert recalls FAIL FAST (no hang past a bounded deadline) -- a
            render must never block on a dead vault.
  Phase R2  Through the outage, assert the breaker opens (status reports it)
            instead of hammering a dead process.
  Phase R3  Recovery: after breaker cooldown, recall reconnects (connector
            respawns the vault) and succeeds -- no manual intervention.
  Phase S   Soak SOAK_S seconds; assert throughput/latency don't degrade
            between the first and last window (fd/mem-leak smell).

Usage:  python resilience_pass.py [vault_binary]
Exit 0 iff all phases pass.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import tempfile
import threading
import time
from pathlib import Path

from _common import MemoryTypeEnum, find_vault_binary, make_connector

SOAK_S = 20.0
CALL_TIMEOUT = 5.0  # modest, so a genuine hang shows as a bounded outlier


def seed(conn, n=30):
    for i in range(n):
        conn.store(content=f"resilience seed note {i} about wal and recall",
                   memory_type=MemoryTypeEnum.INSIGHT, category="insight",
                   key=f"seed-{i}")


def main():
    vault = find_vault_binary()
    tmp = Path(tempfile.mkdtemp(prefix="perseus_resilience_"))
    db = tmp / "res.db"
    conn = make_connector(vault, db, timeout_s=CALL_TIMEOUT,
                          breaker_threshold=3, breaker_cooldown=4)
    print(f"vault: {vault}\ndb: {db}\nstatus: {conn.status}")
    if not conn.available:
        print("FATAL: not available")
        return 2
    seed(conn)
    print(f"seeded; warm hits={len(conn.recall(query='wal recall', max_results=5).items)}")

    # ---- Phase R1/R2: kill mid-load ----------------------------------------
    print("\n[Phase R1/R2] kill vault mid-load; expect fast-fail + breaker open")
    stop = time.time() + 8.0
    kill_at = time.time() + 2.0
    killed = {"done": False}
    stats = {"ok": 0, "err": 0, "max_outage_lat_ms": 0.0, "hang": 0}

    def hammer():
        while time.time() < stop:
            t = time.time()
            seg = conn.recall(query="wal recall", max_results=5)
            dt = (time.time() - t) * 1000
            if killed["done"]:
                stats["max_outage_lat_ms"] = max(stats["max_outage_lat_ms"], dt)
                if dt > (CALL_TIMEOUT * 1000 * 2 + 500):
                    stats["hang"] += 1
            stats["err" if seg.error else "ok"] += 1

    breaker_opened = {"seen": False}

    def killer():
        while time.time() < kill_at:
            time.sleep(0.05)
        proc = conn._client._process if conn._client else None
        if proc:
            proc.kill()
        killed["done"] = True
        print("  >> vault killed at t+2s")
        for _ in range(60):
            if "circuit breaker" in conn.status.lower():
                breaker_opened["seen"] = True
                print(f"  >> breaker opened: {conn.status}")
                break
            time.sleep(0.1)

    with cf.ThreadPoolExecutor(max_workers=9) as ex:
        [ex.submit(hammer) for _ in range(8)]
        ex.submit(killer)
    print(f"  {stats}\n  breaker opened during outage: {breaker_opened['seen']}")
    r1_pass = stats["hang"] == 0
    r2_pass = breaker_opened["seen"] and stats["err"] > 0

    # ---- Phase R3: recovery -------------------------------------------------
    print("\n[Phase R3] recovery after cooldown")
    time.sleep(5.0)  # > breaker cooldown (4s)
    recovered = False
    for attempt in range(10):
        seg = conn.recall(query="wal recall", max_results=5)
        if not seg.error and seg.items:
            recovered = True
            print(f"  recovered on attempt {attempt+1}: status={conn.status}, "
                  f"hits={len(seg.items)}")
            break
        time.sleep(1.0)
    if not recovered:
        print(f"  NOT recovered: status={conn.status}")

    # ---- Phase S: soak ------------------------------------------------------
    print(f"\n[Phase S] soak {SOAK_S:.0f}s, 8 threads; compare first vs last window")
    if not conn.available:
        conn._ensure_connected()
    windows = []
    sstop = time.time() + SOAK_S
    win_len = 4.0
    state = {"win_start": time.time(), "n": 0, "lat": 0.0, "errs": 0}
    wlock = threading.Lock()

    def soaker():
        while time.time() < sstop:
            t = time.time()
            seg = conn.recall(query="wal recall", max_results=5)
            dt = (time.time() - t) * 1000
            with wlock:
                if time.time() - state["win_start"] >= win_len:
                    windows.append((state["n"], state["lat"] / max(1, state["n"])))
                    state["n"], state["lat"] = 0, 0.0
                    state["win_start"] = time.time()
                state["n"] += 1
                state["lat"] += dt
                if seg.error:
                    state["errs"] += 1

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        [ex.submit(soaker) for _ in range(8)]
    if state["n"]:
        windows.append((state["n"], state["lat"] / state["n"]))
    print(f"  windows (count, mean_ms): {[(n, round(m,1)) for n,m in windows]}")
    print(f"  soak errors: {state['errs']}")
    s_pass = True
    if len(windows) >= 2:
        first_m, last_m = windows[0][1], windows[-1][1]
        s_pass = last_m <= first_m * 2.0 + 5 and state["errs"] == 0
        print(f"  first-window mean={first_m:.1f}ms  last-window mean={last_m:.1f}ms")

    print("\n" + "=" * 60)
    print(f"R1 fast-fail (no hang)     : {'PASS' if r1_pass else 'FAIL'}  "
          f"(max outage latency {stats['max_outage_lat_ms']:.0f}ms, hangs {stats['hang']})")
    print(f"R2 breaker opens on outage : {'PASS' if r2_pass else 'FAIL'}")
    print(f"R3 auto-recovery           : {'PASS' if recovered else 'FAIL'}")
    print(f"S  soak (no degradation)   : {'PASS' if s_pass else 'FAIL'}")
    print("=" * 60)

    import shutil
    time.sleep(0.5)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if (r1_pass and r2_pass and recovered and s_pass) else 1


if __name__ == "__main__":
    sys.exit(main())
