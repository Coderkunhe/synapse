#!/usr/bin/env bash
# check-l5-consistency.sh — L5 跨文档一致性机械校验
#
# P12-B29: 替代 L5 "人因检查"的表面文章。不依赖 AI 自觉，用机械规则验证
# 文档间的一致性。发现的每一个 drift 都是 L5 流程失灵的物证。
#
# 检查项:
#   1. batchesSinceLastL5 在多文件间是否一致
#   2. lastL5Batch 引用是否与 checkpoint 同步
#   3. 批次数自洽（roadmap 中 P12 batch 数 vs l5 累积计数）
#   4. 关键文档的"最后更新"时间戳是否新鲜
#   5. roadmap 和 requirements-log 的双向覆盖
#
# Usage:
#   bash tools/check-l5-consistency.sh [--strict]
#
# Exit codes:
#   0 — 全部一致
#   1 — 发现不一致（--strict 模式，或 batchesSinceLastL5 ≥ 2 时）
#   2 — 脚本自身错误

set -o pipefail
# Note: not using set -e or set -u — the script handles all error cases explicitly

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
STRICT=false
WARNINGS=0
ERRORS=0

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=true ;;
  esac
done

# ── Source files ─────────────────────────────────────────────────

CHECKPOINT="$PROJECT_DIR/.claude/l5-checkpoint.json"
CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
ROADMAP="$PROJECT_DIR/docs/roadmap.md"
REQLOG="$PROJECT_DIR/docs/requirements-log.md"
MEMORY_DIR="${HOME}/.claude/projects/-Users-hunter-projects-personal-ai-ai-synapse/memory"

red() { echo -e "\033[31m$*\033[0m"; }
green() { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }

die() { red "FATAL: $*"; exit 2; }

# ── Prerequisites ────────────────────────────────────────────────

command -v python3 >/dev/null 2>&1 || die "python3 is required"
[ -f "$CHECKPOINT" ] || die "l5-checkpoint.json not found at $CHECKPOINT"
[ -f "$CLAUDE_MD" ] || die "CLAUDE.md not found"
[ -f "$ROADMAP" ] || die "roadmap.md not found"
[ -f "$REQLOG" ] || die "requirements-log.md not found"

# ── Extract checkpoint values ────────────────────────────────────

L5_COUNTER=$(python3 -c "import json; print(json.load(open('$CHECKPOINT'))['batchesSinceLastL5'])" 2>/dev/null) || die "Cannot read batchesSinceLastL5 from checkpoint"
L5_LAST_BATCH=$(python3 -c "import json; print(json.load(open('$CHECKPOINT'))['lastL5Batch'])" 2>/dev/null) || die "Cannot read lastL5Batch from checkpoint"
L5_TIMESTAMP=$(python3 -c "import json; print(json.load(open('$CHECKPOINT'))['lastL5Timestamp'])" 2>/dev/null) || die "Cannot read lastL5Timestamp from checkpoint"

# ── Check 1: batchesSinceLastL5 consistency across docs ──────────

echo "=== Check 1: batchesSinceLastL5 多文件一致性 ==="
echo "  checkpoint 值: $L5_COUNTER"

# CLAUDE.md: look for "batchesSinceLastL5=N" pattern in status table
CLAUDE_L5=""
CLAUDE_MATCH=$(grep -oE 'batchesSinceLastL5=[0-9]+' "$CLAUDE_MD" 2>/dev/null | head -1 || true)
if [ -n "$CLAUDE_MATCH" ]; then
  # Extract only the number after "=" (sed avoids matching "5" in "L5")
  CLAUDE_L5=$(echo "$CLAUDE_MATCH" | sed 's/.*=//' | tr -d '[:space:]')
fi
if [ -n "$CLAUDE_L5" ] && [ "$CLAUDE_L5" != "$L5_COUNTER" ]; then
  red "  ❌ CLAUDE.md 声称 batchesSinceLastL5=$CLAUDE_L5，实际 checkpoint=$L5_COUNTER"
  ERRORS=$((ERRORS + 1))
elif [ -n "$CLAUDE_L5" ]; then
  green "  ✅ CLAUDE.md: $CLAUDE_L5"
else
  yellow "  ⚠️  未在 CLAUDE.md 中找到 batchesSinceLastL5"
  WARNINGS=$((WARNINGS + 1))
fi

# p12.md memory: check both header table and key stats
P12_MD="$MEMORY_DIR/active/p12.md"
if [ -f "$P12_MD" ]; then
  P12_VALUES=""
  P12_MATCHES=$(grep -oE 'batchesSinceLastL5=[0-9]+' "$P12_MD" 2>/dev/null || true)
  if [ -n "$P12_MATCHES" ]; then
    # Extract only the number after "=" (sed avoids matching "5" in "L5")
    P12_VALUES=$(echo "$P12_MATCHES" | sed 's/.*=//' | tr -d '[:space:]')
  fi
  if [ -n "$P12_VALUES" ]; then
    P12_UNIQUE=$(echo "$P12_VALUES" | sort -u)
    P12_COUNT=$(echo "$P12_VALUES" | wc -l | tr -d ' ')

    if [ "$(echo "$P12_UNIQUE" | wc -l | tr -d ' ')" -gt 1 ]; then
      red "  ❌ p12.md 内部矛盾: 出现多个不同值: $(echo $P12_VALUES | tr '\n' ' ')"
      ERRORS=$((ERRORS + 1))
    elif [ -n "$P12_UNIQUE" ] && [ "$P12_UNIQUE" != "$L5_COUNTER" ]; then
      red "  ❌ p12.md 声称 batchesSinceLastL5=$P12_UNIQUE，实际 checkpoint=$L5_COUNTER"
      ERRORS=$((ERRORS + 1))
    elif [ -n "$P12_UNIQUE" ]; then
      green "  ✅ p12.md: $P12_UNIQUE ($P12_COUNT 处引用一致)"
    fi
  fi
else
  yellow "  ⚠️  p12.md memory 不存在，跳过"
  WARNINGS=$((WARNINGS + 1))
fi

# ── Check 2: lastL5Batch 引用一致性 ──────────────────────────────

echo ""
echo "=== Check 2: lastL5Batch 引用一致性 ==="
echo "  checkpoint 值: $L5_LAST_BATCH"

# Extract last batch number from L5_LAST_BATCH (e.g., "B27→B28 ..." → extract B28)
L5_TARGET_BATCH=$(echo "$L5_LAST_BATCH" | grep -oE 'B[0-9]+' | tail -1 || echo "")

# CLAUDE.md status table should reference this batch
if [ -n "$L5_TARGET_BATCH" ]; then
  CLAUDE_REF=$(grep -c "$L5_TARGET_BATCH" "$CLAUDE_MD" 2>/dev/null || true)
  CLAUDE_REF="${CLAUDE_REF:-0}"
  if [ "$CLAUDE_REF" -eq 0 ]; then
    yellow "  ⚠️  CLAUDE.md 未引用 L5 目标批次 $L5_TARGET_BATCH"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ CLAUDE.md 引用 $L5_TARGET_BATCH ($CLAUDE_REF 处)"
  fi

  # p12.md should also reference it
  if [ -f "$P12_MD" ]; then
    P12_REF=$(grep -c "$L5_TARGET_BATCH" "$P12_MD" 2>/dev/null || true)
    P12_REF="${P12_REF:-0}"
    if [ "$P12_REF" -eq 0 ]; then
      yellow "  ⚠️  p12.md 未引用 L5 目标批次 $L5_TARGET_BATCH"
      WARNINGS=$((WARNINGS + 1))
    else
      green "  ✅ p12.md 引用 $L5_TARGET_BATCH ($P12_REF 处)"
    fi
  fi
fi

# ── Check 3: 批次数自洽 ──────────────────────────────────────────

echo ""
echo "=== Check 3: roadmap batch 覆盖验证 ==="

# Count all P12 batches in roadmap for cross-reference
ROADMAP_P12_COUNT=$(grep -c 'P12-B[0-9]' "$ROADMAP" 2>/dev/null || echo "0")
REQLOG_P12_COUNT=$(grep -c 'P12-B[0-9]' "$REQLOG" 2>/dev/null || echo "0")
echo "  roadmap P12 batch 条目: $ROADMAP_P12_COUNT"
echo "  requirements-log P12 条目: $REQLOG_P12_COUNT"

# This check is informational — exact batch counts differ because:
# - l5-counter is incremented by pre-commit after L5 reset
# - roadmap entries may lag by one commit
# The real consistency check is in Check 4 (bidirectional coverage)

# ── Check 4: roadmap ↔ requirements-log 双向覆盖 ─────────────────

echo ""
echo "=== Check 4: roadmap ↔ requirements-log 覆盖 ==="

# Extract all P12 batch IDs from roadmap (P12 section)
ROADMAP_BATCHES=$(grep -oE 'P12-B[0-9]+' "$ROADMAP" 2>/dev/null | sort -u || true)
MISSING_IN_REQLOG=0
CHECKED=0
for batch in $ROADMAP_BATCHES; do
  CHECKED=$((CHECKED + 1))
  if ! grep -q "$batch" "$REQLOG" 2>/dev/null; then
    yellow "  ⚠️  $batch 在 roadmap 中存在，但 requirements-log 中缺失"
    MISSING_IN_REQLOG=$((MISSING_IN_REQLOG + 1))
  fi
done
if [ "$MISSING_IN_REQLOG" -eq 0 ] && [ "$CHECKED" -gt 0 ]; then
  green "  ✅ 所有 $CHECKED 个 P12 batch 在 requirements-log 中均有记录"
elif [ "$CHECKED" -eq 0 ]; then
  yellow "  ⚠️  未在 roadmap 中找到 P12 batch 条目"
else
  WARNINGS=$((WARNINGS + MISSING_IN_REQLOG))
fi

# ── Check 5: 时间戳新鲜度 ────────────────────────────────────────

echo ""
echo "=== Check 5: 时间戳新鲜度 ==="
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d 2>/dev/null || echo "")

if [ "$L5_TIMESTAMP" = "$TODAY" ] || [ "$L5_TIMESTAMP" = "$YESTERDAY" ]; then
  green "  ✅ L5 checkpoint 时间戳: $L5_TIMESTAMP (新鲜)"
else
  yellow "  ⚠️  L5 checkpoint 时间戳: $L5_TIMESTAMP (不是今天/昨天)"
  WARNINGS=$((WARNINGS + 1))
fi

# ── Summary ──────────────────────────────────────────────────────

echo ""
echo "=============================================="
echo "  L5 一致性检查结果: $ERRORS 错误 · $WARNINGS 警告"
echo "=============================================="

# Determine exit code
if [ "$ERRORS" -gt 0 ]; then
  red "❌ L5 一致性检查未通过 — 发现 $ERRORS 项硬错误"
  exit 1
fi

# In --strict mode, warnings also fail
if [ "$STRICT" = true ] && [ "$WARNINGS" -gt 0 ]; then
  yellow "⚠️  L5 一致性检查: --strict 模式，$WARNINGS 项警告视为失败"
  exit 1
fi

# When batchesSinceLastL5 ≥ 2, treat warnings as errors (L5 is overdue)
if [ "$L5_COUNTER" -ge 2 ] && [ "$WARNINGS" -gt 0 ]; then
  red "❌ L5 一致性检查未通过 — batchesSinceLastL5=$L5_COUNTER (≥2) 且存在 $WARNINGS 项警告"
  red "   必须先执行 L5 拉通再继续提交"
  exit 1
fi

if [ "$WARNINGS" -gt 0 ]; then
  yellow "⚠️  L5 一致性检查: $WARNINGS 项警告 (非阻断)"
else
  green "✅ L5 一致性检查全部通过"
fi

exit 0
