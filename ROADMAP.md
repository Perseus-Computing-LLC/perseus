@perseus v0.2

@prompt
This document is the single source of truth for the Perseus project.
Every new session working on Perseus must read this file first.
The CURRENT STATE section is manually updated at the end of each session until
Perseus is fully stood up — at that point @waypoint and @session replace it.
Do not ask the user what we're working on. Read this file. Then work.
@end

# Perseus — Living Roadmap

**Repo:** https://github.com/tcconnally/perseus  
**Workspace:** `/workspace/perseus`  
**Skill:** `perseus-context-engine` (installed at `~/.hermes/skills/`)  
**CLI:** `~/.local/bin/perseus`  
**Last updated:** 2026-05-18

---

## What Perseus Is

Perseus is a live context engine for AI assistants (Hermes Agent). Three components:

| Component | Purpose | Status |
|---|---|---|
| **Renderer** | Resolves `@directive` blocks in `.md` files before context window | ✅ Alpha built |
| **Checkpoints** | Lightweight explicit session recovery snapshots | ✅ Alpha built |
| **Pythia** | Tool oracle — ranks approaches given task + live env | 🔶 Prompt emitted, loop not closed |

**Core insight:** Resolve environment state *before* it hits the context window. The assistant receives facts, not instructions to go find facts.

**Pythia** (renamed from "oracle" — Oracle Corp is litigious) is the MVP. Renderer and checkpoints feed it.

---

## What's Built (v0.1)

### `perseus.py` — full CLI

| Command | What it does |
|---|---|
| `perseus render <file.md>` | Resolves `@perseus` source doc → plain markdown |
| `perseus checkpoint --task "..." [opts]` | Writes timestamped YAML to `~/.perseus/checkpoints/` |
| `perseus recover` | Prints latest checkpoint |
| `perseus suggest "<task>"` | Emits structured Pythia prompt over live env snapshot |

### Directives implemented

| Directive | Status | Notes |
|---|---|---|
| `@skills [flag_stale=true]` | ✅ | Scans `~/.hermes/skills/`, reads frontmatter, flags by mtime |
| `@services` (YAML block) | ✅ | HTTP health checks with latency |
| `@session [count=N]` | ✅ | Recent sessions from sessions dir |
| `@date format="..."` | ✅ | Inline substitution |
| `@waypoint [ttl=N]` | ✅ | Latest checkpoint content |
| `@prompt...@end` | ✅ | AI instruction callout block |
| `@query "..."` | ✅ Built | Runs shell cmd, embeds stdout as fenced code block; `@cache` parsed (no-op, Phase 3) |
| `@read <file> path="..."` | ✅ Built | JSON/YAML/TOML path=, .env key=, fallback= |
| `@env <VAR>` | ✅ Built | required=, fallback= modifiers |
| `@if/@else/@endif` | ✅ Built | file.exists/missing, env.set/unset/eq/neq |
| `@include <file>` | ✅ Built | md embedded raw; structured files fenced |
| `@constraint...@end` | ❌ Not built | Phase 3 |
| `@cache session/ttl=N` | ❌ Not built | Phase 3 |

### Files

```
/workspace/perseus/
  perseus.py                    ← main CLI
  spec/
    overview.md
    components.md
    directives.md
    oracle.md                   ← named oracle in spec, Pythia in impl
    integration.md
    data-model.md
  .perseus/
    context.md                  ← live workspace context (uses all 6 built directives)
  ROADMAP.md                    ← this file
  HANDOFF.md                    ← superseded by this file; keep for history

~/.perseus/
  config.yaml
  checkpoints/

~/.local/bin/perseus            ← symlink / wrapper

~/.hermes/skills/
  perseus/
    SKILL.md                    ← `perseus-context-engine` skill
```

---

## Roadmap

### Phase 1 — Close the Pythia Loop ← COMPLETE ✅

The oracle prompt is emitted to stdout. That's half the loop. Close it.

**P1.1 — Pythia as live Hermes skill call (short path)**
- ✅ Updated `perseus-context-engine` skill with explicit Pythia invocation pattern
- When assistant calls `perseus suggest "task"`, Perseus renders env snapshot, assistant produces ranked output inline
- Zero infrastructure cost. Done.

**P1.2 — `@query` directive**
- ✅ Implemented. Runs arbitrary shell commands, embeds stdout as fenced code block.
- `@cache` modifiers parsed for forward compat but no-op until Phase 3
- `context.md` updated to use `@query` for live git log + status
- Unlocks real project AGENTS.md opt-in: `@query "git log --oneline -5"`, `@query "docker ps ..."`

**P1.3 — Hermes workdir auto-injection**
- ✅ Implemented via `no_agent` cron watchdog pattern
- **Finding:** Hermes has no `context_script` hook. It reads `.hermes.md` at cwd at session start (highest priority over AGENTS.md, CLAUDE.md, .cursorrules).
- **Solution:** cron job `70c2cfa762e5` (`perseus-render-workspace.sh`) runs every 5 min; renders `.perseus/context.md` → `.hermes.md` silently (no delivery); Hermes picks it up automatically on next session open.
- Script lives at `~/.hermes/scripts/perseus-render-workspace.sh`; add new workspaces to `WORKSPACES=()` array there.
- `.hermes.md` added to `.gitignore` (generated output, not source)
- Cold-start is now solved: open workspace → `.hermes.md` is ≤5 min stale → Hermes reads it → no orientation phase needed

---

### Phase 2 — Real Project Opt-In ← COMPLETE ✅

Any project's `AGENTS.md` adds `@perseus` on line 1 and gets live values.

**P2.1 — `@read` directive**
```markdown
@read package.json path="version"     → 2.4.1
@read .env key="PORT" fallback="3001"
@read config.yaml path="database.host"
```

**P2.2 — `@env` directive**
```markdown
@env DATABASE_URL required=true
@env NODE_ENV fallback="development"
```

**P2.3 — `@if/@else/@endif`**
```markdown
@if file.exists ".env"
  @include .env
@else
  ⚠ No .env — app will not start.
@endif
```

**P2.4 — `@include`**
```markdown
@include ./CHANGELOG.md
@include ~/.perseus/checkpoints/latest.yaml
```

---

### Phase 3 — Reliability + Scale ← CURRENT PRIORITY

**P3.1 — Cache layer (`@cache session` / `@cache ttl=N`)**
- Currently every render re-runs all directives
- `~/.perseus/cache/` directory already specced in data-model.md
- Key by SHA256 of directive + args

**P3.2 — Smart `perseus recover`**
- If workspace checkpoint is within TTL and `workspace` field matches cwd, print structured recovery block
- This closes the interrupted-session continuity loop that motivated checkpoints

**P3.3 — `@constraint...@end`**
- Machine-readable rules rendered as structured table
- Better signal than prose rules buried in docs

---

### Phase 4 — Self-Bootstrapping

At this point Perseus renders its own roadmap live. This file becomes:

```markdown
@perseus v0.1

## Current State
@waypoint ttl=86400

## Recent Sessions
@session count=3 topic="perseus"

## Pythia Status
@services
  - name: Perseus CLI
    command: perseus --version
```

Manual state block below is retired.

---

### Phase 5 — Pythia Autonomy (v2)

- `--llm` flag: pipe oracle prompt to local model (Ollama/llama.cpp) — no Hermes round-trip
- Accepted recommendations become training data
- Checkpoint diffing — what changed between last two checkpoints
- Multi-workspace support and checkpoint namespacing
- `perseus init` — scaffolds `.perseus/context.md` for a new workspace

---

## Sequencing Summary

```
Phase 1 (done):   Pythia skill loop → @query → workdir auto-injection
Phase 2 (done):   @read → @env → @if/@else → @include  (real project opt-in)
Phase 3 (now):    Cache layer → smart recover → @constraint
Phase 4 (target): Perseus renders its own roadmap live (this section goes away)
Phase 5 (future): Local scoring model, full autonomy
```

---

## CURRENT STATE
*Manually updated each session until Phase 4. Update this block at session end.*

**As of:** 2026-05-18 (session 5 — Phase 2 complete)

**Last completed:**
- P2.1 ✅ — `@read <file>` — full file embed, `path=` dot-notation (JSON/YAML/TOML), `.env` `key=` lookup, `fallback=`
- P2.2 ✅ — `@env VAR` — env var injection, `required=true` warning, `fallback=` support
- P2.3 ✅ — `@if/@else/@endif` — condition blocks: `file.exists`, `file.missing`, `env.set`, `env.unset`, `env.eq`, `env.neq`; recursive via `_render_lines`
- P2.4 ✅ — `@include <file>` — md embedded raw, structured files fenced
- Renderer refactor: `render_source` → `_render_lines` (recursive, used for `@if` branches)
- Version bump: alpha v0.2

**Phase 2 complete. Real project opt-in unlocked — any project's `AGENTS.md` can add `@perseus v0.2` and get live values.**

**Active thread:** Phase 3 — Reliability + Scale

**Next session should:**
1. Read this file first
2. P3.1: Implement `@cache session` / `@cache ttl=N` — `~/.perseus/cache/` keyed by SHA256(directive+args)
3. P3.2: Smart `perseus recover` — workspace TTL match before printing
4. P3.3: `@constraint...@end` — machine-readable rules table
5. Consider Phase 4 opt-in: update this ROADMAP.md itself to use `@read` / `@query` directives

**Blocking / notes:**
- Container `$HOME` quirk: use absolute paths (`/home/hermeswebui`) not `~` in config
- No `gh` CLI — use `curl` + token from `/home/hermeswebui/.hermes/.env`
- Git push: `https://tcconnally:***@github.com/tcconnally/perseus.git`
- Services health check shows all ❌ URLError — expected (container can't reach host-network `localhost`). Not a bug.

---

## Environment Reference

| Thing | Where |
|---|---|
| Percy CLI | `~/.local/bin/perseus` |
| Main script | `/workspace/perseus/perseus.py` |
| Skill | `~/.hermes/skills/perseus/SKILL.md` (`perseus-context-engine`) |
| Global config | `~/.perseus/config.yaml` |
| Checkpoints | `~/.perseus/checkpoints/` |
| Live context | `/workspace/perseus/.perseus/context.md` |
| Spec docs | `/workspace/perseus/spec/` |
| GitHub token | `/home/hermeswebui/.hermes/.env` → `GITHUB_TOKEN` |
