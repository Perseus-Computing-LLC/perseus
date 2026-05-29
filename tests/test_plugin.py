import sys
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── Fixture: preserve built-in state across plugin tests ────────────────────

@pytest.fixture(autouse=True)
def _reset_registry():
    """Remove any plugin-added entries after each test so they don't leak."""
    builtins = set(perseus.DIRECTIVE_REGISTRY.keys())
    yield
    to_remove = [k for k in perseus.DIRECTIVE_REGISTRY if k not in builtins]
    for k in to_remove:
        del perseus.DIRECTIVE_REGISTRY[k]
    # Rebuild the regex to match
    perseus.INLINE_DIRECTIVE_RE = perseus._build_inline_directive_re()
    # task-65: reset per-process plugin-dir cache so the next test re-scans
    perseus._reset_plugin_cache()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _setup_plugin_dir(monkeypatch, tmp_path, plugin_files=None):
    """Create a plugins dir at tmp_path/.perseus/plugins with filename→content map.
    Also creates a MANIFEST.toml with SHA-256 hashes for each plugin file."""
    import hashlib
    home = tmp_path / ".perseus"
    home.mkdir(parents=True, exist_ok=True)
    plugins_dir = home / "plugins"
    plugins_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    if plugin_files:
        for name, content in plugin_files.items():
            (plugins_dir / name).write_text(content, encoding="utf-8")
    # Build MANIFEST.toml with hashes for every .py file (v1.0.5 security: non-empty required)
    manifest_lines = ["# Auto-generated for tests — hashes verified\n"]
    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        h = hashlib.sha256(py_file.read_bytes()).hexdigest()
        manifest_lines.append(f"\n[plugins.{py_file.stem}]\n")
        manifest_lines.append(f'hash = "{h}"\n')
    (plugins_dir / "MANIFEST.toml").write_text("".join(manifest_lines), encoding="utf-8")
    return plugins_dir


def _discover_and_register(cfg_dict):
    """Discover plugins from cfg and register them in DIRECTIVE_REGISTRY."""
    # task-65: exercise the production register_plugins path
    perseus.register_plugins(cfg_dict, force=True)
    # Return the discovered specs for tests that inspect them
    return perseus._discover_plugins(cfg_dict)


# ── Test: Plugin with valid REGISTER → directive resolves correctly ─────────

def test_plugin_valid_register_resolves(monkeypatch, tmp_path):
    plugin_py = """\
from perseus_module import DirectiveSpec

def _resolve_hello(args, cfg, workspace):
    return "Hello from plugin!"

REGISTER = {
    "@hello": DirectiveSpec(
        name="@hello",
        resolver=_resolve_hello,
        args=[],
        kind="inline",
        call_sig="acw",
        summary="Say hello",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"hello_plugin.py": plugin_py})
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    _discover_and_register(c)

    out = perseus.render_source("@perseus v0.5\n@hello", c, None)
    assert "Hello from plugin!" in out


# ── Test: Plugin with invalid REGISTER → warning, render continues ───────────

def test_plugin_invalid_register_continues(monkeypatch, tmp_path):
    plugin_py = """\
# This plugin has a REGISTER that is not a dict — it should be skipped
REGISTER = "not a dict"
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"bad_plugin.py": plugin_py})
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    specs = perseus._discover_plugins(c)
    # No valid DirectiveSpec entries should be found
    assert len(specs) == 0


# ── Test: Plugin dir doesn't exist → no error ───────────────────────────────

def test_plugin_dir_missing_no_error(monkeypatch, tmp_path):
    home = tmp_path / ".perseus"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(perseus, "PERSEUS_HOME", home)
    c = cfg()
    c["plugins"] = {"enabled": True, "dir": str(home / "plugins")}
    # plugins dir does NOT exist
    specs = perseus._discover_plugins(c)
    assert specs == []


# ── Test: plugins.enabled: false → no plugins loaded ────────────────────────

def test_plugin_disabled_returns_empty(monkeypatch, tmp_path):
    plugin_py = """\
from perseus_module import DirectiveSpec

def _resolve_hello(args, cfg, workspace):
    return "Hello from plugin!"

REGISTER = {
    "@hello": DirectiveSpec(
        name="@hello", resolver=_resolve_hello, args=[],
        kind="inline", call_sig="acw", summary="Say hello",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"hello_plugin.py": plugin_py})
    c = cfg()
    c["plugins"] = {"enabled": False, "dir": str(pdir)}
    specs = perseus._discover_plugins(c)
    assert specs == []


# ── Test: Plugin name collision with built-in → built-in wins ───────────────

def test_plugin_collision_with_builtin(monkeypatch, tmp_path):
    """A plugin registering @query should be ignored — built-in wins."""
    plugin_py = """\
from perseus_module import DirectiveSpec

def _resolve_fake_query(args, cfg, workspace):
    return "FAKE QUERY OUTPUT"

REGISTER = {
    "@query": DirectiveSpec(
        name="@query",
        resolver=_resolve_fake_query,
        args=[],
        kind="inline",
        call_sig="acw",
        executes_shell=False,
        summary="Fake query",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"fake_query.py": plugin_py})
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    specs = perseus._discover_plugins(c)

    # Plugin discovered the spec, but we should NOT register it over built-in
    assert len(specs) >= 1
    # Simulate what cli.py does: skip if name already in DIRECTIVE_REGISTRY
    for spec in specs:
        if spec.name not in perseus.DIRECTIVE_REGISTRY:
            perseus.DIRECTIVE_REGISTRY[spec.name] = spec

    # @query should still be the built-in, not the plugin
    original = perseus.DIRECTIVE_REGISTRY["@query"]
    # Verify the built-in wasn't replaced (plugin resolver is different)
    assert "Fake query" not in original.summary


# ── Test: Plugin with executes_shell=True and shell disabled → gated ────────

def test_plugin_shell_execution_gated_by_config(monkeypatch, tmp_path):
    """Plugin with executes_shell=True should be gated when allow_query_shell is False."""
    plugin_py = """\
from perseus_module import DirectiveSpec
import subprocess

def _resolve_mycmd(args, cfg, workspace):
    result = subprocess.run(args.strip(), shell=True, capture_output=True, text=True, timeout=10)
    return result.stdout if result.returncode == 0 else result.stderr

REGISTER = {
    "@mycmd": DirectiveSpec(
        name="@mycmd",
        resolver=_resolve_mycmd,
        args=[],
        kind="inline",
        call_sig="acw",
        executes_shell=True,
        safe_for_hover=False,
        summary="Run a custom command",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"mycmd_plugin.py": plugin_py})
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    _discover_and_register(c)

    # With shell disabled, the directive should be gated
    c["render"]["allow_query_shell"] = False
    out = perseus.render_source("@perseus v0.5\n@mycmd echo hello", c, None)
    assert "denied" in out.lower() or "disabled" in out.lower()


# ── Test: Two plugins with same name → first wins ───────────────────────────

def test_plugin_duplicate_name_first_wins(monkeypatch, tmp_path):
    plugin_a = """\
from perseus_module import DirectiveSpec

def _resolve_a(args, cfg, workspace):
    return "Plugin A"

REGISTER = {
    "@dup": DirectiveSpec(
        name="@dup", resolver=_resolve_a, args=[],
        kind="inline", call_sig="acw", summary="Duplicate A",
    )
}
"""
    plugin_b = """\
from perseus_module import DirectiveSpec

def _resolve_b(args, cfg, workspace):
    return "Plugin B"

REGISTER = {
    "@dup": DirectiveSpec(
        name="@dup", resolver=_resolve_b, args=[],
        kind="inline", call_sig="acw", summary="Duplicate B",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {
        "a_plugin.py": plugin_a,
        "b_plugin.py": plugin_b,
    })
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    specs = perseus._discover_plugins(c)

    # Both plugins return @dup — first wins
    registered = {}
    for spec in specs:
        if spec.name not in registered:
            registered[spec.name] = spec
    assert len(registered) == 1
    assert registered["@dup"].summary == "Duplicate A"


# ── Test: Plugin with import error → warning on stderr, render continues ────

def test_plugin_import_error_continues_render(monkeypatch, tmp_path, capsys):
    """A plugin file that fails to import (missing module) must not break
    Perseus startup or rendering. The error is logged to stderr; other plugins
    and built-in directives continue to work."""
    broken_plugin = """\
import this_module_does_not_exist_anywhere  # raises ImportError at import time

from perseus_module import DirectiveSpec

REGISTER = {}
"""
    good_plugin = """\
from perseus_module import DirectiveSpec

def _resolve_ok(args, cfg, workspace):
    return "good plugin"

REGISTER = {
    "@goodplugin": DirectiveSpec(
        name="@goodplugin", resolver=_resolve_ok, args=[],
        kind="inline", call_sig="acw", summary="Good plugin",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {
        "a_broken.py": broken_plugin,
        "b_good.py": good_plugin,
    })
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    _discover_and_register(c)

    captured = capsys.readouterr()
    assert "Perseus plugin error" in captured.err
    assert "a_broken.py" in captured.err

    # Render still works; the good plugin still registered
    out = perseus.render_source("@perseus v0.5\n@goodplugin", c, None)
    assert "good plugin" in out


# ── Test: Plugin directive carries source=plugin into the graph ─────────────

def test_plugin_directive_has_source_metadata_in_graph(monkeypatch, tmp_path):
    """`perseus graph` output must distinguish plugin-sourced directives from
    built-ins so downstream tools can tell where a directive came from."""
    plugin_py = """\
from perseus_module import DirectiveSpec

def _resolve_mine(args, cfg, workspace):
    return "from plugin"

REGISTER = {
    "@mineonly": DirectiveSpec(
        name="@mineonly", resolver=_resolve_mine, args=[],
        kind="inline", call_sig="acw", summary="Plugin-sourced directive",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"mine.py": plugin_py})
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    _discover_and_register(c)

    source = "@perseus v0.5\n@date\n@mineonly\n"
    graph = perseus.directive_dependency_graph(source, source_name="<test>", workspace=tmp_path)

    by_directive = {n["directive"]: n for n in graph["nodes"]}
    assert by_directive["@date"]["source"] == "builtin"
    assert by_directive["@mineonly"]["source"] == "plugin"


# ── Test: Plugin resolver that throws → error output, render continues ──────

def test_plugin_resolver_throws_continues_render(monkeypatch, tmp_path):
    plugin_py = """\
from perseus_module import DirectiveSpec

def _resolve_broken(args, cfg, workspace):
    raise RuntimeError("Plugin resolver exploded!")

REGISTER = {
    "@broken": DirectiveSpec(
        name="@broken",
        resolver=_resolve_broken,
        args=[],
        kind="inline",
        call_sig="acw",
        summary="This resolver always throws",
    )
}
"""
    pdir = _setup_plugin_dir(monkeypatch, tmp_path, {"broken_plugin.py": plugin_py})
    c = cfg()
    c["plugins"]["dir"] = str(pdir)
    _discover_and_register(c)

    # Should not crash — render continues with an error in output
    out = perseus.render_source("@perseus v0.5\n@broken", c, None)
    assert "error" in out.lower() or "exploded" in out
