@perseus v0.8
@prompt You are exploring a project directory structure.

@list "src/perseus/"
@list "tests/" limit=15
@tree "src/perseus/directives/" depth=2
@tree "benchmark/" depth=1
@query "find src/perseus/ -name '*.py' | wc -l" timeout=5
@read path="ROADMAP.md"
@end
