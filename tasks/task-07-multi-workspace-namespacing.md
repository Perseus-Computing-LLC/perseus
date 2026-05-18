---
id: task-07
title: "Task 07 — Multi-Workspace Checkpoint Namespacing"
status: open
scope: small-medium
depends_on:
  - task-03
claimed_by: null
opened: 2026-05-18
closed: null
---

# Task 07 — Multi-Workspace Checkpoint Namespacing

**Status: Open**  
**Scope: Small-Medium** — targeted hardening of existing checkpoint infrastructure  
**Depends-on: task-03** (checkpoint diffing must be complete; this extends the same store)

---

## The Problem

The checkpoint store currently maintains a single `latest.yaml` pointer (symlink when possible,
plain file fallback). This is fine for single-workspace users. It breaks silently when two or
more workspaces are active simultaneously: whichever workspace ran `perseus checkpoint` last
wins the `latest.yaml` pointer, and `perseus recover` returns the wrong checkpoint for the
other workspace.

`perseus recover --workspace <path>` already filters by workspace path in the checkpoint's
`workspace:` field — but it still resolves the wrong file first, then filters. And `perseus
diff --workspace` has the same exposure: it scans all checkpoints and filters, rather than
going straight to a workspace-scoped index.

This is explicitly marked in the roadmap as the remaining P5A item with no task file. This is
that task.

---

## What Needs to Change

### 1. Per-workspace latest pointer

On every `perseus checkpoint` write, maintain a workspace-scoped pointer in addition to
the global one:

```
~/.perseus/checkpoints/
  latest.yaml                    ← global (unchanged; stays for compatibility)
  latest-<workspace-hash>.yaml   ← NEW: per-workspace pointer
  2026-05-18T0649.yaml
  2026-05-18T0812.yaml
```

The workspace hash is a short deterministic slug derived from the workspace path —
something like `sha256(workspace_path)[:8]` or a sanitized path fragment. It must be
stable across sessions for the same path.

Implementation note: the pointer file (like `latest.yaml`) is a copy of the checkpoint
YAML, not a symlink — symlinks fail on some filesystems. The existing fallback pattern
already handles this; extend it.

### 2. `perseus recover` uses the workspace pointer

When `--workspace` is provided, load `latest-<hash>.yaml` directly instead of scanning
and filtering all checkpoints. Fall back to the scan-and-filter approach if the pointer
doesn't exist (e.g. first session in a new workspace).

```bash
# Before: scans all, filters by workspace field
# After: jumps directly to latest-<hash>.yaml for this workspace
perseus recover --workspace /workspace/perseus
```

### 3. `perseus diff` uses the workspace pointer

When `--workspace` is provided without explicit `--a`/`--b`, use the per-workspace index
to locate the two most recent checkpoints for that workspace, rather than scanning all
checkpoints and filtering. This makes workspace-scoped diff reliable when multiple
workspaces are interleaved in the store.

### 4. Pointer cleanup on `max_keep` prune

When the checkpoint store is pruned (enforcing `checkpoints.max_keep`), clean up any
per-workspace pointers that now point to deleted files. A stale pointer should be removed
or re-pointed to the surviving latest for that workspace.

---

## Interface

No new user-facing CLI changes. The behavior of `--workspace` becomes more reliable. The
internal pointer files are an implementation detail.

```bash
# These existing commands become workspace-reliable:
perseus recover --workspace /workspace/perseus
perseus diff --workspace /workspace/perseus
```

---

## Design Constraints

- Single-file rule in force
- No new dependencies
- Backward compatible: users without `--workspace` see no change
- Global `latest.yaml` pointer must continue to work as before
- Pointer files must be plain YAML copies, not symlinks

---

## Acceptance Criteria

- [ ] `perseus checkpoint` writes `latest-<hash>.yaml` alongside `latest.yaml`
- [ ] `perseus recover --workspace <path>` resolves the correct checkpoint when multiple
  workspaces are interleaved in the store
- [ ] `perseus diff --workspace <path>` diffs the correct pair for that workspace
- [ ] Pointer cleanup runs when `max_keep` prune deletes checkpoints
- [ ] Tests: multi-workspace interleave (two workspaces, alternating checkpoints — recover
  and diff return correct workspace results); pruning cleans stale pointers
- [ ] `spec/data-model.md` updated with the pointer filename convention

---

## Notes

- The workspace hash approach (rather than path sanitization) avoids problems with deep
  or OS-special characters in workspace paths.
- This is the last remaining item in Phase 5A. Once complete, Phase 5 is fully done.
