#!/usr/bin/env python3
"""
gauntlet_setup.py — Full environment setup for the Perseus Gauntlet.

1. Creates PERSEUS_HOME configs with allow_query_shell=true
2. Seeds Mnēmē vault with 75 synthetic memory records
3. Creates workspace checkpoints for @memory narrative data
4. Creates referenced files for @read directives
5. Builds Mnēmē narrative from seeded data
6. Verifies a single render produces real output

Usage:
    python3 benchmark/gauntlet/gauntlet_setup.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GAUNTLET_DIR = Path(__file__).resolve().parent
PROFILES_DIR = GAUNTLET_DIR / "gauntlet_role_profiles"
COLD_HOME = Path("/tmp/perseus-gauntlet/cold")
WARM_HOME = Path("/tmp/perseus-gauntlet/warm")
PROFILE_WORKSPACE_LABEL = os.environ.get(
    "GAUNTLET_PROFILE_WORKSPACE_LABEL",
    "/workspace/perseus/benchmark/gauntlet/gauntlet_role_profiles",
)


def create_config(home: Path) -> None:
    """Create config.yaml with allow_query_shell=true."""
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.yaml"
    config_path.write_text("""\
# Perseus Gauntlet config — benchmarking mode
render:
  allow_query_shell: true
  cache:
    ttl: 86400
memory:
  mneme_vault_path: ""
  mneme_index_path: ""
""")
    print(f"  ✓ Config: {config_path}")


def seed_vault(home: Path) -> int:
    """Run the seed script."""
    sys.path.insert(0, str(GAUNTLET_DIR))
    from gauntlet_seed_mneme import generate_memories
    count = generate_memories(75, home)
    print(f"  ✓ Seeded {count} memory records → {home}/memory/vault/")
    return count


def create_checkpoints(profile_dir: Path) -> int:
    """Create synthetic checkpoint data in the profiles workspace.

    Checkpoints are JSON files in .perseus/checkpoints/ with session metadata.
    The narrative engine reads these to build the @memory narrative.
    """
    perseus_dir = profile_dir / ".perseus"
    checkpoints_dir = perseus_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # Create 20 synthetic checkpoint records across 4 simulated sessions
    base_ts = datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc)

    sessions = [
        {"id": "sess-001", "label": "Mnēmē v2 initial implementation"},
        {"id": "sess-002", "label": "FTS5 index optimization"},
        {"id": "sess-003", "label": "Build artifact drift fix"},
        {"id": "sess-004", "label": "Gauntlet benchmark design"},
    ]

    checkpoint_count = 0
    for si, session in enumerate(sessions):
        for ci in range(5):
            ts = base_ts + timedelta(hours=si * 6 + ci * 1, minutes=ci * 7)
            cp = {
                "session_id": session["id"],
                "timestamp": ts.isoformat(),
                "label": f"{session['label']} — iteration {ci+1}",
                "workspace": PROFILE_WORKSPACE_LABEL,
                "directives_used": [
                    "@query", "@read", "@memory", "@services",
                    "@health", "@agora", "@inbox", "@drift",
                ][:2 + ci % 5],
                "files_changed": ci + 1,
                "duration_s": 120 + ci * 30,
                "exit_code": 0,
                "checkpoint_number": ci + 1,
            }
            cp_path = checkpoints_dir / f"checkpoint-{checkpoint_count:03d}.json"
            cp_path.write_text(json.dumps(cp, indent=2))
            checkpoint_count += 1

    # Also create checkpoints in the perseus home (cold/warm)
    for home in [COLD_HOME, WARM_HOME]:
        home_checkpoints = home / ".perseus" / "checkpoints"
        home_checkpoints.mkdir(parents=True, exist_ok=True)
        for si, session in enumerate(sessions):
            for ci in range(5):
                ts = base_ts + timedelta(hours=si * 6 + ci * 1, minutes=ci * 7)
                cp = {
                    "session_id": session["id"],
                    "timestamp": ts.isoformat(),
                    "label": f"{session['label']} — iteration {ci+1}",
                    "workspace": PROFILE_WORKSPACE_LABEL,
                    "directives_used": ["@query", "@read", "@memory"],
                    "files_changed": ci + 1,
                    "duration_s": 120 + ci * 30,
                    "exit_code": 0,
                }
                cp_path = home_checkpoints / f"checkpoint-{checkpoint_count:03d}.json"
                cp_path.write_text(json.dumps(cp, indent=2))
                checkpoint_count += 1

    print(f"  ✓ Created {checkpoint_count} checkpoints")
    return checkpoint_count


def create_referenced_files(profile_dir: Path) -> None:
    """Create minimal versions of files referenced by @read directives."""
    refs = {
        "README.md": "# Perseus Gauntlet\n\nSynthetic workspace for benchmarking.\n",
        "ROADMAP.md": "# Roadmap\n\n- Phase 1: Mnēmē v2\n- Phase 2: Federation\n",
        "AGENTS.md": "# AI Agent Guide\n\nBuild instructions for AI contributors.\n",
        "CONTRIBUTING.md": "# Contributing\n\nSee docs/CONTRIBUTING.md\n",
        "pyproject.toml": "[project]\nname = \"perseus\"\nversion = \"1.0.5\"\n",
        "package.json": '{"name": "perseus", "version": "1.0.5"}',
        "Dockerfile": "FROM python:3.12\nCOPY perseus.py /app/\n",
    }

    # Create in profile dir for @read
    count = 0
    for name, content in refs.items():
        path = profile_dir / name
        if not path.exists():
            path.write_text(content)
            count += 1

    # Also create .perseus/context.md (referenced by architect)
    context_md = profile_dir / ".perseus" / "context.md"
    context_md.parent.mkdir(parents=True, exist_ok=True)
    if not context_md.exists():
        context_md.write_text("@perseus v1.0\n@prompt Gauntlet benchmark context\n")

    print(f"  ✓ Created {count} referenced files + .perseus/context.md")


def build_narrative(home: Path) -> None:
    """Run perseus memory update to build narrative from checkpoints."""
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(home)

    # First verify checkpoints exist
    cp_dir = home / ".perseus" / "checkpoints"
    if cp_dir.is_dir():
        cp_count = len(list(cp_dir.glob("*.json")))
        print(f"  Checkpoints in {home}: {cp_count}")
    else:
        print(f"  WARNING: No checkpoints in {home}")

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "perseus.py"), "memory", "update"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    if result.returncode == 0:
        print(f"  ✓ Narrative built: {result.stdout.strip()[:100]}")
    else:
        print(f"  ⚠ Narrative build: {result.stderr.strip()[:200]}")


def verify_render(profile_name: str = "architect") -> bool:
    """Render one profile and verify all directives produce real output."""
    profile_path = PROFILES_DIR / f"{profile_name}.md"
    if not profile_path.exists():
        print(f"  ✗ Profile not found: {profile_path}")
        return False

    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(COLD_HOME)

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "perseus.py"), "render", str(profile_path)],
        capture_output=True, text=True, timeout=60, env=env,
        cwd=str(PROFILES_DIR),  # workspace = profiles dir
    )

    output = result.stdout
    stderr = result.stderr

    checks = {
        "@query disabled": "disabled by config" not in output,
        "@memory narrative": "No Mnēmē narrative" not in output,
        "@read missing": "file not found" not in output,
        "@services": "URLError" not in output if "services" in output.lower() else None,
        "Exit code 0": result.returncode == 0,
    }

    all_pass = True
    print(f"\n  Verify: {profile_name}.md")
    for check, passed in checks.items():
        if passed is None:
            continue
        status = "✓" if passed else "✗"
        if not passed:
            all_pass = False
        print(f"    {status} {check}")

    if not all_pass:
        print(f"\n  --- Render output (first 60 lines) ---")
        for i, line in enumerate(output.splitlines()[:60]):
            print(f"  {line[:120]}")

    return all_pass


def main():
    print("=" * 60)
    print("Perseus Gauntlet — Environment Setup")
    print("=" * 60)

    # 1. Create configs
    print("\n1. Creating configs...")
    create_config(COLD_HOME)
    create_config(WARM_HOME)

    # 2. Seed vaults
    print("\n2. Seeding Mnēmē vaults...")
    seed_vault(COLD_HOME)
    seed_vault(WARM_HOME)

    # 3. Create checkpoints
    print("\n3. Creating checkpoints...")
    create_checkpoints(PROFILES_DIR)

    # 4. Create referenced files
    print("\n4. Creating referenced files...")
    create_referenced_files(PROFILES_DIR)

    # 5. Build narratives
    print("\n5. Building narratives...")
    build_narrative(COLD_HOME)
    build_narrative(WARM_HOME)

    # 6. Verify
    print("\n6. Verifying render...")
    ok = verify_render("architect")
    if not ok:
        print("\n⚠ Some directives still not resolving optimally.")
        print("  (Services will fail without actual servers — expected)")
        print("  Proceeding with gauntlet anyway...")

    print(f"\n{'=' * 60}")
    print("Setup complete. Ready for gauntlet.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
