@perseus v0.8
@prompt You are a simulated team lead working inside a large enterprise.

@query "git log --oneline -10" timeout=5 @cache ttl=86400
@query "git shortlog -sn --all" timeout=5 @cache ttl=86400
@query "git branch -a" timeout=5 @cache ttl=86400
@query "gh --version" timeout=5 @cache ttl=86400
@query "jira --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .github/CODEOWNERS" timeout=5 @cache ttl=86400
@query "cat CONTRIBUTING.md" timeout=5 @cache ttl=86400
@query "cat CODE_OF_CONDUCT.md" timeout=5 @cache ttl=86400
@query "ls -la .github/" timeout=5 @cache ttl=86400
@query "cat .github/ISSUE_TEMPLATE/" timeout=5 @cache ttl=86400
@query "gh pr list --state open --limit 10" timeout=5 @cache ttl=86400
@query "gh pr list --state merged --limit 5" timeout=5 @cache ttl=86400
@query "gh issue list --state open --limit 10" timeout=5 @cache ttl=86400
@query "gh issue list --label blocked --limit 5" timeout=5 @cache ttl=86400
@query "gh release list --limit 5" timeout=5 @cache ttl=86400
@query "gh api repos/:owner/:repo/branches" timeout=5 @cache ttl=86400
@query "gh api repos/:owner/:repo/stats/contributors" timeout=5 @cache ttl=86400
@query "gh api repos/:owner/:repo/stats/code_frequency" timeout=5 @cache ttl=86400
@query "gh api repos/:owner/:repo/stats/commit_activity" timeout=5 @cache ttl=86400
@query "gh api repos/:owner/:repo/stats/participation" timeout=5 @cache ttl=86400
@query "curl -s https://api.github.com/repos/Perseus-Computing-LLC/perseus" timeout=5 @cache ttl=86400
@query "gh run list --limit 10" timeout=5 @cache ttl=86400
@query "gh run list --status failed --limit 5" timeout=5 @cache ttl=86400
@query "cat ROADMAP.md" timeout=5 @cache ttl=86400
@query "ls -la tasks/" timeout=5 @cache ttl=86400
@query "wc -l tasks/*.md 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .github/milestones.yml 2>/dev/null" timeout=5 @cache ttl=86400
@services
  - name: jira
    url: http://localhost:8080/health
    timeout: 2
  - name: confluence
    url: http://localhost:8090/health
    timeout: 2
  - name: slack-bot
    url: http://localhost:8081/health
    timeout: 2
  - name: github-runner
    url: http://localhost:8082/health
    timeout: 2
  - name: statuspage
    url: http://localhost:8083/health
    timeout: 2
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@memory focus="recent"
@memory focus="decisions"
@drift
