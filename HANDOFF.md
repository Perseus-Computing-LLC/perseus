# Developer Handoff — 2026-05-19

**For:** Principal developer continuing Phase 13
**Repo:** https://github.com/tcconnally/perseus  
**Baseline:** task-34 batch, 293 tests passing, 1 sandbox-skipped TCP smoke
**State:** Phases 11 and 12 complete; Phase 13A/13B complete; task-35 next

---

## Read These First

1. `ROADMAP.md` — canonical future plan through Phase 15 and the resolver/generator decision gate
2. `AGENTS.md` — contributor constraints and task workflow
3. `tasks/README.md` — Agora workflow
4. `spec/data-model.md` — current schema validation DSL and `perseus validate` contract

---

## What Shipped Since The Previous Handoff

| Task | Commit | Status | Notes |
|---|---|---|---|
| **task-30** Phase 12A schema validation engine | `5f083a8` | complete | `schema=` for `@query`, `@read`, `@env`; `.perseus/schemas/`; `@validate` |
| **task-31** directive output schema annotations | `2453fba` | complete | `DirectiveSpec.output_schema`; automatic render-time validation; explicit `schema=` precedence |
| **task-32** `perseus validate` CLI | `5e105b6` | complete | file/stdin input, human and JSON output, non-zero invalid/error exits |
| **task-33** directive dependency graph | task-33 batch | complete | `perseus graph`, JSON graph, static resource hints |
| **task-34** pattern prefetch rules | task-34 batch | complete | `prefetch.rules`, `perseus prefetch`, cache warming with trust gates |

Phase 11 was already complete in the prior handoff: baseline repairs, `DIRECTIVE_REGISTRY`, `perseus doctor`, JSON agent surfaces, LSP integration tests, and the split test suite are all on `main`.

---

## Current Test Suite

Run:

```bash
python -m pytest tests/ -q
```

Latest local result:

```text
293 passed, 1 skipped
```

The skipped test is the TCP LSP smoke when sandboxed; it has passed outside the sandbox.

Subsystem layout:

```text
tests/
  conftest.py
  test_renderer.py
  test_checkpoint_agora_health.py
  test_oracle.py
  test_memory.py
  test_memory_federation.py
  test_lsp.py
  test_doctor.py
  test_agent_inbox_template.py
  test_llm.py
  test_platform_misc.py
  test_serve.py
```

---

## Phase 12 Contracts Now In Force

- Required dependencies remain unchanged: `pyyaml` only.
- Schema files resolve from `<workspace>/.perseus/schemas/` first, then workspace root, then cwd.
- Supported DSL subset: primitive `type`, `mapping`/`properties`, `required`, `sequence`/`items`, `pattern`, and `enum`.
- `@query schema=`, `@read schema=`, `@env schema=`, and `@validate schema=... @end` are live.
- `DirectiveSpec.output_schema` validates rendered directive output automatically.
- Per-invocation `schema=` takes precedence over registry-level `output_schema`.
- `perseus validate --schema SCHEMA [payload|-] [--json]` returns:
  - `0` valid
  - `1` schema validation failed
  - `2` schema/input read or parse error

---

## Next: Phase 13 — Predictive Pre-Fetching

Task files now exist. Task-33 and task-34 are implemented; continue with:

1. **13A Directive Dependency Graph**
   - Build a static graph over directives found in a source document.
   - Use `DIRECTIVE_REGISTRY` metadata rather than hardcoded directive lists.
   - Keep it read-only and deterministic.

2. **13B Pattern-Based Pre-Fetch Rules**
   - Add `prefetch.rules` config.
   - Trigger prefetches from directive patterns.
   - Reuse existing cache machinery; no daemon.

3. **13C Daedalus-Powered Adaptive Pre-Fetch**
   - Optional scoring layer using existing oracle/Mnēmē patterns.
   - Keep deterministic fallback and no required model dependency.
   - Preserve the Phase 14 resolver-vs-generator decision gate.

Before Phase 14 planning, write the resolver-vs-generator decision brief called out in `ROADMAP.md`.

---

## Architecture Reminders

### `DIRECTIVE_REGISTRY`

Single source of truth for directive metadata. Completion, hover safety, inline dispatch, and output schema validation all derive from it.

Current shape:

```python
class DirectiveSpec(NamedTuple):
    name: str
    resolver: Callable | None
    args: list[str]
    kind: str                 # inline | block | control
    call_sig: str             # acw | ac | a | awc | block
    executes_shell: bool = False
    reads_files: bool = False
    mutates_state: bool = False
    safe_for_hover: bool = True
    cacheable: bool = False
    summary: str = ""
    output_schema: object | None = None
```

### Mnēmē Path

Always resolve the narrative with `_mneme_path(workspace, cfg)`. Do not guess a path.

### Git Hygiene

Work from `main`, use focused commits, and push after green tests. There are no active feature branches.

---

## Non-Negotiable Constraints

1. `perseus.py` stays single-file.
2. `pyyaml` is the only required dependency.
3. Tests before commit.
4. Spec follows code.
5. Keep the mythology and public names.
6. Preserve backward compatibility.
7. Agents execute scoped tasks; if a task conflicts with constraints, mark it blocked.
