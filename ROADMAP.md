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

### Phase 3 — Reliability + Scale ← COMPLETE ✅

**P3.1 — Cache layer (`@cache session` / `@cache ttl=N`)**
- ✅ Two-level cache: in-memory (`_SESSION_CACHE`) for `@cache session`, disk-backed JSON for `@cache ttl=N`
- ✅ `_parse_cache_modifier()` strips modifier from any directive line; returns `(clean_args, mode, ttl)`
- ✅ `cache_get()` / `cache_set()` — session cache is in-process only; TTL cache persists under `~/.perseus/cache/`
- ✅ Cache key = SHA256 of whitespace-normalised directive + clean args (stable across whitespace variations)
- ✅ Expired disk entries auto-pruned on first miss; write failures are non-fatal
- ✅ All inline directives (`@query`, `@skills`, `@session`, `@read`, `@env`, `@include`, `@waypoint`, `@date`) now route through cache layer

**P3.2 — Smart `perseus recover`**
- ✅ `--workspace` flag (defaults to cwd) — prioritises checkpoints by workspace path match + within TTL
- ✅ Three-phase fallback: (1) workspace match + within TTL → (2) workspace match any age → (3) most recent any workspace
- ✅ Each phase annotates output with match quality: "workspace match, 42s ago" / "outside TTL" / "no workspace match"
- ✅ Closes the interrupted-session continuity loop

**P3.3 — `@constraint...@end`**
- ✅ Block directive: `@constraint id="..." severity="..."` gathers body until `@end`
- ✅ All constraint rows in a document are accumulated and flushed as a single table after last line
- ✅ Works inside `@if` branches (rows passed via `_constraint_rows` shared list to recursive calls)
- ✅ Rendered as: `| ID | Severity | Rule |` table — clear machine-readable signal to assistant

---

### Phase 4 — Self-Bootstrapping ← CURRENT PRIORITY

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
Phase 3 (done):   Cache layer → smart recover → @constraint
Phase 4 (now):    Perseus renders its own roadmap live (this section goes away)
Phase 5 (future): Local scoring model, full autonomy
```

---

## CURRENT STATE
*Manually updated each session until Phase 4. Update this block at session end.*

**As of:** 2026-05-18 (session 6 — Phase 3 complete)

**Last completed:**
- P3.1 ✅ — `@cache session` / `@cache ttl=N` — two-level cache (in-memory + disk), `_parse_cache_modifier`, `cache_get/cache_set`, all inline directives wired through cache
- P3.2 ✅ — Smart `perseus recover --workspace` — three-phase fallback: workspace+TTL → workspace-any-age → latest; annotated output
- P3.3 ✅ — `@constraint id="..." severity="..."...@end` — block directive, table accumulator, flushed at top-level render
- Version bump: alpha v0.3; `context.md` and `ROADMAP.md` updated

**Phase 3 complete. Reliability and caching layer is live.**

**Active thread:** Phase 4 — Self-Bootstrapping (Perseus renders its own roadmap)

**Next session should:**
1. Read this file first
2. P4.1: Convert ROADMAP.md itself to use `@perseus` directives — replace the manual CURRENT STATE block with `@waypoint`, git log with `@query`, etc.
3. P4.2: Add `@version` or `@read perseus.py path="..."` to render the CLI version inline
4. P4.3: Consider `perseus init` — scaffolds `.perseus/context.md` for a new workspace (Phase 5 spec item that unlocks Phase 4 dogfooding for other projects)
5. Consider: add `@cache session` to `@skills` and `@session` in the workspace `context.md` (they're stable within a render session)

**Blocking / notes:**
- Container `$HOME` quirk: use absolute paths (`/home/hermeswebui`) not `~` in config
- No `gh` CLI — use `curl` + token from `/home/hermeswebui/.hermes/.env`
- Git push: `https://tcconnally:***@github.com/tcconnally/perseus.git`
- Services health check shows all ❌ URLError — expected (container can't reach host-network `localhost`). Not a bug.
- `@constraint` table is flushed at the *end* of the document. If you need it inline (e.g. mid-document positioning), that's a future enhancement — current placement is after all prose.

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
