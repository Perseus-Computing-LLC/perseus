import argparse
import copy
import io
import json
import os
import select
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus, _capture_json, _seed_oracle_log

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

# ─── task-23: Perseus LSP server ───────────────────────────────────────────


import io


def test_lsp_read_write_message_roundtrip():
    """Frame a message out, parse it back."""
    buf = io.BytesIO()
    perseus._lsp_write_message(buf, {"jsonrpc": "2.0", "id": 1, "method": "ping"})
    buf.seek(0)
    msg = perseus._lsp_read_message(buf)
    assert msg == {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def test_lsp_read_message_returns_none_on_eof():
    buf = io.BytesIO(b"")
    assert perseus._lsp_read_message(buf) is None


def test_lsp_parse_directive_at_line():
    assert perseus._lsp_parse_directive_at_line("@waypoint ttl=60") == ("@waypoint", "ttl=60")
    assert perseus._lsp_parse_directive_at_line("just text") is None
    assert perseus._lsp_parse_directive_at_line("@memory") == ("@memory", "")


def test_lsp_diagnostics_unknown_directive():
    diags = perseus._lsp_diagnostics_for("@bogus arg=1\n", cfg(), Path("/tmp"))
    assert len(diags) == 1
    assert "Unknown directive" in diags[0]["message"]


def test_lsp_diagnostics_unmatched_else_endif():
    text = "@else\n@endif\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    msgs = [d["message"] for d in diags]
    assert any("@else without matching @if" in m for m in msgs)
    assert any("@endif without matching @if" in m for m in msgs)


def test_lsp_diagnostics_unclosed_if():
    text = "@if foo\nhello\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("unclosed @if" in d["message"] for d in diags)


def test_lsp_diagnostics_unclosed_constraint():
    text = "@constraint\nrules\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("Unclosed @constraint" in d["message"] for d in diags)


def test_lsp_diagnostics_cache_ttl_non_integer():
    text = "@waypoint @cache ttl=abc\n"
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("@cache ttl=" in d["message"] for d in diags)


def test_lsp_diagnostics_unsubscribed_federation_alias(monkeypatch):
    text = "@memory federation alias=ghost\n"
    monkeypatch.setattr(perseus, "_load_federation_manifest", lambda cfg: {"subscriptions": []})
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert any("not subscribed" in d["message"] for d in diags)


def test_lsp_diagnostics_subscribed_federation_alias_passes(monkeypatch):
    text = "@memory federation alias=sam\n"
    monkeypatch.setattr(perseus, "_load_federation_manifest", lambda cfg: {"subscriptions": [{"alias": "sam", "path": "/x", "enabled": True}]})
    diags = perseus._lsp_diagnostics_for(text, cfg(), Path("/tmp"))
    assert not any("federation" in d["message"].lower() for d in diags)


def test_lsp_uri_to_path():
    p = perseus._lsp_uri_to_path("file:///tmp/foo.md")
    assert p == Path("/tmp/foo.md").resolve()


def test_lsp_workspace_from_params_uses_workspaceFolders():
    p = perseus._lsp_workspace_from_params({"workspaceFolders": [{"uri": "file:///tmp"}]})
    assert p == Path("/tmp").resolve()


class LSPHarness:
    """Tiny blocking JSON-RPC client for the real Perseus LSP subprocess."""

    def __init__(self, workspace: Path, *, tcp: bool = False, allow_mutations: bool = False):
        self.workspace = workspace
        self.tcp = tcp
        self.allow_mutations = allow_mutations
        self.proc = None
        self.reader = None
        self.writer = None
        self.sock = None
        self._next_id = 0
        self._pending: list[dict] = []

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def start(self):
        script = Path(__file__).resolve().parents[1] / "perseus.py"
        cmd = [sys.executable, str(script), "serve", "--lsp"]
        if self.allow_mutations:
            cmd.append("--allow-lsp-mutations")
        if self.tcp:
            port = self._free_tcp_port()
            cmd += ["--tcp", str(port)]
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            deadline = time.time() + 5
            last_error = None
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise AssertionError(f"LSP exited early: {self._stderr()}")
                try:
                    self.sock = socket.create_connection(("127.0.0.1", port), timeout=0.1)
                    break
                except OSError as exc:
                    last_error = exc
                    time.sleep(0.05)
            if self.sock is None:
                raise AssertionError(f"could not connect to LSP TCP server: {last_error}")
            self.reader = self.sock.makefile("rb")
            self.writer = self.sock.makefile("wb")
        else:
            cmd.append("--stdio")
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.workspace),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.reader = self.proc.stdout
            self.writer = self.proc.stdin
        return self

    @staticmethod
    def _free_tcp_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", 0))
            except PermissionError:
                pytest.skip("TCP sockets are unavailable in this sandbox")
            return int(s.getsockname()[1])

    def _stderr(self) -> str:
        if self.proc and self.proc.stderr and self.proc.poll() is not None:
            try:
                return self.proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""

    def _wait_readable(self, deadline: float) -> None:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for LSP response; stderr={self._stderr()}")
        if self.proc and self.proc.poll() is not None:
            raise AssertionError(f"LSP exited early: {self._stderr()}")
        readable, _, _ = select.select([self.reader.fileno()], [], [], remaining)
        if not readable:
            raise AssertionError(f"timed out waiting for LSP response; stderr={self._stderr()}")

    def _read_byte(self, deadline: float) -> bytes:
        self._wait_readable(deadline)
        chunk = os.read(self.reader.fileno(), 1)
        if not chunk:
            raise AssertionError(f"LSP stream closed; stderr={self._stderr()}")
        return chunk

    def _read_exact(self, length: int, deadline: float) -> bytes:
        data = b""
        while len(data) < length:
            self._wait_readable(deadline)
            chunk = os.read(self.reader.fileno(), length - len(data))
            if not chunk:
                raise AssertionError(f"LSP stream closed; stderr={self._stderr()}")
            data += chunk
        return data

    def read(self, timeout: float = 5) -> dict:
        deadline = time.time() + timeout
        headers = b""
        while not headers.endswith(b"\r\n\r\n"):
            headers += self._read_byte(deadline)
        length = None
        for line in headers.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        assert length is not None
        body = self._read_exact(length, deadline)
        return json.loads(body.decode("utf-8"))

    def write_raw(self, data: bytes) -> None:
        self.writer.write(data)
        self.writer.flush()

    def send(self, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.write_raw(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        req_id = self._next_id
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
        for i, pending in enumerate(self._pending):
            if pending.get("id") == req_id:
                return self._pending.pop(i)
        while True:
            msg = self.read()
            if msg.get("id") == req_id:
                return msg
            self._pending.append(msg)

    def notify(self, method: str, params: dict | None = None) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def expect_notification(self, method: str) -> dict:
        for i, pending in enumerate(self._pending):
            if pending.get("method") == method:
                return self._pending.pop(i)
        while True:
            msg = self.read()
            if msg.get("method") == method:
                return msg
            self._pending.append(msg)

    def initialize(self) -> dict:
        return self.request("initialize", {
            "rootUri": self.workspace.as_uri(),
            "capabilities": {},
        })

    def shutdown(self) -> dict:
        rsp = self.request("shutdown", {})
        self.notify("exit", {})
        if self.proc:
            self.proc.wait(timeout=5)
        return rsp

    def close(self):
        for stream in (self.writer, self.reader):
            try:
                if stream:
                    stream.close()
            except Exception:
                pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)


@pytest.fixture
def lsp_harness(tmp_path):
    with LSPHarness(tmp_path) as harness:
        yield harness


@pytest.fixture
def lsp_harness_tcp(tmp_path):
    with LSPHarness(tmp_path, tcp=True) as harness:
        yield harness


def _lsp_doc(uri: str, text: str, version: int = 1) -> dict:
    return {
        "textDocument": {
            "uri": uri,
            "languageId": "markdown",
            "version": version,
            "text": text,
        }
    }


def test_lsp_initialize_returns_capabilities(lsp_harness):
    rsp = lsp_harness.initialize()
    caps = rsp["result"]["capabilities"]
    assert caps["textDocumentSync"] == 1
    assert caps["hoverProvider"] is True
    assert "@" in caps["completionProvider"]["triggerCharacters"]
    assert "perseus.compactMemory" in caps["executeCommandProvider"]["commands"]


def test_lsp_didopen_and_didchange_publish_diagnostics(lsp_harness, tmp_path):
    lsp_harness.initialize()
    uri = (tmp_path / "context.md").as_uri()
    lsp_harness.notify("textDocument/didOpen", _lsp_doc(uri, '@date format="YYYY"\n'))
    clean = lsp_harness.expect_notification("textDocument/publishDiagnostics")
    assert clean["params"]["diagnostics"] == []

    lsp_harness.notify("textDocument/didChange", {
        "textDocument": {"uri": uri, "version": 2},
        "contentChanges": [{"text": "@if env.set FOO\nbody\n"}],
    })
    diag = lsp_harness.expect_notification("textDocument/publishDiagnostics")
    assert any("unclosed @if" in d["message"].lower() for d in diag["params"]["diagnostics"])


def test_lsp_completion_comes_from_directive_registry(lsp_harness, tmp_path):
    lsp_harness.initialize()
    uri = (tmp_path / "context.md").as_uri()
    lsp_harness.notify("textDocument/didOpen", _lsp_doc(uri, "@"))
    lsp_harness.expect_notification("textDocument/publishDiagnostics")
    rsp = lsp_harness.request("textDocument/completion", {
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 1},
    })
    labels = {item["label"] for item in rsp["result"]["items"]}
    assert set(perseus._LSP_DIRECTIVE_NAMES).issubset(labels)


def test_lsp_hover_over_agent_never_executes(lsp_harness, tmp_path):
    lsp_harness.initialize()
    uri = (tmp_path / "context.md").as_uri()
    lsp_harness.notify("textDocument/didOpen", _lsp_doc(uri, '@agent "echo ATTACK"\n'))
    lsp_harness.expect_notification("textDocument/publishDiagnostics")
    rsp = lsp_harness.request("textDocument/hover", {
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 2},
    })
    value = rsp["result"]["contents"]["value"]
    assert "hover disabled" in value.lower()
    assert "ATTACK" not in value


def test_lsp_executecommand_compact_memory_requires_mutation_gate(lsp_harness):
    lsp_harness.initialize()
    rsp = lsp_harness.request("workspace/executeCommand", {
        "command": "perseus.compactMemory",
        "arguments": [],
    })
    assert rsp["error"]["code"] == -32000
    assert "Mutation command disabled" in rsp["error"]["message"]


def test_lsp_shutdown_exit_reaps_process(lsp_harness):
    lsp_harness.initialize()
    rsp = lsp_harness.shutdown()
    assert rsp["result"] is None
    assert lsp_harness.proc.poll() == 0


def test_lsp_malformed_jsonrpc_returns_parse_error(lsp_harness):
    lsp_harness.initialize()
    lsp_harness.write_raw(b"Content-Length: 1\r\n\r\n{")
    rsp = lsp_harness.read()
    assert rsp["id"] is None
    assert rsp["error"]["code"] == -32700
    assert "Parse error" in rsp["error"]["message"]


def test_lsp_tcp_transport_initialize_smoke(lsp_harness_tcp):
    rsp = lsp_harness_tcp.initialize()
    caps = rsp["result"]["capabilities"]
    assert caps["hoverProvider"] is True
def test_lsp_hover_refuses_to_execute_agent(tmp_path):
    """Critical safety fix: hover must never spawn a subprocess via @agent."""
    cfg_ = cfg()
    workspace = tmp_path
    result = perseus._lsp_resolve_directive_for_hover("@agent", "echo HACKED", cfg_, workspace)
    assert "hover disabled" in result.lower()
    assert "subprocess" in result.lower()
    # The forbidden command text MUST NOT appear in the hover output, period.
    assert "HACKED" not in result


def test_lsp_hover_refuses_query_and_services(tmp_path):
    cfg_ = cfg()
    for name in ("@query", "@services"):
        result = perseus._lsp_resolve_directive_for_hover(name, '"echo X"', cfg_, tmp_path)
        assert "hover disabled" in result.lower()


def test_lsp_hover_still_works_for_safe_directives(tmp_path):
    """Hover sandbox must not break the safe directives."""
    cfg_ = cfg()
    result = perseus._lsp_resolve_directive_for_hover("@date", 'format="YYYY"', cfg_, tmp_path)
    # Should produce a 4-digit year (deterministic, no shell)
    assert len(result.strip()) == 4
    assert result.strip().isdigit()
