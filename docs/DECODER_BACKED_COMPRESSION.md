# Decoder-backed context compression

Status: initial serving slice

Perseus treats selective recall as a lossy **serving** operation, not as a
replacement for stored memory. The prompt may receive a compact explanation or
omit a memory entirely, but the source representation remains available in
Perseus Vault.

## Retention rule

Under a tight recall budget, load-bearing memory outranks ordinary relevance.
The initial policy recognizes these categories:

- `correction`
- `keystone`
- `constraint`
- `contradiction`
- `policy`
- `prohibition`

The categories are deliberately conservative. They identify details whose loss
could change behavior, violate an operator instruction, or hide a known error.
The policy affects only prompt-serving order; it does not rewrite Vault ranking,
authorization, decay, or stored content.

## The decoder contract

When a memory is shortened or omitted, the serving diagnostic retains a
content-free decoder reference containing:

- the Vault entity ID;
- its `(category, key)` address;
- source evidence IDs, when available;
- external references, when available.

The reference is not an access grant. A later drill-down must fetch the original
entity through the normal Vault authorization path.

Oversized explanations are created on a shallow copy of the hit. The source
`MemoryHit` is never mutated by prompt serving, so the full content remains
available to a later fetch in the same process.

## Current diagnostic

When budget pressure occurs, rendered context includes a non-visible trace:

```html
<!-- recall-budget: included=mem-a trimmed=mem-b demoted=mem-a decoder_ids=mem-b -->
```

This is intentionally an ID-level trace rather than a second content channel.
It exposes where to look without defeating the budget or leaking omitted
memory text into the prompt.

## Next evaluation slice

The next step is a semantic-density benchmark. It should compare compressed and
uncompressed serving on:

- task-resumption success;
- exact-fact accuracy;
- correction/prohibition retention;
- false-memory rate;
- source/provenance recovery;
- prompt characters and token accounting.

Token reduction alone is not a quality metric: deleting inconvenient facts is
an easy way to achieve a high ratio.

See also:

- [`selective-recall-budget.md`](selective-recall-budget.md)
- [`served-memory-rendering.md`](served-memory-rendering.md)
- [`context-decision-record.md`](context-decision-record.md)
- `ROADMAP.md` Phase 21B.8

Regression coverage: `tests/test_recall_budget.py`.

Language note: “decoder” here means the evidence-backed drill-down path, not a
claim that a lossy natural-language summary can be perfectly inverted.
