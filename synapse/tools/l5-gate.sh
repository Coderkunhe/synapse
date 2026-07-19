#!/usr/bin/env bash
# L5 Gate — pre-commit hook that blocks when L5 is overdue.
#
# Reads .claude/l5-checkpoint.json and exits 1 if batchesSinceLastL5 >= 2.
# This is a MECHANICAL gate: no human judgment, no skipping.
#
# Usage:
#   bash tools/l5-gate.sh          # check for synapse changes only (default)
#   bash tools/l5-gate.sh --all    # check regardless of changed files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CHECKPOINT="$PROJECT_DIR/.claude/l5-checkpoint.json"

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

# ── Only gate on synapse commits ────────────────────────
if [ "${1:-}" != "--all" ]; then
  STAGED=$(git diff --cached --name-only 2>/dev/null || true)
  SYNAPSE_FILES=$(echo "$STAGED" | grep -c "^synapse/" || true)
  if [ "$SYNAPSE_FILES" -eq 0 ]; then
    exit 0  # Not a synapse commit — skip gate
  fi
fi

# ── Read checkpoint ─────────────────────────────────────
if [ ! -f "$CHECKPOINT" ]; then
  yellow "⚠️  .claude/l5-checkpoint.json not found — assuming first batch, gate passes"
  exit 0
fi

COUNT=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('batchesSinceLastL5', 0))" 2>/dev/null || echo "0")
LAST=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('lastL5Batch', 'unknown'))" 2>/dev/null || echo "unknown")
BATCHES=$(python3 -c "import json; print(', '.join(json.load(open('$CHECKPOINT')).get('completedBatches', [])))" 2>/dev/null || echo "none")

if [ "$COUNT" -ge 2 ]; then
  echo ""
  red "┌──────────────────────────────────────────────────────────┐"
  red "│  🚫 L5 GATE BLOCKED                                       │"
  red "├──────────────────────────────────────────────────────────┤"
  printf "│  Last L5 reset:  %-40s │\n" "$LAST"
  printf "│  Batches since:  %-40s │\n" "$COUNT"
  printf "│  Unpulled:       %-40s │\n" "$BATCHES"
  red "├──────────────────────────────────────────────────────────┤"
  red "│  Action required:                                        │"
  red "│  1. Execute L5 拉通 (L1→L5)                              │"
  red "│  2. Run: bash tools/l5-reset.sh \"Bx→By 拉通完成\"        │"
  red "│  3. Commit L5 docs + checkpoint reset                    │"
  red "│  4. Retry this commit                                    │"
  red "└──────────────────────────────────────────────────────────┘"
  echo ""
  exit 1
fi

green "✅ L5 gate: ${COUNT}/2 batches since last reset (${LAST}) — pass"
exit 0
