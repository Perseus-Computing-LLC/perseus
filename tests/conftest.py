import copy
import importlib.util
import json
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


def _seed_oracle_log(monkeypatch, tmp_path, entries):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    log = tmp_path / "pythia_log.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


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
