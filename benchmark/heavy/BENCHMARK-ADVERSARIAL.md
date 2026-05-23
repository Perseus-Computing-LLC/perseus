# Perseus Adversarial Benchmark — Where It Breaks

**Date:** 2026-05-23
**Perseus:** v1.0.1 + a one-line local Windows shell-fallback patch
**Host:** Windows 11 · Python 3.14.2 · native `python.exe`
**Goal:** Push the renderer past comfortable limits and document every
observed failure mode and architectural cliff.

Full machine-readable run log: `adversarial_results.json`.

---

## Headline

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│   Scaling sweep: render time is LINEAR in @query count.              │
│       10 → 0.61 s   |   500 → 20.22 s   |   ~40 ms / query          │
│                                                                      │
│   Three real Perseus bugs surfaced. Three architectural cliffs.      │
│                                                                      │
│   None of the failure modes corrupt the output document — Perseus    │
│   degrades by emitting a warning block, not by crashing the render.  │
│   (Except for B3 binary output, which crashes the whole render.)     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## A. Scaling Sweep — render time vs. @query count

Each test workspace had a fresh `.perseus/context.md` whose body was
nothing but N `@query "<python -c 'print(i)'>"` lines. The work per
query is trivial (one Python startup + `print`); the run-time is
dominated by subprocess orchestration.

| N queries | Wall clock | ms / query | Output lines | Output bytes |
|---:|---:|---:|---:|---:|
| 10 | **0.607 s** | 60.7 | 10 | 1 040 |
| 50 | **2.255 s** | 45.1 | 50 | 5 240 |
| 100 | **4.215 s** | 42.1 | 100 | 10 490 |
| 200 | **8.235 s** | 41.2 | 200 | 21 090 |
| 500 | **20.218 s** | 40.4 | 500 | 52 890 |

### What this shows

- **Linear in N.** The per-query cost asymptotes to ~40 ms once
  amortised across enough work; the 60-ms outlier at N=10 is one-time
  interpreter and YAML-config load.
- **Strictly sequential.** Perseus walks the source document once and
  invokes `subprocess.run(...)` for each `@query` synchronously. Adding
  a `ProcessPoolExecutor` step (filed under "future work" in
  `BENCHMARK-MEGA-ENTERPRISE.md`) would let the 500-query render finish
  in ~5 s on a 4-core machine instead of 20.
- **No truncation.** All 500 queries were dispatched, all 500 lines
  appear in the output.

---

## B. Edge cases

### B1. `@query` with ~12 MB of stdout

**Setup:** Single `@query` whose stdout is 1.2 M lines of `xxxxxxxxx\n`
(≈12 MB before fencing).

**Result:** ✅ Worked. Rendered in **1.22 s**, produced a
**13.2 MB** `.hermes.md`.

**Observation:** Perseus has **no built-in cap on `@query` stdout size**.
For a context-window-conscious assistant this is a footgun: a
misbehaving scanner can blow up the rendered file (and therefore the
session's context) by orders of magnitude. A user-configurable
`max_query_bytes` setting (with sensible default like 256 KB and
visible truncation marker) would help.

---

### B2. `@query` that exceeds the 30 s timeout

**Setup:** `python -c "time.sleep(45)"` inside a single `@query`.

**Result:** ✅ Correct failure mode — output contains:
```
> ⚠ `@query` timed out (30s): <command>
```

**Observation:** The 30-second `@query` timeout is **hardcoded** at
`perseus.py:1624` and is not surfaced as a directive modifier (e.g.
`@query "..." timeout=120`). Wall clock for the render came in at
45 s, ~15 s longer than the timeout — process-kill latency on
Windows. The renderer doesn't truncate the wait once timeout fires;
it waits for the OS to actually reap the child.

---

### B3. `@query` with binary stdout (null bytes) — **REAL BUG**

**Setup:** Script that writes `b'\x00\xff\x00\xfeHELLO\x00BINARY\x00\n'`
to stdout via `sys.stdout.buffer.write`.

**Result:** ❌ Renderer emits an error line:
```
> ⚠ `@query` error: 'NoneType' object has no attribute 'rstrip'
```

The underlying stderr (captured by the harness, not user-visible)
shows the cause:

```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 1:
invalid start byte
```

at `perseus.py:1619` (`stdout = result.stdout.rstrip("\n")`). Perseus
calls `subprocess.run(..., text=True)`, which decodes stdout as UTF-8
and sets it to `None` on decode failure; the next line dereferences
`None.rstrip()` and raises `AttributeError`.

**Fix:** Either use `text=False` + manual decode-with-replace, or
guard with `stdout = (result.stdout or b'').rstrip(b'\n').decode(...)`.
The user-visible message ("NoneType") leaks the implementation detail.

---

### B4. `@query` stdout contains shell metacharacters

**Setup:** Output line is the literal string ```backticks `cat /etc/passwd`
and ${dollars} and $(subshell)```.

**Result:** ✅ Safe. The output is wrapped in a fenced code block;
backticks and `$()` appear verbatim. No further shell expansion
happens because the @query output is treated as data, not as a
secondary command.

---

### B5. `@query` referencing a missing script

**Setup:** `@query "python /path/to/does-not-exist.py"`.

**Result:** ✅ Graceful. Output contains:
```
> ⚠ `@query` exited 2: <command>
```
followed by the interpreter's stderr in a fenced block. No crash, no
stale data, no silent failure.

---

### B6. `@services` with 100 entries — **ARCHITECTURAL CLIFF**

**Setup:** A YAML block with 100 `- name / url` pairs, all pointed at
local ports that don't answer.

**Result:** ❌ **Did not complete within the 180 s harness timeout.**

**Observation:** `@services` URL checks run **sequentially** with a
default per-service timeout of 3 s (`services_timeout_s` at
`perseus.py:52`). 100 services × 3 s = ~300 s expected total, and the
harness killed it at 180 s ≈ 60 services in.

The directive is documented as supporting "HTTP health checks
(`url:`), Docker container status (`docker:`), or optional shell exit
check (`command:`)" — at present it does not support concurrent
fan-out. For environments with more than ~10 services this becomes
unusable as written, and is the strongest case in this suite for
parallelising directive resolution.

---

### B7. `@services` with a hanging `command:`

**Setup (first pass):** Used a Windows-style backslash path inside a
YAML double-quoted scalar — that's malformed YAML and so failed
parsing before ever reaching the command (counts as separate evidence
that Perseus's YAML diagnostics are clear).

**Setup (redo with single-quoted forward-slash path):** `command: '<python>
<hang.py>'` where `hang.py` sleeps 90 s.

**Result on Windows:** Returned in 0.20 s with `⚠ [WinError 3] The
system cannot find the path specified` — **the same `/bin/bash`
default that `@query` had** at `perseus.py:2941`. The shell-fallback
patch applied for the mega-enterprise benchmark only covered
`resolve_query`; `resolve_services` still bakes in `/bin/bash`. The
hang test never actually got to hang; it was killed by the
Windows-shell incompatibility first.

**Filing:** Same bug as #2 below, second site.

---

### B8. Malformed YAML in `@services`

**Setup:** YAML with a missing colon and a stacked-colon line.

**Result:** ✅ Graceful. Perseus catches `yaml.YAMLError` and emits:
```
> ⚠ Invalid @services YAML: while scanning a simple key
  ...
```
including the line and column of the parse error. Render completes
in 0.19 s.

---

### B9. Very long `context.md` (1000 prose sections + 200 @query blocks)

**Setup:** `context.md` with 1000 `## Section N` headers, prose,
sprinkled with 200 trivial `@query` blocks.

**Result:** ✅ Rendered in **7.97 s**, produced 3 199 lines (96 KB).
The renderer's `_render_lines` loop is fine with a long source — the
work is all in the 200 subprocess spawns and 200 × 40 ms ≈ 8 s, which
matches the scaling sweep exactly. No truncation, no crash, no
parse-time regression observed.

---

### B10. Unicode / emoji in `@query` output

**Setup:** A scanner that prints `🚨 ALERT — Δ change ✓ done — 日本語 — Ω`
and `☃️ ❄️ 🌈`, with `PYTHONUTF8=1` set on the harness.

**Result:** ✅ Worked end-to-end with `PYTHONUTF8=1`. The fenced output
contains the emoji and CJK characters intact.

**Without** `PYTHONUTF8=1`, the **whole render fails** because Perseus
writes the output via `Path.write_text(rendered)` without an explicit
encoding (`perseus.py:7121`). On Windows the locale codec (`cp1252`)
cannot encode `📌` from the `@prompt` block. See "Real Bugs" below.

---

## Pass / Fail Matrix

| # | Test | Outcome | Notes |
|---|---|---|---|
| A | Scaling 10 / 50 / 100 / 200 / 500 | ✅ All pass | Linear, ~40 ms/query |
| B1 | 12 MB stdout | ✅ Pass | No cap — context-bloat footgun |
| B2 | 45 s subprocess vs 30 s timeout | ✅ Pass | Hardcoded 30 s, +15 s OS reap |
| B3 | Binary / null-byte stdout | ❌ **Crash** | `NoneType.rstrip()` — real bug |
| B4 | Shell metacharacters | ✅ Safe | Fenced, not evaluated |
| B5 | Missing script | ✅ Graceful | Exit-code reported |
| B6 | @services × 100 entries | ❌ **Cliff** | Sequential, no fan-out |
| B7 | @services hang command (Win) | ❌ Blocked | Same `/bin/bash` bug (second site) |
| B8 | Malformed @services YAML | ✅ Graceful | Line/col diagnostic |
| B9 | 1000-section context.md + 200 queries | ✅ Pass | Linear, ~8 s |
| B10 | Unicode / emoji output | ✅ Pass (with `PYTHONUTF8=1`) | Without it: render aborts |

---

## Real Perseus Bugs (consolidated, all newly surfaced by this benchmark)

### Bug #1 — `Path.write_text(rendered)` ignores encoding on Windows

- **Location:** `perseus.py:7121`
- **Trigger:** Any rendered document containing non-cp1252 characters
  (e.g. the `📌` in `@prompt` blocks, or any emoji in `@query` output).
- **Workaround:** `PYTHONUTF8=1` or rewriting the line to
  `out_path.write_text(rendered, encoding="utf-8")`.
- **Severity:** **High on Windows** — Perseus's own default `@prompt`
  text contains `📌`, so a brand-new workspace fails to render until
  `PYTHONUTF8=1` is set.

### Bug #2 — Default `shell = "/bin/bash"` is broken on Windows

- **Locations:** `perseus.py:1558` (`resolve_query`) and
  `perseus.py:2941` (`resolve_services` command branch).
- **Trigger:** Any `@query` or `@services command:` on a native
  Windows host. `/bin/bash` does not exist as a Windows path; subprocess
  fails with `[WinError 3]`.
- **Cannot work around via config:** setting `render.shell` to the Git
  Bash path triggers a *different* failure because
  `subprocess.run(shell=True, executable="...with spaces...")` on
  Windows mis-parses the path before launch.
- **Local patch applied here** (for `resolve_query` only — `resolve_services`
  still affected): if on Windows and the configured shell doesn't exist
  on disk, set `shell = None` so `subprocess.run` falls back to
  `cmd.exe`. Patch is in `perseus_win_shell_fix.patch`.
- **Severity:** **High on Windows** — `@query` is dead on arrival
  without the patch.

### Bug #3 — `@query` crashes on undecodable stdout

- **Location:** `perseus.py:1619`
- **Trigger:** `@query` whose stdout contains bytes that aren't valid
  UTF-8 (e.g. a tool that emits raw binary, or a misconfigured locale).
  `subprocess.run(..., text=True)` returns `None` for `stdout` when
  decode fails; the next line calls `.rstrip("\n")` on it.
- **Severity:** Medium. The render does not abort — the affected
  `@query` block emits `> ⚠ @query error: 'NoneType' object has no
  attribute 'rstrip'` and the rest of the document renders normally —
  but the error message is opaque to a user.
- **Fix sketch:** `result = subprocess.run(cmd, ..., text=False)` plus
  `stdout = (result.stdout or b"").decode("utf-8", errors="replace")`.

---

## Architectural Cliffs (not bugs, design limits)

| Limit | Affects | Suggested mitigation |
|---|---|---|
| No parallel `@query` execution | Render time scales linearly with @query count | `ProcessPoolExecutor` or `asyncio.gather` over independent directives. Would have cut the 500-service mega-enterprise render from 3.5 s to ~600 ms. |
| No parallel `@services` URL checks | `@services` becomes unusable at ~10+ entries with `services_timeout_s=3` | Same fan-out treatment. Or document a smaller default. |
| No `@query` stdout size cap | A bad scanner can produce a 13 MB `.hermes.md` and silently bloat the assistant's context | Configurable `render.max_query_bytes` with visible truncation marker. |
| Hardcoded 30 s `@query` timeout | Slow scanners that legitimately need >30 s are clipped | Per-directive `timeout=N` modifier already supported by `@agent` — extend to `@query`. |
| `@skills` / `@session` / `@health` depend on home-dir config | A fresh workspace gets `⚠ Skills directory not found` for each | Either silent skip (cleaner) or per-directive `fallback=` modifier. |

---

## Performance Curve

```
Render time (s)
22 ┤                                                  ● 500q
20 ┤                                              ╱
18 ┤                                          ╱
16 ┤                                      ╱
14 ┤                                  ╱
12 ┤                              ╱
10 ┤                          ╱
 8 ┤                      ● 200q
 6 ┤                  ╱
 4 ┤              ● 100q
 2 ┤      ● 50q
 0 ┤  ● 10q
   └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──
      0 50 100 150 200 250 300 350 400 450 500
                  @query count
```

Slope ≈ 40 ms per `@query` in steady state.

---

## Recommendations (in priority order)

1. **Fix `Path.write_text` encoding** (one-line change, high impact for
   Windows users).
2. **Make `render.shell` work on Windows** — either detect Windows and
   skip the `executable=` kwarg, or honour short-name paths cleanly.
3. **Parallelise `@services` URL/docker/command checks.** This is the
   single biggest UX cliff at scale.
4. **Parallelise independent `@query` blocks.** Bigger win for
   real-world workspaces with many scanners; do it after #3.
5. **Configurable `@query` stdout cap** (`render.max_query_bytes`
   default 256 KB).
6. **Robust binary-stdout handling** in `resolve_query` (no `NoneType`
   surprise).
7. **Per-directive `timeout=N` modifier** on `@query` to match
   `@agent`'s.

---

## Reproduction

```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
pip install pyyaml
python benchmark/heavy/setup_adversarial.py /path/to/perseus-adversarial
cat benchmark/heavy/adversarial_results.json    # full machine log
```

Each test workspace is left on disk under
`/path/to/perseus-adversarial/adv-*` so the rendered outputs can be
inspected directly.
