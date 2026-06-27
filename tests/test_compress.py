"""Tests for the deterministic compress pass (`perseus compress`).

Covers:
- estimate_tokens is deterministic and non-zero for non-empty text.
- compress is a no-op when disabled (default) — render output unchanged.
- trailing-whitespace trim, blank-line collapse (max_blank_lines), adjacent dedup.
- fenced code blocks are preserved VERBATIM (no trim/dedup/collapse inside).
- strip_comments is opt-in.
- the report's reduction math is consistent; compression is deterministic.
- cmd_compress writes output, emits JSON, and never mutates the source file.
"""
from __future__ import annotations

import argparse
import copy
import json

import pytest

from conftest import perseus

if perseus is None:  # pragma: no cover
    pytest.skip("perseus build artifact unavailable", allow_module_level=True)


def _cfg(**compress):
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["compress"]["enabled"] = True
    c["compress"].update(compress)
    return c


def test_estimate_tokens_deterministic():
    assert perseus.estimate_tokens("") == 0
    t = perseus.estimate_tokens("the quick brown fox jumps")
    assert t > 0 and perseus.estimate_tokens("the quick brown fox jumps") == t


def test_disabled_is_noop():
    text = "a\n\n\n\nb   \n"
    out, rep = perseus.compress_text(text, copy.deepcopy(perseus.DEFAULT_CONFIG))
    assert out == text
    assert rep["reduction_pct"] == 0.0
    assert rep["rules"] == []


def test_trim_trailing_whitespace():
    out, rep = perseus.compress_text("hello   \nworld\t\n", _cfg())
    assert out == "hello\nworld\n"
    assert "trim_trailing" in rep["rules"]


def test_collapse_blank_lines_respects_max():
    out, _ = perseus.compress_text("a\n\n\n\n\nb\n", _cfg(max_blank_lines=1))
    assert out == "a\n\nb\n"
    out2, _ = perseus.compress_text("a\n\n\n\n\nb\n", _cfg(max_blank_lines=2))
    assert out2 == "a\n\n\nb\n"


def test_dedup_adjacent_lines():
    out, rep = perseus.compress_text("x\nx\nx\ny\n", _cfg())
    assert out == "x\ny\n"
    assert "dedup_adjacent" in rep["rules"]
    # non-adjacent duplicates are preserved
    out2, _ = perseus.compress_text("x\ny\nx\n", _cfg())
    assert out2 == "x\ny\nx\n"


def test_dedup_can_be_disabled():
    out, _ = perseus.compress_text("x\nx\n", _cfg(dedup_adjacent=False))
    assert out == "x\nx\n"


def test_code_fence_preserved_verbatim():
    text = "```\ncode   with   spaces\nx\nx\n\n\nkept\n```\n"
    out, _ = perseus.compress_text(text, _cfg())
    # trailing spaces, adjacent dupes, and blank runs inside the fence survive
    assert "code   with   spaces" in out
    assert "x\nx\n" in out
    assert "\n\n\nkept" in out


def test_strip_comments_opt_in():
    text = "before <!-- secret note --> after\n"
    keep, _ = perseus.compress_text(text, _cfg())
    assert "<!-- secret note -->" in keep
    drop, rep = perseus.compress_text(text, _cfg(strip_comments=True))
    assert "secret note" not in drop
    assert "strip_comments" in rep["rules"]


def test_report_math_and_determinism():
    text = "title   \n\n\n\nrepeat\nrepeat\n\nend\n"
    a, ra = perseus.compress_text(text, _cfg())
    b, rb = perseus.compress_text(text, _cfg())
    assert a == b and ra == rb                       # deterministic
    assert ra["tokens_saved"] == ra["tokens_before"] - ra["tokens_after"]
    assert ra["tokens_after"] <= ra["tokens_before"]
    assert ra["reduction_pct"] >= 0.0


# ── cmd_compress CLI ─────────────────────────────────────────────────────────

def _args(src, **kw):
    base = dict(command="compress", source=str(src), output=None, json=False,
                max_blank_lines=None, no_dedup=False, strip_comments=False,
                tier=None, no_cache=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_cmd_compress_writes_output_and_keeps_source(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\nAlpha\nAlpha\n\n\n\nBeta   \n", encoding="utf-8")
    out = ws / "out.md"

    rc = perseus.cmd_compress(_args(src, output=str(out)), {})
    assert rc == 0
    body = out.read_text(encoding="utf-8")
    assert body.count("Alpha") == 1            # deduped
    assert "Beta" in body and "Beta   " not in body  # trimmed
    # source untouched
    assert "Alpha\nAlpha" in src.read_text(encoding="utf-8")


def test_cmd_compress_json_report(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text("@perseus\n\nx\nx\n\n\n\ny\n", encoding="utf-8")

    rc = perseus.cmd_compress(_args(src, json=True), {})
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tokens_after"] <= payload["tokens_before"]
    assert set(["tokens_before", "tokens_after", "reduction_pct", "rules"]) <= payload.keys()
