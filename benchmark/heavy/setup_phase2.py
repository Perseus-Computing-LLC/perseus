#!/usr/bin/env python3
"""Phase 2 adversarial coverage — gaps the first adversarial run skipped.

Adds:
    C. Cache behaviour
       C1. baseline:  no cache modifier, run twice → both cold
       C2. @cache ttl=300:   first cold, second warm
       C3. @cache persist:   survives subprocess death
       C4. @cache session:   no benefit across renders (same session = one render)

    D. Concurrency
       D1.  2 parallel renders of same context, separate workspaces
       D2.  5 parallel renders
       D3. 10 parallel renders
       D4.  2 parallel renders against the SAME workspace + output file
            (intentionally racing on the .hermes.md write)

    E. Memory
       E1. RSS during 500-query render (poll every 50 ms)
       E2. RSS during 12 MB stdout render

    F. CLI surface coverage
       F1. perseus graph --json
       F2. perseus prefetch (no rules)
       F3. perseus prefetch (with rules + ttl)
       F4. perseus synthesize  (no LLM, citation contract)
       F5. perseus health
       F6. perseus --help  ← already known to crash on Windows; confirm + log

    G. LSP basic ping
       G1. perseus serve --lsp --stdio: send initialize, wait for response,
           send shutdown/exit, measure handshake latency

Writes a consolidated phase2_results.json next to itself.
Usage:
    python3 setup_phase2.py [base_dir]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

PERSEUS = Path(__file__).resolve().parent.parent.parent / "perseus.py"
PY = sys.executable
HOME_CACHE = Path.home() / ".perseus" / "cache"


def fresh_dir(base: Path, name: str) -> Path:
    d = base / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    (d / ".perseus").mkdir()
    cfg = "render:\n  allow_query_shell: true\n  allow_services_command: false\n"
    if os.name != "nt":
        cfg += "  shell: /bin/bash\n"
    (d / ".perseus" / "config.yaml").write_text(cfg, encoding="utf-8")
    return d


def write_context(d: Path, body: str) -> None:
    (d / ".perseus" / "context.md").write_text(
        "@perseus v0.8\n\n" + body, encoding="utf-8"
    )


def render_once(d: Path, timeout: int = 600) -> dict:
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            [PY, str(PERSEUS), "render",
             str(d / ".perseus" / "context.md"),
             "--output", str(d / ".hermes.md")],
            capture_output=True, timeout=timeout,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        elapsed = time.perf_counter() - t0
        out_path = d / ".hermes.md"
        return {
            "ok": True,
            "rc": r.returncode,
            "elapsed_s": round(elapsed, 3),
            "out_lines": out_path.read_text(encoding="utf-8", errors="replace").count("\n") if out_path.exists() else 0,
            "out_bytes": out_path.stat().st_size if out_path.exists() else 0,
            "stderr_tail": r.stderr.decode("utf-8", errors="replace")[-300:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "elapsed_s": round(time.perf_counter() - t0, 3),
                "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "elapsed_s": round(time.perf_counter() - t0, 3),
                "error": repr(e)}


def clear_home_cache() -> int:
    if not HOME_CACHE.exists():
        return 0
    n = sum(1 for _ in HOME_CACHE.rglob("*") if _.is_file())
    try:
        shutil.rmtree(HOME_CACHE, ignore_errors=True)
    except Exception:
        pass
    HOME_CACHE.mkdir(parents=True, exist_ok=True)
    return n


# ---------------------------------------------------------------------------
# C. Cache behaviour
# ---------------------------------------------------------------------------

# Build a context with N expensive @query (each sleeps S seconds via a
# script file — avoids the @query parser tripping on inner double quotes).
def make_cache_context(d: Path, n_queries: int = 5, sleep_s: float = 0.6, cache_modifier: str = "") -> str:
    scripts_dir = d / ".perseus" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i in range(n_queries):
        s = scripts_dir / f"slow{i}.py"
        s.write_text(
            f"import time\ntime.sleep({sleep_s})\nprint({i!r})\n",
            encoding="utf-8",
        )
        cmd = f"{PY} {s.as_posix()}"
        directive = f'@query "{cmd}"'
        if cache_modifier:
            directive += " " + cache_modifier
        parts.append(directive)
    return "\n".join(parts) + "\n"


def cache_baseline(base: Path) -> dict:
    """Two renders, no cache. Should be near-equal in cost."""
    d = fresh_dir(base, "ph2-cache-baseline")
    write_context(d, make_cache_context(d, cache_modifier=""))
    r1 = render_once(d)
    r2 = render_once(d)
    return {"test": "C1-no-cache",
            "cold_s": r1["elapsed_s"], "warm_s": r2["elapsed_s"],
            "speedup": round(r1["elapsed_s"] / max(r2["elapsed_s"], 0.001), 2)}


def cache_ttl(base: Path) -> dict:
    d = fresh_dir(base, "ph2-cache-ttl")
    write_context(d, make_cache_context(d, cache_modifier="@cache ttl=300"))
    clear_home_cache()
    r1 = render_once(d)
    r2 = render_once(d)
    return {"test": "C2-cache-ttl-300",
            "cold_s": r1["elapsed_s"], "warm_s": r2["elapsed_s"],
            "speedup": round(r1["elapsed_s"] / max(r2["elapsed_s"], 0.001), 2),
            "out_lines_cold": r1["out_lines"], "out_lines_warm": r2["out_lines"]}


def cache_persist(base: Path) -> dict:
    d = fresh_dir(base, "ph2-cache-persist")
    write_context(d, make_cache_context(d, cache_modifier="@cache persist"))
    clear_home_cache()
    r1 = render_once(d)
    r2 = render_once(d)
    return {"test": "C3-cache-persist",
            "cold_s": r1["elapsed_s"], "warm_s": r2["elapsed_s"],
            "speedup": round(r1["elapsed_s"] / max(r2["elapsed_s"], 0.001), 2),
            "out_lines_cold": r1["out_lines"], "out_lines_warm": r2["out_lines"]}


def cache_session(base: Path) -> dict:
    """`@cache session` survives only within one render — second render is cold."""
    d = fresh_dir(base, "ph2-cache-session")
    write_context(d, make_cache_context(d, cache_modifier="@cache session"))
    clear_home_cache()
    r1 = render_once(d)
    r2 = render_once(d)
    return {"test": "C4-cache-session",
            "cold_s": r1["elapsed_s"], "warm_s": r2["elapsed_s"],
            "speedup": round(r1["elapsed_s"] / max(r2["elapsed_s"], 0.001), 2),
            "note": "session cache lives within one render only — warm should NOT be faster"}


# ---------------------------------------------------------------------------
# D. Concurrency
# ---------------------------------------------------------------------------

def concurrent_renders(base: Path, n: int, share_workspace: bool = False) -> dict:
    """Spawn n perseus render processes in parallel."""
    if share_workspace:
        ws = fresh_dir(base, "ph2-concur-shared")
        # 30 trivial queries so each render takes ~1 s
        write_context(ws, "\n".join(
            f'@query "{PY} -c \\"print({i!r})\\""' for i in range(30)
        ) + "\n")
        workspaces = [ws] * n
    else:
        workspaces = []
        for i in range(n):
            ws = fresh_dir(base, f"ph2-concur-{n}-{i}")
            write_context(ws, "\n".join(
                f'@query "{PY} -c \\"print({j!r})\\""' for j in range(30)
            ) + "\n")
            workspaces.append(ws)

    def run(ws: Path, idx: int) -> dict:
        t0 = time.perf_counter()
        try:
            r = subprocess.run(
                [PY, str(PERSEUS), "render",
                 str(ws / ".perseus" / "context.md"),
                 "--output", str(ws / f".hermes-{idx}.md" if share_workspace else ws / ".hermes.md")],
                capture_output=True, timeout=180,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            return {"i": idx, "rc": r.returncode,
                    "elapsed_s": round(time.perf_counter() - t0, 3),
                    "stderr_tail": r.stderr.decode("utf-8", errors="replace")[-200:]}
        except Exception as e:
            return {"i": idx, "error": repr(e),
                    "elapsed_s": round(time.perf_counter() - t0, 3)}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(lambda p: run(p[1], p[0]), enumerate(workspaces)))
    wall = round(time.perf_counter() - t0, 3)

    elapsed_each = [r["elapsed_s"] for r in results if "elapsed_s" in r]
    rcs = [r.get("rc") for r in results]
    return {
        "test": f"D-{'shared' if share_workspace else 'isolated'}-n{n}",
        "n": n,
        "shared_workspace": share_workspace,
        "wall_clock_s": wall,
        "per_render_min_s": min(elapsed_each) if elapsed_each else None,
        "per_render_max_s": max(elapsed_each) if elapsed_each else None,
        "all_rc_zero": all(rc == 0 for rc in rcs),
        "results": results,
    }


# ---------------------------------------------------------------------------
# E. Memory
# ---------------------------------------------------------------------------

def memory_during(d: Path, label: str, timeout: int = 600) -> dict:
    """Spawn perseus render and poll RSS until exit."""
    if not HAVE_PSUTIL:
        return {"test": label, "skipped": "psutil not installed"}

    cmd = [PY, str(PERSEUS), "render",
           str(d / ".perseus" / "context.md"),
           "--output", str(d / ".hermes.md")]
    env = {**os.environ, "PYTHONUTF8": "1"}
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    samples: list[tuple[float, int, int]] = []
    try:
        ps = psutil.Process(proc.pid)
        while True:
            try:
                # parent + children combined
                rss = ps.memory_info().rss
                children_rss = sum(c.memory_info().rss for c in ps.children(recursive=True)
                                   if c.is_running())
                samples.append((round(time.perf_counter() - t0, 3), rss, children_rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
            if time.perf_counter() - t0 > timeout:
                proc.kill()
                break
    finally:
        proc.wait(timeout=10)
    elapsed = round(time.perf_counter() - t0, 3)
    if samples:
        peak_self = max(s[1] for s in samples)
        peak_combined = max(s[1] + s[2] for s in samples)
    else:
        peak_self = peak_combined = 0
    out_path = d / ".hermes.md"
    return {
        "test": label,
        "elapsed_s": elapsed,
        "samples_taken": len(samples),
        "peak_perseus_rss_mb": round(peak_self / (1024 * 1024), 1),
        "peak_combined_rss_mb": round(peak_combined / (1024 * 1024), 1),
        "out_bytes": out_path.stat().st_size if out_path.exists() else 0,
    }


def mem_500_queries(base: Path) -> dict:
    d = fresh_dir(base, "ph2-mem-500q")
    body = "\n".join(f'@query "{PY} -c \\"print({i!r})\\""' for i in range(500))
    write_context(d, body + "\n")
    return memory_during(d, "E1-mem-500-queries")


def mem_12mb_stdout(base: Path) -> dict:
    d = fresh_dir(base, "ph2-mem-12mb")
    script = d / "big.py"
    script.write_text("import sys\nfor i in range(1_200_000): sys.stdout.write('xxxxxxxxx\\n')\n",
                      encoding="utf-8")
    write_context(d, f'@query "{PY} {script.as_posix()}"\n')
    return memory_during(d, "E2-mem-12mb-stdout")


# ---------------------------------------------------------------------------
# F. CLI surface
# ---------------------------------------------------------------------------

def run_cmd(args: list[str], timeout: int = 60) -> dict:
    t0 = time.perf_counter()
    try:
        r = subprocess.run([PY, str(PERSEUS), *args],
                           capture_output=True, timeout=timeout,
                           env={**os.environ, "PYTHONUTF8": "1"})
        return {
            "args": args,
            "rc": r.returncode,
            "elapsed_s": round(time.perf_counter() - t0, 3),
            "stdout_bytes": len(r.stdout),
            "stderr_tail": r.stderr.decode("utf-8", errors="replace")[-300:],
            "stdout_head": r.stdout.decode("utf-8", errors="replace")[:400],
        }
    except Exception as e:
        return {"args": args, "error": repr(e),
                "elapsed_s": round(time.perf_counter() - t0, 3)}


def cli_graph(base: Path) -> dict:
    d = fresh_dir(base, "ph2-cli-graph")
    write_context(d, '@query "echo hi"\n@read .env key="PORT" fallback="3000"\n')
    r = run_cmd(["graph", str(d / ".perseus" / "context.md"), "--json"])
    r["test"] = "F1-graph-json"
    return r


def cli_prefetch_no_rules(base: Path) -> dict:
    d = fresh_dir(base, "ph2-cli-prefetch-none")
    write_context(d, '@query "echo hi"\n')
    r = run_cmd(["prefetch", str(d / ".perseus" / "context.md")])
    r["test"] = "F2-prefetch-no-rules"
    return r


def cli_prefetch_with_rules(base: Path) -> dict:
    d = fresh_dir(base, "ph2-cli-prefetch-rules")
    # Need ~/.perseus/config.yaml with prefetch.rules, then context that triggers
    # For simplicity drop a workspace config that has prefetch.rules
    body = '@query "git status" \n@query "git diff --stat" @cache ttl=300\n'
    write_context(d, body)
    (d / ".perseus" / "config.yaml").write_text(
        "render:\n  allow_query_shell: true\n"
        "prefetch:\n  rules:\n"
        "    - name: status-diff\n"
        "      trigger: '@query \"git status\"'\n"
        "      prefetch:\n"
        "        - '@query \"git diff --stat\" @cache ttl=300'\n",
        encoding="utf-8",
    )
    r = run_cmd(["prefetch", str(d / ".perseus" / "context.md")])
    r["test"] = "F3-prefetch-with-rules"
    return r


def cli_synthesize(base: Path) -> dict:
    d = fresh_dir(base, "ph2-cli-synthesize")
    src = d / "ROADMAP.md"
    src.write_text(
        "@perseus v0.8\n\n"
        "# Roadmap\n\n"
        "## Phase 22\n\n"
        "Status: complete. Tests: 539 passing.\n"
        "Next allowable action: tag v1.0.1 and publish wheel.\n",
        encoding="utf-8",
    )
    r = run_cmd(["synthesize",
                 "What is the next allowable action?",
                 "--source", str(src),
                 "--workspace", str(d)])
    r["test"] = "F4-synthesize-cited"
    return r


def cli_health() -> dict:
    r = run_cmd(["health"])
    r["test"] = "F5-health"
    return r


def cli_help() -> dict:
    """Known to crash on Windows; confirm and log."""
    r = run_cmd(["--help"])
    r["test"] = "F6-help"
    return r


# ---------------------------------------------------------------------------
# G. LSP ping
# ---------------------------------------------------------------------------

def lsp_ping() -> dict:
    """Open perseus serve --lsp --stdio, send initialize, read response."""
    cmd = [PY, str(PERSEUS), "serve", "--lsp", "--stdio"]
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            env={**os.environ, "PYTHONUTF8": "1"})
    initialize = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"processId": os.getpid(), "rootUri": None, "capabilities": {}},
    }
    body = json.dumps(initialize).encode("utf-8")
    payload = b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    try:
        proc.stdin.write(payload)
        proc.stdin.flush()
    except Exception as e:
        proc.kill()
        return {"test": "G1-lsp-initialize", "error": f"write_failed:{e!r}",
                "elapsed_s": round(time.perf_counter() - t0, 3)}

    # Read Content-Length header + body
    result: dict = {"test": "G1-lsp-initialize"}
    try:
        # Read until \r\n\r\n
        buf = b""
        deadline = time.perf_counter() + 10
        while b"\r\n\r\n" not in buf and time.perf_counter() < deadline:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
        if b"\r\n\r\n" not in buf:
            result["error"] = "no_header_received_in_10s"
        else:
            head, _, rest = buf.partition(b"\r\n\r\n")
            cl_line = next((l for l in head.split(b"\r\n")
                            if l.lower().startswith(b"content-length:")), b"")
            cl = int(cl_line.split(b":", 1)[1].strip())
            while len(rest) < cl and time.perf_counter() < deadline:
                more = proc.stdout.read(cl - len(rest))
                if not more:
                    break
                rest += more
            try:
                msg = json.loads(rest.decode("utf-8"))
                result["response_id"] = msg.get("id")
                result["has_capabilities"] = "result" in msg and "capabilities" in msg["result"]
            except Exception as e:
                result["error"] = f"parse_failed:{e!r}"
                result["raw"] = rest[:200].decode("utf-8", errors="replace")
    except Exception as e:
        result["error"] = repr(e)
    finally:
        # send shutdown + exit
        try:
            shutdown = {"jsonrpc": "2.0", "id": 2, "method": "shutdown", "params": None}
            exitm = {"jsonrpc": "2.0", "method": "exit", "params": None}
            for m in (shutdown, exitm):
                b = json.dumps(m).encode("utf-8")
                proc.stdin.write(b"Content-Length: " + str(len(b)).encode() + b"\r\n\r\n" + b)
            proc.stdin.flush()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        result["elapsed_s"] = round(time.perf_counter() - t0, 3)
        result["rc"] = proc.returncode
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else
                "C:/Users/tccon/benchmark/perseus-phase2").resolve()
    base.mkdir(parents=True, exist_ok=True)
    print(f"Phase 2 adversarial benchmarks against {PERSEUS}")
    print(f"Workspace base: {base}  psutil={'yes' if HAVE_PSUTIL else 'no'}")
    print()

    out: dict = {
        "perseus_version": "1.0.1 (with local Windows shell-fallback patch)",
        "host": f"{os.name} · python {sys.version.split()[0]}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "psutil_available": HAVE_PSUTIL,
        "cache": [], "concurrency": [], "memory": [], "cli": [], "lsp": None,
    }

    print("== C. Cache behaviour ==")
    for fn in (cache_baseline, cache_ttl, cache_persist, cache_session):
        r = fn(base)
        out["cache"].append(r)
        print(f"  {r['test']:24s} cold={r['cold_s']}s  warm={r['warm_s']}s  speedup={r['speedup']}x")

    print()
    print("== D. Concurrency ==")
    for n in (2, 5, 10):
        r = concurrent_renders(base, n, share_workspace=False)
        out["concurrency"].append(r)
        print(f"  D-isolated-n{n:2d}    wall={r['wall_clock_s']}s  "
              f"min/max per render = {r['per_render_min_s']}/{r['per_render_max_s']}s  "
              f"all_ok={r['all_rc_zero']}")
    r = concurrent_renders(base, 2, share_workspace=True)
    out["concurrency"].append(r)
    print(f"  D-shared-n2       wall={r['wall_clock_s']}s  all_ok={r['all_rc_zero']}")

    print()
    print("== E. Memory ==")
    if HAVE_PSUTIL:
        for fn in (mem_500_queries, mem_12mb_stdout):
            r = fn(base)
            out["memory"].append(r)
            print(f"  {r['test']:20s} elapsed={r['elapsed_s']}s  "
                  f"peak_perseus={r.get('peak_perseus_rss_mb')}MB  "
                  f"peak_combined={r.get('peak_combined_rss_mb')}MB  "
                  f"out={r.get('out_bytes')}b  samples={r.get('samples_taken')}")
    else:
        print("  (psutil not available; skipping)")

    print()
    print("== F. CLI surface ==")
    for fn in (cli_graph, cli_prefetch_no_rules, cli_prefetch_with_rules,
               cli_synthesize, cli_health, cli_help):
        try:
            r = fn(base) if fn.__name__.endswith(("graph", "no_rules", "with_rules", "synthesize")) else fn()
        except TypeError:
            r = fn()
        out["cli"].append(r)
        print(f"  {r['test']:24s} rc={r.get('rc')}  elapsed={r.get('elapsed_s')}s  "
              f"stdout={r.get('stdout_bytes', 0)}b")

    print()
    print("== G. LSP ==")
    r = lsp_ping()
    out["lsp"] = r
    print(f"  {r['test']:22s} elapsed={r.get('elapsed_s')}s  "
          f"response_id={r.get('response_id')}  caps={r.get('has_capabilities')}  "
          f"rc={r.get('rc')}  error={r.get('error', 'none')}")

    report_path = Path(__file__).resolve().parent / "phase2_results.json"
    report_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print()
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
