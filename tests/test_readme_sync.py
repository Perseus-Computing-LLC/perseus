"""
README ↔ reality sync checks (#551).

The MCP tool table in README.md must stay aligned with the actual default
toolset. These tests pin the README to ground truth so the surface cannot
silently rot again.
"""

import re
from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")

_ROOT = Path(__file__).resolve().parents[1]


def _mcp_section() -> str:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("### MCP Tools", 1)[1]
    return section.split("## The Problem", 1)[0]


def _table_tools(text: str) -> list[str]:
    return re.findall(r"^\| `(perseus_\w+)` \|", text, flags=re.M)


def test_readme_default_tool_table_matches_get_all_mcp_tools():
    """The main README table must be exactly _get_all_mcp_tools({})'s set."""
    section = _mcp_section()
    optin_at = section.find("Opt-in only")
    assert optin_at != -1, "README lost its opt-in tools table"
    default_rows = _table_tools(section[:optin_at])
    optin_rows = _table_tools(section[optin_at:])

    actual = {t["name"] for t in perseus._get_all_mcp_tools({})}

    assert len(default_rows) == len(set(default_rows)), "duplicate rows in README table"
    assert set(default_rows) == actual, (
        "README default-tool table is out of sync with _get_all_mcp_tools({}): "
        f"missing from table: {sorted(actual - set(default_rows))}; "
        f"stale rows in table: {sorted(set(default_rows) - actual)}"
    )
    # Opt-in tools are documented separately and are NOT in the default set.
    assert set(optin_rows) == {"perseus_query", "perseus_agent"}
    assert not (set(optin_rows) & actual), \
        "opt-in-only tools unexpectedly present in the default toolset"


def test_readme_prose_tool_surface_matches_table():
    section = _mcp_section()
    assert "MCP tools resolve live state" in section, "README prose MCP-surface sentence missing"
    optin_at = section.find("Opt-in only")
    default_rows = _table_tools(section[:optin_at])
    assert default_rows, "README MCP tool table is empty"


def test_readme_test_count_comment_matches_current():
    """The test-count comment must match the exact grep-based count.

    Recount with:
        grep -rE '^\\s*def test_' tests/ | wc -l
    and update the <!-- test-count: N --> comment in README.md.
    """
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- test-count: (\d+)", readme)
    assert m, "README test-count comment missing"
    documented = int(m.group(1))

    actual = 0
    for fp in (_ROOT / "tests").glob("*.py"):
        actual += len(re.findall(r"^\s*def test_", fp.read_text(encoding="utf-8"),
                                 flags=re.M))
    assert actual == documented, (
        f"README test-count comment ({documented}) does not match the "
        f"exact count ({actual}) — update the comment"
    )
