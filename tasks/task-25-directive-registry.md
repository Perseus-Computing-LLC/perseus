---
id: task-25
title: "Internal DIRECTIVE_REGISTRY \u2014 single source of truth for directive metadata"
status: completed
priority: high
scope: medium
claimed_by: null
created: 2026-05-18
closed: null
phase: 11
theme: "A \u2014 Closed-loop intelligence / safety"
depends_on: []
blocks:
- task-27
- task-28
opened: '2026-05-18'
---
## Why

Per the 2026-05-18 principal code review, directive knowledge is duplicated across:

- `INLINE_DIRECTIVE_RE` (`perseus.py:~1684`)
- `_render_lines` dispatch chain (`perseus.py:~1853`)
- `_LSP_DIRECTIVE_ARGS` (`perseus.py:~5017`)
- `_lsp_resolve_directive_for_hover` (`perseus.py:~5223`)
- `_HOVER_UNSAFE_STUBS` (added in v0.8.1 review-fix pass)
- README + spec/directives.md tables
- Per-resolver helper signatures
- Tests, which often target helpers directly

Every new directive requires touching 5–7 places. The renderer/LSP can disagree
because they parse separately. Hover safety is a one-off table. This is a
missing-internal-table problem, not a file-splitting problem.

## What

Inside `perseus.py` (still one file — the single-file constraint stands),
introduce a single canonical registry:

```python
DIRECTIVE_REGISTRY: dict[str, DirectiveSpec] = {
    "@waypoint": DirectiveSpec(
        name="@waypoint",
        resolver=resolve_waypoint,
        args=["ttl"],
        kind="inline",                 # "inline" | "block" | "control"
        executes_shell=False,
        reads_files=True,
        mutates_state=False,
        safe_for_hover=True,
        cacheable=True,
        summary="Show the latest checkpoint summary",
    ),
    "@agent": DirectiveSpec(
        ...,
        executes_shell=True,
        safe_for_hover=False,
    ),
    "@query": DirectiveSpec(
        ...,
        executes_shell=True,
        safe_for_hover=False,
        cacheable=True,
    ),
    ...
}
```

Use it to generate / drive:

1. `INLINE_DIRECTIVE_RE` — built at import time from `name` values where
   `kind == "inline"`.
2. `_render_lines` inline dispatch — looks up `spec.resolver` instead of
   if/elif chain. Block directives stay special-cased; the registry just
   declares the boundary.
3. `_LSP_DIRECTIVE_ARGS` — derived from `spec.args`.
4. `_lsp_resolve_directive_for_hover` — looks up `spec.safe_for_hover`;
   unsafe directives return the existing labelled stub. The `_HOVER_UNSAFE_STUBS`
   dict becomes derived state.
5. LSP completion — sources the directive list from the registry.
6. `perseus doctor` (task-26) — reports registry validation issues (missing
   resolver, conflicting flags).

## Acceptance criteria

1. Adding a new directive requires editing one place in `perseus.py`
   (one `DIRECTIVE_REGISTRY[...] = DirectiveSpec(...)` line) plus the
   resolver function itself. No regex, dispatch chain, or LSP table edits.
2. `INLINE_DIRECTIVE_RE` is constructed at import time from the registry
   and asserted to match all `kind=="inline"` names. Drift is a hard fail
   at import.
3. `_lsp_resolve_directive_for_hover` no longer references any directive
   name literally — only `spec.safe_for_hover`.
4. A test enumerates every registered directive and asserts:
   - the resolver is callable,
   - safe_for_hover is False whenever executes_shell is True OR
     mutates_state is True (invariant),
   - cacheable is True only for resolvers that are deterministic given
     their args + workspace state.
5. No regression in the 231 existing tests.

## Non-goals

- Do not change the resolver signatures (some take `cfg` only, some take
  `cfg, workspace`). The registry calls them through a small adapter.
- Do not change directive semantics. This is pure refactor.
- Do not split files. Registry lives in `perseus.py`.

## Start here

1. Define `DirectiveSpec` (frozen dataclass or `typing.NamedTuple`).
2. Define `DIRECTIVE_REGISTRY` with every existing directive.
3. Generate `INLINE_DIRECTIVE_RE` from it; add assertion that the old
   hardcoded regex pattern matches what's generated.
4. Refactor `_render_lines` inline dispatch to look up via registry.
5. Refactor `_lsp_resolve_directive_for_hover` to look up via registry.
6. Add the registry invariant test.
7. Run the full suite. No behavior change should leak through.
