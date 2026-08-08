# Context cartridges (#928)

The core repository does not contain a Transformer training or inference/KV
cache runtime. It therefore ships a deliberately explicit structural adapter,
not a false claim of learned parametric memory.

`train_context_cartridge()` creates a deterministic hash-based projection of a
bounded corpus. It preserves source entity hashes, compatibility metadata,
composition ordering, payload commitments, and a queryable term projection;
raw corpus text is not persisted. Core-loaded cartridges are marked:

```json
{
  "learned": false,
  "quality_status": "structural_only"
}
```

`load_context_cartridge()` verifies the payload commitment, and
`compose_context_cartridges()` requires compatible model/tokenizer/shape
metadata before producing a new digest. `evaluate_context_cartridge()` reports
fixture quality, storage reduction, and a deterministic throughput proxy.

A future optional backend may implement real self-study distillation and KV
prefix loading outside the core dependency set. Its manifest must provide the
actual model/tokenizer revision, architecture, objective, seed, source hashes,
quality result, and measured memory/throughput evidence before changing
`learned` to true.
