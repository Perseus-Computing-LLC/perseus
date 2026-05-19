# Developer Handoff — 2026-05-19

**For:** Principal developer continuing productization
**Repo:** https://github.com/tcconnally/perseus  
**Baseline:** productization roadmap batch, 314 tests passing, 1 sandbox-skipped TCP smoke
**State:** Phases 11, 12, 13, 14, and 15A complete; Phases 15B-22C are queued in Agora as the deployable-product path

---

## Read These First

1. `ROADMAP.md` — canonical future plan through Phase 15 cited synthesis
2. `AGENTS.md` — contributor constraints and task workflow
3. `tasks/README.md` — Agora workflow
4. `spec/data-model.md` — current schema validation DSL and `perseus validate` contract
5. `docs/RESOLVER_VS_GENERATOR.md` — decision brief for the Phase 14/15 boundary
6. `docs/CITED_SYNTHESIS.md` — Phase 15A citation contract and command surface
7. `docs/PERSEUS_PRODUCT_REPORT.md` — full project/productization report

---

## What Shipped Since The Previous Handoff

| Task | Commit | Status | Notes |
|---|---|---|---|
| **task-30** Phase 12A schema validation engine | `5f083a8` | complete | `schema=` for `@query`, `@read`, `@env`; `.perseus/schemas/`; `@validate` |
| **task-31** directive output schema annotations | `2453fba` | complete | `DirectiveSpec.output_schema`; automatic render-time validation; explicit `schema=` precedence |
| **task-32** `perseus validate` CLI | `5e105b6` | complete | file/stdin input, human and JSON output, non-zero invalid/error exits |
| **task-33** directive dependency graph | task-33 batch | complete | `perseus graph`, JSON graph, static resource hints |
| **task-34** pattern prefetch rules | task-34 batch | complete | `prefetch.rules`, `perseus prefetch`, cache warming with trust gates |
| **task-35** adaptive prefetch scoring | task-35 batch | complete | deterministic/Daedalus scoring over predeclared candidates with fallback |
| **Decision brief** resolver vs generator | decision-brief batch | complete | recommends resolver boundary through Phase 14; Phase 15 generation must be opt-in |
| **task-36** reinforcement signal collection | task-36 batch | complete | `perseus oracle outcomes`, deterministic checkpoint-correlated outcome signals |
| **task-37** online scoring adjustment | task-37 batch | complete | outcome-weighted prompt hints for `perseus suggest` |
| **task-38** A/B recommendation testing | task-38 batch | complete | opt-in primary/alternate exploration with oracle log attribution |
| **task-39** cited synthesis contract | task-39 batch | complete | `perseus synthesize`, opt-in LLM drafting, exact quote citation gate |
| **tasks 40-62** productization roadmap | productization-roadmap batch | open | Phase 15B through v1 release candidate path queued in Agora |

Phase 11 was already complete in the prior handoff: baseline repairs, `DIRECTIVE_REGISTRY`, `perseus doctor`, JSON agent surfaces, LSP integration tests, and the split test suite are all on `main`.

---

## Current Test Suite

Run:

```bash
python -m pytest tests/ -q
```

Latest local result:

```text
314 passed, 1 skipped
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
  test_synthesis.py
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

## Next: Productization Roadmap

Phase 13 and Phase 14 are complete:

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

The resolver-vs-generator decision resolved toward a bounded curator layer, not
a full generator. Phase 15A implements the guardrail foundation:

- `perseus synthesize` builds a line-numbered source bundle.
- LLM drafting is off by default and requires `generation.enabled: true` or
  `--enable-generation`.
- Every surviving claim must cite an exact source quote and line range.
- Uncited or invalid claims are dropped.
- Normal `perseus render` output is unchanged.

Next work starts with task-40: use the cited-claim contract for cross-source
consistency synthesis. Do not add a render-time generated section until task-40
proves the command surface is useful.

The deployable-product path is now queued through task-62:

- **Phase 15B-C:** finish cited synthesis only where it adds cross-source value.
- **Phase 16:** product contract, context pack manifest, init/profile workflow.
- **Phase 17:** permission profiles, redaction, audit log, trust report.
- **Phase 18:** installer, release artifacts, versioning, scheduler parity.
- **Phase 19:** adapter conformance, assistant profiles, VSCode release polish.
- **Phase 20:** authenticated serve, container sidecar, headless watch mode.
- **Phase 21:** golden eval corpus, performance budgets, compatibility suite.
- **Phase 22:** v1 docs, demo workspaces, release candidate checklist.

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
