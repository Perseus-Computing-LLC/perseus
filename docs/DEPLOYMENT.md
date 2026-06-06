# Perseus Deployment Guide — Full Ecosystem Configuration

> *"The mirror lets Perseus face the monster clearly, without meeting her gaze."*

This guide walks through deploying every Perseus surface — context engine, Bastra Recall
(Mnēmē memory), LLM proxy, Pythia oracle, Agora task board, Synthesis, and Prefetch
cache warming — on a Hermes Agent host. By the end, you will have a self-maintaining
deployment where every component is watchdogged, health-checked, and wired into Hermes
cron.

**Audience:** anyone running Hermes Agent who wants the full Perseus ecosystem running
autonomously on their server.

**Assumed environment:** Linux (Unraid/Docker), Hermes Agent installed, Node.js 22+
available, Python 3.10+ available.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Hermes Agent                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ Context   │  │ Pythia   │  │ Agora    │  │ Synthesis  │ │
│  │ Engine    │  │ Suggest  │  │ Reporter │  │ Digest     │ │
│  │ (5m cron) │  │ (8am)    │  │ (9am)    │  │ (Mon 9am)  │ │
│  └────┬──────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │
│       │              │             │               │        │
│       ▼              ▼             ▼               ▼        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Perseus LLM Proxy (:18080)               │  │
│  │         Anthropic forwarder (watchdog 10m)            │  │
│  └────────────────────────┬─────────────────────────────┘  │
│                           │                                │
│  ┌────────────────────────┼─────────────────────────────┐  │
│  │          Bastra Recall (Mnēmē — :6723)                │  │
│  │    MCP server → 9 tools → memory vault on disk        │  │
│  │    Daemon + watchdog (5m)                             │  │
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
| Node.js | `node --version` | v22+ |
| Python 3 | `python3 --version` | 3.10+ |
| `pyyaml` | `python3 -c "import yaml"` | any |
| `ANTHROPIC_API_KEY` | `grep ANTHROPIC_API_KEY ~/.hermes/.env` | valid key (Hermes Agent prerequisite — not consumed by Perseus directly; see note below) |

> **Note:** `ANTHROPIC_API_KEY` is consumed by Hermes Agent's LLM proxy, not by Perseus directly. Perseus itself requires no API keys for core functionality. LLM-augmented features (Pythia suggestions, Mnēmē compaction, synthesis) use the provider configured in `~/.perseus/config.yaml` with their respective env vars (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`). See [QUICKSTART.md](../QUICKSTART.md) for LLM backend setup.

**Key files and paths** (adjust if your Hermes home differs):

| Path | Purpose |
|---|---|
| `~/.hermes/config.yaml` | Main Hermes config — MCP servers, plugins, cron |
| `~/.hermes/.env` | API keys and secrets |
| `~/.hermes/scripts/` | Cron scripts live here |
| `~/.hermes/logs/` | All Perseus component logs |
| `~/.hermes/bastra-vault/` | Bastra memory vault on disk |
| `/workspace/perseus/perseus.py` | Standalone Perseus artifact |

---

## Step 1: Bastra Recall — The Mnēmē Memory Backend

Bastra Recall is Perseus's persistent memory layer. It replaces the legacy
flat-file Mnēmē subsystem. The daemon serves a REST API at `:6723`; Hermes
connects via MCP to expose 9 memory tools (`mcp_bastra_recall_*`).

### 1.1 Verify the Node.js Binary

```bash
ls ~/.nvm/versions/node/v22.22.3/bin/node
# Should print the path. If missing, install Node ≥22 via nvm.
```

### 1.2 Create the Daemon Script

Save as `~/.hermes/scripts/bastra-daemon.sh`:

```bash
#!/usr/bin/env bash
# bastra-daemon.sh — start/stop/status for the bastra-recall persistent daemon
set -euo pipefail

VAULT_PATH="${BASTRA_VAULT_PATH:-$HOME/.hermes/bastra-vault}"
DAEMON_JS="/workspace/bastra-recall/packages/daemon/dist/index.js"
NODE_BIN="$HOME/.nvm/versions/node/v22.22.3/bin/node"
LOG_DIR="$HOME/.hermes/logs"
PID_FILE="/tmp/bastra-daemon.pid"
PORT="${BASTRA_HTTP_PORT:-6723}"

mkdir -p "$LOG_DIR" "$VAULT_PATH"

cmd="${1:-status}"

case "$cmd" in
  start)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "bastra-daemon: already running (pid $(cat "$PID_FILE"))"
      exit 0
    fi
    nohup env BASTRA_VAULT_PATH="$VAULT_PATH" "$NODE_BIN" "$DAEMON_JS" \
      > "$LOG_DIR/bastra-daemon.log" 2>&1 &
    echo $! > "$PID_FILE"
    for i in $(seq 1 10); do
      if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        echo "bastra-daemon: started (pid $(cat "$PID_FILE"))"
        exit 0
      fi
      sleep 1
    done
    echo "bastra-daemon: started but health check timed out (pid $(cat "$PID_FILE"))"
    exit 1
    ;;
  stop)
    if [ -f "$PID_FILE" ]; then
      pid=$(cat "$PID_FILE")
      kill "$pid" 2>/dev/null || true
      rm -f "$PID_FILE"
      echo "bastra-daemon: stopped"
    else
      echo "bastra-daemon: not running"
    fi
    ;;
  status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "bastra-daemon: running (pid $(cat "$PID_FILE"))"
      curl -sf "http://127.0.0.1:$PORT/health" 2>/dev/null && echo " (healthy)" || echo " (unhealthy)"
    else
      echo "bastra-daemon: not running"
      rm -f "$PID_FILE"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 {start|stop|status}"
    exit 1
    ;;
esac
```

```bash
chmod +x ~/.hermes/scripts/bastra-daemon.sh
```

### 1.3 Create the Daemon Watchdog

Save as `~/.hermes/scripts/bastra-daemon-watchdog.sh`:

```bash
#!/usr/bin/env bash
# Bastra daemon watchdog — restarts daemon if health check fails.
# Runs via Hermes cron (no-agent mode, every 5m).
set -euo pipefail

DAEMON_SCRIPT="$HOME/.hermes/scripts/bastra-daemon.sh"
PORT=6723

if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    exit 0  # healthy — silent
fi

# Daemon is down or unhealthy — restart it
bash "$DAEMON_SCRIPT" stop 2>/dev/null || true
bash "$DAEMON_SCRIPT" start
```

```bash
chmod +x ~/.hermes/scripts/bastra-daemon-watchdog.sh
```

### 1.4 Configure MCP in Hermes

Add to `~/.hermes/config.yaml` under `mcp_servers:`:

```yaml
mcp_servers:
  bastra-recall:
    command: /home/hermeswebui/.hermes/home/.nvm/versions/node/v22.22.3/bin/node
    args:
    - /workspace/bastra-recall/packages/daemon/dist/mcp-forwarder.js
    env:
      BASTRA_VAULT_PATH: /home/hermeswebui/.hermes/bastra-vault
      BASTRA_FORWARDER_SPAWN: '0'
    timeout: 120
```

**Important:** The `command` must be an absolute path to your Node.js binary. The
`$HOME` in cron execution may differ from your interactive shell — use the full
absolute path. Verify with `which node` or `ls ~/.nvm/versions/node/*/bin/node`.

### 1.5 Verify Bastra

```bash
# Start the daemon
bash ~/.hermes/scripts/bastra-daemon.sh start
# Expected: bastra-daemon: started (pid NNNN)

# Health check
curl -s http://127.0.0.1:6723/health
# Expected: {"ok":true,"vault_size":N,"version":"0.1.0"}

# Check MCP tools are registered
hermes mcp list | grep bastra
# Expected: bastra-recall ... ✓ enabled
```

### 1.6 Schedule the Watchdog

```bash
hermes cron create "every 5m" \
  --name "Bastra-recall daemon watchdog" \
  --script bastra-daemon-watchdog.sh \
  --no-agent \
  --deliver local
```

---

## Step 2: Perseus LLM Proxy

The LLM proxy is a thin Python HTTP server that forwards OpenAI-compatible
`/v1/chat/completions` requests to the Anthropic API, injecting your API key.
Pythia and Synthesis depend on it.

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

### 4.5 Pythia Suggest — Daily at 8 AM

Runs the Pythia tool oracle on the highest-priority open task, using the LLM proxy.

Save as `~/.hermes/scripts/perseus-pythia-suggest.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

PERSEUS_PY="/workspace/perseus/perseus.py"
LLM_URL="${PYTHIA_LLM_URL:-http://127.0.0.1:18080}"
LLM_MODEL="${PYTHIA_LLM_MODEL:-claude-sonnet-4-6}"

TASK_LINE=$(cd /workspace/perseus && python3 "${PERSEUS_PY}" agora list 2>&1 | awk '/^OPEN$/{found=1; next} /^IN_PROGRESS$/{found=0} found && /^task-/{print; exit}')

if [ -z "$TASK_LINE" ]; then
    exit 0
fi

TASK_ID=$(echo "$TASK_LINE" | awk '{print $1}')
echo "Pythia: analyzing ${TASK_ID}..."
echo ""

cd /workspace/perseus && python3 "${PERSEUS_PY}" suggest \
    --llm openai-compat \
    --model-url "${LLM_URL}" \
    --model "${LLM_MODEL}" \
    "${TASK_ID}: $(echo "$TASK_LINE" | cut -d' ' -f3-)" 2>&1
```

```bash
chmod +x ~/.hermes/scripts/perseus-pythia-suggest.sh

hermes cron create "0 8 * * *" \
  --name "Perseus Pythia suggest" \
  --script perseus-pythia-suggest.sh \
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
# Bastra daemon
curl -s http://127.0.0.1:6723/health
# Expected: {"ok":true,"vault_size":N,"version":"0.1.0"}

# LLM proxy
curl -s http://127.0.0.1:18080/health
# Expected: {"status":"ok"}

# Perseus CLI
cd /workspace/perseus && python3 perseus.py --version
# Expected: perseus v1.0.N
```

### 5.2 MCP Memory Tools

```bash
hermes mcp list | grep bastra
# Expected: bastra-recall ... ✓ enabled

# In a Hermes session, these tools should appear:
# mcp_bastra_recall_recall, mcp_bastra_recall_load_memory,
# mcp_bastra_recall_save_memory, mcp_bastra_recall_find_document,
# mcp_bastra_recall_read_document, mcp_bastra_recall_save_document,
# mcp_bastra_recall_recategorize_document, mcp_bastra_recall_move_document,
# mcp_bastra_recall_open_document
```

### 5.3 Cron Jobs

```bash
hermes cron list | grep -E 'Perseus|Bastra'
```

All of these should show `[active]`:

| Job name | Schedule | Mode |
|---|---|---|
| Perseus: refresh workspace context | every 5m | agent |
| Perseus daily checkpoint | 0 3 * * * | no-agent |
| Perseus auto-update | 0 4 * * * | no-agent |
| Perseus prefetch cache warmer | every 30m | no-agent |
| Perseus LLM proxy watchdog | every 10m | no-agent |
| Bastra-recall daemon watchdog | every 5m | no-agent |
| Perseus Agora status reporter | 0 9 * * * | no-agent |
| Perseus Pythia suggest | 0 8 * * * | no-agent |
| Perseus Synthesis weekly digest | 0 9 * * 1 | no-agent |

### 5.4 On-Demand Commands

```bash
# Pythia (requires LLM proxy running)
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

### 5.5 Bastra Memory Round-Trip

From a Hermes session, test the full memory pipeline:

```
# Save a test memory
> mcp_bastra_recall_save_memory with title="test-deployment", type="project-fact",
  summary="Deployment verification test", body="This is a test.",
  topic_path=["test"], tags=["test"], scope="test", recall_when=["testing deployment"]

# Recall it
> mcp_bastra_recall_recall with query="deployment verification"
```

---

## Step 6: Troubleshooting

### Bastra daemon won't start

```bash
# Check the log
tail -20 ~/.hermes/logs/bastra-daemon.log

# Common causes:
# 1. Node binary path wrong — verify with: ls ~/.nvm/versions/node/*/bin/node
# 2. Daemon JS missing — verify: ls /workspace/bastra-recall/packages/daemon/dist/index.js
# 3. Port in use — check: curl -s http://127.0.0.1:6723/health
```

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

### Pythia/Synthesis time out

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

After adding `bastra-recall` to `mcp_servers:` in `config.yaml`, you need a fresh
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
 :05    │ Bastra daemon watchdog (every 5m)
 :10    │ LLM proxy watchdog (every 10m)
 :30    │ Prefetch cache warmer (every 30m)
 03:00  │ Daily checkpoint
 04:00  │ Auto-update
 08:00  │ Pythia suggest
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
