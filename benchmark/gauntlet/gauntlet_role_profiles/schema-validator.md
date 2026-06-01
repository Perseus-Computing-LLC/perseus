@perseus v0.8
@prompt You are validating structured output against a JSON Schema.

@constraint
All output in this section must conform to test-schema.json.
@end
@validate schema=benchmark/gauntlet/gauntlet_role_profiles/_support/test-schema.json
@query "echo '{\"version\":\"1.0.6\",\"status\":\"ok\"}'" timeout=5
@end
@validate schema=benchmark/gauntlet/gauntlet_role_profiles/_support/test-schema.json
@query "echo '{\"version\":\"bad\",\"status\":\"ok\"}'" timeout=5
@end
