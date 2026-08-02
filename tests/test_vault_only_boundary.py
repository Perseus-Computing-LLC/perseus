"""Fail-closed current-facing naming boundary for Perseus Vault."""

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).parents[1]
HISTORICAL = {"CHANGELOG.md", "ROADMAP.md"}
FORBIDDEN = tuple(
    part for part in ("mi" + "mir", "mne" + "me", "mnē" + "mē", "mnemo" + "syne")
)
TOKEN = r"(?:" + "|".join(map(re.escape, FORBIDDEN)) + r")"
PATTERN = re.compile(
    r"(?i)\b" + TOKEN + r"\b|" + TOKEN + r"[_-]|[_-]" + TOKEN
)


def _tracked_paths():
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [Path(item) for item in raw.decode().split("\x00") if item]


def test_current_facing_tree_is_vault_only():
    violations = []
    for rel in _tracked_paths():
        if rel.name in HISTORICAL:
            continue
        if PATTERN.search(str(rel)):
            violations.append(f"path:{rel}")
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if PATTERN.search(text):
            violations.append(str(rel))
    assert not violations, "legacy memory terminology remains: " + ", ".join(violations)
