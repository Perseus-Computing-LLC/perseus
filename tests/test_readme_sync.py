"""
README ↔ reality sync checks (#551).

The MCP tool table and prose count in README.md previously disagreed with
each other AND with the actual default toolset (27 vs 29 vs a different 29),
and the test-count comment was stale. These tests pin the README to ground
truth so the numbers cannot silently rot again.
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


def test_readme_prose_count_matches_table():
    section = _mcp_section()
    m = re.search(r"(\d+) MCP tools resolve live state", section)
    assert m, "README prose tool count sentence missing"
    optin_at = section.find("Opt-in only")
    default_rows = _table_tools(section[:optin_at])
    assert int(m.group(1)) == len(default_rows), (
        f"README prose says {m.group(1)} tools but the table has "
        f"{len(default_rows)} rows"
    )


def test_readme_test_count_comment_roughly_current():
    """The test-count comment may not drift more than 5% (or 40 tests) from
    the actual grep-based count. Recount with:
        grep -rE '^\\s*def test_' tests/ | wc -l
    and update the <!-- test-count: N --> comment in README.md."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- test-count: (\d+)", readme)
    assert m, "README test-count comment missing"
    documented = int(m.group(1))

    actual = 0
    for fp in (_ROOT / "tests").glob("*.py"):
        actual += len(re.findall(r"^\s*def test_", fp.read_text(encoding="utf-8"),
                                 flags=re.M))
    tolerance = max(40, int(actual * 0.05))
    assert abs(actual - documented) <= tolerance, (
        f"README test-count comment ({documented}) has drifted from the "
        f"actual count ({actual}) — update the comment"
    )
