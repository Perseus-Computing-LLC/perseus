@perseus v0.8
@prompt You are a simulated frontend vue working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "node --version" @cache ttl=300
@query "npm --version" @cache ttl=300
@query "npx vue --version" @cache ttl=300
@query "npx nuxt --version" @cache ttl=300
@query "npx vite --version" @cache ttl=300
@query "npx vitest --version" @cache ttl=300
@query "npx playwright --version" @cache ttl=300
@query "npx eslint --version" @cache ttl=300
@query "npx prettier --version" @cache ttl=300
@query "npx stylelint --version" @cache ttl=300
@query "npx vue-tsc --version" @cache ttl=300
@query "ls -la src/" @cache ttl=300
@query "ls -la src/components/" @cache ttl=300
@query "ls -la src/pages/" @cache ttl=300
@query "ls -la src/composables/" @cache ttl=300
@query "ls -la src/store/" @cache ttl=300
@query "ls -la public/" @cache ttl=300
@query "wc -l src/**/*.{vue,ts,js} 2>/dev/null" @cache ttl=300
@query "cat package.json" @cache ttl=300
@query "cat tsconfig.json" @cache ttl=300
@query "cat nuxt.config.ts 2>/dev/null || cat vite.config.ts 2>/dev/null" @cache ttl=300
@query "cat tailwind.config.js 2>/dev/null" @cache ttl=300
@query "cat .eslintrc.json 2>/dev/null" @cache ttl=300
@query "cat .prettierrc" @cache ttl=300
@query "npx npm-check" @cache ttl=300
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
