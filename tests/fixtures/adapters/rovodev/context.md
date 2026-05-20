@perseus v0.4

@prompt
Adapter conformance fixture for the Rovo Dev profile.
@end

# Adapter Fixture: rovodev

## Profile
@read pack.yaml path="profile" fallback="rovodev"

## Assistant
@read pack.yaml path="renders.0.assistant" fallback="rovodev"

## Expected output
@read expected_output fallback="AGENTS.md"
