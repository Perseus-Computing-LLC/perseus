---
id: task-12
title: "Task 12 — Mnēmē: Narrative Project Memory"
status: open
scope: large
depends_on:
  - task-02
  - task-04
claimed_by: null
opened: 2026-05-18
closed: null
---

# Task 12 — Mnēmē: Narrative Project Memory

**Status: Open**  
**Scope: Large — new subsystem; substantial design surface**  
**Depends-on: task-02** (oracle log + `run_llm` infrastructure), **task-04** (Agora task schema)

> **This is a Phase 7 task. Read this entire file before writing a single line of code.**
> The design is complete. Your job is to implement it exactly as specified, then update
> the spec docs. Architecture decisions belong to the project owner. If something conflicts
> with the non-negotiable constraints in ROADMAP.md, mark it Blocked — do not resolve it
> unilaterally.

---

## The Name

**Mnēmē** (Μνήμη) was the original Muse of Memory in pre-classical Greek mythology, before
the canon was expanded to nine. She is the keeper of what happened and why — not a log, not
an audit trail, but the *distilled narrative* of experience.

In Perseus, Mnēmē is the layer that maintains a living narrative of each workspace: what was
built, what was decided, what was learned, what failed, and why things are the way they are.
She answers the question no snapshot can: *how did we get here?*

---

## The Problem

Perseus gives an assistant an accurate snapshot of *current state* — what's running, what
skills are loaded, what the last checkpoint was. What it cannot give is *arc*: the decisions
made three weeks ago, the approach that was tried and rejected, the constraint added after a
painful bug. Without arc, every session on a mature project starts with orientation debt that
no amount of snapshot freshness can repay.

The raw material already exists: checkpoints accumulate task history, the oracle log captures
every Pythia recommendation and whether it was accepted, session digests carry the project's
active threads. Nobody is distilling it. Mnēmē distills it.

---

## What Mnēmē Is Not

- **Not a log viewer.** `oracle_log.jsonl` and checkpoint files are the raw sources. Mnēmē
  reads them; it does not replace them.
- **Not a daemon.** No background process. No file watchers. No scheduler.
  Update is explicit: triggered by the user or by `perseus checkpoint` as a side-effect.
- **Not an LLM requirement.** Two modes — deterministic and LLM-assisted. The deterministic
  mode must be genuinely useful, not a stub.
- **Not a separate file.** Single-file constraint is absolute. All Mnēmē code lives in
  `perseus.py`.

---

## Storage

### Per-workspace narrative file

```
~/.perseus/memory/<workspace-hash>.md
```

`workspace-hash` is `sha256(str(workspace_path.resolve()))[:12]` — same algorithm used in
task-07 for checkpoint namespacing. Consistent across sessions for the same path.

### Narrative file format

The file is a standard markdown document with a YAML frontmatter block. It must be readable
by a human, renderable by GitHub, and parseable by Perseus.

```markdown
---
schema: 1
workspace: /workspace/perseus
workspace_hash: a3f9c12b8e44
updated: 2026-05-18T14:32:00-05:00
checkpoints_processed: 47
oracle_entries_processed: 312
compaction_count: 2
---

# Mnēmē — /workspace/perseus

> Narrative last updated 2026-05-18 14:32 CT.
> Source: 47 checkpoints, 312 oracle entries.
> Run `perseus memory compact` for a full re-distillation.

## Project Arc

[2–4 sentences: what this project is and what it has accomplished. LLM-written when
available; deterministically assembled from checkpoint task fields when not.]

## Key Decisions

[Structured list of significant decisions, with approximate dates and reasoning.
LLM-extracted from checkpoint notes and oracle log accepted/rejected patterns.
Deterministic fallback: extracted from checkpoint `notes` fields containing
decision-language keywords: "renamed", "rejected", "switched", "decided", "constraint".]

- **2026-05-15** — Renamed oracle → Pythia (trademark risk: Oracle Corp)
- **2026-05-18** — Single-file constraint established; no package splits

## Task History

[Compact chronological record of completed work. One line per checkpoint cluster.
LLM: distilled from task+status+next chains. Deterministic: grouped by date, one
entry per unique task value.]

| Date | Task | Outcome |
|---|---|---|
| 2026-05-15 | Phase 1: Pythia skill loop | Complete |
| 2026-05-18 | Phase 5A: --llm flag + oracle log | Complete |

## Patterns & Anti-patterns

[Accumulated tooling patterns that worked and approaches that were abandoned.
LLM: extracted from oracle log accepted/rejected entries and checkpoint notes.
Deterministic: oracle accepted=true entries bucketed by skill/tool name.]

## Recent Activity

[Last N checkpoints verbatim — not distilled. These are the raw recent entries.
This section is always deterministic, even in LLM mode. N = memory.recent_keep config.]

### 2026-05-18T1432 — Phase 5B Agora
- **Task:** Implement Agora async coordination substrate
- **Status:** complete — agora subcommand + @agora directive shipped
- **Next:** task-05 context health
```

---

## Configuration

Add a `memory` block to `DEFAULT_CONFIG`:

```python
"memory": {
    "store": str(PERSEUS_HOME / "memory"),
    "recent_keep": 5,           # how many raw checkpoints to include in Recent Activity
    "auto_update": True,        # update narrative on every checkpoint write
    "compact_threshold": 20,    # auto-compact after this many incremental updates since last compaction
    "llm_provider": None,       # None = deterministic; "ollama" / "openai-compat" = LLM-assisted
    "llm_model": None,          # inherits from llm: block if None
    "max_narrative_lines": 300, # warn (not error) if narrative grows beyond this
},
```

The `llm_provider` key defaults to `None` — deterministic mode — so Mnēmē works for every
user without any LLM setup. LLM-assisted mode is opt-in.

---

## CLI Interface

### `perseus memory update [--workspace <path>] [--llm <provider>]`

Incremental update. Reads new checkpoints and oracle entries since the last high-water mark
and incorporates them into the narrative. Does not re-distill existing content.

```bash
perseus memory update
perseus memory update --workspace /workspace/perseus
perseus memory update --llm ollama
```

**Algorithm:**
1. Load or initialize the narrative file for the workspace
2. Read `checkpoints_processed` and `oracle_entries_processed` from frontmatter
3. Load all checkpoint files sorted by filename; slice from `checkpoints_processed` onward
4. Load all oracle log entries; slice from `oracle_entries_processed` onward
5. If no new data: print "Nothing new since last update." and exit
6. If LLM available: call `_mneme_update_llm(narrative, new_checkpoints, new_oracle_entries, cfg)`
7. If no LLM: call `_mneme_update_deterministic(narrative, new_checkpoints, new_oracle_entries)`
8. Update frontmatter high-water marks and `updated` timestamp
9. Write back to narrative file
10. If `compaction_count` increments since last compaction ≥ `compact_threshold`: print
    advisory "Narrative has N incremental updates. Consider running `perseus memory compact`."

### `perseus memory compact [--workspace <path>] [--llm <provider>]`

Full re-distillation. Re-reads all sources and rebuilds the narrative from scratch.
Increments `compaction_count`. Use after significant project milestones.

```bash
perseus memory compact
perseus memory compact --llm ollama
```

### `perseus memory show [--workspace <path>]`

Print the current narrative to stdout. No modification.

### `perseus memory query "<question>" [--workspace <path>] [--llm <provider>]`

Answer a natural-language question about the project's history.

```bash
perseus memory query "why did we rename oracle to Pythia"
perseus memory query "what approaches have we tried for caching"
```

**Without LLM:** grep-style search of the narrative file; returns matching sections with
context lines. Useful, not intelligent.

**With LLM:** sends the full narrative + query to `run_llm` with a focused answer prompt.
Does NOT append to oracle log — this is a read-only query, not an oracle recommendation.

### `perseus memory status [--workspace <path>]`

Print a summary: narrative age, high-water marks, compaction count, estimated size.

```
Mnēmē — /workspace/perseus
  Updated:     2026-05-18 14:32 CT (2h ago)
  Checkpoints: 47 processed (0 pending)
  Oracle log:  312 entries processed (0 pending)
  Compactions: 2
  Size:        187 lines
  Mode:        deterministic (set memory.llm_provider to enable LLM distillation)
```

---

## `@memory` Renderer Directive

Add `@memory` to the renderer. Reads the narrative file for the inferred workspace and
injects it inline.

```
@memory
@memory focus="decisions"
@memory focus="recent"
@memory ttl=3600
@memory @cache ttl=3600
```

**Arguments:**

| Arg | Values | Description |
|---|---|---|
| `focus` | `"decisions"`, `"recent"`, `"patterns"`, `"arc"` | Emit only the named section |
| `ttl` | integer (seconds) | Short-form cache: equivalent to `@cache ttl=N` |

**No narrative exists yet:**
```markdown
> ⚠ No Mnēmē narrative found for this workspace.
> Run `perseus memory update` to initialize.
```

**Narrative exists but is stale (age > `checkpoints.ttl_s`):**
```markdown
> ⚠ Mnēmē narrative is stale (last updated 3d ago).
> Run `perseus memory update` to refresh.
```

---

## Internal Functions

These are the private functions to implement. Public surface is the `cmd_memory` dispatch
and `resolve_memory` directive handler.

### `_workspace_hash(workspace: Path) -> str`

```python
def _workspace_hash(workspace: Path) -> str:
    import hashlib
    return hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:12]
```

Note: task-07 (multi-workspace checkpoint namespacing) uses the same algorithm. If task-07
has already landed, reuse its implementation. If not, define this helper once here — task-07
will import it.

### `_mneme_path(workspace: Path, cfg: dict) -> Path`

Returns `Path(cfg["memory"]["store"]) / f"{_workspace_hash(workspace)}.md"`.

### `_load_narrative(path: Path) -> tuple[dict, str]`

Load the narrative file. Returns `(frontmatter_dict, body_str)`. If file doesn't exist,
returns `({}, "")`. Parse frontmatter using the same `---` fenced YAML block pattern used
in Agora task parsing.

### `_save_narrative(path: Path, frontmatter: dict, body: str) -> None`

Write narrative file atomically (write to `.tmp`, rename). Frontmatter is serialized as
YAML between `---` fences.

### `_deterministic_narrative(checkpoints: list[dict], oracle_entries: list[dict], existing_body: str, cfg: dict) -> str`

Build or update the narrative body deterministically (no LLM). Called by both `update`
and `compact`. When called from `update`, `existing_body` contains the current narrative
and only new data should be incorporated. When called from `compact`, `existing_body` is
empty and all sources are processed fresh.

**Deterministic rules:**

*Project Arc:* The first sentence is `"Project at {workspace} — {N} checkpoints recorded
over {date_span}."` The second sentence is the most recent checkpoint `task` field prefixed
with `"Most recently: "`.

*Key Decisions:* Scan all checkpoint `notes` fields for sentences containing any of:
`["renamed", "rejected", "switched", "decided", "constraint", "must not", "never", "always",
"chose", "replaced"]`. Extract the full sentence. Deduplicate by normalized lowercase. List
chronologically with the checkpoint `written` date truncated to YYYY-MM-DD.

*Task History:* Group checkpoints by unique `task` value. For each group, use the earliest
`written` date and the latest `status` value. Render as the markdown table shown in the
schema example above.

*Patterns & Anti-patterns:* From the oracle log, collect all entries where `accepted=true`.
Count by the first word of `response` that matches a known skill/tool prefix
(`skill:`, `web_`, `terminal`, `delegate`, `cron`). Render as a bullet list: 
`- **{tool}** — used {N} times (last: {date})`.

*Recent Activity:* The last `memory.recent_keep` checkpoints verbatim (formatted as the
schema example shows). Always re-rendered from scratch on every update/compact.

### `_mneme_update_llm(narrative_body: str, frontmatter: dict, new_checkpoints: list[dict], new_oracle_entries: list[dict], cfg: dict) -> str`

LLM-assisted incremental update. Builds a prompt that contains:
1. The existing narrative body (if any)
2. New checkpoints since last update (YAML-formatted)
3. New oracle entries since last update (JSON-formatted, truncated to key fields)
4. Instruction: update the narrative in-place, preserving existing structure, incorporating
   new information without duplication

Returns the updated narrative body string.

**Prompt template** (implement this verbatim — do not paraphrase):

```
You are Mnēmē, the keeper of project narrative for an AI development workflow.

Your job: update a structured project narrative by incorporating new activity.
Preserve all existing content unless it directly contradicts new information.
Do not invent content. Do not pad. Be terse and factual.

EXISTING NARRATIVE:
{existing_body or "(none — initialize from scratch)"}

NEW CHECKPOINTS ({len(new_checkpoints)} since last update):
{yaml_formatted_checkpoints}

NEW ORACLE LOG ENTRIES ({len(new_oracle_entries)} since last update):
{json_formatted_oracle_entries_key_fields_only}

INSTRUCTIONS:
- Update the "Project Arc" section if the recent work represents a significant milestone
- Add new entries to "Key Decisions" if checkpoint notes contain decision language
- Update "Task History" table with any newly completed tasks
- Update "Patterns & Anti-patterns" based on accepted oracle entries
- Rewrite "Recent Activity" with the {recent_keep} most recent checkpoints
- Return ONLY the updated markdown body. No preamble. No commentary. Start with "## Project Arc".
```

### `_mneme_compact_llm(all_checkpoints: list[dict], all_oracle_entries: list[dict], workspace: Path, cfg: dict) -> str`

LLM-assisted full compaction. Like `_mneme_update_llm` but processes all sources fresh.
Prompt is similar but instructs the LLM to build the narrative from scratch rather than
update an existing one.

---

## Auto-update on Checkpoint Write

When `memory.auto_update` is `True` (the default), `cmd_checkpoint` calls
`cmd_memory_update_silent(workspace, cfg)` after writing the checkpoint.

`cmd_memory_update_silent` is identical to `cmd_memory update` except:
- It prints nothing on success (silent side-effect)
- On any error: print a single warning line `"> ⚠ Mnēmē update failed: {exc}"` — never
  raise or abort the checkpoint write

This is the compounding behavior: every checkpoint automatically advances the narrative
without user intervention.

---

## Design Constraints (all inherited from ROADMAP.md)

- **Single-file.** All code in `perseus.py`. No exceptions.
- **`pyyaml` is the only dependency.** `hashlib`, `json`, `os`, `pathlib`, `re` are all
  stdlib — use them freely.
- **Deterministic mode must be genuinely useful.** LLM mode is opt-in. The test suite must
  not require Ollama.
- **Narrative write is atomic.** Use write-to-temp + rename pattern. Partial writes must
  not corrupt the narrative.
- **Read-only query.** `perseus memory query` does not modify the narrative or oracle log.
- **Backward compatible.** Mnēmē is additive. Users without a narrative file see no
  behavioral change in existing commands (except the silent `auto_update` side-effect on
  `checkpoint`, which produces no output on success).

---

## Acceptance Criteria

- [ ] `perseus memory update` runs without error on a fresh workspace (no existing narrative)
- [ ] `perseus memory update` runs without error when called repeatedly (idempotent)
- [ ] Second call to `perseus memory update` with no new checkpoints prints "Nothing new"
- [ ] `perseus memory compact` rebuilds narrative from all sources
- [ ] `perseus memory show` prints current narrative to stdout
- [ ] `perseus memory status` prints summary with correct counts
- [ ] `perseus memory query "text"` returns matching sections in deterministic mode
- [ ] `@memory` directive renders the narrative inline
- [ ] `@memory focus="decisions"` renders only the Key Decisions section
- [ ] `@memory` with no narrative file renders the "no narrative" warning
- [ ] `@memory` with stale narrative renders the staleness warning
- [ ] `cmd_checkpoint` silently calls memory update when `memory.auto_update=True`
- [ ] `cmd_checkpoint` does not abort or print errors if memory update fails
- [ ] `_workspace_hash` returns a 12-char hex string, stable for the same path
- [ ] Narrative file has valid YAML frontmatter with all required keys
- [ ] Narrative file write is atomic (temp + rename)
- [ ] Tests cover: hash stability, narrative init, incremental update (deterministic),
  compact (deterministic), `@memory` directive (no narrative / stale / fresh / focus),
  auto-update side-effect on checkpoint, silent failure on memory error
- [ ] `spec/components.md` updated: Mnēmē added to components table
- [ ] `spec/directives.md` updated: `@memory` added to directive reference
- [ ] `spec/data-model.md` updated: narrative file schema + memory store layout documented
- [ ] `ROADMAP.md` updated: Phase 7 Mnēmē section added, directive table updated

---

## Notes for the Implementer

**On the incremental update algorithm:** The high-water marks (`checkpoints_processed`,
`oracle_entries_processed`) are integer counts, not timestamps. Checkpoints are sorted by
filename (deterministic, as established in the checkpoint sort fix). Oracle entries are
read sequentially from the JSONL file. On update, slice `checkpoints[hwm:]` and
`oracle_entries[hwm:]`. On write, set `hwm = total_count`. This is simpler and more robust
than timestamp-based tracking.

**On the compaction trigger:** The `compact_threshold` check happens *after* writing the
updated narrative, not before. Print an advisory only — do not auto-compact. The user
decides when to compact.

**On the LLM prompt oracle entries:** Truncate oracle entries to `{task, accepted, timestamp}`
only before sending to LLM — do not include `prompt` or `response` fields (too long). The
LLM needs to know what was tried and whether it worked, not the full oracle exchange.

**On `@memory @cache ttl=N`:** The standard `@cache` modifier applies normally. The short
`ttl=` argument on `@memory` itself is syntactic sugar — `@memory ttl=3600` is equivalent
to `@memory @cache ttl=3600`. Implement the sugar as a pre-processing step in
`resolve_memory`.

**On the `focus=` argument:** Implement by extracting the named `##` section from the
narrative body using a simple heading-to-heading slice. If the section doesn't exist,
render an empty advisory rather than an error.

**Start here:**
1. `_workspace_hash` — five lines
2. `_mneme_path` — two lines
3. `_load_narrative` / `_save_narrative` — the atomic I/O primitives
4. `_deterministic_narrative` — the workhorse; implement and test this in full before
   touching LLM paths
5. `cmd_memory` dispatch with all subcommands wired to stubs
6. `resolve_memory` directive handler
7. `cmd_checkpoint` auto-update side-effect
8. LLM paths last — they require Ollama and can't be unit-tested without mocking

The tests for deterministic mode must cover everything. LLM mode tests may use mocks.
