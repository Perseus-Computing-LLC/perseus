@perseus v0.4

# Context - @date format="YYYY-MM-DD HH:mm z"

## Persistent Memory
@mneme query="lesson preference decision reference" k=5 scope=perseus

## Environment
@query "which perseus 2>/dev/null || echo 'perseus not on PATH'"
@query "python3 -c 'import perseus; print(perseus.__file__)'"
@query "python3 --version"

## Git State
@query "git branch --show-current"
@query "git log --oneline -5"
@query "git status --short"

## Ports
@read .env key="API_PORT" fallback="3000"

## Last Session
@waypoint ttl=86400
@memory query="smoke test" scope=perseus k=2
