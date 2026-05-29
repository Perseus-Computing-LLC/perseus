@perseus v0.8
@prompt You are a simulated web developer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=300
@query "npm --version" timeout=5 @cache ttl=300
@query "node --version" timeout=5 @cache ttl=300
@query "npm ls --depth=0" timeout=5 @cache ttl=300
@query "npm audit --json" timeout=5 @cache ttl=300
@query "npx jest --version" timeout=5 @cache ttl=300
@query "npx eslint --version" timeout=5 @cache ttl=300
@query "npx prettier --version" timeout=5 @cache ttl=300
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
@query "cat package.json | python3 -m json.tool" timeout=5 @cache ttl=300
@query "ls -la node_modules/.bin/" timeout=5 @cache ttl=300
@query "npx tsc --version" timeout=5 @cache ttl=300
@query "npx next --version" timeout=5 @cache ttl=300
@query "npx vite --version" timeout=5 @cache ttl=300
@query "npx webpack --version" timeout=5 @cache ttl=300
@query "npx rollup --version" timeout=5 @cache ttl=300
@query "npx remix --version" timeout=5 @cache ttl=300
@query "npx svelte --version" timeout=5 @cache ttl=300
@query "npx astro --version" timeout=5 @cache ttl=300
@query "npx nuxt --version" timeout=5 @cache ttl=300
@query "cat .nvmrc" timeout=5 @cache ttl=300
@query "cat .node-version" timeout=5 @cache ttl=300
@query "npm outdated --json" timeout=5 @cache ttl=300
@query "npm cache ls 2>/dev/null || echo cache empty" timeout=5 @cache ttl=300
@query "npx playwright --version" timeout=5 @cache ttl=300
@query "npx cypress --version" timeout=5 @cache ttl=300
@query "npx vitest --version" timeout=5 @cache ttl=300
@query "ls src/components/" timeout=5 @cache ttl=300
@query "ls src/pages/" timeout=5 @cache ttl=300
@query "ls src/lib/" timeout=5 @cache ttl=300
@query "ls public/" timeout=5 @cache ttl=300
@query "wc -l src/**/*.{ts,tsx} 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .env.local 2>/dev/null || echo no .env.local" timeout=5 @cache ttl=300
@query "cat .env.production 2>/dev/null || echo no .env.production" timeout=5 @cache ttl=300
@query "npx browserslist" timeout=5 @cache ttl=300
@query "npx caniuse --version" timeout=5 @cache ttl=300
@query "npx lighthouse --version" timeout=5 @cache ttl=300
@query "cat tsconfig.json" timeout=5 @cache ttl=300
@query "cat .eslintrc.js 2>/dev/null || cat .eslintrc.json 2>/dev/null || echo no eslintrc" timeout=5 @cache ttl=300
@query "cat .prettierrc 2>/dev/null || echo no prettierrc" timeout=5 @cache ttl=300
@query "ls -la .husky/" timeout=5 @cache ttl=300
@query "npx turbo --version" timeout=5 @cache ttl=300
@query "npx changeset --version" timeout=5 @cache ttl=300
@query "npx npm-check-updates --version" timeout=5 @cache ttl=300
@query "du -sh node_modules/" timeout=5 @cache ttl=300
@query "find . -name \"*.test.ts\" -o -name \"*.spec.ts\" | wc -l" @cache ttl=300
@query "cat .github/workflows/*.yml" timeout=5 @cache ttl=300
@query "npx knip --version" timeout=5 @cache ttl=300
@query "npx syncpack --version" timeout=5 @cache ttl=300
