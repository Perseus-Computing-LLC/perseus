"""
Perseus → Vault-Mem integration hook.

Plugs into Perseus's render_output() pipeline. After resolve+redact,
optionally queries vault-mem for project-specific memories and injects
them into the rendered context as a "Project Memory" section.

Integration design:
  - **Subprocess CLI**: Calls vault-mem's CLI (`vault-mem-mcp`) via
    subprocess, using `memory_context` or `export-skill --target=generic`
    to fetch structured project memories.
  - **Graceful degradation**: If vault-mem is not installed, the vault
    doesn't exist, or the CLI fails, returns the original context unchanged.
    Perseus works identically without vault-mem.
  - **Opt-in**: Controlled by `VAULTMEM_ENABLED=1` env var and/or Perseus
    config setting. Off by default.
  - **Token-aware**: vault-mem's `memory_context` tool already respects
    `max_tokens` budgets. We pass a sensible default and let vault-mem
    truncate appropriately.

Architecture fit: Vault-mem is a "company brain" memory layer with typed
memories (decisions, observations, learnings, todos, entities, questions).
Complementary to Perseus's pre-session context resolution — Perseus
resolves environment state (services, sessions, skills), vault-mem adds
project knowledge (past decisions, accumulated learnings). Together,
they give the agent a complete picture.

Integration surface: Single Python module (~180 lines). Subprocess
call to `node .../vault-mem-mcp`. No SDK dependency, no sidecar process.
No new Python dependencies.

Token efficiency: ADDS tokens but HIGH VALUE. User controls with
max_tokens config. Typical injection: 1-3KB of curated project context.

Maintenance: One-time integration. Vault-mem is MIT-licensed, actively
maintained by frozo-ai (YC S26 applicant). Bus factor: 2 (founder +
open-source community). If vault-mem disappears, Perseus continues
unchanged.

User-facing value: HIGH. Agents get project-specific decisions, learnings,
and context without manual copy-paste. The "skill export" feature means
agents get a curated, structured knowledge bundle.

Overlap: COMPLEMENTARY. Perseus has mneme (semantic search memory)
and Mneme vault (markdown storage + narrative). Vault-mem adds typed
memory (decisions vs observations vs learnings), automatic keeper hygiene,
and the skill-export feature that Perseus doesn't have.

Verdict: INTEGRATE. High-value, low-risk, clean complement to Perseus.
Follow the merlin_dedup pattern: subprocess call, graceful degradation,
opt-in via config.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional


# ── Configuration resolution ─────────────────────────────────────────────────


def _vaultmem_binary() -> Optional[str]:
    """Resolve the vault-mem-mcp binary/script path."""
    explicit = os.environ.get("VAULTMEM_BINARY")
    if explicit and os.path.exists(explicit):
        return explicit

    # Check common locations
    candidates = [
        # If cloned alongside perseus
        Path(os.environ.get("PERSEUS_REPO_ROOT", "")) / ".." / "frozo-vault-mem"
        / "packages" / "mcp" / "bin" / "vault-mem-mcp",
        # Standard dev clone
        Path.home() / "frozo-vault-mem" / "packages" / "mcp" / "bin" / "vault-mem-mcp",
        # Installed via npm/pnpm
        Path.home() / ".local" / "share" / "pnpm" / "vault-mem-mcp",
    ]

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.exists():
            return str(resolved)

    # Fallback: try `npx vault-mem-mcp`
    try:
        r = subprocess.run(
            ["npx", "-y", "vault-mem-mcp", "--version"],
            capture_output=True,
            timeout=10,
        )
        if r.returncode == 0:
            return "npx"
    except Exception:
        pass

    return None


def _vaultmem_available() -> bool:
    """Check if vault-mem is installed and usable."""
    return _vaultmem_binary() is not None


def _vaultmem_enabled(cfg: dict) -> bool:
    """Check if vault-mem integration is enabled via env or config."""
    if os.environ.get("VAULTMEM_ENABLED", "").strip() in ("1", "true", "yes"):
        return True
    return cfg.get("vaultmem", {}).get("enabled", False)


def _vaultmem_vault_path(cfg: dict) -> str:
    """Resolve vault-mem vault path."""
    return os.environ.get(
        "VAULT_MEM_PATH",
        cfg.get("vaultmem", {}).get("vault_path", str(Path.home() / "vault-mem")),
    )


def _vaultmem_projects(cfg: dict) -> list[str]:
    """Get project slugs to query for context."""
    env_projects = os.environ.get("VAULTMEM_PROJECTS", "")
    if env_projects:
        return [p.strip() for p in env_projects.split(",") if p.strip()]
    return cfg.get("vaultmem", {}).get("projects", [])


def _vaultmem_max_tokens(cfg: dict) -> int:
    """Max tokens for memory context injection."""
    env_val = os.environ.get("VAULTMEM_MAX_TOKENS", "")
    if env_val and env_val.isdigit():
        return int(env_val)
    return cfg.get("vaultmem", {}).get("max_tokens", 2000)


# ── Core integration ─────────────────────────────────────────────────────────


def fetch_project_memory(
    project: str, cfg: dict, max_tokens: int = 2000
) -> tuple[Optional[str], dict]:
    """
    Fetch curated project context from vault-mem for a single project.

    Returns (memory_text, stats). On any failure or if vault-mem is
    unavailable, returns (None, stats_with_skip_reason).
    """
    stats: dict = {
        "ok": True,
        "project": project,
        "output_bytes": 0,
        "duration_ms": 0,
        "skipped_reason": None,
        "error": None,
    }

    binary = _vaultmem_binary()
    if not binary:
        stats["skipped_reason"] = "vault-mem binary not found"
        stats["ok"] = False
        return None, stats

    vault_path = _vaultmem_vault_path(cfg)
    if not os.path.isdir(vault_path):
        stats["skipped_reason"] = f"vault path not found: {vault_path}"
        stats["ok"] = False
        return None, stats

    # Strategy: use export-skill --target=generic to get structured output
    # This gives us decisions, learnings, entities, and questions as
    # structured markdown, which is perfect for AGENTS.md injection.
    env = os.environ.copy()
    env["VAULT_MEM_PATH"] = vault_path

    t0 = time.perf_counter_ns()

    try:
        if binary == "npx":
            cmd = ["npx", "-y", "vault-mem-mcp", "export-skill",
                   project, "--target=generic", "--max-tokens", str(max_tokens)]
        else:
            cmd = ["node", binary, "export-skill",
                   project, "--target=generic", "--max-tokens", str(max_tokens)]

        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
            env=env,
            text=True,
        )

        t1 = time.perf_counter_ns()
        stats["duration_ms"] = (t1 - t0) // 1_000_000

        if r.returncode != 0:
            stats["error"] = f"export-skill exit {r.returncode}: {r.stderr[:200]}"
            stats["ok"] = False
            return None, stats

        output = r.stdout.strip()
        if not output:
            stats["skipped_reason"] = f"no memories for project '{project}'"
            return None, stats

        stats["output_bytes"] = len(output.encode("utf-8"))
        return output, stats

    except subprocess.TimeoutExpired:
        stats["error"] = "vault-mem timed out after 30s"
        stats["ok"] = False
        return None, stats
    except Exception as e:
        stats["error"] = f"{type(e).__name__}: {e}"
        stats["ok"] = False
        return None, stats


def inject_vaultmem_context(context: str, cfg: dict) -> str:
    """
    Inject vault-mem project memories into rendered Perseus context.

    Concatenates memory sections after the rendered context.
    Gracefully degrades if vault-mem is unavailable.
    """
    if not _vaultmem_enabled(cfg):
        return context

    if not _vaultmem_available():
        import sys

        print("[perseus] vault-mem: not available, skipping", file=sys.stderr)
        return context

    projects = _vaultmem_projects(cfg)
    if not projects:
        print("[perseus] vault-mem: enabled but no projects configured", file=sys.stderr)
        return context

    max_tokens = _vaultmem_max_tokens(cfg)
    all_memories = []
    total_bytes = 0
    projects_found = 0

    for project in projects:
        memory_text, stats = fetch_project_memory(project, cfg, max_tokens)
        if memory_text:
            all_memories.append(
                f"### vault-mem: {project}\n{memory_text}"
            )
            total_bytes += stats.get("output_bytes", 0)
            projects_found += 1

    if not all_memories:
        return context

    import sys

    print(
        f"[perseus] vault-mem: injected {total_bytes} bytes from "
        f"{projects_found}/{len(projects)} projects",
        file=sys.stderr,
    )

    section = "## Project Memory (via vault-mem)\n\n" + "\n\n---\n\n".join(all_memories)
    return context.rstrip() + "\n\n" + section + "\n"


def vaultmem_health() -> dict:
    """Quick health check for vault-mem integration."""
    binary = _vaultmem_binary()
    vault_path = os.environ.get(
        "VAULT_MEM_PATH", str(Path.home() / "vault-mem")
    )

    return {
        "available": binary is not None,
        "binary": binary,
        "vault_exists": os.path.isdir(vault_path),
        "vault_path": vault_path,
    }
