# Task 01 — Provider-Agnostic Config & Integration Docs

**Status: Open**  
**Scope: Medium** — config renaming + doc rewrite, no new features  
**Tests required: Yes** — existing tests must still pass; add any if behavior changes

---

## Goal

Perseus was built alongside Hermes Agent but is not tied to it. Right now the code and docs
leak Hermes-specific assumptions that limit Perseus's usefulness to other AI assistants.
This task cleans that up.

---

## What Needs to Change

### 1. `perseus.py` — Config key renaming

The `hermes:` config section should become `assistant:` (or just stay as top-level keys).
The hardcoded defaults should use generic env var names.

**Current:**
```python
HERMES_SKILLS_DIR = Path(os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills"))
HERMES_SESSIONS_DIR = Path(os.environ.get("HERMES_SESSIONS_DIR", Path.home() / ".hermes" / "sessions"))

DEFAULT_CONFIG = {
    ...
    "hermes": {
        "skill_dir": str(HERMES_SKILLS_DIR),
        "sessions_dir": str(HERMES_SESSIONS_DIR),
        "session_digest_count": 5,
    },
}
```

**Target:**
```python
SKILLS_DIR = Path(os.environ.get("PERSEUS_SKILLS_DIR",
    os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills")))
SESSIONS_DIR = Path(os.environ.get("PERSEUS_SESSIONS_DIR",
    os.environ.get("HERMES_SESSIONS_DIR", Path.home() / ".hermes" / "sessions")))

DEFAULT_CONFIG = {
    ...
    "assistant": {
        "skill_dir": str(SKILLS_DIR),
        "sessions_dir": str(SESSIONS_DIR),
        "session_digest_count": 5,
        # Backward compat: old "hermes:" key is merged in load_config() if present
    },
}
```

**Backward compatibility rule:** In `load_config()`, if the loaded YAML has a `hermes:` key,
merge it into `assistant:` with a deprecation comment. Existing configs must not break.

### 2. `@skills` directive docstring and output

The `@skills` directive currently says "Scans `~/.hermes/skills/`" in its output header.
Change to "Scans configured skills directory" and show the actual resolved path.

### 3. `spec/integration.md` — Full rewrite

The current `integration.md` is Hermes-only. Rewrite it as a provider-agnostic adapter guide.

Structure it as:

```
# Integrating Perseus with an AI Assistant

## The Pattern
(render → file → assistant reads at session start)

## Auto-Injection Approaches
- Cron/scheduled render (works everywhere: Hermes, Cursor, CI)
- LaunchAgent/launchd (macOS)  
- systemd timer (Linux)
- Git hook (per-commit context refresh)

## Per-Assistant Notes

### Hermes Agent
(how .hermes.md works, the no_agent cron watchdog, workdir injection)

### Claude Code / claude.ai Projects
(write rendered output to CLAUDE.md or a project knowledge file)

### Rovo Dev
(write to AGENTS.md in the repo root; Rovo Dev reads it at session start)

### Cursor
(write to .cursorrules)

### Generic (any assistant with file access)
(any named file; pass path via --output)
```

Key facts to include:
- The `--output` flag on `perseus render` lets you write to any filename.
- The rendered output is **plain markdown** — no special format required.
- The `@prompt...@end` block is how you embed assistant-specific instructions in the
  context file itself.

### 4. `README.md` — Generalize the auto-injection section

The "Auto-Injection with Hermes" section should become "Auto-Injection" and cover the
pattern generically before showing Hermes as the primary example.

---

## Acceptance Criteria

- [ ] `config["hermes"]` is gone from `DEFAULT_CONFIG`; replaced by `config["assistant"]`
- [ ] Old `hermes:` key in user config is silently migrated (no crash, no data loss)
- [ ] `PERSEUS_SKILLS_DIR` / `PERSEUS_SESSIONS_DIR` env vars work; old `HERMES_*` vars
      still work as fallback
- [ ] All existing tests pass
- [ ] `spec/integration.md` covers at least: Hermes, Rovo Dev, Claude Code, Cursor, generic
- [ ] README auto-injection section is assistant-agnostic

---

## Notes

- The `.hermes.md` output filename convention is fine to keep as the Hermes default. Do not
  remove it — just make it clear in the docs that it's one option, not the only option.
- Don't rename `@skills` or `@session` directives — the names are fine; only the
  implementation defaults and docs need updating.
- The `spec/` files are documentation — update them to match the code changes.
