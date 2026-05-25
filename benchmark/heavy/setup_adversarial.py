#!/usr/bin/env python3
"""Adversarial Perseus benchmark harness.

Pushes Perseus's renderer hard and records observed failure modes.

Test plan:
    A. Scaling sweep: 10 / 50 / 100 / 200 / 500 @query blocks.
    B. Edge cases:
       B1. @query with multi-megabyte stdout
       B2. @query that exceeds the 30 s timeout
       B3. @query that emits binary (null bytes)
       B4. @query with shell metacharacters in stdout
       B5. @query referencing a missing script
       B6. @services with 100 entries
       B7. @services with a `command:` that hangs (requires
            allow_services_command + allow_query_shell)
       B8. Malformed YAML in context.md
       B9. 500-line context.md (combined with the scaling sweep)
       B10. Unicode / emoji in @query output

Each test runs against a fresh workspace and records: wall clock, exit
code, output size, observed behaviour. A consolidated JSON report is
written to `adversarial_results.json` next to this script.

Usage:
    python3 setup_adversarial.py [base_dir]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

PERSEUS = Path(__file__).resolve().parent.parent.parent / "perseus.py"
PY = sys.executable

# ---------------------------------------------------------------------------

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


def render(d: Path, timeout: int = 600) -> dict:
    """Run perseus render and return (rc, elapsed, stdout_bytes, stderr)."""
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
        out_lines = out_path.read_text(encoding="utf-8", errors="replace").count("\n") if out_path.exists() else 0
        out_bytes = out_path.stat().st_size if out_path.exists() else 0
        return {
            "ok": True,
            "rc": r.returncode,
            "elapsed_s": round(elapsed, 3),
            "out_lines": out_lines,
            "out_bytes": out_bytes,
            "stderr_tail": r.stderr.decode("utf-8", errors="replace")[-500:],
        }
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        return {"ok": False, "elapsed_s": round(elapsed, 3),
                "error": f"timeout after {timeout}s"}
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {"ok": False, "elapsed_s": round(elapsed, 3),
                "error": repr(e)}


# ---------------------------------------------------------------------------
# A. Scaling sweep
# ---------------------------------------------------------------------------

def make_query_lines(n: int) -> str:
    """Generate n simple @query blocks that each emit one line."""
    lines = []
    for i in range(n):
        # cheap python invocation that prints one line of output
        # avoid spawning shell pipelines
        lines.append(f'@query "{PY} -c \\"print({i!r})\\""')
    return "\n".join(lines) + "\n"


def scaling_sweep(base: Path) -> list[dict]:
    results = []
    for n in (10, 50, 100, 200, 500):
        d = fresh_dir(base, f"adv-scale-{n}")
        write_context(d, make_query_lines(n))
        r = render(d, timeout=900)
        r["test"] = f"scale-{n}-queries"
        r["n_queries"] = n
        if r.get("ok"):
            r["per_query_ms"] = round(r["elapsed_s"] * 1000 / n, 1)
        print(f"  scale-{n:>3}: rc={r.get('rc')}  "
              f"elapsed={r['elapsed_s']}s  lines={r.get('out_lines')}")
        results.append(r)
    return results


# ---------------------------------------------------------------------------
# B. Edge cases
# ---------------------------------------------------------------------------

def edge_big_stdout(base: Path) -> dict:
    """B1: emit ~12 MB to stdout via a single @query."""
    d = fresh_dir(base, "adv-big-stdout")
    # 12 MB worth of text (1.2 M lines of 10 bytes each, fits in 30 s)
    script = d / "big.py"
    script.write_text(
        "import sys\n"
        "for i in range(1_200_000):\n"
        "    sys.stdout.write('xxxxxxxxx\\n')\n",
        encoding="utf-8",
    )
    write_context(d, f'@query "{PY} {script.as_posix()}"\n')
    r = render(d, timeout=180)
    r["test"] = "B1-big-stdout-12MB"
    return r


def edge_timeout(base: Path) -> dict:
    """B2: @query that sleeps 45 s (default timeout is 30 s)."""
    d = fresh_dir(base, "adv-timeout")
    script = d / "slow.py"
    script.write_text("import time\ntime.sleep(45)\nprint('finally')\n",
                      encoding="utf-8")
    write_context(d, f'@query "{PY} {script.as_posix()}"\n')
    r = render(d, timeout=120)
    r["test"] = "B2-timeout-45s"
    return r


def edge_binary(base: Path) -> dict:
    """B3: @query emits binary with null bytes."""
    d = fresh_dir(base, "adv-binary")
    script = d / "bin.py"
    script.write_text(
        "import sys\n"
        "sys.stdout.buffer.write(b'\\x00\\xff\\x00\\xfeHELLO\\x00BINARY\\x00\\n')\n",
        encoding="utf-8",
    )
    write_context(d, f'@query "{PY} {script.as_posix()}"\n')
    r = render(d, timeout=60)
    r["test"] = "B3-binary-output"
    return r


def edge_metachars(base: Path) -> dict:
    """B4: @query stdout contains shell metacharacters."""
    d = fresh_dir(base, "adv-metachars")
    script = d / "meta.py"
    script.write_text(
        "print('backticks `cat /etc/passwd` and ${dollars} and $(subshell)')\n",
        encoding="utf-8",
    )
    write_context(d, f'@query "{PY} {script.as_posix()}"\n')
    r = render(d, timeout=60)
    r["test"] = "B4-shell-metacharacters"
    return r


def edge_missing(base: Path) -> dict:
    """B5: @query referencing a missing script."""
    d = fresh_dir(base, "adv-missing")
    write_context(d, f'@query "{PY} {d.as_posix()}/does-not-exist.py"\n')
    r = render(d, timeout=60)
    r["test"] = "B5-missing-script"
    return r


def edge_services_100(base: Path) -> dict:
    """B6: @services block with 100 entries (HTTP URLs, all expected to fail)."""
    d = fresh_dir(base, "adv-services-100")
    entries = []
    for i in range(100):
        entries.append(f"  - name: svc{i}")
        entries.append(f"    url: http://127.0.0.1:{60000 + i}/health")
    block = "@services\n" + "\n".join(entries) + "\n@end\n"
    write_context(d, block)
    r = render(d, timeout=180)
    r["test"] = "B6-services-100-entries"
    return r


def edge_services_hang(base: Path) -> dict:
    """B7: @services with a `command:` that sleeps far longer than the timeout.

    Requires render.allow_services_command. We enable it for this test.
    """
    d = fresh_dir(base, "adv-services-hang")
    # Re-enable services command for this specific test
    cfg = ("render:\n"
           "  allow_query_shell: true\n"
           "  allow_services_command: true\n")
    if os.name != "nt":
        cfg += "  shell: /bin/bash\n"
    (d / ".perseus" / "config.yaml").write_text(cfg, encoding="utf-8")
    script = d / "hang.py"
    script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
    block = ("@services\n"
             f"  - name: hang-svc\n"
             f"    command: \"{PY} {script.as_posix()}\"\n"
             "@end\n")
    write_context(d, block)
    r = render(d, timeout=180)
    r["test"] = "B7-services-command-hang"
    return r


def edge_malformed_yaml(base: Path) -> dict:
    """B8: @services block with malformed YAML."""
    d = fresh_dir(base, "adv-malformed-yaml")
    block = ("@services\n"
             "  - name: ok\n"
             "    url http://127.0.0.1/health\n"     # missing colon
             "  - bad: : ::: ::: ::\n"
             "@end\n")
    write_context(d, block)
    r = render(d, timeout=60)
    r["test"] = "B8-malformed-services-yaml"
    return r


def edge_long_context(base: Path) -> dict:
    """B9: very long context.md (1000 directive lines + 1000 prose lines).

    Counts whether the renderer parses it cleanly.
    """
    d = fresh_dir(base, "adv-long-context")
    body = []
    for i in range(1000):
        body.append(f"## Section {i}")
        body.append(f"Paragraph for section {i} — lorem ipsum filler text.")
        if i % 5 == 0:
            body.append(f'@query "{PY} -c \\"print(\'sec-{i}\')\\""')
        body.append("")
    write_context(d, "\n".join(body))
    r = render(d, timeout=900)
    r["test"] = "B9-long-context-md"
    return r


def edge_unicode(base: Path) -> dict:
    """B10: Unicode + emoji in @query output."""
    d = fresh_dir(base, "adv-unicode")
    script = d / "uni.py"
    script.write_text(
        "import sys\n"
        "try:\n"
        "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "except Exception:\n"
        "    pass\n"
        "print('🚨 ALERT — Δ change ✓ done — 日本語 — Ω')\n"
        "print('Mixed: ☃️ ❄️ 🌈 \\u2014 em dash')\n",
        encoding="utf-8",
    )
    write_context(d, f'@query "{PY} -X utf8 {script.as_posix()}"\n')
    r = render(d, timeout=60)
    r["test"] = "B10-unicode-emoji"
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else
                tempfile.gettempdir() + "/perseus-adversarial").resolve()
    base.mkdir(parents=True, exist_ok=True)
    print(f"Running adversarial benchmarks against perseus.py at {PERSEUS}")
    print(f"Workspace base: {base}")
    print()
    print("== A. Scaling sweep ==")
    a_results = scaling_sweep(base)
    print()
    print("== B. Edge cases ==")
    b_tests = [
        edge_big_stdout, edge_timeout, edge_binary, edge_metachars,
        edge_missing, edge_services_100, edge_services_hang,
        edge_malformed_yaml, edge_long_context, edge_unicode,
    ]
    b_results = []
    for fn in b_tests:
        try:
            r = fn(base)
        except Exception as e:
            r = {"test": fn.__name__, "harness_error": repr(e)}
        print(f"  {r.get('test'):28s}  rc={r.get('rc')}  "
              f"elapsed={r.get('elapsed_s')}s  lines={r.get('out_lines')}  "
              f"bytes={r.get('out_bytes')}")
        b_results.append(r)

    report = {
        "perseus_version": "1.0.1 (with local Windows shell-fallback patch)",
        "host": f"{os.name} · python {sys.version.split()[0]}",
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scaling": a_results,
        "edges": b_results,
    }
    out_path = Path(__file__).resolve().parent / "adversarial_results.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print()
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
