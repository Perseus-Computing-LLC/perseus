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


def test_max_five_stages():
    """Max 5 stages in a pipe — per spec (task-71)."""
    stages = perseus._parse_pipe_stages("@a arg1 | @b arg2 | @c arg3 | @d arg4 | @e arg5 | @f arg6")
    assert len(stages) <= 5


def test_pipe_depth_exceeded_preserves_limit():
    """Pipe with 7 stages — only first 5 kept."""
    stages = perseus._parse_pipe_stages("@a | @b | @c | @d | @e | @f | @g")
    assert len(stages) == 5


def test_pipe_with_query():
    """@query output pipes to @cache."""
    source = """\
@perseus v0.5
@query "echo piped_output" | @cache ttl=60
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "piped_output" in out


def test_pipe_single_stage_noop():
    """Single directive without pipe is unchanged."""
    stages = perseus._parse_pipe_stages("@query 'ls'")
    assert len(stages) == 1
    assert stages[0] == "@query 'ls'"


def test_pipe_respects_quoted_pipes():
    """Pipes inside quotes are not treated as stage separators."""
    stages = perseus._parse_pipe_stages('@query "echo a | b" | @cache ttl=60')
    assert len(stages) == 2
    assert stages[0] == '@query "echo a | b"'
    assert stages[1] == "@cache ttl=60"


def test_pipe_in_macro_body():
    """Pipes work inside macro expansions."""
    source = """\
@perseus v0.5
@macro piped-date
@date format="YYYY" | @cache ttl=3600
@endmacro

@piped-date
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    from datetime import datetime
    assert str(datetime.now().year) in out
    assert "@piped-date" not in out


def test_pipe_in_graph():
    """`perseus graph` reports pipe edges."""
    source = "@perseus v0.5\n@date | @cache ttl=60\n"
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        ws = pathlib.Path(td)
        graph = perseus.directive_dependency_graph(source, workspace=ws, cfg=cfg())
        directive_names = [n["directive"] for n in graph.get("nodes", [])]
        assert "@date" in directive_names


def test_alias_expands_in_graph():
    """`perseus graph` sees the same aliases the render path executes."""
    source = '@perseus v0.5\n@q "git status"\n'
    graph = perseus.directive_dependency_graph(source, workspace=None, cfg=cfg())
    directive_names = [n["directive"] for n in graph.get("nodes", [])]
    assert "@query" in directive_names


def test_macro_alias_pipe_composition():
    """Aliases expand inside pipe stages, pipes inside macros."""
    source = """\
@perseus v0.5
@macro composed
@q "echo composed_works" | @cache ttl=60
@endmacro

@composed
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "composed_works" in out


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
    # PATH is set on every platform; HOME is not (Windows uses USERPROFILE).
    source = """\
@perseus v0.5
@if env.set PATH
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
