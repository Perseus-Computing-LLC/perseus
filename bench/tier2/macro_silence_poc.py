#!/usr/bin/env python3
"""bench/tier2/macro_silence_poc.py — Demonstrate unterminated @macro consuming all content.

If @endmacro is missing, _parse_macros_from_lines silently consumes every
line to EOF. All subsequent template content disappears with no warning.
"""
import sys, os
sys.path.insert(0, "/workspace/perseus")
# Use the built artifact, not source modules
import perseus

def test_unterminated_macro():
    lines = [
        "# Report",
        "",
        "Some important text.",
        "",
        "@macro broken",
        "This is the macro body.",
        "@read \"important.md\"",
        "@query \"status check\"",
        "",
        "# More important content",
        "",
        "@memory",
        "@waypoint",
        "",
        "Yet more content.",
        "The end.",
    ]

    macros = perseus._parse_macros_from_lines(lines)

    print(f"Input: {len(lines)} lines")
    print(f"Macros parsed: {list(macros.keys())}")

    if "broken" in macros:
        body, params = macros["broken"]
        print(f"\n** BUG CONFIRMED: Unterminated @macro consumed everything after it")
        print(f"  Macro body has {len(body)} lines (should be ~3-4)")
        print(f"  Content lost: lines 5-{len(lines)}")
        for i, line in enumerate(body[:10]):
            print(f"    body[{i}]: {line[:80]}")
        if len(body) > 10:
            print(f"    ... and {len(body) - 10} more lines silently consumed")

        lost = lines[5:]
        print(f"\n  Content silently dropped ({len(lost)} lines):")
        for line in lost[:5]:
            print(f"    LOST: {line[:80]}")
        if len(lost) > 5:
            print(f"    ... and {len(lost) - 5} more lines")
        return False
    else:
        print("PASS: No macro parsed (unterminated handled correctly)")
        return True


def test_terminated_macro():
    lines = [
        "@macro good",
        "  Body line 1",
        "  Body line 2",
        "@endmacro",
        "# Regular content",
    ]
    macros = perseus._parse_macros_from_lines(lines)
    print(f"\nControl: Macros: {list(macros.keys())}")
    if "good" in macros:
        body, params = macros["good"]
        print(f"  Body lines: {len(body)}")
        print(f"  PASS: Properly terminated macro works")
        return True
    return False


if __name__ == "__main__":
    r1 = test_unterminated_macro()
    r2 = test_terminated_macro()
    if r1 and r2:
        print("\nALL PASS")
    else:
        print("\nUNTERMINATED MACRO BUG CONFIRMED")
        sys.exit(1)
