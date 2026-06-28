"""
Tests for the @research directive (issue #513).

@research calls an EXTERNAL paper-search MCP server (BGPT by default) and
injects structured paper summaries (methods + results) into the rendered
context. These tests MOCK the MCP client — they NEVER spawn a real subprocess
and never touch the network.

Mocking strategy: patch ``perseus._ResearchMCPClient.connect`` /
``.call_tool`` / ``.disconnect`` so ``resolve_research`` exercises its full
parse → call → format → token-cap path against canned payloads.
"""

import copy
from unittest.mock import patch

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _research_cfg(**overrides) -> dict:
    """Config with @research enabled; apply per-test overrides."""
    c = cfg()
    c["research"] = {
        "enabled": True,
        "provider": "bgpt",
        "command": ["npx", "-y", "bgpt-mcp"],
        "tool": "search_papers",
        "default_limit": 5,
        "max_tokens": 1500,
    }
    c["research"].update(overrides)
    return c


def _paper(i: int) -> dict:
    return {
        "title": f"Paper Number {i}",
        "authors": [f"Author {i}A", f"Author {i}B"],
        "year": 2020 + i,
        "methods": f"Method description for paper {i} with several explanatory words here.",
        "results": f"Result description for paper {i} with several explanatory words here.",
    }


class _FakeClient:
    """Stand-in for _ResearchMCPClient. Records calls; never spawns anything."""

    last_instance = None

    def __init__(self, command, timeout_s: float = 20.0):
        self.command = command
        self.connected = False
        self.calls = []
        self.connect_ok = True
        self.payload = {"results": [_paper(1), _paper(2), _paper(3)]}
        self.error = None
        _FakeClient.last_instance = self

    def connect(self):
        self.connected = True
        return self.connect_ok

    def call_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self.error:
            return None, self.error
        return self.payload, None

    def disconnect(self):
        self.connected = False


def _install_fake(monkeypatch, configure=None):
    """Patch _ResearchMCPClient with a factory yielding a configured _FakeClient."""
    holder = {}

    def factory(command, timeout_s=20.0):
        client = _FakeClient(command, timeout_s)
        if configure:
            configure(client)
        holder["client"] = client
        return client

    monkeypatch.setattr(perseus, "_ResearchMCPClient", factory)
    return holder


# ---------------------------------------------------------------------------
# Parsing: query + limit (both forms)
# ---------------------------------------------------------------------------

def test_parses_query_and_flag_limit(monkeypatch):
    holder = _install_fake(monkeypatch)
    out = perseus.resolve_research('"transformer attention mechanisms" --limit 2', _research_cfg())
    assert '### Research: "transformer attention mechanisms"' in out
    tool, args = holder["client"].calls[0]
    assert tool == "search_papers"
    assert args["query"] == "transformer attention mechanisms"
    assert args["num_results"] == 2


def test_parses_kv_limit_form(monkeypatch):
    holder = _install_fake(monkeypatch)
    perseus.resolve_research('"RAG retrieval" limit=3', _research_cfg())
    _tool, args = holder["client"].calls[0]
    assert args["num_results"] == 3


def test_default_limit_used_when_absent(monkeypatch):
    holder = _install_fake(monkeypatch)
    perseus.resolve_research('"no explicit limit"', _research_cfg(default_limit=4))
    _tool, args = holder["client"].calls[0]
    assert args["num_results"] == 4


def test_limit_clamped_to_25(monkeypatch):
    holder = _install_fake(monkeypatch)
    perseus.resolve_research('"big" --limit 9999', _research_cfg())
    _tool, args = holder["client"].calls[0]
    assert args["num_results"] == 25


# ---------------------------------------------------------------------------
# Output shape: <details>, **Methods:**, **Results:**
# ---------------------------------------------------------------------------

def test_output_contains_details_methods_results(monkeypatch):
    _install_fake(monkeypatch)
    out = perseus.resolve_research('"q" --limit 2', _research_cfg())
    assert "<details>" in out
    assert "<summary>" in out
    assert "**Methods:**" in out
    assert "**Results:**" in out


def test_injects_n_blocks(monkeypatch):
    def cfg_two(client):
        client.payload = {"results": [_paper(1), _paper(2)]}
    _install_fake(monkeypatch, configure=cfg_two)
    out = perseus.resolve_research('"q" --limit 2', _research_cfg())
    assert out.count("<details>") == 2
    assert "Paper Number 1" in out and "Paper Number 2" in out


def test_missing_fields_render_na(monkeypatch):
    def sparse(client):
        client.payload = {"results": [{"title": "Only A Title"}]}
    _install_fake(monkeypatch, configure=sparse)
    out = perseus.resolve_research('"q"', _research_cfg())
    assert "Only A Title" in out
    assert "_n/a_" in out  # authors/year/methods/results all missing


# ---------------------------------------------------------------------------
# Token cap + truncation note
# ---------------------------------------------------------------------------

def test_token_cap_truncates_and_notes(monkeypatch):
    def many(client):
        client.payload = {"results": [_paper(i) for i in range(1, 11)]}
    _install_fake(monkeypatch, configure=many)
    # Tiny budget so only a couple of blocks fit.
    out = perseus.resolve_research('"q" --limit 10', _research_cfg(max_tokens=60))
    assert "truncated" in out.lower()
    # Not all 10 papers should be present under the tiny cap.
    assert out.count("<details>") < 10


def test_no_truncation_note_when_under_budget(monkeypatch):
    def two(client):
        client.payload = {"results": [_paper(1), _paper(2)]}
    _install_fake(monkeypatch, configure=two)
    out = perseus.resolve_research('"q" --limit 2', _research_cfg(max_tokens=100000))
    assert "truncated" not in out.lower()
    assert out.count("<details>") == 2


# ---------------------------------------------------------------------------
# Graceful fallback: provider unavailable → no exception
# ---------------------------------------------------------------------------

def test_fallback_when_connect_fails(monkeypatch):
    def fail(client):
        client.connect_ok = False
    _install_fake(monkeypatch, configure=fail)
    out = perseus.resolve_research('"q"', _research_cfg())
    assert "@research: provider unavailable" in out


def test_fallback_when_call_errors(monkeypatch):
    def err(client):
        client.error = "MCP timeout"
    _install_fake(monkeypatch, configure=err)
    out = perseus.resolve_research('"q"', _research_cfg())
    assert "@research: provider unavailable" in out


def test_internal_exception_is_swallowed(monkeypatch):
    def boom(command, timeout_s=20.0):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(perseus, "_ResearchMCPClient", boom)
    out = perseus.resolve_research('"q"', _research_cfg())
    # No exception propagates; quiet marker returned.
    assert "@research: provider unavailable" in out


# ---------------------------------------------------------------------------
# Disabled config → NO Popen / NO subprocess at all
# ---------------------------------------------------------------------------

def test_disabled_config_does_not_spawn(monkeypatch):
    spawned = {"hit": False}

    def tripwire(command, timeout_s=20.0):
        spawned["hit"] = True
        return _FakeClient(command, timeout_s)

    monkeypatch.setattr(perseus, "_ResearchMCPClient", tripwire)
    out = perseus.resolve_research('"q"', _research_cfg(enabled=False))
    assert spawned["hit"] is False
    assert "@research: provider unavailable" in out


def test_disabled_config_never_calls_popen(monkeypatch):
    """Belt-and-suspenders: patch subprocess.Popen itself and assert untouched."""
    called = {"hit": False}
    real_popen = perseus.subprocess.Popen

    def guard(*a, **k):
        called["hit"] = True
        return real_popen(*a, **k)

    monkeypatch.setattr(perseus.subprocess, "Popen", guard)
    perseus.resolve_research('"q"', _research_cfg(enabled=False))
    assert called["hit"] is False


# ---------------------------------------------------------------------------
# Empty query → warning
# ---------------------------------------------------------------------------

def test_empty_query_warns(monkeypatch):
    _install_fake(monkeypatch)
    out = perseus.resolve_research('""', _research_cfg())
    assert "no query specified" in out


def test_blank_args_warns(monkeypatch):
    _install_fake(monkeypatch)
    out = perseus.resolve_research("   ", _research_cfg())
    assert "no query specified" in out


# ---------------------------------------------------------------------------
# Registry + build artifact
# ---------------------------------------------------------------------------

def test_directive_registered():
    assert "@research" in perseus.DIRECTIVE_REGISTRY
    spec = perseus.DIRECTIVE_REGISTRY["@research"]
    assert spec.resolver is perseus.resolve_research
    assert spec.executes_shell is False
    assert spec.call_sig == "acw"


def test_built_artifact_contains_resolver():
    from pathlib import Path
    artifact = Path(__file__).resolve().parents[1] / "perseus.py"
    text = artifact.read_text(encoding="utf-8")
    assert "def resolve_research" in text
    assert "class _ResearchMCPClient" in text


# ---------------------------------------------------------------------------
# End-to-end through the renderer (acceptance criterion)
# ---------------------------------------------------------------------------

def test_render_source_injects_paper_blocks(monkeypatch):
    def two(client):
        client.payload = {"results": [_paper(1), _paper(2)]}
    _install_fake(monkeypatch, configure=two)
    source = '@perseus v0.5\n@research "attention" --limit 2'
    out = perseus.render_source(source, _research_cfg(), None)
    assert "<details>" in out
    assert "**Methods:**" in out
    assert "**Results:**" in out
