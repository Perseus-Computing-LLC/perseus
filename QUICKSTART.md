# Perseus Quickstart

## 30-Second Install

```bash
pip install perseus-ctx
cd your-project
perseus quickstart
```

That's it. Perseus scans your project, creates a context template, and verifies
everything works. If you have an LLM key in your environment (Gemini, Groq,
OpenAI, or DeepSeek), it's auto-detected and configured for Pythia suggestions
and Synthesis.

## What Just Happened

1. **Workspace detected** — Perseus found your git repo root (or current directory)
2. **Context template created** — `.perseus/context.md` with `@skills`, `@services`,
   `@query`, and `@session` directives
3. **Config written** — `.perseus/config.yaml` with the `balanced` permission
   profile (safe for AI-agent workspaces)
4. **First render verified** — all directives resolved successfully
5. **(Optional) LLM configured** — if you chose a free backend during the prompt,
   Perseus is ready for `perseus suggest` and `perseus synthesize`

## Setting Up a Free LLM Backend

Pythia (task suggestions) and Synthesis (cited claims from source files) need an
LLM. Perseus supports several free options:

### Option 1: Gemini Free Tier (recommended)

No credit card required. 15 requests per minute.

```bash
# 1. Get an API key at https://aistudio.google.com/apikey
# 2. Export it
export GEMINI_API_KEY="your-key-here"

# 3. Re-run quickstart — it auto-detects the key
perseus quickstart
```

Perseus adds to `.perseus/config.yaml`:
```yaml
generation:
  enabled: true
  model: gemini-2.5-flash
  provider: openai-compat
llm:
  provider: openai-compat
  model: gemini-2.5-flash
  url: https://generativelanguage.googleapis.com/v1beta
```

### Option 2: Groq Free Tier

No credit card. Very fast inference.

```bash
export GROQ_API_KEY="your-key-here"
perseus quickstart
```

### Option 3: Local llama.cpp (fully offline)

No network. Fully private. Requires llama.cpp server running locally.

```bash
# Install llama.cpp
brew install llama.cpp                    # macOS
# or: apt install llama-cpp               # Linux

# Download a model
llama-cli download llama-3.2-3b

# Start the server (OpenAI-compatible API)
llama-server -m llama-3.2-3b.Q4_K_M.gguf --port 8080

# Configure Perseus
perseus quickstart                        # choose option [4]
```

Your config will be:
```yaml
generation:
  enabled: true
  model: llama-3.2-3b
  provider: llamacpp
llm:
  provider: llamacpp
  model: llama-3.2-3b
  url: http://127.0.0.1:8080
```

### Option 4: Skip and Configure Later

Edit `.perseus/config.yaml` manually, or re-run `perseus quickstart` later.

## Next Steps

| Command | What it does |
|---------|-------------|
| `perseus render .perseus/context.md` | Refresh rendered context |
| `perseus serve` | Start LSP for your editor (Claude Code, Cursor, etc.) |
| `perseus watch` | Auto-refresh context when sources change |
| `perseus suggest "fix the login bug"` | Get ranked tool/skill suggestions |
| `perseus synthesize "What's the auth flow?" --source src/auth.py` | Draft cited synthesis claims |
| `perseus doctor` | Health check — config, LLM, cache, sessions, directives |
| `perseus checkpoint --task "my work" --status "in progress"` | Save a session checkpoint |
| `perseus memory update` | Update Mnēmē project narrative |
| `perseus trust` | Show effective permission profile |
| `perseus --help` | Full command reference |

## Editor Integration

For full wiring instructions — MCP server, editor hooks, live auto-refresh,
systemd timers, cron, context packs, and trust configuration — see
**[WIRING.md](./WIRING.md)**.

### Quick Editor Hooks

### Claude Code / Cursor / Copilot / Gemini CLI

```bash
perseus install --target claude-code
# or: cursor, copilot, gemini-cli
```

This installs hooks so your AI assistant gets fresh Perseus context at session
start.

### MCP Server

```bash
perseus mcp config    # Print MCP client config for Claude Desktop, Cursor, etc.
perseus mcp serve     # Run as an MCP server over stdio
```

## CI/CD Integration

Add to your CI pipeline (GitHub Actions, etc.):

```yaml
- name: Refresh Perseus context
  run: perseus render .perseus/context.md --output .hermes.md --strict
```

The `--strict` flag fails the build if any directive emits a warning.

## Troubleshooting

```bash
# Check everything
perseus doctor

# Verify LLM
perseus llm ping

# Check permission profile
perseus trust

# Recover from last checkpoint
perseus recover
```

## Manual Config

If you prefer to configure manually instead of using `perseus quickstart`:

```bash
perseus init                # Scaffold .perseus/context.md
# Edit .perseus/context.md  # Add your project-specific directives
perseus render .perseus/context.md  # Verify it works
```

Then create `.perseus/config.yaml`:
```yaml
render:
  allow_query_shell: false
permissions:
  profile: balanced
generation:
  enabled: true
  model: gemini-2.5-flash
llm:
  provider: openai-compat
  model: gemini-2.5-flash
  url: https://generativelanguage.googleapis.com/v1beta
```
