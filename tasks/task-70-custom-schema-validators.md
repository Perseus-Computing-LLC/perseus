---
id: task-70
title: Phase 24F — Custom Schema Validators
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-05-24
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on:
- task-65
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

The built-in schema validator (Phase 12) covers type checks, required fields,
sequences, regex patterns, and enums. It's sufficient for structural validation
but not for domain-specific contracts.

A team might need to validate that a `@query` output contains exactly 3 service
definitions each with a `port` field, or that a `@read` config block has
mutually consistent fields. These domain rules can't be expressed in the
built-in validator's YAML schema language. Custom validators let teams enforce
arbitrary constraints via Python, discovered through the same plugin system.

## What

Plugin validators co-located with schema files in `.perseus/schemas/`. Each
validator module exports a `validate` function. Referenced via
`schema="plugin:<name>"`.

### Validator contract

```python
# .perseus/schemas/service_list.py

def validate(value, schema):
    """
    Validate that `value` is a list of service definitions.

    Args:
        value: The parsed output (dict, list, str depending on directive)
        schema: The schema definition dict from the schema file

    Returns:
        (True, "") on success
        (False, "error message") on failure
    """
    if not isinstance(value, list):
        return False, f"Expected list, got {type(value).__name__}"
    for i, svc in enumerate(value):
        if not isinstance(svc, dict):
            return False, f"Item {i}: expected dict, got {type(svc).__name__}"
        if "port" not in svc:
            return False, f"Item {i}: missing required field 'port'"
    return True, ""
```

### Invocation

```
@query "cat services.yaml" schema="plugin:service_list"
@validate schema="plugin:service_list"
{{ @query "cat services.yaml" }}
@endvalidate
```

The `plugin:` prefix tells Perseus to look for `<name>.py` in `.perseus/schemas/`
instead of using the built-in validator.

### Discovery and lifecycle

- Plugin validators are discovered when a `schema="plugin:<name>"` is
  encountered at render time — not pre-scanned on startup
- Validator modules are imported once and cached for the render session
- Import errors → render warning, validation is skipped (value passes)
- Validator function errors (exceptions during `validate()`) → caught, logged
  as warning, validation is skipped

### Composition with built-in validator

- `schema="plugin:<name>"` uses ONLY the plugin validator
- To chain built-in + plugin, use the built-in schema file which can reference
  a plugin: TBD in implementation. Simplest approach: plugin validators can
  call the built-in validator internally if they want structural checks first

## Acceptance Criteria

1. Plugin validators in `.perseus/schemas/` are importable via
   `schema="plugin:<name>"`
2. `validate(value, schema) -> (bool, str)` contract is enforced
3. Plugin validator runs on directive output and controls pass/fail
4. Failed plugin validation → render warning with the plugin's error message
5. Plugin module import error → warning, validation skipped (value passes)
6. Plugin `validate()` exception → caught, warning, validation skipped
7. `perseus validate --schema plugin:<name>` works from CLI
8. Tests:
   - Plugin validator passes valid input
   - Plugin validator fails invalid input with custom message
   - Plugin import error → graceful skip
   - Plugin validate exception → graceful skip
   - Plugin validator via `perseus validate` CLI
   - Non-existent plugin → appropriate error
9. No new dependencies.

## Non-goals

- Do not add async validators
- Do not add validator configuration or arguments beyond the schema dict
- Do not add built-in validator chaining with plugins in v1
- Do not add validator discovery from outside `.perseus/schemas/`
- Do not add validator caching across render sessions
