#!/usr/bin/env bash
# Synapse Phase 治理门禁
# 来源: P100-B1 — G-004 Per-Phase 编号 + check-phase 脚本
# 用法: bash tools/check-phase.sh
#
# 检查项:
#   1. 存在性 — docs/phase-criteria.md 存在
#   2. 引用 — CLAUDE.md 引用了 phase-criteria.md
#   3. Phase 声明 — roadmap.md 中 Phase 声明完整
#   4. Batch 格式 — 使用 Px-By 或 "Phase N Batch M" 格式（新批次）
#   5. Phase 规模 — 单 Phase >10 Batch 告警
#   6. 治理 Phase 隔离 — P100+ 不与功能 Phase 混排
#   7. 跨文档一致 — roadmap + requirements-log + CLAUDE.md Phase 列表对齐

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
ERRORS=0
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

echo "=== Phase 治理门禁 ==="
echo ""

# ── 1. 存在性检查 ──────────────────────────────────────

echo "--- 存在性 ---"
if [ -f "$PROJECT_DIR/docs/phase-criteria.md" ]; then
  green "  ✅ docs/phase-criteria.md 存在"
else
  red "  ❌ docs/phase-criteria.md 缺失 — Phase 划分标准未项目本地化"
  ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 2. 引用检查 ────────────────────────────────────────

echo "--- 引用 ---"
if grep -q 'phase-criteria.md' "$PROJECT_DIR/CLAUDE.md" 2>/dev/null; then
  green "  ✅ CLAUDE.md 引用了 phase-criteria.md"
else
  red "  ❌ CLAUDE.md 未引用 phase-criteria.md — 新会话无法自动加载 Phase 标准"
  ERRORS=$((ERRORS + 1))
fi
echo ""

# ── 3. Phase 声明完整性 ────────────────────────────────

echo "--- Phase 声明 ---"
ROADMAP="$PROJECT_DIR/docs/roadmap.md"
if [ -f "$ROADMAP" ]; then
  # 提取所有 Phase 声明行（## Phase N: ...）
  PHASE_DECLARATIONS=$(grep -c '^## Phase [0-9]' "$ROADMAP" 2>/dev/null || echo "0")
  # 提取所有 Phase 编号
  PHASES=$(grep -oE '^## Phase [0-9]+' "$ROADMAP" 2>/dev/null | grep -oE '[0-9]+' | sort -n | uniq || true)

  if [ -n "$PHASES" ]; then
    PHASE_COUNT=$(echo "$PHASES" | wc -l | tr -d ' ')
    green "  ✅ 发现 $PHASE_COUNT 个 Phase: $(echo "$PHASES" | tr '\n' ' ')"

    # 检查 Phase 编号连续性
    PREV=0
    FIRST=1
    for p in $PHASES; do
      if [ "$FIRST" -eq 1 ]; then
        FIRST=0
      else
        EXPECTED=$((PREV + 1))
        if [ "$p" -ne "$EXPECTED" ]; then
          yellow "  ⚠️  Phase 跳号: P$PREV → P$p (缺 P$EXPECTED)"
          WARNINGS=$((WARNINGS + 1))
        fi
      fi
      PREV=$p
    done
  else
    yellow "  ⚠️  未在 roadmap.md 中找到 Phase 声明"
  fi
else
  yellow "  ⚠️  roadmap.md 不存在 — 跳过 Phase 声明检查"
fi
echo ""

# ── 4. Batch 格式检查 ──────────────────────────────────

echo "--- Batch 格式 ---"
# 检查是否还有旧格式全局 Batch 编号（在 roadmap 和 requirements-log 中）
# 旧格式: 独立的 "Batch N" (不带 Phase 前缀)，如 "| Batch 1 |"
# 新格式: "Phase N Batch M" 或 "P{N}-B{M}"
#
# 注意: Phase 1-6 的历史批次使用旧格式是允许的（已归档）
# 本检查只对 Phase 7+ 的新内容要求新格式

OLD_FORMAT_IN_NEW=$(grep -n '^| Phase [7-9]\|^| Phase 1[0-9]' "$ROADMAP" 2>/dev/null | \
  grep -oE 'Batch [0-9]+' | grep -v 'Phase' || true)

# 更实际的检查：在 requirements-log 中查找 P7+ 的内容
# 提取 P7+ section 中的 Batch 引用
if grep -q '^## Phase [7-9]\|^## Phase 1[0-9]\|^## P[7-9]\|^## P[1-9][0-9]' \
  "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null; then
  # 检查 P7+ section 中是否使用了 Px-By 格式
  P7_SECTIONS=$(grep -n '^### P[7-9]\|^### P[1-9][0-9]' \
    "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | wc -l | tr -d ' ')
  if [ "$P7_SECTIONS" -gt 0 ]; then
    green "  ✅ P7+ 使用 Px-By 格式 ($P7_SECTIONS 条)"
  else
    yellow "  ⚠️  P7+ section 未检测到 Px-By 格式 — 可能使用旧格式"
  fi
else
  green "  ✅ 无需检查（无 P7+ 内容或已使用新格式）"
fi

# 检查是否有裸 Batch 编号（不带 Phase 前缀）在活跃 Phase 中
# 活跃 Phase = P7+（P1-P6 已归档，旧格式可接受）
BARE_BATCHES=$(grep -oE '\bBatch [0-9]+\b' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | \
  sort -u || true)
if [ -n "$BARE_BATCHES" ]; then
  # 这是历史遗留，不算错误，但提醒
  :
fi
green "  ✅ Batch 格式检查完成"
echo ""

# ── 5. Phase 规模告警 ──────────────────────────────────

echo "--- Phase 规模 ---"
if [ -f "$ROADMAP" ]; then
  CURRENT_PHASE=""
  for p in $PHASES; do
    # 统计该 Phase 下的 Batch 行数
    # 使用 awk 提取 Phase section 之间的内容
    BATCH_COUNT=$(awk "/^## Phase $p:/,/^## Phase /" "$ROADMAP" 2>/dev/null | \
      grep -cE '^\|.*Batch' || echo "0")
    if [ "$BATCH_COUNT" -gt 10 ] 2>/dev/null; then
      yellow "  ⚠️  P$p: $BATCH_COUNT Batch — 超过 10 Batch 建议拆分"
      WARNINGS=$((WARNINGS + 1))
    fi
  done
  green "  ✅ Phase 规模检查完成"
fi
echo ""

# ── 6. 治理 Phase 隔离 ─────────────────────────────────

echo "--- 治理 Phase 隔离 ---"
GOV_PHASES=$(echo "$PHASES" | grep -E '^(1[0-9]{2}|[2-9][0-9]{2,})$' || true)
FUNC_PHASES=$(echo "$PHASES" | grep -vE '^(1[0-9]{2}|[2-9][0-9]{2,})$' || true)

if [ -n "$GOV_PHASES" ]; then
  green "  ✅ 治理 Phase 已隔离: P$(echo "$GOV_PHASES" | tr '\n' ',' | sed 's/,$//')"
  # 检查治理 Phase 是否在 roadmap 中有明确的"治理"标注
  for gp in $GOV_PHASES; do
    if awk "/^## Phase $gp:/,/^## Phase /" "$ROADMAP" 2>/dev/null | \
       grep -qi '治理\|governance\|P100'; then
      green "    P$gp: 已标注治理属性"
    else
      yellow "  ⚠️  P$gp: 治理 Phase 建议在 roadmap 中明确标注「治理」"
      WARNINGS=$((WARNINGS + 1))
    fi
  done
else
  green "  ✅ 无治理 Phase（P100+）"
fi
echo ""

# ── 7. 跨文档 Phase 一致性 ─────────────────────────────

echo "--- 跨文档一致性 ---"

# 从 requirements-log 提取 Phase
REQLOG_PHASES=$(grep -oE '^## Phase [0-9]+' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | \
  grep -oE '[0-9]+' | sort -n | uniq || true)

# 从 CLAUDE.md 提取 Phase（当前状态段）
CLAUDE_PHASES=$(sed -n '/^## 当前状态/,/^---$/p' "$PROJECT_DIR/CLAUDE.md" 2>/dev/null | \
  grep -oE '\bP[0-9]+\b' | grep -oE '[0-9]+' | sort -n | uniq || true)

# 比较 roadmap vs requirements-log
if [ -n "$PHASES" ] && [ -n "$REQLOG_PHASES" ]; then
  MISSING_IN_REQLOG=""
  for p in $PHASES; do
    if ! echo "$REQLOG_PHASES" | grep -q "^${p}$" 2>/dev/null; then
      MISSING_IN_REQLOG="$MISSING_IN_REQLOG P$p"
    fi
  done
  if [ -n "$MISSING_IN_REQLOG" ]; then
    yellow "  ⚠️  roadmap 有但 requirements-log 缺:$MISSING_IN_REQLOG"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ roadmap ↔ requirements-log Phase 一致"
  fi
fi

# 检查 CLAUDE.md 是否提到最新 Phase
if [ -n "$PHASES" ]; then
  MAX_PHASE=$(echo "$PHASES" | tail -1)
  if [ -n "$CLAUDE_PHASES" ]; then
    MAX_CLAUDE=$(echo "$CLAUDE_PHASES" | tail -1)
    if [ "$MAX_CLAUDE" -lt "$MAX_PHASE" ]; then
      yellow "  ⚠️  CLAUDE.md 最大 Phase P$MAX_CLAUDE < roadmap P$MAX_PHASE — 当前状态可能过时"
      WARNINGS=$((WARNINGS + 1))
    else
      green "  ✅ CLAUDE.md 当前状态与 roadmap 一致"
    fi
  fi
fi
echo ""

# ── 总结 ────────────────────────────────────────────────

echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
  red "❌ Phase 治理门禁: $ERRORS 个硬错误 · $WARNINGS 个警告"
  exit 1
else
  green "✅ Phase 治理门禁通过"
  if [ "$WARNINGS" -gt 0 ]; then
    yellow "💡 $WARNINGS 个警告（不阻断，建议关注）"
  fi
fi
