# Perseus Deployment Guide — Full Ecosystem Configuration

> *"The mirror lets Perseus face the monster clearly, without meeting her gaze."*

This guide walks through deploying every Perseus surface — context engine, Perseus Vault
memory, Guide oracle, Agora task board, Synthesis, and Prefetch cache warming — on a
Hermes Agent host. By the end, you will have a self-maintaining deployment where every
component is health-checked and wired into Hermes cron.

**Audience:** anyone running Hermes Agent who wants the full Perseus ecosystem running
autonomously on their server.

**Assumed environment:** Linux (Unraid/Docker), Hermes Agent installed, `perseus-vault`
installed, Python 3.10+ available.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Hermes Agent                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ Context   │  │ Guide   │  │ Agora    │  │ Synthesis  │ │
│  │ Engine    │  │ Suggest  │  │ Reporter │  │ Digest     │ │
│  │ (5m cron) │  │ (8am)    │  │ (9am)    │  │ (Mon 9am)  │ │
│  └────┬──────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │
│       │              │             │               │        │
│       ▼              ▼             ▼               ▼        │
│   (each renders a prompt the host agent answers with its    │
│    own model — Perseus runs no inference of its own)        │
│                           │                                │
│  ┌────────────────────────┼─────────────────────────────┐  │
│  │          Perseus Vault (MCP/stdio)                       │  │
│  │    Canonical tools → structured durable memory           │  │
│  │    Health checked by `perseus doctor`                    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                 │
│  │ Prefetch  │  │Checkpoint│  │Auto-     │                 │
│  │ Cache     │  │ (3am)    │  │update    │                 │
│  │ (30m)     │  │          │  │ (4am)    │                 │
│  └──────────┘  └──────────┘  └──────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

**Design principle:** every component has a watchdog or is self-recovering. If something
dies, it comes back without human intervention. If it stays dead, the watchdog cron
reports it.

---

## Prerequisites

Before starting, verify you have:

| Dependency | How to check | Minimum version |
|---|---|---|
| Hermes Agent | `hermes --version` | v0.14.0+ |
| Python 3 | `python3 --version` | 3.10+ |
| `pyyaml` | `python3 -c "import yaml"` | any |
| `perseus-vault` | `command -v perseus-vault` | installed and executable |


**Key files and paths** (adjust if your Hermes home differs):

| Path | Purpose |
|---|---|
| `~/.hermes/config.yaml` | Main Hermes config — MCP servers, plugins, cron |
| `~/.hermes/.env` | API keys and secrets |
| `~/.hermes/scripts/` | Cron scripts live here |
| `~/.hermes/logs/` | All Perseus component logs |
| `~/.perseus/memory/` | Perseus Vault database and local narrative support files |
| `/workspace/perseus/perseus.py` | Standalone Perseus artifact |

---

## Step 1: Perseus Vault — The Persistent Memory Backend

Perseus Vault is the sole persistent-memory backend for Perseus. It runs as a
local-first MCP server over stdio and stores structured entities, temporal
history, journal events, and retrieval indexes in its configured database.

### 1.1 Configure the canonical Vault block

Add the canonical block to `.perseus/config.yaml`:

```yaml
perseus_vault:
  enabled: true
  command: ["perseus-vault", "serve"]
  transport: stdio
```

For a Hermes MCP server entry, use the same canonical executable:

```yaml
mcp_servers:
  perseus_vault:
    command: perseus-vault
    args: [serve]
```

Do not add a second memory backend, an alternate configuration key, or a
compatibility alias. The Vault executable resolves its default database path;
set an explicit `db_path` only when the deployment requires a non-default
location.

### 1.2 Verify the binary and connection

```bash
command -v perseus-vault
perseus doctor --json
hermes mcp list | grep perseus_vault
```

The doctor report should identify the `perseus-vault` executable, the
`perseus_vault` configuration block, and the canonical health tool. A failed
connection must be visible as a diagnostic; Perseus may fall back to local
FTS5 for explicitly local directives, but it must not silently claim that
persistent Vault recall succeeded.

### 1.3 Verify render-time recall

```bash
perseus render .perseus/context.md --format markdown
```

Use the canonical directive when a source file requests persistent recall:

```text
@vault query="project architecture decisions" k=5
```

The rendered output should contain either the canonical Perseus Vault context
block or an explicit, sanitized unavailability diagnostic. Never place API
keys, passwords, tokens, or connection strings in this configuration or in a
committed deployment record.

### 1.4 Operational checks

- Keep the `perseus-vault` executable and database under the owner-managed
  deployment path.
- Preserve the existing database and rollback metadata before upgrades.
- Verify the executable version and health response after a restart.
- Treat a missing binary, failed handshake, or stale database as a deployment
  blocker rather than substituting another memory provider.

---

## Step 2: Perseus LLM Proxy (deprecated — no longer required)

> **Deprecated.** Perseus runs no inference of its own (observe model): Guide,
> Synthesis, and Perseus Vault now render prompts for the host agent to answer with the
> model it already uses, and no component calls a provider directly. This proxy
> is no longer needed for a Perseus deployment — skip this step. The section is
> retained only for operators with an existing proxy still wired into unrelated
> tooling.

The LLM proxy is a thin Python HTTP server that forwards OpenAI-compatible
`/v1/chat/completions` requests to the Anthropic API, injecting your API key.

### 2.1 Create the Proxy Script

Save as `~/.hermes/scripts/perseus-llm-proxy.py`:

```python
#!/usr/bin/env python3
"""Perseus LLM Proxy — thin OpenAI-compat forwarder to Anthropic."""
import http.server
import json
import os
import urllib.request
import urllib.error

PORT = 18080
ANTHROPIC_URL = "https://api.anthropic.com/v1/chat/completions"
ANTHROPIC_VERSION = "2023-06-01"


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[perseus-llm-proxy] {fmt % args}")

    def do_GET(self):
        if self.path in ("/health", "/v1/models"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if "/chat/completions" not in self.path:
            self.send_response(404)
            self.end_headers()
            return

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "ANTHROPIC_API_KEY not set"}).encode())
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_body = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(exc)}).encode())


def _load_env_file(path: str) -> None:
    try:
        with open(os.path.expanduser(path)) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    _load_env_file("~/.hermes/.env")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[perseus-llm-proxy] WARNING: ANTHROPIC_API_KEY not found")
    else:
        print(f"[perseus-llm-proxy] API key loaded (...{api_key[-4:]})")
    server = http.server.HTTPServer(("127.0.0.1", PORT), ProxyHandler)
    print(f"[perseus-llm-proxy] Listening on 127.0.0.1:{PORT} → Anthropic API")
    server.serve_forever()
```

### 2.2 Start the Proxy

```bash
# Start as a background process via Hermes
# (Hermes will track it; use background=true in terminal tool)
python3 ~/.hermes/scripts/perseus-llm-proxy.py &

# Or start directly:
nohup python3 ~/.hermes/scripts/perseus-llm-proxy.py \
  > ~/.hermes/logs/perseus-llm-proxy.log 2>&1 &
```

### 2.3 Create the Proxy Watchdog

Save as `~/.hermes/scripts/perseus-llm-proxy-watchdog.sh`:

```bash
#!/usr/bin/env bash
# Perseus LLM proxy watchdog — restarts proxy if health check fails.
set -euo pipefail

PORT=18080
PROXY_SCRIPT="$HOME/.hermes/scripts/perseus-llm-proxy.py"
LOG="$HOME/.hermes/logs/perseus-llm-proxy.log"

if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    exit 0
fi

echo "[$(date)] Perseus LLM proxy down — restarting"
nohup python3 "${PROXY_SCRIPT}" >> "${LOG}" 2>&1 &
echo "[$(date)] Restarted with PID $!"
```

```bash
chmod +x ~/.hermes/scripts/perseus-llm-proxy-watchdog.sh
```

### 2.4 Schedule the Proxy Watchdog

```bash
hermes cron create "every 10m" \
  --name "Perseus LLM proxy watchdog" \
  --script perseus-llm-proxy-watchdog.sh \
  --no-agent \
  --deliver local
```

### 2.5 Verify the Proxy

```bash
curl -s http://127.0.0.1:18080/health
# Expected: {"status": "ok"}
```

---

## Step 3: Perseus Context Engine

The context engine renders workspace state into `.hermes.md` / `AGENTS.md` files so
Hermes has live context at session start.

This requires the `perseus-context-engine` skill to be installed in Hermes.

### 3.1 Schedule Context Refresh

```bash
hermes cron create "every 5m" \
  --name "Perseus: refresh workspace context" \
  --skills perseus-context-engine \
  --workdir /workspace/perseus \
  --deliver local
```

**What it does:** Every 5 minutes, Hermes loads the `perseus-context-engine` skill,
runs it in the Perseus workspace, and updates the context files.

---

## Step 4: Remaining Cron Jobs

### 4.1 Checkpoint — Daily at 3 AM

Saves a recovery waypoint so session context survives crashes.

Save as `~/.hermes/scripts/perseus-checkpoint-cron.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"

if [[ -f "${PERSEUS_PY}" ]]; then
    PERSEUS_CMD=(python3 "${PERSEUS_PY}")
else
    echo "[$(date)] FATAL: cannot find /workspace/perseus/perseus.py" >&2
    exit 2
fi

# Load env
if [[ -f ~/.hermes/.env ]]; then
    set -a; source ~/.hermes/.env; set +a
fi

TIMESTAMP=$(date +%Y-%m-%dT%H%M)
TASK="auto-checkpoint: daily cron at ${TIMESTAMP}"

echo "[$(date)] Running perseus checkpoint: ${TASK}"
"${PERSEUS_CMD[@]}" checkpoint \
    --task "${TASK}" \
    --status "scheduled" \
    --notes "Automated daily checkpoint via Hermes cron (0 3 * * *)"

echo "[$(date)] Checkpoint saved OK"
```

```bash
chmod +x ~/.hermes/scripts/perseus-checkpoint-cron.sh

hermes cron create "0 3 * * *" \
  --name "Perseus daily checkpoint" \
  --script perseus-checkpoint-cron.sh \
  --no-agent \
  --deliver local
```

### 4.2 Auto-Update — Daily at 4 AM

Checks for and applies Perseus updates from git.

Save as `~/.hermes/scripts/perseus-auto-update.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"

if [[ -f "${PERSEUS_PY}" ]]; then
    PERSEUS_CMD=(python3 "${PERSEUS_PY}")
else
    echo "[$(date)] FATAL: cannot find /workspace/perseus/perseus.py" >&2
    exit 2
fi

CHECK_OUTPUT=$("${PERSEUS_CMD[@]}" update 2>&1) || true

if echo "${CHECK_OUTPUT}" | grep -q "up to date"; then
    exit 0
fi

echo "[$(date)] Updates available, applying …"
if "${PERSEUS_CMD[@]}" update --apply 2>&1; then
    echo "[$(date)] Updated successfully"
else
    echo "[$(date)] Update FAILED — check perseus update --apply manually" >&2
    exit 1
fi
```

```bash
chmod +x ~/.hermes/scripts/perseus-auto-update.sh

hermes cron create "0 4 * * *" \
  --name "Perseus auto-update" \
  --script perseus-auto-update.sh \
  --no-agent \
  --deliver local
```

### 4.3 Prefetch Cache Warmer — Every 30 Minutes

Pre-warms directive caches for all workspace context files, keeping renders fast.

Save as `~/.hermes/scripts/perseus-prefetch-warmer.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"
ERRORS=0
WARMED=0

while IFS= read -r -d '' f; do
    WORKSPACE_DIR="$(dirname "$(dirname "$f")")"
    if [[ "$f" == */AGENTS.md ]]; then
        WORKSPACE_DIR="$(dirname "$f")"
    fi
    if python3 "${PERSEUS_PY}" prefetch --workspace "${WORKSPACE_DIR}" "$f" >/dev/null 2>&1; then
        WARMED=$((WARMED + 1))
    else
        ERRORS=$((ERRORS + 1))
    fi
done < <(find /workspace -maxdepth 4 \( -path '*/.perseus/context.md' -o -name 'AGENTS.md' \) -print0 2>/dev/null)

if [ $ERRORS -gt 0 ]; then
    echo "[$(date)] Prefetch: ${WARMED}/$((WARMED + ERRORS)) ok, ${ERRORS} errors"
    exit 1
fi
exit 0
```

```bash
chmod +x ~/.hermes/scripts/perseus-prefetch-warmer.sh

hermes cron create "every 30m" \
  --name "Perseus prefetch cache warmer" \
  --script perseus-prefetch-warmer.sh \
  --no-agent \
  --deliver local
```

### 4.4 Agora Task Board Reporter — Daily at 9 AM

Summarizes the Perseus task board (open / in-progress / completed tasks).

Save as `~/.hermes/scripts/perseus-agora-reporter.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"
OUTPUT=$(cd /workspace/perseus && python3 "${PERSEUS_PY}" agora list 2>&1)

OPEN=$(echo "$OUTPUT" | awk '/^OPEN$/{found=1; next} /^IN_PROGRESS$/{found=0} found && /^task-/{count++} END{print count+0}')
IN_PROGRESS=$(echo "$OUTPUT" | awk '/^IN_PROGRESS$/{found=1; next} /^COMPLETED$/{found=0} found && /^task-/{count++} END{print count+0}')

if [ "$OPEN" -eq 0 ] && [ "$IN_PROGRESS" -eq 0 ]; then
    exit 0
fi

echo "Agora Task Board"
echo "================"
echo "Open: $OPEN  |  In Progress: $IN_PROGRESS"
echo ""
echo "$OUTPUT" | awk '/^OPEN$/,/^BLOCKED$/' | head -30
```

```bash
chmod +x ~/.hermes/scripts/perseus-agora-reporter.sh

hermes cron create "0 9 * * *" \
  --name "Perseus Agora status reporter" \
  --script perseus-agora-reporter.sh \
  --no-agent \
  --deliver local
```

### 4.5 Guide Suggest — Daily at 8 AM

Runs the Guide tool oracle on the highest-priority open task, using the LLM proxy.

Save as `~/.hermes/scripts/perseus-guide-suggest.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"
LLM_URL="${GUIDE_LLM_URL:-http://127.0.0.1:18080}"
LLM_MODEL="${GUIDE_LLM_MODEL:-claude-sonnet-4-6}"

TASK_LINE=$(cd /workspace/perseus && python3 "${PERSEUS_PY}" agora list 2>&1 | awk '/^OPEN$/{found=1; next} /^IN_PROGRESS$/{found=0} found && /^task-/{print; exit}')

if [ -z "$TASK_LINE" ]; then
    exit 0
fi

TASK_ID=$(echo "$TASK_LINE" | awk '{print $1}')
echo "Guide: analyzing ${TASK_ID}..."
echo ""

cd /workspace/perseus && python3 "${PERSEUS_PY}" suggest \
    --llm openai-compat \
    --model-url "${LLM_URL}" \
    --model "${LLM_MODEL}" \
    "${TASK_ID}: $(echo "$TASK_LINE" | cut -d' ' -f3-)" 2>&1
```

```bash
chmod +x ~/.hermes/scripts/perseus-guide-suggest.sh

hermes cron create "0 8 * * *" \
  --name "Perseus Guide suggest" \
  --script perseus-guide-suggest.sh \
  --no-agent \
  --deliver local
```

### 4.6 Synthesis Weekly Digest — Monday at 9 AM

Generates a cited summary of project changes from CHANGELOG.md and ROADMAP.md.

Save as `~/.hermes/scripts/perseus-synthesis-digest.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"
LLM_URL="${SYNTHESIS_LLM_URL:-http://127.0.0.1:18080}"
LLM_MODEL="${SYNTHESIS_LLM_MODEL:-claude-sonnet-4-6}"

cd /workspace/perseus

python3 "${PERSEUS_PY}" synthesize \
    --source CHANGELOG.md \
    --source ROADMAP.md \
    --llm openai-compat \
    --model-url "${LLM_URL}" \
    --model "${LLM_MODEL}" \
    --enable-generation \
    "What changed this week and what's coming next?" 2>&1
```

```bash
chmod +x ~/.hermes/scripts/perseus-synthesis-digest.sh

hermes cron create "0 9 * * 1" \
  --name "Perseus Synthesis weekly digest" \
  --script perseus-synthesis-digest.sh \
  --no-agent \
  --deliver local
```

---

## Step 5: Verification Checklist

Run through these checks after deployment. All should pass.

### 5.1 Core Services

```bash
# Perseus Vault
command -v perseus-vault
perseus doctor --json
# Expected: canonical perseus_vault configuration and healthy Vault diagnostics

# LLM proxy
curl -s http://127.0.0.1:18080/health
# Expected: {"status":"ok"}

# Perseus CLI
cd /workspace/perseus && python3 perseus.py --version
# Expected: perseus v1.0.N
```

### 5.2 MCP Memory Tools

```bash
hermes mcp list | grep perseus_vault
# Expected: perseus_vault ... ✓ enabled

# In a Hermes session, the canonical tools should appear:
# perseus_vault_remember, perseus_vault_recall, perseus_vault_context,
# perseus_vault_forget, perseus_vault_health, perseus_vault_stats
```

### 5.3 Cron Jobs

```bash
hermes cron list | grep -E 'Perseus|Vault'
```

All of these should show `[active]`:

| Job name | Schedule | Mode |
|---|---|---|
| Perseus: refresh workspace context | every 5m | agent |
| Perseus daily checkpoint | 0 3 * * * | no-agent |
| Perseus auto-update | 0 4 * * * | no-agent |
| Perseus prefetch cache warmer | every 30m | no-agent |
| Perseus LLM proxy watchdog | every 10m | no-agent |
| Perseus Vault health check | on demand | agent |

| Perseus Guide suggest | 0 8 * * * | no-agent |
| Perseus Synthesis weekly digest | 0 9 * * 1 | no-agent |

### 5.4 On-Demand Commands

```bash
# Guide (requires LLM proxy running)
cd /workspace/perseus
python3 perseus.py suggest --llm openai-compat \
  --model-url http://127.0.0.1:18080 \
  --model claude-sonnet-4-6 \
  "How should I add a new directive to Perseus?"

# Agora task board
python3 perseus.py agora list

# Prefetch a single file
python3 perseus.py prefetch .perseus/context.md

# Graph a context file
python3 perseus.py graph .perseus/context.md
```

### 5.5 Perseus Vault Memory Round-Trip

From a Hermes session, test the canonical memory pipeline:

```
# Save a test memory
> perseus_vault_remember with category="test", key="test-deployment",
  content="Deployment verification test"

# Recall it
> perseus_vault_recall with query="deployment verification"
```

---

## Step 6: Troubleshooting

### Perseus Vault is unavailable

```bash
perseus doctor --json
command -v perseus-vault
perseus-vault --version
```

Common causes include a missing executable, an invalid `perseus_vault.command`
value, a failed MCP handshake, or a database permission problem. Correct the
canonical configuration and rerun the doctor check; do not substitute another
memory provider.

### LLM proxy returns empty responses

The proxy forwards to Anthropic. Check:

```bash
# Is the API key valid?
grep ANTHROPIC_API_KEY ~/.hermes/.env

# Test Anthropic directly
curl -s https://api.anthropic.com/v1/chat/completions \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","max_tokens":10,"messages":[{"role":"user","content":"hello"}]}'
```

### Perseus CLI not found in cron

The cron execution environment may have a stripped PATH. **Always use the standalone
`perseus.py` artifact** (`python3 /workspace/perseus/perseus.py`) in cron scripts,
never the pip-installed binary. The standalone artifact has zero import dependencies
beyond `pyyaml`.

### Cron scripts fail silently

No-agent crons with `deliver: local` only deliver stdout. If the script has no output,
you won't see failures unless you check the cron run log:

```bash
hermes cron list | grep <job-name>
# Look for "error" in the last run status
```

### Guide/Synthesis time out

These use the LLM proxy which calls Anthropic. The default 30s timeout in Perseus may
be too short. Increase it:

```bash
# Via environment variable (checked by perseus.py's run_llm)
export PERSEUS_LLM_TIMEOUT=120

# Or in ~/.perseus/config.yaml:
# llm:
#   timeout_s: 120
```

### MCP tools not appearing

After adding `perseus_vault` to `mcp_servers:` in `config.yaml`, you need a fresh
Hermes session:

```
/new
```

Or restart the Hermes process. MCP servers connect at session start.

---

## Cron Job Reference Card

```
 TIME   │ JOB
────────┼──────────────────────────────────────────
 :00    │ Context engine refresh (every 5m)
 :05    │ Perseus Vault health check (on demand)
 :10    │ LLM proxy watchdog (every 10m)
 :30    │ Prefetch cache warmer (every 30m)
 03:00  │ Daily checkpoint
 04:00  │ Auto-update
 08:00  │ Guide suggest
 09:00  │ Agora status reporter
 09:00  │ Synthesis weekly digest (Monday only)
```

---

## See Also

- [Hermes Integration](./HERMES_INTEGRATION.md) — Perseus ↔ Hermes LLM routing
- [Container Deployment](./CONTAINER.md) — Docker / compose deployment
- [Setup & Configuration Guide](../SETUP-GUIDE.md) — Full config reference, automation, security
- [spec/components.md](../spec/components.md) — Component architecture
- [spec/integration.md](../spec/integration.md) — Adapter patterns
- [Quickstart](./quickstart.md) — First-time setup
