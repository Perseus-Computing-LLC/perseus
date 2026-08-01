"""Enforce the internal MCP compatibility count against the actual registry.

The internal compatibility claim is deliberately not a public marketing
surface, but it still guards the current default registry contract. The test
asks the same function the MCP server uses to advertise tools and compares the
length to the internal claim.

If this fails after adding or removing a directive, update the internal claim
and compatibility tests in the same change. Public copy should not be changed
to add a fixed tool count.
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
        "Update the internal claim and compatibility tests together; do not add a public count."
    )
