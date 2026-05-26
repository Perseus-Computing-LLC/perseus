@perseus v0.8
@prompt You are a simulated intern working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "git status" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "pip --version" @cache ttl=300
@query "npm --version" @cache ttl=300
@query "cat README.md | head -10" @cache ttl=300
@query "ls -la" @cache ttl=300
@query "cat .github/CONTRIBUTING.md 2>/dev/null" @cache ttl=300
@query "cat .github/CODE_OF_CONDUCT.md 2>/dev/null" @cache ttl=300
@query "ls docs/ 2>/dev/null" @cache ttl=300
@query "cat CONTRIBUTING.md 2>/dev/null" @cache ttl=300
@query "cat .env.example 2>/dev/null" @cache ttl=300
@query "cat requirements.txt 2>/dev/null" @cache ttl=300
@query "cat package.json | python3 -m json.tool 2>/dev/null" @cache ttl=300
@query "cat Makefile | head -20 2>/dev/null" @cache ttl=300
@read README.md
@read .github/CONTRIBUTING.md
@skills flag_stale=true
@waypoint ttl=86400
