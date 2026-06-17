# Perseus → Hermes context engine

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) **context engine**
plugin that wires Perseus in as the agent's pre-context layer:

- Injects live Perseus context (`perseus doctor --json`, `.perseus/context.md`)
  into the system prompt at session start.
- Delegates conversation compaction to Hermes' built-in `ContextCompressor`.
- Exposes a `perseus_grep` tool so the model can search the injected context.
- Falls back gracefully (no-ops) when the Perseus CLI isn't installed.

## Install

Drop the plugin into the Hermes agent's `plugins/context_engine/` directory
(as `perseus/`), then enable the engine in `config.yaml`:

```bash
cp -r integrations/hermes-context-engine \
  "$HERMES_HOME"/plugins/context_engine/perseus
```

```yaml
# ~/.hermes/config.yaml
context:
  engine: perseus
```

The Perseus CLI (`perseus.py`) is discovered at `$HERMES_HOME/plugins/perseus/`
or `~/.hermes/plugins/perseus/`.

> **Note on `HERMES_HOME` installs:** plugins placed under a Hermes checkout's
> `plugins/` are untracked and can be removed by `hermes update` (git clean).
> Keep this directory as the source of truth and re-sync after updates, or
> install it somewhere the updater won't touch.

## Tool-schema contract (important)

`get_tool_schemas()` must return the **bare inner tool spec**:

```python
return [{"name": "perseus_grep", "description": "...", "parameters": {...}}]
```

Do **not** return a pre-wrapped OpenAI tool object
(`{"type": "function", "function": {...}}`). The Hermes harness wraps the
inner spec itself in `agent/agent_init.py`. Returning a pre-wrapped schema
double-wraps it into `function.function.name`, which strict providers
(e.g. DeepSeek) reject with:

```
HTTP 400: ... tools[N].function: missing field `name`
```

That one malformed tool aborts the **entire** request, not just the tool —
see [NousResearch/hermes-agent#47707](https://github.com/NousResearch/hermes-agent/issues/47707)
for the upstream hardening request (validate/skip nameless schemas before wrapping).
