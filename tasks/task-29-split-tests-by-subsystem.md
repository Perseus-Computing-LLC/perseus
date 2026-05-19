---
id: task-29
title: Split tests/test_perseus.py into 5 subsystem files
status: open
priority: low
scope: small
claimed_by: null
created: 2026-05-18
closed: null
phase: 11
theme: "E \u2014 Quality of life"
depends_on: []
blocks: []
opened: '2026-05-18'
---
## Why

Per the 2026-05-18 review:

> "224 tests in one file is still okay, but it is at the edge. The problem
> is not the number; it is discoverability. I would not split the
> implementation yet, but I would split tests by subsystem ... That does
> not violate the single-file runtime constraint and would make coverage
> gaps easier to see."

`tests/test_perseus.py` is now 231 tests, ~2,700 lines. Finding tests for a
specific subsystem is grep-driven. New contributors don't know where to add
a Mnēmē test vs a renderer test.

The implementation stays as `perseus.py` (single file, non-negotiable).
Only the tests split.

## What

Split `tests/test_perseus.py` into:

```
tests/
├── conftest.py              # shared fixtures (cfg(), _seed_oracle_log, ...)
├── test_renderer.py         # _render_lines, directives, blocks, @if/@else,
│                            #   resolve_*, INLINE_DIRECTIVE_RE
├── test_memory.py           # Mnēmē narrative, federation, @memory, compact,
│                            #   pattern_extractor (P9.2)
├── test_lsp.py              # serve --lsp, _lsp_*, hover sandbox,
│                            #   integration tests when task-27 lands
├── test_serve.py            # cmd_serve HTTP, _serve_collect_stats,
│                            #   loopback gate, endpoints
├── test_oracle.py           # cmd_oracle, infer-labels, drift, @drift,
│                            #   _infer_label_for_entry, _compute_drift
└── test_misc.py             # remaining: health, agora, inbox, llm ping,
                             #   checkpoint, init, cron, systemd, doctor
                             #   (each could become its own file if it grows)
```

A `tests/conftest.py` hosts the shared fixtures so each file imports
none of the others.

## Acceptance criteria

1. `python -m pytest tests/ -q` produces identical test count and identical
   pass/fail set before and after the split.
2. No test moves to a file that doesn't match its subsystem (review
   discipline: a renderer test in `test_oracle.py` is a bug).
3. Each new file starts < 600 lines. If any exceeds that on creation,
   split further (e.g. `test_memory_federation.py`).
4. Shared fixtures (`cfg`, `_seed_oracle_log`, etc.) live in
   `conftest.py` — never duplicated across files.
5. CI/manual run instructions in README and CONTRIBUTING.md (if present)
   updated.

## Non-goals

- Do not refactor the implementation. `perseus.py` stays one file.
- Do not introduce `tox`, `nox`, `hatch`, or any new test runner.
- Do not add `pytest-xdist` parallelism (suite is already < 4s).
- Do not add coverage reporting unless a separate task asks for it.

## Start here

1. Create `tests/conftest.py` with `cfg()` and any other shared helpers
   currently at the top of `test_perseus.py`.
2. Move the federation tests first — they're the most cleanly bounded.
   Verify `pytest -q` count is unchanged.
3. Move the LSP tests.
4. Move oracle/drift tests.
5. Move serve tests.
6. Whatever's left becomes the start of `test_misc.py` — assess whether
   it should be split further (probably yes for renderer + memory).
7. Delete the empty `tests/test_perseus.py` only after the count is
   provably unchanged.
