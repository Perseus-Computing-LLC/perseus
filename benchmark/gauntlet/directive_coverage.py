#!/usr/bin/env python3
"""Directive coverage report generator for Perseus gauntlet.

Scans all gauntlet role profiles, counts directive occurrences, and
cross-references against DIRECTIVE_REGISTRY to produce a coverage summary.

Usage:
    python directive_coverage.py [--roles-dir PATH] [--json]
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Import Perseus modules
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "benchmark" / "gauntlet"))
from gauntlet_lib import load_role_profiles, count_directives  # noqa: E402

# Load DIRECTIVE_REGISTRY from the built artifact
sys.path.insert(0, str(REPO_ROOT))
import perseus  # noqa: E402


def scan_profile_directives(profile_path: str) -> Counter:
    """Count directive occurrences in a single role profile."""
    text = Path(profile_path).read_text(encoding="utf-8", errors="replace")
    counts = Counter()
    for line in text.splitlines():
        stripped = line.strip()
        # Match lines starting with @directive
        m = re.match(r"^@([a-zA-Z][\w-]*)\b", stripped)
        if m:
            directive = "@" + m.group(1).lower()
            counts[directive] += 1
    return counts


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Perseus directive coverage report")
    parser.add_argument(
        "--roles-dir",
        default=str(REPO_ROOT / "benchmark" / "gauntlet" / "gauntlet_role_profiles"),
        help="Path to role profiles directory",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    # Load profiles
    roles_dir = Path(args.roles_dir)
    profiles = load_role_profiles(roles_dir)

    # Collect directive counts from all profiles
    all_counts = Counter()
    profile_directives: dict[str, set[str]] = {}
    for p in profiles:
        counts = scan_profile_directives(p["path"])
        all_counts.update(counts)
        profile_directives[p["name"]] = set(counts.keys())

    # Registered directives
    registered = set(perseus.DIRECTIVE_REGISTRY.keys())
    # Directives that don't appear in the registry (plugin directives, macros, etc.)
    seen = set(all_counts.keys())
    unknown = seen - registered

    # Coverage analysis
    covered = seen & registered
    missing = registered - seen

    # Cacheable directives
    cacheable_registered = {d for d, s in perseus.DIRECTIVE_REGISTRY.items() if s.cacheable}
    cacheable_covered = cacheable_registered & covered
    cacheable_missing = cacheable_registered - covered

    if args.json:
        output = {
            "profile_count": len(profiles),
            "registered_directives": len(registered),
            "covered_directives": len(covered),
            "missing_directives": sorted(missing),
            "coverage_pct": round(len(covered) / len(registered) * 100, 1) if registered else 0,
            "total_occurrences": sum(all_counts.values()),
            "directive_counts": dict(sorted(all_counts.items())),
            "cacheable": {
                "registered": len(cacheable_registered),
                "covered": len(cacheable_covered),
                "missing": sorted(cacheable_missing),
                "coverage_pct": round(len(cacheable_covered) / len(cacheable_registered) * 100, 1) if cacheable_registered else 0,
            },
            "unknown_directives": sorted(unknown) if unknown else [],
        }
        print(json.dumps(output, indent=2))
    else:
        coverage_pct = round(len(covered) / len(registered) * 100, 1) if registered else 0
        cache_pct = round(len(cacheable_covered) / len(cacheable_registered) * 100, 1) if cacheable_registered else 0

        print("DIRECTIVE COVERAGE REPORT")
        print("========================")
        print(f"Registered: {len(registered):3d}  |  Covered: {len(covered):3d}  |  Missing: {len(missing):3d}  |  Coverage: {coverage_pct}%")
        print(f"Cacheable:  {len(cacheable_registered):3d}  |  Covered: {len(cacheable_covered):3d}  |  Missing: {len(cacheable_missing):3d}  |  Coverage: {cache_pct}%")
        print(f"Profiles: {len(profiles)}  |  Total directive occurrences: {sum(all_counts.values())}")
        print()

        # Directive-by-directive breakdown
        print(f"{'Directive':<20} {'Occurrences':>12}  {'Covered':>8}  {'Cacheable':>10}  {'Tier':>5}")
        print("-" * 65)
        for directive in sorted(registered):
            spec = perseus.DIRECTIVE_REGISTRY.get(directive)
            count = all_counts.get(directive, 0)
            status = "✓" if directive in covered else "✗"
            cache = "✓" if spec.cacheable else "—"
            tier = spec.tier if spec else "?"
            print(f"{directive:<20} {count:>12,d}  {status:>8}  {cache:>10}  {tier:>5}")

        if unknown:
            print()
            print(f"⚠ {len(unknown)} unknown directive(s) found in profiles: {', '.join(sorted(unknown))}")

        if missing:
            print()
            print(f"✗ {len(missing)} uncovered directive(s): {', '.join(sorted(missing))}")


if __name__ == "__main__":
    main()
