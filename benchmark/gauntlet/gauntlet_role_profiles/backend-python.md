@perseus v0.8
@prompt You are a simulated backend python working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "pip --version" @cache ttl=300
@query "pytest --version" @cache ttl=300
@query "mypy --version" @cache ttl=300
@query "ruff --version" @cache ttl=300
@query "black --version" @cache ttl=300
@query "isort --version" @cache ttl=300
@query "flake8 --version" @cache ttl=300
@query "bandit --version" @cache ttl=300
@query "safety --version" @cache ttl=300
@query "poetry --version" @cache ttl=300
@query "pip-compile --version" @cache ttl=300
@query "pip-sync --version" @cache ttl=300
@query "uv --version" @cache ttl=300
@query "nox --version" @cache ttl=300
@query "tox --version" @cache ttl=300
@query "coverage --version" @cache ttl=300
@query "pypistats --version" @cache ttl=300
@query "ls -la src/" @cache ttl=300
@query "ls -la tests/" @cache ttl=300
@query "wc -l src/**/*.py 2>/dev/null" @cache ttl=300
@query "wc -l tests/**/*.py 2>/dev/null" @cache ttl=300
@query "cat pyproject.toml | head -30" @cache ttl=300
@query "cat setup.cfg 2>/dev/null" @cache ttl=300
@query "cat setup.py 2>/dev/null" @cache ttl=300
@query "cat pyproject.toml" @cache ttl=300
@query "cat .pre-commit-config.yaml" @cache ttl=300
@query "pip list --format=columns | head -30" @cache ttl=300
@query "pip list --outdated --format=columns | head -20" @cache ttl=300
@query "pytest --collect-only -q tests/" @cache ttl=300
@query "mypy src/" @cache ttl=300
@query "ruff check src/" @cache ttl=300
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
