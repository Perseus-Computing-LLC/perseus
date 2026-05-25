import os
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


# ── Test: Shell hook fires with formatted payload ────────────────────────────

def test_shell_hook_fires(tmp_path):
    log_file = tmp_path / "hook.log"
    c = cfg()
    c["hooks"]["on_render_start"] = [
        {"cmd": ["sh", "-c", f"echo 'render started: {{source}}' >> {log_file}"]},
    ]
    source = """\
@perseus v0.5
Hello
"""
    perseus.render_source(source, c, tmp_path)
    assert log_file.exists()
    content = log_file.read_text()
    assert "render started" in content


# ── Test: Hook failure doesn't break render ──────────────────────────────────

def test_hook_failure_doesnt_break_render(tmp_path):
    c = cfg()
    c["hooks"]["on_render_start"] = [
        {"cmd": ["sh", "-c", "exit 1"]},  # this hook fails
    ]
    source = """\
@perseus v0.5
Hello
"""
    out = perseus.render_source(source, c, tmp_path)
    assert "Hello" in out


# ── Test: hooks.enabled: false → no hooks fire ──────────────────────────────

def test_hooks_disabled(tmp_path):
    log_file = tmp_path / "hook.log"
    c = cfg()
    c["hooks"]["enabled"] = False
    c["hooks"]["on_render_start"] = [
        {"cmd": f"echo 'should not run' >> {log_file}"},
    ]
    source = """\
@perseus v0.5
Hello
"""
    perseus.render_source(source, c, tmp_path)
    assert not log_file.exists()


# ── Test: Python plugin hook fires ──────────────────────────────────────────

def test_python_plugin_hook(tmp_path):
    plugins_dir = tmp_path / ".perseus" / "plugins"
    plugins_dir.mkdir(parents=True)
    hook_log = tmp_path / "python_hook.log"
    (plugins_dir / "my_hook.py").write_text(f"""\
def on_render_start(payload):
    with open("{hook_log}", "w") as f:
        f.write("plugin hook fired: " + payload.get("workspace", "none"))
""")

    c = cfg()
    c["plugins"]["dir"] = str(plugins_dir)
    c["hooks"]["on_render_start"] = [
        {"plugin": "my_hook"},
    ]
    source = """\
@perseus v0.5
Hello
"""
    perseus.render_source(source, c, tmp_path)
    assert hook_log.exists()
    assert "plugin hook fired" in hook_log.read_text()


# ── Test: on_render_complete fires ───────────────────────────────────────────

def test_on_render_complete_hook(tmp_path):
    log_file = tmp_path / "complete.log"
    c = cfg()
    c["hooks"]["on_render_complete"] = [
        {"cmd": ["sh", "-c", f"echo 'duration_ms={{duration_ms}}' >> {log_file}"]},
    ]
    source = """\
@perseus v0.5
Hello
"""
    perseus.render_source(source, c, tmp_path)
    assert log_file.exists()
    assert "duration_ms=" in log_file.read_text()


# ── Test: on_directive_error hook fires ─────────────────────────────────────

def test_on_directive_error_hook(tmp_path):
    # Create a plugin that throws
    plugins_dir = tmp_path / ".perseus" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "broken.py").write_text("""\
from perseus_module import DirectiveSpec

def _resolve_broken(args, cfg, workspace):
    raise RuntimeError("Boom!")

REGISTER = {
    "@broken": DirectiveSpec(
        name="@broken", resolver=_resolve_broken, args=[],
        kind="inline", call_sig="acw", summary="Broken",
    )
}
""")
    error_log = tmp_path / "error.log"
    c = cfg()
    c["plugins"]["dir"] = str(plugins_dir)
    c["hooks"]["on_directive_error"] = [
        {"cmd": ["sh", "-c", f"echo 'error: {{error}}' >> {error_log}"]},
    ]
    # Discover and register the broken plugin
    specs = perseus._discover_plugins(c)
    for spec in specs:
        if spec.name not in perseus.DIRECTIVE_REGISTRY:
            perseus.DIRECTIVE_REGISTRY[spec.name] = spec
    perseus.INLINE_DIRECTIVE_RE = perseus._build_inline_directive_re()

    source = """\
@perseus v0.5
@broken
"""
    perseus.render_source(source, c, tmp_path)
    assert error_log.exists()
    assert "Boom!" in error_log.read_text()
