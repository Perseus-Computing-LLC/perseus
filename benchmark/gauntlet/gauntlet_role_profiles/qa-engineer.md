@perseus v0.8
@prompt You are a simulated qa engineer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "pytest --version" timeout=5 @cache ttl=86400
@query "cypress --version" timeout=5 @cache ttl=86400
@query "playwright --version" timeout=5 @cache ttl=86400
@query "selenium --version" timeout=5 @cache ttl=86400
@query "jest --version" timeout=5 @cache ttl=86400
@query "node --version" timeout=5 @cache ttl=86400
@query "python3 --version" timeout=5 @cache ttl=86400
@query "npx cypress run --browser chrome --headless --spec **/*.cy.ts" timeout=5 @cache ttl=86400
@query "npx playwright test --list" timeout=5 @cache ttl=86400
@query "pytest --collect-only -q" timeout=5 @cache ttl=86400
@query "pytest --coverage --version" timeout=5 @cache ttl=86400
@query "cat .coveragerc 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat pytest.ini" timeout=5 @cache ttl=86400
@query "ls -la tests/" timeout=5 @cache ttl=86400
@query "wc -l tests/**/*.py 2>/dev/null" timeout=5 @cache ttl=86400
@query "ls -la cypress/" timeout=5 @cache ttl=86400
@query "wc -l cypress/e2e/*.cy.ts 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .github/workflows/test.yml" timeout=5 @cache ttl=86400
@query "cat sonar-project.properties 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .env.test" timeout=5 @cache ttl=86400
@query "npx cypress verify" timeout=5 @cache ttl=86400
@query "pytest -x --tb=short --maxfail=5 tests/" timeout=5 @cache ttl=86400
@query "flake8 --version" timeout=5 @cache ttl=86400
@query "mypy --version" timeout=5 @cache ttl=86400
@query "ruff --version" timeout=5 @cache ttl=86400
@query "bandit --version" timeout=5 @cache ttl=86400
@query "safety --version" timeout=5 @cache ttl=86400
@query "vulture --version" timeout=5 @cache ttl=86400
@query "pylint --version" timeout=5 @cache ttl=86400
@services
  - name: test-runner
    url: http://localhost:8080/health
    timeout: 2
  - name: selenium-hub
    url: http://localhost:4444/health
    timeout: 2
  - name: report-portal
    url: http://localhost:8081/health
    timeout: 2
  - name: allure
    url: http://localhost:8082/health
    timeout: 2
  - name: testlink
    url: http://localhost:8083/health
    timeout: 2
@waypoint ttl=86400
@skills flag_stale=true
@agora status=open,in_progress
@inbox
@health
