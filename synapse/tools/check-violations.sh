#!/usr/bin/env bash
# Violations Gate — pre-commit and make check integration for process violations.
#
# Reads docs/process-violations.md for current violation stats and
# .claude/violations-checkpoint.json for the last review snapshot.
#
# P100-B16: Upgraded for three-section format (📋 trigger log + 🔴 active + ✅ closed)
# with state machine (🟡→🔴→🟢) and wasted minutes tracking.
#
# Hard blocks (exit 1) when:
#   - ≥1 active violations with 🔴 status (recurring,防呆 overdue)
#   - batchesSinceLastReview >= 5 (Phase-end review overdue)
#
# Warnings (exit 0) when:
#   - 🟡 active violations >= 10 (too many unaddressed)
#   - new violations detected since last review
#
# Usage:
#   bash tools/check-violations.sh
#
# Mirrors: tools/l5-gate.sh pattern — checkpoint.json -> parse -> gate decision

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VIOLATIONS_FILE="$PROJECT_DIR/docs/process-violations.md"
CHECKPOINT="$PROJECT_DIR/.claude/violations-checkpoint.json"

red()    { echo -e "\033[31m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
yellow() { echo -e "\033[33m$1\033[0m"; }
bold()   { echo -e "\033[1m$1\033[0m"; }

# -- Parse current violations from process-violations.md --------------
parse_violations() {
  if [ ! -f "$VIOLATIONS_FILE" ]; then
    echo "MISSING"
    return
  fi

  # Extract only the index table (between "### 违纪索引" and the "> 统计" line).
  # This avoids false matches from the 防呆可行性评估 table.
  local index_section
  index_section=$(sed -n '/^### 违纪索引/,/^> 统计/p' "$VIOLATIONS_FILE" 2>/dev/null || echo "")

  # Count V-XXX entries in the index section only
  local total
  total=$(echo "$index_section" | grep -cE '^\| V-... \| ' 2>/dev/null || echo "0")

  # Count by state machine status (column 4 in new format)
  local red_active
  red_active=$(echo "$index_section" | grep -E '^\| V-... \|.*\|.*\| 🔴 \|' 2>/dev/null | wc -l | tr -d ' ')

  local yellow_active
  yellow_active=$(echo "$index_section" | grep -E '^\| V-... \|.*\|.*\| 🟡 \|' 2>/dev/null | wc -l | tr -d ' ')

  local green_closed
  green_closed=$(echo "$index_section" | grep -E '^\| V-... \|.*\|.*\| 🟢 \|' 2>/dev/null | wc -l | tr -d ' ')

  # Count guarded (✅ in last column, index section only)
  local guarded
  guarded=$(echo "$index_section" | grep -E '^\| V-... \|.*\| ✅' 2>/dev/null | wc -l | tr -d ' ')

  local unguarded
  unguarded=$((total - guarded))

  # Trigger log stats (dates may be YYYY-MM or YYYY-MM-DD)
  local trigger_count
  trigger_count=$(grep -cE '^\| 202[0-9]-[0-9]{2}' "$VIOLATIONS_FILE" 2>/dev/null || echo "0")

  # Sum wasted minutes from trigger log (column 6, after the leading |)
  local wasted_min
  wasted_min=$(grep -E '^\| 202[0-9]-[0-9]{2}' "$VIOLATIONS_FILE" 2>/dev/null | \
    awk -F'|' '{gsub(/^[ \t]+|[ \t]+$/, "", $6); sum += ($6 + 0)} END {print sum + 0}' || echo "0")

  echo "$total $red_active $yellow_active $green_closed $guarded $unguarded $trigger_count $wasted_min"
}

# -- Read checkpoint -------------------------------------------------
read_checkpoint() {
  if [ ! -f "$CHECKPOINT" ]; then
    echo "MISSING"
    return
  fi

  local last_review batches_since total_at_review
  last_review=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('lastReviewBatch', 'unknown'))" 2>/dev/null || echo "unknown")
  total_at_review=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('totalViolations', 0))" 2>/dev/null || echo "0")
  batches_since=$(python3 -c "import json; print(json.load(open('$CHECKPOINT')).get('batchesSinceLastReview', 0))" 2>/dev/null || echo "0")

  echo "${last_review}|${total_at_review}|${batches_since}"
}

# -- Main gate logic -------------------------------------------------

STATS=$(parse_violations)

if [ "$STATS" = "MISSING" ]; then
  yellow "⚠️  docs/process-violations.md not found — gate passes (no violations to check)"
  exit 0
fi

read -r TOTAL RED_ACTIVE YELLOW_ACTIVE GREEN_CLOSED GUARDED UNGUARDED TRIGGER_COUNT WASTED_MIN <<< "$STATS"
ERRORS=0
WARNINGS=0

echo ""
bold "=== 违纪门禁 (Violations Gate) ==="
echo ""

# -- Trigger log summary --
echo "--- 📋 触发日志 ---"
echo "  触发次数: $TRIGGER_COUNT  ·  浪费总计: ${WASTED_MIN} min"
echo ""

# -- Current state --
echo "--- 当前违纪状态 ---"
echo "  VIO 总计: $TOTAL  |  🔴 活跃: $RED_ACTIVE  |  🟡 观察: $YELLOW_ACTIVE  |  🟢 闭环: $GREEN_CLOSED"
echo "  已防呆: $GUARDED  |  待防呆: $UNGUARDED"
echo ""

# -- Hard gate: active 🔴 violations (advisory in P100-B16 first deployment) --
if [ "$RED_ACTIVE" -ge 1 ]; then
  echo ""
  yellow "  ┌──────────────────────────────────────────────────────────────┐"
  yellow "  │  ⚠️  ${RED_ACTIVE} 项 🔴 活跃违纪未闭环（P100-B16 首部署为警告，下批升级阻断）│"
  yellow "  ├──────────────────────────────────────────────────────────────┤"
  yellow "  │  Action:                                                    │"
  yellow "  │  1. 审查每项 🔴 违纪的根因 + 防呆方案                        │"
  yellow "  │  2. 落地防呆措施后更新状态为 🟢                               │"
  yellow "  │  3. 运行 violations-review.sh 更新 checkpoint                 │"
  yellow "  └──────────────────────────────────────────────────────────────┘"
  echo ""
  WARNINGS=$((WARNINGS + 1))
fi

# -- Warning: too many 🟡 observations --------------------------------
if [ "$YELLOW_ACTIVE" -ge 10 ]; then
  echo ""
  yellow "  ┌──────────────────────────────────────────────────────────────┐"
  yellow "  │  ⚠️  🟡 观察期违纪 ≥10 — 需逐项评估防呆可行性                   │"
  yellow "  ├──────────────────────────────────────────────────────────────┤"
  printf "  │  当前 🟡: %-2d 项 · 已防呆: %-2d / %-2d (%.0f%%)                  │\n" \
    "$YELLOW_ACTIVE" "$GUARDED" "$TOTAL" \
    "$(python3 -c "print(int($GUARDED / max($TOTAL, 1) * 100))" 2>/dev/null || echo "0")"
  yellow "  │  Action: 本 Phase 至少落地 3 项新防呆                          │"
  yellow "  └──────────────────────────────────────────────────────────────┘"
  echo ""
  WARNINGS=$((WARNINGS + 1))
fi

# -- Checkpoint comparison ------------------------------------------
CP_DATA=$(read_checkpoint)

if [ "$CP_DATA" != "MISSING" ]; then
  LAST_REVIEW=$(echo "$CP_DATA" | cut -d'|' -f1)
  TOTAL_AT_REVIEW=$(echo "$CP_DATA" | cut -d'|' -f2)
  BATCHES_SINCE=$(echo "$CP_DATA" | cut -d'|' -f3)

  echo "--- 与上次回顾对比 (${LAST_REVIEW}) ---"
  echo "  上次回顾时: $TOTAL_AT_REVIEW 项违纪"
  echo "  当前:       $TOTAL 项违纪"
  echo "  距上次回顾: ${BATCHES_SINCE} 批"

  # Detect new violations
  if [ "$TOTAL" -gt "$TOTAL_AT_REVIEW" ]; then
    NEW=$((TOTAL - TOTAL_AT_REVIEW))
    yellow "  ⚠️  +${NEW} 项新违纪自上次回顾以来"
    WARNINGS=$((WARNINGS + 1))
  fi

  # Hard gate: review overdue
  if [ "$BATCHES_SINCE" -ge 5 ]; then
    echo ""
    red "  ┌──────────────────────────────────────────────────────────────┐"
    red "  │  🚫 违纪门禁阻断 — Phase 违纪回顾逾期 (>=5 批未回顾)            │"
    red "  ├──────────────────────────────────────────────────────────────┤"
    printf "  │  距上次回顾: %-2d 批 (上限 5)                                  │\n" "$BATCHES_SINCE"
    red "  │                                                              │"
    red "  │  Action:                                                     │"
    red "  │  1. 执行 Phase 违纪回顾 (review all V-NNN items)              │"
    red "  │  2. Run: bash tools/violations-review.sh \"<Phase+N>\"        │"
    red "  │  3. Commit the review + checkpoint reset                     │"
    red "  └──────────────────────────────────────────────────────────────┘"
    echo ""
    ERRORS=$((ERRORS + 1))
  fi

  if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
    green "  ✅ 违纪门禁通过 — 无警告，无阻断"
  fi
else
  yellow "  ⚠️  .claude/violations-checkpoint.json 不存在 — 跳过对比（首次运行？）"
  yellow "     运行 violations-review.sh 初始化 checkpoint"
  echo ""

  if [ "$RED_ACTIVE" -ge 1 ]; then
    yellow "  ⚠️  ${RED_ACTIVE} 项 🔴 活跃违纪 — 需要审查"
    WARNINGS=$((WARNINGS + 1))
  fi

  if [ "$YELLOW_ACTIVE" -ge 10 ]; then
    yellow "  ⚠️  🟡 ≥10 — 需要批量评估"
    WARNINGS=$((WARNINGS + 1))
  fi
fi

# -- Per-violation detail (🔴 active, from index section only) --------
if [ "$RED_ACTIVE" -ge 1 ]; then
  echo ""
  echo "--- 🔴 活跃违纪明细 ---"
  local_idx=$(sed -n '/^### 违纪索引/,/^> 统计/p' "$VIOLATIONS_FILE" 2>/dev/null || echo "")
  echo "$local_idx" | grep -E '^\| V-... \|.*\|.*\| 🔴 \|' 2>/dev/null | while read -r line; do
    v_id=$(echo "$line" | sed 's/| V-\([0-9]*\).*/\1/')
    v_rule=$(echo "$line" | sed 's/| V-[0-9]* | \([^|]*\).*/\1/' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    echo "  🔴 V-${v_id}: ${v_rule}"
  done || echo "  (none)"
  echo ""
fi

# -- Summary --------------------------------------------------------
echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
  red "❌ 违纪门禁: $ERRORS 项硬阻断 · $WARNINGS 项警告"
  exit 1
else
  green "✅ 违纪门禁通过"
  if [ "$WARNINGS" -gt 0 ]; then
    yellow "💡 $WARNINGS 项警告（不阻断，建议关注）"
  fi
fi
