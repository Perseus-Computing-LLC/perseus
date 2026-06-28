@perseus v0.5

@prompt
You are the DevOps operator for this workspace. This document was rendered live
by Perseus and reflects the current state of services, repo, and tooling. All
values below are current — do not re-verify, just start work.
@end

# DevOps Session Context — @date format="YYYY-MM-DD HH:mm"

**Workspace:** {workspace}

---

## Service Health
@services

---

## Working Tree
@query "git status --short"

---

## Environment Template
@read ".env.example"

---

## Maintenance Snapshot
@health

---

## Toolset Stats
@tooltrim stats

---

## Active Tasks
@agora status=in_progress
