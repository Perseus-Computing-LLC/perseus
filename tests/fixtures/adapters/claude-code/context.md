@perseus v0.4

@prompt
Adapter conformance fixture for the Claude Code profile.
@end

# Adapter Fixture: claude-code

## Profile
@read pack.yaml path="profile" fallback="claude-code"

## Assistant
@read pack.yaml path="renders.0.assistant" fallback="claude-code"

## Expected output
@read expected_output fallback="CLAUDE.md"
