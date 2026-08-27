# r/LocalLLaMA — Reddit draft

**Status:** Internal, claims-safe draft. Verify every statement against the
current public evidence before posting.

## Title

Perseus: local context rendering before an assistant session

## Body

Local models often need a compact, inspectable view of the workspace before
useful work can begin. Perseus takes a reviewed `.perseus/context.md`, resolves
selected inputs, and writes ordinary markdown for the assistant to read.

The design goal is explicitness: choose the files and commands, render locally,
inspect the result, and keep unavailable or blocked states visible. It can also
serve a local MCP contract when an assistant needs selected live state rather
than a pre-rendered file.

This is a tool for experimentation, not a claim that every filesystem or
workload has the same behavior. Reproduce any measured result with the linked
method and keep sensitive data out of fixtures.

Repository: https://github.com/Perseus-Computing-LLC/perseus
