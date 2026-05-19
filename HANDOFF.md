# Developer Handoff — 2026-05-19

**From:** Hermes session (opus model, 3 consecutive sessions)  
**For:** Principal developer continuing Phase 11  
**Repo:** https://github.com/tcconnally/perseus  
**Baseline:** `main` @ `764e040`, 250 tests passing, `perseus.py` ~6,330 lines

---

## Read These First

1. `ROADMAP.md` — complete future plan through Phase 15 with decision gates
2. `AGENTS.md` — repo conventions, constraints, task workflow
3. `tasks/README.md` — Agora workflow (how to claim/complete tasks)

Then come back here for the tactical details.

---

## What Shipped This Session

| Task | Commit | Status | Tests Added |
|---|---|---|---|
| **task-25** DIRECTIVE_REGISTRY | `8ac4d38` | ✅ on main | 5 invariant tests |
| **task-26** `perseus doctor` | `1b8d636` | ✅ on main | 13 doctor tests |
| **task-28** `--json` surfaces | `c62ee47` | 🔧 branch | 10 tests (2 failing) |

---

## Active Branch: `feat/task-28-json-surfaces`

> ⚠️ **Note on workflow:** `AGENTS.md` says "commit to `main` and push directly."
> This branch is a deliberate exception — the WIP was parked mid-session with 2
> failing tests. Once the test fixes land, merge it straight to `main` and delete
> the branch. No PR ceremony needed.

### What's done on the branch

All 6 `--json` flags wired end-to-end (argparse + handler logic):

| Command | JSON keys |
|---|---|
| `oracle infer-labels --json` | `scanned, explicit_skipped, inferred_accept, inferred_reject, inferred_none, unchanged, written, dry_run, window_days, window_checkpoints, floor` |
| `oracle drift --json` | `verdict, samples, metrics{acceptance_rate,jaccard,confidence_proxy}, thresholds, warnings, recent_days, baseline_days` |
| `llm ping --json` | `provider, model, url, latency_ms, status, error` |
| `memory status --json` | `workspace, exists, updated, checkpoints_processed, checkpoints_pending, oracle_entries_processed, oracle_entries_pending, compaction_count, line_count, mode, frontmatter` |
| `memory federation list --json` | array of `{alias, path, enabled, status, error, line_count, mtime}` |
| `memory federation pull --json` | array of `{alias, path, status, error, line_count, mtime, bytes}` |

All produce valid JSON on stdout, no extra text. Exit codes unchanged.

### Fix 1: `test_infer_labels_json_schema`

**Root cause:** `cmd_oracle_infer_labels` had an early-return when the oracle log
is empty (`if not entries: print("(no oracle log entries)"); return 0`). The JSON
block came later, so a test using an empty oracle log hit the early return and
got prose, not JSON.

**Fix already applied** (in the branch) — around line 4659 of `perseus.py`:
the empty-entries path now checks `getattr(args, "json", False)` and emits the
zero-count JSON object. Just run the tests to confirm the fix works.

### Fix 2: `test_memory_status_json_with_narrative`

**Root cause:** The test creates a narrative file at `tmp_path / "memories" /
"narrative.md"`. But `_mneme_path(workspace, cfg)` resolves the narrative path
using a workspace hash, not just the memories dir root. So the file the test
wrote is not the file the function reads.

**Fix needed in the test** (not in production code):

```python
def test_memory_status_json_with_narrative(tmp_path, monkeypatch):
    monkeypatch.setattr(perseus, "PERSEUS_HOME", tmp_path)
    c = cfg()
    c["memory"] = {"workspace_memories_dir": str(tmp_path / "memories")}
    (tmp_path / "memories").mkdir(parents=True)

    # Get the actual path _mneme_path will use
    narrative = perseus._mneme_path(tmp_path, c)
    narrative.parent.mkdir(parents=True, exist_ok=True)
    narrative.write_text(
        "---\nupdated: '2026-05-18T12:00:00'\n"
        "checkpoints_processed: 5\noracle_entries_processed: 3\n"
        "compaction_count: 1\n---\nSome narrative content.\n"
    )

    ns = argparse.Namespace(workspace=str(tmp_path), memory_command="status",
                            json=True, llm=None)
    out, rc = _capture_json(monkeypatch, perseus.cmd_memory, ns, c)
    assert out["exists"] is True
    for key in ("updated", "checkpoints_processed", ...):
        assert key in out
```

### After fixing both tests

1. Run `python -m pytest tests/ -q` — expect ~260 passing
2. Update `tasks/task-28-agent-json-surfaces.md` frontmatter: `status: completed`
3. Commit: `git add -A && git commit -m "fix(task-28): test fixes + mark completed"`
4. Merge to main: `git checkout main && git merge feat/task-28-json-surfaces && git push`
5. Delete branch: `git push origin --delete feat/task-28-json-surfaces`

---

## Task 27: LSP Integration Tests

**Spec:** `tasks/task-27-lsp-integration-tests.md`  
**Unblocked by:** task-25 ✅

The LSP server is started with `python perseus.py serve --lsp --stdio`. It speaks
JSON-RPC 2.0 over stdin/stdout with Content-Length framing.

### How to write the test harness

```python
import subprocess, json, threading, time

def lsp_message(payload: dict) -> bytes:
    body = json.dumps(payload).encode()
    return b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body

def read_lsp_message(proc):
    header = b""
    while not header.endswith(b"\r\n\r\n"):
        header += proc.stdout.read(1)
    length = int(header.split(b"Content-Length: ")[1].split(b"\r\n")[0])
    return json.loads(proc.stdout.read(length))

@pytest.fixture
def lsp_proc(tmp_path):
    p = subprocess.Popen(
        ["python", str(Path(__file__).parent.parent / "perseus.py"), "serve", "--lsp", "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(tmp_path),
    )
    yield p
    p.stdin.close(); p.terminate(); p.wait(timeout=5)
```

### Known LSP server quirks

- The server uses raw `sys.stdin.buffer` / `sys.stdout.buffer` — binary mode only
- The shell safety scanner inspects `@query` args; do not put shell-injection
  strings in LSP test documents or you'll get diagnostics you didn't expect
- Hover on `@agent` / `@query` / other `executes_shell=True` directives returns
  a stub (`⚠️ Live preview disabled for ...`) — this is correct behavior from the
  registry's `safe_for_hover` flag, not a bug
- Completion items come from `_LSP_DIRECTIVE_NAMES` which is now derived from
  `DIRECTIVE_REGISTRY` — verify against `set(perseus.DIRECTIVE_REGISTRY.keys())`

### What to test

```
initialize → capabilities response (includes completionProvider, hoverProvider)
textDocument/didOpen → publishDiagnostics (empty for clean doc)
textDocument/didOpen with unknown @foo → publishDiagnostics with one error
textDocument/completion at "@" prefix → all DIRECTIVE_REGISTRY names
textDocument/hover over @date → live resolved value
textDocument/hover over @query "ls" → stub (safe_for_hover=False)
shutdown + exit → clean exit
```

---

## Task 29: Split Tests by Subsystem

**Spec:** `tasks/task-29-split-tests-by-subsystem.md`  
**Do this last** — after task-27 and task-28 are merged, so you only split once.

### Proposed split

```
tests/
  conftest.py            ← shared fixtures
  test_renderer.py       ← directive resolution, @if, caching, @include, @read
  test_checkpoints.py    ← checkpoint, recover, diff, workspace namespacing
  test_oracle.py         ← suggest, oracle log, drift, infer-labels, drift JSON
  test_memory.py         ← Mnēmē narrative, federation, memory JSON
  test_lsp.py            ← LSP JSON-RPC integration tests (task-27)
  test_doctor.py         ← doctor checks, exit codes, JSON output
  test_registry.py       ← DIRECTIVE_REGISTRY invariants (task-25)
  test_json_surfaces.py  ← --json output schemas (task-28)
```

### Shared fixtures for conftest.py

The key shared fixture is `cfg()` — it builds a minimal config dict used by most
tests. Extract it to `conftest.py` so all test files can import it:

```python
# tests/conftest.py
import pytest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import perseus

@pytest.fixture
def cfg(tmp_path):
    return {
        "render": {"allow_query_shell": True, "allow_outside_workspace": False},
        "checkpoints": {"dir": str(tmp_path / "checkpoints"), "ttl_s": 86400},
        "oracle": {"log": str(tmp_path / "oracle_log.yaml")},
    }
```

> Note: the current `test_perseus.py` uses a module-level `cfg()` function (not
> a pytest fixture), so individual tests call it as `cfg()`. You can keep this
> pattern in the split files or convert to fixtures — either works.

---

## Architecture Notes

### DIRECTIVE_REGISTRY structure

```python
DirectiveSpec = NamedTuple('DirectiveSpec', [
    ('name', str),           # "@query"
    ('kind', str),           # "inline" | "block" | "control"
    ('resolver', Callable),  # resolve_query, or None for control directives
    ('call_convention', str),# how to call the resolver — see below
    ('args', list),          # ["fallback=", "schema="] — used for LSP completion
    ('safe_for_hover', bool),# False = LSP hover returns stub, never executes
    ('description', str),    # one-liner for LSP hover tooltip
])
```

**Call convention codes** — the dispatch adapter `_resolve_via_registry()` uses these:
| Code | Signature |
|---|---|
| `"acw"` | `resolver(args, cfg, workspace)` — most resolvers |
| `"ac"` | `resolver(args, cfg)` — skills, session, waypoint, drift |
| `"a"` | `resolver(args)` — env, date |
| `"awc"` | `resolver(args, workspace, cfg)` — include (reversed! historical) |

**Adding a new directive** (after task-25 landed):
1. Write `resolve_mynewdirective(args, cfg, workspace)` function
2. Add one `DirectiveSpec` entry to `DIRECTIVE_REGISTRY` near the top of the file
3. That's it — regex, dispatch, LSP completion, hover safety all derive from registry

### `perseus doctor` check structure

```python
class DoctorResult(NamedTuple):
    status: str   # "ok" | "warn" | "error"
    name: str     # display name
    detail: str   # one-line explanation
```

Each check is a `Callable[[argparse.Namespace, dict], DoctorResult]` in the
`_DOCTOR_CHECKS` list. Exit 0 if no errors, exit 1 if any error.

### `_mneme_path(workspace, cfg)` behavior

The narrative lives at:
```
{cfg["memory"]["workspace_memories_dir"]} / {md5(str(workspace))[:8]}_narrative.md
```
Not just `memories/narrative.md`. This is why the task-28 test fixture was wrong —
always call `_mneme_path(workspace, cfg)` to get the real path in tests.

### The `~/` directory in git status

You'll see `?? ~/` in `git status` — this is a literal directory named `~/`
that got created at the repo root by a tool using unexpanded `~`. It's in
`.gitignore` implicitly (listed as untracked, not staged). Ignore it. If it
bothers you: `rm -rf '~/'; git add .gitignore` to explicitly exclude it.

### pykwalify soft-import

`perseus.py` contains `try: import pykwalify` code for schema validation. But
`pykwalify` is **not** in `requirements.txt` (constraint #2: pyyaml only).
This is intentional — the feature degrades gracefully. Do not add it back to
`requirements.txt` without owner approval. If schema validation work (Phase 12)
proceeds, see the three options in ROADMAP.md § 12A for the resolution path.

---

## Working with This Codebase

### Always use patch-only edits on `perseus.py`

`perseus.py` is ~6,330 lines. Never use `write_file` or `cat > perseus.py` on
it — you will lose content. Always use targeted `patch` / `old_string` →
`new_string` replacements. Section headers look like:

```python
# ─────────────────────────────── Section Name ────────────────────────────────
```

Use them as anchors for unique patch targets.

### Test run command

```bash
cd /workspace/perseus
python -m pytest tests/ -q           # fast summary
python -m pytest tests/ -v --tb=short  # verbose with tracebacks
python -m pytest tests/ -k "doctor"    # filter by name
```

### Rendering ROADMAP / AGENTS live

```bash
python perseus.py render ROADMAP.md   # live phase plan with @date, @query
python perseus.py render AGENTS.md    # live Agora task board + health report
```

These use the actual Perseus renderer — if you see `@agora` in the raw files,
rendered output will show a live task table. Useful for verifying the renderer
didn't regress.

### Claiming a task before starting

```bash
python perseus.py agora claim task-27 --agent "<your name>"
```

This sets `status: in_progress` and `claimed_by` in the task file frontmatter.
Prevents conflicts if multiple agents work in parallel.

---

## Non-Negotiable Constraints (verbatim from ROADMAP.md)

1. **Single file.** `perseus.py` stays one file.
2. **`pyyaml` is the only dependency.**
3. **Tests before commit.** All existing tests must pass. New behavior needs new tests.
4. **Spec follows code.** When behavior changes, update `spec/*.md`.
5. **Keep the mythology.** Perseus, Pythia, Agora, Daedalus, Mnēmē. Don't rename.
6. **Backward compatibility.** `@directive` syntax and config keys must not break.
7. **Executors, not architects.** Implement tasks as specified. If a task conflicts
   with a constraint, mark it Blocked — do not resolve it unilaterally.

---

## Git State at Handoff

```
main (764e040) — clean, pushed:
  63c4625  audit: reopen ghost tasks 26+28, remove pykwalify hard dep
  8ac4d38  feat(task-25): DIRECTIVE_REGISTRY
  908a27f  chore: mark task-25 completed
  1b8d636  feat(task-26): perseus doctor
  1ffbe2f  chore: mark task-26 completed
  764e040  docs: merge future phases into ROADMAP.md + HANDOFF.md

feat/task-28-json-surfaces (c62ee47) — pushed, 2 tests failing:
  c62ee47  wip(task-28): --json agent surfaces — 6 commands wired, 2 test fixes pending
```

**Open tasks by priority:**
1. `feat/task-28-json-surfaces` — finish 2 test fixes, merge, close (1-2 hours)
2. `task-27` — LSP integration tests (half day)
3. `task-29` — split tests by subsystem (2-3 hours, do last)

---

## Test Count History

| Milestone | Tests |
|---|---|
| Start of this session | 232 |
| After task-25 | 237 |
| After task-26 | 250 |
| After task-28 merged (expected) | ~260 |
| After task-27 (expected) | ~275 |
| After task-29 (no new tests, split only) | ~275 |
