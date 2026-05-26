# Cited Synthesis

This synthesis surface keeps Perseus resolver-first. The new synthesis surface is a bounded
curator layer for cases where Perseus can add value before the consuming
assistant sees the context: compression, cross-source consistency, and stable
handoff claims.

The operating rule is strict:

> The LLM is a drafter, not an authority. No citation, no claim.

Contradiction checks are useful, but secondary. A generated claim only survives
when it includes at least one exact quote from a cited source line range. Invalid
or uncited claims are dropped.

## Command

```bash
perseus synthesize "What is the next allowable action?" \
  --source ROADMAP.md \
  --source HANDOFF.md
```

Without `--llm`, the command prints the source-bundled prompt and does not
generate claims.

```bash
perseus synthesize "What is the next allowable action?" \
  --source ROADMAP.md \
  --source HANDOFF.md \
  --llm ollama \
  --enable-generation
```

LLM drafting is disabled by default. Enable it per run with
`--enable-generation` or persistently with:

```yaml
generation:
  enabled: true
```

## JSON Contract

```json
{
  "version": "v1.0.0-cited-synthesis",
  "question": "What is the next allowable action?",
  "generated": true,
  "claims": [
    {
      "text": "The next action is the resolver/generator decision gate.",
      "citations": [
        {
          "source_id": "src1",
          "path": "/workspace/ROADMAP.md",
          "label": "ROADMAP.md",
          "line_start": 640,
          "line_end": 666,
          "quote": "treating generation as an explicit opt-in product pivot"
        }
      ]
    }
  ],
  "dropped_claims": [],
  "source_errors": [],
  "sources": [],
  "guardrails": {
    "citation_required": true,
    "exact_quote_required": true,
    "uncited_claims_dropped": true,
    "model_failure_leaves_render_unchanged": true
  }
}
```

The `claims` array is the only trusted generated surface. `raw_response`, when
present, is diagnostic output from the model and must not be treated as accepted
context.

## Non-Goals

- Do not explain obvious single-source values.
- Do not replace resolved directive output.
- Do not add render-time generated sections until the command surface proves
  useful.
- Do not treat confidence scores as a substitute for citation validation.
