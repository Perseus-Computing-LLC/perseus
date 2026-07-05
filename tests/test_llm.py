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

def test_run_ollama_success(monkeypatch):
    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, *_a):
            return b'{"response":"ranked output"}'
    monkeypatch.setattr(perseus.urllib.request, "urlopen", lambda *a, **k: Resp())
    out = perseus.run_ollama("prompt", cfg())
    assert out == "ranked output"
def test_run_llm_openai_compat_success(monkeypatch):
    class Resp:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, *_a):
            return b'{"choices":[{"message":{"content":"compat result"}}]}'
    monkeypatch.setattr(perseus.urllib.request, "urlopen", lambda *a, **k: Resp())
    out, code = perseus.run_llm("openai-compat", "prompt", cfg(), model="mistral", model_url="http://localhost:11434")
    assert code == 0
    assert out == "compat result"
def test_run_llm_daedalus_routes_to_ollama(monkeypatch):
    captured = {}
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, *_a): return b'{"message":{"content":"daedalus-reply"}}'
    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode())
        return FakeResp()
    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    text, code = perseus.run_llm("daedalus", "the prompt", cfg())
    assert code == 0
    assert text == "daedalus-reply"
    assert "/api/chat" in captured["url"]
    assert captured["data"]["model"] == "perseus-daedalus"
# ─── Hermes provider alias + perseus llm ping (Hermes integration) ─────────


def test_run_llm_hermes_alias_routes_to_openai_compat(monkeypatch):
    """`provider=hermes` should hit /v1/chat/completions like openai-compat."""
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, *_a):
            return b'{"choices":[{"message":{"content":"pong"}}]}'

    def fake_urlopen(req, *a, **k):
        captured["url"] = req.full_url
        captured["body"] = req.data
        return Resp()

    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    out, code = perseus.run_llm("hermes", "test", cfg(), model_url="http://localhost:8080")
    assert code == 0
    assert out == "pong"
    # Hermes serves the OpenAI-compatible chat-completions endpoint
    assert captured["url"] == "http://localhost:8080/v1/chat/completions"


def test_run_llm_hermes_uses_hermes_config_keys(monkeypatch):
    """When `hermes_url`/`hermes_model` are set, they should be used."""
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, *_a):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, *a, **k):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        return Resp()

    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    cfg_ = cfg()
    cfg_["llm"]["hermes_url"] = "http://hermes.local:9000"
    cfg_["llm"]["hermes_model"] = "claude-sonnet"
    out, code = perseus.run_llm("hermes", "test", cfg_)
    assert code == 0
    assert captured["url"] == "http://hermes.local:9000/v1/chat/completions"
    assert captured["payload"]["model"] == "claude-sonnet"


def test_run_llm_hermes_falls_back_to_generic_keys(monkeypatch):
    """If hermes_url is unset, fall back to llm.url (shared openai-compat config)."""
    captured = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, *_a):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, *a, **k):
        captured["url"] = req.full_url
        return Resp()

    monkeypatch.setattr(perseus.urllib.request, "urlopen", fake_urlopen)
    cfg_ = cfg()
    cfg_["llm"]["url"] = "http://shared:7000"
    perseus.run_llm("hermes", "test", cfg_)
    assert captured["url"] == "http://shared:7000/v1/chat/completions"


def test_run_llm_unsupported_provider_lists_hermes():
    """Error message should mention hermes so users know it's supported."""
    text, code = perseus.run_llm("bogus", "test", cfg())
    assert code == 2
    assert "hermes" in text


def test_cmd_llm_ping_success(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("pong", 0))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url=None)
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 0
    out = capsys.readouterr().out
    assert "✓" in out
    assert "hermes" in out


def test_cmd_llm_ping_json_success(monkeypatch):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("pong", 0))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url=None, json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_llm, args, cfg())
    assert rc == 0
    assert out["provider"] == "hermes"
    assert out["status"] == "ok"
    assert out["error"] is None
    assert isinstance(out["latency_ms"], int)


def test_cmd_llm_ping_json_failure(monkeypatch):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("> ⚠ LLM request failed: connection refused", 2))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url="http://localhost:8080", json=True)
    out, rc = _capture_json(monkeypatch, perseus.cmd_llm, args, cfg())
    assert rc == 2
    assert out["status"] == "error"
    assert "connection refused" in out["error"]


def test_cmd_llm_ping_failure_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: ("> ⚠ LLM request failed: connection refused", 2))
    args = argparse.Namespace(llm_sub="ping", provider="hermes", model=None, url="http://localhost:8080")
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 2
    out = capsys.readouterr().out
    assert "✗" in out
    assert "connection refused" in out


def test_cmd_llm_ping_unsupported_provider_short_circuits(monkeypatch, capsys):
    """Unknown providers should bail before run_llm is invoked."""
    called = []
    monkeypatch.setattr(perseus, "run_llm", lambda *a, **k: called.append(1) or ("", 0))
    args = argparse.Namespace(llm_sub="ping", provider="bogus", model=None, url=None)
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 2
    assert not called


def test_cmd_llm_unknown_subcommand_returns_3(capsys):
    args = argparse.Namespace(llm_sub="bogus", provider=None, model=None, url=None)
    rc = perseus.cmd_llm(args, cfg())
    assert rc == 3
