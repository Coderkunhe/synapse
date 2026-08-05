#!/usr/bin/env bash
# Pitfall 自动记录 — 替代手动编辑 pitfalls.md
#
# 用法:
#   record-pitfall.sh --id PFL-XXX --title "..." --desc "..." [--cause "..."] [--fix "..."] [--severity ...] [--dry-run]
#
# D1 Scout: DG-4 🔴→🟢 (P12-B15)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$SCRIPT_DIR/.." && pwd)")"
PITFALLS_FILE="$REPO_ROOT/synapse/docs/pitfalls.md"

# Defaults
PFL_ID=""
TITLE_STR=""
DESC_STR=""
CAUSE_STR=""
FIX_STR=""
SEVERITY="🔴"
STATUS_STR="🔴 待修复"
PITFALL_DATE="${SYNAPSE_PITFALL_DATE:-$(date +%Y-%m-%d)}"
DRY_RUN=false

usage() {
  echo "Usage: record-pitfall.sh --id <PFL-XXX> --title <title> --desc <description> [options]"
  echo ""
  echo "Required:"
  echo "  --id PFL-XXX        Pitfall ID (e.g., PFL-128)"
  echo "  --title TITLE       One-line title"
  echo "  --desc DESCRIPTION  What happened"
  echo ""
  echo "Options:"
  echo "  --severity S        Severity (default: 🔴)"
  echo "  --date YYYY-MM-DD   Discovery date (default: today)"
  echo "  --cause CAUSE       Root cause analysis"
  echo "  --fix FIX           Fix direction"
  echo "  --status STATUS     Initial status (default: 🔴 待修复)"
  echo "  --dry-run           Preview entry without writing"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --id) PFL_ID="$2"; shift 2 ;;
    --title) TITLE_STR="$2"; shift 2 ;;
    --desc) DESC_STR="$2"; shift 2 ;;
    --severity) SEVERITY="$2"; shift 2 ;;
    --date) PITFALL_DATE="$2"; shift 2 ;;
    --cause) CAUSE_STR="$2"; shift 2 ;;
    --fix) FIX_STR="$2"; shift 2 ;;
    --status) STATUS_STR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

# Validate required
if [[ -z "${PFL_ID:-}" || -z "${TITLE_STR:-}" || -z "${DESC_STR:-}" ]]; then
  echo "ERROR: --id, --title, and --desc are required"
  usage
fi

# Validate PFL ID format
if [[ ! "$PFL_ID" =~ ^PFL-[0-9]+$ ]]; then
  echo "ERROR: Invalid PFL ID format: $PFL_ID (expected PFL-XXX)"
  exit 1
fi

# Check for duplicates
if grep -q "^### $PFL_ID " "$PITFALLS_FILE" 2>/dev/null; then
  echo "ERROR: $PFL_ID already exists in pitfalls.md"
  exit 1
fi

# Find next available PFL ID as suggestion
LAST_PFL=$(grep -oE 'PFL-[0-9]+' "$PITFALLS_FILE" | sort -t'-' -k2 -n | tail -1)
NEXT_NUM=$(echo "$LAST_PFL" | sed 's/PFL-//')
NEXT_NUM=$((NEXT_NUM + 1))
SUGGESTED="PFL-$(printf "%03d" "$NEXT_NUM")"

# Build entry using a temp file to avoid string escaping issues
build_entry() {
  local tmp="$1"
  {
    echo ""
    echo "### $PFL_ID — $TITLE_STR $STATUS_STR"
    echo ""
    echo "**踩坑日期**：${PITFALL_DATE}（P12 狗粮发现）· **状态**：${STATUS_STR} · **严重度**：${SEVERITY}"
    echo ""
    echo "**现象**：${DESC_STR}"
    if [[ -n "${CAUSE_STR:-}" ]]; then
      echo ""
      echo "**根因**：${CAUSE_STR}"
    fi
    if [[ -n "${FIX_STR:-}" ]]; then
      echo ""
      echo "**修复方向**："
      echo "1. ${FIX_STR}"
    fi
    echo ""
    echo "---"
  } > "$tmp"
}

ENTRY_TMP=$(mktemp)
build_entry "$ENTRY_TMP"

if $DRY_RUN; then
  echo "=== DRY RUN ==="
  cat "$ENTRY_TMP"
  echo "=== Would append to: $PITFALLS_FILE ==="
  echo "Next available PFL ID: $SUGGESTED (current last: $LAST_PFL)"
  rm -f "$ENTRY_TMP"
  exit 0
fi

# Find insertion point after "## 未闭环条目" header
INSERT_LINE=$(awk '/^## 未闭环条目/{found=1; next} found && /^### PFL-/{print NR; exit}' "$PITFALLS_FILE")

if [[ -z "${INSERT_LINE:-}" ]]; then
  INSERT_LINE=$(awk '/^## 未闭环条目/{print NR+1; exit}' "$PITFALLS_FILE")
fi

if [[ -z "${INSERT_LINE:-}" || "$INSERT_LINE" -le 1 ]]; then
  echo "ERROR: Could not find '## 未闭环条目' section in pitfalls.md"
  rm -f "$ENTRY_TMP"
  exit 1
fi

# Insert the entry
RESULT_TMP=$(mktemp)
head -n $((INSERT_LINE - 1)) "$PITFALLS_FILE" > "$RESULT_TMP"
cat "$ENTRY_TMP" >> "$RESULT_TMP"
tail -n +$INSERT_LINE "$PITFALLS_FILE" >> "$RESULT_TMP"
mv "$RESULT_TMP" "$PITFALLS_FILE"
rm -f "$ENTRY_TMP"

echo "OK: $PFL_ID recorded in pitfalls.md"
echo "  Title: $TITLE_STR"
echo "  Next available: $SUGGESTED"
