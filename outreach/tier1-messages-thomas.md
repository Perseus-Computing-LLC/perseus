# Founder outreach drafts

**Status:** Internal claims-safe draft. These messages intentionally use no unsupported
metrics or customer-performance claims. Replace only with evidence from the
current claims registry and a linked method before sending.

## Short introduction

I built Perseus to put reviewed workspace context in front of an AI assistant
before the session begins. It renders selected files, services, sessions, and
task notes into ordinary markdown, and it can expose a versioned local MCP
contract when live state is needed.

The interesting question is not whether a universal speed or concurrency claim
sounds impressive. It is whether a team can inspect the inputs, reproduce the
result, and set a useful trust boundary around the assistant's context.

Site: https://perseus.observer
Repository: https://github.com/Perseus-Computing-LLC/perseus

## Technical feedback request

Would you be willing to look at the adapter/MCP integration shape? I am
especially interested in portability, explicit unavailable states, and what
review evidence you would require before using a context renderer in a real
workflow.

## Community post draft

Perseus is a local context layer for AI-assisted development. You write a
reviewed context source, render it into the file your assistant already reads,
and optionally start a local MCP server for selected live checks. The source,
generated artifact, and contract tests are kept together so the boundary can be
inspected instead of inferred from a demo.

Feedback on the integration contract is welcome. Please use synthetic or
approved fixtures; do not send secrets or controlled data.
