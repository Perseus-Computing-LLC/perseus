@perseus v0.5

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.
@end

# Session Context — @date format="YYYY-MM-DD HH:mm"

**Workspace:** {workspace}

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

@query "git log --oneline -5"
@query "git status --short"

---

## Available Skills
@skills flag_stale=true

---

## Active Tasks
@agora status=open
@agora status=in_progress

---

## Maintenance Snapshot
@health

---

## Project Narrative
@memory focus="recent"

---

## Inbox
@inbox unread=true
