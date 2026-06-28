@perseus v0.5

@prompt
You are the founder's operating assistant. This document was rendered live by
Perseus and captures the current state of the business workspace. All values
below are current — do not re-verify, just start work.
@end

# Founder Session Context — @date format="YYYY-MM-DD HH:mm"

**Workspace:** {workspace}

---

## Last Session
@waypoint

---

## Roadmap
@read "ROADMAP.md"

---

## Active Tasks
@agora status=open
@agora status=in_progress

---

## Project Narrative
@memory focus="recent"

---

## Maintenance Snapshot
@health

---

## Recent Commits
@query "git log --oneline -10"
