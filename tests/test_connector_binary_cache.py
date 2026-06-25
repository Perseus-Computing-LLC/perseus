"""#448: satellite-connector binary-path probes are memoized per process.

The probes run a `--version` subprocess (vaultmem's npx probe can hit the npm
registry with a 10s timeout) and were re-run on every query / per project. These
tests confirm the resolved path — including a not-installed result — is cached
so the probe runs at most once.
"""
import pytest

from conftest import PY_VER, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _count_runs(monkeypatch, returncode):
    """Patch subprocess.run to count calls and return the given returncode."""
    calls = {"n": 0}

    class _Result:
        def __init__(self):
            self.returncode = returncode
            self.stdout = "1.0.0"
            self.stderr = ""

    def _fake_run(cmd, **kwargs):
        calls["n"] += 1
        return _Result()

    monkeypatch.setattr(perseus.subprocess, "run", _fake_run)
    return calls


def test_memtrace_binary_path_memoizes_positive(monkeypatch):
    perseus._MEMTRACE_BIN_CACHE.clear()
    calls = _count_runs(monkeypatch, returncode=0)
    first = perseus._memtrace_binary_path()
    second = perseus._memtrace_binary_path()
    assert first is not None and first == second
    assert calls["n"] == 1, "binary probe must run only once, then be cached"


def test_memtrace_binary_path_caches_not_installed(monkeypatch):
    perseus._MEMTRACE_BIN_CACHE.clear()
    calls = {"n": 0}

    def _fail(cmd, **kwargs):
        calls["n"] += 1
        raise FileNotFoundError()

    monkeypatch.setattr(perseus.subprocess, "run", _fail)
    assert perseus._memtrace_binary_path() is None
    probes_after_first = calls["n"]
    assert probes_after_first > 0
    # Second call must not re-probe the (absent) binary.
    assert perseus._memtrace_binary_path() is None
    assert calls["n"] == probes_after_first


def test_memorymesh_and_vaultmem_binary_paths_memoize(monkeypatch):
    perseus._MEMORYMESH_BIN_CACHE.clear()
    perseus._VAULTMEM_BIN_CACHE.clear()
    # No binary present anywhere → both resolve to None and cache it.
    monkeypatch.setattr(perseus.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(perseus.os.path, "exists", lambda p: False)

    assert perseus._memorymesh_binary_path() is None
    assert perseus._memorymesh_binary_path() is None  # cached, no raise
    assert perseus._vaultmem_binary() is None
    assert perseus._vaultmem_binary() is None  # cached, no raise
