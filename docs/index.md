# Perseus™ Documentation

> *The mirror lets Perseus face the monster clearly, without meeting her gaze.*

Perseus is a live context engine for AI assistants. It solves the **cold-start problem**: instead of burning the first turns of every session on orientation, Perseus resolves environment state *before* it enters the context window.

---

## Where to Start

| You want to… | Go to… |
|---|---|
| Install and render your first context in 5 minutes | [Quickstart](./quickstart.md) |
| Understand what Perseus is and how it works | [README](../README.md) |
| **Full setup, config & automation guide** | **[Setup Guide](../SETUP-GUIDE.md)** |
| Wire Perseus to a specific assistant (Hermes, Codex, Claude Code, Cursor, Rovo Dev) | [Integration guide](./HERMES_INTEGRATION.md) · [spec/integration.md](../spec/integration.md) |
| Use context packs and profiles | [Context Packs](./CONTEXT_PACKS.md) |
| Understand decoder-backed memory compression | [Decoder-backed compression](./DECODER_BACKED_COMPRESSION.md) |
| Run the offline semantic-density gate | [Semantic-density benchmark](../benchmark/semantic_density/README.md) |
| Replay the serving slice against real Vault | [Real Vault density replay](../benchmark/real_vault_density/README.md) |
| Measure whether startup memory is actually saving time | [Startup-Memory Benchmark](./startup-memory-benchmark.md) |
| Deploy with Docker / run as a service | [Container deployment](./CONTAINER.md) |
| Deploy the full ecosystem on Hermes (previous Vault format, LLM proxy, crons) | [Deployment Guide](./DEPLOYMENT.md) |
| Enable cited synthesis (`@synthesize`) | [Cited Synthesis](./CITED_SYNTHESIS.md) |
| Use the trust and security model | [Spec: permissions](../spec/components.md) |
| Look up every directive | [spec/directives.md](../spec/directives.md) |
| See the config and data schemas | [spec/data-model.md](../spec/data-model.md) |
| Contribute to Perseus | [Contributing](./CONTRIBUTING.md) |
| See use cases and real-world examples | [Use cases](./use-cases.md) · [Examples](./EXAMPLES.md) |
| Review the project roadmap | [ROADMAP.md](../ROADMAP.md) |

---

## Documentation Map

```
docs/
  index.md              ← You are here — documentation hub
  quickstart.md         ← Shortest path from install to rendered context
  HERMES_INTEGRATION.md ← Hermes Agent adapter
  DEPLOYMENT.md         ← Full ecosystem deployment on Hermes
  CONTEXT_PACKS.md      ← Profiles, pack.yaml, gallery
  CONTAINER.md          ← Docker / compose deployment
  CITED_SYNTHESIS.md    ← @synthesize and cited claims
  EXAMPLES.md           ← Real-world usage patterns
  PERFORMANCE.md        ← Performance budgets and tuning
  CONTRIBUTING.md       ← How to contribute
  use-cases.md          ← Use cases by audience
  PRODUCT_CONTRACT.md   ← Product owner contract and workflows
  ip/                   ← IP portfolio

spec/                   ← Normative design specifications
  overview.md           ← Architecture overview
  components.md         ← All components in detail
  directives.md         ← Full directive reference
  pythia.md             ← Pythia (tool oracle) design
  integration.md        ← Adapter patterns and conformance matrix
  data-model.md         ← Config, checkpoint, cache schemas
```

---

## Key Concepts

**Resolve-before-context** — Perseus runs directives and hands the assistant a finished, accurate document. The assistant never sees a directive; only verified facts.

**Directives** — Annotated references in a `.md` source file (`@query`, `@read`, `@env`, `@waypoint`, `@services`, `@skills`, `@session`, …). They're resolved at render time and replaced with their live values.

**Profiles** — Named presets (`hermes`, `codex`, `claude-code`, `cursor`, `rovodev`, `generic`) that scaffold a context pack tuned for a specific assistant.

**Pythia** — The tool oracle. `perseus suggest "task"` assembles a live environment snapshot and ranks tool/skill paths for the work at hand.

**Perseus Vault** — Narrative project memory. Automatically distills checkpoints and oracle logs into a rolling project narrative (`@memory`). The optional MCP-backed Vault accelerator provides Ebbinghaus time-decay, topic trees, and semantic + BM25 hybrid search. Configure the bridge with the canonical `perseus_vault:` block; legacy configuration remains supported for compatibility. Local-only remains the zero-dependency default.

**Agora** — The async agent coordination substrate. `tasks/*.md` with YAML frontmatter; any AI contributor can pick up and work a task without synchronous handoff.

---

## Version

Current release: **v1.0.6** — All 26 phases shipped. Tests all passing.

<!-- trigger pages rebuild for funding.json -->
