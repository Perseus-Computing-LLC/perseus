@perseus v0.8
@prompt You are a simulated intern working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=300
@query "git status" timeout=5 @cache ttl=300
@query "python3 --version" timeout=5 @cache ttl=300
@query "pip --version" timeout=5 @cache ttl=300
@query "npm --version" timeout=5 @cache ttl=300
@query "cat README.md | head -10" timeout=5 @cache ttl=300
@query "ls -la" timeout=5 @cache ttl=300
@query "cat .github/CONTRIBUTING.md 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .github/CODE_OF_CONDUCT.md 2>/dev/null" timeout=5 @cache ttl=300
@query "ls docs/ 2>/dev/null" timeout=5 @cache ttl=300
@query "cat CONTRIBUTING.md 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .env.example 2>/dev/null" timeout=5 @cache ttl=300
@query "cat requirements.txt 2>/dev/null" timeout=5 @cache ttl=300
@query "cat package.json | python3 -m json.tool 2>/dev/null" timeout=5 @cache ttl=300
@query "cat Makefile | head -20 2>/dev/null" timeout=5 @cache ttl=300
@read README.md
@read .github/CONTRIBUTING.md
@skills flag_stale=true
@waypoint ttl=86400
