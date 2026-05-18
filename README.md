# Perseus 🪞

> *Athena didn't tell Perseus to fight Medusa. She handed him a shield — polished to a mirror — and let him see the monster clearly without meeting her gaze. The trick was never strength. It was reflection.*

![Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Piazza della Signoria, Florence.](https://upload.wikimedia.org/wikipedia/commons/thumb/c/c0/Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg/500px-Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg)

*Perseus with the Head of Medusa — Benvenuto Cellini, 1545. Loggia dei Lanzi, Florence. ([Jastrow](https://commons.wikimedia.org/wiki/File:Perseus_Cellini_Loggia_dei_Lanzi_2005_09_13.jpg), CC BY-SA 4.0)*

**Perseus** is a live context engine for AI assistants. It solves the cold-start problem: every new session begins with an assistant that has no idea what's running, what you were working on, which tools are available, or where things broke. Perseus resolves that state **before it ever reaches the context window** — so the assistant starts with a complete, accurate picture instead of burning turns on orientation.

Built as a companion to [Hermes Agent](https://hermes-agent.nousresearch.com). Designed to be assistant-agnostic.

Perseus dogfoods itself: `ROADMAP.md` is a live `@perseus` source — the project's own documentation resolves its git state, CLI version, recent sessions, and last checkpoint at render time.

**Status: Alpha v0.4 — Core engine complete. Phases 1–4 shipped.**

---

## The Problem

Every AI assistant session starts cold. Before useful work can begin, the assistant spends turns on orientation:

- *What services are running right now?*
- *What were we working on last time?*
- *Which tool is the right one for this?*
- *Where did we leave off when the connection dropped?*

This is the **pre-flight tax** — and it compounds across every session, every developer, every context switch.

Static markdown files (AGENTS.md, CLAUDE.md, READMEs) make it worse. They were accurate when written. By the time they're read, the port has changed, the test suite has grown, and the container that was "always running" hasn't been started since Tuesday. The assistant either trusts stale data or stops to verify it — spawning more tool calls, consuming context, delaying work.

**Stale context isn't neutral. It's drag.**

---

## The Solution: Resolve Before Context

Like Perseus holding up the mirror, the fix is indirection: don't hand the assistant a static document and let it go look things up. Resolve everything first, hand it the reflection.

```
Without Perseus                   With Perseus
──────────────────────────────    ─────────────────────────────────────
"Port is 3001 (check .env)"  →   Port: 3001
"47 tests (may be stale)"    →   Tests: 54 passing (run 8s ago)
"Check docker ps first"      →   mongo-dev: Up 4h 12m
"Where did we leave off?"    →   Checkpoint: webhook handler written,
                                             pending test run
```

Any `.md` file beginning with `@perseus` on the first line becomes live. No special extension. No new toolchain. The file renders to plain markdown — the assistant reads facts, not instructions to go find facts.

---

## Three Components

### 🪞 The Renderer — `perseus render`

Resolves directive blocks in a source document before it hits the context window. Shell output, file values, environment variables, service health, session history — all pulled live at render time.

```markdown
@perseus v0.4

# Context — @date format="YYYY-MM-DD HH:mm z"

## What's Running
@query "docker ps --format 'table {{.Names}}\t{{.Status}}'"

## Last Session
@waypoint ttl=86400

## Ports
@read .env key="API_PORT" fallback="3001"
```

Becomes, by the time the assistant reads it:

```markdown
# Context — 2026-05-18 08:33 CDT

## What's Running
mongo-dev    Up 4 hours
redis-dev    Up 4 hours

## Last Session
Checkpoint written: 2026-05-18T08:28
Task: webhook handler — written, pending test run
Next: run pytest tests/test_webhook.py

## Ports
3001
```

The assistant never sees a directive. It sees a document that was already true.

---

### ⚡ Session Waypoints — `perseus checkpoint`

The Fates cut the thread when the connection drops. Waypoints are how you pick it back up.

Write a checkpoint at any natural pause point — end of a task, before a large operation, at a logical handoff. The next session recovers immediately, without re-orientation.

```bash
$ perseus checkpoint \
    --task "Implementing webhook integration" \
    --status "handler written, pending test run" \
    --next "run pytest tests/test_webhook.py" \
    --workspace /workspace/myproject

✅ Checkpoint written: ~/.perseus/checkpoints/2026-05-18T0833.yaml
```

`perseus recover` is workspace-aware: it finds the most relevant checkpoint for your current project, prioritising workspace match and recency, with fallback levels that tell you exactly how stale the data is.

---

### 🔮 Pythia — Tool Oracle (`perseus suggest`)

Pythia was the Oracle at Delphi who gave Perseus his mission. She didn't make decisions — she surfaced the truth so the hero could act clearly. That's the Tool Oracle: given a task and the current environment state, it ranks the highest-utility approaches and tells you *why*.

The Medusa of tool selection is the paralysis of facing too many options directly — 90 skills, 12 integrations, 4 possible approaches. Pythia holds up the mirror.

```bash
$ perseus suggest "deploy the staging container" --category devops
```

Emits a structured oracle prompt with a live environment snapshot — skills table with freshness, service health, recent checkpoint, session digest — which the assistant reads and answers with ranked recommendations. No extra model required. No separate API call. The loop closes in the same context window.

---

## Directives

| Directive | What it does |
|---|---|
| `@query "shell cmd"` | Runs a shell command, embeds stdout as a fenced block |
| `@read <file> [path="key"]` | Reads a file; dot-notation path for JSON/YAML/TOML; `key=` for `.env` files |
| `@env VAR [fallback="x"]` | Injects an environment variable; `required=true` emits a visible warning if unset |
| `@include <file>` | Embeds a file inline; markdown raw, structured files fenced |
| `@if file.exists ".env"` / `@endif` | Conditional blocks: `file.exists/missing`, `env.set/unset/eq/neq` |
| `@constraint id="..." severity="..."` | Machine-readable rules rendered as a `\| ID \| Severity \| Rule \|` table |
| `@skills [flag_stale=true]` | Scans the Hermes skills dir, reads frontmatter, flags stale entries |
| `@services` (YAML block) | HTTP health checks (`url:`), Docker container status (`docker:`), or shell exit check (`command:`) |
| `@session [count=N] [topic="..."]` | Recent session digest from the sessions directory |
| `@date format="YYYY-MM-DD HH:mm z"` | Live date/time, inline or standalone |
| `@waypoint [ttl=N]` | Latest checkpoint rendered inline; `ttl=` skips it if too old |
| `@prompt...@end` | AI instruction callout — visible to the assistant, attributed to Perseus |

Any directive accepts a `@cache` modifier:

```markdown
@query "git log --oneline -5" @cache session      ← run once per render, reuse after
@skills flag_stale=true @cache ttl=3600           ← cache to disk for 1 hour
```

---

## Quick Start

**Requirements:** Python 3.10+, `pyyaml` (`pip install pyyaml`)

```bash
# Install
cp perseus.py ~/.local/bin/perseus
chmod +x ~/.local/bin/perseus

# Configure (absolute paths required — ~ won't resolve in all environments)
mkdir -p ~/.perseus
cat > ~/.perseus/config.yaml << 'EOF'
oracle:
  skill_dir: /home/you/.hermes/skills
hermes:
  sessions_dir: /home/you/.hermes/sessions
EOF

# Scaffold a source document for your workspace (v0.4+)
perseus init /workspace/myproject

# Edit to taste, then render
perseus render /workspace/myproject/.perseus/context.md

# Write a waypoint
perseus checkpoint \
  --task "Adding @query directive" \
  --status "resolver written, tests pending" \
  --next "add to render loop, test with context.md" \
  --workspace /workspace/myproject

# Recover — workspace-aware
perseus recover --workspace /workspace/myproject

# Get Pythia's recommendations
perseus suggest "best way to search for a pattern across a large Python codebase"
```

---

## Auto-Injection with Hermes

Perseus keeps `.hermes.md` fresh via a `no_agent` cron watchdog (no model tokens, no noise):

```
Cron (every 5 min, silent)
  └─ perseus render .perseus/context.md → .hermes.md
                                               ↓
                                   Hermes session start
                                   reads .hermes.md automatically
                                   (highest priority context file)
                                               ↓
                               Assistant has full live context.
                               No orientation phase. Start working.
```

Hermes reads `.hermes.md` at session start with higher priority than `AGENTS.md`, `CLAUDE.md`, or `.cursorrules`. The cron job keeps it ≤5 minutes stale. The cold-start problem is solved before the session opens.

---

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Pythia skill loop · `@query` · workdir auto-injection via cron | ✅ Complete |
| **Phase 2** | `@read` · `@env` · `@if/@else/@endif` · `@include` — real project opt-in | ✅ Complete |
| **Phase 3** | `@cache session/ttl=N` · smart `recover --workspace` · `@constraint` | ✅ Complete |
| **Phase 4** | `@services command:` · `perseus init` · `--version` · ROADMAP.md goes live | ✅ Complete |
| **Phase 5** | `--llm` flag for local model oracle · checkpoint diffing | Planned |

Full detail: [ROADMAP.md](./ROADMAP.md)

---

## Architecture

```
Source document (.perseus/context.md)
  @perseus v0.4
  @query "git log --oneline -5"          ┐
  @read .env key="PORT"                  │  Directives resolved
  @waypoint ttl=86400                    │  before context window.
  @services                              │  Cache layer avoids
    - name: My App                       │  re-running slow queries.
      url: http://localhost:3001/health  ┘
          │
          ▼ perseus render
  Resolved markdown (facts, not instructions)
          │
          ▼
  .hermes.md  ←── cron watchdog keeps this ≤5 min fresh
          │
          ▼
  Hermes session start
  build_context_files_prompt()
          │
          ▼
  AI context window — complete, accurate, zero pre-flight tax

  Waypoints: ~/.perseus/checkpoints/
  Cache:     ~/.perseus/cache/
  Config:    ~/.perseus/config.yaml
```

---

## Etymology

**Perseus** slew Medusa not by meeting her gaze but by watching her reflection in Athena's polished shield. The Medusa here is the paralysis of facing your environment directly — too many tools, stale docs, no continuity between sessions. The mirror is resolved context: you see the situation clearly without being turned to stone by it.

**Hermes** gave Perseus three gifts for the quest: winged sandals for speed, a kibisis to carry what could not be looked at directly, and guidance through the unknown. This Perseus returns the favor — giving Hermes a way to navigate any workspace without the orientation tax.

**Pythia** was the Oracle at Delphi who spoke for Apollo. Pilgrims came with impossible questions; she gave them the truth in a form they could act on. The Tool Oracle works the same way: you come with a task and a tangled environment; it gives you ranked paths forward. She didn't need to know everything — she needed to know what mattered *now*.

**The Graeae** — the three grey sisters who shared a single eye — are what you're working around. Three sisters who can only see one thing at a time: the current context, the tool choice, or the session history. Perseus stole the eye and made them see all three at once. So does the renderer.

---

## License

MIT
