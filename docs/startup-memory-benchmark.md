# Startup-Memory Benchmark — is your startup context actually saving time?

Startup memory (the recall block Perseus renders into `AGENTS.md` / `CLAUDE.md`
/ `.hermes.md` before a session — see
[HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) and, for Rovo Dev, the
`perseus-vault` `docs/lifecycle-hooks.md` "Rovo Dev CLI" section) is only worth
its tokens if it **changes the first retrieval move**. A block that merely
*looks* full — identity, broad background, a stray date-only note — can cost
tokens without making the agent's first action any sharper.

This is a lightweight, repeatable way to measure that, so a regression after a
future Perseus / Vault change is easy to spot. It needs no harness: you paste a
4-prompt pack into a fresh session and score the answers against the rubric
below.

## What "good" means

Judge startup memory by whether it produces:

- **fewer exploratory turns** before the first useful retrieval,
- **fewer broad searches** ("what do I know about X?") in favor of targeted ones,
- a **better first retrieval command** (specific query/filters, not a scan),
- **more selective follow-up** (the agent defers what it doesn't need yet).

The high-value startup facts are the ones with concrete anchors — an active
escalation, a canonical live data source, a known filing location / ticket key.
Low-value ones are vague, date-only, or thematically-relevant-but-inert.
(The Vault's `startup: true` recall mode and `perseus_vault_hygiene` report
score exactly this "actionability" — see the vault `docs/retrieval-modes.md`.)

## The 4-prompt pack

Run these in order, in a **fresh** session that has your startup block loaded.
Each isolates a different quality so you can tell *where* a regression is.

1. **Startup-context quality** — "From the startup context you already have,
   what high-value facts are present, and what important gaps remain for
   `<today's task>`?"
2. **Retrieval-plan quality** — "Turn those gaps into a minimal retrieval plan:
   the fewest lookups that would close them."
3. **First-move discipline** — "What one lookup would you do *first*, and what
   are you intentionally deferring (and why)?"
4. **First-command quality** — "Assuming tool/command discovery is already
   done, what is the single best first retrieval command/query — exact tool,
   query, and filters?"

Prompt 1 measures the startup block itself; prompts 2–4 measure whether it
*shapes* retrieval. Separating them keeps a weak block from hiding behind a
strong retrieval plan (and vice-versa).

## Scoring rubric (0–2 each; 8 = excellent)

| Prompt | 0 (poor) | 1 (partial) | 2 (good) |
| --- | --- | --- | --- |
| 1 Startup-context | Restates identity/background; can't name gaps | Some real facts, vague gaps | Names concrete, action-changing facts + specific gaps |
| 2 Retrieval-plan | Broad "search everything" | A plan, but redundant with startup context | Minimal, non-overlapping lookups |
| 3 First-move | No prioritization / does everything | Picks a first move, weak rationale | Clear first move + explicit, justified deferrals |
| 4 First-command | Generic scan / `query=""` | Reasonable query, no filters | Targeted query **with** category/scope/date filters |

A falling total across runs after a change = a startup-memory regression.

### Good vs bad answers (prompt 4)

- **Bad:** `recall("recent work")` — a broad scan; the startup block didn't
  shape it.
- **Good:** `perseus_vault_recall { query: "ACE-10669 escalation next steps",
  category: "decision", startup: true, limit: 5 }` — the block surfaced the
  live escalation, so the first command is specific and filtered.

## Keeping it repeatable

- Freeze the pack: `.perseus/benchmarks/startup-pack.md` (template below), and
  re-run it after Perseus / Vault upgrades or context-profile changes.
- Re-render the startup block first (`perseus render <source> --format
  agents-md`) and confirm it is wired with `perseus doctor` (the
  `AGENTS.md startup-memory route` check).
- Prune low-signal entries the block keeps surfacing with the Vault's
  `perseus_vault_hygiene` report before re-scoring.

See [`../examples/startup-memory-benchmark-pack.md`](../examples/startup-memory-benchmark-pack.md)
for a copy-paste pack you can drop into a workspace.
