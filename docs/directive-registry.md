# Directive Registry Reference

> **Machine-generated** from the live `DIRECTIVE_REGISTRY`
> (`src/perseus/registry.py`). Regenerate after adding or changing a directive.
> This table is the single source of truth: type -> handler -> source class.

Perseus exposes one uniform grammar of typed `@directive` annotations. Every
directive is one `DirectiveSpec` row in `DIRECTIVE_REGISTRY`. A single call
adapter (`_call_resolver`) dispatches every inline resolver by its declared
`call_sig`; block/structural directives share the renderer's block path. There
is no third dispatch path, and the parser's recognized-directive regex is built
from this same table (`_build_inline_directive_re`), so adding a row is
sufficient to make the grammar parse a new directive.

See the patent disclosure for how this unification reads on claim element (a):
`docs/disclosures/2026-06-27-unified-directive-grammar.md`.

## Source classes

| Source class | Meaning |
|---|---|
| filesystem / workspace | Reads files or workspace artifacts (no shell) |
| shell / live system | Executes a sandboxed subprocess (gated) |
| semantic memory (FTS5/Mneme/Mimir) | Local index / vault recall; offline |
| sub-agent subprocess | Delegates to an agent subprocess (gated) |
| allowlisted external tool | Runs an executable from the tools allowlist |
| in-process / computed | Pure in-process computation (date, env, prompt) |
| control/structural | Renderer control flow (`@if`/`@end`/...); no resolver |

## Registry

| Directive | Resolver | Kind | call_sig | Tier | Source class | Patent claim (a) mapping |
|---|---|---|---|---|---|---|
| `@auto-skill` | `resolve_auto_skill` | inline | `ac` | 1 | in-process / computed |  |
| `@constraint` | `— (control)` | block | `block` | 1 | control/structural |  |
| `@date` | `resolve_date` | inline | `a` | 1 | in-process / computed |  |
| `@else` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@end` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@endif` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@env` | `resolve_env` | inline | `acw` | 1 | in-process / computed |  |
| `@health` | `resolve_health` | inline | `acw` | 1 | filesystem / workspace |  |
| `@if` | `— (control)` | control | `block` | 1 | control/structural |  |
| `@memory` | `resolve_memory` | inline | `acw` | 1 | semantic memory (FTS5/Mneme/Mimir) | @search (semantic memory) |
| `@prompt` | `resolve_prompt_block` | block | `block` | 1 | in-process / computed |  |
| `@tokens` | `resolve_tokens` | block | `a` | 1 | shell / live system |  |
| `@validate` | `resolve_validate_block` | block | `block` | 1 | filesystem / workspace |  |
| `@waypoint` | `resolve_waypoint` | inline | `ac` | 1 | filesystem / workspace |  |
| `@agora` | `resolve_agora` | inline | `acw` | 2 | filesystem / workspace |  |
| `@drift` | `resolve_drift` | inline | `ac` | 2 | filesystem / workspace |  |
| `@inbox` | `resolve_inbox` | inline | `acw` | 2 | filesystem / workspace |  |
| `@mimir` | `resolve_mimir` | inline | `acw` | 2 | semantic memory (FTS5/Mneme/Mimir) |  |
| `@perseus` | `resolve_perseus` | inline | `acw` | 2 | in-process / computed |  |
| `@services` | `resolve_services` | block | `block` | 2 | shell / live system |  |
| `@session` | `resolve_session` | inline | `ac` | 2 | filesystem / workspace |  |
| `@skills` | `resolve_skills` | inline | `ac` | 2 | filesystem / workspace |  |
| `@agent` | `resolve_agent` | inline | `acw` | 3 | sub-agent subprocess | @agent (sub-agent) |
| `@include` | `resolve_include` | inline | `awc` | 3 | filesystem / workspace | recursive composition |
| `@list` | `resolve_list` | inline | `acw` | 3 | filesystem / workspace |  |
| `@mason` | `resolve_mason_tool_directive` | inline | `a` | 3 | in-process / computed |  |
| `@query` | `resolve_query` | inline | `acw` | 3 | shell / live system | @query (live shell) |
| `@read` | `resolve_read` | inline | `acw` | 3 | filesystem / workspace | @file (filesystem) |
| `@synthesize` | `— (control)` | block | `block` | 3 | control/structural |  |
| `@tool` | `resolve_tool` | inline | `acw` | 3 | allowlisted external tool | @tool (external tool) |
| `@tooltrim` | `resolve_tooltrim` | inline | `acw` | 3 | filesystem / workspace |  |
| `@tree` | `resolve_tree` | inline | `acw` | 3 | filesystem / workspace |  |

## Call signatures

| `call_sig` | Adapter call | Used by |
|---|---|---|
| `a`   | `resolver(args)` | dispatched by `_call_resolver` |
| `ac`  | `resolver(args, cfg)` | dispatched by `_call_resolver` |
| `acw` | `resolver(args, cfg, workspace)` | dispatched by `_call_resolver` |
| `awc` | `resolver(args, workspace, cfg)` | dispatched by `_call_resolver` |
| `block` | renderer block-accumulation path | block/structural directives |

## Adding a directive

1. Write `resolve_<name>(args_str, cfg, workspace)` in the appropriate
   `src/perseus/directives/*.py` module.
2. Add one `DirectiveSpec(...)` row to `_bind_registry()` in
   `src/perseus/registry.py`, declaring its `call_sig`, `kind`, `tier`, and
   safety flags (`executes_shell`, `reads_files`, `mutates_state`).
3. Rebuild the single-file artifact (`scripts/build.py`) and bump `VERSION`.

No regex edits, no dispatch-chain edits, no LSP-table edits — the grammar, the
LSP completion table, the cache policy, and the safety gating all derive from
the one row.
