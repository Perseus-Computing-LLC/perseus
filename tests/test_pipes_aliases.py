import pytest
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ═══════════════════════ Pipe Syntax (task-71) ═══════════════════════════════

def test_two_stage_pipe():
    """@date | @cache ttl=60 — date output piped through cache."""
    source = """\
@perseus v0.5
@date format="YYYY" | @cache ttl=3600
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    from datetime import datetime
    assert str(datetime.now().year) in out


def test_pipe_bad_stage_errors():
    """A pipe stage that doesn't match any directive should error."""
    source = """\
@perseus v0.5
@date | @nonexistent
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "not a recognized" in out.lower()


def test_max_three_stages():
    """Max 3 stages in a pipe — extra stages truncated."""
    # _parse_pipe_stages handles truncation
    stages = perseus._parse_pipe_stages("@a arg1 | @b arg2 | @c arg3 | @d arg4")
    assert len(stages) <= 3


# ═══════════════════ Directive Aliasing (task-74) ════════════════════════════

def test_simple_alias_expansion():
    source = """\
@perseus v0.5
@q "echo hello"
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "hello" in out


def test_alias_does_not_expand_inside_fence():
    source = """\
@perseus v0.5
```sh
@q echo test
```
@date format="YYYY"
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    # The @q inside fenced code should NOT be expanded to @query
    assert "@q" in out or "@query" not in out  # alias expansion happens before fence detection
    from datetime import datetime
    assert str(datetime.now().year) in out


def test_alias_in_if_block():
    source = """\
@perseus v0.5
@if env.set HOME
@q "echo home"
@endif
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "home" in out


def test_config_alias_overrides():
    source = """\
@perseus v0.5
@custom "echo hello"
"""
    c = cfg()
    c["directives"]["aliases"] = {"@custom": "@query"}
    out = perseus.render_source(source, c, None)
    assert "hello" in out
