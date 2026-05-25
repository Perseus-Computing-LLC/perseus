# Integrating Perseus with an AI Assistant

Perseus is assistant-agnostic. The core pattern is simple:

1. Write a live context source file with `@perseus` directives
2. Render it on a schedule or at session start
3. Point your assistant at the rendered markdown output

The rendered output is plain markdown. No special file format is required.

Phase 15 cited synthesis is deliberately separate from this render path.
`perseus synthesize` can draft compact claims from source files, but only
explicitly, only with exact citations, and without changing ordinary rendered
context.

---

## The Pattern

```text
source.md with @perseus directives
    ↓ perseus render --output <assistant-specific-file>
plain markdown output
    ↓
assistant reads that file at session start
```

The `@prompt ... @end` block is how you embed assistant-specific instructions in the context source itself.

Phase 16 product profiles provide a higher-level entry point:

```bash
perseus init --profile generic
perseus pack validate
```

Profiles write `.perseus/context.md` plus `.perseus/pack.yaml`, which records
the assistant target, rendered output path, trust profile, and optional
synthesis source packs. Existing `perseus init --template` and direct render
flows remain supported.

---

## Auto-Injection Approaches

### Cron / scheduled render
Prints a POSIX crontab entry on any host and can install it where `crontab` is
available (macOS, Linux, BSD, WSL).

```bash
perseus render .perseus/context.md --output AGENTS.md
perseus cron .perseus/context.md --output AGENTS.md --every 5
perseus cron .perseus/context.md --output AGENTS.md --every 5 --install
```

Use this when you want periodic refresh regardless of assistant. Native
Windows Task Scheduler support is explicitly deferred; Windows users should use
WSL cron, the printed `perseus render` command, or invoke `perseus render` from
their own scheduler.

### macOS LaunchAgent / launchd
Perseus provides a helper for Mac users:

```bash
perseus launchd .perseus/context.md --output AGENTS.md
```

This scaffolds a LaunchAgent plist that periodically refreshes the rendered output.

### systemd timer (Linux)

Perseus scaffolds user-space systemd units for Linux users:

```bash
# Print the .service and .timer files to stdout
perseus systemd .perseus/context.md --output AGENTS.md --interval 5m

# Write them to ~/.config/systemd/user/ and print activation commands
perseus systemd .perseus/context.md --output AGENTS.md --interval 5m --install

# Combined: write + run systemctl --user daemon-reload/enable/start
perseus systemd .perseus/context.md --output AGENTS.md --install --enable
```

Interval accepts `Nm` / `Nh` / `Ns` shorthand or any systemd time spec.
Falls back to a clear redirect message on macOS (use `perseus launchd` instead).

### Scheduler parity

| Platform | Perseus command | Support level |
|---|---|---|
| POSIX cron | `perseus cron SOURCE --output FILE [--every N] [--install]` | Prints a crontab line on any host; `--install` requires `crontab`. |
| macOS launchd | `perseus launchd SOURCE --output FILE [--interval N]` | Supported on macOS; writes a LaunchAgent plist. |
| Linux systemd | `perseus systemd SOURCE --output FILE [--interval 5m] [--install] [--enable]` | Supported on Linux; writes/starts user service + timer units. |
| Native Windows Task Scheduler | none | Deferred; use WSL cron, the printed render command, or a manual `perseus render` invocation. |

### Git hook
A pre-commit or post-checkout hook can refresh rendered context for local workflows.

---

## Per-Assistant Notes

### Hermes Agent
Hermes commonly uses `.hermes.md` as the rendered output file.

```bash
perseus render .perseus/context.md --output .hermes.md
```

Hermes can read that file at session start, or a wrapper script can render on demand before invoking Hermes.

### Claude Code / claude.ai Projects
Render to `CLAUDE.md` or another project knowledge file Claude reads.

```bash
perseus render .perseus/context.md --output CLAUDE.md
```

### Rovo Dev
Render to `AGENTS.md` in the repo root.

```bash
perseus render .perseus/context.md --output AGENTS.md
```

Rovo Dev reads `AGENTS.md` at session start.

### Cursor
Render to `.cursorrules` or another Cursor-readable context file.

```bash
perseus render .perseus/context.md --output .cursorrules
```

### Generic
Any assistant with file access can use Perseus. Pick any output filename and point the assistant at it.

```bash
perseus render .perseus/context.md --output live-context.md
```

---

## Adapter Conformance Matrix

The Phase 19A harness keeps adapter docs, product profiles, context packs, and
render outputs aligned. Each fixture is offline and deterministic.

| Adapter | Expected output | Trust profile | Fixture |
|---|---|---|---|
| generic | `live-context.md` | `balanced` | `tests/fixtures/adapters/generic/` |
| hermes | `.hermes.md` | `balanced` | `tests/fixtures/adapters/hermes/` |
| codex | `AGENTS.md` | `balanced` | `tests/fixtures/adapters/codex/` |
| claude-code | `CLAUDE.md` | `balanced` | `tests/fixtures/adapters/claude-code/` |
| cursor | `.cursorrules` | `balanced` | `tests/fixtures/adapters/cursor/` |
| rovodev | `AGENTS.md` | `balanced` | `tests/fixtures/adapters/rovodev/` |

Run the conformance harness with:

```bash
python -m pytest tests/test_adapter_conformance.py -q
```

---

## Workspace-Local Integration

A workspace can carry its own context source and config:

```text
/workspace/myproject/
  .perseus/
    context.md
    config.yaml
```

`perseus render .perseus/context.md --output <file>` loads the workspace-local config automatically.

---

## Example

```markdown
@perseus v0.4

@prompt
This context was rendered live by Perseus.
Trust the rendered output and skip orientation.
@end

# Session Context — @date format="YYYY-MM-DD HH:mm z"

## Recent Work
@session count=5

## Active Waypoint
@waypoint ttl=86400

## Services
@services
  - name: Local API
    url: http://localhost:8000/health

## Available Skills
@skills flag_stale=true
```
