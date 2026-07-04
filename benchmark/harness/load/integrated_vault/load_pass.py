#!/usr/bin/env python3
"""Integrated Perseus -> Perseus Vault load pass.

FIRST load test of the *integrated* path (the vault's own concurrency arc hit
~4,242 req/s in isolation; the connector path had never been exercised under
concurrency). Drives real load through a `MnemeConnector` -> MCP stdio -> vault
against a seeded temp DB.

  Phase 0  Seed a real dataset so recall returns ranked results.
  Phase A  Concurrency CORRECTNESS: N threads share ONE connector (exactly how
           `perseus mcp serve` shares one vault subprocess). The stdio client
           serializes exchanges under _call_lock and correlates replies by
           req_id -- assert 0 errors, every reply well-formed, NO cross-talk.
  Phase B  Sustained THROUGHPUT + latency (serialized ceiling ~= 1/service).
  Phase C  MIXED read/write: writers `remember` while readers `recall` -- the
           WAL two-writer path + the cohere busy-retry (perseus-vault#449).

Usage:  python load_pass.py [vault_binary] [--keep]
Exit 0 iff Phase A and Phase C pass (correctness gates); B is informational.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys
import tempfile
import time
from pathlib import Path

from _common import MemoryTypeEnum, find_vault_binary, make_connector, pct

KEEP = "--keep" in sys.argv

TOPICS = [
    ("sqlite wal checkpoint tuning", "architecture"),
    ("aes-256-gcm at-rest encryption key rotation", "architecture"),
    ("circuit breaker cooldown threshold policy", "decision"),
    ("ebbinghaus decay scoring for recall ranking", "insight"),
    ("mcp stdio json-rpc framing and req_id correlation", "architecture"),
    ("fts5 bm25 hybrid vector search blend weights", "decision"),
    ("cohere maintenance write-lock busy retry backoff", "insight"),
    ("workspace hash scoping for memory isolation", "decision"),
    ("bi-temporal history valid-time vs transaction-time", "architecture"),
    ("connector version-skew tool alias detection", "insight"),
]
TYPE = {"architecture": MemoryTypeEnum.ARCHITECTURE,
        "decision": MemoryTypeEnum.DECISION,
        "insight": MemoryTypeEnum.INSIGHT}


def seed(conn, per_topic=12):
    ok = err = 0
    for i in range(per_topic):
        for j, (topic, cat) in enumerate(TOPICS):
            content = (f"Note {i} on {topic}. Detail variant {i}-{j}: "
                       f"covers {topic} with specifics and rationale #{i}.")
            success, res = conn.store(
                content=content, memory_type=TYPE[cat], category=cat,
                key=f"{cat}-{j}-{i}", importance=0.5 + (i % 5) * 0.1,
                tags=[cat, f"topic{j}"])
            ok += 1 if success else 0
            if not success:
                err += 1
                if err <= 3:
                    print(f"  seed error: {res}")
    return ok, err


def main():
    vault = find_vault_binary()
    tmp = Path(tempfile.mkdtemp(prefix="perseus_loadpass_"))
    db = tmp / "loadpass.db"
    print(f"vault: {vault}\ndb:    {db}")

    conn = make_connector(vault, db, breaker_threshold=50)
    print(f"connect status: {conn.status}")
    if not conn.available:
        print("FATAL: connector not available; aborting.")
        return 2

    print("\n[Phase 0] seeding ...")
    t0 = time.time()
    ok, serr = seed(conn)
    print(f"  seeded {ok} entities ({serr} errors) in {time.time()-t0:.1f}s")
    probe = conn.recall(query=TOPICS[0][0], max_results=5)
    print(f"  warm recall: {len(probe.items)} hits, err={probe.error!r}")

    # ---- Phase A: concurrency correctness -----------------------------------
    print("\n[Phase A] concurrency correctness (32 threads x 40 recalls, shared connector)")
    A_THREADS, A_EACH = 32, 40
    res = {"err": 0, "empty": 0, "crosstalk": 0, "ok": 0}
    lat = []

    def recall_job(n):
        topic, _ = TOPICS[n % len(TOPICS)]
        first, second = topic.split()[0].lower(), topic.split()[1].lower()
        t = time.time()
        seg = conn.recall(query=topic, max_results=5)
        dt = (time.time() - t) * 1000
        if seg.error:
            return ("err", dt, seg.error)
        if not seg.items:
            return ("empty", dt, None)
        blob = " ".join((h.content or "") for h in seg.items).lower()
        if first not in blob and second not in blob:
            return ("crosstalk", dt, blob[:80])
        return ("ok", dt, None)

    with cf.ThreadPoolExecutor(max_workers=A_THREADS) as ex:
        for f in cf.as_completed([ex.submit(recall_job, i)
                                  for i in range(A_THREADS * A_EACH)]):
            kind, dt, extra = f.result()
            res[kind] += 1
            lat.append(dt)
            if kind in ("err", "crosstalk") and res[kind] <= 3:
                print(f"    {kind}: {extra}")
    print(f"  {res}  (n={sum(res.values())})")
    print(f"  latency ms: p50={pct(lat,50):.1f} p95={pct(lat,95):.1f} "
          f"p99={pct(lat,99):.1f} max={max(lat):.1f}")
    a_pass = res["err"] == 0 and res["crosstalk"] == 0 and res["empty"] == 0

    # ---- Phase B: sustained throughput --------------------------------------
    print("\n[Phase B] sustained throughput (16 threads, 8s)")
    B_THREADS, DUR = 16, 8.0
    stop = time.time() + DUR
    b_lat, b = [], {"ok": 0, "err": 0}

    def sustained():
        i = 0
        while time.time() < stop:
            topic, _ = TOPICS[i % len(TOPICS)]
            i += 1
            t = time.time()
            seg = conn.recall(query=topic, max_results=5)
            b_lat.append((time.time() - t) * 1000)
            b["err" if seg.error else "ok"] += 1

    tb = time.time()
    with cf.ThreadPoolExecutor(max_workers=B_THREADS) as ex:
        [ex.submit(sustained) for _ in range(B_THREADS)]
    elapsed = time.time() - tb
    print(f"  {b['ok']} recalls, {b['err']} errors in {elapsed:.1f}s -> "
          f"{b['ok']/elapsed:.0f} recall/s")
    print(f"  latency ms: p50={pct(b_lat,50):.1f} p95={pct(b_lat,95):.1f} "
          f"p99={pct(b_lat,99):.1f} max={max(b_lat):.1f}")

    # ---- Phase C: mixed read/write ------------------------------------------
    print("\n[Phase C] mixed read/write (12 readers + 4 writers, 6s)  -- #449 busy-retry")
    cstop = time.time() + 6.0
    c = {"r_ok": 0, "r_err": 0, "w_ok": 0, "w_err": 0, "crosstalk": 0}

    def reader():
        i = 0
        while time.time() < cstop:
            topic, _ = TOPICS[i % len(TOPICS)]
            first, second = topic.split()[0].lower(), topic.split()[1].lower()
            i += 1
            seg = conn.recall(query=topic, max_results=5)
            if seg.error:
                c["r_err"] += 1
            else:
                c["r_ok"] += 1
                if seg.items:
                    blob = " ".join((h.content or "") for h in seg.items).lower()
                    if first not in blob and second not in blob:
                        c["crosstalk"] += 1

    def writer(wid):
        i = 0
        while time.time() < cstop:
            topic, cat = TOPICS[i % len(TOPICS)]
            success, res_ = conn.store(
                content=f"live-write w{wid} n{i} on {topic}",
                memory_type=TYPE[cat], category=cat, key=f"live-{wid}-{i%20}",
                importance=0.6, tags=[cat, "live"])
            c["w_ok" if success else "w_err"] += 1
            if not success and c["w_err"] <= 3:
                print(f"    write err: {res_}")
            i += 1

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        [ex.submit(reader) for _ in range(12)]
        [ex.submit(writer, w) for w in range(4)]
    print(f"  {c}")
    c_pass = c["r_err"] == 0 and c["w_err"] == 0 and c["crosstalk"] == 0

    print("\n" + "=" * 60)
    print(f"Phase A correctness : {'PASS' if a_pass else 'FAIL'}  {res}")
    print(f"Phase B throughput  : {b['ok']/elapsed:.0f} recall/s (serialized ceiling)")
    print(f"Phase C mixed r/w   : {'PASS' if c_pass else 'FAIL'}  {c}")
    print("=" * 60)

    if not KEEP:
        import shutil
        time.sleep(0.5)  # let the subprocess release the db handle on Windows
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if (a_pass and c_pass) else 1


if __name__ == "__main__":
    sys.exit(main())
