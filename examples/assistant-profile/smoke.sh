#!/usr/bin/env bash
# Perseus assistant-profile smoke test
# Usage: bash examples/assistant-profile/smoke.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE="$SCRIPT_DIR"

if command -v perseus &>/dev/null; then
  PERSEUS="perseus"
else
  PERSEUS="python3 $REPO_ROOT/perseus.py"
fi

echo "=== Perseus assistant-profile smoke test ==="
echo ""

echo "--- 1. pack validate ---"
$PERSEUS pack validate --workspace "$WORKSPACE"

echo ""
echo "--- 2. render ---"
$PERSEUS render "$WORKSPACE/.perseus/context.md" 2>&1 | head -25

echo ""
echo "--- 3. pack show ---"
$PERSEUS pack show --workspace "$WORKSPACE" 2>&1 || true

echo ""
echo "=== smoke test complete ==="
