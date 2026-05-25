#!/usr/bin/env bash
# Perseus — Claude Code session-start hook
# Place at: .claude/hooks/on_session_start.sh
# Claude Code runs this before every session. Perseus pre-resolves
# live workspace state into CLAUDE.md so Claude opens already oriented.

set -e

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
CONTEXT="$ROOT/.perseus/context.md"
OUTPUT="$ROOT/CLAUDE.md"

# Find Perseus
PERSEUS=""
if command -v perseus &>/dev/null; then
    PERSEUS=perseus
elif [ -f "$ROOT/perseus.py" ]; then
    PERSEUS="python3 $ROOT/perseus.py"
fi

if [ -z "$PERSEUS" ]; then
    echo "[Perseus] Not installed. Run: pip install perseus-ctx" >&2
    exit 0  # Don't block Claude — just skip
fi

if [ ! -f "$CONTEXT" ]; then
    echo "[Perseus] No .perseus/context.md found. Run: perseus init $ROOT" >&2
    exit 0
fi

echo "[Perseus] Resolving live context..."

START=$(date +%s%3N 2>/dev/null || echo 0)
$PERSEUS render "$CONTEXT" --output "$OUTPUT"
ELAPSED=$(( $(date +%s%3N 2>/dev/null || echo 0) - START ))

LINES=$(wc -l < "$OUTPUT" 2>/dev/null || echo 0)
KB=$(du -k "$OUTPUT" 2>/dev/null | cut -f1 || echo 0)

echo "[Perseus] → $LINES lines · ${KB}KB · ${ELAPSED}ms"
echo "[Perseus] Claude will open with live context — no orientation calls needed."
