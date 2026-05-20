@perseus v0.4

@prompt
Adapter conformance fixture for the Hermes profile.
@end

# Adapter Fixture: hermes

## Profile
@read pack.yaml path="profile" fallback="hermes"

## Assistant
@read pack.yaml path="renders.0.assistant" fallback="hermes"

## Expected output
@read expected_output fallback=".hermes.md"
