---
id: task-13
title: Implement @if query("...") matches /regex/ conditional
status: completed
scope: small-medium
depends_on: []
claimed_by: claude-sonnet-4.5
opened: '2026-05-18'
closed: '2026-05-18'
---

### Description

The `@if` directive currently supports `file.exists`, `file.missing`, `env.set`, `env.unset`, `env.eq`, and `env.neq`. This task is to extend it with support for matching the output of a shell command against a regular expression.

### Syntax

The new conditional syntax will be:

```
@if query("shell command") matches /regex/
...
@endif
```

And the negated version:

```
@if query("shell command") not matches /regex/
...
@endif
```

### Implementation Details

1.  **`evaluate_condition()` in `perseus.py`**:
    *   The primary logic will be added to this function (around line 787).
    *   It needs to parse conditions like `query("...") matches /.../` and `query("...") not matches /.../`.
    *   A regular expression should be used to robustly parse this new format.

2.  **Shell Command Execution**:
    *   The `shell command` inside `query(...)` should be executed.
    *   The execution must be gated by the existing `allow_query_shell` trust setting. If `allow_query_shell` is `False`, the condition should evaluate to `False` and a warning should be logged.
    *   The `stdout` of the command will be used for the regex match. `stderr` should be ignored or logged for debugging.

3.  **Regex Matching**:
    *   The output (stdout) of the command should be tested against the provided `/regex/`.
    *   The `matches` variant should return `True` if the regex finds a match in the stdout.
    *   The `not matches` variant should return `True` if the regex does not find a match.

4.  **Error Handling**:
    *   If the conditional string is malformed (e.g., missing `/` delimiters for the regex, invalid command), a visible warning should be logged to the console during parsing to help users debug their templates. The condition should evaluate to `False`.

5.  **Testing**:
    *   Add new unit tests to `tests/test_perseus.py` to cover:
        *   A successful `matches` case.
        *   A successful `not matches` case.
        *   A failing `matches` case.
        *   A failing `not matches` case.
        *   The `allow_query_shell = False` case.
        *   A malformed conditional string.

6.  **Documentation**:
    *   Update `spec/directives.md` to document the `@if query(...)` conditional and mark it as implemented.

### Scope

*   **Effort**: Small-Medium. The logic involves shell execution and regex parsing, which needs to be done carefully.
*   **Dependencies**: No new external dependencies are required.
*   **Files**: All code changes should be in `perseus.py`.

---

# Completed

**Date:** 2026-05-18
**By:** claude-sonnet-4.5
**Commit:** (pending)

## What shipped

- Extended `evaluate_condition()` in `perseus.py` with a new branch for
  `query("shell command") [not] matches /regex/[i]` syntax.
- Honors `render.allow_query_shell` — when false, prints a warning to stderr
  and evaluates to False (does NOT raise).
- 30-second subprocess timeout matches the rest of `@query` family.
- Optional `i` flag for case-insensitive matching (kept minimal on purpose).
- Invalid regex raises `ConditionParseError` so the renderer surfaces a
  clear warning instead of silently failing.
- Tests cover: matches (true/false), not matches (true/false), allow_query_shell=false,
  case-insensitive flag, invalid regex, failed command, full render integration.

## Notes for follow-up

- Only `i` flag is supported. Adding `m`/`s` is trivial if the use case appears.
- Stdout-only matching; stderr is ignored. If a user needs stderr matching,
  they can wire it with `query("cmd 2>&1")`.
