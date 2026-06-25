import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Also make src/perseus importable for build tests (test_build.py).
# Append (not insert at 0) to avoid shadowing the importlib-loaded perseus_module.
_SRC_PATH = str(Path(__file__).resolve().parents[1] / "src")
if _SRC_PATH not in sys.path:
    sys.path.append(_SRC_PATH)

PY_VER = tuple(map(int, sys.version.split()[0].split('.')))

if PY_VER >= (3, 10):
    SPEC = importlib.util.spec_from_file_location("perseus_module", Path(__file__).resolve().parents[1] / "perseus.py")
    perseus = importlib.util.module_from_spec(SPEC)
    assert SPEC and SPEC.loader
    # Register before exec_module so that init code can find us
    sys.modules["perseus_module"] = perseus
    SPEC.loader.exec_module(perseus)
else:
    perseus = None


def cfg():
    """Return a config with shell execution enabled (test default).

    Tests that need to verify the gated behavior (shell disabled) should
    explicitly set `c["render"]["allow_query_shell"] = False`."""
    assert perseus is not None
    c = copy.deepcopy(perseus.DEFAULT_CONFIG)
    c["render"]["allow_query_shell"] = True
    c["render"]["allow_agent_shell"] = True
    return c


def make_tool_script(dir_path, name, *, sh, bat):
    """Write a directly-executable @tool script appropriate to the platform.

    @tool execs the registered path with no shell (``[path] + args`` via
    Popen), so on Windows the script must be a ``.bat`` — a ``.sh`` with a
    shebang raises ``OSError [WinError 193] %1 is not a valid Win32
    application``. Tests pass the POSIX (``sh``) and Windows (``bat``) bodies;
    the matching one is written and its path returned, so the *behavior* under
    test (output, exit code, timeout, truncation, caching) is exercised on both
    platforms rather than skipped.
    """
    if os.name == "nt":
        p = Path(dir_path) / f"{name}.bat"
        p.write_text(bat, encoding="utf-8")
    else:
        p = Path(dir_path) / f"{name}.sh"
        p.write_text(sh, encoding="utf-8")
        p.chmod(0o755)
    return p


def marker_touch_command(path):
    """Return a shell command that creates an empty file at ``path`` on the
    current platform's default shell. Hook/query commands run through the
    platform shell (cmd.exe on Windows, /bin/sh on POSIX), and ``touch`` does
    not exist on cmd — using it would make "should not run" gate tests pass for
    the wrong reason (the command fails regardless of the gate)."""
    p = str(path)
    if os.name == "nt":
        return f'type nul > "{p}"'
    return f'touch "{p}"'


def _seed_oracle_log(monkeypatch, tmp_path, entries):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    log = tmp_path / "pythia_log.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _capture_json(monkeypatch, fn, *a, **kw):
    """Call fn, capture print output, parse as JSON."""
    captured = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    rc = fn(*a, **kw)
    text = "\n".join(captured)
    return json.loads(text), rc


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: advisory slow/performance checks")


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """Clear the @cache session store before each test to prevent
    cross-test cache pollution (flaky prefetch tests when ran > 0)."""
    if perseus is not None:
        perseus._SESSION_CACHE.clear()
        if hasattr(perseus, "_WARNED_CACHE_DIR_OVERRIDES"):
            perseus._WARNED_CACHE_DIR_OVERRIDES.clear()
        # #445: clear the memoized cache-dir resolution + "dir ensured" set so a
        # test that monkeypatches PERSEUS_HOME / cache_dir isn't served a value
        # resolved under a different test's home.
        if hasattr(perseus, "_SAFE_CACHE_DIR_CACHE"):
            perseus._SAFE_CACHE_DIR_CACHE.clear()
        if hasattr(perseus, "_CACHE_DIR_ENSURED"):
            perseus._CACHE_DIR_ENSURED.clear()


@pytest.fixture(autouse=True)
def _allow_dangerous_env(monkeypatch):
    """Set PERSEUS_ALLOW_DANGEROUS=1 for all tests.

    The defense-in-depth gate (issue #94/#95) requires this env var even
    when allow_query_shell=True.  Tests that verify the gated (denied)
    behaviour can override this with monkeypatch.delenv."""
    monkeypatch.setenv("PERSEUS_ALLOW_DANGEROUS", "1")


@pytest.fixture(autouse=True)
def _detach_subprocess_stdin(monkeypatch):
    """Default subprocess stdin to DEVNULL for any test that doesn't set it.

    Many tests shell out to the perseus CLI. On Windows, pytest replaces the
    process stdin with a captured stream whose handle is invalid, so a child
    process inheriting it raises OSError [WinError 6] "The handle is invalid"
    before the command even runs. These are non-interactive invocations, so
    detaching stdin is always safe; explicit stdin= (e.g. run(input=...)) is
    preserved via setdefault. POSIX is unaffected (DEVNULL is cross-platform).
    """
    real_init = subprocess.Popen.__init__

    def _init(self, *args, **kwargs):
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        return real_init(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "__init__", _init)


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate tests/golden/*/expected.md snapshots from current render output.",
    )
    parser.addoption(
        "--enforce-budgets",
        action="store_true",
        default=False,
        help="Turn advisory performance budget warnings into hard test failures.",
    )


def normalize_golden(text: str) -> str:
    """Normalize golden output before comparison."""
    lines = []
    for line in text.replace("\r\n", "\n").splitlines():
        if "# VOLATILE" in line:
            continue
        lines.append(line.rstrip())
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"
