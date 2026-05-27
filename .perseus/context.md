@perseus v0.4

# Context - @date format="YYYY-MM-DD HH:mm z"

## Persistent Memory
@mneme query="lesson preference decision reference" k=5 scope=perseus

## What's Running
@query "echo 'stale_service Up 2 hours'"

## Ports
@read .env key="API_PORT" fallback="3000"

## Last Session
@waypoint ttl=86400
@memory query="smoke test" scope=perseus k=2

