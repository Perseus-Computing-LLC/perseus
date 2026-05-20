"""Advisory performance budgets for Phase 21B (task-58).

Run explicitly with:

    python -m pytest tests/test_perf_budgets.py -m slow

By default, budget overruns emit warnings so slower developer machines do not
make normal CI flaky. Add ``--enforce-budgets`` to make overruns hard failures.
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

BUDGETS = {
    "render": {"cold_ms": 200, "warm_ms": 100},
    "graph": {"cold_ms": 100, "warm_ms": 50},
    "prefetch": {"cold_ms": 200, "warm_ms": 100},
    "synthesize": {"cold_ms": 300, "warm_ms": 150},
    "serve": {"cold_ms": 500, "warm_ms": 500},
    "lsp-initialize": {"cold_ms": 500, "warm_ms": 300},
    "watch": {"cold_ms": 300, "warm_ms": 150},
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


def _record_budget(request, command: str, cold_ms: float, warm_ms: float) -> None:
    budget = BUDGETS[command]
    failures = []
    if cold_ms > budget["cold_ms"] * 2:
        failures.append(f"cold {cold_ms:.1f}ms > 2× budget {budget['cold_ms']}ms")
    if warm_ms > budget["warm_ms"] * 2:
        failures.append(f"warm {warm_ms:.1f}ms > 2× budget {budget['warm_ms']}ms")
    if warm_ms > cold_ms * 1.25:
        failures.append(f"warm {warm_ms:.1f}ms unexpectedly exceeds cold {cold_ms:.1f}ms by >25%")
    if not failures:
        return
    msg = f"performance budget advisory for {command}: " + "; ".join(failures)
    if request.config.getoption("--enforce-budgets"):
        pytest.fail(msg)
    warnings.warn(pytest.PytestWarning(msg), stacklevel=2)


@pytest.mark.slow
@pytest.mark.parametrize("command", ["render", "graph", "prefetch", "synthesize"])
def test_cli_performance_budgets(command: str, tmp_path: Path, request):
    source = _write_perf_workspace(tmp_path)
    env = _env(tmp_path / "perseus-home")
    base = [sys.executable, str(PERSEUS_PY)]
    if command == "render":
        cmd = base + ["render", str(source), "--output", str(tmp_path / "rendered.md")]
    elif command == "graph":
        cmd = base + ["graph", str(source), "--workspace", str(tmp_path), "--json"]
    elif command == "prefetch":
        cmd = base + ["prefetch", str(source), "--workspace", str(tmp_path), "--json"]
    else:
        cmd = base + ["synthesize", "What status can be cited?", "--source", "source-a.md", "--json"]

    cold_ms, cold = _timed_run(cmd, cwd=tmp_path, env=env)
    warm_ms, warm = _timed_run(cmd, cwd=tmp_path, env=env)

    assert cold.returncode == 0, cold.stderr
    assert warm.returncode == 0, warm.stderr
    _record_budget(request, command, cold_ms, warm_ms)


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

    cold_ms = once()
    warm_ms = once()
    _record_budget(request, "serve", cold_ms, warm_ms)


@pytest.mark.slow
def test_lsp_initialize_budget(tmp_path: Path, request):
    cold_start = time.perf_counter()
    with LSPHarness(tmp_path) as harness:
        rsp = harness.initialize()
        assert "capabilities" in rsp["result"]
    cold_ms = (time.perf_counter() - cold_start) * 1000

    warm_start = time.perf_counter()
    with LSPHarness(tmp_path) as harness:
        rsp = harness.initialize()
        assert "capabilities" in rsp["result"]
    warm_ms = (time.perf_counter() - warm_start) * 1000

    _record_budget(request, "lsp-initialize", cold_ms, warm_ms)


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
        "--workspace",
        str(tmp_path),
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

    cold_ms = once()
    warm_ms = once()
    _record_budget(request, "watch", cold_ms, warm_ms)
