import os
import json
import time
import subprocess
from pathlib import Path
import pytest
from conftest import PY_VER, cfg, perseus

@pytest.fixture
def temp_hooks_dir(tmp_path):
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    return hooks_dir

def test_shell_hook_on_render_complete(tmp_path):
    log_file = tmp_path / "hook.log"
    cfg = {
        "hooks": {
            "enabled": True,
            "on_render_complete": [
                # No quotes: cmd.exe echoes single quotes literally, so
                # `echo 'done'` would write "'done'". `echo done` round-trips
                # on both bash and cmd (trailing space/newline is stripped).
                {"command": "echo done > " + str(log_file)}
            ]
        }
    }
    source = "@perseus\nHello world"
    perseus.render_source(source, cfg)
    assert log_file.exists()
    assert log_file.read_text(encoding="utf-8").strip() == "done"

def test_python_hook_on_directive_resolved(temp_hooks_dir, tmp_path):
    log_file = tmp_path / "python_hook.log"
    # repr() the path so a Windows path (C:\Users\...) embeds as a valid string
    # literal — a bare str would turn \U, \t, etc. into escape sequences.
    hook_code = (
        'def on_directive_resolved(payload):\n'
        '    with open(' + repr(str(log_file)) + ', "w", encoding="utf-8") as f:\n'
        '        f.write(payload["name"] + ":" + payload["args"])\n'
    )
    (temp_hooks_dir / "test_hook.py").write_text(hook_code, encoding="utf-8")
    cfg = {
        "hooks": {
            "enabled": True,
            "dir": str(temp_hooks_dir)
        }
    }
    perseus._reset_hooks_cache()
    source = "@perseus\n@date format=%Y"
    perseus.render_source(source, cfg)
    assert log_file.exists()
    assert log_file.read_text(encoding="utf-8").strip() == "@date:format=%Y"

def test_hook_failure_does_not_break_render():
    cfg = {
        "hooks": {
            "enabled": True,
            "on_render_start": [
                {"command": "exit 1"}
            ]
        }
    }
    source = "@perseus\nHello"
    result = perseus.render_source(source, cfg)
    assert "Hello" in result

def test_hook_timeout_kills_runaway_hook(tmp_path):
    start = time.time()
    # ~10s runaway command per platform (`sleep` isn't a cmd.exe builtin;
    # `ping -n 11` waits ~10s). Verifies the 5s hook timeout tree-kills it.
    runaway = "ping -n 11 127.0.0.1 >nul" if os.name == "nt" else "sleep 10"
    cfg = {
        "hooks": {
            "enabled": True,
            "on_render_start": [
                {"command": runaway}
            ]
        }
    }
    source = "@perseus\nHello"
    perseus.render_source(source, cfg)
    duration = time.time() - start
    assert duration < 7

def test_template_variable_substitution(tmp_path):
    log_file = tmp_path / "vars.log"
    cfg = {
        "hooks": {
            "enabled": True,
            "on_render_start": [
                # No quotes (cmd echoes them literally). Compare against the
                # platform-native rendering of the workspace path.
                {"command": "echo {{workspace}}> " + str(log_file)}
            ]
        }
    }
    source = "@perseus\nHello"
    ws = tmp_path / "ws"
    perseus.render_source(source, cfg, workspace=ws)
    assert log_file.read_text(encoding="utf-8").strip() == str(ws)

def test_hooks_enabled_gate(tmp_path):
    log_file = tmp_path / "gate.log"
    cfg = {
        "hooks": {
            "enabled": False,
            "on_render_start": [
                {"command": "echo 'fired' > " + str(log_file)}
            ]
        }
    }
    source = "@perseus\nHello"
    perseus.render_source(source, cfg)
    assert not log_file.exists()

def test_per_hook_disable(tmp_path):
    log_file = tmp_path / "per_hook.log"
    cfg = {
        "hooks": {
            "enabled": True,
            "on_render_start": {
                "enabled": False,
                "commands": ["echo 'fired' > " + str(log_file)]
            }
        }
    }
    source = "@perseus\nHello"
    perseus.render_source(source, cfg)
    assert not log_file.exists()
