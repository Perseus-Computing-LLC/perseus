# Perseus v0.5 Hardening Patch Plan

## Scope
Fix the highest-value issues from the audit directly in `perseus.py` and add focused pytest coverage.

## Planned changes

1. **Workspace inference**
   - Replace `source_path.parent.parent` with a helper that infers workspace safely.
   - Use resolved paths consistently.

2. **Directive parsing hardening**
   - Add shared helpers for quoted token parsing and key/value attribute parsing.
   - Rework `@read` file/modifier parsing to match the newer `@query` quote handling.
   - Improve `@if` to report malformed/unknown conditions instead of silently returning false.
   - Detect unmatched `@if` / missing `@endif`.
   - Relax `@perseus` header regex to accept a bare `@perseus` line.

3. **`@services` robustness and trust model**
   - Support explicit `@services ... @end` blocks while preserving backward compatibility.
   - Allow blank lines inside YAML blocks.
   - Validate each service entry is a mapping.
   - Add config gates for shell-backed execution in `@query` and `@services command`.
   - Reuse configured shell for shell-backed execution.

4. **Workspace boundary safety**
   - Add helper to resolve relative paths against workspace and optionally block/warn when escaping workspace.
   - Apply to `@read` and `@include`.

5. **Skills/frontmatter robustness**
   - Parse frontmatter structurally instead of using raw `text.index('---', 3)`.
   - Prefer frontmatter `name` where present.

6. **Checkpoint/recover improvements**
   - Use recorded `stale_after` if present when deciding freshness.
   - Add a clearer message when checkpoint store does not exist.
   - Make `latest.yaml` fallback to a normal file if symlinks are unsupported.

7. **Phase 5 prep / launchd**
   - Add `perseus launchd` scaffolding subcommand for macOS LaunchAgents.

8. **Tests**
   - Add focused pytest coverage for the fixes above.

## Validation plan
- Run targeted pytest cases for parser, render, services, and checkpoint behavior.
- Run a small CLI smoke pass for `render` and `launchd` argument wiring.
