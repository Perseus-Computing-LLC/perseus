import copy
import importlib.util
import json
import sys
from pathlib import Path

PY_VER = tuple(map(int, sys.version.split()[0].split('.')))

if PY_VER >= (3, 10):
    SPEC = importlib.util.spec_from_file_location("perseus_module", Path(__file__).resolve().parents[1] / "perseus.py")
    perseus = importlib.util.module_from_spec(SPEC)
    assert SPEC and SPEC.loader
    SPEC.loader.exec_module(perseus)
else:
    perseus = None


def cfg():
    assert perseus is not None
    return copy.deepcopy(perseus.DEFAULT_CONFIG)


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


def pytest_addoption(parser):
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate tests/golden/*/expected.md snapshots from current render output.",
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
