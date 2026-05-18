# Perseus Alpha — Renderer Implementation Brief

**Handed off from:** Session 2026-05-18  
**Workspace:** `/workspace/perseus`  
**Repo:** https://github.com/tcconnally/perseus  

---

## What Perseus Is

Perseus is a live context engine for AI assistants (Hermes Agent). It solves the cold-start problem — every session starts cold and burns turns on orientation. Perseus resolves environment state **before** it hits the context window.

Three components (build order):
1. **Renderer** ← build this session
2. Checkpoints (explicit, lightweight session recovery)
3. **Pythia** — the tool oracle / Hermes skill (renamed from "oracle" to avoid Oracle Corp trademark issues)

---

## This Session's Scope

Build the **alpha renderer** as a **Hermes skill** (`~/.hermes/skills/`).

### Three directives only (alpha scope):

| Directive | Does | Implementation |
|---|---|---|
| `@skills` | List available Hermes skills, flag stale ones | Scan `~/.hermes/skills/` recursively, read SKILL.md frontmatter, check mtime |
| `@services` | Live health check a list of URLs/containers | `curl` with timeout per entry; `docker ps` for container checks |
| `@session` | Digest of recent Hermes sessions | Call `session_search` with no query (recent mode) |

### Source format

Standard `.md` file. `@perseus` on line 1 activates rendering. Example:

```markdown
@perseus v0.1

@prompt
This context was rendered live. All values are current.
@end

# Session Context — 2026-05-18 06:49 CT

## Available Skills
@skills flag_stale=true

## Services
@services
  - name: Hermes WebUI
    url: http://localhost:7779
  - name: ntfy
    url: http://localhost:8080/v1/health

## Recent Sessions
@session count=5
```

---

## Spec Files (already written — read these first)

- `spec/overview.md` — problem, solution, non-goals
- `spec/components.md` — detailed component specs, build order, Pythia alpha design
- `spec/directives.md` — full directive reference (build only @skills, @services, @session for alpha)
- `spec/oracle.md` — Pythia spec (named "oracle" in file, rename to Pythia in implementation)
- `spec/data-model.md` — directory layout, checkpoint schema, config schema

---

## Key Decisions (locked)

- **No new file extension** — standard `.md` with `@perseus` on line 1
- **Checkpoints are explicit** — the assistant calls `perseus checkpoint` as a tool at natural pauses; no timers, no hooks
- **Pythia is a Hermes skill** — not just a CLI; the assistant can call it mid-session
- **Renderer alpha = 3 directives** — @skills, @services, @session only

---

## Hermes Environment

- Skills live at: `~/.hermes/skills/`
- Session search available via Hermes `session_search` tool
- No `gh` CLI — use `curl` + token from `/home/hermeswebui/.hermes/.env` for any GitHub ops
- Git push pattern: `https://tcconnally:${GITHUB_TOKEN}@github.com/tcconnally/perseus.git`
- User: Thomas (thc) — autonomous style, no check-ins, implement and decide details

---

## Deliverables

1. `perseus render` — Python script that processes a `.md` file with `@perseus` header and resolves the three alpha directives
2. Hermes skill: `~/.hermes/skills/perseus/SKILL.md` — so the assistant can call `perseus render` and `perseus checkpoint` as tools
3. A working `context.md` at `/workspace/perseus/.perseus/context.md` that uses all three directives against the live homelab
4. Commit and push everything to the repo
