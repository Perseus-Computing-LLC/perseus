"""
Tests for mneme_narrative._deterministic_narrative — operator-added
section preservation (#549).

Regression guard: standard headings from the existing body must NOT leak
into the "Operator-Added Sections" block as bare duplicates on every
compact/update rebuild.
"""

from pathlib import Path

import pytest

from conftest import PY_VER, cfg, perseus

pytestmark = pytest.mark.skipif(PY_VER < (3, 10), reason="Perseus requires Python 3.10+")


def _rebuild(existing_body: str, tmp_path: Path) -> str:
    return perseus._deterministic_narrative([], [], existing_body, tmp_path, cfg())


def test_standard_headings_do_not_leak_into_operator_block(tmp_path):
    """#549 repro: standard sections around a custom one leaked bare headings."""
    existing = "\n".join([
        "## Task History",
        "| task | outcome |",
        "",
        "## My Custom Notes",
        "custom content line 1",
        "custom content line 2",
        "",
        "## Recent Activity",
        "recent activity content",
    ])
    result = _rebuild(existing, tmp_path)

    # Custom section preserved, with its content.
    assert "## My Custom Notes" in result
    assert "custom content line 1" in result
    assert "custom content line 2" in result
    assert "## Operator-Added Sections" in result

    # Standard headings appear exactly once (from the deterministic rebuild),
    # not duplicated as bare headings inside the operator block.
    assert result.count("## Task History") == 1
    assert result.count("## Recent Activity") == 1
    assert result.count("## Project Arc") == 1

    # And the operator block itself contains no standard headings.
    operator_block = result.split("## Operator-Added Sections", 1)[1]
    assert "## Task History" not in operator_block
    assert "## Recent Activity" not in operator_block


def test_no_custom_sections_no_operator_block(tmp_path):
    """A body with only standard sections must not grow an operator block."""
    existing = "\n".join([
        "## Project Arc",
        "arc content",
        "",
        "## Key Decisions",
        "- a decision",
        "",
        "## Recent Activity",
        "recent content",
    ])
    result = _rebuild(existing, tmp_path)
    assert "## Operator-Added Sections" not in result


def test_standard_heading_with_trailing_colon_excluded(tmp_path):
    existing = "\n".join([
        "## Key Decisions:",
        "- a decision",
        "",
        "## Runbook",
        "step 1",
    ])
    result = _rebuild(existing, tmp_path)
    operator_block = result.split("## Operator-Added Sections", 1)[1]
    assert "## Runbook" in operator_block
    assert "step 1" in operator_block
    assert "## Key Decisions" not in operator_block


def test_multiple_custom_sections_all_preserved(tmp_path):
    existing = "\n".join([
        "## Custom One",
        "one body",
        "",
        "## Task History",
        "| t | o |",
        "",
        "## Custom Two",
        "two body",
    ])
    result = _rebuild(existing, tmp_path)
    operator_block = result.split("## Operator-Added Sections", 1)[1]
    assert "## Custom One" in operator_block
    assert "one body" in operator_block
    assert "## Custom Two" in operator_block
    assert "two body" in operator_block
    assert "## Task History" not in operator_block
    assert "| t | o |" not in operator_block

    # Rebuild output is idempotent w.r.t. duplicate standard headings.
    assert result.count("## Task History") == 1
