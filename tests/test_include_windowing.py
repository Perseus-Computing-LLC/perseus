"""Tests for @include windowing modifiers — last= / since= and the oversize
advisory warning (#433: AGENTS.md grows unbounded when @include references a
large file)."""
import copy
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _write_log(tmp_path: Path) -> Path:
    """A dated session log like a SAM Chief-of-Staff AGENTS.local.md."""
    log = tmp_path / "log.md"
    log.write_text(
        "# Session Log\n\nPreamble line.\n\n"
        "## 2020-01-01 ancient entry\nold body\n\n"
        "## 2099-12-31 future entry\nnew body\n",
        encoding="utf-8",
    )
    return log


def test_include_last_keeps_final_n_lines(tmp_path):
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md" last=2', tmp_path, cfg())
    assert "## 2099-12-31 future entry" in out
    assert "new body" in out
    # Earlier content is dropped.
    assert "ancient entry" not in out
    assert "Preamble line." not in out
    assert len(out.splitlines()) == 2


def test_include_since_keeps_recent_dated_sections(tmp_path):
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md" since=1d', tmp_path, cfg())
    # Preamble (before first dated heading) is always kept.
    assert "Preamble line." in out
    # Recent section kept, ancient section dropped.
    assert "future entry" in out
    assert "new body" in out
    assert "ancient entry" not in out
    assert "old body" not in out


def test_include_since_units_week_and_hour(tmp_path):
    log = tmp_path / "log.md"
    recent = (datetime.now() - timedelta(days=2)).date().isoformat()
    old = (datetime.now() - timedelta(days=30)).date().isoformat()
    log.write_text(f"## {old} old\nx\n\n## {recent} recent\ny\n", encoding="utf-8")
    out = perseus.resolve_include('"log.md" since=1w', tmp_path, cfg())
    assert recent in out and "y" in out
    assert old not in out


def test_include_last_and_since_combine(tmp_path):
    _write_log(tmp_path)
    # since drops the ancient section first, then last caps the remainder.
    out = perseus.resolve_include('"log.md" since=1d last=1', tmp_path, cfg())
    assert len(out.splitlines()) == 1
    assert "ancient entry" not in out


def test_include_rejects_unknown_option(tmp_path):
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md" foo=1', tmp_path, cfg())
    assert "⚠" in out
    assert "unsupported option" in out


def test_include_rejects_bad_last(tmp_path):
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md" last=abc', tmp_path, cfg())
    assert "⚠" in out
    assert "last=" in out


def test_include_rejects_bad_since(tmp_path):
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md" since=soon', tmp_path, cfg())
    assert "⚠" in out
    assert "since=" in out


def test_include_unexpected_trailing_input_still_rejected(tmp_path):
    """Genuine garbage (not key=value) still warns, preserving strictness."""
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md" garbage', tmp_path, cfg())
    assert "⚠" in out
    assert "unexpected trailing input" in out


def test_include_no_options_unchanged(tmp_path):
    """A bare @include with no modifiers behaves exactly as before."""
    _write_log(tmp_path)
    out = perseus.resolve_include('"log.md"', tmp_path, cfg())
    assert "Preamble line." in out
    assert "ancient entry" in out
    assert "future entry" in out


def test_include_oversize_warning_opt_in(tmp_path):
    big = tmp_path / "big.md"
    big.write_text("x" * 5000, encoding="utf-8")
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["render"]["max_include_warn_bytes"] = 1000
    out = perseus.resolve_include('"big.md"', tmp_path, c)
    assert "⚠" in out
    assert "warn threshold" in out
    # Content is still included in full (advisory only).
    assert "x" * 5000 in out


def test_include_oversize_warning_disabled_by_default(tmp_path):
    big = tmp_path / "big.md"
    big.write_text("x" * 5000, encoding="utf-8")
    out = perseus.resolve_include('"big.md"', tmp_path, cfg())
    assert "warn threshold" not in out


def test_include_registry_exposes_window_args():
    spec = perseus.DIRECTIVE_REGISTRY["@include"]
    assert "last=" in spec.args
    assert "since=" in spec.args
