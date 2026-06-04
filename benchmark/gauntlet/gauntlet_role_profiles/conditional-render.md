@perseus v0.8
@prompt You are testing conditional rendering with environment-driven conditions.

@if env.set HOME
@query "echo has-home" timeout=5
@endif
@if env.set NONEXISTENT_VAR_12345_XYZ
SHOULD NOT RENDER
@endif
@if env.set PATH
PATH is set — this renders.
@else
PATH would be absent — this would render instead.
@endif
@end
