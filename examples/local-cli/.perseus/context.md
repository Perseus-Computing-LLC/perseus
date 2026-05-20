@perseus v0.5

@prompt
This is the Perseus local-cli demo workspace. All values below are resolved
live — trust them and start work immediately.
@end

# Local CLI Demo — @date format="YYYY-MM-DD HH:mm z"

**Workspace:** @env "PWD"  
**User:** @env "USER"

---

## Last Session
@waypoint ttl=86400

---

## Environment

| Variable | Value |
|---|---|
| Python | @query "python3 --version" @cache session |
| Perseus | @query "perseus --version" @cache session |
| Shell | @env "SHELL" |
| OS | @query "uname -sr" @cache session |

---

## Workspace State

```
@query "git log --oneline -5" @cache session
```

```
@query "git status --short"
```

---

## Active Files

@read ".perseus/context.md" lines=1:10

---

## Health

@health

---

## Notes

- `@query` directives run real shell commands — edit them to match your project
- `@waypoint` restores the last checkpoint written by `perseus checkpoint`
- `@health` flags stale checkpoints, oversized narratives, and config drift
- `@cache session` means the result is reused within this render pass — safe for version strings and slow commands
- Remove `@cache session` from `git status` to always get a fresh read
