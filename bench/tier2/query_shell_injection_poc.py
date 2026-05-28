#!/usr/bin/env python3
"""bench/tier2/query_shell_injection_poc.py — Demonstrate shell injection in @query.

When render.allow_query_shell=true, the command string is passed directly to
subprocess.run(shell=True) with no shell metacharacter escaping.
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "/workspace/perseus")
import perseus

def test_shell_injection():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir) / "workspace"
        ws.mkdir()
        cfg = {"render": {"allow_query_shell": True, "max_query_bytes": 10240}}

        tests = [
            ("Command chaining &&", '"echo safe && echo also_executed"'),
            ("Command substitution $()", '"echo user_is_$(whoami)"'),
            ("Pipe |", '"echo hello | rev"'),
            ("Backtick ``", '"echo date_is_`date +%Y`"'),
            ("Variable $HOME", '"echo home_is_$HOME"'),
        ]

        found_injection = False
        for desc, cmd in tests:
            print(f"\nTest: {desc}")
            print(f"  Command: {cmd}")
            result = perseus.resolve_query(cmd, cfg=cfg, workspace=ws)
            output = result.strip()
            print(f"  Output:  {output[:120]}")
            if desc == "Command chaining &&" and "also_executed" in output:
                print("  ** INJECTION: Second command executed via shell chaining")
                found_injection = True
            if desc == "Pipe |" and "olleh" in output:
                print("  ** INJECTION: Pipe executed through shell")
                found_injection = True

        # Test gate when disabled
        print(f"\nTest: Gate when allow_query_shell=false")
        cfg_disabled = {"render": {"allow_query_shell": False}}
        result = perseus.resolve_query('"echo should_not_run"', cfg=cfg_disabled, workspace=ws)
        print(f"  Output: {result.strip()}")
        if "disabled" in result.lower():
            print("  OK: Gate blocks properly")
        else:
            print("  ** BUG: Gate failed")
            found_injection = True

        return found_injection


if __name__ == "__main__":
    bug = test_shell_injection()
    if bug:
        print("\nSHELL INJECTION CONFIRMED (gated by allow_query_shell=false by default)")
    else:
        print("\nNo injection detected")
