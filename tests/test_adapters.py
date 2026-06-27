"""Tests for the Context Adapter SDK (#473) — resolve once, compose into the stack."""

import sys
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def test_resolve_context_inline_source():
    out = perseus.resolve_context("@perseus\nHello world", cfg())
    assert "Hello world" in out


def test_resolve_context_from_file(tmp_path):
    src = tmp_path / "ctx.perseus"
    src.write_text("@perseus\nFrom a file", encoding="utf-8")
    out = perseus.resolve_context(src, cfg())
    assert "From a file" in out


def test_resolve_context_file_workspace_resolves_includes(tmp_path):
    # An @include relative path resolves against the file's directory by default.
    (tmp_path / "part.md").write_text("included body", encoding="utf-8")
    src = tmp_path / "ctx.perseus"
    src.write_text("@perseus\n@include part.md", encoding="utf-8")
    out = perseus.resolve_context(src, cfg())
    assert "included body" in out


def test_as_messages_shape():
    msgs = perseus.as_messages("CTX")
    assert msgs == [{"role": "system", "content": "CTX"}]
    assert perseus.as_messages("CTX", role="user")[0]["role"] == "user"


def test_compose_text_and_messages():
    assert perseus.compose("@perseus\nHi", target="text", cfg=cfg()).strip() == "Hi"
    msgs = perseus.compose("@perseus\nHi", target="messages", cfg=cfg())
    assert msgs[0]["content"].strip() == "Hi"


def test_compose_unknown_target_errors():
    with pytest.raises(ValueError):
        perseus.compose("@perseus\nHi", target="nope", cfg=cfg())


def test_to_langchain_messages():
    pytest.importorskip("langchain_core")
    msgs = perseus.to_langchain_messages("CTX")
    assert len(msgs) == 1
    assert msgs[0].content == "CTX"
    assert msgs[0].type == "system"


def test_to_llamaindex_messages():
    pytest.importorskip("llama_index.core")
    msgs = perseus.to_llamaindex_messages("CTX")
    assert len(msgs) == 1
    assert msgs[0].content == "CTX"


def test_compose_langchain_target():
    pytest.importorskip("langchain_core")
    msgs = perseus.compose("@perseus\nGraph ctx", target="langchain", cfg=cfg())
    assert msgs[0].content.strip() == "Graph ctx"
