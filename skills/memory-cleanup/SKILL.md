---
name: memory-cleanup
description: >-
  Audits all memory systems in a Perseus environment, identifies stale or
  superseded stores (Mem0, Mempalace, old vector DBs, garbled federation
  artifacts), and deletes them. Keeps Perseus Mneme (the live system) as the
  single source of truth. Run periodically or when upgrading Perseus versions.
tags: [maintenance, memory, cleanup, housekeeping]
requires: []
---

# Memory Cleanup Skill

Audits and purges stale memory systems from a Perseus environment, keeping
Perseus Mneme as the single source of truth. Run after upgrading Perseus,
after switching memory backends, or whenever memory feels noisy.

---

## Philosophy

> **Retaining old context is not as important as staying on the latest
> tooling and pushing the envelope.** Old memory systems accumulate noise,
> cause federation artifacts, and slow down recall. When in doubt, delete.

The live Perseus Mneme index (`~/.perseus/memory/`) is always the source of
truth. Everything else is a candidate for removal.

---

## Trigger Phrases

- "clean up memory"
- "purge stale memory systems"
- "memory cleanup"
- "reflect and clean"
- "audit memory"

---

## Workflow

### Step 1 — Audit All Memory Locations

Check for the following known memory system locations:

```bash
# Perseus (live — keep)
ls -lht ~/.perseus/memory/        # Mneme BM25 index files
ls -lht ~/.perseus/checkpoints/   # Session waypoints

# Rovo Dev sessions (live — keep)
ls ~/.rovodev/sessions/
ls ~/.codex/memories/

# Stale systems (candidates for deletion)
ls ~/.mem0/                       # Mem0 library (superseded by Mneme)
ls ~/.mempalace/                  # Mempalace (superseded by Mneme)
ls ~/.cache/chroma/               # Orphaned Chroma vector stores
ls ~/.cache/code-nemo/            # Nemo memory (if present)
ls ~/.local/share/perseus/        # Old single-file perseus installs
```

Report findings in a table:

| Location | Last Modified | Size | Status |
|---|---|---|---|
| `~/.perseus/memory/` | {date} | {N} files | ✅ Live — keep |
| `~/.perseus/checkpoints/` | {date} | {N} files | ✅ Live — keep |
| `~/.mem0/` | {date} | {size} | 🗑️ Stale — delete |
| `~/.mempalace/` | {date} | {size} | 🗑️ Stale — delete |
| `~/.cache/chroma/` | {date} | {size} | ⚠️ Check — may be active |

---

### Step 2 — Check for Garbled Federation Artifacts

Perseus `@memory` with federation enabled can write low-quality blended
content from other workspaces. Check the newest memory files:

```bash
ls -lt ~/.perseus/memory/ | head -5
```

For each file written in the current session, read the first 5 lines. If
the content is incoherent, references unknown projects, or contains
placeholder text (`[... Table Continuation ...]`, `Subagent:`, etc.), it is
a garbled federation artifact — delete it.

Flag: any file where the content does not match your actual work context.

---

### Step 3 — Check for Stale Venv Installs

Old Perseus venvs can accumulate stale `perseus.py` files that shadow the
installed package:

```bash
find ~ -path "*/site-packages/perseus.py" 2>/dev/null
```

If found, check the version:
```bash
head -5 {path}/perseus.py   # look for version comment
```

If older than the system Perseus version (`perseus --version`), delete the
stale file and reinstall in the venv:
```bash
# delete via delete_file tool, then:
{venv}/bin/pip install --force-reinstall perseus-ctx
```

---

### Step 4 — Delete Confirmed Stale Files

Use `delete_file` for each stale file identified. Do not use bash `rm` — use
the `delete_file` tool to maintain audit trail.

**Always delete:**
- `~/.mem0/` — entire contents (Mem0 library, superseded by Perseus Mneme)
- `~/.mempalace/` — entire contents (Mempalace, superseded by Perseus Mneme)
- Any garbled federation artifacts in `~/.perseus/memory/`
- Stale `perseus.py` in venv site-packages (see Step 3)

**Check before deleting:**
- `~/.cache/chroma/` — may be used by active tools (check config first)
- `~/.local/share/perseus/` — used by launchd watchdog scripts; update rather than delete

**Never delete:**
- `~/.perseus/memory/` — live Mneme index
- `~/.perseus/checkpoints/` — session waypoints
- `~/.perseus/config.yaml` — configuration
- `~/.rovodev/AGENTS.md` — rendered context
- `~/.codex/` — Rovo Dev session index

---

### Step 5 — Verify Clean State

After deletions, confirm:

```bash
ls ~/.mem0/ 2>/dev/null || echo "mem0: clean ✅"
ls ~/.mempalace/ 2>/dev/null || echo "mempalace: clean ✅"
ls ~/.perseus/memory/ | wc -l   # should be same count minus deleted artifacts
```

Report final state:

```
Memory Cleanup Complete
═══════════════════════
✅ ~/.perseus/memory/    — {N} files (live Mneme index)
✅ ~/.perseus/checkpoints/ — {N} files (session waypoints)
🗑️  ~/.mem0/             — deleted ({N} files)
🗑️  ~/.mempalace/        — deleted ({N} files)
🗑️  {garbled files}     — deleted ({N} files)

Single source of truth: Perseus Mneme ✅
```

---

## Cadence

| Trigger | When |
|---|---|
| After Perseus version upgrade | Always |
| After switching memory backends | Always |
| Weekly maintenance | Optional — run with `reflect` |
| When memory feels noisy or federated content is garbled | On demand |

---

## Known Stale Systems (as of 2026-05-27)

| System | Location | Status | Superseded By |
|---|---|---|---|
| Mem0 | `~/.mem0/` | Deprecated | Perseus Mneme |
| Mempalace | `~/.mempalace/` | Deprecated | Perseus Mneme |
| Chroma (standalone) | `~/.cache/chroma/` | Check context | Perseus Mneme |
| Code-Nemo | `~/.cache/code-nemo/` | Check context | Perseus Mneme |
| Old single-file perseus | `~/.local/share/perseus/` | Update, don't delete | pip install |

---

## Notes for Multi-Environment Use

When running this skill on a new Perseus environment (different machine or
workspace), the stale system locations are the same but the active paths
may differ. Always:

1. Run Step 1 audit first — don't assume the same stale systems exist
2. Confirm `perseus --version` and `~/.perseus/config.yaml` are present
   before deleting anything
3. Check `~/.local/share/perseus/` — on some environments this is used by
   active launchd jobs and should be updated, not deleted

---

*Part of the Perseus skill library. Compatible with Rovo Dev CLI, Claude Code, and any MCP-enabled assistant.*
*See: https://github.com/Perseus-Computing-LLC/perseus*
