---
id: task-68
title: Phase 24D — Output Format Adapters
status: completed
priority: medium
scope: medium
claimed_by: hermes
created: 2026-05-24
closed: 2026-05-25
phase: 24
theme: "Extensibility Architecture — Hephaestus"
depends_on:
- task-65
blocks: []
opened: '2026-05-24'
closed: null
---

## Why

Perseus currently supports two output formats: markdown (default) and HTML
(`--format html`, Phase 23). As Perseus is adopted in more contexts — CI
pipelines, agent toolchains, dashboards — users need structured output they can
parse programmatically.

JSON output lets agents consume resolved context as structured data. Custom
format adapters let teams produce output tailored to their specific downstream
consumers without modifying Perseus source.

## What

Plugin interface for format adapters beyond the built-in markdown, HTML, and
JSON.

### Built-in JSON format

`perseus render --format json` resolves directives and returns structured output:

```json
{
  "resolved": "# Rendered markdown...",
  "directives": [
    {
      "name": "query",
      "args": "git log --oneline -5",
      "output": "828ece7 chore...",
      "cached": false,
      "duration_ms": 42
    }
  ],
  "metadata": {
    "source": ".perseus/context.md",
    "workspace": "/workspace/perseus",
    "timestamp": "2026-05-24T20:00:00Z",
    "version": "1.0.1",
    "cache_stats": {"hits": 3, "misses": 5},
    "directive_count": 8,
    "render_duration_ms": 234
  }
}
```

### Custom format adapters

Custom formats live in `~/.perseus/formats/<name>.py` and export a `render`
function:

```python
# ~/.perseus/formats/slack.py

def render(resolved_markdown, metadata):
    """Return Slack-formatted message for CI notification."""
    lines = []
    lines.append(f"*Perseus Render Complete*")
    lines.append(f"Workspace: `{metadata['workspace']}`")
    lines.append(f"Directives: {metadata['directive_count']}")
    lines.append(f"Duration: {metadata['render_duration_ms']}ms")
    lines.append(f"Cache: {metadata['cache_stats']['hits']} hits, "
                 f"{metadata['cache_stats']['misses']} misses")
    return "\n".join(lines)
```

Usage: `perseus render --format slack path/to/context.md`

### Discovery and contract

- Custom formats are auto-discovered from `~/.perseus/formats/` on startup
- Format name = filename minus `.py` extension
- Each module must export `render(resolved_markdown, metadata) -> str`
- Custom format names that collide with built-ins (`markdown`, `html`, `json`)
  are ignored with a warning
- Format loading errors are warnings — failed formats are skipped, `--format`
  references to them produce a render error
- The `metadata` dict carries: `source`, `workspace`, `timestamp`, `version`,
  `cache_stats`, `directive_count`, `render_duration_ms`, `directives` list

### JSON contract stability

The JSON output schema is a **stable contract** for agent consumption. Fields
may be added but existing fields will not be removed or change type within v1.x.
Documented in `docs/AGENT_SURFACES.md`.

## Acceptance Criteria

1. `perseus render --format json` produces valid JSON matching the schema above
2. Custom format adapters are auto-discovered from `~/.perseus/formats/`
3. `perseus render --format <custom>` invokes the matching adapter
4. Custom format that collides with built-in → ignored with warning
5. Custom format with import error → skipped, render error if referenced
6. `perseus render --format json` output includes all metadata fields
7. JSON format output is documented in `docs/AGENT_SURFACES.md`
8. Tests:
   - JSON format output schema validation
   - Custom format adapter loads and renders
   - Custom format with import error → graceful degradation
   - Format name collision → built-in wins
   - All metadata fields present in JSON output
9. No new dependencies.

## Non-goals

- Do not add binary output formats (PDF, DOCX, etc.)
- Do not add format adapter arguments or configuration
- Do not add streaming/chunked format output
- Do not add format-specific directive behavior
- Do not add a format registry or marketplace

## Completed

- Implemented in Phase 24 sprint (2026-05-24–25)
- Full test suite: 661 passed, 1 skipped
