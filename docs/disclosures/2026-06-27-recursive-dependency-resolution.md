# Technical Disclosure 8: Recursive, Dependency-Ordered Directive Resolution

**Project:** Perseus — Live Context Engine for AI Assistants
**Concept:** When a directive resolves to content that itself contains further
directives (via `@include`), Perseus resolves them in dependency order,
maintaining an explicit directive dependency graph, with path- and inode-based
cycle detection and a configurable depth bound — and terminates. Inline
resolver output is a deliberate injection boundary: it is inserted literally and
never re-parsed as directives.
**Disclosure Date:** 2026-06-27
**Author:** Thomas Connally
**Classification:** Tier 1 — Core
**Patent linkage:** A dependent claim on recursive, dependency-ordered
resolution, plus a concrete data structure (the directive dependency graph) for
the §101 "improvement to the functioning of a computer" argument. Provisional
64/069,842, issue #490.

## Problem Statement

Context assembled from composable sources needs to resolve nested references:
an included fragment may itself include further fragments and run its own
directives. Naive textual inclusion either (a) fails to resolve nested
directives, (b) recurses without bound on cyclic references, or (c) re-parses
arbitrary resolver output as new directives — an injection vector. A correct
system must resolve depth-first in dependency order, detect cycles, bound depth,
and refuse to treat resolved *content* as new *code*.

## The Invention

### 1. Recursive resolution through `@include`

`@include <file>` reads the target and renders it through the same
`render_source` entry point with an incremented `_include_depth`. The included
body's own directives resolve in place, depth-first, before control returns to
the parent. A three-level chain (`root → level1 → level2`) resolves every
level's directives in parent-before-child order:

```
# Level 0
```text
L0-shell
```
## Level 1
```text
L1-shell
```
### Level 2
L2-shell
```

(Committed as `docs/ip/exhibits/SAMPLE-B-recursive-resolution.md`,
byte-reproducible.)

### 2. Cycle detection (path + inode)

Each include call carries two immutable ancestor chains: a path chain
(`_include_path_chain`) and an inode chain (`_include_inode_chain`, keyed by
`(st_dev, st_ino)`). Before rendering a target, Perseus checks both. The path
check catches ordinary `A → B → A` loops; the inode check catches hard-link
loops where two distinct paths resolve to the same underlying file and would
otherwise bypass path-based detection. On a hit, resolution stops with the full
chain reported:

```
> ⚠ @include: circular dependency detected. Chain: …/cycB.md → …/cycA.md → …/cycB.md
```

### 3. Depth bound

Independent of cycle detection, `render.max_include_depth` (default 5) caps
recursion depth, stopping runaway chains that are deep but not strictly cyclic
with a clear, non-fatal warning.

### 4. Injection boundary — resolver output is data, not code

This is the security property that makes recursive resolution safe to claim.
Inline resolver output (e.g. `@query` / `@agent` stdout) is appended to the
rendered document **literally**. It is never re-scanned for directives.
Recursion happens *only* through `@include`, whose target is a file the operator
explicitly named. A `@query` whose stdout is the literal string
`@read /etc/secret` does **not** trigger a file read — the text appears verbatim
and the secret never leaks. (Asserted by
`tests/test_ip_recursive_resolution.py::test_inline_resolver_output_is_not_reparsed_as_directives`.)

This cleanly separates two trust tiers: **author-controlled** structure
(`@include` chains the author wrote) recurses; **resolver-produced** content
(shell stdout, agent output, file bytes) does not. It is the difference between
a compiler following `#include` and a compiler refusing to execute the *output*
of a program as more source.

## The Directive Dependency Graph (data structure for §101)

`directive_dependency_graph(source, workspace, cfg)` produces an explicit, typed
graph **without executing any directive**:

- **Nodes**: one per directive, carrying `id`, `directive`, `line`, `kind`,
  `source` (builtin/plugin), parsed `args`, cache policy, the full safety
  metadata from its `DirectiveSpec` (`executes_shell`, `reads_files`,
  `mutates_state`, `safe_for_hover`, `cacheable`), and `resources` — static
  dependency targets (file path, shell command, env var, memory index) extracted
  without touching the resource.
- **Edges**: ordering edges (`type: "order"`) capturing the resolution sequence.

This graph is the concrete computational artifact the §101 argument rests on:
the invention does not merely "assemble text," it builds and walks a typed
dependency structure with declared safety properties per node, enabling
cycle detection, depth bounding, cache-key derivation, and audit — a specific
improvement to how the machine assembles context, not an abstract idea.

## Scope / honest bounds

The static `directive_dependency_graph` enumerates the directives of a single
source file (with `@include` nodes marked as file-reading dependencies); it does
not currently inline the *included* files' sub-graphs into one combined graph.
Full cross-file graph expansion is a tracked enhancement. The recursive
*resolution* itself (Section 1) is fully multi-level; only the static
*visualization* is single-file today. This bound is stated so the claim reads on
what is implemented: multi-level recursive resolution with cycle detection and a
per-file typed dependency graph.

## Reduction to Practice

- Recursive resolution + cycle + depth + injection boundary:
  `src/perseus/directives/include.py`, `src/perseus/renderer.py`
- Dependency graph: `directive_dependency_graph` (see `src/perseus/directives/query.py`
  graph helpers and the renderer)
- Tests: `tests/test_ip_recursive_resolution.py` (6 tests, all offline)
- Exhibit: `docs/ip/exhibits/SAMPLE-B-recursive-resolution.{md,json}`

## Claims Summary (for attorney review)

1. A method for assembling context, comprising: resolving a first directive that
   designates a second source document; rendering the second source document
   such that directives contained therein are resolved in dependency order prior
   to returning to the first document; maintaining, across the recursion, an
   immutable ancestor chain identifying each source by both path and
   device-inode identity; and halting resolution of any branch whose target
   appears in the ancestor chain, thereby detecting cyclic dependencies that
   path identity alone would not catch.

2. The method of claim 1, further comprising bounding recursion by a configurable
   maximum depth independent of cycle detection.

3. The method of claim 1, wherein content produced by resolving a directive is
   incorporated into the output as literal text and is not re-parsed for
   directives, such that only author-designated inclusion edges produce
   recursion and resolver-produced content cannot inject further resolution.

4. The method of claim 1, further comprising constructing, without executing any
   directive, a typed dependency graph whose nodes declare per-directive safety
   metadata and static resource targets and whose edges encode resolution order.
