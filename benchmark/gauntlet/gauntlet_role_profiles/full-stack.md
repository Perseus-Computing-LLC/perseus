@perseus v0.8
@prompt You are a simulated full stack working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "node --version" @cache ttl=300
@query "npm --version" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "java --version" @cache ttl=300
@query "npx next --version" @cache ttl=300
@query "npx nest --version" @cache ttl=300
@query "npx prisma --version" @cache ttl=300
@query "npx drizzle-kit --version" @cache ttl=300
@query "npx tsc --version" @cache ttl=300
@query "npx eslint --version" @cache ttl=300
@query "npx prettier --version" @cache ttl=300
@query "npx jest --version" @cache ttl=300
@query "npx playwright --version" @cache ttl=300
@query "npx cypress --version" @cache ttl=300
@query "npx swagger --version" @cache ttl=300
@query "npx graphql --version" @cache ttl=300
@query "ls -la src/" @cache ttl=300
@query "ls -la api/" @cache ttl=300
@query "ls -la web/" @cache ttl=300
@query "ls -la shared/" @cache ttl=300
@query "ls -la e2e/" @cache ttl=300
@query "wc -l **/*.{ts,js,py} 2>/dev/null | tail -5" @cache ttl=300
@query "cat package.json" @cache ttl=300
@query "cat tsconfig.json" @cache ttl=300
@query "cat turbo.json 2>/dev/null" @cache ttl=300
@query "cat nx.json 2>/dev/null" @cache ttl=300
@query "cat docker-compose.yml 2>/dev/null | head -30" @cache ttl=300
@query "cat .github/workflows/ci.yml" @cache ttl=300
@query "cat .env.example" @cache ttl=300
@query "cat Dockerfile" @cache ttl=300
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
@drift
@prefetch
