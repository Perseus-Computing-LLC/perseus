# ─────────────────────────────── Scheduler ────────────────────────────────────
# Cross-platform scheduling commands: launchd (macOS), cron (POSIX), systemd (Linux)
import sys as _scheduler_sys

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
    return tokens, "perseus-render", _scheduler_safe_stem(source_path)


def _scheduler_shell_join(tokens) -> str:
    """Quote argv tokens for cron and systemd command-line fields."""
    import shlex as _shlex

    return _shlex.join([str(token) for token in tokens])


def _scheduler_xml_text(value) -> str:
    """Escape a value inserted into a launchd plist text node."""
    from xml.sax.saxutils import escape as _xml_escape

    return _xml_escape(str(value))


def _scheduler_safe_stem(source) -> str:
    """Return a portable scheduler identifier derived from a source path."""
    import re as _re

    stem = Path(source).stem
    safe = _re.sub(r"[^A-Za-z0-9_.@-]+", "-", stem).strip(".-")
    return safe or "context"


def _scheduler_source_marker(source) -> str:
    """Return a stable, shell-safe identity marker for a render source."""
    import hashlib as _hashlib

    canonical = str(Path(source).expanduser().resolve()).encode("utf-8")
    return _hashlib.sha256(canonical).hexdigest()[:16]


def _scheduler_cron_join(tokens) -> str:
    """Quote argv and escape cron's special percent separator."""
    return _scheduler_shell_join(tokens).replace("%", r"\%")


def _scheduler_systemd_join(tokens) -> str:
    """Quote argv and escape systemd's percent specifier introducer."""
    return _scheduler_shell_join([str(token).replace("%", "%%") for token in tokens])


def _scheduler_cron_source_matches(line, source) -> bool:
    """Match one render crontab line to exactly one canonical source path."""
    import re as _re
    import shlex as _shlex

    line_text = str(line)
    digest = _scheduler_source_marker(source)
    marker = _re.search(
        rf"(?:^|\s)#\s*perseus-render\s+source={_re.escape(digest)}(?:\s|$)",
        line_text,
    )
    command_text = line_text[: marker.start()] if marker else line_text
    try:
        tokens = _shlex.split(command_text, comments=True, posix=True)
    except ValueError:
        return False
    source_text = str(Path(source).expanduser().resolve())
    for index, token in enumerate(tokens):
        if token != "render" or index == 0 or index + 1 >= len(tokens):
            continue
        if tokens[index + 1] != source_text:
            continue
        launcher = Path(tokens[index - 1]).name.lower()
        if launcher == "perseus":
            return True
        if launcher == "perseus.py" and index > 1:
            interpreter = Path(tokens[index - 2]).name.lower()
            if interpreter.startswith("python"):
                return True
    return False


def _scheduler_cron_tag_matches(line, tag) -> bool:
    """Match a complete scheduler tag, not a similarly-prefixed comment."""
    import re as _re

    return bool(
        _re.search(
            rf"(?:^|\s)#\s*{_re.escape(tag)}(?:\s|$)",
            str(line),
        )
    )


def _scheduler_windows_quote(value) -> str:
    """Quote a value for a copied Windows command when it needs protection."""
    import re as _re

    text = str(value)
    if _re.fullmatch(r"[A-Za-z0-9_./:\\=-]+", text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def _scheduler_windows_command(tokens) -> str:
    """Render a Windows command line that is safe to paste into cmd.exe."""
    import re as _re

    def _cmd_quote(value):
        text = str(value)
        escaped = text.replace("^", "^^")
        for character in "&|<>()":
            escaped = escaped.replace(character, f"^{character}")
        escaped = escaped.replace('"', '^"')
        if not text or _re.search(r"[\s&|<>()^!\"]", text):
            return f'"{escaped}"'
        return escaped

    return " ".join(_cmd_quote(token) for token in tokens)


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
        default_label = f"com.perseus.render.{_scheduler_safe_stem(source_path)}"
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
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", label):
        print("Error: --label may contain only letters, digits, '.', '_' and '-'.", file=sys.stderr)
        sys.exit(1)
    program_arguments = "\n".join(
        f"      <string>{_scheduler_xml_text(tok)}</string>" for tok in prog_tokens
    )

    content = LAUNCHD_TEMPLATE.format(
        label=_scheduler_xml_text(label),
        program_arguments=program_arguments,
        workdir=_scheduler_xml_text(workdir),
        interval=interval,
        stdout_log=_scheduler_xml_text(stdout_log),
        stderr_log=_scheduler_xml_text(stderr_log),
    )

    if plist_path.exists() and not args.force:
        print(f"Error: {plist_path} already exists. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    plist_path.write_text(content, encoding="utf-8")

    print(f"✔ Wrote LaunchAgent plist: {plist_path}")
    print(f"  Launcher: {_scheduler_shell_join(launcher)}")
    if not stable:
        print("  ⚠ Could not find a stable `perseus` launcher (~/.local/bin/perseus or on PATH);")
        print("    falling back to a version-specific path that may go stale after a Python upgrade.")
        print("    Install the console script (`pipx install perseus-ctx` or ensure ~/.local/bin is on PATH).")
    print()
    print("Next steps:")
    print(f"  1. Load it:    {_scheduler_shell_join(['launchctl', 'load', plist_path])}")
    print(f"  2. Start now:  {_scheduler_shell_join(['launchctl', 'start', label])}")
    print(f"  3. Check logs: {_scheduler_shell_join(['tail', '-f', stdout_log, stderr_log])}")


# ─────────────────────────────── cron (POSIX) ────────────────────────────────

def cmd_cron(args, cfg):
    """Generate a crontab entry for a scheduled Perseus job.

    POSIX-oriented: works on systems with crontab (macOS, Linux, BSD).
    Recommended over launchd/systemd when portability matters.
    #693: ``--job render`` (default; byte-identical to the pre-#693 entry)
    or ``--job maintain`` (hands-off memory hygiene).
    """
    job_tokens, tag, _stem = _resolve_job(args, cfg)
    for field in ("source", "output"):
        value = getattr(args, field, None)
        if value is not None and any(char in str(value) for char in ("\n", "\r")):
            print(
                f"Error: {field} path must not contain line breaks.",
                file=_scheduler_sys.stderr,
            )
            _scheduler_sys.exit(1)
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
    if every < 60 and 60 % every:
        print(
            "Error: cron supports sub-hour intervals only when they divide 60 minutes; "
            "use systemd or Task Scheduler for this cadence.",
            file=sys.stderr,
        )
        sys.exit(1)
    if every > 60:
        if every % 60:
            print(
                "Error: cron supports intervals above 60 minutes only as whole hours; "
                "use systemd or Task Scheduler for this cadence.",
                file=sys.stderr,
            )
            sys.exit(1)
        hours = every // 60
        if 24 % hours:
            print(
                "Error: cron supports whole-hour intervals only when the hour step "
                "divides one day; use systemd or Task Scheduler for this cadence.",
                file=sys.stderr,
            )
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

    cmd = _scheduler_cron_join(launcher + job_tokens)
    source_marker = "" if is_maintain else f" source={_scheduler_source_marker(args.source)}"
    # Suppress crontab MAILTO noise; route stderr to /dev/null on success
    entries = [f"{schedule} {cmd} >/dev/null 2>&1  # {tag}{source_marker}"]
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
        if sys.platform == "win32":
            # #694: no crontab on native Windows — route to the Task
            # Scheduler backend so `cron create --install` still lands a
            # working schedule instead of a "crontab not found" error.
            print("> crontab is not available on native Windows — installing a Windows Scheduled Task instead.")
            return cmd_schtasks(args, cfg)
        try:
            existing = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True, check=False,
            )
            current = existing.stdout if existing.returncode == 0 else ""
        except FileNotFoundError:
            print("Error: `crontab` not found in PATH. Install cron first.", file=sys.stderr)
            sys.exit(1)

        # #693: dedup hygiene globally but identify render entries by source so
        # independent context files can each have one scheduled entry.
        if is_maintain:
            duplicate = any(
                _scheduler_cron_tag_matches(line, "perseus-hygiene")
                for line in current.splitlines()
            )
        else:
            source = Path(args.source).expanduser().resolve()
            duplicate = any(
                _scheduler_cron_source_matches(line, source)
                for line in current.splitlines()
            )
        if duplicate:
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
        suffix = " Systemd support is deferred; use Windows Task Scheduler via `perseus schtasks create`." if sys.platform == "win32" else ""
        print(f"Error: `perseus systemd` is only supported on Linux.{suffix}", file=sys.stderr)
        sys.exit(1)

    job_tokens, tag, stem = _resolve_job(args, cfg)
    is_maintain = tag == "perseus-hygiene"
    unit = "perseus-hygiene" if is_maintain else f"perseus-render-{stem}"
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
    exec_start = _scheduler_systemd_join(launcher + job_tokens)

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
        print(f"  {_scheduler_shell_join(['systemctl', '--user', 'daemon-reload'])}")
        print(f"  {_scheduler_shell_join(['systemctl', '--user', 'enable', f'{unit}.timer'])}")
        print(f"  {_scheduler_shell_join(['systemctl', '--user', 'start', f'{unit}.timer'])}")
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


# ──────────────────────── Windows Task Scheduler (#694) ──────────────────────

def _schtasks_schedule(every_minutes: int) -> list:
    """schtasks trigger args for an every-N-minutes cadence.

    schtasks /SC MINUTE caps /MO at 1439, so daily-or-slower cadences map to
    /SC DAILY (at 03:00, matching the cron backend's off-hours choice).
    """
    if every_minutes >= 1440:
        days = max(1, every_minutes // 1440)
        return ["/SC", "DAILY", "/MO", str(days), "/ST", "03:00"]
    return ["/SC", "MINUTE", "/MO", str(every_minutes)]


def _schtasks_tr(tokens: list) -> str:
    """Quote every value in a /TR command string that needs protection."""
    return " ".join(_scheduler_windows_quote(t) for t in tokens)


def cmd_schtasks(args, cfg):
    """#694: schedule a Perseus job via the native Windows Task Scheduler.

    Fills the platform gap the other backends leave: cron/launchd/systemd
    have zero coverage on native Windows, which is exactly where the
    hands-off hygiene persona lives. Task names parallel the POSIX tags:
    ``Perseus\\hygiene`` (+ ``Perseus\\hygiene-vacuum`` weekly companion)
    and ``Perseus\\render-<stem>``.
    """
    if sys.platform != "win32":
        print("Error: `perseus schtasks` is only supported on Windows.", file=sys.stderr)
        sys.exit(1)

    job_tokens, tag, stem = _resolve_job(args, cfg)
    is_maintain = tag == "perseus-hygiene"
    launcher, stable = _perseus_launcher()
    tr_cmd = _schtasks_tr(launcher + job_tokens)

    raw_every = getattr(args, "every", None)
    if raw_every is None:
        raw_every = _hygiene_schedule_minutes(cfg) if is_maintain else 5
    try:
        every = int(raw_every)
    except (TypeError, ValueError):
        print(f"Error: --every must be an integer (got {raw_every!r})", file=sys.stderr)
        sys.exit(1)
    if every <= 0:
        print("Error: --every must be > 0", file=sys.stderr)
        sys.exit(1)

    task_name = "Perseus\\hygiene" if is_maintain else f"Perseus\\render-{stem}"
    commands = [
        ["schtasks", "/Create", "/TN", task_name, "/TR", tr_cmd] + _schtasks_schedule(every)
    ]
    if is_maintain:
        hygiene = (cfg or {}).get("hygiene", {}) if isinstance(cfg, dict) else {}
        try:
            vacuum_runs = int(hygiene.get("vacuum_every_runs", 7) or 0)
        except (TypeError, ValueError):
            vacuum_runs = 7
        if vacuum_runs > 0:
            # Same stateless-scheduler reasoning as the cron backend: an
            # explicit weekly VACUUM task replaces an every-Nth-run counter.
            commands.append([
                "schtasks", "/Create", "/TN", "Perseus\\hygiene-vacuum",
                "/TR", tr_cmd + " --vacuum", "/SC", "WEEKLY", "/D", "SUN", "/ST", "03:00",
            ])

    if not stable:
        print("# ⚠ Could not find a stable `perseus` launcher (~/.local/bin/perseus or on PATH);")
        print("#   the task uses a version-specific path that may go stale after a Python upgrade.")

    if not getattr(args, "install", False):
        print("# Run these to install the Windows Scheduled Task(s):")
        for c in commands:
            print("  " + _scheduler_windows_command(c))
        print()
        print("Or install automatically with: perseus schtasks ... --install")
        return

    for c in commands:
        name = c[c.index("/TN") + 1]
        probe = subprocess.run(["schtasks", "/Query", "/TN", name],
                               capture_output=True, text=True, check=False)
        if probe.returncode == 0:
            print(f'> ⚠ Task {name} already exists. Remove it first: schtasks /Delete /TN "{name}" /F')
            sys.exit(1)
        proc = subprocess.run(c, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            print(f"Error: schtasks /Create failed: {(proc.stderr or proc.stdout).strip()}",
                  file=sys.stderr)
            sys.exit(1)
        print(f"✔ Created scheduled task {name}")
    print()
    print(f'Verify with: schtasks /Query /TN "{task_name}"')
    if is_maintain:
        cleanup = "perseus schtasks uninstall --job maintain"
    else:
        source = str(getattr(args, "source", "")).replace('"', '\\"')
        cleanup = f'perseus schtasks uninstall "{source}" --job render'
    print(f"Remove with: {cleanup}")


def cmd_schtasks_uninstall(args, cfg):
    """Remove Perseus Windows Scheduled Tasks (render by source, or hygiene)."""
    if sys.platform != "win32":
        print("Error: `perseus schtasks` is only supported on Windows.", file=sys.stderr)
        sys.exit(1)
    job = getattr(args, "job", "render") or "render"
    if job == "maintain":
        names = ["Perseus\\hygiene", "Perseus\\hygiene-vacuum"]
    else:
        if not getattr(args, "source", None):
            print("Error: removing a render task requires the source path.", file=sys.stderr)
            sys.exit(1)
        stem = _scheduler_safe_stem(args.source)
        names = [f"Perseus\\render-{stem}"]
    removed = 0
    for name in names:
        proc = subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"],
                              capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            print(f"✔ Removed scheduled task {name}")
            removed += 1
    if removed == 0:
        print("No matching scheduled task found.")


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
            hygiene_tags = ("perseus-hygiene", "perseus-hygiene-vacuum")
            filtered = [
                l for l in lines
                if not any(_scheduler_cron_tag_matches(l, tag) for tag in hygiene_tags)
            ]
            removed_what = "the perseus-hygiene entries"
        else:
            if not getattr(args, "source", None):
                print("Error: removing a render entry requires the source path.", file=sys.stderr)
                sys.exit(1)
            source = Path(args.source).expanduser().resolve()
            filtered = [l for l in lines if not _scheduler_cron_source_matches(l, source)]
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
    """Remove render or hygiene user-space systemd units."""
    if sys.platform == "darwin" or sys.platform == "win32":
        print("Error: `perseus systemd` is only supported on Linux.", file=sys.stderr)
        sys.exit(1)
    job = getattr(args, "job", "render") or "render"
    if job == "maintain":
        label = "perseus-hygiene"
    else:
        if not getattr(args, "source", None):
            print("Error: removing a render unit requires the source path.", file=sys.stderr)
            sys.exit(1)
        source_path = Path(args.source).expanduser().resolve()
        label = f"perseus-render-{_scheduler_safe_stem(source_path)}"
    user_units = Path.home() / ".config" / "systemd" / "user"
    timer_path = user_units / f"{label}.timer"
    service_path = user_units / f"{label}.service"
    import subprocess as _sp
    _sp.run(["systemctl", "--user", "disable", f"{label}.timer"], capture_output=True)
    for unit_name in (f"{label}.timer", f"{label}.service"):
        _sp.run(["systemctl", "--user", "stop", unit_name], capture_output=True)
    for p in [timer_path, service_path]:
        if p.exists():
            p.unlink()
            print(f"✔ Removed: {p}")
    _sp.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print(f"Run: {_scheduler_shell_join(['systemctl', '--user', 'stop', f'{label}.timer'])}  # if still running")
