@perseus v0.8
@prompt You are a simulated qa engineer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "pytest --version" @cache ttl=300
@query "cypress --version" @cache ttl=300
@query "playwright --version" @cache ttl=300
@query "selenium --version" @cache ttl=300
@query "jest --version" @cache ttl=300
@query "node --version" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "npx cypress run --browser chrome --headless --spec **/*.cy.ts" @cache ttl=300
@query "npx playwright test --list" @cache ttl=300
@query "pytest --collect-only -q" @cache ttl=300
@query "pytest --coverage --version" @cache ttl=300
@query "cat .coveragerc 2>/dev/null" @cache ttl=300
@query "cat pytest.ini" @cache ttl=300
@query "ls -la tests/" @cache ttl=300
@query "wc -l tests/**/*.py 2>/dev/null" @cache ttl=300
@query "ls -la cypress/" @cache ttl=300
@query "wc -l cypress/e2e/*.cy.ts 2>/dev/null" @cache ttl=300
@query "cat .github/workflows/test.yml" @cache ttl=300
@query "cat sonar-project.properties 2>/dev/null" @cache ttl=300
@query "cat .env.test" @cache ttl=300
@query "npx cypress verify" @cache ttl=300
@query "pytest -x --tb=short --maxfail=5 tests/" @cache ttl=300
@query "flake8 --version" @cache ttl=300
@query "mypy --version" @cache ttl=300
@query "ruff --version" @cache ttl=300
@query "bandit --version" @cache ttl=300
@query "safety --version" @cache ttl=300
@query "vulture --version" @cache ttl=300
@query "pylint --version" @cache ttl=300
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
