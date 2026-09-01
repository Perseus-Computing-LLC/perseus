"""The documented plain ``uv run pytest`` gate must be self-provisioning."""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_plain_uv_run_provisions_pytest_from_the_default_dev_group():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    group = re.search(
        r"(?ms)^\[dependency-groups\]\s+dev\s*=\s*\[(.*?)\]",
        text,
    )
    assert group, "pyproject.toml must declare a default uv development group"
    assert re.search(r"(?i)pytest(?:[<>=!~]|\s|\")", group.group(1))
