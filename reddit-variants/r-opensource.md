# r/opensource — Reddit draft

**Status:** Internal, claims-safe draft. Do not add figures unless they are in
the current claims registry with a reproducible method.

## Title

Perseus: an inspectable render-to-file context layer

## Body

Perseus is a small Python-oriented tool that resolves selected project context
into markdown before an AI assistant reads it. It supports assistant-specific
output files, adapter fixtures, and a local MCP server for explicitly configured
live checks.

The repository keeps source, generated output, contract tests, and trust-boundary
documentation together. I would appreciate review of the adapter contract,
portability, and failure-state handling. This is not a universal benchmark or
production authorization claim; please test it with your own approved fixtures.

Repository: https://github.com/Perseus-Computing-LLC/perseus
