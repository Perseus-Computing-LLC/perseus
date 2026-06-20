---
id: task-100
title: "Federation Conflict Detection & Merge Assistance"
status: open
priority: medium
scope: medium
claimed_by: null
created: 2026-06-19
phase: 27
theme: Decentralized Federation — Conflict Resolution
depends_on:
- task-96
- task-97
blocks: []
opened: '2026-06-19'
closed: null
---
## Why

When multiple federated workspaces have narratives covering the same topic,
they may disagree. Perseus's resolver-first philosophy means it should show
the conflict, not silently pick a winner. But it can also help: detect
overlaps, show side-by-side diffs, and draft reconciliations via Pythia's
cited synthesis pipeline.

## What

Three new capabilities: inline conflict detection during render, a
side-by-side diff viewer, and Pythia-assisted merge drafting.

### 1. Inline conflict detection

`@federation conflicts` directive renders detected conflicts:

```
> ⚠ Narrative conflicts detected:
>
> | Topic | Workspaces | Overlap |
> |---|---|---|
> | deployment strategy | alpha, beta | 87% |
> | database migration | alpha, gamma | 72% |
>
> Run `perseus memory federation diff <a> <b>` to inspect.
```

Detection approach:
- Extract Mnēmē section headers (## lines) from each federated narrative
- Compute pairwise FTS5 similarity on section body text
- Flag pairs above `federation.conflict_threshold` (default 0.6)
- Cache results in `~/.perseus/cache/federation/conflicts.json`
- `@federation conflicts` reads cache; `--refresh` flag re-computes

### 2. `perseus memory federation diff`

```
perseus memory federation diff <alias-a> <alias-b> [--topic TOPIC]
```

- Side-by-side markdown view of conflicting sections
- Without `--topic`: shows all conflicts between the two workspaces
- With `--topic`: shows only sections matching that topic header
- Output format: two-column markdown with `---` separator
- `--json` flag: structured output for agent consumption

### 3. `perseus memory federation merge`

```
perseus memory federation merge <alias-a> <alias-b> --topic TOPIC
```

- Builds a cited-synthesis prompt using the existing `perseus synthesize`
  pipeline (Phase 15A)
- Sources: conflicting narrative sections + full text of both narratives
- Output: draft reconciliation with line citations back to source narratives
- Requires `generation.enabled: true` or `--allow-generation` flag
- Output is a suggestion — never auto-applied to any narrative
- `--output FILE` writes the suggestion to a file instead of stdout
- `--llm ollama` routes through local model

### 4. Config keys

| Key | Default | Description |
|---|---|---|
| `federation.conflict_threshold` | 0.6 | FTS5 similarity threshold for conflict detection |
| `federation.conflict_cache_ttl_s` | 86400 | Cache TTL for conflict analysis results |

### Verification

- Two workspaces with overlapping topics → conflicts detected
- Two workspaces with no overlap → no conflicts reported
- `diff` shows correct side-by-side view
- `merge` produces synthesis with valid source citations
- Merge output is never written to either narrative file
