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


def test_tool_list_cache_distinguishes_allow_block():
    """#446: the per-signature tool-list cache must not leak one cfg's filtered
    list to a cfg with a different allowlist/blocklist."""
    base_names = {t["name"] for t in perseus._get_all_mcp_tools(cfg())}
    assert "perseus_services" in base_names

    blocked = cfg()
    blocked["mcp"] = {"tool_blocklist": ["perseus_services"]}
    blocked_names = {t["name"] for t in perseus._get_all_mcp_tools(blocked)}
    assert "perseus_services" not in blocked_names

    # Re-querying the unblocked cfg must still include it (no cross-contamination
    # between cached signatures).
    assert "perseus_services" in {t["name"] for t in perseus._get_all_mcp_tools(cfg())}

    # A sensitive tool is exposed only when explicitly allowlisted.
    allowed = cfg()
    allowed["mcp"] = {"tool_allowlist": ["perseus_query"]}
    assert "perseus_query" in {t["name"] for t in perseus._get_all_mcp_tools(allowed)}


def test_tool_list_cache_invalidates_on_registry_change():
    """#446: caching generated tool schemas must not hide directives registered
    (or removed) after the first build — the cache keys on a registry signature."""
    reg = perseus.DIRECTIVE_REGISTRY
    base_names = {t["name"] for t in perseus._get_all_mcp_tools(cfg())}
    assert "perseus_zzz_cache_probe" not in base_names

    # Clone an existing resolvable spec under a synthetic directive name.
    sample = next(
        s for s in reg.values()
        if s.kind in ("inline", "block") and s.resolver is not None
    )
    reg["@zzz-cache-probe"] = sample
    try:
        after = {t["name"] for t in perseus._get_all_mcp_tools(cfg())}
        assert "perseus_zzz_cache_probe" in after, "new directive not reflected — stale cache"
    finally:
        del reg["@zzz-cache-probe"]

    restored = {t["name"] for t in perseus._get_all_mcp_tools(cfg())}
    assert "perseus_zzz_cache_probe" not in restored, "removed directive lingered — stale cache"


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


def test_malformed_line_does_not_kill_server():
    """A malformed JSON line must get a -32700 parse error and the server must
    keep serving (previously one bad line returned None == EOF and exited)."""
    ROOT = str(Path(__file__).resolve().parent.parent)
    proc = subprocess.Popen(
        [sys.executable, "perseus.py", "mcp", "serve", "--workspace", "/tmp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", cwd=ROOT
    )
    try:
        # Garbage line first.
        proc.stdin.write("this is not json\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert resp["error"]["code"] == -32700
        assert resp["id"] is None

        # Server is still alive: a real request after the bad line still works,
        # including a non-ASCII argument (UTF-8 stdin, not cp1252).
        list_msg = json.dumps(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list",
             "params": {"_note": "café-Mnēmē-📌"}}
        ) + "\n"
        proc.stdin.write(list_msg)
        proc.stdin.flush()
        resp2 = json.loads(proc.stdout.readline())
        assert resp2["id"] == 7
        assert "tools" in resp2["result"]
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_unknown_notification_gets_no_response():
    """Per JSON-RPC 2.0 the server must never reply to a notification, even an
    unknown one; a following request's response must be the next line out."""
    ROOT = str(Path(__file__).resolve().parent.parent)
    proc = subprocess.Popen(
        [sys.executable, "perseus.py", "mcp", "serve", "--workspace", "/tmp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", cwd=ROOT
    )
    try:
        # Unknown notification (no id) — must produce NO output line.
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/bogus"}) + "\n")
        proc.stdin.flush()
        # Follow with a ping (id=5). If the notification had wrongly produced a
        # response, this readline would return that instead.
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 5, "method": "ping"}) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        assert resp["id"] == 5
        assert "result" in resp
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


# ── #575: stdio server must survive non-object JSON and `null` lines ─────────

def test_non_object_json_line_does_not_kill_server():
    """#575: `123`, `\"str\"`, `[]` and `null` are valid JSON but not JSON-RPC
    messages. Each must get a -32600 Invalid Request reply (id null) and the
    server must keep serving. Pre-fix, `123` crashed the whole server with
    AttributeError and `null` looked like the EOF sentinel (silent shutdown)."""
    ROOT = str(Path(__file__).resolve().parent.parent)
    proc = subprocess.Popen(
        [sys.executable, "perseus.py", "mcp", "serve", "--workspace", "/tmp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", cwd=ROOT
    )
    try:
        for bad_line in ('123\n', '"just a string"\n', '[]\n', 'null\n'):
            proc.stdin.write(bad_line)
            proc.stdin.flush()
            resp = json.loads(proc.stdout.readline())
            assert resp["error"]["code"] == -32600, bad_line
            assert resp["id"] is None

        # Server is still alive after all four.
        list_msg = json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {}}) + "\n"
        proc.stdin.write(list_msg)
        proc.stdin.flush()
        resp2 = json.loads(proc.stdout.readline())
        assert resp2["id"] == 5
        assert "tools" in resp2["result"]
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)


def test_numeric_args_validated_at_boundary(tmp_path):
    """#575: ttl/count/limit are string-typed JSON args; non-integer values
    must be rejected at the MCP boundary, never interpolated into the
    directive arg string."""
    c = cfg()
    for tool, args in (
        ("perseus_waypoint", {"ttl": "1; rm -rf /"}),
        ("perseus_session", {"count": "3 unread=true"}),
        ("perseus_inbox", {"limit": "5; @env PATH"}),
    ):
        result = perseus._call_tool(tool, args, c, tmp_path)
        assert result.startswith("Error: invalid arguments"), (tool, result)

    # Valid integers (as the string-typed schema delivers them) still work.
    for tool, args in (
        ("perseus_waypoint", {"ttl": "3600"}),
        ("perseus_session", {"count": "2"}),
        ("perseus_inbox", {"limit": "5"}),
    ):
        result = perseus._call_tool(tool, args, c, tmp_path)
        assert not result.startswith("Error: invalid arguments"), (tool, result)


def test_mcp_int_helper():
    assert perseus._mcp_int("5", "ttl") == 5
    assert perseus._mcp_int(7, "count") == 7
    assert perseus._mcp_int(" 42 ", "limit") == 42
    for bad in ("1; rm", "abc", None, "1.5", ""):
        with pytest.raises(ValueError):
            perseus._mcp_int(bad, "ttl")


# ── #576: perseus_trace was advertised but unroutable — now removed ──────────

def test_perseus_trace_not_advertised():
    """#576: perseus_trace had no @trace directive or special-case handler, so
    every call errored. It must no longer be advertised in tools/list."""
    names = {t["name"] for t in perseus._get_all_mcp_tools({})}
    assert "perseus_trace" not in names
    names_default_cfg = {t["name"] for t in perseus._get_all_mcp_tools(cfg())}
    assert "perseus_trace" not in names_default_cfg


# ── #577: server-card Content-Length must count bytes, not code points ───────

def test_server_card_content_length_is_bytes():
    """#577: the card contains non-ASCII (em-dashes in tool descriptions);
    Content-Length in characters short-framed the JSON for compliant HTTP
    clients. http.client trusts Content-Length, so a truncated body fails
    json.loads here pre-fix."""
    import http.client
    import socket
    import threading as _threading

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    c = cfg()
    c["mcp"] = {"allow_no_auth": True}
    t = _threading.Thread(
        target=perseus.serve_mcp_sse, args=(c, None, port), daemon=True
    )
    t.start()

    deadline = time.time() + 5
    body = None
    content_length = None
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            conn.request("GET", "/.well-known/mcp/server-card.json",
                         headers={"Host": "127.0.0.1"})
            resp = conn.getresponse()
            content_length = int(resp.getheader("Content-Length"))
            body = resp.read()
            conn.close()
            break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    assert body is not None, "SSE server never came up"
    # Content-Length must equal the BYTE length actually sent. (json.dumps
    # currently escapes non-ASCII via ensure_ascii=True, so today's card is
    # ASCII-only — this pins bytes-based framing so a future
    # ensure_ascii=False or non-ASCII serverInfo field cannot reintroduce
    # short-framing.)
    assert content_length == len(body)
    card = json.loads(body.decode("utf-8"))  # truncated JSON would raise here
    assert card["serverInfo"]["name"] == "perseus"


# ─────────────────────────────────────────────────────────────────────────────
# #641: zero-arg perseus_date must return a date, not the format string
# ─────────────────────────────────────────────────────────────────────────────


def test_perseus_date_zero_arg_returns_current_date(tmp_path):
    """#641 regression: tools/call perseus_date with NO arguments must return
    a real, current date. Pre-fix the zero-arg default was strftime syntax
    ("%Y-%m-%d %H:%M:%S"), which resolve_date does not substitute — every MCP
    client's happy path got the literal format string back verbatim."""
    from datetime import datetime
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "perseus_date", "arguments": {}}}
    resp = perseus._handle_tools_call(msg, cfg(), tmp_path)
    text = resp["result"]["content"][0]["text"].strip()
    assert "%" not in text, f"format string leaked through: {text!r}"
    parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    # It is the CURRENT date/time, not a fixed or garbage value.
    assert abs((parsed - datetime.now()).total_seconds()) < 300


def test_perseus_date_strftime_format_also_mapped(tmp_path):
    """#641: clients that were taught strftime syntax by the old tool
    description keep working — resolve_date now maps %Y %m %d %H %M %S."""
    from datetime import datetime
    msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
           "params": {"name": "perseus_date",
                      "arguments": {"format": "%Y-%m-%dT%H:%M:%S"}}}
    resp = perseus._handle_tools_call(msg, cfg(), tmp_path)
    text = resp["result"]["content"][0]["text"].strip()
    datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")  # raises if unsubstituted


def test_resolve_date_human_tokens_and_literals_still_work():
    """#641: the strftime pre-pass must not disturb human tokens or literal
    words (the #595 word-boundary protection)."""
    import re as _re
    from datetime import datetime
    out = perseus.resolve_date('format="YYYY-MM-DD"')
    datetime.strptime(out, "%Y-%m-%d")
    # Literal words containing token substrings stay intact (#595).
    out2 = perseus.resolve_date('format="zulu HHmm"')
    assert _re.fullmatch(r"zulu \d{4}", out2), out2


# ─────────────────────────────────────────────────────────────────────────────
# #643: MCP serve loop observability + bounded readline
# ─────────────────────────────────────────────────────────────────────────────


def _reset_mcp_session_stats():
    for k in perseus._MCP_SESSION_STATS:
        perseus._MCP_SESSION_STATS[k] = 0


def test_read_message_oversized_line_capped_and_drained(monkeypatch, capsys):
    """#643: a single line exceeding the cap must be drained in bounded chunks
    (never fully buffered), counted, and reported as a parse error (-32700 at
    the loop level); the NEXT line must still parse normally."""
    import io
    _reset_mcp_session_stats()
    monkeypatch.setattr(perseus, "_MCP_MAX_LINE_BYTES", 64)
    stream = io.StringIO("x" * 500 + "\n" + '{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n')
    try:
        assert perseus._read_message(stream) is perseus._PARSE_ERROR
        assert perseus._MCP_SESSION_STATS["oversized_lines"] == 1
        # The oversized line was drained: the following message is intact.
        nxt = perseus._read_message(stream)
        assert isinstance(nxt, dict) and nxt["id"] == 1
        # And EOF afterwards.
        assert perseus._read_message(stream) is perseus._EOF
        err = capsys.readouterr().err
        assert "malformed client input" in err
        assert "perseus_get_health" in err
    finally:
        _reset_mcp_session_stats()


def test_malformed_line_counted_and_warning_rate_limited(capsys):
    """#643: malformed lines are counted per session; stderr warns on the
    first occurrence and every Nth after — not on every bad line."""
    import io
    _reset_mcp_session_stats()
    try:
        assert perseus._read_message(io.StringIO("this is not json\n")) is perseus._PARSE_ERROR
        err1 = capsys.readouterr().err
        assert "malformed client input #1" in err1
        assert perseus._read_message(io.StringIO("still not json\n")) is perseus._PARSE_ERROR
        err2 = capsys.readouterr().err
        assert "malformed client input" not in err2  # rate-limited
        assert perseus._MCP_SESSION_STATS["malformed_lines"] == 2
    finally:
        _reset_mcp_session_stats()


def test_malformed_counters_surface_in_get_health(tmp_path, capsys):
    """#643: perseus_get_health exposes the per-session malformed-input
    counters so a misframing client is diagnosable from the client side."""
    _reset_mcp_session_stats()
    try:
        c = cfg()
        clean = perseus._call_tool("perseus_get_health", {}, c, tmp_path)
        assert "MCP session: 0 malformed inputs" in clean
        perseus._note_malformed("malformed_lines")
        perseus._note_malformed("invalid_requests")
        report = perseus._call_tool("perseus_get_health", {}, c, tmp_path)
        assert "2 malformed input(s)" in report
        assert "1 unparseable" in report
        assert "1 non-object" in report
    finally:
        _reset_mcp_session_stats()
