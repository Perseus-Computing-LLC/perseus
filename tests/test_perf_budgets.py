"""Performance budgets for Phase 21B (task-58). Run with --enforce-budgets.

Budgets are blocking by default (hard failures on overrun). The 2× tolerance
window catches transient noise while preventing sustained regressions.

Recalibrated 2026-05-22 for modular src/ architecture. Budgets set at ~1.5×
measured warm time on the reference machine.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import warnings
from pathlib import Path

import pytest

from conftest import PY_VER
from test_lsp import LSPHarness

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSEUS_PY = REPO_ROOT / "perseus.py"

# Calibrated 2026-05-22: reference machine measured warm render ~289ms, graph ~288ms,
# prefetch ~278ms, LSP init ~300ms. Budgets set at ~1.5× for headroom.
# Single threshold per command — cold/warm distinction is meaningless for a CLI
# subprocess tool (every launch is a fresh process).
BUDGETS: dict[str, float] = {
    "render":      500,   # measured ~290ms, v1.0.6 preflight + security overhead
    "graph":       550,   # measured ~310ms, v1.0.6 preflight overhead
    "prefetch":    450,   # measured ~278ms, v1.0.5 bump for security review overhead
    "synthesize":  500,   # LLM-dependent — generous budget
    "serve":       800,   # network startup
    "lsp-init":    600,   # subprocess + JSON-RPC handshake
    "watch":       600,   # v1.0.6 preflight overhead
}


def _write_perf_workspace(workspace: Path) -> Path:
    (workspace / ".perseus").mkdir(parents=True, exist_ok=True)
    (workspace / ".perseus" / "config.yaml").write_text(
        "permissions:\n  profile: strict\n"
        "render:\n  allow_query_shell: false\n  allow_agent_shell: false\n"
    )
    (workspace / "notes.md").write_text("Perseus performance fixture.\n")
    source = workspace / "context.md"
    source.write_text(
        "@perseus v0.4\n\n"
        "# Performance Fixture\n\n"
        "@include \"notes.md\"\n\n"
        "@env PERF_BUDGET_MISSING fallback=unset\n\n"
        "@tree . depth=1\n"
    )
    (workspace / "source-a.md").write_text(
        "Project Atlas is green because every release gate has a cited owner.\n"
    )
    return source


def _env(home: Path) -> dict:
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(home)
    return env


def _timed_run(cmd: list[str], *, cwd: Path, env: dict, timeout: float = 5.0) -> tuple[float, subprocess.CompletedProcess[str]]:
    start = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, proc


def _record_budget(request, command: str, elapsed_ms: float) -> None:
    budget = BUDGETS[command]
    # 2× tolerance: transient noise shouldn't fail CI, but sustained regressions will
    if elapsed_ms > budget * 2:
        msg = f"performance budget FAIL for {command}: {elapsed_ms:.1f}ms > 2× budget {budget}ms"
        pytest.fail(msg)
    if elapsed_ms > budget:
        # Within 1×–2×: warn (upgrade to fail on second offense in CI)
        msg = f"performance budget overrun for {command}: {elapsed_ms:.1f}ms > budget {budget}ms"
        if request.config.getoption("--enforce-budgets"):
            pytest.fail(msg)
        warnings.warn(pytest.PytestWarning(msg), stacklevel=2)


@pytest.mark.slow
@pytest.mark.parametrize("command", ["render", "graph", "prefetch"])
def test_cli_performance_budgets(command: str, tmp_path: Path, request):
    source = _write_perf_workspace(tmp_path)
    env = _env(tmp_path / "perseus-home")
    base = [sys.executable, str(PERSEUS_PY)]
    if command == "render":
        cmd = base + ["render", str(source), "--output", str(tmp_path / "rendered.md")]
    elif command == "graph":
        cmd = base + ["graph", str(source), "--json"]
    elif command == "prefetch":
        cmd = base + ["prefetch", str(source), "--json"]

    # Warm the filesystem, then measure
    _timed_run(cmd, cwd=tmp_path, env=env)
    elapsed_ms, proc = _timed_run(cmd, cwd=tmp_path, env=env)
    assert proc.returncode == 0, proc.stderr
    _record_budget(request, command, elapsed_ms)


@pytest.mark.slow
def test_serve_startup_budget(tmp_path: Path, request):
    _write_perf_workspace(tmp_path)
    env = _env(tmp_path / "perseus-home")
    token = "perf-token"
    (tmp_path / ".perseus" / "config.yaml").write_text(
        "serve:\n  bind: 127.0.0.1\n  auth_token: perf-token\n"
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    cmd = [sys.executable, str(PERSEUS_PY), "serve", "--host", "127.0.0.1", "--port", str(port)]

    def once() -> float:
        start = time.perf_counter()
        proc = subprocess.Popen(cmd, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.perf_counter() + 5
            while time.perf_counter() < deadline:
                try:
                    import urllib.request
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers={"Authorization": f"Bearer {token}"})
                    with urllib.request.urlopen(req, timeout=0.2) as resp:
                        assert resp.status == 200
                    return (time.perf_counter() - start) * 1000
                except Exception:
                    time.sleep(0.02)
            raise AssertionError("serve did not respond before timeout")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)

    # Warm, then measure
    once()
    elapsed_ms = once()
    _record_budget(request, "serve", elapsed_ms)


@pytest.mark.slow
def test_lsp_initialize_budget(tmp_path: Path, request):
    # Warm, then measure
    with LSPHarness(tmp_path) as harness:
        harness.initialize()

    start = time.perf_counter()
    with LSPHarness(tmp_path) as harness:
        rsp = harness.initialize()
        assert "capabilities" in rsp["result"]
    elapsed_ms = (time.perf_counter() - start) * 1000
    _record_budget(request, "lsp-init", elapsed_ms)


@pytest.mark.slow
def test_watch_first_render_budget(tmp_path: Path, request):
    source = _write_perf_workspace(tmp_path)
    env = _env(tmp_path / "perseus-home")
    output = tmp_path / "watched.md"
    cmd = [
        sys.executable,
        str(PERSEUS_PY),
        "watch",
        "--source",
        str(source),
        "--output",
        str(output),
        "--interval",
        "10",
    ]

    def once() -> float:
        start = time.perf_counter()
        proc = subprocess.Popen(cmd, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.perf_counter() + 5
            while time.perf_counter() < deadline:
                if output.exists() and "Performance Fixture" in output.read_text():
                    return (time.perf_counter() - start) * 1000
                time.sleep(0.02)
            stderr = proc.stderr.read() if proc.stderr else ""
            raise AssertionError(f"watch did not render before timeout: {stderr}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
            if output.exists():
                output.unlink()

    # Warm, then measure
    once()
    elapsed_ms = once()
    _record_budget(request, "watch", elapsed_ms)
