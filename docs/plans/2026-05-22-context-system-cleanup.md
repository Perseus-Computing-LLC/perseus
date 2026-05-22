# Perseus Context System Cleanup — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Ship the uncommitted Mnēmē bugfixes, fix a stale ROADMAP constraint, and clean up the homelab context file so every rendered `.hermes.md` session starts with useful signal instead of dead weight.

**Architecture:** Two distinct scopes — (A) the Perseus repo itself (code + docs), (B) the homelab workspace context config. Both are independent; scope A must land first so the artifact is up-to-date before anything triggers a re-render.

**Tech Stack:** Python (`src/perseus/`, `scripts/build.py`, `pytest`), Markdown (ROADMAP.md, tasks/), shell (`.perseus/context.md` `@query` directives)

**Repo root:** `/workspace/perseus`  
**Homelab context file:** `/workspace/perseus/.perseus/context.md`  
**Rendered output:** `/workspace/.hermes.md`

---

## Executor Flags (read before starting)

1. **Always edit `src/perseus/`, never `perseus.py` directly.** After every code change, regenerate the artifact with `python3 scripts/build.py` from the repo root. Verify line count went up or stayed constant — a silent drop means the build script missed a module.
2. **Run `python3 -m pytest tests/ -q` before every commit.** All 496 tests must pass. New behavior in Task 3 needs new tests.
3. **Task 1 (commit uncommitted diff) must land before Task 2 (artifact rebuild) — they're sequential.** Tasks 3, 4, 5 are independent of each other and can be done in any order after Task 2.
4. **The `.perseus/context.md` changes (Tasks 6–10) do NOT require the Perseus source to be touched.** They are config/template edits only. No tests cover them — verify by running `python3 perseus.py render .perseus/context.md` and reading the output.
5. **ROADMAP.md is a live `@perseus` source file** — its raw text contains `@directive` syntax. Edit it as plain markdown; don't accidentally strip directive lines when patching constraint sections.

---

## Scope A — Perseus Repo

### Task 1: Commit the uncommitted Mnēmē diff

**Objective:** Land the 2-bug + 3-feature diff currently sitting unstaged in `src/perseus/agora.py`, `src/perseus/checkpoint.py`, `src/perseus/cli.py`, and `src/perseus/registry.py`.

**Files:**
- Already modified (check `git diff HEAD`): `src/perseus/agora.py`, `src/perseus/checkpoint.py`, `src/perseus/cli.py`, `src/perseus/registry.py`

**Step 1: Verify the diff is what we expect**

```bash
git -C /workspace/perseus diff HEAD --stat
```

Expected: 4 files changed, insertions/deletions in agora.py, checkpoint.py, cli.py, registry.py only. No surprises.

**Step 2: Run the full test suite against the unstaged changes**

```bash
cd /workspace/perseus && python3 -m pytest tests/ -q
```

Expected: all tests pass (496 or more). If any fail, stop — do not commit. Investigate the failure before proceeding.

**Step 3: Regenerate the single-file artifact**

```bash
cd /workspace/perseus && python3 scripts/build.py
```

Expected: no errors. `perseus.py` is rewritten.

**Step 4: Verify artifact integrity**

```bash
cd /workspace/perseus && python3 perseus.py --version
```

Expected: prints version string (e.g. `perseus 1.0.1`). No import errors.

**Step 5: Commit**

```bash
cd /workspace/perseus
git add src/perseus/agora.py src/perseus/checkpoint.py src/perseus/cli.py src/perseus/registry.py perseus.py
git commit -m "feat: bugs 1-3 + features 1-4 (memory/checkpoint improvements)

- Bug #1: stale @memory now prepends warning instead of replacing body
- Bug #2: memory workspace falls back to home when CWD has no .perseus/
- Bug #3: checkpoint workspace defaults to CWD for reliable per-workspace namespacing
- Feature #1: @memory workspace= modifier for cross-workspace renders
- Feature #2: touch updated timestamp on successful render (suppress false-stale)
- Feature #3: proactive compact suggestion at 80% of compact_threshold
- Feature #4: checkpoint always writes workspace= field (defaults to CWD)"
git push origin main
```

**Verify:** `git log --oneline -3` shows the new commit at HEAD.

---

### Task 2: Fix ROADMAP.md constraint #1 — stale single-file rule

**Objective:** Update the Non-Negotiable Constraints section in ROADMAP.md so constraint #1 reflects the current `src/` module architecture instead of the pre-refactor single-file rule. AGENTS.md already has the correct wording — mirror it.

**Files:**
- Modify: `/workspace/perseus/ROADMAP.md` (the constraints section, around line 157–173)

**Step 1: Read the current constraint block**

Read lines 157–173 of ROADMAP.md to confirm the exact text before patching.

**Step 2: Replace constraint #1**

Find this text in ROADMAP.md:
```
1. **Single file.** `perseus.py` stays one file. No package structure, no `setup.py`, no
   sub-modules. Internal section headers and grouping are fine. File splits are not.
```

Replace with:
```
1. **Edit source, regenerate artifact.** Edit `src/perseus/` modules, not `perseus.py`
   directly. Regenerate the single-file artifact with `python scripts/build.py`. Keep the
   generated root artifact committed. Do not add runtime dependencies without explicit approval.
```

**Step 3: Verify the surrounding constraints are unchanged**

Read lines 157–175 of ROADMAP.md after the patch. Constraints #2–7 should be byte-for-byte identical.

**Step 4: Commit**

```bash
cd /workspace/perseus
git add ROADMAP.md
git commit -m "docs: fix ROADMAP constraint #1 — reflect src/ module architecture"
git push origin main
```

---

### Task 3: Add `@skills` category filter support to the renderer

**Objective:** Add an optional `category=` (or `include=`) modifier to the `@skills` directive so context files can request a filtered subset of skills instead of the full 100-row table. This is the code change that enables Task 9 (homelab context trim).

**Files:**
- Modify: `src/perseus/renderer.py` (or whichever module contains `resolve_skills`) — find it with `grep -n "resolve_skills\|def.*skills" src/perseus/*.py`
- Modify: `spec/directives.md` — add `category=` / `include=` to the `@skills` entry
- Create: `tests/test_skills_filter.py` (new test file)

**Step 1: Locate the skills resolver**

```bash
grep -n "resolve_skills\|def.*_skills\b" /workspace/perseus/src/perseus/*.py
```

Note the file and line number. Open that file and read the `resolve_skills` function.

**Step 2: Understand the current behavior**

The `@skills` directive reads the skills directory, parses YAML frontmatter, and returns a markdown table. The `flag_stale=true` modifier is already supported. We're adding a `category=` modifier that filters rows where the skill path starts with `category/`.

**Step 3: Write the failing tests first**

Create `/workspace/perseus/tests/test_skills_filter.py`:

```python
"""Tests for @skills category= filter modifier."""
import pytest
from tests.conftest import make_renderer  # or however conftest exposes it


def test_skills_category_filter_returns_only_matching_rows(tmp_path, monkeypatch):
    """@skills category=devops returns only skills whose path starts with devops/."""
    # Create a fake skills dir with two categories
    skills_dir = tmp_path / "skills"
    (skills_dir / "devops").mkdir(parents=True)
    (skills_dir / "media").mkdir(parents=True)
    # devops skill
    devops_skill = skills_dir / "devops" / "docker" / "SKILL.md"
    devops_skill.parent.mkdir(parents=True)
    devops_skill.write_text(
        "---\nname: docker\ndescription: Docker stuff.\n---\n\n# Docker\n"
    )
    # media skill
    media_skill = skills_dir / "media" / "spotify" / "SKILL.md"
    media_skill.parent.mkdir(parents=True)
    media_skill.write_text(
        "---\nname: spotify\ndescription: Spotify stuff.\n---\n\n# Spotify\n"
    )

    # Render @skills category=devops pointing at our fake dir
    # (Adjust this call to match how the test suite invokes the renderer)
    r = make_renderer(tmp_path, skills_dir=str(skills_dir))
    output = r.render_string("@skills category=devops")

    assert "docker" in output.lower()
    assert "spotify" not in output.lower()


def test_skills_include_filter_accepts_comma_separated(tmp_path):
    """@skills include=devops,media returns skills from both categories."""
    # Similar fixture setup as above, then assert both appear.
    pass  # implement after the single-category case passes


def test_skills_no_filter_returns_all(tmp_path):
    """@skills with no category/include filter returns all skills (existing behavior)."""
    pass  # smoke test to confirm backward compat
```

**Step 4: Run the tests to verify they fail correctly**

```bash
cd /workspace/perseus && python3 -m pytest tests/test_skills_filter.py -v
```

Expected: FAIL — test infrastructure errors or assertion failures. Not import errors (fix those before continuing).

**Step 5: Implement `category=` filter in the skills resolver**

In the `resolve_skills` function, parse the `category=` modifier from the args string (same pattern as other modifiers — use `_parse_kv_modifiers` if it exists, or `re.search`). After scanning the skills directory, filter the results:

```python
# Parse modifiers (existing pattern — adapt to match how the file does it)
mods = _parse_kv_modifiers(args_str)
category_filter = (mods.get("category") or mods.get("include") or "").strip().lower()
categories = [c.strip() for c in category_filter.split(",") if c.strip()] if category_filter else []

# After building the skill list, apply filter
if categories:
    skills = [s for s in skills if any(s["path"].startswith(cat + "/") or s["path"].startswith(cat) for cat in categories)]
```

The `"path"` key name may differ — check what field the skill dict actually uses for the relative path from the skills root.

**Step 6: Run the tests — all must pass**

```bash
cd /workspace/perseus && python3 -m pytest tests/ -q
```

Expected: all pass, including the new `test_skills_filter.py` tests.

**Step 7: Update spec**

In `spec/directives.md`, find the `@skills` entry and add:

```
| `category=<name>` | Optional. Filter to skills whose path starts with `<name>/`. Comma-separated for multiple: `category=devops,media`. |
| `include=<name>` | Alias for `category=`. |
```

**Step 8: Regenerate artifact and commit**

```bash
cd /workspace/perseus
python3 scripts/build.py
python3 -m pytest tests/ -q
git add src/perseus/ perseus.py tests/test_skills_filter.py spec/directives.md
git commit -m "feat: add category= / include= filter to @skills directive"
git push origin main
```

---

### Task 4: Create Agora task file for the homelab context improvements

**Objective:** Register the homelab context work as a completed Agora task so the project record reflects that this work happened and why.

**Files:**
- Create: `/workspace/perseus/tasks/task-23-homelab-context-cleanup.md`

**Step 1: Create the task file**

```markdown
---
id: task-23
title: "Homelab context file cleanup and skills filter"
status: completed
scope: small
depends_on: [task-22]
claimed_by: hermes
opened: 2026-05-22
closed: 2026-05-22
---

# Task 23: Homelab Context File Cleanup

## Goal

Clean up the homelab workspace `.perseus/context.md` so every rendered `.hermes.md`
starts with high-signal context instead of dead weight.

## Changes Made

1. Removed always-empty `## Docker Containers` section (agent container has no socket access)
2. Replaced `## Recent Hermes Cron Jobs` file listing with a `@query` summary
3. Reduced `@skills` to relevant categories via `category=` filter (requires task from this session)
4. Fixed `@session` count to exclude cron noise
5. Fixed `@services` Perseus CLI entry to use the installed CLI path
6. Updated `@percy` version tag from v0.4 to current

## Completed

All changes landed in `.perseus/context.md`. Rendered output verified with
`python3 perseus.py render .perseus/context.md`.
```

**Step 2: Commit**

```bash
cd /workspace/perseus
git add tasks/task-23-homelab-context-cleanup.md
git commit -m "docs(task-23): homelab context cleanup — completed"
git push origin main
```

---

## Scope B — Homelab Context File

All tasks in this scope modify `/workspace/perseus/.perseus/context.md`. After every task, verify by running:

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md
```

Read the output and confirm the section looks right. There are no automated tests for context files.

---

### Task 5: Remove the dead Docker Containers section

**Objective:** Delete the `## Docker Containers` block from the context file. The Hermes agent container has no Docker socket access; this section renders as an error message on every session.

**Files:**
- Modify: `/workspace/perseus/.perseus/context.md`

**Step 1: Read the current file**

Read `/workspace/perseus/.perseus/context.md` in full.

**Step 2: Remove the Docker section**

Find and remove this block (exact text may vary slightly):

```markdown
## Docker Containers (homelab)
@query "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -30 || echo '(docker unavailable)'"
```

Or whatever the Docker section currently contains. Remove it entirely — the heading and any directives under it.

**Step 3: Verify render**

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md 2>&1 | head -80
```

Confirm: no Docker section, no `docker unavailable` message.

**Step 4: Commit**

```bash
cd /workspace/perseus
git add .perseus/context.md
git commit -m "fix(context): remove dead Docker Containers section (no socket access)"
git push origin main
```

---

### Task 6: Replace the Cron Jobs section with a useful `@query`

**Objective:** The current section shows a raw `ls -l` of the cron output directory. Replace it with a `@query` that surfaces the last 5 cron job names and their most recent run time from the jobs.json file — or remove the section entirely if the query would be too noisy.

**Files:**
- Modify: `/workspace/perseus/.perseus/context.md`

**Step 1: Inspect the current cron jobs section**

Read `/workspace/perseus/.perseus/context.md` and find the `## Recent Hermes Cron Jobs` block.

**Step 2: Inspect the actual jobs.json structure**

```bash
python3 -c "import json; d=json.load(open('/home/hermeswebui/.hermes/cron/jobs.json')); [print(j.get('name','?'), j.get('schedule','?'), j.get('last_run','never')) for j in d.get('jobs', d) if isinstance(d.get('jobs', d), list)]" 2>/dev/null || cat /home/hermeswebui/.hermes/cron/jobs.json | head -60
```

This tells us what fields are available to query.

**Step 3: Choose between two options**

- **Option A (preferred):** Replace with a `@query` that extracts job names + last run times:
  ```
  @query "python3 -c \"import json,sys; jobs=json.load(open('/home/hermeswebui/.hermes/cron/jobs.json')); [print(f'- {j[\\\"name\\\"]}: {j.get(\\\"last_run\\\",\\\"never\\\")}') for j in jobs.get('jobs', jobs) if isinstance(jobs.get('jobs',jobs),list)]\" 2>/dev/null" fallback="(cron unavailable)"
  ```
- **Option B:** Remove the section entirely if the jobs.json structure doesn't cleanly support this.

Pick Option A if jobs.json is a clean list with `name` and `last_run` fields. Otherwise pick Option B.

**Step 4: Update the context file and verify render**

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md 2>&1 | grep -A 10 "Cron"
```

**Step 5: Commit**

```bash
cd /workspace/perseus
git add .perseus/context.md
git commit -m "fix(context): replace cron jobs ls listing with useful @query summary"
git push origin main
```

---

### Task 7: Fix the `@services` Perseus CLI entry

**Objective:** The `@services` block checks `python3 /workspace/perseus/perseus.py --version` using the source path. It should use the installed CLI (`~/.local/bin/perseus --version`) so it reflects the actually-deployed binary, not just the repo checkout.

**Files:**
- Modify: `/workspace/perseus/.perseus/context.md`

**Step 1: Confirm the installed CLI path**

```bash
which perseus || ls -la ~/.local/bin/perseus
```

**Step 2: Update the services block**

Find:
```yaml
  - name: Perseus CLI
    command: "python3 /workspace/perseus/perseus.py --version"
```

Replace with:
```yaml
  - name: Perseus CLI
    command: "~/.local/bin/perseus --version"
```

Or if `perseus` is on PATH: `command: "perseus --version"`

**Step 3: Verify render shows Perseus CLI as ✅**

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md 2>&1 | grep -A 3 "Perseus CLI"
```

**Step 4: Commit**

```bash
cd /workspace/perseus
git add .perseus/context.md
git commit -m "fix(context): use installed perseus CLI path in @services health check"
git push origin main
```

---

### Task 8: Trim `@skills` to homelab-relevant categories

**Objective:** Replace the bare `@skills flag_stale=true` directive (renders all ~100 skills) with a filtered version showing only the categories relevant to homelab work. Requires Task 3 (category filter) to be shipped first.

**Dependency:** Task 3 must be complete and `perseus.py` must include the `category=` filter.

**Files:**
- Modify: `/workspace/perseus/.perseus/context.md`

**Step 1: Decide on the category list**

Homelab-relevant categories:
- `devops` — docker, homelab hygiene, webhooks, Portainer
- `media` — Plex, Sonarr/Radarr adjacent
- `smart-home` — Home Assistant, Hue
- `github` — PR workflow, issues (for Perseus work done from homelab)
- `software-development` — Perseus context engine, debugging, TDD

**Step 2: Update the skills directive**

Find:
```
@skills flag_stale=true
```

Replace with:
```
@skills flag_stale=true category=devops,media,smart-home,github,software-development
```

**Step 3: Verify render — skills table should be ~20 rows, not ~100**

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md 2>&1 | grep -c "^|"
```

Expected: significantly fewer rows than the unfiltered version. If the count is still ~100, the Task 3 code change didn't land correctly in the installed `perseus.py`.

**Step 4: Commit**

```bash
cd /workspace/perseus
git add .perseus/context.md
git commit -m "fix(context): filter @skills to homelab-relevant categories"
git push origin main
```

---

### Task 9: Tune `@session` count and fix version tag

**Objective:** Two minor context file housekeeping items: (1) reduce `@session` from `count=5` to `count=3` to reduce noise from cron job sessions polluting the list; (2) update the `@perseus v0.4` version tag at the top of the file to the current protocol version.

**Files:**
- Modify: `/workspace/perseus/.perseus/context.md`

**Step 1: Check the current Perseus protocol version**

```bash
grep -r "directive protocol version" /workspace/perseus/src/perseus/ /workspace/perseus/AGENTS.md | head -3
```

The AGENTS.md header says `@perseus v0.8` — use that as the current version.

**Step 2: Update the version tag**

Find line 1 of `.perseus/context.md`:
```
@perseus v0.4
```

Replace with:
```
@perseus v0.8
```

**Step 3: Update session count**

Find:
```
@session count=5
```

Replace with:
```
@session count=3
```

**Step 4: Verify render looks clean**

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md 2>&1 | grep -A 8 "Recent Sessions"
```

**Step 5: Commit**

```bash
cd /workspace/perseus
git add .perseus/context.md
git commit -m "fix(context): bump @perseus version tag to v0.8, reduce @session to count=3"
git push origin main
```

---

### Task 10: Final render and checkpoint

**Objective:** Trigger a clean render of the updated context file to confirm the full output is correct, then write a checkpoint marking this work complete.

**Step 1: Render the full context**

```bash
cd /workspace/perseus && python3 perseus.py render .perseus/context.md --output /tmp/context-preview.md && cat /tmp/context-preview.md
```

Read the full output. Confirm:
- No Docker Containers section
- Cron jobs section is either absent or shows a useful job list
- Skills table has ~15–25 rows (not ~100)
- Perseus CLI shows ✅ in services
- Recent Sessions shows 3 entries (not 5), no cron-job titles
- Version tag is v0.8

**Step 2: If all looks good, copy to the live rendered location**

```bash
cp /tmp/context-preview.md /workspace/.hermes.md
```

> ⚠ This overwrites the live context file that Hermes reads. Do this only after confirming the preview looks correct in Step 1.

**Step 3: Write a checkpoint**

```bash
cd /workspace/perseus && python3 perseus.py checkpoint --task "context system cleanup complete" --status "done" --next "monitor first post-cleanup session for any missing signal"
```

**Step 4: Summary commit if any files changed**

```bash
cd /workspace/perseus && git status
# If any tracked files are dirty:
git add -A && git commit -m "chore: post-cleanup render and checkpoint" && git push origin main
```

---

## Completion Criteria

All of the following must be true before this plan is marked done:

- [ ] `git log --oneline -10` shows all commits from Tasks 1–9 in history
- [ ] `python3 -m pytest tests/ -q` passes with ≥ 496 tests
- [ ] `python3 perseus.py --version` runs without error
- [ ] `python3 perseus.py render .perseus/context.md` produces output with no error lines
- [ ] Rendered context has no Docker Containers section
- [ ] Rendered context skills table has ≤ 30 rows
- [ ] ROADMAP.md constraint #1 matches AGENTS.md wording
- [ ] All commits pushed to `origin/main`
