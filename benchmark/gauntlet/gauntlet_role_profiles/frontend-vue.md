@perseus v0.8
@prompt You are a simulated frontend vue working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "node --version" timeout=5 @cache ttl=86400
@query "npm --version" timeout=5 @cache ttl=86400
@query "npx vue --version" timeout=5 @cache ttl=86400
@query "npx nuxt --version" timeout=5 @cache ttl=86400
@query "npx vite --version" timeout=5 @cache ttl=86400
@query "npx vitest --version" timeout=5 @cache ttl=86400
@query "npx playwright --version" timeout=5 @cache ttl=86400
@query "npx eslint --version" timeout=5 @cache ttl=86400
@query "npx prettier --version" timeout=5 @cache ttl=86400
@query "npx stylelint --version" timeout=5 @cache ttl=86400
@query "npx vue-tsc --version" timeout=5 @cache ttl=86400
@query "ls -la src/" timeout=5 @cache ttl=86400
@query "ls -la src/components/" timeout=5 @cache ttl=86400
@query "ls -la src/pages/" timeout=5 @cache ttl=86400
@query "ls -la src/composables/" timeout=5 @cache ttl=86400
@query "ls -la src/store/" timeout=5 @cache ttl=86400
@query "ls -la public/" timeout=5 @cache ttl=86400
@query "wc -l src/**/*.{vue,ts,js} 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat package.json" timeout=5 @cache ttl=86400
@query "cat tsconfig.json" timeout=5 @cache ttl=86400
@query "cat nuxt.config.ts 2>/dev/null || cat vite.config.ts 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat tailwind.config.js 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .eslintrc.json 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .prettierrc" timeout=5 @cache ttl=86400
@query "npx npm-check" timeout=5 @cache ttl=86400
@services
  - name: dev-server
    url: http://localhost:3000/health
    timeout: 2
  - name: nuxt-devtools
    url: http://localhost:3300/health
    timeout: 2
  - name: storybook-vue
    url: http://localhost:6006/health
    timeout: 2
@read package.json
@read tsconfig.json
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
