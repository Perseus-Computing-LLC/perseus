@perseus v0.4

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.
@end

# Claude Code Context — @date format="YYYY-MM-DD HH:mm z"

**Workspace:** @env PWD fallback="(unknown)"

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

```
@query "git log --oneline -5" @cache session
```

```
@query "git status --short" @cache session
```

---

## Environment

| Variable | Value |
|---|---|
| Python | @query "python3 --version 2>&1" @cache session |
| Perseus | @query "perseus --version 2>&1" @cache session |
| Node | @query "node --version 2>/dev/null || echo '(not installed)'" @cache session |
| Branch | @query "git branch --show-current 2>/dev/null || echo '(not a git repo)'" @cache session |

---

## Services
@services
  - name: Local dev server
    url: http://localhost:3000/health
  - name: API server
    url: http://localhost:8000/health
@end

---

## Recent Sessions
@session count=3

---

## Health
@health
