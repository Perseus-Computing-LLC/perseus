@perseus v0.8
@prompt You are a simulated backend python working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=300
@query "python3 --version" timeout=5 @cache ttl=300
@query "pip --version" timeout=5 @cache ttl=300
@query "pytest --version" timeout=5 @cache ttl=300
@query "mypy --version" timeout=5 @cache ttl=300
@query "ruff --version" timeout=5 @cache ttl=300
@query "black --version" timeout=5 @cache ttl=300
@query "isort --version" timeout=5 @cache ttl=300
@query "flake8 --version" timeout=5 @cache ttl=300
@query "bandit --version" timeout=5 @cache ttl=300
@query "safety --version" timeout=5 @cache ttl=300
@query "poetry --version" timeout=5 @cache ttl=300
@query "pip-compile --version" timeout=5 @cache ttl=300
@query "pip-sync --version" timeout=5 @cache ttl=300
@query "uv --version" timeout=5 @cache ttl=300
@query "nox --version" timeout=5 @cache ttl=300
@query "tox --version" timeout=5 @cache ttl=300
@query "coverage --version" timeout=5 @cache ttl=300
@query "pypistats --version" timeout=5 @cache ttl=300
@query "ls -la src/" timeout=5 @cache ttl=300
@query "ls -la tests/" timeout=5 @cache ttl=300
@query "wc -l src/**/*.py 2>/dev/null" timeout=5 @cache ttl=300
@query "wc -l tests/**/*.py 2>/dev/null" timeout=5 @cache ttl=300
@query "cat pyproject.toml | head -30" timeout=5 @cache ttl=300
@query "cat setup.cfg 2>/dev/null" timeout=5 @cache ttl=300
@query "cat setup.py 2>/dev/null" timeout=5 @cache ttl=300
@query "cat pyproject.toml" timeout=5 @cache ttl=300
@query "cat .pre-commit-config.yaml" timeout=5 @cache ttl=300
@query "pip list --format=columns | head -30" timeout=5 @cache ttl=300
@query "pip list --outdated --format=columns | head -20" timeout=5 @cache ttl=300
@query "pytest --collect-only -q tests/" timeout=5 @cache ttl=300
@query "mypy src/" timeout=5 @cache ttl=300
@query "ruff check src/" timeout=5 @cache ttl=300
@services
  - name: api-blue
    url: http://localhost:8000/health
    timeout: 2
  - name: api-green
    url: http://localhost:8001/health
    timeout: 2
  - name: celery-flower
    url: http://localhost:5555/health
    timeout: 2
  - name: redis
    url: http://localhost:6379/health
    timeout: 2
  - name: postgres
    url: http://localhost:5432/health
    timeout: 2
  - name: rabbitmq
    url: http://localhost:5672/health
    timeout: 2
  - name: sentry-backend
    url: http://localhost:9000/health
    timeout: 2
  - name: datadog
    url: http://localhost:8125/health
    timeout: 2
@read pyproject.toml
@read setup.cfg
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@memory focus="recent"
@drift
@inbox

@mneme query="Python sqlite FTS5"