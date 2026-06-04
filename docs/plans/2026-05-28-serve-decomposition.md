# Serve.py Decomposition Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Split `src/perseus/serve.py` (~2,994 lines) into focused modules so it is no longer the monolithic gatekeeper for unrelated surfaces.

**Architecture:** Extract four new modules — `synthesis.py` (cited synthesis), `scheduler.py` (cron/systemd/launchd), `doctor.py` (health/doctor/trust), `update.py` (self-update) — leaving `serve.py` as the HTTP/LSP transport + render orchestration (~1,700 lines). Each new module is a single Python file; no new directories. The build script (`scripts/build.py`) module order is updated to insert the new modules before `serve.py`.

**Tech Stack:** Python 3.10+, stdlib only. No new dependencies.

**Line count targets (before/after):**
- `serve.py`: 2,994 → ~1,700
- `synthesis.py`: new, ~420 lines
- `scheduler.py`: new, ~290 lines
- `doctor.py`: new, ~550 lines
- `update.py`: new, ~170 lines

---

## Executor Flags

1. **Import discipline:** Every `from perseus.X import Y` between the new modules and existing code is stripped by the build script. All cross-module references use bare names — they are resolved at concatenation time. Do NOT add import lines inside functions.
2. **Stdlib imports:** `__init__.py` already imports `re`, `json`, `os`, `sys`, `time`, `hashlib`, `subprocess`, `pathlib.Path`, etc. at the top of the artifact. New modules must NOT re-import these at module level — the concatenation provides them. Local imports inside functions are OK only for modules NOT already in `__init__.py`.
3. **Line-count assertion:** `scripts/build.py` has a baseline of 14,957 lines with a ±3% drift window. After this decomposition, update `BASELINE_LINES` to the new actual count. If the window fires, the build fails — adjust the baseline, don't widen the window.
4. **Smoke test timing:** Run `perseus --version` after every task that touches module order or extracted code. Don't wait until the end.
5. **Build order is canonical:** The build script's `MODULE_ORDER` list determines concatenation order. New modules must appear BEFORE `serve.py` since `serve.py` references their symbols.

---

### Task 1: Create `src/perseus/synthesis.py`

**Objective:** Extract the cited synthesis functions (lines 409–828 of serve.py).

**Files:**
- Create: `src/perseus/synthesis.py`
- Modify: `src/perseus/serve.py` (remove lines 409–828)
- Modify: `scripts/build.py` (add `synthesis.py` to MODULE_ORDER before serve.py)

**Step 1: Write the new module**

Create `src/perseus/synthesis.py` containing lines 409–828 of serve.py. This includes:
- `_synthesis_rel_label()` (L411)
- `_resolve_synthesis_source()` (L418)
- `_load_synthesis_sources()` (L433)
- `_numbered_source_excerpt()` (L460)
- `build_synthesis_prompt()` (L467)
- `_extract_json_object()` (L491)
- `_citation_window()` (L509)
- `build_consistency_prompt()` (L516)
- `_validate_consistency_conflicts()` (L544)
- `_validate_synthesis_claims()` (L598)
- `synthesize_question()` (L649)
- `format_synthesis_human()` (L743)
- `cmd_synthesize()` (L800)

The section header comment `# ───── Cited synthesis ─────` becomes the module's opening comment block.

**Step 2: Remove extracted code from serve.py**

Delete lines 409–828 (the entire Cited synthesis section including its header).

**Step 3: Add to build order**

In `scripts/build.py`, insert `"src/perseus/synthesis.py"` into `MODULE_ORDER` between `"src/perseus/memory.py"` and `"src/perseus/serve.py"`.

```python
    "src/perseus/mneme_federation.py",
    "src/perseus/inbox.py",
    "src/perseus/agora.py",
    "src/perseus/pythia.py",
    "src/perseus/lsp.py",
    "src/perseus/install.py",
    "src/perseus/synthesis.py",       # ← NEW
    "src/perseus/serve.py",
    "src/perseus/cli.py",
]
```

**Step 4: Build and smoke test**

```bash
python scripts/build.py
# Expected: Built perseus.py (N lines)
# Expected: Smoke test ok: perseus v1.0.5 — Patent Pending
python perseus.py --version
python -m pytest tests/test_synthesis.py -x -q
```

**Step 5: Commit**

```bash
git add src/perseus/synthesis.py src/perseus/serve.py scripts/build.py perseus.py
git commit -m "refactor: extract cited synthesis from serve.py into synthesis.py"
```

---

### Task 2: Create `src/perseus/scheduler.py`

**Objective:** Extract cron, systemd, and launchd scheduling commands (lines 1250–1537).

**Files:**
- Create: `src/perseus/scheduler.py`
- Modify: `src/perseus/serve.py` (remove lines 1250–1537)
- Modify: `scripts/build.py` (add `scheduler.py` before serve.py)

**Step 1: Write the new module**

Create `src/perseus/scheduler.py` containing:
- `cmd_launchd()` (L1250–1301)
- `cmd_cron()` (L1358–1431)
- `_parse_systemd_interval()` (L1459)
- `cmd_systemd()` (L1477–1537)

Include section header comments as found in serve.py.

**Step 2: Remove extracted code from serve.py**

Delete lines 1250–1537 (launchd through systemd sections).

**Step 3: Add to build order**

Insert `"src/perseus/scheduler.py"` before `serve.py` in MODULE_ORDER.

**Step 4: Build and smoke test**

```bash
python scripts/build.py
python -m pytest tests/ -x -q -k "not (lsp or mcp or serve)"  # smoke: skip integration tests
```

**Step 5: Commit**

```bash
git add src/perseus/scheduler.py src/perseus/serve.py scripts/build.py perseus.py
git commit -m "refactor: extract scheduler commands from serve.py into scheduler.py"
```

---

### Task 3: Create `src/perseus/doctor.py`

**Objective:** Extract health checks, doctor diagnostics, and trust commands (lines 1539–2081).

**Files:**
- Create: `src/perseus/doctor.py`
- Modify: `src/perseus/serve.py` (remove lines 1539–2081)
- Modify: `scripts/build.py` (add `doctor.py` before serve.py)

**Step 1: Write the new module**

Create `src/perseus/doctor.py` containing:
- Health section (L1539–1650): `_health_collect()`, `_health_report()`, `cmd_health()`, `resolve_health()`
- Doctor section (L1652–1884): `_find_version()`, `DoctorResult`, all `_doctor_check_*()` functions, `_effective_profile_summary()`
- Trust section (L1886–2032): `cmd_trust()`
- Doctor cmd (L2034–2081): `cmd_doctor()`

Note: `_find_version()` at L1654 is referenced by serve.py's `_serve_*` functions for the version banner. The concatenation handles this — serve.py will see the name because it's concatenated before serve.py.

**Step 2: Remove extracted code from serve.py**

Delete lines 1539–2081 (Health through cmd_doctor).

**Step 3: Add to build order**

Insert `"src/perseus/doctor.py"` before `serve.py`.

**Step 4: Build and smoke test**

```bash
python scripts/build.py
python perseus.py doctor
python perseus.py trust
python perseus.py health
python -m pytest tests/test_doctor.py tests/test_permission_profiles.py -x -q
```

**Step 5: Commit**

```bash
git add src/perseus/doctor.py src/perseus/serve.py scripts/build.py perseus.py
git commit -m "refactor: extract doctor/health/trust from serve.py into doctor.py"
```

---

### Task 4: Create `src/perseus/update.py`

**Objective:** Extract the self-update command (lines 2083–2254).

**Files:**
- Create: `src/perseus/update.py`
- Modify: `src/perseus/serve.py` (remove lines 2083–2254)
- Modify: `scripts/build.py` (add `update.py` before serve.py)

**Step 1: Write the new module**

Create `src/perseus/update.py` containing:
- `cmd_update()` (L2083–2192)
- `_find_perseus_repo()` (L2194–2214)
- `_toggle_auto_update()` (L2216–2254)

**Step 2: Remove extracted code from serve.py**

Delete lines 2083–2254.

**Step 3: Add to build order**

Insert `"src/perseus/update.py"` before `serve.py`.

**Step 4: Build and smoke test**

```bash
python scripts/build.py
python perseus.py update
```

**Step 5: Commit**

```bash
git add src/perseus/update.py src/perseus/serve.py scripts/build.py perseus.py
git commit -m "refactor: extract self-update from serve.py into update.py"
```

---

### Task 5: Update line-count baseline and full test suite

**Objective:** After all four extractions, update `BASELINE_LINES` in `scripts/build.py` and run the full test suite.

**Step 1: Get new line count**

```bash
wc -l perseus.py
# Example output: 15146 perseus.py
```

**Step 2: Update BASELINE_LINES**

In `scripts/build.py`, update line 87:

```python
BASELINE_LINES = 15146  # post-serve-decomposition
```

**Step 3: Full test suite**

```bash
python -m pytest tests/ -x -q --tb=short
# Expected: all passing, 1 skip (same as before)
```

**Step 4: Commit**

```bash
git add scripts/build.py
git commit -m "chore: update line-count baseline after serve.py decomposition"
```

---

### Task 6: Clean up — verify no dead references

**Objective:** Ensure no stale cross-references remain.

**Step 1: Search for references to moved functions**

```bash
grep -n 'synthesize_question\|cmd_synthesize\|cmd_launchd\|cmd_cron\|cmd_systemd\|cmd_health\|cmd_doctor\|cmd_trust\|cmd_update' src/perseus/serve.py
```

None of these should remain in serve.py.

**Step 2: Verify CLI dispatch still works**

```bash
python perseus.py --help
python perseus.py synthesize --help
python perseus.py cron --help
python perseus.py doctor --help
python perseus.py update --help
```

The `cli.py` module's dispatch table references these function names; the concatenation provides them from the new modules.

**Step 3: Commit**

```bash
git commit -m "chore: verify no dead references after serve.py decomposition" --allow-empty
```

---

## Architecture After Decomposition

```
src/perseus/
├── __init__.py        (entry, version, stdlib imports)
├── config.py          (DEFAULT_CONFIG, PERMISSION_PROFILES)
├── registry.py        (DIRECTIVE_REGISTRY)
├── renderer.py        (render_source, cache layer)
├── checkpoint.py      (checkpoint read/write)
├── memory.py          (Mnēmē memory system)
├── mneme_*.py         (Mnēmē v2: index, narrative, federation)
├── inbox.py           (agent inbox)
├── agora.py           (task board)
├── pythia.py          (Pythia recommendations)
├── lsp.py             (LSP protocol implementation)
├── mcp.py             (MCP server tools)
├── install.py         (hook installer)
│
├── synthesis.py       ★ NEW — cited synthesis (L409–828)
├── scheduler.py       ★ NEW — cron, systemd, launchd (L1250–1537)
├── doctor.py          ★ NEW — health, doctor, trust (L1539–2081)
├── update.py          ★ NEW — self-update (L2083–2254)
│
├── serve.py           (~1,700 lines after extraction)
│   - Render/watch/graph/prefetch
│   - Context packs
│   - Schema validation CLI
│   - Init/install/templates
│   - MCP serve dispatch
│   - HTTP serve/LSP server
│   - Oracle CLI wrapper
│
├── cli.py             (argparse dispatch)
│
└── directives/        (one file per directive type)
```

## Verification Checklist

After all tasks:
- [ ] `python scripts/build.py --check` passes
- [ ] `python -m pytest tests/ -q` — same pass count as before (754 pass, 1 skip)
- [ ] `python perseus.py --version` outputs `v1.0.5`
- [ ] `python perseus.py --help` shows all subcommands
- [ ] `python perseus.py synthesize --help` works
- [ ] `python perseus.py cron --help` works
- [ ] `python perseus.py doctor` works
- [ ] `python perseus.py trust` works
- [ ] `python perseus.py update` works
- [ ] `python perseus.py health` works
- [ ] All benchmark infographics still render correctly (no function name changes)
