# Background daemon with graph-driven cache invalidation — Design Spike

**Task:** [task-64](../../tasks/task-64-daemon-cache-invalidation.md)
**Status:** Design spike — no code changes proposed in this doc.
**Author:** claude-opus-4-7 (claimed via `perseus agora claim`)
**Date:** 2026-05-24
**Phase:** post-v1
**Outcome:** Build a **v1 MVP** that augments `perseus watch` with graph-driven invalidation. Defer the full multi-source daemon (`perseus daemon`) until adoption justifies it.

---

## What exists today

Three subsystems already do most of the work this task asks about:

| Subsystem | Where | Role |
|---|---|---|
| `cmd_watch` ([serve.py:336](../../src/perseus/serve.py)) | mtime-polling loop with two-tick debounce | Detects *source* file changes, re-renders the whole document |
| `directive_dependency_graph` ([directives/query.py:236](../../src/perseus/directives/query.py)) | Static parse of source | Returns nodes with `resources: [{kind, value}]` and metadata flags (`executes_shell`, `reads_files`, `cacheable`, …) |
| Per-directive cache ([renderer.py](../../src/perseus/renderer.py)) | In-memory + disk | Keyed by `sha256(directive_line)`, modes: `session`, `ttl=N`, `persist`, `mock` |

What does **not** exist:
- A way to invalidate a single cache entry when its **input resource** changes (today only TTL or explicit `mock` clears entries).
- Anything watching the resources directives depend on — only the source markdown file is watched.
- A long-lived process that keeps the parsed graph + warm cache between renders.

The gap is small and well-shaped. The task's intuition is correct: the static graph already extracts the dependency edges we need.

---

## 1. Granular cache entries

**Current:** cache key = `sha256(directive_line)`. Two directives with identical text share an entry. TTL is the only invalidation trigger.

**Proposed:** keep the key. Add an optional **resource fingerprint** stored alongside the value. On read, the cache miss path triggers if either (a) TTL expired, or (b) any of the directive's tracked resources has a fingerprint that differs from the one recorded at write time.

```python
# Disk cache JSON entry today
{"expires": 1716595200.0, "value": "..."}

# Proposed (backward-compatible — old entries still load)
{"expires": 1716595200.0, "value": "...", "fingerprints": {"file:/etc/foo": "1716594000-1234"}}
```

The fingerprint per resource kind:

| `kind` | Fingerprint | Notes |
|---|---|---|
| `file` | `f"{mtime_ns}-{size}"` | Cheap. Use sha256 for files under N bytes if mtime granularity bites. |
| `directory` | `mtime_ns` of dir entry | Captures add/remove, not nested edits — explicit limitation. |
| `env` | current value | Long-lived process needs this since env can change via SIGHUP-reload. |
| `shell` | **not fingerprintable** | Shell directives keep TTL semantics. See §2 for trigger syntax option. |
| `key`, `schema` | already embedded in directive line | No additional fingerprint needed. |

The directive line hash stays the cache key — this preserves existing test fixtures and round-trip compatibility. The fingerprint is metadata that *might* invalidate, not a key component.

**Edge case:** a directive with `@cache ttl=300` and a watched file resource gets the **union** of invalidation triggers — first one to fire wins. This is the safe default.

## 2. Resource tracking

The graph already gives us `node["resources"]`. The daemon needs to map each resource to a check.

**File / directory:** polling-based mtime check. Same mechanism `cmd_watch` uses today, just per resource instead of per source. On Linux a real `inotify` backend would be cheaper at scale, but it requires `ctypes` glue or a dep — see §5.

**Env:** read `os.environ` on every cycle. Fast.

**Shell:** unsolvable without re-executing the command, which defeats the cache. Two acceptable answers:
1. **Keep TTL behavior.** `@query` directives without a TTL are evaluated once per daemon lifetime; with a TTL, they refresh on schedule. This matches current renderer behavior — no surprise.
2. **Optional `trigger=poll:Ns` modifier** (new syntax, not in MVP). Lets a user say "re-run this every N seconds in daemon mode without setting a TTL." Defer until requested.

**Services:** `@services` already runs health checks on its own cadence. Daemon mode can subscribe to health-state transitions as invalidation events for any directive that references the same service URL — but this needs a new resource-hint type (`{"kind": "service", "value": url}`) which the graph does not currently emit. Out of scope for v1 MVP.

**Minimum invalidation trigger set for MVP:** `file` and `directory` only. This covers `@read`, `@include`, `@list`, `@tree` — the directives most users hit. `@env`, `@query`, `@services` keep existing semantics.

## 3. Delta rendering

**Question the task asks:** when a single directive's output changes, can we splice the new value into the already-rendered artifact instead of re-rendering the whole source?

**Answer: no, and we shouldn't try.**

A typical render is sub-second with a warm cache — the rendered artifact is essentially `for line in source: maybe_swap_directive(line)`. With granular cache hits on every unchanged directive, the "full re-render" cost reduces to file I/O + cache lookups.

Splice-into-artifact would require:
- Byte-offset bookkeeping per directive (currently the renderer is line-oriented, not byte-oriented).
- Handling for changed output length (downstream offsets shift).
- Atomic-write semantics for the rendered file (partial writes mid-splice are visible to the LLM, which is exactly what we're trying to prevent).
- A new IR sitting between the source and the output.

That's a meaningful chunk of complexity to save milliseconds. The leverage is on **selective re-execution**, not selective output assembly.

**MVP behavior on invalidation:** invalidate the affected cache entry, then re-render the source end-to-end. All other entries hit warm cache. Output file is atomically replaced (write-temp + rename).

## 4. Daemon lifecycle

The task asks how a daemon would differ from `perseus watch` in ways that genuinely improve UX. Honest answer for the MVP: **not much, structurally — the win is what happens inside the loop, not around it.**

**Recommended MVP shape: extend `cmd_watch`, do not introduce a new `perseus daemon` command.**

```
perseus watch --graph                 # new flag — enables graph-driven invalidation
perseus watch --graph --interval 1    # already-supported interval flag
```

Same process model, same signal handling (`SIGINT`/`SIGTERM` already wired at [serve.py:314](../../src/perseus/serve.py)), same `--exit-on-error` semantics. The change is **inside** `_watch_loop`:

1. On startup: build the graph once. Record fingerprints for every `file`/`directory` resource.
2. Each tick: poll fingerprints. If any changed, *invalidate* (delete) the matching cache entries before re-rendering.
3. On render: existing cache machinery handles the rest.

When this proves out and a user actually asks for `perseus daemon` (multi-source supervisor, status RPC, systemd `Type=notify`, socket activation), that's a separate task. Premature daemonization adds surface area that nobody is asking for today.

**What we do not add in MVP:**
- New CLI verbs (`perseus daemon start/stop/status`)
- IPC sockets or HTTP control plane (the `perseus serve` HTTP server from task-18 already covers read-only access; daemon control can come later)
- systemd unit files (task-11 already shipped systemd integration for the watch command — the new flag rides on that)
- launchd parity (task-50 covers cross-platform scheduling separately)

## 5. Zero-dependency constraint

Task asks specifically: *"Can we do inotify via `select.poll` on `/proc/self/fd` or does this require a new optional dep?"*

**The premise is wrong.** `select.poll`/`epoll` watch *file descriptor readiness for I/O*, not filesystem change events. The real Linux primitive is `inotify_init1()` + `inotify_add_watch()`, which returns an fd you can `read()` from — and that fd *is* pollable with `select.poll`, which is probably what the task author was reaching for. But there are no inotify bindings in the stdlib. Options:

| Approach | Deps | Cross-platform |
|---|---|---|
| **mtime polling** | None | Yes |
| `ctypes` wrapper around `libc inotify_init1` | None (stdlib `ctypes`) | Linux only |
| `select.kqueue` watching VNODE events | None (stdlib) | macOS/BSD only, needs an fd per file |
| `ReadDirectoryChangesW` via `ctypes` | None (stdlib) | Windows only, dir-granularity |
| `watchdog` PyPI package | New dep | Yes, but `pyyaml`-only rule rules this out |

**MVP picks mtime polling.** Same code path the existing `cmd_watch` already uses — no new dep, no platform-specific code, no `ctypes` adventures. The performance hit (one `stat()` per resource per tick) is negligible for typical workspaces (tens of resources at most).

If a power-user case eventually demands event-driven watches on large trees, the `ctypes`/`kqueue` paths can be added behind a `[watch].backend = native|polling` config knob without breaking the MVP. **Defer until a real user complains.**

---

## Decision

### Is this worth building post-v1?
**Yes, in the MVP form (`perseus watch --graph`). No, in the full daemon form.**

The graph-driven invalidation is a real differentiator versus the polling-only `perseus watch` we ship today, and versus Memix's structural model (which re-indexes wholesale). The leverage is high because the graph and per-directive cache already exist — the missing piece is ~one screen of code wiring fingerprints into cache reads.

The full daemon (separate process, IPC, lifecycle commands) is not justified by current demand. `perseus watch` already serves the foreground use case; `perseus serve` covers the HTTP read-only case; the LSP server (task-23) covers editor integration. Adding a fourth long-running mode without a user asking for it is solution-in-search-of-problem.

### Minimum viable increment beyond `perseus watch`
A single new flag on the existing command:

```
perseus watch --graph [--interval N]
```

**What ships in the MVP:**
1. New cache JSON field `fingerprints: {resource_id: fingerprint}` — written on cache_set, checked on cache_get.
2. New helper `compute_resource_fingerprint(resource: dict) -> str | None` in `renderer.py` (returns `None` for unfingerprintable kinds).
3. `_watch_loop` builds the graph once at startup and on source change, tracks file/directory fingerprints, deletes stale cache entries before each re-render.
4. Backward compatibility: without `--graph`, behavior is **identical** to today. Cache entries written without `fingerprints` continue to honor TTL only.

**Estimated scope:** ~150–300 LOC added to `renderer.py` and `serve.py`. No new modules. No new dependencies. Existing tests continue to pass; new tests cover the fingerprint round-trip and the invalidation path.

**Non-goals confirmed:**
- No splice rendering.
- No native inotify/kqueue backend in the MVP.
- No new `perseus daemon` command.
- No new directive syntax (`trigger=poll:N` and `kind:service` are explicitly deferred).
- No invalidation for `@query`, `@env`, `@services` (TTL semantics retained).

### Suggested follow-up tasks (not auto-created — owner decides)
- `task-NN: cache fingerprint field + compute_resource_fingerprint helper` (renderer-only, no behavior change)
- `task-NN: perseus watch --graph flag + resource polling in _watch_loop` (depends on above)
- `task-NN: optional ctypes inotify backend behind config knob` (future, only if scale demands it)
- `task-NN: @services resource hints in directive graph` (prerequisite for service-state invalidation)
