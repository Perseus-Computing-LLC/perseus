#!/usr/bin/env python3
"""directive_coverage.py — Post-gauntlet directive coverage report.

Reads all role profiles, counts directive occurrences, cross-references
against DIRECTIVE_REGISTRY, and reports coverage gaps.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GAUNTLET_DIR = Path(__file__).resolve().parent
PROFILES_DIR = GAUNTLET_DIR / "gauntlet_role_profiles"

# Mappings from registry (kept in sync manually — the registry lives in the build artifact)
DIRECTIVE_TABLE: dict[str, dict] = {
    "@date":        {"tier": 1, "cacheable": False, "summary": "Current date/time"},
    "@waypoint":    {"tier": 1, "cacheable": True,  "summary": "Latest checkpoint summary"},
    "@memory":      {"tier": 1, "cacheable": True,  "summary": "Memory search + narrative"},
    "@health":      {"tier": 1, "cacheable": False, "summary": "Context maintenance report"},
    "@env":         {"tier": 1, "cacheable": False, "summary": "Embed environment variable"},
    "@prompt":      {"tier": 1, "cacheable": False, "summary": "System prompt block"},
    "@constraint":  {"tier": 1, "cacheable": False, "summary": "Constraint block"},
    "@validate":    {"tier": 1, "cacheable": False, "summary": "Schema validation block"},
    "@if":          {"tier": 1, "cacheable": False, "summary": "Conditional block start"},
    "@else":        {"tier": 1, "cacheable": False, "summary": "Conditional else"},
    "@endif":       {"tier": 1, "cacheable": False, "summary": "Conditional block end"},
    "@end":         {"tier": 1, "cacheable": False, "summary": "Block directive end"},
    "@services":    {"tier": 2, "cacheable": False, "summary": "Health-check services"},
    "@skills":      {"tier": 2, "cacheable": True,  "summary": "List available skills"},
    "@session":     {"tier": 2, "cacheable": True,  "summary": "Recent session digests"},
    "@agora":       {"tier": 2, "cacheable": True,  "summary": "Task board"},
    "@inbox":       {"tier": 2, "cacheable": True,  "summary": "Agent message inbox"},
    "@drift":       {"tier": 2, "cacheable": False, "summary": "Oracle drift report"},
    "@perseus":     {"tier": 2, "cacheable": True,  "summary": "Remote Perseus fetch"},
    "@mneme":       {"tier": 2, "cacheable": False, "summary": "Memory recall (BM25)"},
    "@query":       {"tier": 3, "cacheable": True,  "summary": "Run shell command"},
    "@read":        {"tier": 3, "cacheable": True,  "summary": "Embed file contents"},
    "@include":     {"tier": 3, "cacheable": True,  "summary": "Include and render file"},
    "@list":        {"tier": 3, "cacheable": True,  "summary": "List directory contents"},
    "@tree":        {"tier": 3, "cacheable": True,  "summary": "Tree view of directory"},
    "@agent":       {"tier": 3, "cacheable": False, "summary": "Execute agent subprocess"},
    "@tool":        {"tier": 3, "cacheable": False, "summary": "Allowlisted external tool"},
    "@synthesize":  {"tier": 3, "cacheable": False, "summary": "LLM synthesis block"},
    "@prefetch":    {"tier": 3, "cacheable": False, "summary": "Prefetch warming"},
    "@graph":       {"tier": 3, "cacheable": False, "summary": "Dependency graph"},
    "@focus":       {"tier": 3, "cacheable": False, "summary": "Context focus"},
}


def count_directives_in_profiles(profiles_dir: Path) -> dict[str, int]:
    """Count occurrences of each directive across all profiles."""
    counts: dict[str, int] = {}
    META = {"readme", "roadmap", "agents", "contributing", "circular-a", "circular-b", "level-1", "level-2"}

    for f in sorted(profiles_dir.iterdir()):
        if f.suffix != ".md":
            continue
        if f.stem.lower() in META:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        directives = re.findall(r'@(\w+)', text)
        for d in directives:
            d_lower = d.lower()
            # Map aliases
            alias_map = {"q": "query", "chk": "health", "dr": "drift", "syn": "synthesize"}
            d_lower = alias_map.get(d_lower, d_lower)
            key = f"@{d_lower}"
            # Skip non-directive @ tokens (@perseus header, @end, @cache, @else, @endif)
            if key not in DIRECTIVE_TABLE:
                continue
            counts[key] = counts.get(key, 0) + 1

    return counts


def generate_report(profile_counts: dict[str, int]) -> str:
    """Generate a markdown coverage report."""
    lines: list[str] = []
    lines.append("# Perseus Gauntlet — Directive Coverage Report")
    lines.append("")
    lines.append(f"**Profiles scanned:** {len([f for f in PROFILES_DIR.iterdir() if f.suffix == '.md'])}")
    lines.append(f"**Directive types registered:** {len(DIRECTIVE_TABLE)}")
    lines.append(f"**Directive types covered:** {len(profile_counts)}")
    lines.append("")

    # Coverage percentage
    registered = set(DIRECTIVE_TABLE.keys())
    covered = set(profile_counts.keys())
    missing = registered - covered
    coverage_pct = len(covered) / len(registered) * 100 if registered else 0
    lines.append(f"## Coverage: {coverage_pct:.0f}% ({len(covered)}/{len(registered)})")
    lines.append("")

    if missing:
        lines.append("### Missing Directives (not in any profile)")
        lines.append("")
        lines.append("| Directive | Tier | Cacheable | Summary |")
        lines.append("|-----------|------|-----------|---------|")
        for d in sorted(missing):
            info = DIRECTIVE_TABLE[d]
            lines.append(f"| `{d}` | {info['tier']} | {'✓' if info['cacheable'] else '✗'} | {info['summary']} |")
        lines.append("")

    # Coverage table
    lines.append("### Covered Directives")
    lines.append("")
    lines.append("| Directive | Tier | Cacheable | Occurrences | Summary |")
    lines.append("|-----------|------|-----------|-------------|---------|")
    total_occurrences = 0
    for d in sorted(covered, key=lambda x: -profile_counts.get(x, 0)):
        count = profile_counts[d]
        total_occurrences += count
        info = DIRECTIVE_TABLE[d]
        lines.append(f"| `{d}` | {info['tier']} | {'✓' if info['cacheable'] else '✗'} | {count} | {info['summary']} |")
    lines.append("")

    # Per-profile breakdown
    lines.append("### Per-Profile Breakdown")
    lines.append("")
    lines.append("| Profile | Directives |")
    lines.append("|---------|-----------|")

    META = {"readme", "roadmap", "agents", "contributing", "circular-a", "circular-b", "level-1", "level-2"}
    for f in sorted(PROFILES_DIR.iterdir()):
        if f.suffix != ".md":
            continue
        if f.stem.lower() in META:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        directives = re.findall(r'@(\w+)', text)
        count = len([d for d in directives if f"@{d.lower()}" in DIRECTIVE_TABLE])
        lines.append(f"| {f.stem} | {count} |")

    lines.append("")
    lines.append(f"**Total directive occurrences:** {total_occurrences}")
    lines.append(f"**Profiles with directives:** {len([f for f in PROFILES_DIR.iterdir() if f.suffix == '.md' and f.stem.lower() not in META])}")

    return "\n".join(lines)


def main() -> int:
    if not PROFILES_DIR.is_dir():
        print(f"ERROR: Profiles directory not found: {PROFILES_DIR}", file=sys.stderr)
        return 1

    profile_counts = count_directives_in_profiles(PROFILES_DIR)
    report = generate_report(profile_counts)
    print(report)

    # Also write to file
    output_path = GAUNTLET_DIR / "directive_coverage_report.md"
    output_path.write_text(report)
    print(f"\nReport saved to: {output_path}")

    # Return exit code based on coverage
    registered = set(DIRECTIVE_TABLE.keys())
    covered = set(profile_counts.keys())
    missing = registered - covered
    if missing:
        print(f"\n⚠ {len(missing)} directives not covered: {', '.join(sorted(missing))}")
        return 0  # soft warning — don't block CI
    return 0


if __name__ == "__main__":
    sys.exit(main())
