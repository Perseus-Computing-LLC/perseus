@perseus v0.8
@prompt You are a simulated full stack working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "node --version" timeout=5 @cache ttl=86400
@query "npm --version" timeout=5 @cache ttl=86400
@query "python3 --version" timeout=5 @cache ttl=86400
@query "java --version" timeout=5 @cache ttl=86400
@query "npx next --version" timeout=5 @cache ttl=86400
@query "npx nest --version" timeout=5 @cache ttl=86400
@query "npx prisma --version" timeout=5 @cache ttl=86400
@query "npx drizzle-kit --version" timeout=5 @cache ttl=86400
@query "npx tsc --version" timeout=5 @cache ttl=86400
@query "npx eslint --version" timeout=5 @cache ttl=86400
@query "npx prettier --version" timeout=5 @cache ttl=86400
@query "npx jest --version" timeout=5 @cache ttl=86400
@query "npx playwright --version" timeout=5 @cache ttl=86400
@query "npx cypress --version" timeout=5 @cache ttl=86400
@query "npx swagger --version" timeout=5 @cache ttl=86400
@query "npx graphql --version" timeout=5 @cache ttl=86400
@query "ls -la src/" timeout=5 @cache ttl=86400
@query "ls -la api/" timeout=5 @cache ttl=86400
@query "ls -la web/" timeout=5 @cache ttl=86400
@query "ls -la shared/" timeout=5 @cache ttl=86400
@query "ls -la e2e/" timeout=5 @cache ttl=86400
@query "wc -l **/*.{ts,js,py} 2>/dev/null | tail -5" timeout=5 @cache ttl=86400
@query "cat package.json" timeout=5 @cache ttl=86400
@query "cat tsconfig.json" timeout=5 @cache ttl=86400
@query "cat turbo.json 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat nx.json 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat docker-compose.yml 2>/dev/null | head -30" timeout=5 @cache ttl=86400
@query "cat .github/workflows/ci.yml" timeout=5 @cache ttl=86400
@query "cat .env.example" timeout=5 @cache ttl=86400
@query "cat Dockerfile" timeout=5 @cache ttl=86400
@services
  - name: api
    url: http://localhost:3001/health
    timeout: 2
  - name: webapp
    url: http://localhost:3000/health
    timeout: 2
  - name: postgres
    url: http://localhost:5432/health
    timeout: 2
  - name: redis
    url: http://localhost:6379/health
    timeout: 2
  - name: minio
    url: http://localhost:9000/health
    timeout: 2
  - name: swagger-ui
    url: http://localhost:8080/health
    timeout: 2
  - name: graphql-playground
    url: http://localhost:4000/health
    timeout: 2
  - name: hasura
    url: http://localhost:8081/health
    timeout: 2
  - name: n8n
    url: http://localhost:5678/health
    timeout: 2
  - name: supabase
    url: http://localhost:8000/health
    timeout: 2
  - name: directus
    url: http://localhost:8055/health
    timeout: 2
  - name: strapi
    url: http://localhost:1337/health
    timeout: 2
@read package.json
@read README.md
@read Dockerfile
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@memory focus="recent"
@memory focus="decisions"
@memory
@drift
@prefetch
