@perseus v0.3

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.
@end

# Perseus Session Context — @date format="YYYY-MM-DD HH:mm CDT"

**Workspace:** current repo checkout  
**Repo:** https://github.com/tcconnally/perseus  
**Project:** Perseus — Live Context Engine for AI Assistants (alpha v0.8)

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

@query "git log --oneline -5" fallback="git log unavailable"
@query "git status --short" fallback="git status unavailable"

---

## Available Skills
@skills flag_stale=true

---

## Services
@services
  - name: Hermes WebUI
    url: http://localhost:7779
  - name: ntfy
    url: http://localhost:8080/v1/health
  - name: Portainer
    url: https://localhost:9443/api/status

---

## Recent Sessions
@session count=5

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
