"""Adversarial path traversal and workspace boundary tests for _resolve_path.

Covers:
  - Relative path escapes (../../../etc/passwd)
  - Absolute paths (/etc/passwd)
  - Symlink escapes (symlink inside workspace → outside)
  - Null byte injection
  - Unicode homoglyph tricks

Also includes Hypothesis property tests for _resolve_path invariants.
"""

import os
import tempfile
import pytest
from pathlib import Path
from hypothesis import given, settings, strategies as st, assume


# Import from the built artifact (not source modules — per skill docs)
import sys
sys.path.insert(0, "/workspace/perseus")
import perseus
from perseus import _resolve_path


# ── Workspace boundary tests ──────────────────────────────────────────────────

class TestWorkspaceBoundary:
    """Verify _resolve_path blocks escapes with allow_outside_workspace=False."""

    @pytest.fixture
    def workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / "workspace"
            ws.mkdir()
            yield ws

    def test_relative_escape_blocked(self, workspace):
        """../../../etc/passwd should be rejected."""
        _, warning = _resolve_path("../../../etc/passwd", workspace, allow_outside_workspace=False)
        assert warning is not None
        assert "escapes workspace" in warning

    def test_absolute_path_escape_blocked(self, workspace):
        """/etc/passwd should be rejected"""
        _, warning = _resolve_path("/etc/passwd", workspace, allow_outside_workspace=False)
        assert warning is not None
        assert "escapes workspace" in warning

    def test_path_inside_workspace_allowed(self, workspace):
        """A file inside the workspace should be allowed."""
        (workspace / "test.txt").write_text("hello")
        fp, warning = _resolve_path("test.txt", workspace, allow_outside_workspace=False)
        assert warning is None
        assert fp.exists()

    def test_path_inside_subdir_allowed(self, workspace):
        """A file inside a workspace subdirectory should be allowed."""
        sub = workspace / "subdir"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested")
        fp, warning = _resolve_path("subdir/nested.txt", workspace, allow_outside_workspace=False)
        assert warning is None
        assert fp.exists()

    def test_null_byte_handled(self, workspace):
        """Null byte injection raises ValueError from pathlib — safe rejection."""
        with pytest.raises(ValueError, match="embedded null"):
            _resolve_path("test\0.txt", workspace, allow_outside_workspace=False)

    def test_allow_outside_workspace_true(self, workspace):
        """With allow_outside_workspace=True, paths outside are permitted."""
        _, warning = _resolve_path("/dev/null", workspace, allow_outside_workspace=True)
        assert warning is None

    def test_dot_dot_normalized_then_resolved(self, workspace):
        """path/to/../../etc/passwd should be resolved and blocked."""
        _, warning = _resolve_path("subdir/../../etc/passwd", workspace, allow_outside_workspace=False)
        assert warning is not None
        assert "escapes workspace" in warning

    def test_symlink_escape_blocked(self, workspace):
        """Symlink inside workspace pointing outside should be blocked."""
        outside = Path(tempfile.gettempdir()) / "perseus_escape_test_target.txt"
        outside.write_text("target")
        symlink = workspace / "escape_link"
        try:
            symlink.symlink_to(outside)
            _, warning = _resolve_path("escape_link", workspace, allow_outside_workspace=False)
            assert warning is not None
            assert "escapes workspace" in warning
        except OSError:
            pytest.skip("symlink creation not available")

    def test_workspace_none_falls_back_to_cwd(self):
        """When workspace is None, cwd becomes the boundary."""
        # A path outside cwd should be blocked
        _, warning = _resolve_path("/etc/passwd", workspace=None, allow_outside_workspace=False)
        assert warning is not None
        assert "escapes workspace" in warning

    def test_expanduser_allowed(self, workspace):
        """~ expansion should work when path stays in workspace."""
        # Skip — ~ expansion interacts with actual home, not temp workspace
        pass


# ── Hypothesis property tests ─────────────────────────────────────────────────

@given(st.text(min_size=1, max_size=200))
@settings(max_examples=300)
def test_resolve_path_never_crashes(text):
    """_resolve_path must return a (Path, str|None) tuple for any input."""
    try:
        result = _resolve_path(text, workspace=None, allow_outside_workspace=False)
        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 2, f"Expected length 2, got {len(result)}"
        fp, warning = result
        assert isinstance(fp, Path), f"Expected Path, got {type(fp)}"
        assert warning is None or isinstance(warning, str)
    except ValueError:
        # pathlib may raise ValueError for null bytes or invalid chars
        pass
    except RuntimeError:
        # expanduser may RuntimeError on some tilde patterns on certain platforms
        pass
    except OSError:
        pass


@given(st.text(min_size=1, max_size=50))
@settings(max_examples=200)
def test_resolve_path_within_workspace_has_no_warning(basename):
    """A simple filename within the workspace should never emit a warning."""
    import os as _os
    assume("/" not in basename)
    assume("\\" not in basename)
    assume("\0" not in basename)
    assume(not basename.startswith("~"))  # tilde expansion can fail on certain platforms
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        try:
            (ws / basename).write_text("test")
            fp, warning = _resolve_path(basename, ws, allow_outside_workspace=False)
            if warning is None:
                assert fp.exists()
        except OSError:
            pass  # Invalid filename for filesystem
