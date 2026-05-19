# Resolver vs Generator Decision Brief

**Date:** 2026-05-19  
**Status:** Pre-Phase 14 decision brief  
**Recommendation:** Keep Perseus a trustworthy resolver through Phase 14. Treat
Phase 15 generation as an explicit product pivot, not a natural continuation of
the current roadmap.

---

## Decision

Perseus should continue to optimize for resolved, inspectable, provenance-backed
context:

- Render directives into factual markdown.
- Validate resolved payloads before injection.
- Score and prefetch existing facts.
- Improve Pythia recommendations from observed outcomes.

Perseus should not silently become a prose generator. If Phase 15 proceeds, it
should be implemented as an opt-in, visibly labeled layer that sits beside
resolved facts rather than replacing them.

---

## Why This Matters

The current product promise is simple: Perseus reduces cold-start tax by handing
an assistant facts that were resolved before the context window. That trust
model is why workspace reads, shell execution, schemas, doctor checks, static
graphs, and prefetch gates all matter.

Generation changes that promise. It adds interpretation, synthesis, and model
failure modes to a system whose strongest property is that users can inspect
where every value came from.

This is not mainly an implementation question. It is a product identity and
trust-boundary question.

---

## Options

### Option A: Stay A Resolver

Perseus keeps generating no new context prose. It resolves, validates, ranks,
prefetches, and reports facts.

**Upside:** Highest trust, easiest testing, clearest positioning, least surprise.

**Downside:** Leaves summarization and interpretation to the consuming
assistant, which may repeat work across sessions.

### Option B: Add A Bounded Curator Layer

Perseus may produce labeled summaries or annotations, but only as an optional
section with provenance links to resolved inputs.

**Upside:** Captures some value from Mneme, Daedalus, and Pythia without
collapsing the trust model.

**Downside:** Requires evals, provenance UI, and stronger language around what
is generated versus resolved.

### Option C: Become A Generator

Perseus actively writes context prose and recommendations into the primary
assistant context.

**Upside:** More autonomous and potentially more ergonomic.

**Downside:** Blurs responsibility, increases hallucination risk, complicates
testing, and makes Perseus compete with the consuming assistant's own reasoning.

---

## Recommendation

Choose **Option A for Phase 14**.

Phase 14 should improve Pythia scoring, feedback loops, and recommendation
quality without generating new context prose. This keeps Phase 14 aligned with
the resolver identity.

If the owner wants Phase 15, choose **Option B as the first experiment**, not
Option C. The first generative surface should be explicitly labeled, opt-in, and
provenance-backed.

---

## Phase 15 Entry Criteria

Do not begin generative context work until all of these are true:

- Phase 14 recommendation learning is green and documented.
- The owner explicitly chooses a generator/curator direction.
- Generated content has a separate output section or command surface.
- Every generated claim can point back to resolved context, oracle log entries,
  Mneme narrative text, or explicit user input.
- Model failure leaves normal `perseus render` output unchanged.
- Tests include golden fixtures, provenance checks, model-unavailable behavior,
  and clear separation between resolved and generated sections.

---

## Guardrails If Generation Proceeds

- Default off: `generation.enabled: false`.
- Never replace resolved directive output with generated prose.
- Label generated sections plainly.
- Include source/provenance metadata in JSON surfaces.
- Keep schema validation available for any generated structured output.
- Reuse existing LLM routing; add no required dependency.
- Treat model output as advisory unless explicitly promoted by the user.

---

## Phase 14 Guidance

Phase 14 should stay inside the resolver boundary:

- Reinforcement signals may adjust Pythia scores.
- Online scoring may change recommendation order.
- A/B testing may compare existing recommendation candidates.
- Daedalus may score, rank, or classify.
- Daedalus should not write primary context prose.

That keeps the next phase powerful without changing what Perseus is.
