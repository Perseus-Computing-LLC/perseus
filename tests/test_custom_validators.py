import os
from pathlib import Path
import pytest
import sys
import json
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

def test_plugin_validator_pass(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    vcode = 'def validate(value, schema):\n    if isinstance(value, list) and len(value) == 3:\n        return True, ""\n    return False, "Expected list of length 3"\n'
    (schemas_dir / "len3.py").write_text(vcode, encoding="utf-8")
    src = '@perseus v1.0\n@query "echo \'[1, 2, 3]\'" schema="plugin:len3"'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "[1, 2, 3]" in out

def test_plugin_validator_fail(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    vcode = 'def validate(value, schema):\n    if isinstance(value, list) and len(value) == 3:\n        return True, ""\n    return False, "Expected list of length 3"\n'
    (schemas_dir / "len3.py").write_text(vcode, encoding="utf-8")
    src = '@perseus v1.0\n@query "echo \'[1, 2]\'" schema="plugin:len3"'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "\u26a0" in out

def test_plugin_validator_import_error(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    (schemas_dir / "bad_syntax.py").write_text("this is not valid python {{{", encoding="utf-8")
    src = '@perseus v1.0\n@query "echo hello" schema="plugin:bad_syntax"'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "hello" in out

def test_plugin_validator_exception(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    vcode = 'def validate(value, schema):\n    raise RuntimeError("boom")\n'
    (schemas_dir / "boom.py").write_text(vcode, encoding="utf-8")
    src = '@perseus v1.0\n@query "echo hello" schema="plugin:boom"'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "hello" in out

def test_plugin_validator_not_found(tmp_path):
    src = '@perseus v1.0\n@query "echo hello" schema="plugin:missing"'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "plugin validator" in out.lower() or "hello" in out

def test_plugin_validator_validate_directive(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    vcode = 'def validate(value, schema):\n    if isinstance(value, dict) and value.get("ok") is True:\n        return True, ""\n    return False, "not ok"\n'
    (schemas_dir / "checker.py").write_text(vcode, encoding="utf-8")
    src = '@perseus v1.0\n@validate schema="plugin:checker"\nok: true\n@end'
    out = perseus.render_source(src, cfg(), tmp_path)
    assert "ok: true" in out

def test_plugin_validator_cli(tmp_path):
    schemas_dir = tmp_path / ".perseus" / "schemas"
    schemas_dir.mkdir(parents=True)
    vcode = 'def validate(value, schema):\n    return True, ""\n'
    (schemas_dir / "always_ok.py").write_text(vcode, encoding="utf-8")
    import subprocess, os as _os
    perseus_py = _os.path.join(_os.path.dirname(__file__), "..", "perseus.py")
    result = subprocess.run(
        [sys.executable, perseus_py, "validate", "--schema", "plugin:always_ok"],
        cwd=str(tmp_path),
        input='{"key": "value"}',
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
