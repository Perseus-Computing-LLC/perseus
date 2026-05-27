@perseus v0.8
@prompt
You are the performance engineer profile in the Perseus gauntlet.
@end

## Baseline
@query "git log --oneline -5" @cache ttl=300

## Services
@services
  - name: svc-4720
    url: http://127.0.0.1:4720/health
  - name: svc-4721
    url: http://127.0.0.1:4721/health
  - name: svc-4722
    url: http://127.0.0.1:4722/health
  - name: svc-4723
    url: http://127.0.0.1:4723/health
  - name: svc-4724
    url: http://127.0.0.1:4724/health
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
