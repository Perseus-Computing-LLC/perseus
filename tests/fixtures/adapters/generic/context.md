@perseus v0.4

@prompt
Adapter conformance fixture for the generic profile.
@end

# Adapter Fixture: generic

## Profile
@read pack.yaml path="profile" fallback="generic"

## Assistant
@read pack.yaml path="renders.0.assistant" fallback="generic"

## Expected output
@read expected_output fallback="live-context.md"
