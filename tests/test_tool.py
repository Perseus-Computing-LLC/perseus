import pytest
from pathlib import Path
from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def test_tool_allowed_runs(tmp_path):
    """Allowed tool produces output."""
    script = tmp_path / "hello.sh"
    script.write_text("#!/bin/sh\necho hello from tool")
    script.chmod(0o755)
    c = cfg()
    c["tools"]["allowlist"] = [{"path": str(script), "timeout_s": 5}]
    source = """\
@perseus v0.5
@tool "%s"
""" % script
    out = perseus.render_source(source, c, tmp_path)
    assert "hello from tool" in out


def test_tool_not_allowlisted_errors(tmp_path):
    """Non-allowlisted tool returns error."""
    script = tmp_path / "private.sh"
    script.write_text("#!/bin/sh\necho secret")
    script.chmod(0o755)
    c = cfg()
    c["tools"]["allowlist"] = []
    source = """\
@perseus v0.5
@tool "%s"
""" % script
    out = perseus.render_source(source, c, tmp_path)
    assert "not in the tools allowlist" in out


def test_tool_disabled_warns(tmp_path):
    """tools.enabled=false returns warning."""
    script = tmp_path / "cmd.sh"
    script.write_text("#!/bin/sh\necho hi")
    script.chmod(0o755)
    c = cfg()
    c["tools"]["enabled"] = False
    source = """\
@perseus v0.5
@tool "%s"
""" % script
    out = perseus.render_source(source, c, tmp_path)
    assert "disabled" in out.lower()
