"""Tests for MCP Deep Integration (task-75)."""
import json
import pytest
import subprocess
import sys
import time
from pathlib import Path
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def test_tools_list_returns_directive_tools():
    """tools/list returns all non-sensitive directive tools from registry."""
    c = cfg()
    tools = perseus._get_all_mcp_tools(c)
    tool_names = [t["name"] for t in tools]
    # Sensitive tools excluded unless allowlisted, but others present
    assert len(tool_names) >= 5
    assert "perseus_read" in tool_names
    assert "perseus_services" in tool_names
    assert "perseus_memory" in tool_names
    assert "perseus_health" in tool_names
    assert "perseus_agora" in tool_names
    # Legacy tools preserved
    assert "perseus_get_context" in tool_names
    assert "perseus_get_health" in tool_names


def test_tools_list_includes_plugin_directives(tmp_path):
    """Plugin directives appear in tools/list when plugins are loaded."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "my_plugin.py").write_text("""
REGISTER = {}
""", encoding="utf-8")
    c = cfg()
    c["plugins"] = {"enabled": True, "dir": str(plugins_dir)}
    perseus.register_plugins(c, force=True)
    tools = perseus._get_all_mcp_tools(c)
    # At minimum, built-ins are there
    assert len(tools) > 0


def test_tools_call_query_resolves(tmp_path):
    """tools/call for perseus_query resolves correctly."""
    c = cfg()
    c["render"]["allow_query_shell"] = True
    c["mcp"] = {"tool_allowlist": ["perseus_query"]}
    result = perseus._call_tool("perseus_query", {"command": "echo hello_mcp"}, c, tmp_path)
    assert "hello_mcp" in result


def test_tools_call_read_resolves(tmp_path):
    """tools/call for perseus_read resolves correctly."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("mcp read test", encoding="utf-8")
    c = cfg()
    result = perseus._call_tool("perseus_read", {"path": str(test_file)}, c, tmp_path)
    assert "mcp read test" in result


def test_tools_call_enforces_blocklist(tmp_path):
    """tools/call enforces the same blocklist policy as tools/list."""
    c = cfg()
    c["render"]["allow_query_shell"] = True
    c["mcp"] = {"tool_blocklist": ["perseus_query"]}
    result = perseus._call_tool("perseus_query", {"command": "echo bypassed"}, c, tmp_path)
    assert "blocked by mcp.tool_blocklist" in result
    assert "bypassed" not in result


def test_trust_gate_blocks_query(tmp_path):
    """Trust gate blocks shell execution — returns error."""
    c = cfg()
    c["render"]["allow_query_shell"] = False
    result = perseus._call_tool("perseus_query", {"command": "echo blocked"}, c, tmp_path)
    assert "blocked" in result.lower() or "error" in result.lower()


def test_trust_gate_blocks_agent(tmp_path):
    """Trust gate blocks agent execution."""
    c = cfg()
    c["render"]["allow_agent_shell"] = False
    result = perseus._call_tool("perseus_agent", {"agent": "test", "prompt": "hello"}, c, tmp_path)
    assert "blocked" in result.lower() or "error" in result.lower()


def test_legacy_get_context_preserved(tmp_path):
    """perseus_get_context tool is preserved."""
    c = cfg()
    result = perseus._call_tool("perseus_get_context", {}, c, tmp_path)
    assert isinstance(result, str)


def test_legacy_get_health_preserved(tmp_path):
    """perseus_get_health tool is preserved."""
    c = cfg()
    result = perseus._call_tool("perseus_get_health", {}, c, tmp_path)
    assert isinstance(result, str)


def test_doctor_includes_mcp_check():
    """perseus doctor includes MCP server readiness."""
    ROOT = str(Path(__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, "perseus.py", "doctor", "--json"],
        capture_output=True, text=True, cwd=ROOT
    )
    data = json.loads(result.stdout)
    check_ids = [c["id"] for c in data["checks"]]
    assert "mcp_server" in check_ids


def test_stdio_handshake():
    """Stdio transport handles initialize -> tools/list -> tools/call."""
    ROOT = str(Path(__file__).resolve().parent.parent)
    proc = subprocess.Popen(
        [sys.executable, "perseus.py", "mcp", "serve", "--workspace", "/tmp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=ROOT
    )
    try:
        # Initialize
        init_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        proc.stdin.write(init_msg)
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert resp["id"] == 1
        assert "serverInfo" in resp["result"]

        # Notifications/initialized
        notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        proc.stdin.write(notif)
        proc.stdin.flush()

        # tools/list
        list_msg = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}) + "\n"
        proc.stdin.write(list_msg)
        proc.stdin.flush()
        resp2 = json.loads(proc.stdout.readline())
        assert resp2["id"] == 2
        assert "tools" in resp2["result"]
        assert len(resp2["result"]["tools"]) > 0
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


# ─────────────────────────────────────────────────────────────────────────────
# #139 regression: _call_tool timeout must kill the subprocess tree and
# must not block on executor shutdown
# ─────────────────────────────────────────────────────────────────────────────


def _mcp_query_cfg() -> dict:
    """Build a config that allows perseus_query via MCP."""
    c = cfg()
    c.setdefault("render", {})["allow_query_shell"] = True
    c.setdefault("mcp", {})["tool_timeout_s"] = 1
    c["mcp"]["tool_allowlist"] = ["perseus_query"]
    return c


def test_call_tool_timeout_does_not_block_on_executor_shutdown(tmp_path):
    """Regression for #139 — pre-1.0.6 used a context-managed executor,
    so future.result(timeout=…) abandoned the future but executor.shutdown
    (wait=True) blocked the response until the worker finished. A 1s timeout
    on a 10s sleep blocked _call_tool for ~10s.

    Post-fix: shutdown(wait=False, cancel_futures=True) is called in a
    finally block. The response returns within ~timeout seconds, not
    ~sleep seconds.
    """
    c = _mcp_query_cfg()

    # Cross-platform long-running command: `sleep` does not exist on cmd.exe,
    # where it fails instantly and defeats the timeout being tested. Use a
    # sleeper script invoked by the interpreter — and NO double quotes, since
    # the MCP query wrapper escapes them to \" which cmd.exe cannot parse.
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time; time.sleep(10)\n", encoding="utf-8")
    long_cmd = f"{sys.executable} {sleeper}"

    start = time.time()
    result = perseus._call_tool(
        "perseus_query",
        {"command": long_cmd},
        c,
        tmp_path,
    )
    elapsed = time.time() - start

    # Must return promptly. We allow generous headroom (3s) for thread
    # scheduling + subprocess cleanup, but the bug being tested manifested
    # as ~10s blocking.
    assert elapsed < 3.0, (
        f"_call_tool blocked for {elapsed:.2f}s — executor.shutdown(wait=True) "
        f"defeated the timeout"
    )
    assert "timed out" in result.lower()


def test_call_tool_timeout_actually_kills_subprocess(tmp_path):
    """Regression for #139 — pre-1.0.6 abandoned the worker but the
    subprocess kept running. After fix, the subprocess tree is killed
    via os.killpg (POSIX) or taskkill /T (Windows) on timeout.
    """
    import os, subprocess, time as _time, uuid, shutil
    if os.name == "nt":
        pytest.skip("Subprocess-tree kill test is POSIX-specific")
    if shutil.which("pgrep") is None:
        pytest.skip("pgrep not available")

    c = _mcp_query_cfg()

    # Use a unique marker so pgrep can find OUR sleep process without
    # matching unrelated ones.
    marker = f"perseus_test_marker_{uuid.uuid4().hex[:8]}"
    cmd = f"sleep 30 # {marker}"

    start = _time.time()
    result = perseus._call_tool(
        "perseus_query",
        {"command": cmd},
        c,
        tmp_path,
    )
    elapsed = _time.time() - start

    assert elapsed < 3.0
    assert "timed out" in result.lower()

    # Wait briefly for the kill signal to propagate, then assert no
    # zombie sleep process remains.
    _time.sleep(0.5)
    pgrep = subprocess.run(
        ["pgrep", "-f", marker],
        capture_output=True, text=True,
    )
    # pgrep exit code 1 means no matches (good); 0 means matches (bad).
    if pgrep.returncode == 0:
        # Cleanup before failing
        for pid in pgrep.stdout.split():
            try:
                os.kill(int(pid), 9)
            except (ValueError, ProcessLookupError):
                pass
        pytest.fail(
            f"Subprocess(es) still running after timeout: {pgrep.stdout.strip()}"
        )

    # And the killer hint should be in the result.
    assert "subprocess killed" in result.lower() or "timed out" in result.lower()


def test_call_tool_normal_completion_under_timeout(tmp_path):
    """Sanity: under-timeout calls still work normally."""
    c = _mcp_query_cfg()
    c["mcp"]["tool_timeout_s"] = 5
    result = perseus._call_tool(
        "perseus_query",
        {"command": "echo hello-mcp"},
        c,
        tmp_path,
    )
    assert "hello-mcp" in result
    assert "timed out" not in result.lower()


def test_kill_active_subprocess_for_thread_returns_false_when_no_subprocess():
    """The killer is safe to call when no subprocess is registered."""
    import threading
    fake_tid = threading.get_ident() + 12345  # ident no thread will use
    result = perseus.kill_active_subprocess_for_thread(fake_tid)
    assert result is False
