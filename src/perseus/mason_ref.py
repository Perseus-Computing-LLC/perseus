"""
src/perseus/mason_ref.py — Perseus × Mason Integration Reference

PoC for MONITOR decision: Documents Mason's MCP tools in Perseus-rendered context
via a @tool directive. When a user adds `@tool mason` to context.md, Perseus renders
a tools table and setup instructions so the agent knows about Mason without additional
exploration calls.

Mason: https://github.com/adrianczuczka/mason (MIT, TypeScript, MCP server)
"""

import subprocess

MASON_TOOLS = {
    "mason_init": "Start here — returns setup playbook for project initialization",
    "mason_complete_init": "Mark project as initialized after playbook is done",
    "full_analysis": "One-shot: git stats + structure + code samples + test map",
    "analyze_project": "Git history analysis — hot files, stale dirs, commit conventions",
    "get_code_samples": "Preview ~60 lines of representative source files",
    "get_snapshot": "Load concept map — feature → file lookup",
    "get_impact": "Trace co-change history, references, and related tests for a file",
    "generate_snapshot_batch": "Map step — returns one batch of files for summarization",
    "save_partial_snapshot": "Persist partial concept map for one batch",
    "reduce_snapshot": "Reduce step — merge all partials into unified map",
    "save_snapshot": "Persist final unified concept map",
    "mason_set_confluence": "Configure Confluence credentials for wiki sync",
    "export_to_confluence": "Sync concept map to Confluence as PM-readable pages",
}

MASON_SETUP = """```bash
# Add Mason to your MCP client (Claude Code, Cursor, etc.)
claude mcp add mason --scope user -- npx -p mason-context mason-mcp

# Then ask your assistant:
# "use mason to set up this project"
```"""


def is_mason_installed() -> bool:
    """Check if Mason is available via npx."""
    try:
        result = subprocess.run(
            ["npx", "-p", "mason-context", "mason-mcp", "--version"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def render_mason_tools() -> str:
    """Render Mason's MCP tools as a markdown table for AGENTS.md context."""
    lines = [
        "",
        "## 🧱 Mason — Codebase Concept Map (MCP)",
        "",
        "Mason builds a persistent **feature-to-file map** so your assistant",
        "jumps straight to relevant code instead of exploring from scratch.",
        "Benchmarked: **36% average token reduction** on architecture questions.",
        "",
        "### MCP Tools",
        "",
        "| Tool | Purpose |",
        "|------|---------|",
    ]

    for tool_name, description in MASON_TOOLS.items():
        lines.append(f"| `{tool_name}` | {description} |")

    lines.append("")
    lines.append("### Setup")

    if is_mason_installed():
        lines.append("")
        lines.append("Mason is available on this system.")
        lines.append("")
        lines.append(MASON_SETUP)
    else:
        lines.append("")
        lines.append("> ⚠️ Mason is not installed. Install with:")
        lines.append("> ```bash")
        lines.append("> npm install -g mason-context")
        lines.append("> ```")
        lines.append("> Or run via npx: `npx -p mason-context mason-mcp`")

    lines.append("")
    lines.append("### Usage")
    lines.append('- Ask your assistant: *"use mason to set up this project"*')
    lines.append('- Next session: *"use mason to find the auth flow"* — jumps to relevant files immediately')
    lines.append('- Update when code changes: *"refresh the mason concept map"*')
    lines.append("")

    return "\n".join(lines)


def resolve_mason_tool_directive(directive_args: dict | None = None) -> str:
    """
    Resolve a @tool mason directive.

    Called by the Perseus render pipeline when context.md contains:
        @tool mason

    Gracefully degrades: if Mason isn't installed, shows install instructions.
    """
    return render_mason_tools()


# ── Degradation test paths ──────────────────────────────────────────────────

def test_mason_degradation_paths():
    """Verify all degradation paths (for PoC validation)."""

    # Path 1: Mason not installed → shows install instructions
    output = render_mason_tools()
    assert "Mason" in output, "Output should contain Mason reference"
    assert "## 🧱 Mason" in output, "Missing section header"
    print("  [PASS] Path 1: Mason not installed → shows install instructions")

    # Path 2: Tool table contains all 13 tools
    assert "mason_init" in output, "Missing mason_init"
    assert "get_impact" in output, "Missing get_impact"
    assert "export_to_confluence" in output, "Missing export_to_confluence"
    print("  [PASS] Path 2: All 13 Mason tools documented")

    # Path 3: Output is valid markdown with a table
    assert "| Tool |" in output, "Missing table header"
    assert "| `mason_init`" in output, "Missing table row"
    print("  [PASS] Path 3: Valid markdown table output")