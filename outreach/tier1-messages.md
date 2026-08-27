# Tier-one outreach drafts

**Status:** Internal claims-safe drafting only. Before sending, use claims from the current
site, `claims.json`, and the release-matched benchmark reports. Do not add
unverified performance, savings, concurrency, team-size, compliance, or
production-suitability figures.

## Message principles

- Describe Perseus as a system around the model: it renders selected workspace
  context, while Vault persists memory and Ledger records evidence.
- Say what was actually observed and link the method when a measured result is
  relevant. Do not turn a draft experiment into a product guarantee.
- Ask for a bounded technical evaluation rather than implying customer results.
- Never request secrets, controlled data, or production access in an outreach
  message.

## Latent Space / AI engineering audience

**Subject:** A small context-rendering tool for assistant workflows

Perseus resolves selected project state into markdown before an assistant starts
work. It is not a model or an assistant platform; it is a local context layer
with explicit paths, commands, and trust boundaries. The repository includes a
render-to-file flow, MCP integration, and adapter fixtures for common assistant
knowledge files.

If useful, I would value feedback on the integration shape and the evidence
needed for a careful technical write-up. The current public documentation and
methodology are here:

- https://perseus.observer/
- https://github.com/Perseus-Computing-LLC/perseus

## Open-source / Python audience

**Subject:** Local, inspectable context rendering for Python workflows

Perseus turns a reviewed `.perseus/context.md` into ordinary markdown that an
assistant already knows how to read. The implementation is Python-oriented and
keeps the source, generated artifact, and contract tests together. A local
installation uses the published package version documented in the repository.

I am looking for feedback on portability, directive ergonomics, and how to make
claims reproducible—not for an endorsement or an unbounded performance claim.

## Defense and regulated-workflow audience

Perseus can help organize evidence and workspace context, but it does not grant
authority, establish an ATO, or replace a customer's security and authorization
process. Any evaluation should use approved non-sensitive fixtures, a bounded
workspace, and the evaluator's own controls.

## Follow-up questions

1. Which assistant file or MCP transport does your workflow already support?
2. Which paths and commands would you allow a local context renderer to inspect?
3. What evidence format would make a small, repeatable evaluation useful?
4. Which failure or unavailable states must be visible rather than hidden?
