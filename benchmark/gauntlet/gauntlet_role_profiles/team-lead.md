@perseus v0.8
@prompt You are a simulated team lead working inside a large enterprise.

@query "git log --oneline -10" @cache ttl=300
@query "git shortlog -sn --all" @cache ttl=300
@query "git branch -a" @cache ttl=300
@query "gh --version" @cache ttl=300
@query "jira --version 2>/dev/null" @cache ttl=300
@query "cat .github/CODEOWNERS" @cache ttl=300
@query "cat CONTRIBUTING.md" @cache ttl=300
@query "cat CODE_OF_CONDUCT.md" @cache ttl=300
@query "ls -la .github/" @cache ttl=300
@query "cat .github/ISSUE_TEMPLATE/" @cache ttl=300
@query "gh pr list --state open --limit 10" @cache ttl=300
@query "gh pr list --state merged --limit 5" @cache ttl=300
@query "gh issue list --state open --limit 10" @cache ttl=300
@query "gh issue list --label blocked --limit 5" @cache ttl=300
@query "gh release list --limit 5" @cache ttl=300
@query "gh api repos/:owner/:repo/branches" @cache ttl=300
@query "gh api repos/:owner/:repo/stats/contributors" @cache ttl=300
@query "gh api repos/:owner/:repo/stats/code_frequency" @cache ttl=300
@query "gh api repos/:owner/:repo/stats/commit_activity" @cache ttl=300
@query "gh api repos/:owner/:repo/stats/participation" @cache ttl=300
@query "curl -s https://api.github.com/repos/tcconnally/perseus" @cache ttl=300
@query "gh run list --limit 10" @cache ttl=300
@query "gh run list --status failed --limit 5" @cache ttl=300
@query "cat ROADMAP.md" @cache ttl=300
@query "ls -la tasks/" @cache ttl=300
@query "wc -l tasks/*.md 2>/dev/null" @cache ttl=300
@query "cat .github/milestones.yml 2>/dev/null" @cache ttl=300
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
