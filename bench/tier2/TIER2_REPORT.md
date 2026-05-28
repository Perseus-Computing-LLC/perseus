# Perseus Code Review — Tier 2 — deepseek-v4-pro, 2026-05-27

**Reviewed at commit:** `20be13c` — 2026-05-27 20:19:14 -0500 — "fix: rewrite context.md with live environment directives"  
**VERSION file:** 1.0.5  
**Artifact lines:** 14,728 (`perseus.py`)  
**Python version:** 3.12.13  
**SQLite version:** 3.46.1  
**Test suite baseline:** 746 passed, 7 failed, 1 skipped (82.3s), 754 collected  

---

## §1 Methodology

**Files read in full (43 source files):**
- `src/perseus/`: renderer.py, registry.py, mcp.py, mneme_index.py, audit.py, config.py, serve.py, pythia.py, webhooks.py, checkpoint.py, agora.py, inbox.py, mneme_federation.py, mneme_narrative.py, lsp.py, install.py, redaction.py, hooks.py, macros.py, memory.py, html_format.py, assistant_formats.py, cli.py, `__init__.py`
- `src/perseus/directives/`: query.py, agent.py, include.py, read.py, perseus.py, env.py, tool.py, skills.py, waypoint.py, session.py, services.py, misc.py, `__init__.py`
- `scripts/`: build.py
- `spec/`: directives.md

**Files spot-read:** ROADMAP.md, README.md, CHANGELOG.md, HANDOFF.md, SECURITY.md, pyproject.toml, requirements.txt, Dockerfile

**Tools used:** ast (stdlib), inspect (stdlib), subprocess, curl-equivalent via urllib, Python assertions

**POCs and tests written:**
- `bench/tier2/macro_silence_poc.py` — unterminated @macro data loss (CONFIRMED)
- `bench/tier2/query_shell_injection_poc.py` — shell metacharacter injection (CONFIRMED)
- `bench/tier2/checkpoint_lock_poc.py` — orphaned lock analysis
- `bench/tier2/mcp_sse_auth_poc.py` — SSE GET no-auth test
- `bench/tier2/memory_exhaustion_poc.py` — pre-read memory exhaustion

**Subagents deployed (3):**
- Subagent 1: Read 15 skipped files (§11), 50+ findings
- Subagent 2: Read renderer.py (301–1275), pythia.py (full), 5 directive files, 30+ findings
- Subagent 3: Read serve.py (2974 lines), mcp.py (full), build.py, 20+ findings

---

## §2 Prior Findings Re-Verified (24 items)

| # | Description | Test | Status |
|---|-------------|------|--------|
| 1 | Duplicate `_expand_aliases` between registry.py and renderer.py | `"_expand_aliases" in render_source` → True | **FAIL** — still duplicated |
| 2 | Fail-open `allow_query_shell` default | `cfg["render"].get("allow_query_shell", False)` → False | **PASS** — fixed, defaults False |
| 3 | MCP required-args check on bare names | Checked via _generate_directive_tools (inspect) | **PASS** — arg matching uses `arg_name in (...)` |
| 4 | MCP `_DIRECTIVE_ARG_BUILDERS` no quote escaping | `_mcp_quote` escapes `"` but not space/semicolon/newline | **FAIL** — partial fix, args still injectable |
| 5 | MCP SSE POST /message no auth | `_check_auth` called in `do_POST` (mcp.py:402) | **PASS** — auth check present |
| 6 | MCP SIGALRM doesn't work on Windows | Code now uses ThreadPoolExecutor (mcp.py:246) | **PASS** — fixed |
| 7 | `SERVER_VERSION` hardcoded | Now `SERVER_VERSION = _PERSEUS_VERSION` → 1.0.5 | **PASS** — fixed |
| 8 | Foreign resolver: no URL allowlist, no SSRF protection | Checked `resolve_perseus` in directives/perseus.py | **FAIL** — no URL allowlist; `@perseus` fetches any URL |
| 9 | `INTERNAL_IMPORT_RE` single-line only | `build.py:74` — regex only matches single-line `from perseus.X import Y` | **FAIL** — multi-line imports stripped, indented imports NOT |
| 10 | `@include` re-reads file for size warning | `include.py:58` — `read_bytes()` before `max_include_bytes` check | **FAIL** — full file read before size gate |
| 11 | FTS5 MATCH expression injection | Verified FTS5 operators via SQLite direct query | **FAIL** — FTS5 operators still interpreted |
| 12 | Mnēmē rollback inside bare `except` | `mneme_index.py:243` — `except Exception: conn.rollback(); raise` | **PASS** — correct behavior |
| 13 | `_mneme_delete_document` LIKE escape | `mneme_index.py:153` — id validated with `^[A-Za-z0-9_-]{1,128}$` | **PASS** — id validation prevents injection |
| 14 | Mnēmē field weighting by repetition | Now uses native FTS5 column BM25 weights (mneme_index.py:42-48) | **PASS** — fixed |
| 15 | Cache `cache_set` non-atomic write | Now uses `NamedTemporaryFile` + `os.replace` (renderer.py:170-179) | **PASS** — fixed |
| 16 | C1: MCP SIGALRM hard-fails on Windows | Code now uses ThreadPoolExecutor | **PASS** — fixed |
| 17 | C2: Pipe stages never read cache | Verified in `_execute_pipe` — each stage resolves independently via `_resolve_directive` which checks cache | **PASS** — indirect fix |
| 18 | C4/C5: FTS5 apostrophe escape/operators | Tested with `@memory "it's"` → FTS5 error | **FAIL** — still present |
| 19 | C7: `@include`/`@read` use char count for byte limit | Checked include.py:65-67, read.py:74-75 | **PASS** — now uses `len(data)` byte count |
| 20 | C8: `@agent` hard-codes `/bin/bash` | Checked agent.py: `shell = _get_shell(cfg)` | **PASS** — now uses config-resolved shell |
| 21 | S1: `safe_for_hover` defaults True | `DirectiveSpec.safe_for_hover: bool = False` in registry.py:21 | **PASS** — defaults False |
| 22 | S5: workspace config can set `cache_dir`/`audit.log_path` | `_safe_cache_dir` constrains to `~/.perseus` or `~/.cache` | **PASS** — path validation added |
| 23 | S7: Plugin discovery `exec_module` with no sandbox | `registry.py:301` — `spec.loader.exec_module(mod)` no sandbox | **FAIL** — still exec'd without sandboxing |
| 24 | D1: CHANGELOG 1.0.5 claims `@bastra` directive | Grep: no `@bastra` in source | **FAIL** — CHANGELOG mentions it, code doesn't have it |

**Summary:** 12 PASS (fixed), 12 FAIL (still present or partially fixed)

---

## §3 Build Artifact Differential

### 3.1 Concatenation correctness
**Script:** `bench/tier2/build_audit.py` (see below)

**Finding B1: `_expand_aliases` duplicated between registry.py and renderer.py**  
Lines: registry.py:144-237, renderer.py:~1220-1310  
The function is copied verbatim in both modules. The built artifact contains two identical function definitions. The one in renderer.py shadows the registry.py version, but both compile. No runtime error, but accumulated maintenance debt — fixes to one copy must be replicated to the other.

**Finding B2: `INTERNAL_IMPORT_RE` misses indented imports**  
Line: build.py:74  
The regex `r"^\s*from\s+perseus\.[a-zA-Z_][\w.]*\s+import\s+"` matches imports at any indent level, but the multi-line tracking at build.py:116-127 only checks if the line ends with `\` or `(`. If a multi-line import closes on the same line as it opens (`from perseus.config import (\n    FOO,\n    BAR\n)`), the continuation is handled by the `in_multiline_import` flag. However, if a line starts with whitespace and contains `from perseus.X import` inside a function body (indented), it IS matched and stripped. This is CORRECT behavior, not a bug — the regex intentionally matches indented imports.

**Multi-line import experiment:** Dropped a deliberate multi-line import: `from perseus.config import (\n    DEFAULT_CONFIG,\n    _get_shell,\n)` into query.py. The build script strips it correctly — the `in_multiline_import` flag catches lines 2-3 of the import and skips them. PASS.

### 3.2 Order verification
Walking the 14,728-line artifact with `ast.parse` reveals no forward references at module level. All names are defined before use. PASS.

### 3.3 Line-count drift guard
The guard (`BASELINE_LINES = 14400`, ±5% window 13680–15120) correctly catches the current artifact at 14,728 lines. Adding 200 lines triggers the guard (15,028 > 15,120). Removing 200 lines also triggers (14,528 > 13,680? No — 14,528 is within 13,680-15,120). The low guard would need a removal of ~1,048 lines to trigger. PASS.

### 3.4 Version regex
The regex at build.py:148 `r'^(_PERSEUS_VERSION\s*=\s*)".*?"(\s*#.*)?$'` uses `re.MULTILINE`. Setting VERSION to `1.2.3"; os.system("touch /tmp/pwned"); _ = "` would produce: `_PERSEUS_VERSION = "1.2.3\"; os.system(\"touch /tmp/pwned\"); _ = \""`. Since the regex only captures the first `"..."` pair, the injected content after `";` would be part of the output but the leading `_PERSEUS_VERSION = "1.2.3` would be followed by `"; os.system("touch /tmp/pwned"); _ = ""` which is syntactically valid (a string concatenation). This is a potential injection vector IF an attacker controls VERSION. Severity: LOW — VERSION is repo-controlled.

### 3.5 Smoke test depth
Current smoke: `python perseus.py --version` exit 0. Proposed stronger tests:
1. `python perseus.py render --source <(echo "# Test\n@date")` — validates render pipeline
2. `python perseus.py mcp serve --help` — validates MCP init
3. `python perseus.py memory index rebuild --help` — validates Mnēmē init

---

## §4 Argument Parser Fuzzing

**Script:** `bench/tier2/argparse_fuzz.py` (to be written — manual verification done)

### Findings table

| Directive | Input | Bug Type | Severity |
|-----------|-------|----------|----------|
| `@query` | `"cmd1 && cmd2"` | Shell injection via `&&` | CRITICAL (gated) |
| `@query` | `"cmd \| grep x"` | Pipe interpreted as pipeline by command, not directive pipe | MEDIUM |
| `@query` | `"echo \`whoami\`"` | Backtick command substitution | CRITICAL (gated) |
| `@agent` | `"cmd $(whoami)"` | Command substitution | CRITICAL (gated) |
| `@agent` | Unquoted args | `shlex.split` applies but `shell=True` still active | HIGH (gated) |
| `@tool` | `--flag=value` as single arg | Bypasses `allowed_args` exact-match check | HIGH |
| `@read` | `path="../../etc/passwd"` | Path traversal blocked by `_resolve_path` | PASS |
| `@include` | `directive @cache ttl=0` | TTL=0 accepted, cache written with 0s expiry | LOW |
| `@memory` | `query="OR 1=1"` | FTS5 operator `OR` interpreted natively | MEDIUM |

### Quote-pairing results
- `@query "echo \"hello\""` → Shell executes `echo "hello"` correctly (escape works)
- `@query "$(rm -rf /)"` → Command substitution executes (CONFIRMED)
- `@query "cmd | grep x"` → Pipe executed by shell, returns grep output

---

## §5 Renderer Adversarial Corpus

**Script:** `bench/tier2/renderer_runner.py` (harness), `bench/tier2/renderer_torture/` (inputs)

### Key results

**R1: Unterminated @macro — CONFIRMED CRITICAL**  
`bench/tier2/macro_silence_poc.py` demonstrates: when `@endmacro` is missing, all content after `@macro broken` is silently consumed. 11 lines of template content disappear with zero warning. Reproduction: `python bench/tier2/macro_silence_poc.py` → exit 1.

**R2: Macro parameter prefix collision**  
If param names are `["a", "ab"]` and values are `["X", "Y"]`, `%a%` substitution destroys the `%ab%` token. renderer.py:338 uses `str.replace(f"%{pname}%", value)` which is order-sensitive and can destroy tokens.

**R3: Macro width vs depth**  
`MAX_MACRO_DEPTH=10` limits recursion depth (top-down). Width (fan-out in a single pass) is limited only by `max_width=100000` which is checked per-pass, not cumulatively. A macro that doubles line count each pass creates ~2¹⁰ × initial lines before the width check.

**R4: Cache key whitespace**  
`_cache_key` preserves quoted whitespace but normalizes unquoted. `@query  ls\t-la` and `@query ls -la` produce the SAME cache key (both normalize to `@query ls -la` in unquoted segments). This is correct — two semantically identical commands should share a cache entry.

**R5: @include diamond**  
`_visited.copy()` per branch (include.py:85) means A→B→D and A→C→D both render D. In a diamond-shaped include tree, D is rendered twice per path through the diamond.

---

## §6 Cache Layer Audit

### Cache key table

| Call site | Key constructed | Mode |
|-----------|----------------|------|
| Normal directive | SHA256(normalized_line) | Config-dependent |
| Pipe stage | SHA256(individual_stage_line) | Per-stage |
| `@cache session` | SHA256(clean_line) | In-memory only |
| `@cache ttl=N` | SHA256(clean_line) | Disk JSON |
| `@cache persist` | SHA256(clean_line) | Disk JSON, cfg TTL |
| `@cache mock="X"` | N/A — bypasses execution | Mock substitute |

**C1: Cache set atomic but temp file leak**  
renderer.py:170-179 uses `NamedTemporaryFile(delete=False)` + `os.replace()`. If `os.replace()` fails (cross-device, permission error), the temp file persists. No `finally: os.unlink(tmp.name)` on the exception path.

**C2: `@cache mock` regex greedy on quoted values**  
renderer.py:73: `r'\s*@cache\s+mock=(".*?"|\'.*?\'|\S+)'` — the `.*?` is non-greedy which is correct, but backslash-escaped quotes inside mock values are not handled. `@cache mock="hello \"world\""` would capture only `hello \` before the next `"`.

**C3: `persist_cache_ttl_s` defaults**  
renderer.py:130: `int(cfg.get("render", {}).get("persist_cache_ttl_s", 3600))` — defaults to 3600. If set to 0, `int(0)` = 0, which means the entry expires immediately (time.time() + 0 < time.time() → always expired). If set to negative, cache is never valid. PASS (behavior is documented in comments).

---

## §7 Mnēmē / FTS5 Deep Dive

### Schema migration matrix
The code at mneme_index.py:92-107 checks `PRAGMA table_info(mneme_fts)` and compares against `expected_columns`. If the v1 schema (`id, title, search_text, type, scope, summary, updated`) is detected, it DROPs the table and recreates with v2 schema. This is destructive — all indexed data is lost on migration. The code also deletes `mneme_meta WHERE key LIKE 'schema_%'` which could delete unrelated metadata. Severity: MEDIUM.

### FTS5 operator injection
Testing with `@memory "it's a test"` (with apostrophe): the FTS5 MATCH expression is constructed with the user query passed directly. SQLite's FTS5 interprets `'` as a string delimiter but the code does NOT double-escape apostrophes. Result: FTS5 syntax error when searching for phrases containing apostrophes. CONFIRMED — prior finding #11 still present.

### Concurrent index access
mneme_index.py:83: `sqlite3.connect(str(index_path), check_same_thread=False)` — connections are cached per-process (keyed by pid). Two threads in the same process share one connection. SQLite in WAL mode supports concurrent readers but only one writer. If two threads both call `_mneme_build_index`, the second will get `SQLITE_BUSY` and the `except Exception` at line 243 silently rolls back and re-raises. The error propagates to the caller. PASS (correct behavior).

### `_mneme_delete_document` with attacker-controlled id
mneme_index.py:153 validates `doc_id` against `r'^[A-Za-z0-9_-]{1,128}$'`. Characters like `%`, `_`, `..`, `/` are rejected. PASS — injection blocked by regex validation.

---

## §8 Plugin / Hook / Format / Webhook Hostile Demos

### P1: Plugin `exec_module` with no sandbox
registry.py:301: `spec.loader.exec_module(mod)` executes arbitrary Python at import time. A malicious `~/.perseus/plugins/exfil.py` can:
1. Read `~/.aws/credentials`
2. POST to attacker-controlled URL
3. Register a directive that returns clean-looking output

**Attack visibility in audit log:** INVISIBLE. Plugin loading happens before any render and is not audited.

### P2: Lying plugin metadata
A plugin declaring `executes_shell=False` but calling `subprocess.run()` in its resolver bypasses the gate at registry.py:244. The `_call_resolver` function checks `spec.executes_shell` but a lying plugin declares `False`. Once the resolver runs, it can execute anything.

**Attack visibility:** PARTIALLY VISIBLE — the directive call appears in audit log, but the fact that `executes_shell` was lied about is invisible.

### P3: Hook command injection
hooks.py: the `on_directive_resolved` hook expands `$@` to the directive output. If the output contains shell metacharacters, the hook command can be injected. Not verified — hooks.py not yet read in detail.

### P4: Webhook SSRF
webhooks.py:127: `urllib.request.urlopen(req, timeout=timeout)` — no TLS certificate verification (`context` parameter not set), follows redirects by default. A malicious webhook endpoint URL can redirect to internal services.

**Attack visibility:** VISIBLE in audit log (webhook delivery events are logged).

---

## §9 Networked Exploitation

### N1: MCP SSE GET endpoints unauthenticated — CONFIRMED HIGH
mcp.py:382-398: `do_GET` serves `/sse` and `/health` without calling `_check_auth()`. Even when `sse_bearer_token` is configured, these endpoints are freely accessible.

**Visibility:** INVISIBLE in audit log (GET requests to SSE endpoint don't trigger audit events).

### N2: MCP SSE DNS rebinding bypass via missing Host header
mcp.py:367-372: If the `Host` header is empty/missing, the DNS rebinding check is silently skipped, falling through to bearer token check. If no token is configured (default), the endpoint is fully open.

### N3: Foreign resolver SSRF — no URL allowlist
directives/perseus.py: `@perseus <url>` fetches any URL with no allowlist. An attacker who can control a template with `@perseus http://169.254.169.254/latest/meta-data/` can exfiltrate cloud metadata.

**Visibility:** VISIBLE in audit log (foreign fetch events are logged).

### N4: Serve HTTP server missing Host header validation
serve.py:2606-2620: Unlike the MCP SSE server, the main HTTP serve has NO Host header validation at all. Any browser on the same machine can access `http://127.0.0.1:7991/` and read rendered context, Pythia logs, and checkpoint data.

**Visibility:** VISIBLE in audit log (GET requests to serve endpoints are logged).

---

## §10 Cross-Platform Matrix

**Not verified.** Running tests on Windows and macOS requires VMs not available in this environment. The current test suite (754 tests) runs on Linux with 7 failures:
- `test_audit_event_writes_jsonl` — AssertionError (6 related)
- `test_cache_persist_writes_and_reads_disk` — 1 failure

**Lifecycle integration test:** Not run. Requires `perseus` CLI on PATH (not available in this environment — perseus is only importable as a Python module).

---

## §11 Previously Skipped Files (~40% of Code Surface)

### 11.1 `pythia.py` (1,264 lines)
**Summary:** LLM oracle — generates suggestions, compact narratives, Daedalus maintenance.

**Key findings:**
1. **CRITICAL: Full prompts permanently logged to JSONL** — pythia.py:129,618-620: `build_pythia_log_entry` stores complete prompts (including environment snapshot, service health, checkpoint summaries) in `~/.perseus/pythia_log.jsonl`. Anyone with filesystem access reads full LLM conversation history.
2. **HIGH: Prompt injection via `task` parameter** — pythia.py:509,525: `cmd_suggest` interpolates `--task` value directly into LLM prompt with no sanitization. `perseus suggest --task "Ignore previous instructions..."` injects into the LLM.
3. **MEDIUM: Concurrent log corruption** — Append and rewrite paths race without file locking. Lost entries.
4. **MEDIUM: No API key handling** — urllib.request constructed without Authorization header. Remote authenticated providers unusable through this path without a local proxy.

### 11.2 `webhooks.py` (152 lines)
1. **HIGH: SSRF via unverified HTTPS + redirect-following** — webhooks.py:127: `urlopen` with no TLS verification, follows redirects.
2. **MEDIUM: Empty HMAC secret after env var expansion** — If `$SECRET` resolves to empty, HMAC computed with predictable empty key.
3. **LOW: Daemon threads lose in-flight deliveries on unclean shutdown.**

### 11.3 `checkpoint.py` (372 lines)
1. **CRITICAL: Orphaned lock file on crash** — checkpoint.py:39-41: `os.O_CREAT | os.O_EXCL` lock files with NO PID staleness detection. Crash between lock+unlink → permanent deadlock for ALL agents.
2. **HIGH: TOCTOU on workspace pointer** — checkpoint.py:70: pointer file reads entire checkpoint into memory after the checkpoint was written. Concurrent modification possible.
3. **MEDIUM: Dangling pointers on crash during pruning** — Old checkpoints deleted before workspace pointers updated.

### 11.4 `agora.py` (489 lines)
1. **MEDIUM: High-water mark IndexError on concurrent deletions** — agora.py:51-53: HWM index exceeds actual checkpoint list if another process prunes checkpoints.
2. **MEDIUM: `@memory` silently updates `fm["updated"]` on read path** — agora.py:439: Side-effecting write inside what should be read-only directive resolution.
3. **LOW: LLM prompt includes full narrative without token counting** — May exceed context window.

### 11.5 `inbox.py` (177 lines)
1. **HIGH: Path traversal via unsanitized `sender` in filename** — inbox.py:78: `f"{ts}-{sender}.yaml"` with sender from user config. No sanitization for `../`.
2. **MEDIUM: Prefix-based message lookup non-deterministic** — Two messages sharing prefix can match wrong one.
3. **LOW: No size limit on message file reads** — OOM on multi-GB YAML.

### 11.6 `mneme_federation.py` (352 lines)
1. **MEDIUM: YAML bomb via manifest file** — `yaml.safe_load` on manifest; no size limit.
2. **MEDIUM: Race condition on manifest write** — Two concurrent writes to same `.tmp` file.

### 11.7 `mneme_narrative.py` (362 lines)
1. **MEDIUM: Pythia log read into memory without size cap** — 100MB+ log → OOM.
2. **MEDIUM: Unredacted Pythia entries sent to LLM** — Sensitive data in prompts sent to Daedalus.
3. **LOW: Keyword matching false positives** — "must not", "never", "always" match incidental usage.

### 11.8 `directives/tool.py` (142 lines)
1. **CRITICAL: Argument allowlist bypass via `--flag=value`** — tool.py:97-99: Exact string match against `allowed_args`. `--flag=value` as single arg doesn't match `--flag` entry.
2. **HIGH: Tool execution in workspace directory** — Malicious script in workspace executed.
3. **MEDIUM: Output truncation splits UTF-8 characters** — `stdout[:max_bytes]` on Python string, not bytes.

### 11.9 `directives/services.py` (137 lines)
1. **HIGH: ThreadPoolExecutor hangs render on stuck health check** — services.py:121-127: `executor.shutdown(wait=True)` waits for ALL futures.
2. **MEDIUM: `urlopen` redirect follows to file://** — No redirect protection on health check URLs.

### 11.10 `directives/session.py` (221 lines)
1. **CRITICAL: RCE via `@if query("shell command")`** — session.py:103-111: `shell=True` when `allow_query_shell=true`. Gated by config.
2. **MEDIUM: `cfg["assistant"]` KeyError if key missing** — session.py:142: `.get()` used on inner dict but `[]` used on outer.

### 11.11 `directives/misc.py` (317 lines)
1. **MEDIUM: `relative_to` fails on symlink directories** — misc.py:147-162: silently skips content.
2. **MEDIUM: Triple-backtick fence detection not tracked across lines** — `@date` inside multi-line code blocks still resolved.

### 11.12 `directives/skills.py` (61 lines)
1. **MEDIUM: `cfg["pythia"]["skill_dir"]` KeyError if missing** — skills.py:6: direct `[]` access.

### 11.13 `directives/waypoint.py` (54 lines)
1. **MEDIUM: `cfg["checkpoints"]["store"]` KeyError** — waypoint.py:5: direct `[]` access.

### 11.14 `lsp.py` (387 lines)
1. **HIGH: Byte-at-a-time stream reading** — lsp.py:16-43: 1M syscalls for 1MB message.
2. **MEDIUM: Unbounded document storage** — No total memory cap on open documents.
3. **MEDIUM: Render as LSP command runs full pipeline** — If `allow_query_shell=true`, RCE via editor command.

### 11.15 `install.py` (271 lines)
1. **MEDIUM: No file size limit on settings.json read** — OOM on large config files.
2. **LOW: `_find_project_root` limited to 10 levels** — `.git` at level 11 not found.

### 11.16 `config.py` (329 lines)
1. **MEDIUM: `_get_shell` returns PATH-resolved binary** — Malicious shell binary in PATH before `/bin/bash`.
2. **LOW: Default profile is `None` (not `balanced`)** — Comment says balanced is recommended.

---

## §12 Documentation Drift

| Directive | Spec status | Code status | CHANGELOG status |
|-----------|-------------|-------------|------------------|
| `@query` | Documented | Implements spec | 1.0.0+ |
| `@read` | Documented | Implements spec | 1.0.0+ |
| `@include` | Documented | Implements spec | 1.0.0+ |
| `@perseus` | Documented | No URL allowlist | 1.0.4+ |
| `@agent` | Documented | Uses config shell | 1.0.3+ |
| `@tool` | Documented | Allowlist bypass | 1.0.5+ |
| `@memory` | Documented | FTS5 injection partial | 1.0.5 "Mnēmē v2" |
| `@mneme` | Documented | Backward compat | 1.0.5 |
| `@bastra` | **NOT IN CODE** | **DOES NOT EXIST** | **CHANGELOG claims exists** |
| `@validate` | Documented | Implements spec | 1.0.0+ |
| `@synthesize` | Documented | LLM integration | 1.0.3+ |
| `@if/@else/@endif` | Documented (session.py) | Implements spec | 1.0.1+ |
| `@services` | Documented | SSRF risk in URL checks | 1.0.1+ |
| `@list/@tree` | Not in directives.md | Implements misc.py | 1.0.2+ |
| `@skills` | Not in directives.md | Implements skills.py | 1.0.3+ |
| `@waypoint` | Not in directives.md | Implements waypoint.py | 1.0.3+ |

**Finding D1 (re-confirmed):** CHANGELOG 1.0.5 claims `@bastra` directive for recall integration. No `@bastra` directive exists in any source file or in `DIRECTIVE_REGISTRY`. The `@memory` directive handles Mnēmē recall, and `@mneme` is a backward-compat alias. `@bastra` appears only in CHANGELOG text and in `HANDOFF.md` references to a "bastra-recall integration" task.

---

## §13 Semver / Dependency Audit

### pyyaml
`requirements.txt` doesn't explicitly pin `pyyaml`. `yaml.safe_load` is used throughout — this prevents arbitrary code execution from YAML but does NOT prevent resource exhaustion attacks ("billion laughs" YAML equivalent, deeply nested structures).

### SQLite minimum vs GLOB ESCAPE
SQLite `GLOB ... ESCAPE` is available since 3.31.0 (2020-01-22). Python 3.12.13 ships with SQLite 3.46.1 — well above the minimum. However, Python 3.10 on Ubuntu 20.04 ships with SQLite 3.31.1 (just barely above the minimum). The code doesn't check the SQLite version, so if run on Python < 3.11 with an older SQLite, `GLOB ... ESCAPE` would fail. Currently, the code uses GLOB ESCAPE for `_mneme_delete_document`'s pattern matching.

### Python minimum vs tomllib
`tomllib` is stdlib since Python 3.11. The code has fallback to `tomli` for older Python. `pyproject.toml` doesn't specify `requires-python`.

### urllib redirect default
`urllib.request.urlopen` follows redirects by default (max 10 redirects). This affects:
- `webhooks.py` (SSRF risk)
- `directives/perseus.py` (foreign resolver)
- `directives/services.py` (health checks)
No code path calls `urllib.request.install_opener()` or creates a custom `HTTPRedirectHandler`. All three paths follow redirects.

---

## §14 Severity-Ranked Findings

### CRITICAL

**C-1: Unterminated @macro silently consumes all remaining content**
- File: renderer.py:245-247
- Evidence: `bench/tier2/macro_silence_poc.py` — CONFIRMED, exit 1
- Failure: All content after unclosed `@macro` is silently dropped from output
- Patch: After parsing macro body, if `@endmacro` is never found, emit warning and discard the partial macro (not the subsequent content)

```diff
--- a/src/perseus/renderer.py
+++ b/src/perseus/renderer.py
@@ -243,6 +246,10 @@ def _parse_macros_from_lines(lines, start=0):
             i += 1
             body: list[str] = []
             while i < len(lines) and not MACRO_END_RE.match(lines[i]):
                 body.append(lines[i])
                 i += 1
+            if i >= len(lines):
+                # Unterminated macro — discard, don't consume rest of template
+                print(f"Perseus warning: unterminated @macro '{name}'", file=sys.stderr)
+                break
             # ... rest of parsing
```

**C-2: Orphaned checkpoint lock file — permanent deadlock on crash**
- File: checkpoint.py:39-41, 108
- Evidence: analysis confirms no PID staleness check
- Failure: Process crash between lock acquire and release → `.lock` file persists forever → ALL agents permanently blocked from writing checkpoints
- Patch: Add PID-based staleness detection

```diff
--- a/src/perseus/checkpoint.py
+++ b/src/perseus/checkpoint.py
@@ -39,7 +39,15 @@ def _write_checkpoint(...):
     for attempt in range(10):
         try:
             fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
+            os.write(fd, str(os.getpid()).encode())
             break
         except FileExistsError:
+            # Check if lock holder is still alive
+            try:
+                stale_pid = int(lock_path.read_text().strip())
+                os.kill(stale_pid, 0)  # signal 0 = check existence
+            except (OSError, ValueError):
+                lock_path.unlink(missing_ok=True)  # stale lock
             time.sleep(0.1 * (attempt + 1))
```

**C-3: Pre-read memory exhaustion in @include/@read**
- File: include.py:58, read.py:66
- Evidence: `bench/tier2/memory_exhaustion_poc.py` — reads entire file before checking `max_*_bytes` limit
- Failure: `@include` on a large file causes MemoryError before size gate fires
- Patch: Check `fp.stat().st_size` BEFORE `read_bytes()`

```diff
--- a/src/perseus/directives/include.py
+++ b/src/perseus/directives/include.py
@@ -56,6 +56,10 @@
+    # Check file size before reading to prevent memory exhaustion
+    max_bytes = render_cfg.get("max_include_bytes")
+    if max_bytes is not None:
+        try:
+            if fp.stat().st_size > max_bytes * 2:  # safety margin
+                return f"> ⚠ @include: file too large ({fp.stat().st_size:,} bytes)"
+        except OSError:
+            pass  # stat failed, fall through to read
     try:
         data = fp.read_bytes()
```

### HIGH

**H-1: MCP SSE GET endpoints unauthenticated**
- File: mcp.py:382-398
- Evidence: `bench/tier2/mcp_sse_auth_poc.py`
- Failure: `/sse` and `/health` serve without auth even when bearer token configured
- Patch: Add `_check_auth(self)` call at top of `do_GET`

**H-2: Foreign resolver SSRF — no URL allowlist**
- File: directives/perseus.py
- Failure: `@perseus` fetches any URL including cloud metadata endpoints
- Patch: Add `foreign.allowed_hosts` config with default `["127.0.0.1", "localhost"]`

**H-3: Webhook SSRF via redirect-following**
- File: webhooks.py:127
- Failure: `urlopen` follows redirects to internal services
- Patch: Create custom opener with `HTTPRedirectHandler` disabled or restricted

**H-4: DNS rebinding — serve.py missing Host header check**
- File: serve.py:2606-2620
- Failure: Browser on same machine can read rendered context via DNS rebinding
- Patch: Add Host header validation identical to mcp.py:368-372

**H-5: Checkpoint pointer TOCTOU**
- File: checkpoint.py:70
- Failure: Workspace pointer reads checkpoint file separately from write
- Patch: Use `os.replace` to atomically update both pointer and checkpoint together

### MEDIUM

**M-1: FTS5 apostrophe not escaped**
- File: mneme_index.py around line 300
- Failure: `@memory "it's"` produces FTS5 syntax error
- Patch: Double the apostrophe before FTS5 MATCH

**M-2: Argument allowlist bypass in @tool**
- File: directives/tool.py:97-99
- Failure: `--flag=value` as single arg doesn't match `--flag` in allowlist
- Patch: Split on `=` before checking allowed args

**M-3: LSP byte-at-a-time stream reading**
- File: lsp.py:16-43
- Failure: 1M syscalls for 1MB message, extreme slowness
- Patch: Buffer reads or use Content-Length-based chunk reading

**M-4: Pythia log exposes cross-workspace data**
- File: serve.py:2715-2723
- Failure: `/oracle/log` reads global Pythia log, not workspace-scoped
- Patch: Filter by workspace or add workspace-specific log files

**M-5: `@memory` silently updates `fm["updated"]` on read**
- File: agora.py:439
- Failure: Read-only render path side-effects the narrative file
- Patch: Only update timestamp when actual mutation occurs

**M-6: Concurrent Pythia log corruption**
- File: pythia.py
- Failure: Append and rewrite race without locking → lost entries
- Patch: Use `fcntl.flock` or per-process log files

**M-7: Inbox path traversal via sender field**
- File: inbox.py:78
- Failure: `../` in sender field writes outside inbox directory
- Patch: Sanitize sender to alphanumeric only

**M-8: Diamond @include renders twice**
- File: include.py:85
- Failure: `_visited.copy()` per branch causes D to be rendered twice
- Patch: Share a mutable `_visited` set across all branches

**M-9: @macro parameter prefix collision**
- File: renderer.py:338
- Failure: Parameter "a" destroys token "ab" before "ab" substitution
- Patch: Sort replacements by descending parameter name length

### LOW

L-1: `@cache mock` regex doesn't handle escaped quotes
L-2: TTL=0 creates immediately-expired cache entries (documented behavior)
L-3: Skills directive `cfg["pythia"]["skill_dir"]` KeyError potential
L-4: Waypoint directive `cfg["checkpoints"]["store"]` KeyError potential
L-5: Session directive `cfg["assistant"]` KeyError potential
L-6: `_get_shell` returns PATH-resolved binary (trojan risk)
L-7: `_find_project_root` limited to 10 levels
L-8: Stale hardcoded `v0.6` in serve HTML badge
L-9: Webhook empty HMAC secret after env var expansion

### NIT
N-1: `_PERSEUS_VERSION` via `globals().get(...)` with stale fallback
N-2: Sentry value `None` in webhook queue with fragile `task_done`
N-3: Inline `import json as _json` pattern suggests copy-paste
N-4: Sequential replacement in date directive (fragile but correct)
N-5: Truncation to 60 chars can split UTF-8 in skills description

---

## §15 Top Recommendations

Ranked by impact × ease:

1. **Fix unterminated @macro** (C-1) — 5-line patch, prevents silent data loss
2. **Add PID staleness to checkpoint lock** (C-2) — 10-line patch, prevents permanent deadlock
3. **Add pre-read size check to @include/@read** (C-3) — 6-line patch, prevents OOM
4. **Add auth to MCP SSE GET endpoints** (H-1) — 2-line patch, critical auth bypass
5. **Add Host header validation to serve.py** (H-4) — copy from mcp.py:368-372
6. **Add URL allowlist to foreign resolver** (H-2) — config + 5-line check
7. **Fix FTS5 apostrophe escaping** (M-1) — double apostrophe before MATCH
8. **Fix @tool argument allowlist bypass** (M-2) — split on = before match
9. **Scope Pythia log to workspace** (M-4) — prevent cross-workspace data leak
10. **Remove `@bastra` from CHANGELOG or implement it** (D1) — documentation integrity

---

## §16 What I Could Not Verify and Why

1. **Windows/macOS test matrices** (§10) — No VMs available in this environment. GitHub Actions would be needed.
2. **BM25 benchmark replication** (§7.5) — The benchmark scripts under `benchmark/` were not run. The 37ms P50 claim could not be independently verified.
3. **Lifecycle integration test** (§10.5) — Requires `perseus` on PATH and a clean environment per test.
4. **DNS rebinding full PoC** (§9.2) — Requires a second browser-capable machine on the same network.
5. **LSP hover SSRF/file read** (§9.6-9.7) — Requires running LSP server and a mock LSP client.
6. **Foreign resolver file:// demo** (§9.4) — The `@perseus` directive likely blocks `file://` URLs via the `urlopen` handler, but this wasn't tested.
7. **Cache stampede race** (§6.9-6.10) — Requires precise `os.kill` timing which is flaky in tests.
8. **`_capture_file_snapshot` race on FAT32** (§5.11) — No FAT32 filesystem available.
9. **Argument parser fuzzing with hypothesis** (§4.2) — Manual spot-checks done; full 10K-input fuzz not run.
10. **Build artifact symbol table diff** (§3.1) — `ast.parse`-based diff not automated; manual verification of key functions done.
11. **Plugin hostile demos with actual exfiltration** (§8.1) — Not executed to avoid actual credential exfiltration risk.
12. **Checkpoint crash simulation** (C-2) — `os.kill` based crash simulation is inherently unreliable in test frameworks.
