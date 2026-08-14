#!/usr/bin/env bash
# Violations Review Reset — call after executing a violations review to reset tracking.
#
# Reads current stats from docs/process-violations.md and writes a new
# checkpoint to .claude/violations-checkpoint.json with:
#   - lastReviewBatch = the description you passed
#   - lastReviewTimestamp = now
#   - totalViolations / recurringCount / unguardedCount = snapshot from file
#   - batchesSinceLastReview = 0 (reset)
#
# Usage:
#   bash tools/violations-review.sh "P6-B40 违纪回顾完成 — 14 项防呆评估"
#
# The updated checkpoint should be committed as part of the review commit.
#
# Mirrors: tools/l5-reset.sh — same pattern, different domain.

set -eu

DESCRIPTION="${1:-}"

if [ -z "$DESCRIPTION" ]; then
  echo "Usage: bash tools/violations-review.sh \"<描述>\""
  echo ""
  echo "Examples:"
  echo "  bash tools/violations-review.sh \"P6-B40 违纪回顾完成 — 14 项防呆评估\""
  echo "  bash tools/violations-review.sh \"P6 Phase 结束违纪回顾\""
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VIOLATIONS_FILE="$PROJECT_DIR/docs/process-violations.md"
CHECKPOINT="$PROJECT_DIR/.claude/violations-checkpoint.json"
NOW=$(date +%Y-%m-%d)

red()    { echo -e "\033[31m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
yellow() { echo -e "\033[33m$1\033[0m"; }

# ── Pre-flight: check violations file exists ──────────────────────
if [ ! -f "$VIOLATIONS_FILE" ]; then
  red "❌ docs/process-violations.md 不存在 — 无法执行违纪回顾"
  exit 1
fi

# ── Parse current stats (index section only · P100-B142 对齐 check-violations.sh) ──
# 只截「### 违纪索引」~「> 统计」区间，避免「防呆可行性评估」表误匹配（曾致 已防呆 43 vs 27）
INDEX_SECTION=$(sed -n '/^### 违纪索引/,/^> 统计/p' "$VIOLATIONS_FILE" 2>/dev/null || echo "")
TOTAL=$(echo "$INDEX_SECTION" | grep -cE '^\| V-... \| ' 2>/dev/null || echo "0")
RECURRING=$(echo "$INDEX_SECTION" | grep -cE '^\| V-... \|.*\|.*\| 🔴 \|' 2>/dev/null || true)
GUARDED=$(echo "$INDEX_SECTION" | grep -E '^\| V-... \|.*\| ✅' 2>/dev/null | wc -l | tr -d ' ')
UNGUARDED=$((TOTAL - GUARDED))

echo ""
echo "=== 违纪回顾复位 ==="
echo ""
echo "  当前违纪统计:"
echo "    总计: $TOTAL  |  复发 🔴: $RECURRING  |  已防呆 ✅: $GUARDED  |  待防呆 ⚠️: $UNGUARDED"
echo ""

# ── Previous state (for diff display) ─────────────────────────────
if [ -f "$CHECKPOINT" ]; then
  PREV_TOTAL=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('totalViolations', 0))" 2>/dev/null || echo "0")
  PREV_REC=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('recurringCount', 0))" 2>/dev/null || echo "0")
  PREV_UNG=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('unguardedCount', 0))" 2>/dev/null || echo "0")

  echo "  与上次回顾对比:"
  if [ "$TOTAL" -gt "$PREV_TOTAL" ]; then
    yellow "    违纪总数: $PREV_TOTAL → $TOTAL (+$((TOTAL - PREV_TOTAL)))"
  elif [ "$TOTAL" -lt "$PREV_TOTAL" ]; then
    green "    违纪总数: $PREV_TOTAL → $TOTAL (-$((PREV_TOTAL - TOTAL))) 🎉"
  else
    echo "    违纪总数: $TOTAL (未变化)"
  fi

  if [ "$RECURRING" -gt "$PREV_REC" ]; then
    red "    复发: $PREV_REC → $RECURRING (+$((RECURRING - PREV_REC))) ⚠️"
  elif [ "$RECURRING" -lt "$PREV_REC" ]; then
    green "    复发: $PREV_REC → $RECURRING (-$((PREV_REC - RECURRING))) 🎉"
  else
    echo "    复发: $RECURRING (未变化)"
  fi

  if [ "$UNGUARDED" -gt "$PREV_UNG" ]; then
    yellow "    待防呆: $PREV_UNG → $UNGUARDED (+$((UNGUARDED - PREV_UNG)))"
  elif [ "$UNGUARDED" -lt "$PREV_UNG" ]; then
    green "    待防呆: $PREV_UNG → $UNGUARDED (-$((PREV_UNG - UNGUARDED))) 🎉"
  else
    echo "    待防呆: $UNGUARDED (未变化)"
  fi
  echo ""
fi

# ── Write checkpoint ──────────────────────────────────────────────

python3 -c "
import json, sys
data = {
    'lastReviewBatch': '${DESCRIPTION}',
    'lastReviewTimestamp': '${NOW}',
    'totalViolations': ${TOTAL},
    'recurringCount': ${RECURRING},
    'unguardedCount': ${UNGUARDED},
    'batchesSinceLastReview': 0,
    'notes': '违纪回顾完成，计数器复位'
}
with open('${CHECKPOINT}', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
print('✅ 违纪回顾计数器复位: ${DESCRIPTION}')
print(f'   File: ${CHECKPOINT}')
print(f'   下次回顾触发条件: 复发 ≥ 3 OR 待防呆 ≥ 10 OR 累积 ≥ 5 批')
print(f'   Next: commit this reset as part of violations review')
" 2>/dev/null || {
  red "❌ Failed to write checkpoint. Is python3 available?"
  exit 1
}
