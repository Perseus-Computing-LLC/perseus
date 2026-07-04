"""Shared setup for the integrated Perseus -> Perseus Vault load harness.

These scripts exercise the *integrated* path — the Python `MnemeConnector`
talking to a real vault binary over MCP stdio — not the vault in isolation.
They are opt-in (not run in CI): they require a built `perseus-vault` binary and
spawn real subprocesses against temp databases.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# benchmark/harness/load/integrated_vault/_common.py -> repo root is 4 up.
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

import perseus  # noqa: E402  (the single-file built artifact at repo root)

MemoryTypeEnum = perseus.MemoryTypeEnum
MnemeConnector = perseus.MnemeConnector


def find_vault_binary(argv: list[str] | None = None) -> str:
    """Resolve the vault binary: explicit argv[1], then $PERSEUS_VAULT_BIN, then
    common local build/install locations. Raises if none is runnable."""
    argv = argv if argv is not None else sys.argv
    candidates: list[Path] = []
    for a in argv[1:]:
        if not a.startswith("-"):
            candidates.append(Path(a))
    env = os.environ.get("PERSEUS_VAULT_BIN")
    if env:
        candidates.append(Path(env))
    exe = "perseus-vault.exe" if os.name == "nt" else "perseus-vault"
    candidates += [
        REPO_ROOT.parent / "perseus-vault" / "target" / "release" / exe,
        Path.home() / "bin" / exe,
        REPO_ROOT / "perseus-vault" / "target" / "release" / exe,
    ]
    for c in candidates:
        if c and c.is_file():
            return str(c)
    raise SystemExit(
        "No perseus-vault binary found. Pass a path as argv[1], set "
        "$PERSEUS_VAULT_BIN, or build it (cargo build --release in perseus-vault)."
    )


def make_connector(vault_exe: str, db_path: Path, *, timeout_s: float = 30.0,
                   retry_attempts: int = 2, breaker_threshold: int = 50,
                   breaker_cooldown: int = 5) -> "perseus.MnemeConnector":
    cfg = {"perseus_vault": {
        "enabled": True,
        "transport": "stdio",
        "command": [vault_exe, "serve", "--db", str(db_path)],
        "timeout_s": timeout_s,
        "init_timeout_s": 60.0,
        "retry_policy": {"max_attempts": retry_attempts, "backoff_base": 1.2},
        "circuit_breaker": {"threshold": breaker_threshold, "cooldown": breaker_cooldown},
    }}
    return MnemeConnector(cfg)


def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]
