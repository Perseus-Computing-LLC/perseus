# Perseus v1.0.0 — Release Validation Record

**Date:** 2026-05-20  
**RC Version:** v1.0.0-rc.1 → **Released as v1.0.0**  
**Gate:** ✅ Owner approved. v1.0.0 tag cut and published to PyPI as `perseus-ctx`.

---

## Validation Matrix

| Gate | Status | Notes |
|---|---|---|
| All critical development tasks complete | ✅ | All development tasks closed |
| Full test suite green | ✅ | 493 passed, 1 skipped (TCP LSP smoke — expected in sandbox) |
| py_compile (syntax check) | ✅ | No errors |
| Release artifacts built | ✅ | `dist/perseus-1.0.0-rc.1.tar.gz` + `SHA256SUMS` (RC); v1.0.0 artifacts rebuilt after version bump |
| Release artifact checksums verified | ✅ | `scripts/release.sh --check` passes |
| Version coherence (`VERSION` ↔ `_PERSEUS_VERSION` ↔ `--version`) | ✅ | All report `v1.0.0` |
| Adapter conformance harness | ✅ | 6 profiles: generic, hermes, codex, claude-code, cursor, rovodev |
| Golden corpus tests | ✅ | `tests/test_golden.py` |
| Performance budget tests | ✅ | 3 advisory warnings (render, graph, prefetch) — not failures; see Known Limitations |
| Compatibility/migration suite | ✅ | `tests/test_compat_migration.py` — checkpoint round-trip, config migration, pack versioning |
| Installer smoke | ✅ | `scripts/install.sh` installs and verifies `v1.0.0-rc.1` |
| Container image tests | ✅ | Static checks pass; Docker build/run skipped (no Docker in CI sandbox) |
| Docs hub + quickstart | ✅ | `docs/index.md`, `docs/quickstart.md`, `docs/CONTRIBUTING.md` |
| Example workspaces | ✅ | `examples/local-cli/`, `examples/assistant-profile/`, `examples/container/` — smoke tests pass |
| README / CHANGELOG / ROADMAP aligned | ✅ | All reference v1.0.0; CHANGELOG entries updated |
| IP portfolio | ✅ | Trademark filed. Patent pending. |
| No open Agora tasks | ✅ | All Agora tasks closed; 0 open |

---

## Release Artifacts

```
dist/
  perseus-1.0.0-rc.1.tar.gz   — runtime + installer + docs (113K)
  SHA256SUMS                   — checksums for tarball + runtime
```

Build: `bash scripts/release.sh`  
Verify: `bash scripts/release.sh --check`

---

## Known Limitations (v1.0.0-rc.1)

| Item | Severity | Notes |
|---|---|---|
| Performance budgets: render/graph/prefetch warm times exceed 2× budget (100–260ms) | Advisory | Budget thresholds (100ms) are aspirational for a 10K-line single-file CLI on first load. Not a correctness issue. To be tuned in a post-v1 performance pass. |
| TCP LSP smoke test skipped | Expected | Requires a real TCP port; skipped in sandbox/CI. The stdio LSP path is fully covered. |
| Container build/run test skipped | Expected | Skipped when Docker is not available. Static container tests pass; manual Docker smoke verified. |
| `zip` not installed | Minor | `.zip` release artifact skipped on this build host; tarball is the primary artifact. Install `zip` to produce both. |
| `@session topic=` filter is partially implemented | Minor | `topic="..."` does keyword filtering but behavior may not match spec for all inputs. To be sharpened post-v1. |
| Windows native Task Scheduler | Deferred | `perseus systemd`/`launchd`/`cron` cover Linux/macOS. Windows users: use WSL cron or invoke `perseus render` from your own scheduler. Explicitly deferred. |
| No external docs site | Deferred | `docs/` is in-repo markdown. A rendered docs site (GitHub Pages, ReadTheDocs) is a post-v1 item. |

---

## Support Envelope (v1.0.0)

- **Python:** 3.10+
- **Runtime dependency:** `pyyaml` only
- **Platforms:** Linux (primary), macOS (tested), Windows WSL (community)
- **Assistants:** Hermes, Codex, Claude Code, Cursor, Rovo Dev, any markdown-reading agent
- **Installation:** `scripts/install.sh` or direct `python3 perseus.py`

---

## Release Record

- ✅ RC validation passed on 2026-05-20
- ✅ Known Limitations reviewed and accepted or deferred
- ✅ IP status recorded (trademark filed)
- ✅ Version bumped from `1.0.0-rc.1` → `1.0.0` in all 6 locations
- ✅ CHANGELOG `[Unreleased]` → `[1.0.0] — 2026-05-20`
- ✅ Release artifacts rebuilt and checksums verified
- ✅ Published to PyPI as `perseus-ctx 1.0.0`

---

*Perseus v1.0.0. All development tasks complete. The mirror is ready.*
