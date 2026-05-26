@perseus v0.8
@prompt You are a simulated web developer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "npm --version" @cache ttl=300
@query "node --version" @cache ttl=300
@query "npm ls --depth=0" @cache ttl=300
@query "npm audit --json" @cache ttl=300
@query "npx jest --version" @cache ttl=300
@query "npx eslint --version" @cache ttl=300
@query "npx prettier --version" @cache ttl=300
@read /workspace/perseus/package.json
@read /workspace/perseus/tsconfig.json
@skills flag_stale=true
@waypoint ttl=86400
@services
  - name: dev-server
    url: http://localhost:3000/health
    timeout: 2
  - name: api-mock
    url: http://localhost:3001/health
    timeout: 2
  - name: storybook
    url: http://localhost:6006/
    timeout: 2
@agora status=open,in_progress
@inbox
@memory focus="recent"
@health
@drift
@query "cat package.json | python3 -m json.tool" @cache ttl=300
@query "ls -la node_modules/.bin/" @cache ttl=300
@query "npx tsc --version" @cache ttl=300
@query "npx next --version" @cache ttl=300
@query "npx vite --version" @cache ttl=300
@query "npx webpack --version" @cache ttl=300
@query "npx rollup --version" @cache ttl=300
@query "npx remix --version" @cache ttl=300
@query "npx svelte --version" @cache ttl=300
@query "npx astro --version" @cache ttl=300
@query "npx nuxt --version" @cache ttl=300
@query "cat .nvmrc" @cache ttl=300
@query "cat .node-version" @cache ttl=300
@query "npm outdated --json" @cache ttl=300
@query "npm cache ls 2>/dev/null || echo cache empty" @cache ttl=300
@query "npx playwright --version" @cache ttl=300
@query "npx cypress --version" @cache ttl=300
@query "npx vitest --version" @cache ttl=300
@query "ls src/components/" @cache ttl=300
@query "ls src/pages/" @cache ttl=300
@query "ls src/lib/" @cache ttl=300
@query "ls public/" @cache ttl=300
@query "wc -l src/**/*.{ts,tsx} 2>/dev/null" @cache ttl=300
@query "cat .env.local 2>/dev/null || echo no .env.local" @cache ttl=300
@query "cat .env.production 2>/dev/null || echo no .env.production" @cache ttl=300
@query "npx browserslist" @cache ttl=300
@query "npx caniuse --version" @cache ttl=300
@query "npx lighthouse --version" @cache ttl=300
@query "cat tsconfig.json" @cache ttl=300
@query "cat .eslintrc.js 2>/dev/null || cat .eslintrc.json 2>/dev/null || echo no eslintrc" @cache ttl=300
@query "cat .prettierrc 2>/dev/null || echo no prettierrc" @cache ttl=300
@query "ls -la .husky/" @cache ttl=300
@query "npx turbo --version" @cache ttl=300
@query "npx changeset --version" @cache ttl=300
@query "npx npm-check-updates --version" @cache ttl=300
@query "du -sh node_modules/" @cache ttl=300
@query "find . -name \"*.test.ts\" -o -name \"*.spec.ts\" | wc -l" @cache ttl=300
@query "cat .github/workflows/*.yml" @cache ttl=300
@query "npx knip --version" @cache ttl=300
@query "npx syncpack --version" @cache ttl=300
