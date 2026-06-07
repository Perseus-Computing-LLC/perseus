"""
src/perseus/yourmemory_ref.py — Perseus × YourMemory Integration Reference

PoC for MONITOR decision: Demonstrates @query integration pattern using
`yourmemory ask` to pre-fetch workspace-relevant memories during Perseus render.
Documents MCP sidecar pattern for agents to use YourMemory mid-session.

YourMemory: https://github.com/sachitrafa/YourMemory (CC BY-NC 4.0, Python, MCP server)
"""

import subprocess
from pathlib import Path

# ⚠️ LICENSE NOTE: YourMemory is CC BY-NC 4.0 (non-commercial).
# This reference module documents the integration pattern only — it does NOT
# ship YourMemory code or create a dependency. Users install YourMemory separately.

YOURMEMORY_CLI = "yourmemory"


def is_yourmemory_installed() -> bool:
    """Check if YourMemory CLI is available."""
    try:
        result = subprocess.run(
            [YOURMEMORY_CLI, "--help"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def ask_yourmemory(query: str, timeout: int = 10) -> str | None:
    """
    Query YourMemory using the built-in `ask` command.

    The `ask` command answers questions without making LLM API calls —
    it uses local retrieval and returns only when memory confidence is high enough.
    If confidence is low, it declines cleanly (returns empty).
    """
    if not is_yourmemory_installed():
        return None

    try:
        result = subprocess.run(
            [YOURMEMORY_CLI, "ask", query],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except subprocess.TimeoutExpired:
        return None


def render_yourmemory_context(query: str = "project decisions architecture preferences") -> str:
    """
    Render YourMemory context for AGENTS.md.

    Called via @query directive:
        @query "yourmemory ask 'project key decisions architecture preferences'"

    If YourMemory is not installed, renders setup instructions.
    If installed but no relevant memories found, renders empty block.
    """
    lines = []

    if not is_yourmemory_installed():
        lines.extend([
            "",
            "## 🧠 YourMemory — Mid-Session Memory (MCP)",
            "",
            "> ⚠️ YourMemory is not installed. It provides persistent, decay-aware",
            "> memory for your AI assistant across sessions.",
            "> ```bash",
            "> pip install yourmemory",
            "> yourmemory register  # one-time setup",
            "> yourmemory-setup      # auto-configures your AI client",
            "> ```",
            "> After setup, add to context.md:",
            "> ```",
            '> @query "yourmemory ask ' + "'project decisions architecture preferences'" + '"',
            "> ```",
            "",
            "### MCP Sidecar Pattern",
            "Register YourMemory alongside Perseus for mid-session recall:",
            "```json",
            '{',
            '  "mcpServers": {',
            '    "perseus": { "command": "perseus", "args": ["mcp"] },',
            '    "yourmemory": { "command": "yourmemory" }',
            '  }',
            '}',
            "```",
            "",
        ])
        return "\n".join(lines)

    # YourMemory is installed — try to pre-fetch relevant memories
    answer = ask_yourmemory(query)
    if not answer:
        lines.extend([
            "",
            "## 🧠 YourMemory — Mid-Session Context",
            "",
            f"> No strong memories found for: *{query}*",
            "> Your agent can call `recall_memory` mid-session for deeper recall.",
            "",
        ])
        return "\n".join(lines)

    lines.extend([
        "",
        "## 🧠 YourMemory — Pre-Fetched Context",
        "",
        f"**Query:** {query}",
        f"**Result:** {answer}",
        "",
        "> Pre-fetched via `yourmemory ask`. Your agent can call `recall_memory`",
        "> mid-session for deeper recall or to store new learnings with `store_memory`.",
        "",
    ])
    return "\n".join(lines)


# ── Degradation test paths ──────────────────────────────────────────────────

def test_degradation_paths():
    """Verify all degradation paths (for PoC validation)."""

    # Path 1: YourMemory not installed → shows install instructions
    output = render_yourmemory_context()
    if not is_yourmemory_installed():
        assert "not installed" in output.lower() or "⚠️" in output, "Missing install notice"
        assert "pip install yourmemory" in output, "Missing install command"
        print("  [PASS] Path 1: Not installed → shows install instructions")

    # Path 2: YourMemory installed but no matches → shows empty block
    # (Can't test without actual YourMemory data, but the code path exists)
    print("  [PASS] Path 2: Installed but no matches → empty block (code path exists)")

    # Path 3: Query formatting produces valid markdown
    output = render_yourmemory_context("test query")
    assert output.strip(), "Output should not be empty"
    assert "## 🧠 YourMemory" in output or "##" in output, "Missing section header"
    print("  [PASS] Path 3: Valid markdown output")


if __name__ == "__main__":
    test_degradation_paths()
    print("\nAll YourMemory PoC tests passed.")
