@perseus v0.8
@prompt You are a simulated accessibility auditor working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "node --version" timeout=5 @cache ttl=86400
@query "npx axe --version" timeout=5 @cache ttl=86400
@query "npx lighthouse --version" timeout=5 @cache ttl=86400
@query "npx pa11y --version" timeout=5 @cache ttl=86400
@query "npx wave --version" timeout=5 @cache ttl=86400
@query "npx accesslint --version" timeout=5 @cache ttl=86400
@query "npx checker --version" timeout=5 @cache ttl=86400
@query "npx html-validate --version" timeout=5 @cache ttl=86400
@query "npx nu-html-checker --version" timeout=5 @cache ttl=86400
@query "ls -la src/" timeout=5 @cache ttl=86400
@query "ls -la src/components/" timeout=5 @cache ttl=86400
@query "ls -la src/pages/" timeout=5 @cache ttl=86400
@query "wc -l src/**/*.{html,vue,tsx,jsx} 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat package.json" timeout=5 @cache ttl=86400
@query "cat .accesslintrc.js 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .pa11yci 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .lighthouserc.js 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .htmlvalidate.json 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat wcag-report.json 2>/dev/null" timeout=5 @cache ttl=86400
@services
  - name: axe-core
    url: http://localhost:8080/health
    timeout: 2
  - name: lighthouse-ci
    url: http://localhost:8081/health
    timeout: 2
  - name: pa11y-dashboard
    url: http://localhost:8082/health
    timeout: 2
  - name: wave-api
    url: http://localhost:8083/health
    timeout: 2
@read README.md
@read package.json
@skills flag_stale=true
@waypoint ttl=86400
@synthesize
@memory focus="recent"
