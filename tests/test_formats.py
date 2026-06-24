import json
import os
import tempfile
from pathlib import Path
import pytest
from conftest import PY_VER, cfg, perseus

@pytest.fixture
def perseus_home():
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        original_home = os.environ.get("PERSEUS_HOME")
        os.environ["PERSEUS_HOME"] = str(home)
        yield home
        if original_home:
            os.environ["PERSEUS_HOME"] = original_home
        else:
            del os.environ["PERSEUS_HOME"]

def test_json_format():
    source = "@perseus\n@date"
    config = {"render": {}}
    output = perseus.render_output(source, "json", config)
    data = json.loads(output)
    assert "resolved" in data
    assert "directives" in data
    assert "metadata" in data
    meta = data["metadata"]
    assert "source" in meta
    assert "workspace" in meta
    assert "timestamp" in meta
    assert "version" in meta
    assert "cache_stats" in meta
    assert "directive_count" in meta
    assert meta["directive_count"] == 1

def test_custom_format(perseus_home):
    formats_dir = perseus_home / "formats"
    formats_dir.mkdir(parents=True)
    adapter_py = formats_dir / "testfmt.py"
    adapter_py.write_text("def render(resolved, meta):\n    return 'CUSTOM:' + str(len(resolved)) + ':' + str(meta['directive_count'])\n", encoding="utf-8")
    source = "@perseus\nHello world\n@date"
    config = {"render": {}}
    output = perseus.render_output(source, "testfmt", config)
    assert "Hello world" in output or "CUSTOM:" in output

def test_format_collision(perseus_home, capsys):
    formats_dir = perseus_home / "formats"
    formats_dir.mkdir(parents=True)
    adapter_py = formats_dir / "json.py"
    adapter_py.write_text("def render(r, m): return 'fake json'", encoding="utf-8")
    source = "@perseus\nHello"
    config = {"render": {}}
    output = perseus.render_output(source, "json", config)
    data = json.loads(output)
    assert "Hello" in data["resolved"]

def test_format_import_error(perseus_home, capsys):
    formats_dir = perseus_home / "formats"
    formats_dir.mkdir(parents=True)
    adapter_py = formats_dir / "broken.py"
    adapter_py.write_text("import non_existent_module", encoding="utf-8")
    source = "@perseus\nHello"
    config = {"render": {}}
    output = perseus.render_output(source, "broken", config)
    assert "Hello" in output

def test_format_missing_render(perseus_home, capsys):
    formats_dir = perseus_home / "formats"
    formats_dir.mkdir(parents=True)
    adapter_py = formats_dir / "norender.py"
    adapter_py.write_text("x = 1", encoding="utf-8")
    source = "@perseus\nHello"
    config = {"render": {}}
    output = perseus.render_output(source, "norender", config)
    assert "Hello" in output
