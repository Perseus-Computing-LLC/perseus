#!/usr/bin/env bash
# =============================================================================
#  Perseus One-Shot Bootstrap
#  Live Context Engine for AI Assistants
#
#  Usage:
#    curl -sSL https://raw.githubusercontent.com/Perseus-Computing-LLC/perseus/main/scripts/bootstrap.sh | bash
#
#  What this does:
#    1. Installs system dependencies (Python 3.10+, pip)
#    2. Installs perseus-ctx via pip
#    3. Generates a .env file with required environment variables
#    4. Initializes workspace config (.perseus/config.yaml + context.md)
#    5. Verifies the installation and prints a success summary
#
#  Idempotent — safe to re-run. Existing config is never overwritten without
#  confirmation unless FORCE=1 is set.
# =============================================================================
set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { printf "${GREEN}✓${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}⚠${NC} %s\n" "$*"; }
fail() { printf "${RED}✗${NC} %s\n" "$*" >&2; exit 1; }
info() { printf "${CYAN}→${NC} %s\n" "$*"; }
header() { printf "\n${BOLD}══ %s ══${NC}\n" "$*"; }

FORCE="${FORCE:-0}"
WORKSPACE="${WORKSPACE:-$(pwd)}"

echo ""
echo "============================================"
echo "  Perseus One-Shot Bootstrap"
echo "  Live Context Engine for AI Assistants"
echo "  github.com/Perseus-Computing-LLC/perseus"
echo "============================================"

# ── Step 1: OS detection & system dependencies ─────────────────────────────
header "Step 1: System dependencies"

detect_pkg_manager() {
    if command -v apt-get &>/dev/null; then
        echo "apt"
    elif command -v yum &>/dev/null; then
        echo "yum"
    elif command -v dnf &>/dev/null; then
        echo "dnf"
    elif command -v pacman &>/dev/null; then
        echo "pacman"
    elif command -v brew &>/dev/null; then
        echo "brew"
    elif command -v apk &>/dev/null; then
        echo "apk"
    else
        echo "unknown"
    fi
}

PKG_MGR=$(detect_pkg_manager)

# Ensure Python 3.10+
install_python() {
    case "$PKG_MGR" in
        apt)
            info "Installing Python via apt-get..."
            apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv
            ;;
        yum|dnf)
            info "Installing Python via $PKG_MGR..."
            $PKG_MGR install -y python3 python3-pip
            ;;
        pacman)
            info "Installing Python via pacman..."
            pacman -Sy --noconfirm python python-pip
            ;;
        apk)
            info "Installing Python via apk..."
            apk add --no-cache python3 py3-pip
            ;;
        brew)
            info "Installing Python via Homebrew..."
            brew install python@3.12
            ;;
        *)
            info "No supported package manager detected. Checking for existing Python..."
            ;;
    esac
}

# Check existing Python
PYTHON=""
for py in python3.12 python3.11 python3.10 python3; do
    if command -v "$py" &>/dev/null; then
        ver=$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$py"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python 3.10+ not found. Attempting to install..."
    install_python
    # Re-check
    for py in python3.12 python3.11 python3.10 python3; do
        if command -v "$py" &>/dev/null; then
            ver=$("$py" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                PYTHON="$py"
                break
            fi
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    fail "Could not find or install Python 3.10+. Install it manually: https://www.python.org/downloads/"
fi
ok "Python: $($PYTHON --version)"

# Ensure pip
if ! $PYTHON -m pip --version &>/dev/null; then
    info "Installing pip..."
    $PYTHON -m ensurepip --upgrade 2>/dev/null || true
    if ! $PYTHON -m pip --version &>/dev/null; then
        fail "pip installation failed. Install it manually."
    fi
fi
ok "pip: $($PYTHON -m pip --version | awk '{print $2}')"

# ── Step 2: Install perseus-ctx ─────────────────────────────────────────────
header "Step 2: Install perseus-ctx"

# Supply-chain: allow pinning the exact version so a curl|bash install is
# reproducible and not silently exposed to a newly-published (possibly
# compromised) release. `PERSEUS_CTX_VERSION=1.0.17 curl ... | bash` pins to
# `perseus-ctx==1.0.17`; unset keeps the previous latest-floating behaviour.
PKG_SPEC="perseus-ctx"
if [ -n "${PERSEUS_CTX_VERSION:-}" ]; then
    PKG_SPEC="perseus-ctx==${PERSEUS_CTX_VERSION}"
    info "Pinning install to ${PKG_SPEC}"
fi

if command -v perseus &>/dev/null; then
    CURRENT_VER=$(perseus --version 2>/dev/null || echo "unknown")
    ok "perseus already installed: $CURRENT_VER"
    if [ "$FORCE" != "1" ]; then
        info "Skipping reinstall (use FORCE=1 to upgrade)"
    else
        info "Upgrading perseus-ctx..."
        $PYTHON -m pip install --upgrade "$PKG_SPEC"
    fi
else
    info "Installing perseus-ctx via pip..."
    $PYTHON -m pip install "$PKG_SPEC"
fi

# Verify installation
if ! command -v perseus &>/dev/null; then
    # pip may install to ~/.local/bin — ensure it's on PATH
    if [ -f "$HOME/.local/bin/perseus" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    if ! command -v perseus &>/dev/null; then
        fail "perseus installation failed. Check pip output above."
    fi
fi

PERSEUS_VER=$(perseus --version 2>/dev/null || echo "unknown")
ok "perseus: $PERSEUS_VER"

# ── Step 3: Generate .env file ──────────────────────────────────────────────
header "Step 3: Environment file (.env)"

ENV_FILE="$WORKSPACE/.env"
if [ -f "$ENV_FILE" ] && [ "$FORCE" != "1" ]; then
    ok ".env already exists — skipping (use FORCE=1 to overwrite)"
else
    info "Generating .env with required variables..."
    BOOTSTRAP_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u)
    cat > "$ENV_FILE" << ENVEOF
# =============================================================================
#  Perseus + Mneme Environment
#  Generated by perseus bootstrap — ${BOOTSTRAP_DATE}
# =============================================================================

# Required for @query, @agent, and @services command: directives in Perseus
# Without this, shell-executing directives render as disabled.
PERSEUS_ALLOW_DANGEROUS=1

# ── Optional: API Keys ─────────────────────────────────────────────────────
# Uncomment and fill in your keys. These are available to Perseus subprocesses.
# DeepSeek (used as openai-compatible provider):
# DEEPSEEK_API_KEY=sk-your-key-here

# OpenAI:
# OPENAI_API_KEY=sk-your-key-here

# Anthropic:
# ANTHROPIC_API_KEY=***-it-in-environ

# ── Optional: Mneme ────────────────────────────────────────────────────────
# Database path for Mneme (default: mneme.db in working directory)
# MNEME_DB_PATH=~/.perseus/mneme/mneme.db
ENVEOF
    ok ".env created at $ENV_FILE"
fi

# Source .env so PERSEUS_ALLOW_DANGEROUS is available immediately
set +u
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE" 2>/dev/null || true
fi
set -u
export PERSEUS_ALLOW_DANGEROUS="${PERSEUS_ALLOW_DANGEROUS:-1}"

# ── Step 4: Initialize workspace configuration ──────────────────────────────
header "Step 4: Workspace configuration"

CONFIG_DIR="$WORKSPACE/.perseus"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
CONTEXT_FILE="$CONFIG_DIR/context.md"

mkdir -p "$CONFIG_DIR"

# Create config.yaml if missing
if [ -f "$CONFIG_FILE" ] && [ "$FORCE" != "1" ]; then
    ok ".perseus/config.yaml already exists — skipping"
else
    info "Creating .perseus/config.yaml..."
    cat > "$CONFIG_FILE" << 'CONFEOF'
# Perseus workspace configuration
# Docs: https://github.com/Perseus-Computing-LLC/perseus/blob/main/SETUP-GUIDE.md

render:
  # Enable @query shell execution (REQUIRED for shell directives to work)
  allow_query_shell: true
  # Enable @agent subprocess execution
  allow_agent_shell: true
  # Enable @services HTTP health checks
  allow_remote_services_health: true
  # Enable @services command: checks
  allow_services_command: true
  # Run @services checks in parallel
  parallel_services: true
  # Timeout per service check (seconds)
  services_timeout_s: 3

trust:
  allow_query_shell: true
  allow_outside_workspace: false
  redact_secrets: true

# Mneme memory backend (optional — uncomment when mneme is installed)
# mneme:
#   enabled: true
#   transport: "stdio"
#   command: ["mneme", "--db", "~/.perseus/mneme/mneme.db"]
#   timeout_s: 10.0
#   merge_strategy: "local_first"
#   fallback_to_local: true
#   circuit_breaker:
#     threshold: 3
#     cooldown: 120
CONFEOF
    ok ".perseus/config.yaml created"
fi

# Create context.md if missing (or force overwrite)
if [ -f "$CONTEXT_FILE" ] && [ "$FORCE" != "1" ]; then
    ok ".perseus/context.md already exists — skipping"
else
    info "Creating .perseus/context.md..."
    cat > "$CONTEXT_FILE" << 'CTXEOF'
@perseus v1.0.6

@prompt
This document was rendered live by Perseus. All values below are current —
do not verify services, re-scan skills, or re-read session history. Trust the
rendered output and skip orientation. Start work immediately.
@end

# Workspace Context — @date format="YYYY-MM-DD HH:mm z"

---

## Local Services

@services
- name: Example Web App
  url: http://localhost:3000
@end

---

## Workspace State

@query "whoami" fallback="unknown user"
@query "hostname" fallback="unknown host"
@query "uname -a" fallback="unknown system"
@query "df -h / | tail -1" fallback="disk info unavailable"

---

## Long-Term Memory (Engram-rs)

@memory workspace_hash="auto" max_results=5 focus=recent
CTXEOF
    ok ".perseus/context.md created"
fi

# ── Step 5: Render to verify ────────────────────────────────────────────────
header "Step 5: Verification render"

OUTPUT_FILE="${OUTPUT_FILE:-AGENTS.md}"

info "Rendering context.md → $OUTPUT_FILE..."
if PERSEUS_ALLOW_DANGEROUS=1 perseus render "$CONTEXT_FILE" --output "$OUTPUT_FILE" 2>&1; then
    ok "Render succeeded → $OUTPUT_FILE ($(wc -l < "$OUTPUT_FILE" 2>/dev/null || echo "?") lines)"
else
    warn "Render had issues (may be expected — check $OUTPUT_FILE for details)"
fi

# ── Step 6: Success summary ─────────────────────────────────────────────────
header "Success Summary"

echo ""
printf "  ${BOLD}%-30s${NC} %s\n" "Perseus version:" "$PERSEUS_VER"
printf "  ${BOLD}%-30s${NC} %s\n" "Python:" "$($PYTHON --version 2>&1)"
printf "  ${BOLD}%-30s${NC} %s\n" "pip:" "$($PYTHON -m pip --version 2>&1 | head -1)"
printf "  ${BOLD}%-30s${NC} %s\n" "OS:" "$(uname -s) $(uname -m)"
printf "  ${BOLD}%-30s${NC} %s\n" "Workspace:" "$WORKSPACE"
printf "  ${BOLD}%-30s${NC} %s\n" ".env:" "$([ -f "$ENV_FILE" ] && echo '✓ exists' || echo '✗ missing')"
printf "  ${BOLD}%-30s${NC} %s\n" "Config:" "$([ -f "$CONFIG_FILE" ] && echo '✓ exists' || echo '✗ missing')"
printf "  ${BOLD}%-30s${NC} %s\n" "Context:" "$([ -f "$CONTEXT_FILE" ] && echo '✓ exists' || echo '✗ missing')"
printf "  ${BOLD}%-30s${NC} %s\n" "PERSEUS_ALLOW_DANGEROUS:" "${PERSEUS_ALLOW_DANGEROUS:-not set}"
printf "  ${BOLD}%-30s${NC} %s\n" "Output:" "$([ -f "$OUTPUT_FILE" ] && echo "✓ $OUTPUT_FILE" || echo '✗ not rendered')"

echo ""
echo "============================================"
echo "  ${GREEN}Perseus bootstrap complete!${NC}"
echo ""
echo "  Next steps:"
echo "    1. source .env                   # Load environment variables"
echo "    2. perseus render .perseus/context.md --output AGENTS.md"
echo "    3. cat AGENTS.md                 # Verify rendered context"
echo ""
echo "  Full docs: https://github.com/Perseus-Computing-LLC/perseus/blob/main/SETUP-GUIDE.md"
echo "============================================"
