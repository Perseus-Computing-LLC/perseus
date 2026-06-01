@perseus v0.8
@prompt You are testing allowlisted tool execution. Note: requires tool_allowlist config.

@tool "echo 'allowed tool works'"
@tool "date -u"
@tool "wc -l ROADMAP.md"
@end
