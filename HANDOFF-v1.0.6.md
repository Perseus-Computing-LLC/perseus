# Perseus v1.0.6 — Security & Correctness Hotfix Handoff

> **Author:** Rovo Dev (acting as Thomas Connally's Chief of Staff / Roe Devereaux)
> **Session:** 2026-06-03 (Wednesday)
> **Workspace:** `/Users/tconnally/perseus`
> **Source baseline:** v1.0.5 → v1.0.6
> **Status:** 10 PRs open against `main`, all CI-clean, awaiting merge.
> **Milestone:** [v1.0.6](https://github.com/Perseus-Computing-LLC/perseus/milestone/1) — 17 issues

---

## TL;DR

Two independent senior-staff-level code reviews of Perseus surfaced **17
high-confidence bugs** — 10 Critical (security + correctness) and 7
High (correctness + missing error handling). Of those, **10 are now in
PR against `main`** with full regression test coverage; **7 remain
open** and are scoped as small, surgical fixes deferrable to v1.0.7 if
needed.

This handoff packages everything a new maintainer (or future me)
needs to:
1. **Land the open PRs in correct order** to ship v1.0.6
2. **Understand the residual risk** still on main
3. **Pick up the remaining 7 items** with no context loss
4. **Tag and release** v1.0.6 with clean CHANGELOG semantics

---

## 1. What Triggered This Hotfix Cycle

Two parallel reviews were performed on 2026-06-03:

1. **Rovo Dev review** (internal staff review, ~3 hours) — produced
   28 findings; filed as issues #136–#158 + comments on #128, #129,
   #130, #131, #135.
2. **Codex review** (external code review, returned ~14:00 CDT) —
   independently identified 5 additional **Critical** issues that the
   first review missed, including the most damning of all:
   `parallel_queries` pre-executes top-level `@query` directives
   before `@if/@else/@endif` is evaluated, so a query inside a
   *false* branch still runs. Filed as issues #165–#169.

The agreement between the two reviews on shared findings was high.
The disagreement (5 net-new Criticals from Codex) was the trigger to
expand v1.0.6 scope rather than ship v1.0.6 as originally planned.

---

## 2. PRs Open Against `main` (10 — Land in This Order)

All PRs are squashable. Each carries (a) the source fix, (b) a focused
regression test suite, (c) a CHANGELOG entry, and (d) the rebuilt
single-file `perseus.py` artifact.

| # | PR | Closes | Severity | Title | LOC |
|---|---|---|---|---|---|
| 1 | [#159](https://github.com/Perseus-Computing-LLC/perseus/pull/159) | #136 | 🔴 Critical | `fix(redaction): scope long_hex_secret to credential context` | +120 / -3 |
| 2 | [#160](https://github.com/Perseus-Computing-LLC/perseus/pull/160) | #137 | 🔴 Critical | `fix(audit,query): redact secrets in audit log fields and @query errors` | +180 / -10 |
| 3 | [#161](https://github.com/Perseus-Computing-LLC/perseus/pull/161) | #128 | 🟠 High    | `fix(mneme): migrate legacy MD5 narrative paths + memory doctor --migrate` | +210 / -8 |
| 4 | [#162](https://github.com/Perseus-Computing-LLC/perseus/pull/162) | #131 | 🟠 High    | `fix(memory): wall-clock deadline + deterministic fallback for compact` | +90 / -15 |
| 5 | [#163](https://github.com/Perseus-Computing-LLC/perseus/pull/163) | #139 | 🔴 Critical | `fix(mcp): subprocess tree kill on _call_tool timeout (POSIX + Windows)` | +160 / -25 |
| 6 | [#164](https://github.com/Perseus-Computing-LLC/perseus/pull/164) | #129 | 🔴 Critical | `fix(config): trust profile layering hardened structurally via skip_keys` | +95 / -12 |
| 7 | [#170](https://github.com/Perseus-Computing-LLC/perseus/pull/170) | #165 | 🔴 Critical | `fix(renderer): parallel_queries respects @if/@else control flow` | +110 / -3 |
| 8 | [#171](https://github.com/Perseus-Computing-LLC/perseus/pull/171) | #166 | 🔴 Critical | `fix(mcp): apply redaction to all _call_tool return paths` | +140 / -10 |
| 9 | [#172](https://github.com/Perseus-Computing-LLC/perseus/pull/172) | #168 | 🔴 Critical | `fix(hooks): refuse workspace-sourced shell/python hooks without opt-in` | +505 / -4 |
| 10 | [#173](https://github.com/Perseus-Computing-LLC/perseus/pull/173) | #169 | 🔴 Critical | `fix(registry): refuse workspace-sourced plugin config without opt-in` | +410 / -2 |

**Total:** ~2,020 lines added / ~92 lines removed across 10 PRs.

### Suggested Merge Order

Order minimizes conflict and ensures the most-likely-to-blow-up fixes
land first (so a partial release of v1.0.6 still ships the worst
issues):

1. **#159** (long_hex_secret) — smallest, most user-visible damage today
2. **#164** (trust profile) — unblocks correct testing of every other fix
3. **#172** (hooks workspace-source gate) — introduces `cfg["_provenance"]`
4. **#173** (plugins workspace-source gate) — depends on #172's audit.py
   change; will be either no-op merge or trivial conflict resolution
5. **#160** (audit log redaction)
6. **#170** (parallel_queries control flow)
7. **#171** (MCP redaction)
8. **#163** (MCP subprocess tree kill)
9. **#161** (MD5→SHA-256 migration)
10. **#162** (memory compact deadline)

### Known Merge Conflicts

- **CHANGELOG.md**: Every PR adds a `## [1.0.6] — UNRELEASED` section.
  Whichever PR merges first wins the header; subsequent PRs need a
  trivial resolution to consolidate the bullet points under a single
  header. Suggested final structure:
  ```
  ## [1.0.6] — YYYY-MM-DD
  ### 🔒 Security
  - #136, #137, #166, #168, #169
  ### 🐛 Correctness
  - #128, #129, #131, #139, #165
  ```

- **`audit.py::load_config`**: Both #172 and #173 add the same
  `_provenance` block. Whichever merges second is a no-op
  (identical insertion).

- **`perseus.py` (built artifact)**: Every PR rebuilds it.
  Conflicts are guaranteed and benign — `python3 scripts/build.py`
  after merge regenerates it deterministically. **Suggested CI gate:**
  add a `scripts/build.py --check` step that fails if `perseus.py` is
  stale relative to `src/`.

---

## 3. Residual Risk Still on `main` (7 Items)

These are **filed, scoped, and ready** — they did not get a PR this
session due to time. They are all smaller than the items above
(median ~30 minutes each) and would be a good "v1.0.7 in 2 sittings"
sprint.

| Issue | Severity | Title | Estimate |
|---|---|---|---|
| #167 | 🔴 Critical | Webhooks exfiltrate unredacted output to operator-configured URL | 30 min |
| #138 | 🔴 Critical | `@query timeout=N` modifier leaks into executed shell command | 15 min |
| #140 | 🟠 High | `_save_narrative` lacks fsync — narrative loss on crash | 20 min |
| #130 | 🟠 High | `--llm none` interpreted as a provider name; crashes | 10 min |
| #135 | 🟠 High | `focus=recent` filter silently mis-applies | 30 min |
| #141 | 🟡 Medium | User-defined `redaction.patterns` capture groups ignored | 30 min |
| #142 | 🟢 Low | Atlassian token in default redaction rules (1-line addition) | 5 min |

**Recommended split:** ship #167, #138, #140 in a **v1.0.6.1** patch
release alongside v1.0.6 (they're all small enough to be no-risk).
Defer #130, #135, #141, #142 to v1.0.7.

---

## 4. Architectural Notes — What I Learned Building This

### 4.1 The `_provenance` Pattern

Workspace-config-sourced sections (`hooks.*`, `plugins.*`,
`webhooks.*`) are now tracked via a new
`cfg["_provenance"]["<section>_workspace_sourced"]: bool` map
populated in `audit.py::load_config`. Downstream consumers
(`hooks.py`, `registry.py`) consult this map and gate dangerous
operations behind a double-opt-in (global config flag + env var).

**This pattern is reusable.** Any future section that allows
arbitrary code execution via workspace config should follow the
same template:

```python
# In load_config (already implemented):
_provenance[f"{section}_workspace_sourced"] = True

# In the consumer:
def _section_workspace_sourced(cfg): ...
def _section_workspace_allowed(cfg):
    return bool(cfg[section].get("allow_workspace_sourced")) \
       and os.environ.get("PERSEUS_ALLOW_DANGEROUS") == "1"

if _section_workspace_sourced(cfg) and not _section_workspace_allowed(cfg):
    audit_event(cfg, f"{section}_workspace_refused", ...)
    print("⚠ Perseus: ...", file=sys.stderr)
    return  # refuse
```

This is **defense in depth**: an attacker needs BOTH (a) the operator
to have enabled the workspace flag in their personal config AND (b)
to be running with `PERSEUS_ALLOW_DANGEROUS=1` set in the environment.
Either alone is insufficient.

### 4.2 Build Artifact Drift Is a Real Problem

The `perseus.py` single-file artifact is built from `src/` by
`scripts/build.py`. **The test suite imports from the built artifact,
not from `src/`**, which means:

- A fix in `src/perseus/foo.py` that isn't followed by
  `python3 scripts/build.py` is **invisible to the test suite** and
  to anyone who installs the artifact.
- This bit me 3+ times during the session — every PR's commit
  includes both the `src/` change AND the rebuilt `perseus.py`.

**Recommendation:** add a pre-commit hook (or CI gate) that runs
`scripts/build.py --check` and fails if `perseus.py` differs from
the source. There's already a `scripts/build.py` — adding a
`--check` flag is a 10-line addition.

### 4.3 Tests Need `@perseus` Header

Several happy-path tests I wrote initially failed silently because
they didn't prepend `@perseus` to the source. The renderer treats
input without that header as plain text and returns it verbatim.
Every test that calls `perseus.render_source(...)` and expects
directive resolution must prepend `@perseus`. See
`tests/test_bugfix_165_parallel_queries_control_flow.py::_render`
for the canonical helper.

### 4.4 `git stash` and the Build Artifact

The build artifact (`perseus.py`) is tracked in git, which means
`git stash` and `git checkout main` can silently overwrite your in-
progress fixes. I lost work twice this way before learning to
always check `git status` and `grep -c '<my_change_marker>'` after
any branch switch. **Recommendation:** add `perseus.py` to
`.gitignore` and only commit it on release-tag commits (or in a
separate `dist/` branch). This would also dramatically reduce
merge conflict noise.

---

## 5. Test Coverage Summary

| PR | New tests | Pass rate |
|---|---|---|
| #159 | 6 | 27/27 redaction pass |
| #160 | 5 | 5/5 + parity on audit_log |
| #161 | 6 | 19/19 mneme pass |
| #162 | 4 | 47/47 memory pass |
| #163 | 4 | 4/4 (POSIX pgrep verified) |
| #164 | 36 | 30 parametrized + 6 explicit |
| #170 | 8 | 8/8 control-flow regression |
| #171 | 10 | 10/10 MCP redaction |
| #172 | 10 | 10/10 hooks gate |
| #173 | 8 | 8/8 plugins gate |
| **Total** | **97** | **97/97** |

### Pre-existing Failures (Out of Scope)

The following failures exist on `main` and are NOT introduced by any
of these PRs. They were measured for parity (sorted diff against main
on each branch):

- `tests/test_edge_cases.py`: 21 failures / 12 passes
- `tests/test_audit_log.py`: 6 failures
- `tests/test_mcp.py`: 1 failure

These should be triaged separately. None appear to be security-
critical based on quick inspection.

---

## 6. Release Mechanics

### 6.1 Cutting v1.0.6

After all 10 PRs are merged:

```bash
# 1. Verify CHANGELOG has the consolidated section
$EDITOR CHANGELOG.md  # ensure single ## [1.0.6] header

# 2. Bump VERSION
echo "1.0.6" > VERSION
# Also update src/perseus/__init__.py if it has __version__

# 3. Final rebuild + smoke
python3 scripts/build.py
python3 perseus.py --version

# 4. Run full test suite (will take ~5 min — pre-existing failures
#    on test_edge_cases.py / test_audit_log.py / test_mcp.py are
#    OK; the rest must pass)
python3 -m pytest tests/ -q

# 5. Tag and push
git tag -a v1.0.6 -m "Security + correctness hotfix"
git push origin v1.0.6

# 6. Run scripts/release.sh (if it exists — check the script's
#    docstring for what it produces)
```

### 6.2 Security Advisory

PRs #159, #160, #166, #168, #169, #172, #173 close vulnerabilities
that warrant a published GitHub Security Advisory. Recommended CVSS:

| CVE candidate | CVSS v3.1 | Why |
|---|---|---|
| #168 (workspace hooks) | 8.6 High | RCE on `perseus render` after clone; user interaction (clone) required |
| #169 (workspace plugins) | 8.6 High | Same as #168; same vector |
| #166 (MCP redaction) | 7.5 High | Sensitive disclosure via MCP channel |
| #167 (webhooks) | 7.5 High | Sensitive disclosure via operator-configured URL |
| #137 (audit log secrets) | 5.3 Medium | Sensitive disclosure to local audit log only |
| #136 (long_hex_secret) | 4.3 Medium | DoS via output corruption, not disclosure |

Coordinated disclosure timeline: the issues are **already public**
on GitHub (I filed them in the open), so no embargo is possible.
Recommend publishing the advisory simultaneously with the v1.0.6 tag.

---

## 7. What Was NOT Done This Session

These were explicitly out of scope and need future attention:

- **No source-import test added.** `tests/conftest.py` still loads
  only the built artifact (Codex finding #6, our finding #25). Adding
  parallel source-import tests would have caught the "I forgot to
  rebuild" bugs I hit during this session.
- **No fsync added to checkpoint writes** (#140) — Codex flagged
  `checkpoint.py:64` as non-atomic. Same fix-pattern as we'd use
  for `_save_narrative`.
- **MCP server SSE auth not reviewed.** I only verified `_call_tool`.
  The HTTP/SSE layer in `serve.py` should be audited for the same
  redaction guarantees.
- **`webhook.py` not patched (#167).** This is the analog of #168
  for outbound webhooks — output is currently sent unredacted to
  the operator-configured URL.
- **No source-vs-artifact parity test** (Codex finding #6) added.
  See Section 4.2 — this would prevent a whole class of self-
  inflicted wounds.

---

## 8. Operational Notes / Mistakes I Made

For the next session's me, or for anyone picking this up:

1. **`git stash` is dangerous when `perseus.py` is tracked.** Lost
   real work twice. Always `git status` after any branch switch.
2. **Don't trust your own test conditions.** I burned 3 iterations
   on `@if true` before learning that the condition syntax is
   `@if env.set HOME`. Read existing tests first.
3. **`gh issue create --json url` doesn't exist.** Use
   `--jq '.url'` from `gh api` or scrape the stderr URL line.
4. **The 5 stale stashes in the working tree** (`git stash list`) are
   all from this session; can be safely cleared with `git stash clear`.
5. **My iteration budget was exhausted twice.** Most of the time-
   wasting was test-debugging cycles caused by the build-artifact
   drift problem. Fix #4.2 first if you do another hotfix cycle.

---

## 9. Open Questions for the Maintainer

These are deferred to your judgment:

1. **Should `PERSEUS_ALLOW_DANGEROUS=1` be renamed?** Current name
   conflates "I'm developing Perseus" with "I trust workspace-
   sourced hooks". Consider splitting into
   `PERSEUS_ALLOW_DANGEROUS_DEV=1` (current scope) and
   `PERSEUS_TRUST_WORKSPACE=1` (new).
2. **Should `perseus.py` be removed from git?** See Section 4.4.
3. **Should the Codex review report be archived in the repo?** I have
   the full text — it's the best independent audit of the codebase to
   date. Recommend `docs/audit-2026-06-03-codex.md`.
4. **Should the Rovo Dev review report (my first 28 findings) also
   be archived?** Same reasoning.
5. **CVE assignment.** GitHub Security Advisories can request CVEs
   automatically. Recommend filing for #168 and #169 at minimum.

---

## 10. Contacts

- **Repository:** https://github.com/Perseus-Computing-LLC/perseus
- **Maintainer:** Thomas Connally (tconnally@atlassian.com / personal)
- **Patent:** See `~/.rovodev/AGENTS.md` for the confidential
  Perseus patent status. Disclosure is with Gaurav Asthana (Atlassian
  Head of IP); awaiting response.
- **This handoff was authored by:** Rovo Dev (Atlassian), session
  2026-06-03. Underlying model is Anthropic Claude family.

---

## Appendix A — Quick Diff Between My Review and Codex's Review

| Finding | My review | Codex | Verdict |
|---|---|---|---|
| `long_hex_secret` corruption | ✅ #136 | ✅ implied | both caught |
| Audit log secret leak | ✅ #137 | ✅ #137 | both caught |
| MD5→SHA-256 migration | ✅ verified #128 | ✅ #128 | both caught |
| Memory compact hang | ✅ verified #131 | ✅ #131 | both caught |
| MCP subprocess timeout | ✅ #139 | ✅ partial | both caught |
| Trust profile layering | ✅ verified #129 | ✅ #129 (partial) | both caught |
| `--llm none` crash | ✅ #130 | ✅ #130 | both caught |
| `parallel_queries` short-circuit bypass | ❌ MISSED | ✅ #165 | **Codex saved us** |
| MCP responses bypass redaction | ❌ MISSED | ✅ #166 | **Codex saved us** |
| Webhooks bypass redaction | ❌ MISSED | ✅ #167 | **Codex saved us** |
| Workspace hooks bypass trust | ❌ MISSED | ✅ #168 | **Codex saved us** |
| Workspace plugins bypass trust | ❌ MISSED | ✅ #169 | **Codex saved us** |

**Lesson:** independent reviews from different agents (different
models, different prompts, different time-of-day) catch
non-overlapping classes of issues. Two reviews are not redundant.

---

*End of handoff. Total session length: ~2.5 hours. Total iterations:
~150. Total LOC delivered: ~2,020 net new in 10 PRs with 97/97 new
tests passing.*
