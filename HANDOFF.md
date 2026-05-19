# Developer Handoff — 2026-05-19

**From:** Hermes session (post-Phase-11 validation)  
**For:** Principal developer continuing Phase 12  
**Repo:** https://github.com/tcconnally/perseus  
**Baseline:** `main` @ `a413566`, 272 tests passing, `perseus.py` ~6,840 lines

---

## Read These First

1. `ROADMAP.md` — complete future plan through Phase 15 with decision gates
2. `AGENTS.md` — repo conventions, constraints, task workflow
3. `tasks/README.md` — Agora workflow (how to claim/complete tasks)

Then come back here for the tactical details.

---

## What Shipped (Phase 11 — Complete)

| Task | Commit | Status | Tests Added |
|---|---|---|---|
| **task-25** DIRECTIVE_REGISTRY | `8ac4d38` | ✅ on main | 5 invariant tests |
| **task-26** `perseus doctor` | `1b8d636` | ✅ on main | 13 doctor tests |
| **task-28** `--json` agent surfaces | `99f80cf` | ✅ on main | ~10 JSON schema tests |
| **task-27** LSP integration tests | `195e16f` | ✅ on main | ~30 LSP subprocess tests |
| **task-29** split tests by subsystem | `4f21170` | ✅ on main | 0 new (mechanical split) |
| **baseline repairs** fenced-block safety, diff, doctor paths, schema fallback | `cb545bc` | ✅ on main | — |

All 29 tasks closed. No open tasks. One skipped test: TCP LSP smoke (sandbox-blocked port bind; passes outside sandbox).

---

## Current State

```
main (a413566) — clean, pushed
  a413566  chore: bump context.md to @perseus v0.4, v0.8.1
  4aa79c0  docs: refresh phase 11 status
  4f21170  test(task-29): split suite by subsystem
  195e16f  test(task-27): exercise lsp server loop
  99f80cf  feat(task-28): add agent json surfaces
  cb545bc  fix(phase-11): stabilize baseline contracts
```

No open branches. No stashed work.

---

## Test Suite Layout

272 tests across 13 subsystem files:

```
tests/
  conftest.py                   ← shared fixtures (cfg, tmp_path wiring, _capture_json)
  test_renderer.py              ← directive resolution, @if, caching, @include, @read
  test_checkpoint_agora_health.py ← checkpoint, recover, diff, agora, health
  test_oracle.py                ← suggest, oracle log, drift, infer-labels
  test_memory.py                ← Mnēmē narrative, compaction, query
  test_memory_federation.py     ← federation manifest, CLI subcommands, @memory federation
  test_lsp.py                   ← LSP JSON-RPC subprocess tests, TCP smoke, mutation gate
  test_doctor.py                ← doctor checks, exit codes, --json
  test_agent_inbox_template.py  ← @inbox, @agent, template gallery
  test_llm.py                   ← --llm flag, llm ping, provider routing
  test_platform_misc.py         ← launchd, systemd, cron, serve, init
  test_serve.py                 ← perseus serve HTTP
  test_perseus.py               ← deleted (was the monolith; now split)
```

Run the suite:

```bash
python -m pytest tests/ -q             # fast summary
python -m pytest tests/ -v --tb=short  # verbose with tracebacks
python -m pytest tests/ -k "doctor"    # filter by name
```

---

## What's Next: Phase 12 — Schema Validation Engine

**Goal:** Formalized context quality assurance — Perseus validates that resolved
context is well-formed before injection.

**Spec:** `ROADMAP.md` § Phase 12

### Open Decision: pykwalify vs pure Python

The `@query schema=` modifier already exists as a proof-of-concept and currently
soft-imports `pykwalify`. This violates constraint #2 (pyyaml only). Three options
are documented in `ROADMAP.md § 12A`:

- **A:** Get explicit owner approval for pykwalify as second dependency
- **B:** Minimal built-in schema validator (type checks, required fields, patterns)
- **C:** pykwalify as optional soft-dep with graceful fallback

**Phase 11 baseline repairs chose option B** for the `@query schema=` subset already
implemented. Unless you have a reason to revisit, stay on option B for the full
Phase 12 engine.

### Phase 12 task order

1. **12A** — Schema DSL & validation engine: YAML-based schema language,
   validate `@query`/`@read`/`@env` outputs, schemas in `.perseus/schemas/`
2. **12B** — Directive-level schema annotations: optional `output_schema` field
   in `DirectiveSpec`, automatic validation on render
3. **12C** — `perseus validate` CLI: standalone validation without full render,
   useful for CI gates

No task files written yet for Phase 12. Write them before starting (follow the
frontmatter schema in `tasks/README.md`).

---

## Architecture Reference

### DIRECTIVE_REGISTRY

Single source of truth for all directive metadata. Adding a new directive:

1. Write `resolve_mynewdirective(args, cfg, workspace)` function
2. Add one `DirectiveSpec` entry to `DIRECTIVE_REGISTRY`
3. Regex, dispatch, LSP completion, hover safety all derive automatically

```python
DirectiveSpec = NamedTuple('DirectiveSpec', [
    ('name', str),            # "@query"
    ('kind', str),            # "inline" | "block" | "control"
    ('resolver', Callable),   # the resolve_ function, or None for control
    ('call_convention', str), # "acw" | "ac" | "a" | "awc" — see below
    ('args', list),           # ["fallback=", "schema="] — for LSP completion
    ('safe_for_hover', bool), # False = LSP hover returns stub, never executes
    ('description', str),     # one-liner for LSP hover tooltip
])
```

Call convention codes for `_resolve_via_registry()`:

| Code | Signature |
|---|---|
| `"acw"` | `resolver(args, cfg, workspace)` — most resolvers |
| `"ac"` | `resolver(args, cfg)` — skills, session, waypoint, drift |
| `"a"` | `resolver(args)` — env, date |
| `"awc"` | `resolver(args, workspace, cfg)` — include (reversed; historical) |

### `_mneme_path(workspace, cfg)`

The narrative file is NOT at `memories/narrative.md`. It lives at:

```
{cfg["memory"]["workspace_memories_dir"]} / {md5(str(workspace))[:8]}_narrative.md
```

Always call `_mneme_path(workspace, cfg)` to resolve this in tests.

### `perseus doctor` check structure

```python
class DoctorResult(NamedTuple):
    status: str   # "ok" | "warn" | "error"
    name: str     # display name
    detail: str   # one-line explanation
```

Each check is a `Callable[[argparse.Namespace, dict], DoctorResult]` in the
`_DOCTOR_CHECKS` list.

### Agent JSON surfaces (`docs/AGENT_SURFACES.md`)

Six commands expose stable `--json` contracts:

| Command | Key fields |
|---|---|
| `oracle infer-labels --json` | `scanned, inferred_accept, inferred_reject, written, dry_run` |
| `oracle drift --json` | `verdict, samples, metrics, thresholds, warnings` |
| `llm ping --json` | `provider, model, url, latency_ms, status, error` |
| `memory status --json` | `workspace, exists, updated, checkpoints_processed, line_count, mode` |
| `memory federation list --json` | array of `{alias, path, enabled, status, line_count, mtime}` |
| `memory federation pull --json` | array of `{alias, path, status, line_count, bytes}` |

Full contracts in `docs/AGENT_SURFACES.md`.

---

## Working with This Codebase

### Always patch `perseus.py` — never overwrite it

`perseus.py` is ~6,840 lines. Use targeted `old_string` → `new_string` patch edits
only. Section headers are anchor points:

```python
# ─────────────────────────────── Section Name ────────────────────────────────
```

### Fenced code blocks are literal

The renderer now skips directive execution inside fenced code blocks. Docs can
safely contain `@query` examples without triggering them.

### The `~/` directory in git status

A literal directory named `~/` exists at the repo root (created by an unexpanded
`~` in a tool call). It's untracked and ignored. Harmless — ignore it, or
`rm -rf '~/'` if it bothers you.

### Claiming a task before starting

```bash
python perseus.py agora claim task-XX --agent "<your name>"
```

---

## Non-Negotiable Constraints

1. **Single file.** `perseus.py` stays one file. No package structure.
2. **`pyyaml` is the only required dependency.** No new deps without owner approval.
3. **Tests before commit.** All existing tests must pass. New behavior needs new tests.
4. **Spec follows code.** When behavior changes, update `spec/*.md`.
5. **Keep the mythology.** Perseus, Pythia, Agora, Daedalus, Mnēmē. Don't rename.
6. **Backward compatibility.** `@directive` syntax and config keys must not break.
7. **Executors, not architects.** If a task conflicts with a constraint, mark it
   Blocked — do not resolve it unilaterally.

---

## Test Count History

| Milestone | Tests |
|---|---|
| Start of Phase 11 session | 250 |
| After task-25 (DIRECTIVE_REGISTRY) | 255 |
| After task-26 (doctor) | 259 |
| After task-28 (--json surfaces) | ~269 |
| After task-27 (LSP integration tests) | ~272 |
| After task-29 (test split, no new tests) | **272** |
