@perseus v0.8
@prompt You are a simulated release manager working inside a large enterprise.

@query "git log --oneline -20" @cache ttl=300
@query "git tag -l --sort=-version:refname" @cache ttl=300
@query "git describe --tags --always" @cache ttl=300
@query "git log --oneline --decorate tag..HEAD" @cache ttl=300
@query "gh release list --limit 10" @cache ttl=300
@query "gh release view" @cache ttl=300
@query "gh pr list --state merged --limit 10 --json title,mergedAt,labels" @cache ttl=300
@query "gh pr list --state open --limit 5" @cache ttl=300
@query "gh run list --limit 10 --json conclusion,headBranch,createdAt" @cache ttl=300
@query "gh run list --status failed --limit 5" @cache ttl=300
@query "gh issue list --milestone current --state closed --limit 20" @cache ttl=300
@query "gh issue list --milestone next --state open --limit 10" @cache ttl=300
@query "cat CHANGELOG.md | head -40" @cache ttl=300
@query "cat .github/release.yml 2>/dev/null" @cache ttl=300
@query "cat .github/changesets/config.json 2>/dev/null" @cache ttl=300
@query "ls -la .changeset/ 2>/dev/null" @cache ttl=300
@query "cat .github/workflows/release.yml" @cache ttl=300
@query "cat VERSION 2>/dev/null || cat version.txt 2>/dev/null" @cache ttl=300
@query "git status" @cache ttl=300
@query "git stash list" @cache ttl=300
@query "git reflog --oneline -10" @cache ttl=300
@services
  - name: release-dashboard
    url: http://localhost:8080/health
    timeout: 2
  - name: changelog-gen
    url: http://localhost:8081/health
    timeout: 2
  - name: version-bot
    url: http://localhost:8082/health
    timeout: 2
  - name: release-notes
    url: http://localhost:8083/health
    timeout: 2
  - name: slack-release
    url: http://localhost:8084/health
    timeout: 2
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@memory focus="recent"
