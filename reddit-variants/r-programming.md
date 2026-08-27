# r/programming — Reddit draft

**Status:** Internal, claims-safe draft.

## Title

A Python build pipeline for deterministic assistant context files

## Body

Perseus resolves a context source into a normal markdown file that an assistant
can read at session start. The interesting engineering pieces are the explicit
source boundaries, generated single-file artifact, adapter conformance fixtures,
and contract checks for unavailable or blocked operations.

The integration guide documents file rendering and a local MCP server. It does
not claim that rendering creates a sandbox or that one workload's measurements
apply everywhere. Feedback on the build/test design and portability is welcome.

Repository: https://github.com/Perseus-Computing-LLC/perseus
