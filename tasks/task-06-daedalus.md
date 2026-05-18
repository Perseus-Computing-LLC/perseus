---
id: task-06
title: "Task 06 — Daedalus: Local Autonomous Scoring Model"
status: open
scope: large
depends_on:
  - task-02
claimed_by: null
opened: 2026-05-18
closed: null
---

# Task 06 — Daedalus: Local Autonomous Scoring Model

**Status: Open**  
**Scope: Large**  
**Depends-on: task-02** (oracle log must exist before Daedalus can be trained)

> **Do not start this task until task-02 has been in production long enough to accumulate
> labeled oracle log data.** The project owner will update status to open when ready.
> This file is here so the design intent is clear. Do not implement it speculatively.

---

## The Name

Daedalus is the master craftsman of Greek mythology — builder of the Labyrinth, creator of
Talos (the bronze giant), maker of the golden mechanical servants that operated on their own.
He is the patron of autonomous builders and the craftsman who makes other heroes possible.

In Perseus, **Daedalus is the trained intelligence that powers Pythia without a round-trip.**
Today, `perseus suggest` assembles an oracle prompt and passes it to whatever LLM is in the
session. Daedalus replaces that LLM call with a small local model, fine-tuned on accepted
oracle recommendations, that runs offline and instantly.

---

## Concept

The oracle log (`~/.perseus/oracle_log.jsonl`) built in Phase 5A captures every Pythia
recommendation — the task, the environment snapshot, the prompt, the response, and whether
it was accepted. Daedalus turns that data into a model.

The flow:

```
oracle_log.jsonl (labeled)
       │
       ▼
perseus oracle export     ← emit as fine-tuning dataset (prompt/completion pairs)
       │
       ▼
fine-tune small model     ← Mistral 7B / Phi-3-mini via Ollama or llama.cpp
       │
       ▼
perseus suggest --llm daedalus   ← routes to local fine-tuned model, no round-trip
```

---

## What Needs to Be Built

### 1. Oracle log labeling CLI

```bash
# Label a recommendation as accepted or rejected
perseus oracle accept <log-id>
perseus oracle reject <log-id>

# List recent log entries with their accepted status
perseus oracle log [--limit N] [--unlabeled]
```

Each entry in `oracle_log.jsonl` has a unique timestamp-based ID. These commands flip the
`accepted` field (`null` → `true` or `false`).

### 2. Dataset export

```bash
perseus oracle export [--output <file>] [--format jsonl|alpaca]
```

- Filters to entries where `accepted=true`
- Emits as JSONL with `prompt` / `completion` pairs (default) or Alpaca-format
- Default output: `~/.perseus/daedalus_dataset.jsonl`
- Print summary: how many accepted, rejected, unlabeled entries

### 3. `--llm daedalus` provider

When `--llm daedalus` is passed to `perseus suggest`, route to the configured Daedalus model
via Ollama. The model name is set in config:

```yaml
llm:
  daedalus_model: "perseus-daedalus"   # Ollama model name after fine-tuning
  daedalus_url: "http://localhost:11434"
```

Behavior is identical to `--llm ollama` — same request/response format, same oracle log
append. The only difference is the model name routes to the fine-tuned local model.

### 4. Config section

Add to `DEFAULT_CONFIG`:
```python
# existing llm: block gets one new key
"llm": {
    ...
    "daedalus_model": "perseus-daedalus",
}
```

---

## Design Constraints

- Single-file rule in force
- No new dependencies — fine-tuning itself happens outside Perseus (user runs Ollama);
  Perseus only handles data export and model routing
- Perseus does not train the model — it prepares the data and routes to the result
- `--llm daedalus` must fail gracefully if the model isn't available in Ollama
- Existing oracle log entries must not be modified by export (read-only operation)

---

## Acceptance Criteria

- [ ] `perseus oracle accept/reject <id>` updates `oracle_log.jsonl` correctly
- [ ] `perseus oracle log` displays recent entries with status
- [ ] `perseus oracle export` emits valid JSONL with only accepted entries
- [ ] `--format alpaca` produces valid Alpaca-format fine-tuning data
- [ ] `--llm daedalus` routes to configured Ollama model
- [ ] Graceful error when Daedalus model is not available in Ollama
- [ ] `data-model.md` and `spec/oracle.md` updated to reflect Daedalus v1
- [ ] Tests cover: labeling, export filtering, export format, provider routing, missing-model error

---

## Notes

- Perseus does not run the fine-tuning. That's a user step: take the exported dataset,
  fine-tune a small base model (Mistral 7B, Phi-3-mini), push to Ollama as `perseus-daedalus`.
  Perseus just makes the data ready and knows how to call the result.
- The first version of Daedalus will not be very good. That's expected. It gets better as
  the oracle log grows and more entries are labeled. The infrastructure matters more than
  initial model quality.
- Cross-session learning (P6.4 in the roadmap) emerges naturally from this loop — every
  accepted suggestion adds to the training set on the next export cycle.
