import argparse
import copy
import io
import json
import os
import select
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from conftest import PY_VER, cfg, perseus, _capture_json, _seed_oracle_log

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

def test_infer_workspace_for_non_dot_perseus_source(tmp_path):
    src = tmp_path / "docs" / "context.md"
    src.parent.mkdir(parents=True)
    src.write_text("@perseus\n")
    assert perseus._infer_workspace(src) == src.parent.resolve()


def test_render_accepts_bare_perseus_header():
    out = perseus.render_source("@perseus\nHello", cfg(), None)
    assert out == "Hello"


def test_render_preserves_directives_inside_fenced_code():
    text = '@perseus\n```markdown\n@date format="YYYY"\n@agora status=open\n```\n@date format="YYYY"'
    out = perseus.render_source(text, cfg(), None)
    assert '```markdown\n@date format="YYYY"\n@agora status=open\n```' in out
    assert out.rstrip().endswith(str(datetime.now().year))


def test_inline_date_preserves_code_span_examples():
    text = '@perseus\n| `@date format="YYYY"` | @date format="YYYY" |'
    out = perseus.render_source(text, cfg(), None)
    assert '`@date format="YYYY"`' in out
    assert f"| {datetime.now().year} |" in out


def test_read_parses_quoted_path_and_fallback_with_quotes(tmp_path):
    workspace = tmp_path
    target = workspace / "a'b.txt"
    target.write_text("content")
    out = perseus.resolve_read(f'"{target.name}" fallback="say \\\"hi\\\""', cfg(), workspace)
    assert "content" in out
    assert out.startswith("```text")


def test_read_blocks_workspace_escape_by_default(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("nope")
    out = perseus.resolve_read(f'"{outside}"', cfg(), tmp_path)
    assert "escapes workspace" in out


def test_include_blocks_workspace_escape_by_default(tmp_path):
    outside = tmp_path.parent / "secret.md"
    outside.write_text("# secret")
    out = perseus.resolve_include(f'"{outside}"', tmp_path, cfg())
    assert "escapes workspace" in out


def test_if_unknown_condition_emits_warning():
    text = "@perseus\n@if env.eql FOO \"bar\"\nA\n@endif"
    out = perseus.render_source(text, cfg(), None)
    assert "@if error" in out
    assert "unknown @if condition" in out


def test_if_missing_endif_emits_warning():
    text = "@perseus\n@if env.set HOME\nA"
    out = perseus.render_source(text, cfg(), None)
    assert "unmatched @if" in out


def test_services_invalid_entry_reports_warning_row():
    out = perseus.resolve_services("- just-a-string", cfg())
    assert "service entry must be a mapping" in out


def test_services_command_disabled_by_default():
    block = "- name: check\n  command: echo hello"
    out = perseus.resolve_services(block, cfg())
    assert "command checks disabled by config" in out


def test_services_block_allows_blank_lines_and_explicit_end():
    text = "@perseus\n@services\n- name: one\n  command: echo hi\n\n- name: two\n  command: echo hi\n@end"
    out = perseus.render_source(text, cfg(), None)
    assert "| one |" in out
    assert "| two |" in out


def test_services_empty_explicit_block_warns():
    text = "@perseus\n@services\n@end"
    out = perseus.render_source(text, cfg(), None)
    assert "@services: empty block" in out


def test_query_can_be_disabled_by_config():
    local_cfg = cfg()
    local_cfg["render"]["allow_query_shell"] = False
    out = perseus.resolve_query('"echo hi"', local_cfg)
    assert "@query is disabled by config" in out


def test_query_with_schema_validation(tmp_path):
    workspace = tmp_path
    schemas_dir = workspace / "schemas"
    schemas_dir.mkdir()
    schema_file = schemas_dir / "test_schema.yaml"
    schema_file.write_text("""
type: map
mapping:
  "name":
    type: str
    required: true
  "version":
    type: str
    required: true
""")

    # Test with valid data
    valid_yaml = "{name: my-package, version: 1.0.0}"
    out = perseus.resolve_query(f'"echo \'{valid_yaml}\'" schema="{schema_file}"', cfg(), workspace)
    assert "my-package" in out

    # Test with invalid data
    invalid_yaml = "{name: my-package}"
    out = perseus.resolve_query(f'"echo \'{invalid_yaml}\'" schema="{schema_file}"', cfg(), workspace)
    assert "Validation Error" in out



def test_skills_frontmatter_parses_structurally(tmp_path):
    skill_dir = tmp_path / "skills" / "cat" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo-name\ndescription: uses --- inside text ok\n---\nbody")
    local_cfg = cfg()
    local_cfg["oracle"]["skill_dir"] = str(tmp_path / "skills")
    out = perseus.resolve_skills("", local_cfg)
    assert "demo-name" in out
    assert "uses --- inside text ok" in out
# ── task-08: @list and @tree ─────────────────────────────────────────────────

def test_list_directory_simple(tmp_path):
    local = cfg()
    (tmp_path / "packages" / "api").mkdir(parents=True)
    (tmp_path / "packages" / "web").mkdir(parents=True)
    out = perseus.resolve_list('./packages/ type="dirs" depth=1 as="list"', local, tmp_path)
    assert "- api/" in out
    assert "- web/" in out


def test_list_structured_json_table(tmp_path):
    local = cfg()
    pkg = tmp_path / "package.json"
    pkg.write_text(json.dumps({"scripts": {"dev": "vite dev", "build": "vite build"}}))
    out = perseus.resolve_list('./package.json path="scripts" columns="key:Command,value:Runs" as="table"', local, tmp_path)
    assert "| Command | Runs |" in out
    assert "dev" in out
    assert "vite build" in out


def test_list_missing_path_warns(tmp_path):
    out = perseus.resolve_list('./nope', cfg(), tmp_path)
    assert "not found" in out


def test_list_outside_workspace_warns(tmp_path):
    local = cfg()
    local["render"]["allow_outside_workspace"] = False
    other = tmp_path.parent / "other-ws"
    other.mkdir(exist_ok=True)
    out = perseus.resolve_list(str(other), local, tmp_path)
    assert "escapes workspace" in out


def test_tree_basic(tmp_path):
    local = cfg()
    (tmp_path / "src" / "api").mkdir(parents=True)
    (tmp_path / "src" / "api" / "routes.py").write_text("")
    (tmp_path / "src" / "api" / "models.py").write_text("")
    (tmp_path / "src" / "utils").mkdir(parents=True)
    (tmp_path / "src" / "utils" / "parser.py").write_text("")
    out = perseus.resolve_tree('./src/ depth=3', local, tmp_path)
    assert "```" in out
    assert "src/" in out
    assert "routes.py" in out
    assert "parser.py" in out


def test_tree_match_and_exclude(tmp_path):
    local = cfg()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("")
    (tmp_path / "src" / "b.txt").write_text("")
    (tmp_path / "src" / "node_modules").mkdir()
    (tmp_path / "src" / "node_modules" / "x.py").write_text("")
    out = perseus.resolve_tree('./src/ depth=2 match="*.py" exclude="node_modules"', local, tmp_path)
    assert "a.py" in out
    assert "b.txt" not in out
    assert "node_modules" not in out


def test_list_and_tree_dispatch_through_render(tmp_path):
    local = cfg()
    (tmp_path / "pkgs").mkdir()
    (tmp_path / "pkgs" / "x").mkdir()
    src = ['@list ./pkgs type="dirs"']
    out = perseus._render_lines(src, local, workspace=tmp_path)
    assert "- x/" in out
# ─────────────────────────────────────────────────────────────────────────────
# task-14: @query fallback="text"
# ─────────────────────────────────────────────────────────────────────────────

def test_query_fallback_on_failed_command():
    out = perseus.resolve_query('"false" fallback="no git here"', cfg())
    assert out == "no git here"


def test_query_fallback_on_empty_stdout():
    out = perseus.resolve_query('"true" fallback="no output"', cfg())
    assert out == "no output"


def test_query_fallback_ignored_on_success():
    out = perseus.resolve_query('"echo hello" fallback="never seen"', cfg())
    assert "hello" in out
    assert "never seen" not in out


def test_query_no_fallback_still_shows_warning_on_failure():
    out = perseus.resolve_query('"false"', cfg())
    assert "⚠" in out or "exited" in out


def test_query_fallback_single_quoted():
    out = perseus.resolve_query("\"false\" fallback='single-q text'", cfg())
    assert out == "single-q text"


def test_query_fallback_with_cache_modifier_stripped_first(monkeypatch):
    # When @cache is stripped before fallback parsing, fallback should still work.
    raw = '"false" fallback="cached fallback" @cache ttl=10'
    # The renderer normally strips @cache; we strip manually here to simulate
    cleaned, _, _, _ = perseus._parse_cache_modifier(raw)
    out = perseus.resolve_query(cleaned, cfg())
    assert out == "cached fallback"


def test_query_fallback_unescapes_simple_escapes():
    out = perseus.resolve_query(r'"false" fallback="line one\nline two"', cfg())
    assert "line one\nline two" == out


# ─────────────────────────────────────────────────────────────────────────────
# task-13: @if query("...") matches /regex/
# ─────────────────────────────────────────────────────────────────────────────

def test_if_query_matches_true():
    assert perseus.evaluate_condition(
        'query("echo hello world") matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_matches_false():
    assert perseus.evaluate_condition(
        'query("echo goodbye") matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_not_matches_true():
    assert perseus.evaluate_condition(
        'query("echo goodbye") not matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_not_matches_false():
    assert perseus.evaluate_condition(
        'query("echo hello world") not matches /hello/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_respects_allow_query_shell_false(capsys):
    local = cfg()
    local["render"]["allow_query_shell"] = False
    result = perseus.evaluate_condition(
        'query("echo hello") matches /hello/',
        workspace=None,
        cfg=local,
    )
    assert result is False
    err = capsys.readouterr().err
    assert "allow_query_shell" in err


def test_if_query_case_insensitive_flag():
    assert perseus.evaluate_condition(
        'query("echo HELLO") matches /hello/i',
        workspace=None,
        cfg=cfg(),
    ) is True


def test_if_query_invalid_regex_raises():
    with pytest.raises(perseus.ConditionParseError):
        perseus.evaluate_condition(
            'query("echo x") matches /[unclosed/',
            workspace=None,
            cfg=cfg(),
        )


def test_if_query_failed_command_returns_false(capsys):
    # `false` always exits non-zero with empty stdout — the regex can't match empty
    assert perseus.evaluate_condition(
        'query("false") matches /anything/',
        workspace=None,
        cfg=cfg(),
    ) is False


def test_if_query_matches_inside_render_block():
    cfg_local = cfg()
    cfg_local["render"]["allow_query_shell"] = True
    src = """@perseus v0.6

@if query("echo present") matches /present/
SHOWN
@else
HIDDEN
@endif
"""
    rendered = perseus.render_source(src, cfg_local, workspace=None)
    assert "SHOWN" in rendered
    assert "HIDDEN" not in rendered
# ═══════════════════════════════════════════════════════════════════════════════
# Task-25: DIRECTIVE_REGISTRY invariant tests
# ═══════════════════════════════════════════════════════════════════════════════

def test_registry_every_directive_has_callable_resolver_or_is_control():
    """Every registered directive with kind='inline' must have a callable resolver."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            assert callable(spec.resolver), f"{name}: inline directive must have callable resolver"
        # Control/block directives may have None resolver
        if spec.kind == "control":
            assert spec.resolver is None, f"{name}: control directive should have no resolver"


def test_registry_unsafe_hover_invariant():
    """Directives that execute shell or mutate state must NOT be safe_for_hover."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.executes_shell or spec.mutates_state:
            assert not spec.safe_for_hover, (
                f"{name}: executes_shell={spec.executes_shell} mutates_state={spec.mutates_state} "
                f"but safe_for_hover=True — violates safety invariant"
            )


def test_registry_inline_re_matches_all_inline_directives():
    """INLINE_DIRECTIVE_RE must match every registered inline directive."""
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        if spec.kind == "inline":
            m = perseus.INLINE_DIRECTIVE_RE.match(name)
            assert m is not None, f"{name}: not matched by INLINE_DIRECTIVE_RE"
            m2 = perseus.INLINE_DIRECTIVE_RE.match(f"{name} some_arg=value")
            assert m2 is not None, f"{name} with args: not matched by INLINE_DIRECTIVE_RE"


def test_registry_no_unknown_call_sigs():
    """call_sig must be one of the known adapter patterns."""
    valid = {"acw", "ac", "a", "awc", "block"}
    for name, spec in perseus.DIRECTIVE_REGISTRY.items():
        assert spec.call_sig in valid, f"{name}: unknown call_sig={spec.call_sig!r}"


def test_registry_completeness_against_resolver_functions():
    """Every resolve_* function in perseus module should be in the registry."""
    import inspect
    resolver_funcs = {
        name for name, obj in inspect.getmembers(perseus, inspect.isfunction)
        if name.startswith("resolve_")
    }
    registered_resolvers = {
        spec.resolver.__name__ for spec in perseus.DIRECTIVE_REGISTRY.values()
        if spec.resolver is not None
    }
    missing = resolver_funcs - registered_resolvers
    assert not missing, f"resolve_* functions not in registry: {missing}"
