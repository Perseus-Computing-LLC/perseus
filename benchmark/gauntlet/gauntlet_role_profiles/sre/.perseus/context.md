@perseus v0.8
@prompt
You are the sre profile in the Perseus gauntlet.
@end

## Baseline
@query "git log --oneline -5" @cache ttl=300

## Services
@services
  - name: svc-4620
    url: http://127.0.0.1:4620/health
  - name: svc-4621
    url: http://127.0.0.1:4621/health
  - name: svc-4622
    url: http://127.0.0.1:4622/health
  - name: svc-4623
    url: http://127.0.0.1:4623/health
  - name: svc-4624
    url: http://127.0.0.1:4624/health
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
@health
@drift
@synthesize question="What is the benchmark role?" source="README.md"

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
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 73" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 80" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "git status --short" @cache ttl=300
@query "printf gauntlet_%s 87" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "pwd" @cache ttl=300
@query "ls" @cache ttl=300
@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
