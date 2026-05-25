---
id: task-11
title: "Task 11 — Linux systemd Timer Integration (`perseus systemd`)"
status: completed
scope: small
depends_on: []
claimed_by: claude-sonnet-4.5
opened: 2026-05-18
closed: 2026-05-18
---

# Task 11 — Linux systemd Timer Integration (`perseus systemd`)

**Status: Open**  
**Scope: Small** — parity with existing `perseus launchd` (macOS); same pattern, different init system  
**Depends-on: None**

---

## Context

`spec/integration.md` describes systemd timer support for Linux users:

> Use `perseus render ... --output ...` inside a systemd service/timer pair.

Today Perseus only has `perseus launchd` for macOS LaunchAgent scaffolding. This task adds
`perseus systemd` as the Linux-native equivalent — scaffolding a user-space systemd service
and timer unit that periodically renders a context file.

This is explicit in the spec and a natural gap for any Linux user (including container
environments).

---

## Interface

```bash
# Scaffold systemd units for scheduled context rendering
perseus systemd <source.md> --output <target-file> [--interval 5m]

# Manage the scaffolded units
perseus systemd install    # copies units to ~/.config/systemd/user/; enables + starts timer
perseus systemd status     # systemctl --user status perseus-render.timer
perseus systemd uninstall  # disables and removes units
```

The default interval is 5 minutes (`5m`). Accepted format: `Nm` (minutes) or `Nh` (hours).

---

## What Gets Scaffolded

Running `perseus systemd <source.md> --output <target>` prints two unit files to stdout
(like `launchd` prints the plist). The user can pipe them to files or use `--install` to
write them directly.

### `~/.config/systemd/user/perseus-render.service`

```ini
[Unit]
Description=Perseus context renderer
After=default.target

[Service]
Type=oneshot
ExecStart=/home/<user>/.local/bin/perseus render <source.md> --output <target>
```

### `~/.config/systemd/user/perseus-render.timer`

```ini
[Unit]
Description=Perseus context render timer

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Unit=perseus-render.service

[Install]
WantedBy=timers.target
```

---

## `--install` flag

When `--install` is passed:

1. Write both unit files to `~/.config/systemd/user/`
2. Print the commands to enable and start the timer:
   ```
   systemctl --user daemon-reload
   systemctl --user enable perseus-render.timer
   systemctl --user start perseus-render.timer
   ```
3. Optionally run those commands if `--enable` is also passed

Perseus does not `os.system()` the `systemctl` calls by default — it prints them. The user
runs them. This is intentional: Perseus shouldn't silently interact with the init system
without the user's explicit action (unlike `launchd` which has similar constraints).

---

## Platform Detection

`perseus systemd` should check that the platform is Linux before scaffolding. On macOS,
emit a clear message: "Use `perseus launchd` on macOS."

---

## Design Constraints

- Single-file rule in force
- No new dependencies
- Scaffold output uses absolute paths derived from `sys.argv[0]` or the configured CLI path
- Must work in user-space (`~/.config/systemd/user/`) — never write to system-wide paths
- Unit file content must be deterministic and safe for version control (no embedded secrets)

---

## Acceptance Criteria

- [ ] `perseus systemd <source> --output <target>` prints scaffolded unit files to stdout
- [ ] `--interval` controls `OnUnitActiveSec` in the timer unit
- [ ] `--install` writes files to `~/.config/systemd/user/`
- [ ] `--install` prints the systemctl commands to activate the timer
- [ ] On macOS, emits a redirect-to-launchd message instead of scaffolding
- [ ] Tests: unit file content correctness, interval substitution, macOS platform guard
- [ ] `spec/integration.md` updated: systemd section marked implemented with example

---

## Notes

- This is explicitly a scaffold command, not a daemon manager. Perseus doesn't manage the
  timer lifecycle — it writes the files and tells the user what to run.
- User-space systemd (`~/.config/systemd/user/`) is the right target — no root, no
  system-wide side effects.
- The pattern mirrors `perseus launchd` exactly. Read that implementation first.

---

# Completed

**Closed:** 2026-05-18 · **Implemented by:** claude-sonnet-4.5

- `perseus systemd <source> -o <output> [--interval Nm|Nh] [--install] [--enable]`
- Scaffolds user-space `~/.config/systemd/user/perseus-render.{service,timer}` units
- `--install` writes the files and prints the three `systemctl --user` activation commands
- `--enable` (with `--install`) runs the systemctl commands as a convenience
- On macOS, redirects with `Use \`perseus launchd\` on macOS.` (parity with launchd's macOS guard)
- `_parse_systemd_interval` accepts `5m`/`2h`/`30s` plus systemd-native forms; raises on garbage
- Tests cover unit content, interval substitution, macOS guard
