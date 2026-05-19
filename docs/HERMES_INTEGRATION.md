# Hermes Integration — Perseus + NousResearch Hermes Agent

**Status:** supported in alpha v0.7+ · single-config-block · no Perseus code changes ever required after initial setup
**Audience:** anyone running [Hermes Agent](https://github.com/NousResearch/hermes-agent) who wants Perseus's LLM-augmented surfaces (Pythia oracle, Mnēmē narrative compaction, Daedalus drift detection) to route through Hermes instead of Ollama or a raw OpenAI endpoint.

---

## TL;DR — 30 seconds

```bash
# 1. Start Hermes's OpenAI-compatible server (any port, this example uses 8080)
hermes proxy start --port 8080      # OAuth provider (Claude Pro, ChatGPT Pro, SuperGrok)
# — or —
hermes serve --openai --port 8080   # any configured Hermes provider

# 2. Tell Perseus to use it (~/.perseus/config.yaml)
cat >> ~/.perseus/config.yaml <<'YAML'
llm:
  provider: hermes
  hermes_url: http://localhost:8080
  hermes_model: claude-sonnet-4.6   # or whatever Hermes is serving
  timeout_s: 60
YAML

# 3. Verify
perseus llm ping
# ✓ hermes · model=claude-sonnet-4.6 · http://localhost:8080 · 312 ms · 'pong'
```

That's the whole integration. From here, every `--llm hermes` flag on any Perseus command will route through Hermes.

---

## Why this works without a Hermes-specific provider

Hermes Agent ships an **OpenAI-compatible `/v1/chat/completions` server** ([Hermes README](https://github.com/NousResearch/hermes-agent)). Perseus's `openai-compat` provider already speaks that protocol. The `hermes` provider name is a **friendly alias** that:

1. Reads from dedicated `hermes_url` / `hermes_model` config keys (so Hermes config can coexist with other openai-compat endpoints — e.g. a llamacpp box for cheap tasks).
2. Defaults to `http://localhost:8080` (Hermes's documented default port) instead of `http://localhost:11434` (Ollama's port).
3. Reserves the namespace for a future Hermes-native provider if/when Hermes adds non-standard extensions (auth headers, model picker over the wire, tool-gateway routing).

Today the alias is a thin shim. Tomorrow it can grow without breaking anyone's config.

---

## Config reference

The full `llm:` block, with Hermes-specific keys highlighted:

```yaml
llm:
  provider: hermes              # or: ollama, openai-compat, llamacpp, daedalus
  timeout_s: 60                 # default 30; bump for slow models

  # Hermes-specific (used when provider == hermes)
  hermes_url: http://localhost:8080     # base URL, NO /v1 suffix
  hermes_model: claude-sonnet-4.6       # any model Hermes is configured to serve

  # Fallback / shared keys (used by openai-compat, llamacpp, and as fallback for hermes)
  url: http://localhost:11434
  model: mistral

  # Daedalus (Perseus's fine-tuned local model, ollama-backed)
  daedalus_url: http://localhost:11434
  daedalus_model: perseus-daedalus
```

**Gotcha:** the `url` field is the **base** URL. Perseus appends `/v1/chat/completions` itself. If you set `hermes_url: http://localhost:8080/v1` the request will hit `http://localhost:8080/v1/v1/chat/completions` and fail. Strip the `/v1` suffix.

---

## Which Perseus surfaces actually use the LLM?

Most of Perseus is deterministic and doesn't need an LLM at all. The LLM-augmented surfaces are:

| Surface | Command | LLM use |
|---|---|---|
| **Pythia oracle** | `perseus suggest "<task>" --llm hermes` | Generates the recommendation when the deterministic rules can't pick a clear winner |
| **Mnēmē compact** | `perseus memory compact --llm hermes` | Rewrites the narrative into tighter prose (deterministic falls back if LLM unavailable) |
| **Mnēmē update** | `perseus memory update --llm hermes` | Optional polish over the deterministic distillation |
| **Mnēmē query** | `perseus memory query "<question>" --llm hermes` | Answers questions over the narrative (deterministic grep fallback otherwise) |
| **Daedalus drift** (Phase 9) | `perseus oracle drift --llm hermes` | Reserved for future LLM explanation; current drift reporting is deterministic/JSON-first |

Everything else — rendering, checkpoints, federation, health, inbox, serve, agora — runs without ever touching an LLM. You can use Perseus end-to-end with no LLM configured at all.

---

## `perseus llm ping` — the diagnostic command

```bash
perseus llm ping
perseus llm ping --provider hermes
perseus llm ping --provider hermes --url http://other-host:8080
perseus llm ping --provider hermes --model claude-opus-4.6
```

Sends a one-word prompt ("Reply with the single word: pong.") through the configured provider. Reports:

- **Success:** `✓ <provider> · model=<model> · <url> · <ms> ms · '<preview>'` (exit 0)
- **Transport failure:** `✗ <provider> · <url> · <ms> ms · <error>` (exit 2)
- **Unsupported provider:** `✗ unsupported provider: <name>` (exit 2)

Use it in scripts, CI, or `@health` checks. Use it before opening an issue — if `ping` fails, the bug is in your environment; if `ping` succeeds but `suggest` doesn't, the bug is in Perseus.

---

## Per-invocation overrides

Every Perseus command that takes `--llm` also takes `--model` and `--model-url` for ad-hoc routing without editing config:

```bash
# One-off route to a different Hermes box
perseus suggest "debug failing test" \
  --llm hermes \
  --model-url http://gpu-box.lan:8080 \
  --model deepseek-coder-v3

# Route Mnēmē compaction to a heavier model than your default
perseus memory compact --llm hermes --model claude-opus-4.6
```

These flags do **not** persist; for permanent changes, edit `~/.perseus/config.yaml`.

---

## Auth (or lack thereof)

**Today:** Perseus does not send an `Authorization` header. This matches Hermes's localhost-only default posture: Hermes binds to `127.0.0.1` with no auth, and Perseus on the same box reaches it with no auth.

**If you put Hermes behind a reverse proxy with auth:** Perseus needs a code change (one field added to `run_llm`'s `Request(...)` construction). File an issue tagged `provider-hermes-auth` and it'll get scoped as a small task. The hook is intentionally trivial — auth header support is ~10 LoC + one test.

---

## Cross-host topology

The example assumes Perseus and Hermes on the same machine. They don't have to be:

| Topology | Hermes side | Perseus side |
|---|---|---|
| **Same box** | `hermes proxy start --port 8080` | `hermes_url: http://localhost:8080` |
| **Mac → Linux box on LAN** | `hermes proxy start --host 0.0.0.0 --port 8080` | `hermes_url: http://hermes-box.lan:8080` |
| **Mac → Linux via SSH tunnel** | `hermes proxy start --port 8080` (on remote) + `ssh -L 8080:localhost:8080 user@remote` | `hermes_url: http://localhost:8080` |
| **Mac → Linux via Tailscale/WireGuard** | `hermes proxy start --host 0.0.0.0 --port 8080` | `hermes_url: http://<tailscale-ip>:8080` |

The SSH-tunnel option is the simplest secure default — Hermes stays bound to localhost on the remote, the tunnel handles authn, and Perseus's config doesn't need to know where Hermes actually lives.

---

## Federation + Hermes

`@memory federation` and `perseus memory federation *` are **LLM-free**. Subscriptions read narrative files directly from disk; no model is invoked. If you want LLM-summarized federation digests, treat that as post-Phase 14 generator/curator work and file an issue tagged `federation-llm-digest`.

---

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `ping` returns `connection refused` | Hermes not running, wrong port | `hermes proxy start --port 8080` and check `lsof -i :8080` |
| `ping` returns `404 Not Found` | `hermes_url` has `/v1` suffix | Strip it — Perseus appends the path itself |
| `ping` returns `Model not found` | `hermes_model` not configured in Hermes | `hermes model` to see what's available |
| `ping` returns `timeout` | Model is slow (large prompts, GPU offload) | Bump `llm.timeout_s` to 120 or higher |
| `ping` returns empty/`> ⚠ LLM returned no response.` | Hermes returned 200 but no `choices[0].message.content` | Check Hermes logs; usually a provider misconfig on Hermes's end |
| `suggest --llm hermes` falls back to deterministic | Same as above — but Pythia is graceful by design | Run `ping` to isolate; check `~/.perseus/oracle.log` |

---

## Operational notes

- **Mnēmē auto-update at checkpoint time** is deterministic-only by design. The LLM path runs *only* when explicitly requested via `--llm` or when `memory.llm_provider` is set in config. This means `perseus checkpoint` never blocks on a network round-trip even if Hermes is misconfigured.
- **Oracle log entries created with `--llm hermes`** record `provider: hermes` and `model: <resolved-model>` in the log, so retrospective dataset exports (`perseus oracle export`) can filter by provider for training-data curation.
- **Mixing providers per command is fine.** `perseus suggest ... --llm hermes` and `perseus memory compact --llm ollama` in the same shell coexist without state issues.

---

## Roadmap touchpoints

- **Phase 9 (Daedalus v2)** — `perseus oracle drift` is implemented as a deterministic/JSON-first surface. Future LLM explanations can use `perseus llm ping` as a precondition.
- **Phase 10 (LSP)** — the LSP server (`perseus serve --lsp`) is implemented. Surfacing `llm.provider` and recent ping state in editor UI remains an optional editor enhancement.
- **Future team mode** — if/when Perseus grows a server mode for shared federation, Hermes will likely be one of the first inference paths supported via the same alias, with auth headers added.

---

## See also

- [Hermes Agent — README](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent — Quickstart](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/getting-started/quickstart.md)
- [Hermes Agent — v0.14 Foundation Release (OpenAI-compatible proxy)](https://github.com/NousResearch/hermes-agent/blob/main/RELEASE_v0.14.0.md)
- Perseus `spec/components.md` § 4 (Mnēmē) and § 6 (Pythia) for the LLM-augmented surfaces
- Perseus `README.md` § "Configuration" for the full `llm:` block
