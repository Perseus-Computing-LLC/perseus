@perseus v0.4

@prompt
This is a demo workspace for the Perseus local-cli example.
All values below are resolved live — trust them.
@end

# Local CLI Demo — @date format="YYYY-MM-DD HH:mm z"

## Last Checkpoint
@waypoint ttl=86400

## Git State
@query "git log --oneline -3" @cache session

## Python Version
@query "python3 --version" @cache session

## Perseus Version
@query "perseus --version" @cache session
