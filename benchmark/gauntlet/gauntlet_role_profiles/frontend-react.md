@perseus v0.8
@prompt You are a simulated frontend react working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=300
@query "node --version" timeout=5 @cache ttl=300
@query "npm --version" timeout=5 @cache ttl=300
@query "npx react-scripts --version" timeout=5 @cache ttl=300
@query "npx next --version" timeout=5 @cache ttl=300
@query "npx vite --version" timeout=5 @cache ttl=300
@query "npx jest --version" timeout=5 @cache ttl=300
@query "npx playwright --version" timeout=5 @cache ttl=300
@query "npx cypress --version" timeout=5 @cache ttl=300
@query "npx eslint --version" timeout=5 @cache ttl=300
@query "npx prettier --version" timeout=5 @cache ttl=300
@query "npx stylelint --version" timeout=5 @cache ttl=300
@query "npx chromatic --version" timeout=5 @cache ttl=300
@query "npx storybook --version" timeout=5 @cache ttl=300
@query "ls -la src/" timeout=5 @cache ttl=300
@query "ls -la src/components/" timeout=5 @cache ttl=300
@query "ls -la src/pages/" timeout=5 @cache ttl=300
@query "ls -la src/hooks/" timeout=5 @cache ttl=300
@query "ls -la src/lib/" timeout=5 @cache ttl=300
@query "ls -la public/" timeout=5 @cache ttl=300
@query "wc -l src/**/*.{ts,tsx} 2>/dev/null" timeout=5 @cache ttl=300
@query "cat package.json" timeout=5 @cache ttl=300
@query "cat tsconfig.json" timeout=5 @cache ttl=300
@query "cat next.config.js 2>/dev/null || cat vite.config.ts 2>/dev/null" timeout=5 @cache ttl=300
@query "cat tailwind.config.js 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .eslintrc.json 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .prettierrc" timeout=5 @cache ttl=300
@query "cat postcss.config.js 2>/dev/null" timeout=5 @cache ttl=300
@query "npx npm-check" timeout=5 @cache ttl=300
@services
  - name: dev-server
    url: http://localhost:3000/health
    timeout: 2
  - name: storybook
    url: http://localhost:6006/health
    timeout: 2
  - name: chromatic-review
    url: http://localhost:8080/health
    timeout: 2
@read package.json
@read tsconfig.json
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
