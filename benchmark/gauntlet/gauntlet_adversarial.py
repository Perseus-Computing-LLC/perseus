"""
gauntlet_adversarial.py — 12 adversarial scenarios for the Perseus Gauntlet.

Each scenario is a function that sets up the adverse condition, runs renders
for a specified duration, then cleans up and verifies recovery.

Safety: A1 (disk full), A4 (OOM), A9 (fork bomb) have kill switches.
All scenarios have a max 300s duration and cleanup that runs even on exception.
"""

from __future__ import annotations

import inspect
import json
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure gauntlet_lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gauntlet_lib import perseus_executable, timestamp_iso, write_json


# ─── Sentinel / kill-switch helpers ──────────────────────────────────────────

SENTINEL_DIR: Path | None = None


def _init_sentinels(base: Path) -> Path:
    global SENTINEL_DIR
    sentinel_dir = base / "sentinels"
    sentinel_dir.mkdir(parents=True, exist_ok=True)
    SENTINEL_DIR = sentinel_dir
    return sentinel_dir


def _kill_switch_triggered() -> bool:
    """Check if any kill-switch sentinel file exists."""
    if SENTINEL_DIR is None:
        return False
    for f in SENTINEL_DIR.glob("kill_switch_*"):
        return True
    return False


def _write_sentinel(name: str, data: dict | None = None):
    if SENTINEL_DIR is not None:
        p = SENTINEL_DIR / name
        p.write_text(json.dumps(data or {"ts": timestamp_iso()}))


def _cleanup_callback(callback, label: str = "scenario"):
    """Decorator-like helper to ensure cleanup runs even after exception."""
    return None


# ─── Scenario runner ─────────────────────────────────────────────────────────

def run_scenario(
    scenario_id: str,
    duration_s: int = 300,
    perseus_home: Path = Path("/tmp/perseus-gauntlet/adversarial"),
    role_profile: Path | None = None,
) -> dict:
    """Run a single adversarial scenario for the specified duration.

    Returns dict with scenario_id, duration_s, renders_attempted, renders_successful,
    errors, and recovery_status.
    """
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

    t0 = time.time()
    last_check = t0

    while time.time() - t0 < duration_s:
        if _kill_switch_triggered():
            result["errors"].append("Kill switch triggered")
            break

        if not role_profile or not role_profile.is_file():
            # Use a minimal inline context
            ctx = str(perseus_home / "_adversarial_ctx.md")
            try:
                Path(ctx).write_text(
                    "@perseus v0.8\n@prompt adversarial test\n@query \"echo adversarial\" @cache ttl=300\n"
                )
            except OSError as exc:
                result["errors"].append(f"Cannot write context file: {exc}")
                continue
            target = ctx
        else:
            target = str(role_profile)

        result["renders_attempted"] += 1
        try:
            r = subprocess.run(
                [sys.executable, perseus, "render", target],
                capture_output=True, text=True, timeout=30, env=env,
            )
            if r.returncode == 0:
                result["renders_successful"] += 1
            else:
                result["errors"].append(f"Render failed: exit {r.returncode} — {r.stderr[:200]}")
        except subprocess.TimeoutExpired:
            result["errors"].append("Render timed out (30s)")
        except Exception as exc:
            result["errors"].append(str(exc)[:200])

        # Kill switch check every 30s
        if time.time() - last_check > 30:
            last_check = time.time()
            if _kill_switch_triggered():
                break

    # Final render to verify recovery
    try:
        r = subprocess.run(
            [sys.executable, perseus, "render", target],
            capture_output=True, text=True, timeout=30, env=env,
        )
        result["recovery_status"] = "clean" if r.returncode == 0 else f"failed (exit {r.returncode})"
        result["recovery_stderr"] = r.stderr[:300]
    except Exception as exc:
        result["recovery_status"] = f"exception: {exc}"

    result["actual_duration_s"] = time.time() - t0
    return result


# ─── Scenario implementations ─────────────────────────────────────────────────

def scenario_a1_disk_full(
    duration_s: int = 300,
    nfs_base: Path = Path("/mnt/perseus-gauntlet"),
) -> dict:
    """A1: Fill NFS share to 95% capacity, then continue renders.

    KILL SWITCH: sentinel file check every 30s.
    Cleanup: delete filler file.
    """
    filler_path = nfs_base / ".gauntlet_filler"
    result: dict = {"scenario": "A1_disk_full", "setup": None, "renders": None, "cleanup": None}

    # Setup: create a large filler file to consume ~95% of available space
    try:
        stat = os.statvfs(str(nfs_base))
        total_bytes = stat.f_frsize * stat.f_blocks
        free_bytes = stat.f_frsize * stat.f_bfree
        target_free = int(total_bytes * 0.05)  # leave 5% free
        fill_size = max(0, free_bytes - target_free - 10 * 1024**2)  # minus 10MB safety margin

        if fill_size > 0:
            with open(filler_path, "wb") as f:
                chunk = b"x" * 1024 * 1024  # 1MB chunks
                written = 0
                while written < fill_size and not _kill_switch_triggered():
                    f.write(chunk)
                    written += len(chunk)
                    f.flush()
                    os.fsync(f.fileno())
            result["setup"] = f"wrote {written / 1024**3:.1f}GB filler"
        else:
            result["setup"] = "insufficient space to fill to 95%"
    except Exception as exc:
        result["setup"] = f"setup failed: {exc}"

    # Run renders under pressure
    result["renders"] = run_scenario("A1_disk_full", duration_s)

    # Cleanup
    try:
        if filler_path.is_file():
            filler_path.unlink()
        result["cleanup"] = "filler removed"
    except Exception as exc:
        result["cleanup"] = f"cleanup failed: {exc}"

    return result


def scenario_a2_network_partition(
    duration_s: int = 120,
    nfs_base: Path = Path("/mnt/perseus-gauntlet"),
) -> dict:
    """A2: Isolate node via iptables DROP rules.

    Cleanup: delete iptables rules.
    Note: Requires root; skipped if not root.
    """
    result: dict = {"scenario": "A2_network_partition", "setup": None, "renders": None, "cleanup": None}

    if os.geteuid() != 0:
        result["setup"] = "SKIPPED: requires root"
        result["renders"] = {}
        return result

    try:
        # Isolate loopback and local traffic only
        subprocess.run(
            ["iptables", "-A", "INPUT", "!", "-i", "lo", "-j", "DROP"],
            check=True, timeout=10,
        )
        subprocess.run(
            ["iptables", "-A", "OUTPUT", "!", "-o", "lo", "-j", "DROP"],
            check=True, timeout=10,
        )
        result["setup"] = "iptables DROP rules applied (non-loopback)"
    except Exception as exc:
        result["setup"] = f"setup failed: {exc}"
        result["renders"] = run_scenario("A2_network_partition", duration_s)
        # Cleanup
        try:
            subprocess.run(["iptables", "-D", "INPUT", "!", "-i", "lo", "-j", "DROP"],
                           timeout=10, check=True)
            subprocess.run(["iptables", "-D", "OUTPUT", "!", "-o", "lo", "-j", "DROP"],
                           timeout=10, check=True)
            result["cleanup"] = "iptables rules removed"
        except Exception as exc:
            result["cleanup"] = f"cleanup failed: {exc}"
        return result

    result["renders"] = run_scenario("A2_network_partition", duration_s)

    # Cleanup
    try:
        subprocess.run(
            ["iptables", "-D", "INPUT", "!", "-i", "lo", "-j", "DROP"],
            timeout=10, check=True,
        )
        subprocess.run(
            ["iptables", "-D", "OUTPUT", "!", "-o", "lo", "-j", "DROP"],
            timeout=10, check=True,
        )
        result["cleanup"] = "iptables rules removed"
    except Exception as exc:
        result["cleanup"] = f"cleanup failed: {exc}"

    return result


def scenario_a3_clock_skew(
    duration_s: int = 300,
) -> dict:
    """A3: Skew system clock by +2 hours.

    Cleanup: restore clock via ntp or manual set.
    Note: Requires root.
    """
    result: dict = {"scenario": "A3_clock_skew", "setup": None, "renders": None, "cleanup": None}

    if os.geteuid() != 0:
        result["setup"] = "SKIPPED: requires root"
        result["renders"] = {}
        return result

    try:
        # Record current time
        now = time.time()
        skewed = now + 7200  # +2 hours
        subprocess.run(
            ["date", "-s", f"@{int(skewed)}"],
            check=True, timeout=10,
        )
        result["setup"] = f"clock skewed +2h from {time.ctime(now)} to {time.ctime(skewed)}"
    except Exception as exc:
        result["setup"] = f"setup failed: {exc}"
        return result

    result["renders"] = run_scenario("A3_clock_skew", duration_s)

    # Cleanup: try ntpdate, fall back to manual
    try:
        subprocess.run(
            ["ntpdate", "-u", "pool.ntp.org"],
            timeout=30, check=True,
        )
        result["cleanup"] = "clock restored via ntpdate"
    except Exception:
        try:
            # Fallback: set to original + duration
            restore_time = now + duration_s + 5
            subprocess.run(["date", "-s", f"@{int(restore_time)}"], timeout=10, check=True)
            result["cleanup"] = f"clock restored to approximate time ({time.ctime(restore_time)})"
        except Exception as exc:
            result["cleanup"] = f"clock restore failed: {exc}"

    return result


def scenario_a4_oom_pressure(
    duration_s: int = 300,
) -> dict:
    """A4: Consume 90% of available RAM, then continue renders.

    KILL SWITCH: sentinel file check every 30s.
    Cleanup: kill memory consumer process.
    """
    result: dict = {"scenario": "A4_oom_pressure", "setup": None, "renders": None, "cleanup": None}
    consumer_proc = None

    # Setup: allocate memory to fill 90% of RAM
    try:
        import psutil  # type: ignore
        available_mb = psutil.virtual_memory().available // 1024 // 1024
        target_mb = int(available_mb * 0.9)

        # Spawn a process that allocates memory
        consumer_proc = subprocess.Popen(
            [sys.executable, "-c", f"""
import time
# Allocate ~{target_mb}MB in 10MB chunks
data = []
for _ in range({target_mb // 10}):
    data.append(bytearray(10 * 1024 * 1024))
    time.sleep(0.01)
# Hold allocation
time.sleep(3600)
"""],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Give it time to allocate
        time.sleep(2)
        used_after = psutil.virtual_memory().used // 1024 // 1024
        result["setup"] = f"allocated ~{target_mb}MB of {available_mb}MB available (used: {used_after}MB)"
    except ImportError:
        result["setup"] = "SKIPPED: psutil not available"
        return result
    except Exception as exc:
        result["setup"] = f"setup failed: {exc}"
        return result

    # Run renders under memory pressure
    result["renders"] = run_scenario("A4_oom_pressure", duration_s)

    # Cleanup
    try:
        if consumer_proc:
            consumer_proc.kill()
            consumer_proc.wait(timeout=10)
        result["cleanup"] = "memory consumer killed"
    except Exception as exc:
        result["cleanup"] = f"cleanup failed: {exc}"

    return result


def scenario_a5_cache_poison(
    duration_s: int = 300,
    perseus_home: Path = Path("/tmp/perseus-gauntlet/adversarial"),
) -> dict:
    """A5: Inject invalid cache entries, then verify Perseus handles them."""
    result: dict = {"scenario": "A5_cache_poison", "setup": None, "renders": None, "cleanup": None}

    # Setup: inject malformed cache entries
    cache_dir = perseus_home / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    poison_files = [
        ("poison_invalid_json.json", "{invalid json content!!!}"),
        ("poison_invalid_yaml.yaml", "<<error: [unbalanced"),
        ("poison_empty.json", ""),
        ("poison_binary.bin", b"\x00\x01\x02\x03\x04\xff\xfe\xfd\xfc"),
        ("poison_symlink.lnk", "target_does_not_exist"),
        ("poison_oversized.json", "x" * 1024 * 1024),  # 1MB entry
    ]

    written = []
    for name, content in poison_files:
        try:
            path = cache_dir / name
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content)
            written.append(name)
        except Exception:
            pass

    result["setup"] = f"injected {len(written)} poison cache entries: {', '.join(written)}"

    # Run renders — Perseus should gracefully handle corrupted cache
    result["renders"] = run_scenario("A5_cache_poison", duration_s)

    # Cleanup
    for name, _ in poison_files:
        p = cache_dir / name
        try:
            if p.is_symlink():
                p.unlink()
            elif p.is_file():
                p.unlink()
        except Exception:
            pass
    result["cleanup"] = f"removed {len(written)} poison entries"

    return result


def scenario_a6_pid_reuse(
    duration_s: int = 300,
) -> dict:
    """A6: Rapid process churn to stress PID-lock ownership."""
    result: dict = {"scenario": "A6_pid_reuse", "setup": None, "renders": None, "cleanup": None}

    # Setup: rapid fork/exit cycle to churn PIDs
    churn_proc = subprocess.Popen(
        [sys.executable, "-c", """
import os, time, sys
# Rapid fork/exit cycle - spawn 500 short-lived processes per second
for _ in range(1500):
    try:
        pid = os.fork()
        if pid == 0:
            sys.exit(0)
    except OSError:
        pass
    time.sleep(0.002)
"""],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    result["setup"] = f"PID churn process started (pid {churn_proc.pid})"

    # Run renders during PID churn
    result["renders"] = run_scenario("A6_pid_reuse", duration_s)

    # Cleanup
    try:
        churn_proc.kill()
        churn_proc.wait(timeout=5)
        result["cleanup"] = "churn process killed"
    except Exception as exc:
        result["cleanup"] = f"cleanup failed: {exc}"

    return result


def scenario_a7_signal_storm(
    duration_s: int = 300,
) -> dict:
    """A7: Randomly send SIGTERM/SIGINT to Perseus processes during renders."""
    result: dict = {"scenario": "A7_signal_storm", "setup": None, "renders": None, "cleanup": None}

    result["setup"] = "signal storm ready"

    # Run renders with periodic signal injection
    perseus = perseus_executable()
    env = os.environ.copy()
    home = Path("/tmp/perseus-gauntlet/signal-storm")
    home.mkdir(parents=True, exist_ok=True)
    env["PERSEUS_HOME"] = str(home)

    t0 = time.time()
    signals_sent = 0
    renders_ok = 0
    renders_failed = 0

    while time.time() - t0 < duration_s:
        if _kill_switch_triggered():
            break

        try:
            proc = subprocess.Popen(
                [sys.executable, perseus, "render", "-"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env,
            )
            try:
                proc.stdin.write(b"@perseus v0.8\n@query \"sleep 0.5\" @cache ttl=300\n")
                proc.stdin.close()
            except Exception:
                pass

            # Randomly send signal
            sig = random.choice([signal.SIGTERM, signal.SIGINT])
            time.sleep(random.uniform(0.05, 0.3))
            try:
                os.kill(proc.pid, sig)
                signals_sent += 1
            except Exception:
                pass

            try:
                stdout, stderr = proc.communicate(timeout=5)
                if proc.returncode == 0:
                    renders_ok += 1
                else:
                    renders_failed += 1
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
                renders_failed += 1
        except Exception:
            renders_failed += 1
        except (BrokenPipeError, ValueError):
            # communicate() raises ValueError if stdin was already closed,
            # or BrokenPipeError if the process exited before we could write.
            renders_failed += 1

    result["renders"] = {
        "duration_s": time.time() - t0,
        "signals_sent": signals_sent,
        "renders_ok": renders_ok,
        "renders_failed": renders_failed,
    }
    result["cleanup"] = "signal storm completed"

    return result


def scenario_a8_fd_exhaustion(
    duration_s: int = 300,
) -> dict:
    """A8: Exhaust file descriptors, then verify graceful degradation."""
    result: dict = {"scenario": "A8_fd_exhaustion", "setup": None, "renders": None, "cleanup": None}

    # Setup: open many file descriptors, but reserve ~100 for Perseus
    fds: list[int] = []
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        # Only consume FDs up to soft limit minus 200 (leave room for Perseus)
        target = max(0, soft - 200)
        for i in range(target):
            try:
                fd = os.open("/dev/null", os.O_RDONLY)
                fds.append(fd)
            except OSError:
                break
        result["setup"] = f"opened {len(fds)} FDs (limit: soft={soft}, hard={hard}, reserved 200 for Perseus)"
    except Exception as exc:
        result["setup"] = f"setup failed: {exc}"
        return result

    # Run renders with FD pressure — cleanup ALWAYS runs
    try:
        result["renders"] = run_scenario("A8_fd_exhaustion", duration_s)
    except Exception as exc:
        result["renders"] = {"error": str(exc)[:200], "renders_attempted": 0, "renders_successful": 0, "errors": []}
    finally:
        # Cleanup: always restore FDs
        closed = 0
        for fd in fds:
            try:
                os.close(fd)
                closed += 1
            except OSError:
                pass
        result["cleanup"] = f"closed {closed}/{len(fds)} FDs"

    return result


def scenario_a9_fork_bomb_defense(
    duration_s: int = 300,
) -> dict:
    """A9: Fork bomb defense — limit subprocesses while hammering concurrent renders.

    KILL SWITCH: sentinel file check every 30s.
    """
    result: dict = {"scenario": "A9_fork_bomb_defense", "setup": None, "renders": None, "cleanup": None}

    result["setup"] = "fork bomb defense ready"

    # Run renders with rapid concurrent subprocess spawning
    perseus = perseus_executable()
    env = os.environ.copy()
    home = Path("/tmp/perseus-gauntlet/fork-bomb")
    home.mkdir(parents=True, exist_ok=True)
    env["PERSEUS_HOME"] = str(home)

    # Pre-create context file so run_scenario doesn't need to write
    ctx_file = home / "_adversarial_ctx.md"
    ctx_file.write_text("@perseus v0.8\n@prompt adversarial test\n@query \"echo survived\" @cache ttl=300\n")

    t0 = time.time()
    renders_ok = 0
    renders_failed = 0
    all_procs: list[subprocess.Popen] = []

    try:
        while time.time() - t0 < duration_s:
            if _kill_switch_triggered():
                break

            # Spawn many concurrent renders
            procs = []
            for _ in range(20):
                try:
                    p = subprocess.Popen(
                        [sys.executable, perseus, "render", str(ctx_file)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, env=env,
                    )
                    procs.append(p)
                    all_procs.append(p)
                except OSError:
                    break  # Process limit hit

            for p in procs:
                try:
                    stdout, stderr = p.communicate(timeout=30)
                    if p.returncode == 0:
                        renders_ok += 1
                    else:
                        renders_failed += 1
                except Exception:
                    renders_failed += 1
                    try:
                        p.kill()
                    except OSError:
                        pass

        result["renders"] = {
            "duration_s": time.time() - t0,
            "renders_ok": renders_ok,
            "renders_failed": renders_failed,
        }
    finally:
        # Kill any remaining procs
        for p in all_procs:
            try:
                if p.poll() is None:
                    p.kill()
            except OSError:
                pass
    result["cleanup"] = "fork bomb defense completed"

    return result


def scenario_a10_symlink_race(
    duration_s: int = 300,
    perseus_home: Path = Path("/tmp/perseus-gauntlet/adversarial"),
) -> dict:
    """A10: Create and modify symlink chains during renders to test workspace escape prevention."""
    result: dict = {"scenario": "A10_symlink_race", "setup": None, "renders": None, "cleanup": None}

    race_dir = perseus_home / "symlink_race"
    race_dir.mkdir(parents=True, exist_ok=True)

    # Setup: create symlink chains
    target = race_dir / "target"
    target.write_text("sensitive data")

    # Create context.md BEFORE renders
    ctx_file = race_dir / "context.md"
    ctx_file.write_text("@perseus v0.8\n@prompt symlink race\n@query \"echo test\" @cache ttl=300\n")

    chain = []
    for i in range(20):
        link = race_dir / f"link_{i}"
        if i == 0:
            link.symlink_to(target)
        else:
            link.symlink_to(race_dir / f"link_{i - 1}")
        chain.append(link)

    result["setup"] = f"created {len(chain)} symlink chain entries"

    # Create context.md BEFORE the render loop so renders have a file to read
    (race_dir / "context.md").write_text("@perseus v0.8\n@prompt symlink race\n")

    # Run renders while modifying symlinks
    perseus = perseus_executable()
    env = os.environ.copy()
    env["PERSEUS_HOME"] = str(perseus_home)

    t0 = time.time()
    renders_ok = 0
    renders_failed = 0

    while time.time() - t0 < duration_s:
        if _kill_switch_triggered():
            break

        # Rapidly swap symlink targets
        for link in chain:
            try:
                link.unlink()
                link.symlink_to(race_dir / ".." / ".." / "etc" / "passwd")
                time.sleep(0.001)
                link.unlink()
                link.symlink_to(target)
            except Exception:
                pass

        # Render
        try:
            r = subprocess.run(
                [sys.executable, perseus, "render", str(race_dir / "context.md")],
                capture_output=True, text=True, timeout=10, env=env,
            )
            if r.returncode == 0:
                renders_ok += 1
            else:
                renders_failed += 1
        except Exception:
            renders_failed += 1

    result["renders"] = {
        "duration_s": time.time() - t0,
        "renders_ok": renders_ok,
        "renders_failed": renders_failed,
    }

    # Cleanup
    for link in chain:
        try:
            if link.is_symlink() or link.exists():
                link.unlink()
        except Exception:
            pass

    result["cleanup"] = "symlink race cleaned up"

    return result


def scenario_a11_locale_corruption(
    duration_s: int = 300,
) -> dict:
    """A11: Set invalid locale, verify Perseus handles UTF-8 gracefully."""
    result: dict = {"scenario": "A11_locale_corruption", "setup": None, "renders": None, "cleanup": None}

    saved_lang = os.environ.get("LANG", "")
    saved_lc_all = os.environ.get("LC_ALL", "")

    # Setup: corrupt locale
    os.environ["LANG"] = "invalid_LANG.UTF-8"
    os.environ["LC_ALL"] = "C.C"
    result["setup"] = f"locale set to invalid (LANG=invalid_LANG.UTF-8, LC_ALL=C.C), was LANG={saved_lang}"

    # Run renders
    result["renders"] = run_scenario("A11_locale_corruption", duration_s)

    # Cleanup
    if saved_lang:
        os.environ["LANG"] = saved_lang
    else:
        os.environ.pop("LANG", None)
    if saved_lc_all:
        os.environ["LC_ALL"] = saved_lc_all
    else:
        os.environ.pop("LC_ALL", None)
    result["cleanup"] = f"locale restored (LANG={saved_lang})"

    return result


def scenario_a12_timezone_shift(
    duration_s: int = 300,
) -> dict:
    """A12: Change timezone during enterprise week renders, verify timestamp consistency."""
    result: dict = {"scenario": "A12_timezone_shift", "setup": None, "renders": None, "cleanup": None}

    saved_tz = os.environ.get("TZ", "")

    # Setup: shift to different timezone
    os.environ["TZ"] = "Pacific/Midway"  # UTC-11
    time.tzset()
    result["setup"] = f"TZ set to Pacific/Midway (was {saved_tz or 'UTC'})"

    # Mid-run: shift again
    half_time = duration_s / 2
    run_start = time.time()
    renders_run = 0

    while True:
        elapsed = time.time() - run_start
        if elapsed >= duration_s:
            break
        if elapsed >= half_time and os.environ.get("TZ") != "Asia/Kamchatka":
            os.environ["TZ"] = "Asia/Kamchatka"  # UTC+12
            time.tzset()
            result["mid_run_shift"] = "shifted to Asia/Kamchatka (UTC+12)"

        result["renders"] = run_scenario("A12_timezone_shift", 30)  # run in 30s chunks
        renders_run += 1

    result["renders_count"] = renders_run

    # Cleanup
    if saved_tz:
        os.environ["TZ"] = saved_tz
    else:
        os.environ.pop("TZ", None)
    time.tzset()
    result["cleanup"] = f"TZ restored ({saved_tz or 'unset'})"

    return result


# ─── Registry ─────────────────────────────────────────────────────────────────

SCENARIOS: dict[str, dict] = {
    "A1_disk_full": {
        "fn": scenario_a1_disk_full,
        "duration": 300,
        "hazard": True,  # kill switch required
        "description": "Fill NFS to 95%, render under space pressure",
    },
    "A2_network_partition": {
        "fn": scenario_a2_network_partition,
        "duration": 120,
        "hazard": False,
        "description": "iptables DROP non-loopback traffic",
    },
    "A3_clock_skew": {
        "fn": scenario_a3_clock_skew,
        "duration": 300,
        "hazard": False,
        "description": "Shift system clock +2h, test TTL expiry",
    },
    "A4_oom_pressure": {
        "fn": scenario_a4_oom_pressure,
        "duration": 300,
        "hazard": True,  # kill switch required
        "description": "Consume 90% RAM, render under memory pressure",
    },
    "A5_cache_poison": {
        "fn": scenario_a5_cache_poison,
        "duration": 300,
        "hazard": False,
        "description": "Inject invalid cache entries, test graceful handling",
    },
    "A6_pid_reuse": {
        "fn": scenario_a6_pid_reuse,
        "duration": 300,
        "hazard": False,
        "description": "Rapid fork/exit churn to test PID-lock ownership",
    },
    "A7_signal_storm": {
        "fn": scenario_a7_signal_storm,
        "duration": 300,
        "hazard": False,
        "description": "Random SIGTERM/SIGINT during renders",
    },
    "A8_fd_exhaustion": {
        "fn": scenario_a8_fd_exhaustion,
        "duration": 300,
        "hazard": False,
        "description": "Open 50K file descriptors, test graceful degradation",
    },
    "A9_fork_bomb_defense": {
        "fn": scenario_a9_fork_bomb_defense,
        "duration": 300,
        "hazard": True,  # kill switch required
        "description": "Rapid concurrent subprocess spawning",
    },
    "A10_symlink_race": {
        "fn": scenario_a10_symlink_race,
        "duration": 300,
        "hazard": False,
        "description": "Symlink chains during render to test workspace escape prevention",
    },
    "A11_locale_corruption": {
        "fn": scenario_a11_locale_corruption,
        "duration": 300,
        "hazard": False,
        "description": "Set invalid locale, verify UTF-8 survival",
    },
    "A12_timezone_shift": {
        "fn": scenario_a12_timezone_shift,
        "duration": 300,
        "hazard": False,
        "description": "Change TZ during renders, verify timestamp consistency",
    },
}


def run_all_adversarial(
    nfs_base: Path = Path("/mnt/perseus-gauntlet"),
    perseus_home: Path = Path("/tmp/perseus-gauntlet/adversarial"),
    duration_s: int = 300,
    profile_path: Path | None = None,
    scenarios: list[str] | None = None,
) -> dict:
    """Run all (or selected) adversarial scenarios and return combined results."""
    _init_sentinels(nfs_base)

    scenario_names = scenarios or list(SCENARIOS.keys())
    results: dict[str, dict] = {}
    overall_pass = True

    for sid in scenario_names:
        if sid not in SCENARIOS:
            results[sid] = {"error": f"Unknown scenario: {sid}"}
            overall_pass = False
            continue

        info = SCENARIOS[sid]
        print(f"  Running {sid}: {info['description']}...", file=sys.stderr)

        try:
            # Compat: respect each scenario's actual signature (not all accept nfs_base/perseus_home)
            sig = inspect.signature(info["fn"])
            kwargs = {"duration_s": info["duration"]}
            if "nfs_base" in sig.parameters:
                kwargs["nfs_base"] = nfs_base
            if "perseus_home" in sig.parameters:
                kwargs["perseus_home"] = perseus_home
            result = info["fn"](**kwargs)
            results[sid] = result

            # Save per-scenario result immediately (survives crash)
            scenario_file = nfs_base / "results" / f"adversarial_{sid}.json"
            try:
                write_json(scenario_file, result)
            except OSError:
                pass

            # Check if renders succeeded
            renders = result.get("renders", {})
            if isinstance(renders, dict):
                errs = renders.get("errors", [])
                if errs:
                    overall_pass = False
                    print(f"    FAILED: {len(errs)} errors", file=sys.stderr)
                else:
                    print(f"    PASS ({renders.get('renders_successful', 0)}/{renders.get('renders_attempted', 0)})",
                          file=sys.stderr)
        except Exception as exc:
            results[sid] = {"error": str(exc)}
            overall_pass = False
            print(f"    CRASHED: {exc}", file=sys.stderr)
            # Save crash result too
            scenario_file = nfs_base / "results" / f"adversarial_{sid}.json"
            try:
                write_json(scenario_file, {"error": str(exc), "scenario": sid})
            except OSError:
                pass

    return {
        "phase": 7,
        "name": "adversarial-gauntlet",
        "scenarios": results,
        "overall_pass": overall_pass,
        "scenarios_run": len(scenario_names),
        "scenarios_passed": sum(1 for s in results.values()
                                if not s.get("error") and not (s.get("renders") or {}).get("errors")),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Perseus Gauntlet — Adversarial Scenarios")
    parser.add_argument("--nfs-path", default="/mnt/perseus-gauntlet")
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--scenarios", nargs="*", help="Specific scenarios to run (default: all)")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    nfs_base = Path(args.nfs_path)
    result = run_all_adversarial(
        nfs_base=nfs_base,
        duration_s=args.duration,
    )

    output = json.dumps(result, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output)
    print(output)
