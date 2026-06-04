@perseus v0.8
@prompt You are an infrastructure auditor verifying environment state.

@env required="HOME" fallback="/root"
@env required="PATH" fallback="/usr/bin"
@env required="USER" fallback="root"
@date format="%Y-%m-%dT%H:%M:%S"
@date format="%s"
@session count=3
@waypoint ttl=3600
@skills flag_stale=true
@health
@memory mode=narrative
@query "whoami" timeout=5
@query "pwd" timeout=5
@query "uname -a" timeout=5
@read path="ROADMAP.md"
@services
@agora status=open
@inbox unread=true limit=5
@drift
@end
