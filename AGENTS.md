
> 📌 **Perseus prompt:** This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.

# Perseus Session Context — 2026-05-28 09:40 CDT

**Workspace:** current repo checkout  
**Repo:** https://github.com/Perseus-Computing-LLC/perseus  
**Project:** Perseus — Live Context Engine for AI Assistants (v1.0.6)

---

## Last Session
**Checkpoint written:** 2026-05-27T10:54:03.000642-05:00
**Task:** Update Perseus and generate memory checkpoints
**Status:** completed
**Next:** Decide whether to keep the regenerated perseus.py artifact diff and separately handle existing benchmark/gauntlet worktree changes.
**Workspace:** /Users/tconnally/Documents/perseus
**Notes:** Fast-forwarded main to origin/main c4b26d1. Smoke check reports perseus v1.0.6. Full suite passed outside sandbox: 1,032 passed in 69.14s. Sandbox-only pytest run failed on localhost socket binds. Regenerated perseus.py from src; artifact now removes stale generated prefetch/Mneme index snippets absent from source. Pre-existing benchmark and gauntlet changes were not touched.

---

## Workspace State

```text
86371c5 chore: commit gauntlet results, benchmark artifacts, and regenerated perseus.py
98eb66f feat: add memory-cleanup skill
96bebc1 feat: add pir-action-tracker skill
5fcf16f fix(mneme): port prefetch resource hints and index warming to canonical source
1094ea8 fix(mneme): resolve FTS5 search escaping and stale-index bugs
```
```text
 M .perseus/context.md
```

---

## Available Skills
> No skills found.

---

## Services
| Service | Status | Latency |
|---|---|---|
| Hermes WebUI | ❌ URLError | — |
| ntfy | ❌ URLError | — |
| Portainer | ❌ URLError | — |
| Perseus CLI | ✅ perseus v1.0.6 | — |

---

## Recent Sessions
> No recent sessions found.

---

## Active Tasks
> No tasks found.
> No tasks found.

---

## Maintenance Snapshot
### Duplicate Checkpoints (in last 5)
- **(no task)** — appears 2× with same status/next:
  - `20260526T2359.yaml`
  - `2026-05-27T0127.yaml`


---

## Project Narrative
Project memory is intentionally not rendered into tracked assistant files.