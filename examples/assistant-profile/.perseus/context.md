@perseus v0.5

@prompt
This is the Perseus assistant-profile demo workspace. It uses the Hermes
profile — swap `profile: hermes` in `pack.yaml` to target Codex, Claude Code,
Cursor, or any other assistant. All values below are rendered live.
@end

# Assistant Profile Demo — @date format="YYYY-MM-DD HH:mm z"

**Workspace:** @env "PWD"  
**Profile:** hermes → `.hermes.md`

---

## Last Session
@waypoint ttl=86400

---

## Workspace State

```
@query "git log --oneline -5" @cache session
```

```
@query "git status --short"
```

---

## Environment

| Key | Value |
|---|---|
| Python | @query "python3 --version" @cache session |
| Perseus | @query "perseus --version" @cache session |
| Node | @query "node --version 2>/dev/null || echo n/a" @cache session |

---

## Services
@services

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

## Notes

- Output path is controlled by `profile:` in `pack.yaml` — change it to `claude-code`, `cursor`, `codex`, or `generic` to retarget
- `@memory` distils accumulated checkpoints into a narrative — run `perseus checkpoint` to build it up over time
- `@agora` reads live task state from the Agora task board
- `@services` pings running services and reports their status
- Refresh this file automatically: `perseus cron --help`
