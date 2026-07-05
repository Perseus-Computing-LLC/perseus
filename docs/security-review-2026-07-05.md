# Perseus (context engine) — Security Review — 2026-07-05

Independent pre-launch audit of the `src/perseus/` product code (v1.0.17), ahead of
the integrated Perseus + Perseus Vault launch. Ten parallel review passes (five per
product) fed findings that were then **re-traced to source and re-verified by hand** —
several agent-reported "criticals" did not survive that verification and are recorded
below as *not-a-finding* so the ranking reflects only what was confirmed.

Threat model: MIT/public OSS; runs locally and on a server (greg); consumed by the
Hermes agent. Untrusted inputs are **hostile template/memory content**, **fetched web
content**, and **workspace-supplied config**. The MCP caller itself is trusted (local
stdio). Primary risks: local RCE via the shell-directive gates, path/symlink escape,
SSRF + prompt-injection from fetched content, and deploy/supply-chain posture.

## TL;DR
The headline control — the `@query`/`@agent`/`@if query()` **double-gate**
(`render.allow_query_shell` *and* `PERSEUS_ALLOW_DANGEROUS=1`, both default-off) — is
**correctly enforced with safe defaults at every shell site**, including via aliases,
pipe stages, and with LSP hover blocked. Path containment (`_resolve_path`:
canonicalize-then-`relative_to`) is sound, and the prior review's C-3/M-7/S5/N1/N2
findings are **confirmed fixed**. The real residual risk is (1) a cluster of
**egress paths that skip the SSRF/redirect guards** the rest of the code already
applies, and (2) **deploy/supply-chain posture** — the published Docker image ships
with the dangerous-mode gate pre-flipped, and the curl|bash installer points at a
personal-fork namespace. No unconditional RCE bypass was found.

## Findings (verified, ranked)

| # | Sev | Area | What | File |
|---|-----|------|------|------|
| 1 | MED | Supply chain | Docker image bakes `ENV PERSEUS_ALLOW_DANGEROUS=1` — pre-flips one of the two shell-RCE gate layers for every container | `Dockerfile:13` |
| 2 | MED | Supply chain | `bootstrap.sh` curl\|bash one-liner + all doc links point at the **personal fork** `tcconnally/perseus`, not `Perseus-Computing-LLC/perseus`; `pip install` unpinned | `scripts/bootstrap.sh:7,42,153,157,236,351` |
| 3 | MED | SSRF | Federation fetch/push: no scheme allow-list, **no private-IP block, follows redirects** — the `_is_private_host` + `_NoRedirect` guards used by `@perseus`/`@services`/webhooks are absent here | `mneme_federation.py:245,356` |
| 4 | MED | Injection | `@tool` `--flag=value` allow-list bypass: a bare-flag allow-list entry admits an arbitrary attached value (argv only, no shell — escalates only if an interpreter is allow-listed) | `directives/tool.py:97-101` |
| 5 | MED | Path/symlink | `@tree` follows symlinked directories out of the workspace (child paths not re-validated) → out-of-tree **filename disclosure**. `@list` is safe (`os.walk` no-followlinks) | `directives/misc.py:248` |
| 6 | MED | Supply chain | Self-update verifies GPG **fail-open**: `PERSEUS_GPG_FINGERPRINT=None` → `_gpg_verify_signature` returns "pass"; gpg-missing/unsigned/timeout also pass. `update --apply` runs whatever `origin/main` holds | `src/perseus/update.py:7-9,28-31,146-165` |
| 7 | MED | Prompt injection | `@perseus` remote-resolved content is injected into the rendered context **unlabeled** (no untrusted-content fence). Gated behind a configured trusted peer (HMAC + shared_secret required by default), so requires a compromised/hostile peer | `directives/perseus.py:192`; `serve.py:2039` |
| 8 | LOW-MED | Deploy | `serve.py` runs as root in Docker; container hardening (non-root `USER`, base-image digest pin) missing | `Dockerfile` |
| 9 | LOW-MED | Connector | Vault-connector binary resolution appends **CWD-relative** `./perseus-vault/target/release/…` candidates → untrusted-search-path exec if Perseus is run from an attacker-influenced CWD | `doctor.py:536-546` |
| 10 | LOW | Cross-workspace | `/oracle/log` returns **all** workspaces' Pythia prompts by default; the `?workspace=` filter is a **substring match on task text**, not a workspace field (auth-gated on remote binds; loopback+redacted otherwise) | `serve.py:2065-2077` |
| 11 | LOW | Webhooks | Empty/typo'd HMAC secret → webhook delivered **unsigned** with only a conditional warning; no minimum-length floor (unlike `@perseus`'s 32-char floor) | `webhooks.py:148-152,203` |
| 12 | LOW | SSRF | Webhook target has no private-IP block (redirects *are* blocked, TLS on) — operator-config trust, but env-expanded URL widens it | `webhooks.py:82-104,215` |
| 13 | LOW | DoS | `run_llm`/`run_ollama`/doctor do `resp.read()` with **no size cap** — a malicious/compromised LLM endpoint OOMs the process (operator-configured URL) | `pythia.py:220,589; doctor.py:411` |
| 14 | LOW | DNS-rebinding | `serve.py` `_serve_host_header_ok` returns **True on a missing Host header** (the `mcp.py` equivalent was fixed to return False); only matters on an opted-in no-auth bind | `serve.py:1811-1812` |
| 15 | LOW | Supply chain | Installed runtime dep `pyyaml>=6.0.1` is an unbounded floor with no hashes/lockfile for the wheel (dev freeze IS pinned) | `pyproject.toml:30` |
| 16 | LOW | Deploy | No-auth remote serve (`--i-understand-no-auth`) and `redaction.enabled` are independent toggles → an operator can expose unredacted `/context` remotely | `serve.py:2143` |

Root-cause groupings: **#3/#11/#12/#13** are one cause — egress paths that don't reuse
the project's own `_is_private_host` / `_NoRedirect` / bounded-read helpers. **#1/#2/#8/#15**
are deploy/supply-chain posture. **#4/#5** are untrusted-argument confinement.

## Confirmed sound (re-verified — no action)
- **`@query`/`@agent`/`@if query()` double-gate** — both `render.allow_*_shell` (default
  False) **and** `PERSEUS_ALLOW_DANGEROUS` required at all three sites; safe via aliases,
  pipe stages; LSP hover blocked (`safe_for_hover=False`). Prior gap #616 fixed.
- **Path containment `_resolve_path`** — NUL-reject → `resolve(strict=False)` (collapses
  `..` + canonicalizes symlinks) → `relative_to(ws)`; default `allow_outside_workspace=False`.
  Prior "`../` blocked" holds; symlink escape blocked. (Note the `@tree` gap #5 is the
  one place child paths aren't re-validated.)
- **Pre-read size guard** (`stat` before `read_bytes`, 50 MB default) present in `@read`/
  `@include` — prior C-3 fixed. **Inbox sender sanitize** (M-7) fixed. **`_safe_cache_dir`**
  (S5) fixed. **MCP SSE**: GET endpoints authenticated, empty-Host rejected, bind
  127.0.0.1, startup refuses no-auth — prior N1/N2 fixed. **Constant-time** token compares.
- **Build integrity** — `build.py --check` byte-compares the committed `perseus.py`
  against a fresh render (pre-commit hook + PyPI publish gate); version-string injection
  mitigated (semver `fullmatch`); stripped-import AST check. Verified in-sync.
- **PyPI publish** — OIDC trusted publishing, no stored token, tag==VERSION + `--check` gate.
- **Secrets** — no full-config-dump-to-disk path; env secrets not round-tripped;
  `config.yaml`/`.env` git-ignored; `yaml.safe_load` throughout (no `yaml.load`/`eval`/
  `os.system`/`pickle` anywhere in `src/perseus/`). **Pythia log redacted before write**
  (residual only if `redaction.enabled:false`).

## Not-a-finding (agent-reported, refuted on verification)
- **"@perseus HMAC is unusable → forces `verify_signatures=false`"** — FALSE. `serve.py`
  `_respond` signs **all** JSON responses (incl `/api/context`) with `X-Perseus-Signature`
  when `foreign.shared_secret` is set (`serve.py:2166-2170`). With `verify_signatures=True`
  (default) and empty secret, `@perseus` fails **closed** (no fetch). The agent grepped
  the wrong scope. (Downgraded #7 to MED accordingly.)

## Recommended fix order
- **Now (code, low-risk):** #3 (federation SSRF — reuse existing guards), #4 (@tool `=`
  bypass), #5 (@tree symlink guard), #11 (webhook empty-secret fail-closed), #13 (bounded
  read), #14 (missing-Host reject).
- **Now (deploy/supply, no runtime code):** #1 (drop the Dockerfile env), #2 (repoint +
  pin installer), #8 (non-root `USER` + digest), #15 (cap `pyyaml<7`).
- **Soon (behavioral, needs care):** #6 (self-update fail-closed when auto/fingerprint set),
  #7 (fence remote content), #10 (workspace-scope `/oracle/log`), #9 (drop CWD candidate),
  #16 (couple redaction with no-auth remote).
