"""Enforce claims.json's perseus_tool_count against the actual MCP registry.

claims.json marks perseus_tool_count as "code-enforced". Before #803 nothing
computed the count: test_claims_sync only pinned the string on surfaces, so the
registry could drift from the published number without failing CI. This test
makes the label true: it asks the same function the MCP server uses to
advertise tools and compares the length to the claim.

If this fails after adding or removing a directive, update claims.json AND
every surface pinned by test_claims_sync in the same change.
"""

import json
from pathlib import Path

import pytest

from conftest import perseus

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(perseus is None, reason="perseus module requires Python 3.10+")
def test_mcp_tool_count_matches_claim():
    claims = json.loads((_ROOT / "claims.json").read_text(encoding="utf-8"))["claims"]
    claimed = int(claims["perseus_tool_count"]["value"])
    tools = perseus._get_all_mcp_tools({})
    names = [t.get("name") for t in tools]
    assert len(names) == len(set(names)), f"duplicate MCP tool names: {names}"
    assert len(tools) == claimed, (
        f"claims.json says perseus_tool_count={claimed} but "
        f"_get_all_mcp_tools() advertises {len(tools)} tools: {sorted(names)}. "
        "Update claims.json and the pinned surfaces together."
    )
