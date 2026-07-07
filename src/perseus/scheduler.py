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


def _resolve_job(args, cfg):
    """#693: resolve the scheduled job into (cli_tokens, tag, label_stem).

    ``render`` (the default, and the only job before #693) needs a source and
    an output path; ``maintain`` is the hands-off memory hygiene pass
    (``perseus vault maintain``) and takes neither. The tag is the marker the
    installers use for dedup/uninstall (``# perseus-render`` stays byte-
    identical so existing installed entries keep matching).
    """
    job = getattr(args, "job", "render") or "render"
    if job == "maintain":
        tokens = ["vault", "maintain"]
        hygiene = (cfg or {}).get("hygiene", {}) if isinstance(cfg, dict) else {}
        # A report-only rollout (hygiene.dry_run: true) bakes --dry-run into
        # the scheduled entry; flip the config and reinstall to go live.
        if hygiene.get("dry_run"):
            tokens.append("--dry-run")
        return tokens, "perseus-hygiene", "hygiene"
    if job != "render":
        print(f"Error: unknown --job {job!r} (expected: render, maintain)", file=sys.stderr)
        sys.exit(1)
    if not getattr(args, "source", None) or not getattr(args, "output", None):
        print("Error: --job render requires a source file and --output.", file=sys.stderr)
        sys.exit(1)
    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    tokens = ["render", str(source_path), "--output", str(output_path)]
    return tokens, "perseus-render", source_path.stem


def _hygiene_schedule_minutes(cfg) -> int:
    """#693: scheduled-maintain cadence from the hygiene config (default nightly)."""
    hygiene = (cfg or {}).get("hygiene", {}) if isinstance(cfg, dict) else {}
    try:
        minutes = int(hygiene.get("schedule_minutes", 1440))
    except (TypeError, ValueError):
        minutes = 1440
    return minutes if minutes > 0 else 1440


def cmd_launchd(args, cfg):
    if sys.platform != "darwin":
        print("Error: `perseus launchd` is only supported on macOS.", file=sys.stderr)
        sys.exit(1)

    job_tokens, _tag, label_stem = _resolve_job(args, cfg)
    is_render = job_tokens[0] == "render"
    if is_render:
        source_path = Path(args.source).expanduser().resolve()
        if not source_path.exists():
            print(f"Error: file not found: {source_path}", file=sys.stderr)
            sys.exit(1)
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        workdir = _infer_workspace(source_path)
        default_label = f"com.perseus.render.{source_path.stem}"
        interval = int(args.interval)
    else:
        # maintain: no source/output; run from HOME; default cadence comes
        # from hygiene.schedule_minutes unless --interval was given explicitly.
        workdir = Path.home()
        default_label = "com.perseus.hygiene"
        interval = int(args.interval) if args.interval != 300 else _hygiene_schedule_minutes(cfg) * 60

    launch_agents = Path.home() / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True, exist_ok=True)

    logs_dir = PERSEUS_HOME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    label = args.label or default_label
    plist_path = launch_agents / f"{label}.plist"
    launcher, stable = _perseus_launcher()
    stdout_log = logs_dir / f"{label}.out.log"
    stderr_log = logs_dir / f"{label}.err.log"

    # Build the ProgramArguments <string> list from a version-stable launcher
    # so a Python minor-version upgrade does not strand the job (#430).
    prog_tokens = launcher + job_tokens
    program_arguments = "\n".join(f"      <string>{tok}</string>" for tok in prog_tokens)

    content = LAUNCHD_TEMPLATE.format(
        label=label,
        program_arguments=program_arguments,
        workdir=str(workdir),
        interval=interval,
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
    )

    if plist_path.exists() and not args.force:
        print(f"Error: {plist_path} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    plist_path.write_text(content, encoding="utf-8")

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
    """Generate a crontab entry for a scheduled Perseus job.

    POSIX-oriented: works on systems with crontab (macOS, Linux, BSD).
    Recommended over launchd/systemd when portability matters.
    #693: ``--job render`` (default; byte-identical to the pre-#693 entry)
    or ``--job maintain`` (hands-off memory hygiene).
    """
    job_tokens, tag, _stem = _resolve_job(args, cfg)
    is_maintain = tag == "perseus-hygiene"

    raw_every = getattr(args, "every", None)
    if raw_every is None:
        # Defaults are job-aware: renders poll (5 min), hygiene runs on the
        # configured cadence (hygiene.schedule_minutes, nightly).
        raw_every = _hygiene_schedule_minutes(cfg) if is_maintain else 5
    try:
        every = int(raw_every)
    except (TypeError, ValueError):
        print(f"Error: --every must be an integer (got {raw_every!r})", file=sys.stderr)
        sys.exit(1)
    if every <= 0:
        print("Error: --every must be > 0", file=sys.stderr)
        sys.exit(1)

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

    cmd = " ".join(launcher + job_tokens)
    # Suppress crontab MAILTO noise; route stderr to /dev/null on success
    entries = [f"{schedule} {cmd} >/dev/null 2>&1  # {tag}"]
    if is_maintain:
        # Companion weekly VACUUM (hygiene.vacuum_every_runs at the nightly
        # default ≈ weekly). cron is stateless, so an explicit weekly entry
        # replaces an every-Nth-run counter. Skipped when the throttle is 0.
        hygiene = (cfg or {}).get("hygiene", {}) if isinstance(cfg, dict) else {}
        try:
            vacuum_runs = int(hygiene.get("vacuum_every_runs", 7) or 0)
        except (TypeError, ValueError):
            vacuum_runs = 7
        if vacuum_runs > 0:
            entries.append(f"0 3 * * 0 {cmd} --vacuum >/dev/null 2>&1  # {tag}-vacuum")

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

        # #693: dedup per-tag so a render entry and a hygiene entry coexist.
        if f"# {tag}" in current:
            print(f"> ⚠ A {tag} entry already exists in crontab. Remove it first or edit by hand.")
            print(current)
            sys.exit(1)

        new_crontab = current.rstrip() + ("\n" if current.strip() else "") + "\n".join(entries) + "\n"
        try:
            proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True,
                                  capture_output=True, check=False)
            if proc.returncode != 0:
                print(f"Error: `crontab -` failed: {proc.stderr.strip()}", file=sys.stderr)
                sys.exit(1)
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH.", file=sys.stderr)
            sys.exit(1)
        print("✔ Installed crontab entr" + ("ies:" if len(entries) > 1 else "y:"))
        for entry in entries:
            print(f"  {entry}")
        print()
        print("Verify with: crontab -l")
        print(f"Remove with: crontab -e  (delete the line(s) tagged `# {tag}`)")
        return

    # Default: print the entries
    print("# Add this to your crontab (run `crontab -e`):")
    for entry in entries:
        print(entry)
    print()
    print("Or install automatically with: perseus cron ... --install")


# ─────────────────────────────── systemd (Linux) ─────────────────────────────

SYSTEMD_SERVICE_TEMPLATE = """\
[Unit]
Description={description}
After=default.target

[Service]
Type=oneshot
ExecStart={exec_start}
"""

SYSTEMD_TIMER_TEMPLATE = """\
[Unit]
Description={description}

[Timer]
OnBootSec=1min
OnUnitActiveSec={interval}
Unit={unit}.service

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
    """Scaffold ~/.config/systemd/user/<unit>.{service,timer} units.

    #693: ``--job render`` (default) writes perseus-render.{service,timer}
    exactly as before; ``--job maintain`` writes perseus-hygiene.* running
    ``perseus vault maintain`` on the hygiene cadence.
    """
    if sys.platform == "darwin":
        print("Use `perseus launchd` on macOS.", file=sys.stderr)
        sys.exit(1)
    if sys.platform != "linux":
        suffix = " Native Windows Task Scheduler support is deferred." if sys.platform == "win32" else ""
        print(f"Error: `perseus systemd` is only supported on Linux.{suffix}", file=sys.stderr)
        sys.exit(1)

    job_tokens, tag, _stem = _resolve_job(args, cfg)
    is_maintain = tag == "perseus-hygiene"
    unit = "perseus-hygiene" if is_maintain else "perseus-render"
    service_desc = (
        "Perseus memory hygiene (vault maintain)" if is_maintain else "Perseus context renderer"
    )
    timer_desc = (
        "Perseus memory hygiene timer" if is_maintain else "Perseus context render timer"
    )

    raw_interval = getattr(args, "interval", None)
    if raw_interval is None:
        raw_interval = f"{_hygiene_schedule_minutes(cfg)}m" if is_maintain else "5m"
    try:
        interval = _parse_systemd_interval(raw_interval)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    launcher, stable = _perseus_launcher()
    exec_start = " ".join(launcher + job_tokens)

    service_content = SYSTEMD_SERVICE_TEMPLATE.format(
        description=service_desc, exec_start=exec_start
    )
    timer_content = SYSTEMD_TIMER_TEMPLATE.format(
        description=timer_desc, interval=interval, unit=unit
    )
    if not stable:
        print("# ⚠ Could not find a stable `perseus` launcher (~/.local/bin/perseus or on PATH);", file=sys.stderr)
        print("#   ExecStart uses a version-specific path that may go stale after a Python upgrade.", file=sys.stderr)

    if getattr(args, "install", False):
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service_path = unit_dir / f"{unit}.service"
        timer_path = unit_dir / f"{unit}.timer"
        service_path.write_text(service_content, encoding="utf-8")
        timer_path.write_text(timer_content, encoding="utf-8")
        print(f"✔ Wrote {service_path}")
        print(f"✔ Wrote {timer_path}")
        print()
        print("Next steps:")
        print("  systemctl --user daemon-reload")
        print(f"  systemctl --user enable {unit}.timer")
        print(f"  systemctl --user start {unit}.timer")
        if getattr(args, "enable", False):
            for cmd in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", f"{unit}.timer"],
                ["systemctl", "--user", "start", f"{unit}.timer"],
            ):
                try:
                    subprocess.run(cmd, check=False)
                except Exception as exc:
                    print(f"> ⚠ {' '.join(cmd)} failed: {exc}")
        return

    # Default: print both unit files to stdout, separated
    print(f"# ~/.config/systemd/user/{unit}.service")
    print(service_content)
    print(f"# ~/.config/systemd/user/{unit}.timer")
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
    """Remove a Perseus crontab entry — render entries by source path, or the
    hygiene entries (``--job maintain``) by their ``# perseus-hygiene`` tag."""
    import subprocess as _sp
    job = getattr(args, "job", "render") or "render"
    try:
        result = _sp.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            print("No crontab found.")
            return
        lines = result.stdout.split("\n")
        if job == "maintain":
            # Drops the nightly entry AND its weekly -vacuum companion.
            filtered = [l for l in lines if "# perseus-hygiene" not in l]
            removed_what = "the perseus-hygiene entries"
        else:
            if not getattr(args, "source", None):
                print("Error: removing a render entry requires the source path.", file=sys.stderr)
                sys.exit(1)
            source = Path(args.source).expanduser().resolve()
            marker = f"perseus render {source}"
            filtered = [l for l in lines if marker not in l]
            removed_what = f"the render entry for {source}"
        if len(filtered) == len(lines):
            print("No matching crontab entry found.")
            return
        _sp.run(["crontab", "-"], input="\n".join(filtered) + "\n", text=True)
        print(f"✔ Removed {removed_what}")
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
