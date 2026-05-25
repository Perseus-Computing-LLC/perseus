import pytest
from pathlib import Path

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── Test: Simple macro expansion (no params) ─────────────────────────────────

def test_simple_macro_expansion():
    source = """\
@perseus v0.5

@macro hello
Hello, world!
@endmacro

@hello
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "Hello, world!" in out
    assert "@macro" not in out
    assert "@endmacro" not in out


# ── Test: Parameterized macro substitution ───────────────────────────────────

def test_parameterized_macro():
    source = """\
@perseus v0.5

@macro greet %name%
Greetings, %name%!
@endmacro

@greet Thomas
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "Greetings, Thomas!" in out


# ── Test: Macro in macros file loaded correctly ──────────────────────────────

def test_macro_from_workspace_file(tmp_path):
    macros_file = tmp_path / ".perseus" / "macros.md"
    macros_file.parent.mkdir(parents=True)
    macros_file.write_text("""\
@macro workspace-hello
Hello from workspace macros!
@endmacro
""")

    source = """\
@perseus v0.5
@workspace-hello
"""
    c = cfg()
    out = perseus.render_source(source, c, tmp_path)
    assert "Hello from workspace macros!" in out


# ── Test: Macro shadowing (source doc overrides macros file) ─────────────────

def test_macro_shadowing(tmp_path):
    macros_file = tmp_path / ".perseus" / "macros.md"
    macros_file.parent.mkdir(parents=True)
    macros_file.write_text("""\
@macro greet %name%
Hello from file, %name%!
@endmacro
""")

    source = """\
@perseus v0.5

@macro greet %name%
Hello from source, %name%!
@endmacro

@greet Thomas
"""
    c = cfg()
    out = perseus.render_source(source, c, tmp_path)
    assert "Hello from source, Thomas!" in out
    assert "Hello from file" not in out


# ── Test: Recursive macro (chained) ──────────────────────────────────────────

def test_macro_chaining():
    source = """\
@perseus v0.5

@macro inner
inner content
@endmacro

@macro outer
outer: @inner
@endmacro

@outer
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "outer: inner content" in out


# ── Test: Macro cycle detection (depth-limited) ──────────────────────────────

def test_macro_cycle_stops():
    """A → B → A cycle should stop after MAX_MACRO_DEPTH without infinite recursion."""
    source = """\
@perseus v0.5

@macro a
from A: @b
@endmacro

@macro b
from B: @a
@endmacro

@a
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    # Should not crash — output will either be partially expanded or contain the raw invocation
    assert "from A" in out or "from B" in out
    # Verify it didn't infinite-recursion (test just needs to not hang)


# ── Test: Macro inside @if block (macros expand before if evaluation) ────────

def test_macro_inside_if_block():
    source = """\
@perseus v0.5

@macro show-something
something
@endmacro

@if env.set HOME
@show-something
@endif
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "something" in out


# ── Test: Macro referencing undefined macro → warning ────────────────────────

def test_macro_referencing_undefined():
    source = """\
@perseus v0.5

@macro test-macro
@nonexistent
@endmacro

@test-macro
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    # The @nonexistent should remain as-is (unexpanded) — render should not crash
    assert "@nonexistent" in out


# ── Test: Empty macro → no output ────────────────────────────────────────────

def test_empty_macro():
    source = """\
@perseus v0.5

@macro nothing
@endmacro

Before
@nothing
After
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "Before" in out
    assert "After" in out
    # Empty macro expands to nothing — Before and After should be adjacent
    lines = [l for l in out.splitlines() if l.strip()]
    before_idx = next(i for i, l in enumerate(lines) if "Before" in l)
    after_idx = next(i for i, l in enumerate(lines) if "After" in l)
    # They should be consecutive (or very close, accounting for empty lines)
    assert after_idx == before_idx + 1 or lines[before_idx + 1].strip() == ""


# ── Test: Macro preserves indentation and structure ──────────────────────────

def test_macro_preserves_structure():
    source = """\
@perseus v0.5

@macro header
## Section Title
- item 1
- item 2
@endmacro

@header
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "## Section Title" in out
    assert "- item 1" in out
    assert "- item 2" in out


# ── Test: Multiple parameters ────────────────────────────────────────────────

def test_multiple_parameters():
    source = """\
@perseus v0.5

@macro deploy %env% %version%
Deploying %env% at version %version%
@endmacro

@deploy production 2.0
"""
    c = cfg()
    out = perseus.render_source(source, c, None)
    assert "Deploying production at version 2.0" in out
