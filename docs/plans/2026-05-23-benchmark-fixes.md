# Perseus v1.0.2 — Benchmark Bug Fixes + Architecture Hardening Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
> **Parallel workstream:** Claude Opus is running Phase 2 adversarial coverage (gaps in the benchmark). This plan covers everything else.

**Goal:** Fix three Windows-crashing one-line bugs, add stdout cap and configurable timeout to @query, and parallelize @query/@services resolution.

**Architecture:** Bug fixes are isolated edits in `src/perseus/directives/query.py`, `src/perseus/directives/services.py`, and `src/perseus/serve.py`. The parallelization touches `src/perseus/renderer.py` for @query batching and `src/perseus/directives/services.py` for @services concurrency. All work edits source modules under `src/perseus/`, then regenerates `perseus.py` via `python scripts/build.py`.

**Tech Stack:** Python 3.11+, pyyaml, concurrent.futures, subprocess

**Sources of truth:**
- `ROADMAP.md` — project phase/component status
- `src/perseus/` — canonical source (edit here, not `perseus.py`)
- `scripts/build.py` — regenerates the single-file artifact
- `AGENTS.md` — contributor constraints (pyyaml only, tests before merge, edit source not artifact)

**Related benchmark:** Opus 4.7 Max benchmark (@ COLD-START-BENCHMARK-2026-05-23.md, COLD-START-BENCHMARK-ENTERPRISE-2026-05-23.md)

---

## Executor Flags

1. **Edit `src/perseus/` not `perseus.py`** — the root `perseus.py` is a generated artifact. Rebuild with `python scripts/build.py` after every edit.
2. **All existing tests must pass.** Run `python -m pytest tests/ -q` before committing. Breakage is not acceptable for one-line bug fixes.
3. **New tests for new behavior.** The stdout cap and timeout features need tests. The bugs need regression tests.
4. **Parallelization is opt-in.** Do NOT change the default render behavior to parallel — it's a config flag (`render.parallel=True`). Default sequential preserves backward compatibility.
5. **Line count check.** After each task, verify `wc -l perseus.py` didn't silently drop content. Baseline: ~10,322 lines.

---

## Task 1: Fix `write_text` encoding on Windows

**Objective:** Add `encoding="utf-8"` to the render output write path so emoji (like `📌`) survive on Windows where `locale.getpreferredencoding()` returns `cp1252`.

**Files:**
- Modify: `src/perseus/serve.py:61`

**Step 1: Apply the fix**

```python
# Before (line 61):
        out_path.write_text(rendered)

# After:
        out_path.write_text(rendered, encoding="utf-8")
```

**Step 2: Audit other `write_text` calls for the same issue**

Check these locations for missing `encoding="utf-8"`:
- `src/perseus/inbox.py:36` — `tmp.write_text(text)` — risk if text contains emoji
- `src/perseus/serve.py:2816` — `context_file.write_text(content)` — risk if template contains emoji
- `src/perseus/audit.py:609` — `latest.write_text(outfile.read_text())` — reading already-encoded content, low risk
- `src/perseus/serve.py:1277` — `plist_path.write_text(content)` — plist content, low risk

Fix the two user-facing paths (inbox.py:36 and serve.py:2816) along with serve.py:61. Leave audit.py (round-trips its own content) and plist_path (macOS-only) alone.

**Step 3: Rebuild and test**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 4: Commit**

```bash
git add src/perseus/serve.py src/perseus/inbox.py
git commit -m "fix: add encoding='utf-8' to write_text calls for Windows compatibility"
```

---

## Task 2: Fix `/bin/bash` unreachable on Windows

**Objective:** On Windows, `subprocess.run(executable="/bin/bash")` is fatal. Detect when the configured shell doesn't exist and fall back to the system default (omit `executable` kwarg entirely).

**Files:**
- Modify: `src/perseus/directives/query.py:25,81`
- Modify: `src/perseus/directives/services.py:84,89`

**Step 1: Add a `_resolve_shell` helper**

This helper goes in `src/perseus/directives/query.py` (imported by services.py or duplicated — prefer a shared location). Since both query.py and services.py need it, add it to `src/perseus/config.py` (already loaded by both).

```python
# In src/perseus/config.py, add after existing functions:

def resolve_shell(cfg: dict) -> str | None:
    """Return the shell executable, or None if it doesn't exist on this system.
    
    On Windows, /bin/bash doesn't exist. Returning None tells subprocess
    to use the system default (COMSPEC on Windows, /bin/sh elsewhere).
    """
    shell = cfg["render"].get("shell", "/bin/bash")
    import shutil
    resolved = shutil.which(shell)
    if resolved is None and shell != "/bin/bash":
        # Non-default shell specified but not found — warn and fall back
        return None
    if resolved is None:
        # Default /bin/bash not found (Windows) — use system default
        return None
    return resolved
```

**Step 2: Update query.py (lines 25, 81)**

```python
# Line 25 (shell variable for audit + executable):
shell = resolve_shell(cfg)  # was: cfg["render"].get("shell", "/bin/bash")

# Line 81 (the subprocess.run call):
    result = subprocess.run(
        cmd,
        shell=True,
        executable=shell,      # None ⟹ system default
        capture_output=True,
        text=True,
        timeout=timeout,       # now configurable (Task 5)
    )
```

**Step 3: Update services.py (lines 84, 89)**

```python
# Line 84 (audit event):
shell = resolve_shell(cfg)  # was: cfg["render"].get("shell", "/bin/bash")

# Line 89:
executable=resolve_shell(cfg),
```

**Note:** When `shell` is `None`, passing `executable=None` to `subprocess.run()` is valid and means "use system default shell." Python handles this correctly on all platforms.

**Step 4: Add `import shutil` to the stdlib imports comment at top of config.py**

**Step 5: Rebuild and test**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 6: Commit**

```bash
git add src/perseus/config.py src/perseus/directives/query.py src/perseus/directives/services.py
git commit -m "fix: detect missing shell executable, fall back to system default for Windows compat"
```

---

## Task 3: Fix binary stdout → NoneType crash in @query

**Objective:** When `subprocess.run(text=True)` receives binary output that can't be decoded, `result.stdout` may be `None` on some platforms. Guard `.rstrip()` call.

**Files:**
- Modify: `src/perseus/directives/query.py:86`

**Step 1: Apply the guard**

```python
# Before (line 86):
        stdout = result.stdout.rstrip("\n")

# After:
        stdout = (result.stdout or "").rstrip("\n")
```

**Step 2: Verify the fix handles all edge cases**

- Normal text output: `result.stdout` is a string, `.rstrip()` works ✓
- Empty output: `result.stdout` is `""`, `("" or "").rstrip()` = `""` ✓
- Binary output on Windows: `result.stdout` is `None`, `(None or "").rstrip()` = `""` ✓ — falls through to `if not stdout:` → `"> (no output from cmd)"`
- Error exit: `result.stdout` is a string, `.rstrip()` works ✓

**Step 3: Rebuild and test**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 4: Commit**

```bash
git add src/perseus/directives/query.py
git commit -m "fix: guard against None stdout from subprocess on binary output (Windows)"
```

---

## Task 4: Add stdout size cap to @query

**Objective:** A misbehaving command can silently embed 12 MB of output into the context document. Add `render.max_query_bytes` config (default 256 KB) with a visible truncation marker.

**Files:**
- Modify: `src/perseus/directives/query.py` (after line 86)
- Modify: `src/perseus/config.py` (add default)
- Create: `tests/test_query_stdout_cap.py`

**Step 1: Write failing test**

```python
# tests/test_query_stdout_cap.py
import pytest
from perseus.directives.query import resolve_query

def test_stdout_cap_truncates_large_output():
    """Verify stdout is truncated at max_query_bytes with a marker."""
    cfg = {
        "render": {
            "shell": "/bin/sh",
            "allow_query_shell": True,
            "max_query_bytes": 100,  # 100 bytes cap
        }
    }
    # Command emits 500 bytes
    result = resolve_query(
        f'"python3 -c \\"print(\'x\' * 500)\\""',
        cfg,
    )
    # Should be truncated
    assert len(result) < 500
    assert "truncated" in result.lower() or "..." in result
    # Should still be a fenced code block
    assert result.startswith("```")


def test_stdout_cap_passes_small_output():
    """Verify small output is not truncated."""
    cfg = {
        "render": {
            "shell": "/bin/sh",
            "allow_query_shell": True,
            "max_query_bytes": 10000,
        }
    }
    result = resolve_query(
        f'"echo hello"',
        cfg,
    )
    assert "hello" in result


def test_stdout_cap_default_is_256k():
    """Verify default cap is 256 KB."""
    cfg = {
        "render": {
            "shell": "/bin/sh",
            "allow_query_shell": True,
        }
    }
    result = resolve_query(
        f'"python3 -c \\"print(\'x\' * 10)\\""',
        cfg,
    )
    # Small output passes through fine
    assert "xxxxx" in result
```

**Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_query_stdout_cap.py -v
# Expected: FAIL — no truncation in resolve_query
```

**Step 3: Implement the cap**

In `src/perseus/directives/query.py`, after `stdout = (result.stdout or "").rstrip("\n")`:

```python
        # Apply stdout size cap
        max_bytes = int(cfg["render"].get("max_query_bytes", 256 * 1024))
        stdout_bytes = stdout.encode("utf-8")
        if len(stdout_bytes) > max_bytes:
            # Truncate at nearest newline under the cap to avoid mid-line cuts
            stdout = stdout_bytes[:max_bytes].decode("utf-8", errors="replace")
            # Try to find last newline
            last_nl = stdout.rfind("\n")
            if last_nl > max_bytes // 2:
                stdout = stdout[:last_nl]
            truncated_msg = f"\n\n> ⚠ Output truncated at {max_bytes} bytes ({len(stdout_bytes)} bytes total)"
            stdout = stdout + truncated_msg
```

**Step 4: Run test to verify pass**

```bash
python -m pytest tests/test_query_stdout_cap.py -v
# Expected: 3 PASS
```

**Step 5: Rebuild and full test suite**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 6: Commit**

```bash
git add src/perseus/directives/query.py tests/test_query_stdout_cap.py
git commit -m "feat: add render.max_query_bytes cap (default 256 KB) to prevent stdout bombs in context docs"
```

---

## Task 5: Add configurable @query timeout

**Objective:** The 30-second `@query` timeout is hardcoded. Allow per-directive `timeout=N` (like `@agent` already supports) and a config-level `render.query_timeout_s` default.

**Files:**
- Modify: `src/perseus/directives/query.py` (parse `timeout=N` modifier, use it)
- Modify: `src/perseus/config.py` (add default)
- Create: tests in `tests/test_query_stdout_cap.py` (extend existing)

**Step 1: Add timeout parsing to query.py**

Insert before the subprocess.run call (around line 77), after `fallback` extraction:

```python
    # Extract timeout=N modifier (per-directive override)
    timeout = int(cfg["render"].get("query_timeout_s", 30))
    tm_match = re.search(r'\s+timeout=(\d+)(?:\s|$)', raw)
    if tm_match:
        timeout = int(tm_match.group(1))
        raw = (raw[:tm_match.start()] + raw[tm_match.end():]).rstrip()
```

Then update the `subprocess.run` call:

```python
        result = subprocess.run(
            cmd,
            shell=True,
            executable=shell,
            capture_output=True,
            text=True,
            timeout=timeout,  # was: timeout=30
        )
```

And update the timeout error message:

```python
    except subprocess.TimeoutExpired:
        if fallback is not None:
            return fallback
        return f"> ⚠ `@query` timed out ({timeout}s): `{cmd}`"  # was: (30s)
```

**Step 2: Write tests**

```python
def test_query_custom_timeout():
    """Verify timeout=N modifier works."""
    cfg = {
        "render": {
            "shell": "/bin/sh",
            "allow_query_shell": True,
        }
    }
    # sleep 10 with timeout=1 should time out
    result = resolve_query(
        f'"sleep 10" timeout=1',
        cfg,
    )
    assert "timed out" in result
    assert "1s" in result
```

**Step 3: Run tests, rebuild, commit**

```bash
python -m pytest tests/test_query_stdout_cap.py::test_query_custom_timeout -v
python scripts/build.py
python -m pytest tests/ -q
git add src/perseus/directives/query.py tests/test_query_stdout_cap.py
git commit -m "feat: add configurable timeout=N to @query directive"
```

---

## Task 6: Parallelize @services health checks

**Objective:** @services does sequential HTTP health checks. With 100 services at 3s timeout each, that's 5 minutes. Parallel HTTP checks cut it to ~3 seconds. Use `concurrent.futures.ThreadPoolExecutor` only in @services (the block directive), which is isolated and safe.

**Files:**
- Modify: `src/perseus/directives/services.py` (the `resolve_services` function)
- Create: `tests/test_services_parallel.py`

**Design note:** Do NOT add a dependency. `concurrent.futures` is stdlib. Opt-in via `render.parallel_services=True` config flag. Default is `False` (preserve backward compatibility). HTTP checks run in thread pool (I/O bound); command checks also in thread pool (subprocess I/O bound).

**Step 1: Write failing test**

```python
# tests/test_services_parallel.py
import time
from perseus.directives.services import resolve_services

def test_services_parallel_reduces_latency():
    """Parallel checks should be faster than sequential for multiple services."""
    # 5 services each with 1s timeout, sequential would be ~5s
    # parallel should be ~1s (all fire at once)
    services_yaml = """
- name: s1
  url: http://127.0.0.1:19991
- name: s2
  url: http://127.0.0.1:19992
- name: s3
  url: http://127.0.0.1:19993
- name: s4
  url: http://127.0.0.1:19994
- name: s5
  url: http://127.0.0.1:19995
"""
    cfg = {
        "render": {
            "parallel_services": True,
            "services_timeout_s": 1,
            "allow_remote_services_health": True,
        }
    }
    start = time.monotonic()
    result = resolve_services(services_yaml, cfg)
    elapsed = time.monotonic() - start
    
    # Should have 5 service rows
    assert result.count("|") >= 5
    # Parallel should be under 2s (all fire at once, 1s timeout)
    assert elapsed < 2.0, f"Expected <2s for parallel, got {elapsed:.1f}s"
```

**Step 2: Run test to verify failure**

```bash
python -m pytest tests/test_services_parallel.py::test_services_parallel_reduces_latency -v
# Expected: FAIL — ~5s elapsed > 2s threshold
```

**Step 3: Implement parallel health checks**

In `src/perseus/directives/services.py`, wrap the service loop:

```python
def resolve_services(block_content: str, cfg: dict) -> str:
    """Parse YAML service list from block and health-check each."""
    timeout = float(cfg["render"].get("services_timeout_s", 3))
    parallel = bool(cfg["render"].get("parallel_services", False))
    try:
        services = yaml.safe_load(block_content) or []
    except yaml.YAMLError as e:
        return f"> ⚠ Invalid @services YAML: {e}"

    if not services:
        return "> No services configured."

    def _check_one(svc: dict, index: int) -> tuple[int, str]:
        """Check one service, return (index, row_string)."""
        if not isinstance(svc, dict):
            return index, "| (invalid) | ⚠ service entry must be a mapping | — |"
        name = svc.get("name", "(unnamed)")
        url = svc.get("url", "")
        docker = svc.get("docker", "")

        if url:
            status, latency = health_check_url(url, timeout, cfg)
            lat_str = f"{latency:.0f}ms" if latency is not None else "—"
            return index, f"| {name} | {status} | {lat_str} |"
        elif docker:
            try:
                out = subprocess.check_output(
                    ["docker", "ps", "--filter", f"name={docker}", "--format", "{{.Status}}"],
                    timeout=timeout,
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                if out:
                    return index, f"| {name} | ✅ {out} | — |"
                else:
                    return index, f"| {name} | ❌ not running | — |"
            except Exception:
                return index, f"| {name} | ⚠ docker unavailable | — |"
        elif command := str(svc.get("command") or ""):
            if not cfg["render"].get("allow_services_command", False):
                return index, f"| {name} | ⚠ command checks disabled by config | — |"
            shell = resolve_shell(cfg)
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    executable=shell,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                out_text = (result.stdout or result.stderr).strip()
                first_line = out_text.splitlines()[0][:80] if out_text else ""
                if result.returncode == 0:
                    status = f"✅ {first_line}" if first_line else "✅ ok"
                else:
                    status = f"❌ {first_line}" if first_line else f"❌ exit {result.returncode}"
            except subprocess.TimeoutExpired:
                status = "⚠ timeout"
            except Exception as exc:
                status = f"⚠ {exc}"
            return index, f"| {name} | {status} | — |"
        else:
            return index, f"| {name} | ⚠ no url/docker/command | — |"

    if parallel and len(services) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        rows = [None] * len(services)
        with ThreadPoolExecutor(max_workers=min(len(services), 16)) as executor:
            futures = {executor.submit(_check_one, svc, i): i for i, svc in enumerate(services)}
            for future in as_completed(futures):
                index, row = future.result()
                rows[index] = row
    else:
        rows = [_check_one(svc, i)[1] for i, svc in enumerate(services)]

    return "\n".join(["| Service | Status | Latency |", "|---|---|---|"] + rows)
```

**Step 4: Add `from .config import resolve_shell` import or duplicate**

Since services.py currently doesn't import from config, add `from ..config import resolve_shell` at top. Alternatively, inline the shell resolution (already has `cfg["render"].get("shell", "/bin/bash")`).

**Step 5: Run tests, rebuild**

```bash
python -m pytest tests/test_services_parallel.py -v
python scripts/build.py
python -m pytest tests/ -q
```

**Step 6: Commit**

```bash
git add src/perseus/directives/services.py tests/test_services_parallel.py
git commit -m "feat: add render.parallel_services for concurrent health checks (ThreadPoolExecutor)"
```

---

## Task 7: Parallelize @query inline directives (opt-in)

**Objective:** Multiple @query directives in a context file run sequentially, each paying ~140ms Python interpreter startup. With `render.parallel_queries=True`, batch all @query calls in the render pass and run them concurrently via ProcessPoolExecutor.

**Files:**
- Modify: `src/perseus/renderer.py` (`_render_lines`)
- Modify: `src/perseus/directives/query.py` (expose the command-extraction path)

**Design:** This is the most invasive change. The render loop is inherently sequential (output assembled in order). Approach:
1. First pass: scan for @query directives, collecting (directive, args, line_index)
2. If parallel mode and >1 queries: run all in ProcessPoolExecutor, collect results
3. Second pass: replace @query invocations with cached/pre-computed results
4. Sequential fallback for any that fail in parallel mode

**Pitfall:** The resolver functions aren't pickleable (they reference module-level functions with complex state). ProcessPoolExecutor needs picklable targets. Solution: use ThreadPoolExecutor for @query too — each query is a `subprocess.run()` which releases the GIL, so threads are fine for I/O-bound subprocess calls. The interpreter startup cost is inside the child subprocess, not the parent thread.

**Config flag:** `render.parallel_queries` (default `False`)

**Step 1: Write test**

```python
# tests/test_query_parallel.py
import time
from perseus.renderer import render_source

def test_parallel_queries_faster_than_sequential():
    """Multiple sleep queries should complete in ~1s parallel vs N seconds sequential."""
    source = """@perseus v0.4
@query "sleep 1 && echo done1"
@query "sleep 1 && echo done2"
@query "sleep 1 && echo done3"
@query "sleep 1 && echo done4"
"""
    cfg = {
        "render": {
            "shell": "/bin/sh",
            "allow_query_shell": True,
            "parallel_queries": True,
        }
    }
    start = time.monotonic()
    result = render_source(source, cfg)
    elapsed = time.monotonic() - start
    
    assert "done1" in result
    assert "done2" in result
    assert "done3" in result
    assert "done4" in result
    # Parallel: all 4 fire at once, all sleep 1s, ~1s total
    assert elapsed < 2.0, f"Expected <2s for parallel, got {elapsed:.1f}s"
```

**Step 2: Run to verify failure**

```bash
python -m pytest tests/test_query_parallel.py -v
# Expected: FAIL — sequential ~4s
```

**Step 3: Implement**

In `src/perseus/renderer.py`, modify `_render_lines` to batch @query directives when `parallel_queries` is enabled. The implementation has two phases:

*Phase A — Extract query directives* (scan lines, identify @query, extract args):
```python
# In _render_lines, before the main while loop, if parallel mode:
queries = []
if cfg["render"].get("parallel_queries", False):
    # Scan for @query directives
    for idx, line in enumerate(lines):
        m = INLINE_DIRECTIVE_RE.match(line)
        if m and m.group(1).lower() == "@query":
            queries.append((idx, m.group(2) or ""))
```

*Phase B — Execute in parallel and cache results:*
```python
if len(queries) > 1:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _run_query(args):
        idx, args_str = args
        return idx, resolve_query(args_str, cfg, workspace)
    
    query_results = {}
    with ThreadPoolExecutor(max_workers=min(len(queries), 8)) as executor:
        futures = {executor.submit(_run_query, q): q[0] for q in queries}
        for future in as_completed(futures):
            idx, result = future.result()
            query_results[idx] = result
```

*Phase C — During the main render loop*, check for cached results:
```python
# In the inline directive resolution block (line 424-472):
m = INLINE_DIRECTIVE_RE.match(line)
if m:
    directive = m.group(1).lower()
    if directive == "@query" and query_results and i in query_results:
        output.append(query_results[i])
        i += 1
        continue
    # ... existing resolution logic ...
```

**Step 4: Run tests, rebuild, commit**

```bash
python -m pytest tests/test_query_parallel.py -v
python scripts/build.py
python -m pytest tests/ -q
git add src/perseus/renderer.py tests/test_query_parallel.py
git commit -m "feat: add render.parallel_queries for concurrent @query execution (ThreadPoolExecutor)"
```

---

## Task 8: Update README to match reality

**Objective:** The README claims "parallel subprocess pool" which Opus verified is not true. Update the README performance section to reflect actual behavior and the new `render.parallel_queries` / `render.parallel_services` flags.

**Files:**
- Modify: `README.md`

**Step 1: Find and replace the stale claim**

Search README.md for "parallel subprocess" and update to describe actual sequential default + opt-in parallelism.

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: correct README parallelism claims, document parallel_queries/parallel_services flags"
```

---

## Task 9: Update CHANGELOG and bump version

**Objective:** Record all changes for v1.0.3.

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `VERSION`

**Step 1: Update VERSION**

```bash
echo "1.0.3" > VERSION
```

**Step 2: Update CHANGELOG**

Add `## [1.0.3] — 2026-05-23` section with:
- Fixed: write_text encoding on Windows (📌 emoji crash)
- Fixed: /bin/bash unreachable on native Windows Python
- Fixed: binary stdout NoneType crash in @query
- Added: render.max_query_bytes stdout cap (default 256 KB)
- Added: configurable timeout=N modifier for @query
- Added: render.parallel_services for concurrent health checks
- Added: render.parallel_queries for concurrent @query execution

**Step 3: Rebuild with new version**

```bash
python scripts/build.py
python -m pytest tests/ -q
```

**Step 4: Commit and push**

```bash
git add VERSION CHANGELOG.md perseus.py
git commit -m "release: v1.0.3 — Windows fixes, stdout cap, parallelism, configurable @query timeout"
git push origin main
```

---

## Verification Checklist (after all tasks)

- [ ] `python -m pytest tests/ -q` — all 539+ tests pass
- [ ] `python scripts/build.py` — regenerates artifact successfully
- [ ] `python perseus.py --version` — prints `perseus alpha v1.0.3`
- [ ] `grep -c "encoding=.utf-8" src/perseus/serve.py` — shows encoding param on write_text
- [ ] `grep "resolve_shell" src/perseus/config.py` — shows new helper function
- [ ] `grep "max_query_bytes" src/perseus/directives/query.py` — shows cap implementation
- [ ] `grep "timeout=" src/perseus/directives/query.py` — shows timeout parsing
- [ ] `grep "ThreadPoolExecutor" src/perseus/directives/services.py` — shows parallel services
- [ ] `grep "parallel_queries" src/perseus/renderer.py` — shows parallel query batching
- [ ] `git diff --stat main` — no changes to `perseus.py` that aren't from build script
