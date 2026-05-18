---
id: task-02
title: "Task 02 \u2014 Phase 5: `--llm` Flag & Oracle Log"
status: completed
scope: large
depends_on: []
claimed_by: null
opened: '2026-05-18'
closed: null
---
# Task 02 — Phase 5: `--llm` Flag & Oracle Log

**Status: Completed**  
**Depends-on: None** (independent of Task 01)  
**Scope: Large** — new feature with meaningful design surface  
**Tests required: Yes** — unit tests for oracle log + argument wiring; LLM call can be mocked

---

## Goal

Pythia's alpha design is a structured prompt passed to whatever assistant is running the session.
Phase 5 makes it autonomous: `perseus suggest` can pipe the oracle prompt directly to a locally
running model, no assistant round-trip required.

This task implements the `--llm` flag and the oracle recommendation log.

---

## Part A — `--llm` Flag

### Interface

```bash
# Use Ollama (default local target)
perseus suggest "summarize arxiv papers on RAG" --llm ollama

# Specify model
perseus suggest "..." --llm ollama --model mistral

# Use llama.cpp server
perseus suggest "..." --llm llamacpp --model-url http://localhost:8080

# Use any OpenAI-compatible endpoint
perseus suggest "..." --llm openai-compat --model-url http://localhost:11434/v1 --model mistral
```

### Design

- **Ollama** is the primary target. Default URL: `http://localhost:11434`. API: POST `/api/chat`
  with `{"model": ..., "messages": [...], "stream": false}`.
- **llama.cpp server** exposes an OpenAI-compatible API at `/v1/chat/completions`. Treat it
  as `openai-compat`.
- **No new dependencies.** Use `urllib.request` (stdlib). Do not import `requests` or `httpx`.
- The LLM call should have a configurable timeout (default 30s). If it fails or times out,
  print a clear error and exit non-zero. Do not silently fall back to printing the raw prompt.
- The oracle prompt template (already in `spec/oracle.md`) is what gets sent to the model.
  The system message should be the "You are the Perseus Tool Oracle..." preamble. The user
  message is the assembled environment snapshot + task.

### Config

Add to `DEFAULT_CONFIG`:
```python
"llm": {
    "provider": "ollama",          # ollama | llamacpp | openai-compat
    "model": "mistral",
    "url": "http://localhost:11434",
    "timeout_s": 30,
}
```

The `--llm`, `--model`, and `--model-url` CLI flags override config.

---

## Part B — Oracle Recommendation Log

Every time `perseus suggest` runs (with or without `--llm`), log the interaction to
`~/.perseus/oracle_log.jsonl`. This is the seed of a future fine-tuning dataset.

### Log entry schema

```json
{
  "version": 1,
  "timestamp": "2026-05-18T14:00:00+00:00",
  "task": "summarize arxiv papers on RAG",
  "env_snapshot": {
    "skills_count": 87,
    "stale_skills_count": 3,
    "services": [{"name": "...", "status": "..."}],
    "checkpoint_age_s": 3600
  },
  "prompt": "...(full oracle prompt sent to model or assistant)...",
  "response": "...(model output, or null if no --llm)...",
  "provider": "ollama",
  "model": "mistral",
  "accepted": null
}
```

- `accepted` is `null` at log time. A future `perseus oracle accept <log-id>` command will
  flip it to `true`/`false`. Don't implement that command in this task.
- Log file should be append-only JSONL (one JSON object per line).
- If logging fails (disk full, permissions), print a warning but do not fail the suggest command.

---

## Acceptance Criteria

- [ ] `perseus suggest "task"` still works without `--llm` (existing behavior unchanged)
- [ ] `perseus suggest "task" --llm ollama` sends the oracle prompt to Ollama and prints the response
- [ ] `perseus suggest "task" --llm openai-compat --model-url <url>` works with any
      OpenAI-compatible endpoint
- [ ] Timeout is respected; failure is surfaced clearly
- [ ] Every `perseus suggest` call (with or without `--llm`) appends to `~/.perseus/oracle_log.jsonl`
- [ ] Log entries match the schema above
- [ ] No new pip dependencies (stdlib urllib only)
- [ ] LLM call is mockable in tests (accept a `_http_post` injectable or patch urllib)
- [ ] All existing tests pass

---

## Notes

- Don't implement streaming output. `stream: false` for Ollama, standard non-streaming for
  OpenAI-compat. This keeps the implementation simple and the log entry complete.
- The `env_snapshot` in the log doesn't need to be the full rendered markdown — just the
  structured summary (counts, service statuses, checkpoint age). The full prompt field
  captures the rest.
- Config for the `llm:` block should live in `~/.perseus/config.yaml` alongside the existing
  config keys. The `data-model.md` spec should be updated to show it.

---

## Completed

- Added a dedicated `llm` config block with provider, model, URL, and timeout settings.
- Extended `perseus suggest` with `--model` and `--model-url` overrides in addition to `--llm`.
- Implemented local-provider execution for `ollama`, `llamacpp`, and `openai-compat` using stdlib `urllib.request` only.
- Added clear non-zero failure behavior for unsupported providers and request failures.
- Added append-only oracle logging to `~/.perseus/oracle_log.jsonl` with task, prompt, response, provider, model, and env snapshot summary fields.
- Preserved existing no-`--llm` behavior while logging prompt-only runs with `response: null`.
- Added focused tests for provider handling, logging behavior, and failure cases.

### Notes

- The implementation keeps the existing prompt template and layers provider execution on top of it, consistent with the task notes.
- Logging failures warn without failing `perseus suggest`, as requested.
