@perseus v0.8
@prompt
You are the mobile developer profile in the Perseus gauntlet.
@end

## Baseline
@query "git log --oneline -5" @cache ttl=300

## Services
@services
  - name: svc-4520
    url: http://127.0.0.1:4520/health
  - name: svc-4521
    url: http://127.0.0.1:4521/health
  - name: svc-4522
    url: http://127.0.0.1:4522/health
  - name: svc-4523
    url: http://127.0.0.1:4523/health
  - name: svc-4524
    url: http://127.0.0.1:4524/health
@end

## Role Signals
@read README.md
@read package.json
@read pyproject.toml
@skills flag_stale=true
@waypoint ttl=86400
@agora status=open,in_progress

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
