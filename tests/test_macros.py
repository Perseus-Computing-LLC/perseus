import pytest
from pathlib import Path
from datetime import datetime
from conftest import cfg, perseus

def test_simple_macro_expansion():
    text = """@perseus
@macro project-health
Custom Macro Content
@endmacro

@project-health"""
    out = perseus.render_source(text, cfg(), None)
    assert "Custom Macro Content" in out
    assert "@project-health" not in out
    assert "@macro" not in out
    assert "@endmacro" not in out

def test_macro_case_insensitivity():
    text = """@perseus
@macro Project-Health
Custom Macro Content
@endmacro

@project-health"""
    out = perseus.render_source(text, cfg(), None)
    assert "@project-health" not in out
    assert "Custom Macro Content" in out

def test_recursive_macro_expansion():
    text = """@perseus
@macro level2
Deep Content
@endmacro

@macro level1
@level2
@endmacro

@level1"""
    out = perseus.render_source(text, cfg(), None)
    assert "@level1" not in out
    assert "@level2" not in out
    assert "Deep Content" in out

def test_recursive_macro_depth_exceeded(tmp_path):
    # The spec says depth 10.
    text = """@perseus
@macro infinite
@infinite
@endmacro

@infinite"""
    out = perseus.render_source(text, cfg(), None)
    assert "macro expansion depth exceeded" in out.lower()
    assert "max 10" in out.lower()

def test_shared_macros(tmp_path, monkeypatch):
    shared_macros_file = tmp_path / "macros.md"
    shared_macros_file.write_text("""@macro shared-macro
Shared Content
@endmacro
""", encoding="utf-8")
    
    # Configure perseus to use this shared macros file
    config = cfg()
    if "macros" not in config:
        config["macros"] = {}
    config["macros"]["file"] = str(shared_macros_file)
    
    text = """@perseus
@shared-macro"""
    out = perseus.render_source(text, config, None)
    assert "Shared Content" in out

def test_source_macro_overrides_shared(tmp_path):
    shared_macros_file = tmp_path / "macros.md"
    shared_macros_file.write_text("""@macro override-me
Shared Content
@endmacro
""", encoding="utf-8")
    
    config = cfg()
    if "macros" not in config:
        config["macros"] = {}
    config["macros"]["file"] = str(shared_macros_file)
    
    text = """@perseus
@macro override-me
Local Content
@endmacro

@override-me"""
    out = perseus.render_source(text, config, None)
    assert "Local Content" in out
    assert "Shared Content" not in out

def test_macro_with_if_directive():
    text = """@perseus
@macro conditional-block
@if env.set HOME
Inside If
@endif
@endmacro

@conditional-block"""
    out = perseus.render_source(text, cfg(), None)
    assert "@conditional-block" not in out
    # If HOME is set, it should show "Inside If"
    import os
    if os.environ.get("HOME"):
        assert "Inside If" in out

def test_undefined_macro_invocation():
    text = """@perseus
@undefined-macro"""
    out = perseus.render_source(text, cfg(), None)
    # Undefined macro should be preserved
    assert "@undefined-macro" in out


def test_macro_with_cache_modifier(tmp_path):
    local_cfg = cfg()
    local_cfg["render"]["cache_dir"] = str(tmp_path / "cache")
    
    text = """@perseus
@macro cached-macro
@query "echo cached-output" @cache ttl=60
@endmacro

@cached-macro"""
    out = perseus.render_source(text, local_cfg, None)
    assert "cached-output" in out
    
    # Check if it was actually cached. #612: @query now carries an env
    # fingerprint, so the entry lands under <base>.<fp>, not the bare base key.
    clean_args, _, _, _ = perseus._parse_cache_modifier('"echo cached-output" @cache ttl=60')
    _base = perseus._cache_key(f"@query {clean_args} :: ")  # workspace=None
    _fp = perseus._dependency_fingerprint("@query", clean_args, None, local_cfg)
    cache_key = f"{_base}.{_fp}" if _fp else _base
    cached = perseus.cache_get(cache_key, "ttl", 60, local_cfg)
    assert cached is not None
    assert "cached-output" in cached

def test_macro_graph_expansion(tmp_path):
    source = """@perseus
@macro my-macro
@read config.yaml
@endmacro

@my-macro
"""
    # Build graph
    graph = perseus.directive_dependency_graph(source, workspace=tmp_path, cfg=cfg())
    
    directives = [node["directive"] for node in graph["nodes"]]
    assert "@read" in directives
    assert "@my-macro" not in directives


def test_macro_quoted_multiword_args():
    # Quoted args may contain spaces; each maps to one positional param.
    text = """@perseus
@macro card
**%what%**
- Why: %why%
@endmacro

@card what="HOT-127068 Automation Rules" why="2 items past due\""""
    out = perseus.render_source(text, cfg(), None)
    assert "**HOT-127068 Automation Rules**" in out
    assert "- Why: 2 items past due" in out
    assert "@card" not in out


def test_macro_unquoted_args_backward_compatible():
    # No quotes -> plain whitespace split, exactly as before.
    text = """@perseus
@macro pair
%a%-%b%
@endmacro

@pair foo bar"""
    out = perseus.render_source(text, cfg(), None)
    assert "foo-bar" in out


def test_macro_malformed_quotes_fall_back():
    # Unbalanced quote must not raise; falls back to whitespace split.
    text = """@perseus
@macro one
[%x%]
@endmacro

@one "unbalanced"""
    out = perseus.render_source(text, cfg(), None)
    # Should render without error; first token used for %x%.
    assert "@one" not in out


def test_macro_positional_quoted_args():
    # Positional quoted args (no key=) map in order and may contain spaces.
    text = """@perseus
@macro card
**%what%**
- Why: %why%
@endmacro

@card "HOT-1 big summary" "very important\""""
    out = perseus.render_source(text, cfg(), None)
    assert "**HOT-1 big summary**" in out
    assert "- Why: very important" in out
