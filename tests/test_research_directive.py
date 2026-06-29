"""Tests for the @research directive (#513).

The external paper-search MCP subprocess is ALWAYS mocked — these tests must
never spawn a real `npx`/`bgpt-mcp` process. We patch
``_ResearchMCPClient.connect`` / ``.call_tool`` / ``.disconnect`` (and, for the
disabled-config test, ``subprocess.Popen``) so behaviour is deterministic and
offline.
"""
import copy
import json

import pytest

from conftest import perseus


# ── helpers ────────────────────────────────────────────────────────────────
def _research_cfg(enabled=True, **over):
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["research"]["enabled"] = enabled
    for k, v in over.items():
        c["research"][k] = v
    return c


_FAKE_PAPERS = {
    "results": [
        {
            "title": "Attention Is All You Need",
            "authors": ["Vaswani", "Shazeer", "Parmar"],
            "year": 2017,
            "methods": "Transformer architecture with self-attention; trained on WMT14.",
            "results": "BLEU 28.4 EN-DE; state of the art at lower training cost.",
        },
        {
            "title": "A Paper Missing Fields",
            # no authors / year / methods / results on purpose
        },
        {
            "title": "Third Paper",
            "authors": ["Doe"],
            "year": 2021,
            "methods": "RCT, n=120.",
            "results": "p < 0.05 improvement.",
        },
    ]
}


class _FakeClient:
    """Stand-in for _ResearchMCPClient. Records the args it was called with."""
    last_arguments = None
    last_tool = None
    connect_returns = True
    call_returns = (_FAKE_PAPERS, None)

    def __init__(self, command, timeout_s=10.0):
        self.command = command

    def connect(self):
        return type(self).connect_returns

    def call_tool(self, tool_name, arguments):
        type(self).last_tool = tool_name
        type(self).last_arguments = arguments
        return type(self).call_returns

    def disconnect(self):
        pass


@pytest.fixture
def patched_client(monkeypatch):
    """Patch resolve_research to use a controllable fake MCP client."""
    _FakeClient.last_arguments = None
    _FakeClient.last_tool = None
    _FakeClient.connect_returns = True
    _FakeClient.call_returns = (copy.deepcopy(_FAKE_PAPERS), None)
    monkeypatch.setattr(perseus, "_ResearchMCPClient", _FakeClient)
    return _FakeClient


# ── parsing ────────────────────────────────────────────────────────────────
def test_parse_query_and_limit_kv_form(patched_client):
    cfg = _research_cfg()
    out = perseus.resolve_research('"transformer models" limit=2', cfg, None)
    assert patched_client.last_arguments["query"] == "transformer models"
    assert patched_client.last_arguments["num_results"] == 2
    assert 'Research: "transformer models"' in out


def test_parse_query_and_limit_flag_form(patched_client):
    cfg = _research_cfg()
    out = perseus.resolve_research('"crispr delivery" --limit 3', cfg, None)
    assert patched_client.last_arguments["query"] == "crispr delivery"
    assert patched_client.last_arguments["num_results"] == 3


def test_default_limit_used_when_unspecified(patched_client):
    cfg = _research_cfg(default_limit=4)
    perseus.resolve_research('"some query"', cfg, None)
    assert patched_client.last_arguments["num_results"] == 4


def test_limit_clamped_to_max(patched_client):
    cfg = _research_cfg()
    perseus.resolve_research('"q" --limit 999', cfg, None)
    assert patched_client.last_arguments["num_results"] == 25


# ── output shape ───────────────────────────────────────────────────────────
def test_output_contains_details_methods_results(patched_client):
    cfg = _research_cfg()
    out = perseus.resolve_research('"transformers" --limit 3', cfg, None)
    assert "<details>" in out
    assert "**Methods:**" in out
    assert "**Results:**" in out
    assert "Attention Is All You Need" in out
    # authors list joined and year present in the summary
    assert "Vaswani" in out
    assert "2017" in out


def test_missing_fields_render_na(patched_client):
    cfg = _research_cfg()
    out = perseus.resolve_research('"q" --limit 2', cfg, None)
    # The second paper has no authors/year/methods/results -> _n/a_
    assert "_n/a_" in out


def test_limit_caps_number_of_blocks(patched_client):
    cfg = _research_cfg()
    out = perseus.resolve_research('"q" --limit 1', cfg, None)
    assert out.count("<details>") == 1


# ── token cap ──────────────────────────────────────────────────────────────
def test_token_cap_and_truncation_note(patched_client):
    # A pile of long papers + a tiny max_tokens forces truncation.
    big = {"results": [
        {
            "title": f"Paper {i}",
            "authors": ["Author"],
            "year": 2020,
            "methods": "word " * 80,
            "results": "result " * 80,
        }
        for i in range(10)
    ]}
    patched_client.call_returns = (big, None)
    cfg = _research_cfg(max_tokens=50)
    out = perseus.resolve_research('"q" --limit 10', cfg, None)
    assert "truncated" in out.lower()
    # Estimated tokens (~words*1.3) must not blow far past the cap.
    est = int(len(out.split()) * 1.3)
    assert est <= 50 + 40  # cap + small allowance for the truncation note


# ── graceful degradation ───────────────────────────────────────────────────
def test_fallback_when_provider_unavailable(patched_client):
    patched_client.connect_returns = False
    cfg = _research_cfg()
    out = perseus.resolve_research('"q"', cfg, None)
    assert "unavailable" in out.lower()
    # No exception, still returns the heading.
    assert 'Research: "q"' in out


def test_provider_error_no_exception(patched_client):
    patched_client.call_returns = (None, "MCP timeout")
    cfg = _research_cfg()
    out = perseus.resolve_research('"q"', cfg, None)
    assert isinstance(out, str)
    assert "MCP timeout" in out or "provider error" in out.lower()


def test_disabled_config_does_not_spawn_subprocess(monkeypatch):
    """When research.enabled is False, NO Popen call may happen."""
    calls = []
    real_popen = perseus.subprocess.Popen

    def _spy(*a, **k):
        calls.append(a)
        return real_popen(*a, **k)

    monkeypatch.setattr(perseus.subprocess, "Popen", _spy)
    cfg = _research_cfg(enabled=False)
    out = perseus.resolve_research('"q" --limit 3', cfg, None)
    assert calls == []  # never spawned
    assert "disabled" in out.lower()


def test_empty_query_warns(patched_client):
    cfg = _research_cfg()
    out = perseus.resolve_research('   ', cfg, None)
    assert "no query" in out.lower()
    # Must not have called the provider.
    assert patched_client.last_arguments is None


def test_no_papers_found(patched_client):
    patched_client.call_returns = ({"results": []}, None)
    cfg = _research_cfg()
    out = perseus.resolve_research('"obscure" --limit 5', cfg, None)
    assert "no papers found" in out.lower()


# ── registry + build artifact ──────────────────────────────────────────────
def test_directive_registered():
    perseus._bind_registry()
    assert "@research" in perseus.DIRECTIVE_REGISTRY
    spec = perseus.DIRECTIVE_REGISTRY["@research"]
    assert spec.resolver is perseus.resolve_research
    assert spec.executes_shell is False
    assert spec.call_sig == "acw"


def test_built_artifact_contains_resolver():
    import pathlib
    artifact = pathlib.Path(__file__).resolve().parents[1] / "perseus.py"
    text = artifact.read_text(encoding="utf-8")
    assert "def resolve_research" in text


def test_render_through_registry(patched_client):
    """End-to-end: @research resolves via render_source with mocked client."""
    cfg = _research_cfg()
    source = '@perseus v0.5\n@research "transformers" --limit 2'
    out = perseus.render_source(source, cfg, None)
    assert "<details>" in out
    assert "**Methods:**" in out
