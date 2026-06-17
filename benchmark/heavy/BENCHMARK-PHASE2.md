# Perseus Adversarial — Phase 2 (cache · concurrency · memory · CLI · LSP)

**Date:** 2026-05-23
**Perseus:** v1.0.1 + local Windows shell-fallback patch
**Host:** Windows 11 · Python 3.14.2 · `psutil` 7.2.2 available

Covers the gaps the original adversarial run skipped. Machine-readable
log: `phase2_results.json`.

---

## Headline

```
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│   @cache ttl=300 / persist     →  15× warm-render speedup             │
│   Concurrent renders          →  safe up to 10 instances              │
│   Memory at 500 @query        →  51 MB Perseus RSS, 71 MB combined    │
│   Memory at 12 MB @query stdout → 67 MB RSS (5.6× the stdout size)   │
│   LSP `initialize` handshake  →  works, ~0.2 s, capabilities returned │
│   `perseus graph/prefetch/synthesize/health/--help`  →  all OK on    │
│     Windows IFF PYTHONUTF8=1 is set                                  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## C. Cache behaviour

Each test renders the **same 5-query workspace twice**. Each query
sleeps 0.6 s, so cold render ≈ 3.0 s + Perseus overhead. If cache
works the second render returns near-instantly.

| Test | Cache modifier | Cold | Warm | Speedup | Result |
|---|---|---:|---:|---:|---|
| C1 | _none_ | 3.460 s | 3.431 s | 1.01× | ✅ as expected — no cache, no speedup |
| C2 | `@cache ttl=300` | 3.477 s | **0.229 s** | **15.18×** | ✅ works exactly as documented |
| C3 | `@cache persist` | 3.443 s | **0.219 s** | **15.72×** | ✅ disk-cache survives subprocess death |
| C4 | `@cache session` | 3.406 s | 3.422 s | 1.00× | ✅ session lives within one render only — no cross-render benefit (correct) |

### Implications

- The mega-enterprise audit (3.47 s, 25 @query) → **~230 ms** on warm
  cache if every scanner gets `@cache ttl=300`. That's ~15× the
  reported headline number, achievable today without code changes.
- Caching is the single biggest practical optimisation available to a
  user today. **None of the existing benchmark contexts use it.**
  Recommendation: ship `setup_mega.py` and `setup_mixed.py` variants
  that demonstrate `@cache ttl=` on every scanner.
- `@cache session` is genuinely a no-op across separate render
  invocations. The documented semantics ("run once per render, reuse
  after") match observed behaviour. Useful when the same `@query`
  appears multiple times in one `context.md`; useless for the cron
  loop case.

---

## D. Concurrency — N parallel `perseus render` processes

Each render targets its own workspace with 30 trivial @query blocks
(baseline serial render: ~1.0 s). Spawned via `ThreadPoolExecutor`.

| N | Workspace | Wall clock | Per-render (min/max) | All exit-0 | Notes |
|---:|---|---:|---:|---|---|
| 2 | isolated | 1.54 s | 1.54 / 1.54 s | ✅ | Per-render ~50 % slower under contention |
| 5 | isolated | 1.88 s | 1.88 / 1.88 s | ✅ | Linear-ish slowdown |
| 10 | isolated | 3.11 s | 2.92 / 3.11 s | ✅ | Visible contention at 10× — likely subprocess pool exhaustion on Windows |
| 2 | **shared workspace** | 1.73 s | — | ✅ | Two renders against same `.perseus/` dir, different output files — no corruption |

### What this tells us

- **Perseus is safe to run concurrently.** No file-lock errors, no
  half-written output, no cache-corruption symptoms across 2 / 5 / 10
  parallel renders.
- Running 10 parallel renders **does not 10×** the throughput — each
  individual render takes ~3 s vs ~1 s standalone. Bottleneck is
  subprocess creation (likely Windows `CreateProcess` serialisation
  in the kernel).
- A cron loop firing while a previous render is still going is fine.
  No race on `.hermes.md` write observed at 2-shared.
- **Not tested:** two renders writing to the **same** `.hermes.md`
  output path. The atomicity of `out_path.write_text` on Windows
  is left as an open question.

---

## E. Memory footprint

`psutil` polled the Perseus parent and its subprocess tree every 50 ms.

| Test | Wall | Peak Perseus RSS | Peak combined RSS | Output file | Notes |
|---|---:|---:|---:|---:|---|
| E1: 500 @query render | 21.6 s | **51.6 MB** | 71.6 MB | 53 KB | Combined peak ~71 MB across Perseus + 25-deep subprocess tree |
| E2: single 12 MB stdout | 1.3 s | **67.6 MB** | 84.2 MB | 13.2 MB | Perseus holds ~**5.6×** the stdout size in RSS while rendering |

### Implications

- Perseus itself is modest — ~50 MB resident for the heaviest sane
  workload. No memory leaks across 500 sequential @query.
- **A large `@query` stdout amplifies memory roughly 5–6×** in Perseus.
  A 12 MB scanner output costs ~67 MB Perseus RSS during the render.
  At 100 MB stdout this could approach 500 MB — combined with the
  fact that Perseus has no `max_query_bytes` cap, this is a real DoS
  vector if a runaway scanner output is allowed through.

---

## F. CLI surface coverage

All commands invoked from the harness with `PYTHONUTF8=1` set.

| # | Command | rc | Elapsed | stdout | Result |
|---|---|---:|---:|---:|---|
| F1 | `perseus graph <ctx> --json` | 0 | 0.20 s | 1.7 KB | ✅ Returns full directive graph as JSON |
| F2 | `perseus prefetch <ctx>` (no rules) | 0 | 0.20 s | 177 B | ✅ Reports `Rules: 0 Matches: 0 Ran: 0` |
| F3 | `perseus prefetch <ctx>` (with rules) | 0 | 0.25 s | 222 B | ✅ Triggered rule matches and warmed cache |
| F4 | `perseus synthesize <question> --source <md>` | 0 | 0.20 s | 905 B | ✅ Emits cited-synthesis prompt (no LLM run) |
| F5 | `perseus health` | 0 | 0.21 s | 219 B | ✅ Reports clean maintenance state |
| F6 | `perseus --help` | 0 | 0.20 s | 2.4 KB | ✅ **iff `PYTHONUTF8=1`** — see bug below |

### Sample outputs

**`perseus graph`** returns a structured directive graph — useful as a
machine-readable surface for editors / agents that want to know what a
context file will do without running it:

```json
{
  "source": ".../.perseus/context.md",
  "workspace": "...",
  "nodes": [
    {"id": "n1", "directive": "@query", "line": 3, "kind": "inline",
     "args": "\"echo hi\"", "cache": {...}}
  ]
}
```

**`perseus prefetch` with rules** correctly executed a configured
prefetch rule and warmed the cache for the downstream `@query`:

```
Prefetch: .perseus/context.md
Rules: 1  Matches: 1  Ran: 1  Skipped: 0  Failed: 0
- ran: status-diff n1 -> @query "git diff --stat" @cache ttl=300 (cached)
```

**`perseus synthesize`** correctly built a citation-enforcing prompt
but did not run any LLM (no `--enable-generation` flag):

```
Cited synthesis: What is the next allowable action?
Sources:
- src1 ROADMAP.md (8 lines)
Generation was not run. Prompt: ...
```

### Bug #4 — `perseus --help` (and other commands) crash without `PYTHONUTF8` on Windows

When the harness env is plain (no `PYTHONUTF8=1`), `perseus --help`
on Windows fails with:

```
UnicodeEncodeError: 'charmap' codec can't encode character 'ē'
(`ē`, from "Mnēmē") in position 1397
```

Same root cause as bug #1 — Python on Windows defaults stdout to
`cp1252`, which can't encode Perseus's own help text. With
`PYTHONUTF8=1` set, all commands work. This means **Perseus on a
fresh Windows install can't display its own `--help` text** until the
user sets an environment variable.

Suggested fix: at startup, `sys.stdout.reconfigure(encoding="utf-8",
errors="replace")` before any output, or wrap help generation in a
safe encoder.

---

## G. LSP basic ping

Sent a minimal LSP `initialize` request over stdio, waited for response,
then sent `shutdown` + `exit`.

| Metric | Value |
|---|---|
| `initialize` round-trip | **0.20 s** |
| Response `id` | 1 ✅ |
| `result.capabilities` present | ✅ |
| Server clean exit (rc=0) | ✅ |

The LSP server is **functional and well-behaved**. JSON-RPC framing
(Content-Length headers + LF body) is correct; the shutdown/exit
handshake works. This is real, not stubbed.

---

## Consolidated findings, updated

### Real bugs (now four)

| # | Location | Description | Severity (Win / POSIX) |
|---|---|---|---|
| 1 | `perseus.py:7121` | `Path.write_text(rendered)` ignores encoding | **High** / none |
| 2 | `perseus.py:1558`, `2941` | Default `shell="/bin/bash"` is unreachable on Windows; can't be repaired via config because `subprocess.run(executable=...)` mangles paths with spaces | **High** / none |
| 3 | `perseus.py:1619` | `@query` crashes with `'NoneType' object has no attribute 'rstrip'` on undecodable stdout | Medium / Medium |
| 4 | argparse help text | `perseus --help` crashes on Windows under default locale due to `ē` in "Mnēmē" | **Medium** / none |

### Architectural cliffs (now five)

| # | Limit | Quantified impact | Mitigation |
|---|---|---|---|
| α | Sequential `@query` | Linear render time; 500 svc audit = 3.5 s (could be ~600 ms parallel) | `ProcessPoolExecutor` |
| β | Sequential `@services` URL checks | 100 entries @ 3 s default = 5 min serial | Same fan-out |
| γ | No `@query` stdout cap | 12 MB scanner output → 67 MB Perseus RSS + bloated context | `render.max_query_bytes` |
| δ | Hardcoded 30 s `@query` timeout | Slow scanners get clipped | Per-directive `timeout=N` |
| ε | 10× concurrent renders → per-render gets 3× slower | Cron+manual overlap shows real contention | Acceptable; possibly subprocess pool on Windows |

### What now works that I didn't expect to

- **`@cache ttl=300` and `@cache persist` are real** and deliver 15×
  warm-render speedups out of the box.
- **Concurrent renders are safe.** No file locks, no race corruption
  in 2-shared workspace test.
- **LSP server is real** and the JSON-RPC handshake works in 200 ms.
- **`perseus synthesize` honours its citation contract** by default —
  it builds the cited-synthesis prompt but doesn't run an LLM unless
  `--enable-generation` is passed. Safe by default.

---

## Reproduction

```bash
git clone https://github.com/Perseus-Computing-LLC/perseus.git
cd perseus
pip install pyyaml psutil
python benchmark/heavy/setup_phase2.py /path/to/perseus-phase2
cat benchmark/heavy/phase2_results.json
```

Each test workspace is left under `/path/to/perseus-phase2/ph2-*` for
inspection.

---

## Recommendations (revised, in priority order)

1. **Fix Windows `write_text` and `--help` encoding** (bugs #1, #4) —
   two-line change, unblocks Perseus on every fresh Windows install.
2. **Document `@cache ttl=` prominently in the README headline.** It's a
   15× speedup users aren't using.
3. **Parallelise `@services` URL checks.** Worst UX cliff at scale.
4. **Parallelise `@query`.** Bigger absolute win on heavy contexts.
5. **Cap `@query` stdout size** with visible truncation marker.
6. **Fix Windows shell default** (bug #2) — `@query` and `@services
   command:` are both broken on Windows out of the box.
7. **Robust binary-stdout handling** in `resolve_query` (bug #3).
8. **Per-directive timeout modifier** on `@query` (`timeout=N`).
