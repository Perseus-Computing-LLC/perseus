"""User-facing documentation contracts for context, memory, and launchers."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "QUICKSTART.md",
    ROOT / "SETUP-GUIDE.md",
    ROOT / "WIRING.md",
    ROOT / "docs" / "quickstart.md",
)

LAUNCHER_DOCS = PUBLIC_DOCS + (
    ROOT / "spec" / "integration.md",
    ROOT / "docs" / "nexo-integration-guide.md",
)


def test_public_docs_define_the_context_and_memory_boundary():
    """All primary onboarding docs use the same ownership vocabulary."""
    required = (
        "active working context",
        "durable memory",
        "recalled memory",
        "session history",
        "perseus resolves and shapes the active working context",
        "perseus vault owns durable-memory persistence and recall",
        "@memory",
    )

    for path in PUBLIC_DOCS:
        text = path.read_text(encoding="utf-8").lower()
        missing = [phrase for phrase in required if phrase not in text]
        assert not missing, f"{path.relative_to(ROOT)} missing: {missing}"


def test_public_docs_use_the_stable_launcher_for_automation():
    """MCP and scheduler guidance must point at the upgrade-safe launcher."""
    for path in LAUNCHER_DOCS:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        assert "~/.local/bin/perseus" in text, f"{rel} lacks the stable launcher"
        assert not re.search(r"(?i)library/python|python/3\.", text), (
            f"{rel} contains a version-specific launcher path"
        )
        assert not re.search(
            r"(?m)^\s*['\"]?command['\"]?\s*:\s*['\"]?perseus['\"]?\s*$",
            text,
        ), f"{rel} contains a bare MCP launcher"
