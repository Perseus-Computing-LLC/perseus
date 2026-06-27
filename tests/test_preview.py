"""Tests for the diffable token-annotated compile preview (`perseus preview`).

Covers:
- total_tokens reconciles with estimate_tokens of the rendered context.
- output is byte-identical across runs (the diffability guarantee).
- the JSON report carries no volatile fields (no duration_ms / cached / timestamp).
- per-directive attribution: a resolved directive appears with a token count.
- tier-skipped directives are reported (normalized) and not counted as resolved.
- cmd_preview returns 0 and never mutates the source file.
"""
from __future__ import annotations

import argparse
import json

import pytest

from conftest import perseus

if perseus is None:  # pragma: no cover
    pytest.skip("perseus build artifact unavailable", allow_module_level=True)


def _args(src, **kw):
    base = dict(command="preview", source=str(src), json=False, tier=None, no_cache=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _write(tmp_path, monkeypatch, body):
    home = tmp_path / "home"; home.mkdir()
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    ws = tmp_path / "ws"; ws.mkdir()
    src = ws / "ctx.md"
    src.write_text(body, encoding="utf-8")
    return ws, src


def test_total_reconciles_with_rendered_tokens(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n# A\nalpha text here\n\n## B\nbeta text here\n")
    rc = perseus.cmd_preview(_args(src, json=True), {})
    assert rc == 0
    report = json.loads(capsys.readouterr().out)

    # Reconcile against the rendered context via the same path the command uses.
    cfg = perseus.load_config(ws)
    perseus._merge_pack_mimir_config(cfg, ws)
    rendered = perseus.render_source(src.read_text(encoding="utf-8"), cfg, ws, max_tier=3)
    assert report["total_tokens"] == perseus.estimate_tokens(rendered)
    assert report["total_tokens"] > 0


def test_preview_is_byte_identical_across_runs(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n# Static\nno directives here, fully deterministic\n")
    perseus.cmd_preview(_args(src, json=True), {})
    first = capsys.readouterr().out
    perseus.cmd_preview(_args(src, json=True), {})
    second = capsys.readouterr().out
    assert first == second

    # human output is likewise stable run-to-run
    perseus.cmd_preview(_args(src), {})
    h1 = capsys.readouterr().out
    perseus.cmd_preview(_args(src), {})
    h2 = capsys.readouterr().out
    assert h1 == h2


def test_json_report_has_no_volatile_fields(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\n# H\n@date\n")
    perseus.cmd_preview(_args(src, json=True), {})
    report = json.loads(capsys.readouterr().out)

    assert {"source", "tier", "total_tokens", "total_bytes",
            "directive_count", "directives", "sections", "skipped"} <= report.keys()
    assert report["source"] == "ctx.md"            # basename, not an absolute path
    assert "timestamp" not in report               # no wall-clock in a diffable report
    for d in report["directives"]:
        assert set(d.keys()) == {"name", "args", "tokens", "pct"}
        assert "duration_ms" not in d and "cached" not in d


def test_directive_attribution(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\n# Header\n@date\n")
    perseus.cmd_preview(_args(src, json=True), {})
    report = json.loads(capsys.readouterr().out)
    by_name = {d["name"]: d for d in report["directives"]}
    assert "date" in by_name
    assert by_name["date"]["tokens"] > 0


def test_tier_skip_reported_not_counted(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch,
                     "@perseus\n\n# Files\n@tree .\n\n## Always\n@date\n")
    perseus.cmd_preview(_args(src, json=True, tier=1), {})
    report = json.loads(capsys.readouterr().out)
    assert report["tier"] == 1
    skipped_names = [s["name"] for s in report["skipped"]]
    assert "tree" in skipped_names                 # a tier-3 directive, skipped at tier 1
    assert "tree" not in [d["name"] for d in report["directives"]]
    # skipped names are normalized — no leading '@'
    assert all(not s["name"].startswith("@") for s in report["skipped"])


def test_cmd_preview_does_not_mutate_source(tmp_path, monkeypatch, capsys):
    ws, src = _write(tmp_path, monkeypatch, "@perseus\n\n# Keep\noriginal body\n")
    before = src.read_text(encoding="utf-8")
    perseus.cmd_preview(_args(src), {})
    capsys.readouterr()
    assert src.read_text(encoding="utf-8") == before
