@perseus v0.4

@prompt
Adapter conformance fixture for the Codex profile.
@end

# Adapter Fixture: codex

## Profile
@read pack.yaml path="profile" fallback="codex"

## Assistant
@read pack.yaml path="renders.0.assistant" fallback="codex"

## Expected output
@read expected_output fallback="AGENTS.md"
