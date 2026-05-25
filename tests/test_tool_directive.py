import pytest
import os
import tempfile
from pathlib import Path
from conftest import cfg, perseus

def test_tool_by_name(tmp_path):
    # Create a dummy tool
    tool_script = tmp_path / "hello.sh"
    tool_script.write_text("#!/bin/bash\necho \"hello $1\"")
    tool_script.chmod(0o755)
    
    c = cfg()
    c["tools"] = {
        "enabled": True,
        "allowlist": [
            {
                "name": "greet",
                "path": str(tool_script),
                "allowed_args": ["world", "hermes"],
                "timeout_s": 5,
                "max_output_bytes": 1024
            }
        ]
    }
    
    # Test success with name
    source = '@perseus v0.5\n@tool "greet" world'
    out = perseus.render_source(source, c, tmp_path)
    assert "hello world" in out

def test_tool_disallowed_arg(tmp_path):
    tool_script = tmp_path / "hello.sh"
    tool_script.write_text("#!/bin/bash\necho \"hello $1\"")
    tool_script.chmod(0o755)
    
    c = cfg()
    c["tools"] = {
        "enabled": True,
        "allowlist": [
            {
                "name": "greet",
                "path": str(tool_script),
                "allowed_args": ["world"],
                "timeout_s": 5,
                "max_output_bytes": 1024
            }
        ]
    }
    
    source = '@perseus v0.5\n@tool "greet" evil'
    out = perseus.render_source(source, c, tmp_path)
    assert "not allowed" in out

def test_tool_unregistered(tmp_path):
    c = cfg()
    c["tools"] = {"enabled": True, "allowlist": []}
    source = '@perseus v0.5\n@tool "unknown"'
    out = perseus.render_source(source, c, tmp_path)
    assert "not in the tools allowlist" in out

def test_tool_disabled(tmp_path):
    c = cfg()
    c["tools"] = {"enabled": False, "allowlist": [{"name": "foo", "path": "/bin/true"}]}
    source = '@perseus v0.5\n@tool "foo"'
    out = perseus.render_source(source, c, tmp_path)
    assert "disabled" in out

def test_tool_exit_nonzero(tmp_path):
    tool_script = tmp_path / "fail.sh"
    tool_script.write_text("#!/bin/bash\necho 'stderr info' >&2\nexit 1")
    tool_script.chmod(0o755)
    
    c = cfg()
    c["tools"] = {
        "enabled": True,
        "allowlist": [{"name": "fail", "path": str(tool_script), "timeout_s": 5}]
    }
    
    source = '@perseus v0.5\n@tool "fail"'
    out = perseus.render_source(source, c, tmp_path)
    assert "failed with exit code 1" in out
    assert "stderr info" in out

def test_tool_timeout(tmp_path):
    tool_script = tmp_path / "sleep.sh"
    tool_script.write_text("#!/bin/bash\nsleep 10")
    tool_script.chmod(0o755)
    
    c = cfg()
    c["tools"] = {
        "enabled": True,
        "allowlist": [{"name": "sleep", "path": str(tool_script), "timeout_s": 1}]
    }
    
    source = '@perseus v0.5\n@tool "sleep"'
    out = perseus.render_source(source, c, tmp_path)
    assert "timed out after 1s" in out

def test_tool_truncation(tmp_path):
    tool_script = tmp_path / "big.sh"
    tool_script.write_text("#!/bin/bash\necho '1234567890'")
    tool_script.chmod(0o755)
    
    c = cfg()
    c["tools"] = {
        "enabled": True,
        "allowlist": [
            {
                "name": "big",
                "path": str(tool_script),
                "max_output_bytes": 5
            }
        ]
    }
    
    source = '@perseus v0.5\n@tool "big"'
    out = perseus.render_source(source, c, tmp_path)
    assert "12345" in out
    assert "[truncated to 5 bytes]" in out

def test_tool_with_cache(tmp_path):
    tool_script = tmp_path / "count.sh"
    # Create a file to count
    counter_file = tmp_path / "counter.txt"
    counter_file.write_text("0")
    tool_script.write_text(f"#!/bin/bash\nval=$(cat {counter_file}); echo $((val+1)) | tee {counter_file}")
    tool_script.chmod(0o755)
    
    c = cfg()
    c["tools"] = {
        "enabled": True,
        "allowlist": [{"name": "count", "path": str(tool_script)}]
    }
    
    source = '@perseus v0.5\n@tool "count" @cache ttl=3600'
    out1 = perseus.render_source(source, c, tmp_path)
    assert out1.strip() == "1"
    
    out2 = perseus.render_source(source, c, tmp_path)
    assert out2.strip() == "1" # Should be cached

def test_tool_strict_profile(tmp_path):
    # Test that 'strict' profile disables tools
    c = cfg()
    # In conftest.py, cfg() returns a deepcopy of DEFAULT_CONFIG
    # but doesn't apply profiles.
    # We can manually apply it or simulate it.
    
    # Applying strict profile
    perseus._apply_permission_profile(c, "strict")
    
    assert "tools" in str(c)  # tools config present
    
    tool_script = tmp_path / "hello.sh"
    tool_script.write_text("#!/bin/bash\necho hello")
    tool_script.chmod(0o755)
    
    c["tools"]["allowlist"] = [{"name": "hello", "path": str(tool_script)}]
    
    source = '@perseus v0.5\n@tool "hello"'
    out = perseus.render_source(source, c, tmp_path)
    assert "disabled" in out
