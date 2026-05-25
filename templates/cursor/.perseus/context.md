@perseus v0.5

@prompt
You are Cursor. This document was rendered live by Perseus and is loaded
as `.cursorrules` at session start. All values below are current — do not
re-verify, just start work.
@end

# Cursor Session Context — @date format="YYYY-MM-DD HH:mm"

**Workspace:** {workspace}  
**Consumer:** Cursor reads `.cursorrules` at session start

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

---

## Output

Rendered to `.cursorrules` via cron (see `perseus cron --help`).
