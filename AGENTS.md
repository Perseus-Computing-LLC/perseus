@perseus v0.8

# Perseus — Agent Contributor Guide

This file is read by AI coding assistants (Rovo Dev, Claude Code, Codex, Cursor, etc.) at
session start. It tells you what Perseus is, how the repo is organized, and how to pick up
work.

---

## What Perseus Is

Perseus is a **live context engine for AI assistants**. It solves the cold-start problem: instead
of burning the first N turns of a session on orientation ("what's running? what were we doing?"),
Perseus resolves environment state *before* it enters the context window. The assistant receives
facts, not instructions to go find facts.

Core surfaces:

| Component | CLI command | What it does |
|---|---|---|
| **Renderer** | `perseus render <file.md>` | Resolves `@directive` blocks → plain markdown |
| **Checkpoints** | `perseus checkpoint / recover` | Lightweight session recovery snapshots |
| **Pythia** | `perseus suggest "<task>"` | Ranks tool/skill/approach options given live env state |
| **Agora** | `perseus agora ...` / `@agora` | Task board and scoped agent coordination |
| **Mnēmē** | `perseus memory ...` / `@memory` | Narrative project memory and federation |
| **Prefetch** | `perseus graph` / `perseus prefetch` | Static directive graphing and opt-in cache warming |
| **Synthesis** | `perseus synthesize ...` | Opt-in cited claims; uncited LLM output is dropped |

**Design philosophy:** Perseus is assistant-agnostic. It was built alongside Hermes Agent but
is not tied to it. The renderer output is plain markdown. The checkpoint store is plain YAML.
Any AI assistant that can read a file or receive stdin can use Perseus.

---

## Repo Layout

```
perseus.py              ← single-file CLI; this is the entire implementation
requirements.txt        ← pyyaml only
tests/
  conftest.py           ← shared pytest fixtures and module import wiring
  test_renderer.py      ← directive resolution, rendering, schema validation
  test_lsp.py           ← LSP JSON-RPC subprocess coverage
  test_doctor.py        ← doctor checks, exit codes, JSON output
  test_*.py             ← subsystem suites; run all before committing
spec/
  overview.md           ← high-level design; start here
  components.md         ← detailed component specs
  directives.md         ← full directive reference
  pythia.md             ← Pythia (tool oracle) design
  integration.md        ← adapter patterns for wiring Perseus to an AI assistant
  data-model.md         ← config schema, checkpoint schema, directory layout
ROADMAP.md              ← living roadmap; rendered live by Perseus itself
tasks/
  README.md             ← how the task workflow works
  *.md                  ← individual task specs; pick one up and work it
.perseus/
  context.md            ← live workspace context for this repo (Perseus dogfooding)
```

---

## Your Role

You are an **executor**, not an architect. The framework, feature roadmap, naming decisions,
and implementation plans come from the project owner. Your job is to implement tasks exactly
as specified — correctly, completely, and within the stated constraints.

**Do not:**
- Propose architectural changes, refactors, or "next steps" outside of a task spec
- Create new tasks unless the owner or current handoff explicitly asks for them
- Suggest splitting `perseus.py` into modules or packages
- Rename concepts, directives, or config keys
- Add dependencies
- Open PRs or branches without being asked — commit to `main` and push

**If you finish a task and see something worth doing**, note it as a comment in your
completion summary inside the task file. Do not act on it. The project owner will decide
if it warrants a new task.

**If a task spec conflicts with a constraint below**, stop. Do not resolve it yourself.
Add a `## Blocked` section to the task file explaining the conflict and wait for direction.

---

## Non-Negotiable Constraints

1. **Single file.** `perseus.py` stays one file. No package structure, no `setup.py`, no
   sub-modules. The entire implementation must be inspectable in one scroll. Internal
   organization (section headers, grouping) is fine. File splits are not.
2. **`pyyaml` is the only dependency.** Do not add deps without explicit approval.
3. **Tests before merge.** All existing tests must pass. New behavior needs new tests.
   Run: `python -m pytest tests/ -q`
4. **Spec and code must agree.** When you change behavior, update the relevant `spec/*.md`
   file. The spec is documentation, not a contract — the code is the truth.
5. **Keep the mythology.** Perseus, Pythia, Agora, Daedalus, Mnēmē, and the Medusa problem. Don't rename core concepts.
6. **Backward compatibility.** Existing `@directive` syntax and config keys must not break.
   New behavior is additive or behind config flags.

---

## How to Pick Up a Task

1. Read `tasks/README.md` for the workflow.
2. List available tasks: `ls tasks/*.md` (excluding README.md).
3. Read the task file. It has: goal, scope, acceptance criteria, and notes.
4. Implement. Run tests. Update spec if needed.
5. Commit with a message matching the task ID (e.g. `feat(task-02): provider-agnostic config`).
6. Mark the task complete by adding a `## Completed` section at the bottom of the task file
   with a brief summary of what changed.

Do not start a task that is already marked Completed or In Progress.

---

## Active Tasks (live Agora board)

@agora status=open,in_progress

> ↑ This block is rendered live by Perseus itself. When viewing this file via
> `perseus render AGENTS.md`, the `@agora` directives are expanded to a markdown
> table of open and in-progress task files. When viewing this file raw on
> GitHub/GitLab, you'll see the directive source — pick up a task whose
> `status: open` and claim it via `perseus agora claim <task-id> --agent <name>`.

## Maintenance Snapshot

@health

> ↑ Same idea — when rendered, this is a Mnēmē/Daedalus-style maintenance
> report (stale checkpoints, near-duplicates, large context files, old
> completed tasks). Raw view shows the directive.

---

## Running Perseus Locally

```bash
# Install dep
pip install pyyaml

# Smoke test
python perseus.py --version

# Run test suite
python -m pytest tests/ -q

# Render the live roadmap
python perseus.py render ROADMAP.md
```

---

## Key Design Decisions (Don't Relitigate Without a Task)

- **`@query` and `allow_query_shell`:** Shell execution is on by default for `@query` because
  it's the primary power-user directive. Disabling it by default would break most real context
  files. It can be turned off in config.
- **`allow_services_command=False` default:** The `command:` variant in `@services` is newer
  and less battle-tested. Silent wrong health status is worse than a disabled feature.
- **`allow_outside_workspace=False` default:** Security gate — prevents a misconfigured or
  malicious context file from reading arbitrary paths on the filesystem.
- **`.hermes.md` output file name:** This is a Hermes Agent convention (Hermes reads it at
  session start). Other assistants use different names (`AGENTS.md`, `CLAUDE.md`,
  `.cursorrules`). The output path should be configurable; the default is for Hermes users.
