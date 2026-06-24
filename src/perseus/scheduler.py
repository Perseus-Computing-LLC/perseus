# ─────────────────────────────── Scheduler ────────────────────────────────────
# Cross-platform scheduling commands: launchd (macOS), cron (POSIX), systemd (Linux)

LAUNCHD_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{program_arguments}
    </array>
    <key>WorkingDirectory</key>
    <string>{workdir}</string>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
  </dict>
</plist>
"""


def _perseus_launcher() -> tuple[list[str], bool]:
    """Resolve a version-stable way to invoke ``perseus`` from a scheduled job.

    Scheduled jobs (launchd/cron/systemd) persist for months across Perseus
    upgrades. Baking in the versioned interpreter path (``sys.executable``) or
    the versioned site-packages script (``__file__``) means a Python
    minor-version bump (e.g. 3.13 → 3.14) silently strands the job on the old
    binary — pip installs the new console script under a new path while the
    plist keeps calling the old one, with ``LastExitStatus = 0`` and no error
    (#430).

    Prefer a stable console-script launcher that always resolves to the current
    install, in order:

      1. ``~/.local/bin/perseus`` — the stable user symlink that survives
         Python minor-version bumps (recommended in the install docs).
      2. ``perseus`` on ``PATH`` — the pip console script.
      3. ``{sys.executable} {__file__}`` — last-resort, version-specific
         fallback (matches legacy behaviour).

    Returns ``(argv_tokens, is_stable)`` where ``is_stable`` is ``False`` only
    for the version-specific fallback so callers can warn.
    """
    import shutil as _shutil

    local_bin = Path.home() / ".local" / "bin" / "perseus"
    try:
        if local_bin.exists():
            return [str(local_bin)], True
    except OSError:
        pass

    # shutil.which can raise on some platforms (e.g. its win32 branch touches
    # _winapi, which is absent off-Windows) — degrade to the fallback instead
    # of crashing the scheduler command.
    try:
        which = _shutil.which("perseus")
    except Exception:
        which = None
    if which:
        return [which], True

    # Fallback: version-specific interpreter + script (may go stale on upgrade).
    return [str(Path(sys.executable).resolve()), str(Path(__file__).resolve())], False


def cmd_launchd(args, cfg):
    if sys.platform != "darwin":
        print("Error: `perseus launchd` is only supported on macOS.", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    logs_dir = PERSEUS_HOME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    label = args.label or f"com.perseus.render.{source_path.stem}"
    plist_path = launch_agents / f"{label}.plist"
    launcher, stable = _perseus_launcher()
    workdir = _infer_workspace(source_path)
    stdout_log = logs_dir / f"{label}.out.log"
    stderr_log = logs_dir / f"{label}.err.log"

    # Build the ProgramArguments <string> list from a version-stable launcher
    # so a Python minor-version upgrade does not strand the job (#430).
    prog_tokens = launcher + ["render", str(source_path), "--output", str(output_path)]
    program_arguments = "\n".join(f"      <string>{tok}</string>" for tok in prog_tokens)

    content = LAUNCHD_TEMPLATE.format(
        label=label,
        program_arguments=program_arguments,
        workdir=str(workdir),
        interval=int(args.interval),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )

    if plist_path.exists() and not args.force:
        print(f"Error: {plist_path} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    plist_path.write_text(content)

    print(f"✔ Wrote LaunchAgent plist: {plist_path}")
    print(f"  Launcher: {' '.join(launcher)}")
    if not stable:
        print("  ⚠ Could not find a stable `perseus` launcher (~/.local/bin/perseus or on PATH);")
        print("    falling back to a version-specific path that may go stale after a Python upgrade.")
        print("    Install the console script (`pipx install perseus-ctx` or ensure ~/.local/bin is on PATH).")
    print()
    print("Next steps:")
    print(f"  1. Load it:    launchctl load {plist_path}")
    print(f"  2. Start now:  launchctl start {label}")
    print(f"  3. Check logs: tail -f {stdout_log} {stderr_log}")


# ─────────────────────────────── cron (POSIX) ────────────────────────────────

def cmd_cron(args, cfg):
    """Generate a crontab entry for periodic rendering.

    POSIX-oriented: works on systems with crontab (macOS, Linux, BSD).
    Recommended over launchd/systemd when portability matters.
    """
    try:
        every = int(args.every)
    except (TypeError, ValueError):
        print(f"Error: --every must be an integer (got {args.every!r})", file=sys.stderr)
        sys.exit(1)
    if every <= 0:
        print("Error: --every must be > 0", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    launcher, stable = _perseus_launcher()

    # Build crontab schedule expression
    if every == 1:
        schedule = "* * * * *"
    elif every < 60:
        schedule = f"*/{every} * * * *"
    elif every == 60:
        schedule = "0 * * * *"
    else:
        hours = every // 60
        schedule = f"0 */{hours} * * *"

    cmd = f"{' '.join(launcher)} render {source_path} --output {output_path}"
    # Suppress crontab MAILTO noise; route stderr to /dev/null on success render
    entry = f"{schedule} {cmd} >/dev/null 2>&1  # perseus-render"
    if not stable:
        print("# ⚠ Could not find a stable `perseus` launcher (~/.local/bin/perseus or on PATH);")
        print("#   the entry below uses a version-specific path that may go stale after a Python upgrade.")

    if args.install:
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, check=False,
            )
            current = existing.stdout if existing.returncode == 0 else ""
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH. Install cron first.", file=sys.stderr)
            sys.exit(1)

        if "# perseus-render" in current:
            print("> ⚠ A perseus-render entry already exists in crontab. Remove it first or edit by hand.")
            print(current)
            sys.exit(1)

        new_crontab = current.rstrip() + ("\n" if current.strip() else "") + entry + "\n"
        try:
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True,
                                  capture_output=True, check=False)
            if proc.returncode != 0:
                print(f"Error: `crontab -` failed: {proc.stderr.strip()}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH.", file=sys.stderr)
            sys.exit(1)
        print("✔ Installed crontab entry:")
        print(f"  {entry}")
        print()
        print("Verify with: crontab -l")
        print("Remove with: crontab -e  (delete the line tagged `# perseus-render`)")
        return

    # Default: print the entry
    print("# Add this line to your crontab (run `crontab -e`):")
    print(entry)
    print()
    print("Or install automatically with: perseus cron ... --install")


# ─────────────────────────────── systemd (Linux) ─────────────────────────────

SYSTEMD_SERVICE_TEMPLATE = """\
[Unit]
Description=Perseus context renderer
After=default.target

[Service]
Type=oneshot
ExecStart={exec_start}
"""

SYSTEMD_TIMER_TEMPLATE = """\
[Unit]
Description=Perseus context render timer

[Timer]
OnBootSec=1min
OnUnitActiveSec={interval}
Unit=perseus-render.service

[Install]
WantedBy=timers.target
"""


def _parse_systemd_interval(raw: str) -> str:
    """Accept '5m', '2h', or systemd-native like '30s'/'1h30min' — return systemd time spec.

    Defaults to '5min' if empty. Raises ValueError on garbage.
    """
    s = (raw or "").strip().lower()
    if not s:
        return "5min"
    m = re.fullmatch(r"(\d+)\s*([smh])", s)
    if m:
        n, unit = m.group(1), m.group(2)
        return {"s": f"{n}s", "m": f"{n}min", "h": f"{n}h"}[unit]
    # passthrough for already-systemd-native values
    if re.fullmatch(r"[\d\s a-z]+", s):
        return s
    raise ValueError(f"unrecognised interval: {raw!r}")


def cmd_systemd(args, cfg):
    """Scaffold ~/.config/systemd/user/perseus-render.{service,timer} units."""
    if sys.platform == "darwin":
        print("Use `perseus launchd` on macOS.", file=sys.stderr)
        sys.exit(1)
    if sys.platform != "linux":
        suffix = " Native Windows Task Scheduler support is deferred." if sys.platform == "win32" else ""
        print(f"Error: `perseus systemd` is only supported on Linux.{suffix}", file=sys.stderr)
        sys.exit(1)

    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    try:
        interval = _parse_systemd_interval(getattr(args, "interval", "5m") or "5m")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    launcher, stable = _perseus_launcher()
    exec_start = f"{' '.join(launcher)} render {source_path} --output {output_path}"

    service_content = SYSTEMD_SERVICE_TEMPLATE.format(exec_start=exec_start)
    timer_content = SYSTEMD_TIMER_TEMPLATE.format(interval=interval)
    if not stable:
        print("# ⚠ Could not find a stable `perseus` launcher (~/.local/bin/perseus or on PATH);", file=sys.stderr)
        print("#   ExecStart uses a version-specific path that may go stale after a Python upgrade.", file=sys.stderr)

    if getattr(args, "install", False):
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service_path = unit_dir / "perseus-render.service"
        timer_path = unit_dir / "perseus-render.timer"
        service_path.write_text(service_content)
        timer_path.write_text(timer_content)
        print(f"✔ Wrote {service_path}")
        print(f"✔ Wrote {timer_path}")
        print()
        print("Next steps:")
        print("  systemctl --user daemon-reload")
        print("  systemctl --user enable perseus-render.timer")
        print("  systemctl --user start perseus-render.timer")
        if getattr(args, "enable", False):
            for cmd in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "perseus-render.timer"],
                ["systemctl", "--user", "start", "perseus-render.timer"],
            ):
                try:
                    subprocess.run(cmd, check=False)
                except Exception as exc:
                    print(f"> ⚠ {' '.join(cmd)} failed: {exc}")
        return

    # Default: print both unit files to stdout, separated
    print("# ~/.config/systemd/user/perseus-render.service")
    print(service_content)
    print("# ~/.config/systemd/user/perseus-render.timer")
    print(timer_content)


def cmd_launchd_uninstall(args, cfg):
    """Remove a Perseus LaunchAgent plist."""
    if sys.platform != "darwin":
        print("Error: `perseus launchd` is only supported on macOS.", file=sys.stderr)
        sys.exit(1)
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    label = args.label
    plist_path = launch_agents / f"{label}.plist"
    if not plist_path.exists():
        print(f"Error: {plist_path} does not exist.", file=sys.stderr)
        sys.exit(1)
    # Unload first if loaded
    import subprocess as _sp
    _sp.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    plist_path.unlink()
    print(f"✔ Removed LaunchAgent: {plist_path}")


def cmd_cron_uninstall(args, cfg):
    """Remove the Perseus crontab entry."""
    import subprocess as _sp
    try:
        result = _sp.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            print("No crontab found.")
            return
        lines = result.stdout.split("\n")
        source = Path(args.source).expanduser().resolve()
        marker = f"perseus render {source}"
        filtered = [l for l in lines if marker not in l]
        if len(filtered) == len(lines):
            print("No matching crontab entry found.")
            return
        _sp.run(["crontab", "-"], input="\n".join(filtered) + "\n", text=True)
        print(f"✔ Removed crontab entry for {source}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_systemd_uninstall(args, cfg):
    """Remove a user-space systemd timer and service unit."""
    if sys.platform == "darwin" or sys.platform == "win32":
        print("Error: `perseus systemd` is only supported on Linux.", file=sys.stderr)
        sys.exit(1)
    source_path = Path(args.source).expanduser().resolve()
    label = f"perseus-render-{source_path.stem}"
    user_units = Path.home() / ".config" / "systemd" / "user"
    timer_path = user_units / f"{label}.timer"
    service_path = user_units / f"{label}.service"
    import subprocess as _sp
    for p in [timer_path, service_path]:
        if p.exists():
            p.unlink()
            print(f"✔ Removed: {p}")
    _sp.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("Run: systemctl --user stop {label}.timer  # if still running")
