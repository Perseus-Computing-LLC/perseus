# Developer Handoff — 2026-05-19

**From:** Hermes session (opus model)  
**For:** Principal developer continuing Phase 11  
**Repo state:** `main` is clean + pushed; `feat/task-28-json-surfaces` has WIP

---

## What Shipped This Session

| Task | Commit | Tests Added |
|---|---|---|
| **task-25** DIRECTIVE_REGISTRY | `8ac4d38` | 5 invariant tests |
| **task-26** `perseus doctor` | `1b8d636` | 13 doctor tests |

Both are on `main`, pushed.

---

## What's In Progress

### task-28: `--json` Agent Surfaces — branch `feat/task-28-json-surfaces`

All 6 `--json` flags are wired in argparse and handler logic:
- `perseus oracle infer-labels --json`
- `perseus oracle drift --json`
- `perseus llm ping --json`
- `perseus memory status --json`
- `perseus memory federation list --json`
- `perseus memory federation pull --json`

**Two test failures remain:**

1. **`test_infer_labels_json_schema`** — The early-return path in
   `cmd_oracle_infer_labels` when `entries` is empty used to print prose and
   return 0 before reaching the JSON block. **Fix already applied** (around line
   4659 — the empty-entries path now checks `getattr(args, "json", False)` and
   emits JSON). Just needs a test run to confirm.

2. **`test_memory_status_json_with_narrative`** — The test creates a narrative
   at `tmp_path/memories/narrative.md`, but `_mneme_path()` resolves the
   narrative path via workspace hash, not the raw directory. The test fixture
   needs to either:
   - Mock `_mneme_path()` to return the test narrative directly, or
   - Create the narrative at the path `_mneme_path(tmp_path, cfg)` returns

   The fix is in the test, not the production code.

**Remaining work after test fixes:**
- Mark task-28 complete in `tasks/task-28-agent-json-surfaces.md`
- Merge branch to main

---

## What's Not Started

### task-27: LSP Integration Tests

Real JSON-RPC subprocess tests — spawn `perseus serve --lsp --stdio`, send
`initialize`/`textDocument/didOpen`, verify `publishDiagnostics`, test
completion and hover via the DIRECTIVE_REGISTRY.

**Key implementation notes:**
- The LSP server uses a hand-rolled JSON-RPC reader over stdio (no library)
- Watch for `rb""` byte-string patterns — the shell safety scanner may trip
- The hover resolver uses the registry's `safe_for_hover` flag — unsafe
  directives return stubs, safe ones resolve live
- The completion provider is now derived from `DIRECTIVE_REGISTRY` via
  `_LSP_DIRECTIVE_ARGS` / `_LSP_DIRECTIVE_NAMES` — test against those

### task-29: Split Tests by Subsystem

Mechanical refactor. Do this **last** after all other test additions land.

Proposed split:
```
tests/
  conftest.py           ← shared fixtures (cfg(), tmp_path helpers)
  test_renderer.py      ← directive resolution, caching, conditional blocks
  test_checkpoints.py   ← checkpoint/recover/diff
  test_oracle.py        ← suggest, oracle log, drift, infer-labels
  test_memory.py        ← Mnēmē narrative, federation
  test_lsp.py           ← LSP helpers, framing, diagnostics
  test_doctor.py        ← doctor checks
  test_registry.py      ← DIRECTIVE_REGISTRY invariants
  test_json_surfaces.py ← --json output tests
```

The current `test_perseus.py` is ~3000 lines / ~260 tests. Each test function
is self-contained — no ordering dependencies. The main shared fixture is `cfg()`
which builds a default config dict.

---

## Architecture Notes for the Developer

### DIRECTIVE_REGISTRY structure

```python
DirectiveSpec = NamedTuple('DirectiveSpec', [
    ('name', str),           # "@query"
    ('kind', str),           # "inline" | "block" | "control"
    ('resolver', Callable),  # resolve_query, or None for control
    ('call_convention', str),# "acw" | "ac" | "a" | "awc"
    ('args', list),          # ["fallback=", "schema="]
    ('safe_for_hover', bool),# False = stub in LSP hover
    ('description', str),    # Human-readable one-liner
])
```

The `call_convention` field encodes which args the resolver expects:
- `"acw"` = `(args, cfg, workspace)` — most resolvers
- `"ac"` = `(args, cfg)` — skills, session, waypoint, drift
- `"a"` = `(args)` — env, date
- `"awc"` = `(args, workspace, cfg)` — include (reversed param order!)

The dispatch adapter in `_resolve_via_registry()` handles this routing.

### `perseus doctor` check structure

Each check is a function returning `DoctorResult(status, name, detail)`:
- `status`: `"ok"`, `"warn"`, or `"error"`
- Exit 0 if no errors, exit 1 if any error

Add a check = write one function + add it to `_DOCTOR_CHECKS` list. The `--json`
output is a flat list of `{check, status, detail}` objects.

### Non-negotiable constraints (from ROADMAP.md)

1. Single file — `perseus.py` stays one file
2. `pyyaml` is the only dependency
3. Tests before commit
4. Spec follows code
5. Keep the mythology
6. Backward compatibility
7. Executors, not architects

---

## Test Counts

| Milestone | Tests |
|---|---|
| Session start | 232 |
| After task-25 | 237 |
| After task-26 | 250 |
| After task-28 (on branch, 2 failing) | 260 |

---

## File Sizes

- `perseus.py`: ~6,330 lines
- `tests/test_perseus.py`: ~3,000 lines
- Always use **patch-only edits** on `perseus.py` — never `write_file` on it

---

## Git State

```
main (1ffbe2f):
  63c4625 audit: reopen ghost tasks 26+28, remove pykwalify hard dep, add EXAMPLES.md
  8ac4d38 feat(task-25): DIRECTIVE_REGISTRY
  908a27f chore: mark task-25 completed
  1b8d636 feat(task-26): perseus doctor
  1ffbe2f chore: mark task-26 completed

feat/task-28-json-surfaces (c62ee47):
  c62ee47 wip(task-28): --json agent surfaces — 6 commands wired, 2 test fixes pending
```
