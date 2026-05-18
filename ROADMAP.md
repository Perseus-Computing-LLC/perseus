@perseus v0.4

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
**Last updated:** @date format="YYYY-MM-DD"

---

## What Perseus Is

Perseus is a live context engine for AI assistants (Hermes Agent). Three components:

| Component | Purpose | Status |
|---|---|---|
| **Renderer** | Resolves `@directive` blocks in `.md` files before context window | ✅ Alpha built |
| **Checkpoints** | Lightweight explicit session recovery snapshots | ✅ Alpha built |
| **Pythia** | Tool oracle — ranks approaches given task + live env | ✅ Skill loop closed |

**Core insight:** Resolve environment state *before* it hits the context window. The assistant receives facts, not instructions to go find facts.

**Pythia** (renamed from "oracle" — Oracle Corp is litigious) is the MVP. Renderer and checkpoints feed it.

---

## What's Built

### `perseus.py` — full CLI

@query "python3 /workspace/perseus/perseus.py --version"

| Command | What it does |
|---|---|
| `perseus render <file.md>` | Resolves `@perseus` source doc → plain markdown |
| `perseus checkpoint --task "..."` | Writes timestamped YAML to `~/.perseus/checkpoints/` |
| `perseus recover` | Prints latest checkpoint (workspace + TTL aware) |
| `perseus suggest "<task>"` | Emits structured Pythia prompt over live env snapshot |
| `perseus init [workspace]` | Scaffolds `.perseus/context.md` for a new workspace |

### Directives implemented

| Directive | Status | Notes |
|---|---|---|
| `@skills [flag_stale=true]` | ✅ | Scans `~/.hermes/skills/`, reads frontmatter, flags by mtime |
| `@services` (YAML block / explicit block) | ✅ | HTTP health checks (url:), docker status (docker:), optional shell cmd (command:) |
| `@session [count=N]` | ✅ | Recent sessions from sessions dir |
| `@date format="..."` | ✅ | Inline substitution |
| `@waypoint [ttl=N]` | ✅ | Latest checkpoint content |
| `@prompt...@end` | ✅ | AI instruction callout block |
| `@query "..."` | ✅ | Runs shell cmd, embeds stdout as fenced code block |
| `@read <file> path="..."` | ✅ | JSON/YAML/TOML path=, .env key=, fallback= |
| `@env <VAR>` | ✅ | required=, fallback= modifiers |
| `@if/@else/@endif` | ✅ | file.exists/missing, env.set/unset/eq/neq |
| `@include <file>` | ✅ | md embedded raw; structured files fenced |
| `@cache session/ttl=N` | ✅ | Two-level cache: in-memory (session) + disk (TTL) |
| `@constraint...@end` | ✅ | Block directive; renders as table at doc end |

### Files

- `requirements.txt` — runtime dependency list (`pyyaml`)
- `tests/test_perseus.py` — focused regression tests for the hardening pass


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
    context.md                  ← live workspace context
  ROADMAP.md                    ← this file (now a @perseus source)
  HANDOFF.md                    ← superseded; keep for history

~/.perseus/
  config.yaml
  checkpoints/
  cache/

~/.local/bin/perseus            ← symlink / wrapper

~/.hermes/skills/
  perseus/
    SKILL.md                    ← `perseus-context-engine` skill
```

---

## Workspace State

@query "git -C /workspace/perseus log --oneline -5"
@query "git -C /workspace/perseus status --short"

---

## Roadmap

### Phase 1 — Close the Pythia Loop ← COMPLETE ✅

**P1.1** — Pythia as live Hermes skill call  
**P1.2** — `@query` directive  
**P1.3** — Hermes workdir auto-injection via `no_agent` cron watchdog

---

### Phase 2 — Real Project Opt-In ← COMPLETE ✅

**P2.1** — `@read` directive  
**P2.2** — `@env` directive  
**P2.3** — `@if/@else/@endif`  
**P2.4** — `@include`

---

### Phase 3 — Reliability + Scale ← COMPLETE ✅

**P3.1** — Cache layer (`@cache session` / `@cache ttl=N`)  
**P3.2** — Smart `perseus recover --workspace`  
**P3.3** — `@constraint...@end`

---

### Phase 4 — Self-Bootstrapping ← COMPLETE ✅

Perseus renders its own roadmap live. This file is now a `@perseus` source.

**P4.1** — `command:` variant in `@services` (run shell cmd, check exit code)  
**P4.2** — ROADMAP.md converted to live `@perseus` source; manual CURRENT STATE retired  
**P4.3** — `perseus init` — scaffolds `.perseus/context.md` for a new workspace  
**P4.4** — `--version` flag, v0.4 bump

---

### Hardening pass — completed after alpha audit

- safer workspace inference for `render`
- quote-aware `@read` parsing helpers
- visible `@if` parse errors and unmatched-block warnings
- workspace-boundary checks for `@read` / `@include`
- `@query` and `@services command` trust gates
- structural frontmatter parsing for `@skills`
- `stale_after`-aware recover logic
- macOS `perseus launchd` scaffolding
- focused pytest coverage

### Phase 5 — Pythia Autonomy (v2) ← CURRENT PRIORITY

#### Phase 5A status

- `perseus suggest --llm ollama[:model]` foundation implemented
- snapshot builder split from prompt rendering
- local Ollama invocation path added
- focused tests added for snapshot/prompt/model flow


- `--llm` flag: pipe oracle prompt to local model (Ollama/llama.cpp) — no Hermes round-trip
- Accepted recommendations become training data
- Checkpoint diffing — what changed between last two checkpoints
- Multi-workspace support and checkpoint namespacing
- `perseus init` already landed in Phase 4

---

## Sequencing Summary

```
Phase 1 (done):   Pythia skill loop → @query → workdir auto-injection
Phase 2 (done):   @read → @env → @if/@else → @include  (real project opt-in)
Phase 3 (done):   Cache layer → smart recover → @constraint
Phase 4 (done):   Self-bootstrapping — this file is now live
Phase 5 (now):    Local scoring model, full autonomy
```

---

## Last Session
@waypoint ttl=86400

---

## Recent Sessions
@session count=3 topic="perseus"

---

## CLI Health
@services
  - name: Perseus CLI
    command: python3 /workspace/perseus/perseus.py --version

---

## Environment Reference

| Thing | Where |
|---|---|
| Percy CLI | `~/.local/bin/perseus` |
| Main script | `/workspace/perseus/perseus.py` |
| Skill | `~/.hermes/skills/perseus/SKILL.md` (`perseus-context-engine`) |
| Global config | `~/.perseus/config.yaml` |
| Checkpoints | `~/.perseus/checkpoints/` |
| Cache | `~/.perseus/cache/` |
| Live context | `/workspace/perseus/.perseus/context.md` |
| Spec docs | `/workspace/perseus/spec/` |
| GitHub token | `/home/hermeswebui/.hermes/.env` → `GITHUB_TOKEN` |

**Notes:**
- Container `$HOME` quirk: use absolute paths (`/home/hermeswebui`) not `~` in config
- No `gh` CLI — use `curl` + token from `/home/hermeswebui/.hermes/.env`
- Git push: `https://tcconnally:***@github.com/tcconnally/perseus.git`
- Services health check shows all ❌ URLError — expected (container can't reach host-network `localhost`). Not a bug.
- `@constraint` table flushed at end of document. Inline positioning is a future enhancement.
