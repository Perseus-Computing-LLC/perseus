#!/usr/bin/env bash
# Perseus local-cli smoke test
# Usage: bash examples/local-cli/smoke.sh
# Exercises render, checkpoint, recover, suggest, doctor.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE="$SCRIPT_DIR"

# Resolve the perseus command
if command -v perseus &>/dev/null; then
  PERSEUS="perseus"
else
  PERSEUS="python3 $REPO_ROOT/perseus.py"
fi

echo "=== Perseus local-cli smoke test ==="
echo "perseus: $PERSEUS"
echo ""

echo "--- 1. version ---"
$PERSEUS --version

echo ""
echo "--- 2. render ---"
$PERSEUS render "$WORKSPACE/.perseus/context.md" --no-shell 2>/dev/null \
  || $PERSEUS render "$WORKSPACE/.perseus/context.md" 2>&1 | head -20

echo ""
echo "--- 3. checkpoint ---"
$PERSEUS checkpoint \
  --task "Perseus local-cli smoke test" \
  --status "running" \
  --next "verify recover" \
  --workspace "$WORKSPACE"

echo ""
echo "--- 4. recover ---"
$PERSEUS recover --workspace "$WORKSPACE"

echo ""
echo "--- 5. suggest (quick) ---"
$PERSEUS suggest "how do I keep context fresh between sessions" --quick --no-services 2>&1 | head -15

echo ""
echo "--- 6. doctor ---"
$PERSEUS doctor 2>&1 || true  # exit 1 is ok for missing config in demo

echo ""
echo "=== smoke test complete ==="
