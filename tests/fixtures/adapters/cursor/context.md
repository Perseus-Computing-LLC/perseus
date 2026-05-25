@perseus v0.4

@prompt
Adapter conformance fixture for the Cursor profile.
@end

# Adapter Fixture: cursor

## Profile
@read pack.yaml path="profile" fallback="cursor"

## Assistant
@read pack.yaml path="renders.0.assistant" fallback="cursor"

## Expected output
@read expected_output fallback=".cursorrules"
