#!/usr/bin/env bash
# Perseus claude-code smoke test
# Usage: bash examples/claude-code/smoke.sh
# Renders context.md → CLAUDE.md and verifies the output is a non-empty markdown file.

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

echo "=== Perseus claude-code smoke test ==="
echo "perseus: $PERSEUS"
echo ""

echo "--- 1. version ---"
$PERSEUS --version

echo ""
echo "--- 2. render to CLAUDE.md ---"
$PERSEUS render "$WORKSPACE/.perseus/context.md" --output "$WORKSPACE/CLAUDE.md"
echo "Rendered CLAUDE.md ($(wc -l < "$WORKSPACE/CLAUDE.md") lines)"

echo ""
echo "--- 3. verify output ---"
if grep -q "Claude Code Context" "$WORKSPACE/CLAUDE.md"; then
  echo "✅ CLAUDE.md contains expected heading"
else
  echo "❌ CLAUDE.md missing expected heading" >&2
  exit 1
fi

echo ""
echo "--- 4. checkpoint ---"
$PERSEUS checkpoint \
  --task "Perseus claude-code smoke test" \
  --status "running" \
  --next "verify CLAUDE.md refresh" \
  --workspace "$WORKSPACE"

echo ""
echo "--- 5. recover ---"
$PERSEUS recover --workspace "$WORKSPACE"

echo ""
echo "--- 6. doctor ---"
$PERSEUS doctor 2>&1 || true  # exit 1 ok for missing config in demo

echo ""
echo "=== smoke test complete ==="
