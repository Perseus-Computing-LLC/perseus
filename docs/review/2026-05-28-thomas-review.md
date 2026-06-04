# Perseus v1.0.5 Code Review — Findings & Action Plan

**Date**: 2026-05-28
**Reviewer**: Thomas Connally
**Reviewed**: `tcconnally/perseus@0bb24ad` (origin/main after force-push)
**Artifact**: Built perseus.py at 14,957 lines, 754 tests collected, 688 pass / 58 fail / 7 skip / 1 xfail on Windows

---

## Priority 1 — Structural Hazards

### 1.1 serve.py is 2,994 lines — monolithic gatekeeper
**Source**: `serve.py::cmd_render`, `cmd_serve`, `cmd_mcp`, `cmd_synthesize`, `cmd_doctor`, `cmd_init`
**Severity**: High
**Recommendation**: Extract HTTP serve → `serve_http.py`, MCP dispatch → `mcp_dispatch.py`, synthesis → move to `synthesize.py`, scheduler/install/update → `cron.py`, trust/doctor → `trust.py`.
**Risk**: v1.1 changes will keep crossing unrelated surfaces; security fixes stay hard to audit.
**Status**: TODO

### 1.2 Source modules are build fragments, not clean package modules
**Source**: `scripts/build.py::build`, `cli.py` module bootstrap, `registry.py::_bind_registry`
**Severity**: High
**Recommendation**: Either make `src/perseus` importable directly or document it as a fragment tree + add CI checks for import/order/registry invariants.
**Risk**: Traceback triage, plugin work, and source-level testing remain brittle.
**Status**: TODO

### 1.3 Build contract depends on exact module order
**Source**: `scripts/build.py::MODULE_ORDER`, `scripts/build.py::build`
**Severity**: Medium
**Recommendation**: Add generated source map or stable module markers; fail CI if earlier modules introduce `__main__` blocks or import-time side effects.
**Risk**: Contributors can add normal-looking Python that only breaks after concatenation.
**Status**: TODO

---

## Priority 2 — Security & Trust Model

### 2.1 @query runs shell outside workspace boundary
**Source**: `directives/query.py::resolve_query`, `audit.py::_resolve_path`
**Severity**: High
**Recommendation**: Set `cwd=workspace` in `subprocess.run()`; document that `allow_outside_workspace` does not sandbox shell commands.
**Status**: 🔧 IN PROGRESS

### 2.2 @agent vs @query shell policy confusion
**Source**: `registry.py::_call_resolver`, `directives/agent.py::resolve_agent`
**Severity**: Medium
**Recommendation**: One shared shell execution policy helper; make `allow_agent_shell` either truly independent or explicitly subordinate to `allow_query_shell`.
**Status**: 🔧 IN PROGRESS

### 2.3 Redaction at rest — secrets persisted raw
**Source**: `pythia.py::append_pythia_log`, `pythia.py::build_pythia_log_entry`, `audit.py::audit_event`, `renderer.py::cache_set`
**Severity**: High
**Recommendation**: Apply `redact_value` before persistence in Pythia, audit, and cache stores.
**Risk**: Rendered output looks safe while `~/.perseus/` stores raw secrets.
**Status**: 🔧 IN PROGRESS

### 2.4 Plugin MANIFEST gate checks existence only — no hash/signature verification
**Source**: `registry.py::_discover_plugins`, `registry.py::_discover_formats`
**Severity**: High
**Recommendation**: Verify manifest hashes or rename to "manifest presence gate" + require `plugins.allow_unsigned` for all import-time code.
**Risk**: A dropped `.py` file + empty MANIFEST.toml executes code at render time.
**Status**: 🔧 IN PROGRESS

### 2.5 cmd_serve / cmd_mcp do not reload workspace-local config
**Source**: `cli.py::main`, `serve.py::cmd_serve`, `serve.py::cmd_mcp`, `audit.py::load_config`
**Severity**: High
**Recommendation**: Call `load_config(workspace)` inside `cmd_serve` and `cmd_mcp` before reading auth, bind, MCP, or render gates.
**Risk**: Operators believe workspace policy is active when the server uses only global/default config.
**Status**: 🔧 IN PROGRESS

---

## Priority 3 — Architecture & Extensibility

### 3.1 Pythia/Daedalus documented aspirationally but no local scoring model ships
**Source**: `pythia.py::cmd_suggest`, `pythia.py::run_llm`, `pythia.py::_pythia_online_score_adjustments`
**Severity**: Medium
**Recommendation**: Document Daedalus as "external model route + data pipeline" until a real scorer ships.
**Status**: TODO

### 3.2 Foreign resolver config surface is split and partly stale
**Source**: `config.py::DEFAULT_CONFIG`, `directives/perseus.py::resolve_perseus`
**Severity**: Medium
**Recommendation**: Collapse to one canonical `foreign` config block or add migration aliases with warnings.
**Risk**: Users set documented-looking keys that do nothing.
**Status**: TODO

### 3.3 MCP tool count in docs is wrong (24 advertised, 22 default)
**Source**: `mcp.py::_get_all_mcp_tools`, `mcp.py::_mcp_tool_allowed`, `README.md`
**Severity**: Low
**Recommendation**: Document "22 default, 24 with sensitive tools allowlisted."
**Status**: TODO

---

## Priority 4 — Correctness & Edge Cases

### 4.1 Windows support not release-green (58 failures)
**Source**: `directives/session.py::evaluate_condition`, `directives/tool.py::resolve_tool`, `audit.py::_extract_quoted_token`, `audit.py::_parse_kv_modifiers`
**Severity**: High
**Recommendation**: Add Windows CI as required for release; mark POSIX-only tests; fix product paths separately from fixture portability.
**Status**: TODO

### 4.2 Quoted modifier parsing corrupts Windows paths (backslash escapes decoded)
**Source**: `audit.py::_extract_quoted_token`, `audit.py::_parse_kv_modifiers`, `renderer.py @synthesize block handling`
**Severity**: High
**Recommendation**: Treat path-bearing modifiers as raw strings or only decode `\"`, `\'`, and `\\`.
**Risk**: Windows absolute paths fail or point somewhere unintended.
**Status**: 🔧 IN PROGRESS

### 4.3 Cache invalidation is TTL-only, no dependency fingerprinting
**Source**: `renderer.py::_cache_key`, `renderer.py::cache_get`, `renderer.py::cache_set`, `serve.py::_watch_loop`
**Severity**: Medium
**Recommendation**: Add file/env/dependency fingerprints as cache metadata; invalidate on watched dependency changes.
**Risk**: Perseus can feed stale resolved facts with no warning.
**Status**: TODO (v1.1)

### 4.4 @tool .sh scripts fail on Windows (WinError 193)
**Source**: `directives/tool.py::resolve_tool`
**Severity**: Medium
**Recommendation**: Document @tool as native executable only on Windows or add per-tool interpreter support.
**Status**: TODO

---

## Priority 5 — Missing / Drift

### 5.1 Version and test count drift in docs
**Source**: `docs/PERSEUS_PRODUCT_REPORT.md`, `README.md`, `CHANGELOG.md`, `VERSION`
**Severity**: Medium
**Recommendation**: Single-source version/test-count metadata or stop publishing exact test counts outside release artifacts.
**Status**: TODO

### 5.2 Security test gaps (MCP SSE auth, workspace-local config, plugin hash, persisted redaction)
**Source**: `tests/test_mcp.py`, `tests/test_serve.py`, `tests/test_plugin.py`, `tests/test_redaction.py`
**Severity**: Medium
**Recommendation**: Add tests as v1.1 release blockers.
**Status**: TODO (v1.1)

---

## Action Summary

| Priority | Fixes now | Count |
|----------|-----------|-------|
| P1 (Structural) | Plan, execute in v1.1 | 3 |
| P2 (Security) | **Fix now** | 5 |
| P3 (Architecture) | Docs + config cleanup | 3 |
| P4 (Correctness) | Path fix now, rest v1.1 | 4 |
| P5 (Drift/Test) | Docs fix now, tests v1.1 | 2 |

**Immediate (this session)**: P2-5 serve/MCP config, P2-1 @query cwd, P2-3 redaction at rest, P2-4 plugin manifest, P4-2 Windows path parsing, P2-2 shell policy, P5-1 docs drift.
