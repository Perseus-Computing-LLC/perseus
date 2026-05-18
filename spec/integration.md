# Integrating Perseus with an AI Assistant

Perseus is assistant-agnostic. The core pattern is simple:

1. Write a live context source file with `@perseus` directives
2. Render it on a schedule or at session start
3. Point your assistant at the rendered markdown output

The rendered output is plain markdown. No special file format is required.

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

---

## Auto-Injection Approaches

### Cron / scheduled render
Works anywhere a scheduler is available.

```bash
perseus render .perseus/context.md --output AGENTS.md
```

Use this when you want periodic refresh regardless of assistant.

### macOS LaunchAgent / launchd
Perseus provides a helper for Mac users:

```bash
perseus launchd .perseus/context.md --output AGENTS.md
```

This scaffolds a LaunchAgent plist that periodically refreshes the rendered output.

### systemd timer (Linux)
Use `perseus render ... --output ...` inside a systemd service/timer pair.

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
