#!/usr/bin/env bash
# Synapse 经验编号连续性检查（LRN 防呆）
# 来源: P5-B14 — GlassCortex 制度审计 E6 + LRN-2026-057 防呆三原则
# 用法: bash tools/check-lessons.sh
#
# 检查项:
#   1. LL 编号连续性 — lessons-learned.md 中 LL1..LLN 无跳号/无重复
#   2. P 编号连续性 — pitfalls.md 中 P-001..P-NNN 无跳号/无重复
#   3. 交叉引用有效性 — lessons-learned.md 引用的 P-NNN 必须在 pitfalls.md 中存在
#   4. P↔LL 双向关联 (warning) — 建议 pitfalls 条目反向引用对应 LL

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ERRORS=0
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

LESSONS_FILE="$PROJECT_DIR/docs/lessons-learned.md"
PITFALLS_FILE="$PROJECT_DIR/docs/pitfalls.md"

echo "=== 经验编号连续性（LRN 防呆） ==="
echo ""

# ── 文件存在性 ─────────────────────────────────────────

if [ ! -f "$LESSONS_FILE" ]; then
  yellow "  ⚠️  lessons-learned.md 不存在 — 跳过 LL 检查"
  LESSONS_FILE=""
fi
if [ ! -f "$PITFALLS_FILE" ]; then
  yellow "  ⚠️  pitfalls.md 不存在 — 跳过 P 检查"
  PITFALLS_FILE=""
fi

# ── 1. LL 编号连续性 ───────────────────────────────────

if [ -n "$LESSONS_FILE" ]; then
  echo "--- LL 编号（lessons-learned.md） ---"

  # 提取所有 ## LLN: 格式的编号
  LL_NUMS=$(grep -oE '^## LL[0-9]+:' "$LESSONS_FILE" 2>/dev/null | \
    grep -oE '[0-9]+' | sort -n || true)

  if [ -z "$LL_NUMS" ]; then
    yellow "  ⚠️  未找到 LL# 标题 — 可能是格式不同"
  else
    LL_COUNT=$(echo "$LL_NUMS" | wc -l | tr -d ' ')
    green "  找到 $LL_COUNT 条 LL 经验"

    # 检查重复
    LL_DUPS=$(echo "$LL_NUMS" | uniq -d || true)
    if [ -n "$LL_DUPS" ]; then
      red "  ❌ 重复 LL 编号: $LL_DUPS"
      ERRORS=$((ERRORS + 1))
    else
      green "  ✅ 无重复 LL 编号"
    fi

    # 检查连续性
    PREV=0
    for n in $LL_NUMS; do
      EXPECTED=$((PREV + 1))
      if [ "$n" -ne "$EXPECTED" ]; then
        red "  ❌ LL 跳号: LL$PREV → LL$n (缺 LL$EXPECTED)"
        ERRORS=$((ERRORS + 1))
      fi
      PREV=$n
    done
    if [ "$ERRORS" -eq 0 ] || [ "$PREV" -eq "$LL_COUNT" ]; then
      green "  ✅ LL 编号连续 (LL1 → LL$PREV)"
    fi
    LL_MAX=$PREV
  fi
  echo ""
fi

# ── 2. P 编号连续性 ────────────────────────────────────

if [ -n "$PITFALLS_FILE" ]; then
  echo "--- P 编号（pitfalls.md） ---"

  # 提取所有 ### P-NNN: 格式的编号
  P_NUMS=$(grep -oE '^### P-[0-9]+:' "$PITFALLS_FILE" 2>/dev/null | \
    grep -oE '[0-9]+' | sort -n || true)

  if [ -z "$P_NUMS" ]; then
    yellow "  ⚠️  未找到 P-### 标题 — 可能是格式不同"
  else
    P_COUNT=$(echo "$P_NUMS" | wc -l | tr -d ' ')
    green "  找到 $P_COUNT 条 P 踩坑记录"

    # 检查重复
    P_DUPS=$(echo "$P_NUMS" | uniq -d || true)
    if [ -n "$P_DUPS" ]; then
      red "  ❌ 重复 P 编号: $P_DUPS"
      ERRORS=$((ERRORS + 1))
    else
      green "  ✅ 无重复 P 编号"
    fi

    # 检查连续性
    PREV=0
    for n in $P_NUMS; do
      EXPECTED=$((PREV + 1))
      if [ "$((10#$n))" -ne "$EXPECTED" ]; then
        red "  ❌ P 跳号: P-$(printf '%03d' $PREV) → P-$(printf '%03d' $n) (缺 P-$(printf '%03d' $EXPECTED))"
        ERRORS=$((ERRORS + 1))
      fi
      PREV=$((10#$n))
    done
    if [ "$ERRORS" -eq 0 ] || [ "$PREV" -eq "$P_COUNT" ]; then
      green "  ✅ P 编号连续 (P-001 → P-$(printf '%03d' $PREV))"
    fi
  fi
  echo ""
fi

# ── 3. 交叉引用有效性 ──────────────────────────────────

if [ -n "$LESSONS_FILE" ] && [ -n "$PITFALLS_FILE" ]; then
  echo "--- 交叉引用有效性 ---"

  # 从 lessons-learned.md 提取引用的 P-NNN
  P_REFS=$(grep -oE '\bP-[0-9]{3}\b' "$LESSONS_FILE" 2>/dev/null | \
    grep -oE '[0-9]+' | sort -n | uniq || true)

  # 从 pitfalls.md + archive 提取存在的 P-NNN（P100-B103 归档后需查两份文件）
  PITFALLS_ARCHIVE="$PROJECT_DIR/docs/archive/pitfalls-archive.md"
  P_EXISTING=$( (grep -oE '^### P-[0-9]+:' "$PITFALLS_FILE" 2>/dev/null; \
                 grep -oE '^### P-[0-9]+:' "$PITFALLS_ARCHIVE" 2>/dev/null) | \
    grep -oE '[0-9]+' | sort -n || true)

  INVALID_REFS=0
  for ref in $P_REFS; do
    if ! echo "$P_EXISTING" | grep -q "^${ref}$" 2>/dev/null; then
      red "  ❌ lessons-learned.md 引用不存在的 P-$(printf '%03d' $ref)"
      ERRORS=$((ERRORS + 1))
      INVALID_REFS=$((INVALID_REFS + 1))
    fi
  done

  if [ "$INVALID_REFS" -eq 0 ]; then
    if [ -z "$P_REFS" ]; then
      yellow "  ⚠️  lessons-learned.md 未引用任何 P-### 条目"
      WARNINGS=$((WARNINGS + 1))
    else
      REF_COUNT=$(echo "$P_REFS" | wc -l | tr -d ' ')
      green "  ✅ 所有 $REF_COUNT 条 P 交叉引用有效"
    fi
  fi

  # 4. 反向引用检查 (warning only)
  LL_REFS_IN_PITFALLS=$(grep -oE '\bLL[0-9]+\b' "$PITFALLS_FILE" 2>/dev/null || true)
  if [ -z "$LL_REFS_IN_PITFALLS" ]; then
    yellow "  💡 pitfalls.md 未反向引用 LL# 经验 — 建议补充关联（不阻断）"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ pitfalls.md 包含 LL 反向引用"
  fi
  echo ""
fi

# ── 总结 ────────────────────────────────────────────────

echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
  red "❌ 经验编号检查: $ERRORS 个硬错误 · $WARNINGS 个警告"
  exit 1
else
  green "✅ 经验编号检查通过"
  if [ "$WARNINGS" -gt 0 ]; then
    yellow "💡 $WARNINGS 个警告（不阻断，建议关注）"
  fi
fi
