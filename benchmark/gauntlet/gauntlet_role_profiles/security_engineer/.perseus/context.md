@perseus v0.8
@prompt
You are the security engineer profile in the Perseus gauntlet.
@end

## Baseline
@query "git log --oneline -5" @cache ttl=300

## Services
@services
  - name: svc-4560
    url: http://127.0.0.1:4560/health
  - name: svc-4561
    url: http://127.0.0.1:4561/health
  - name: svc-4562
    url: http://127.0.0.1:4562/health
  - name: svc-4563
    url: http://127.0.0.1:4563/health
  - name: svc-4564
    url: http://127.0.0.1:4564/health
@end

## Role Signals
@read README.md
@read package.json
@read pyproject.toml
@skills flag_stale=true
@waypoint ttl=86400
@agora status=open,in_progress
@inbox
@memory focus="recent"

## Load
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 3" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 10" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 17" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 24" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 31" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 38" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 45" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 52" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 59" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 66" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
