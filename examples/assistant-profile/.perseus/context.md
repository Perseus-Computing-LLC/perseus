@perseus v0.4

@prompt
This is a demo workspace for the Perseus assistant-profile example.
It uses a Hermes profile. Swap the profile in pack.yaml to target a different assistant.
@end

# Assistant Profile Demo — @date format="YYYY-MM-DD HH:mm z"

## Last Session
@waypoint ttl=86400

## Project Memory
@memory ttl=300

## Open Tasks
@agora status=open

## Git State
@query "git log --oneline -5" @cache session
