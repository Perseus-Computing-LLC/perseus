@perseus v0.8
@prompt You are a simulated architect working inside a large enterprise.

@query "git log --oneline -10" @cache ttl=300
@query "git log --all --oneline --graph" @cache ttl=300
@query "gh repo view" @cache ttl=300
@query "gh api repos/:owner/:repo/languages" @cache ttl=300
@query "cat .github/CODEOWNERS" @cache ttl=300
@query "cat .github/CODEOWNERS" @cache ttl=300
@query "ls -la" @cache ttl=300
@query "find . -name '*.py' -o -name '*.ts' -o -name '*.go' | head -30" @cache ttl=300
@query "wc -l $(find . -name '*.py' -o -name '*.ts' -o -name '*.go' | head -100) 2>/dev/null" @cache ttl=300
@query "cloc --version 2>/dev/null && cloc --quiet ." @cache ttl=300
@query "du -sh . --exclude=.git" @cache ttl=300
@query "cat README.md | head -20" @cache ttl=300
@query "cat ROADMAP.md" @cache ttl=300
@query "cat AGENTS.md 2>/dev/null" @cache ttl=300
@query "cat .perseus/context.md 2>/dev/null" @cache ttl=300
@services
  - name: archimate
    url: http://localhost:8080/health
    timeout: 2
  - name: structurizr
    url: http://localhost:8081/health
    timeout: 2
  - name: drawio
    url: http://localhost:8082/health
    timeout: 2
  - name: c4-builder
    url: http://localhost:8083/health
    timeout: 2
  - name: adr-viewer
    url: http://localhost:8084/health
    timeout: 2
  - name: backstage
    url: http://localhost:7000/health
    timeout: 2
  - name: docsify
    url: http://localhost:3000/health
    timeout: 2
@read README.md
@read ROADMAP.md
@read AGENTS.md
@read .perseus/context.md
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@memory focus="recent"
@drift
@prefetch
@graph @focus="architecture"
@synthesize
