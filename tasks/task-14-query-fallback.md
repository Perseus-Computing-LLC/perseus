---
id: task-14
title: Implement fallback="text" for @query directive
status: open
scope: small
depends_on: []
claimed_by: null
opened: '2026-05-18'
closed: null
---

### Description

The `@query` directive in `spec/directives.md` specifies a `fallback="text"` modifier, but the implementation in `resolve_query()` currently ignores it. This task is to implement this functionality.

The purpose of the fallback is to provide a default value when the shell command in the `@query` directive fails to execute or returns an empty result.

### Syntax

```
@query("shell command", fallback="default text")
```

### Implementation Details

1.  **`resolve_query()` in `perseus.py`**:
    *   The primary logic will be added to this function.
    *   It needs to parse the `fallback="..."` argument from the directive's arguments. A simple regex or string split should be sufficient.

2.  **Fallback Logic**:
    *   The fallback text should be returned under two conditions:
        1.  The `shell command` fails to execute (i.e., returns a non-zero exit code).
        2.  The `shell command` executes successfully but produces no output (empty `stdout`).

3.  **Default Behavior**:
    *   If no `fallback` is provided and the command fails or returns empty stdout, the directive should resolve to an empty string, which is the current behavior.

4.  **Testing**:
    *   Add new unit tests to `tests/test_perseus.py` to cover:
        *   A command that fails, with a fallback provided.
        *   A command that produces empty stdout, with a fallback provided.
        *   A successful command, where the fallback should be ignored.
        *   A failing command without a fallback (should return empty string).

### Scope

*   **Effort**: Small. This is a minor addition to an existing function.
*   **Dependencies**: No new external dependencies are required.
*   **Files**: All code changes should be in `perseus.py`.
