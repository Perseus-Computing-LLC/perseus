
import pytest
import copy
import re
from pathlib import Path
from perseus import render_source, DEFAULT_CONFIG, _expand_aliases

def test_alias_simple():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@q"] = "@query"
    
    lines = ["@q echo 'hello'"]
    expanded = _expand_aliases(lines, cfg)
    assert expanded == ["@query echo 'hello'"]

def test_alias_case_sensitive():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@q"] = "@query"
    
    lines = ["@Q echo 'hello'"]
    expanded = _expand_aliases(lines, cfg)
    assert expanded == ["@Q echo 'hello'"]

def test_alias_exact_match():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@svc"] = "@services"
    
    lines = ["@svc2 args"]
    expanded = _expand_aliases(lines, cfg)
    assert expanded == ["@svc2 args"]

def test_alias_chaining():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@a"] = "@b"
    cfg["directives"]["aliases"]["@b"] = "@query"
    
    lines = ["@a args"]
    expanded = _expand_aliases(lines, cfg)
    assert expanded == ["@query args"]

def test_alias_circular():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@a"] = "@b"
    cfg["directives"]["aliases"]["@b"] = "@a"
    
    lines = ["@a args", "@b args"]
    expanded = _expand_aliases(lines, cfg)
    assert expanded == ["@a args", "@b args"]

def test_alias_in_pipe():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@q"] = "@query"
    cfg["directives"]["aliases"]["@h"] = "@head"
    
    lines = ["@q 'ls' | @h 5"]
    expanded = _expand_aliases(lines, cfg)
    assert expanded == ["@query 'ls' | @head 5"]

def test_alias_in_macro():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@d"] = "@date"
    source = """@perseus
@macro my-date
  @d
@endmacro
@my-date"""
    rendered = render_source(source, cfg)
    assert "@d" not in rendered
    assert re.search(r'\d', rendered)

def test_alias_not_found_directive():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@q"] = "@notfound"
    
    source = "@perseus\n@q args"
    rendered = render_source(source, cfg)
    assert "@notfound" in rendered

def test_alias_shadowing_builtin():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["directives"]["aliases"]["@query"] = "@read"
    
    lines = ["@query args"]
    expanded = _expand_aliases(lines, cfg)
    # Should ignore @query alias as it shadows a built-in
    assert expanded == ["@query args"]
