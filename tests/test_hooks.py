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
                {"command": "echo 'done' > " + str(log_file)}
            ]
        }
    }
    source = "@perseus\nHello world"
    perseus.render_source(source, cfg)
    assert log_file.exists()
    assert log_file.read_text().strip() == "done"

def test_python_hook_on_directive_resolved(temp_hooks_dir, tmp_path):
    log_file = tmp_path / "python_hook.log"
    hook_code = (
        'def on_directive_resolved(payload):\n'
        '    with open("' + str(log_file) + '", "w") as f:\n'
        '        f.write(payload["name"] + ":" + payload["args"])\n'
    )
    (temp_hooks_dir / "test_hook.py").write_text(hook_code)
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
    assert log_file.read_text().strip() == "@date:format=%Y"

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
    cfg = {
        "hooks": {
            "enabled": True,
            "on_render_start": [
                {"command": "sleep 10"}
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
                {"command": "echo '{{workspace}}' > " + str(log_file)}
            ]
        }
    }
    source = "@perseus\nHello"
    perseus.render_source(source, cfg, workspace=Path("/tmp/ws"))
    assert log_file.read_text().strip() == "/tmp/ws"

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
