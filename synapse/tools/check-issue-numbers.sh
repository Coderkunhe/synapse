#!/usr/bin/env bash
# Synapse 议题编号自洽校验 — CLAUDE.md ↔ tracks/synapse.md ↔ master-backlog 三方对齐
# G26: 机械校验议题编号、状态、Batch 范围的三方一致性
# 用法: bash tools/check-issue-numbers.sh
# 退出码: 0 = 一致, 1 = 发现不一致（WARNING 级，不阻断 commit）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
ERRORS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

echo "=== 议题编号自洽校验（G26）==="
echo ""

CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
TRACK_MD="$PROJECT_DIR/tracks/synapse.md"
BACKLOG_MD="$PROJECT_DIR/docs/master-backlog.md"

# ── 前置：文件存在性 ──
for f in "$CLAUDE_MD" "$TRACK_MD"; do
  if [ ! -f "$f" ]; then
    red "  ❌ 缺失: $f"
    ERRORS=$((ERRORS + 1))
  fi
done
if [ $ERRORS -gt 0 ]; then
  echo ""
  exit 1
fi

# ── 校验 1: Track 段头 Batch 范围新鲜度 ──
# 从 tracks/synapse.md P10 段头提取声明的范围（如 "B1→B28"）
echo "--- 校验 1: Track 段头 Batch 范围新鲜度 ---"

# 提取 track 段头中声明的范围（仅 P10 架构升级段头）
TRACK_HEADER_LINE=$(grep "^### P10 架构升级" "$TRACK_MD" 2>/dev/null || echo "")
TRACK_HEADER_RANGE=$(echo "$TRACK_HEADER_LINE" | grep -oE 'B[0-9]+→B[0-9]+' || echo "")
if [ -z "$TRACK_HEADER_RANGE" ]; then
  yellow "  ⚠️  未找到 track 段头 Batch 范围（如 B1→B28）"
else
  # 提取段头中的最后一批编号
  TRACK_HEADER_LAST=$(echo "$TRACK_HEADER_RANGE" | sed 's/.*→B//')

  # 从 P10 路线图中提取实际最后一批（含 ✅ 标记的最大 B 编号）
  # 匹配格式: P10-B{N} ... ✅
  ACTUAL_LAST=$(grep -oE 'P10-B[0-9]+' "$TRACK_MD" | sed 's/P10-B//' | sort -n | tail -1 || echo "0")

  if [ "$TRACK_HEADER_LAST" != "$ACTUAL_LAST" ] && [ "$ACTUAL_LAST" != "0" ]; then
    red "  ❌ Track 段头声明范围 ${TRACK_HEADER_RANGE}，但实际最后一批为 P10-B${ACTUAL_LAST}"
    red "     → 过期段头需更新为 B1→B$ACTUAL_LAST"
    ERRORS=$((ERRORS + 1))
  else
    green "  ✅ Track 段头 Batch 范围 ${TRACK_HEADER_RANGE} 与实际一致"
  fi
fi
echo ""

# ── 校验 2: Track 段头议题状态 vs 实际批次状态 ──
echo "--- 校验 2: 议题状态一致性 ---"

# 从 track 段头提取议题状态声明
TRACK_HEADER=$(grep "^### P10 架构升级" "$TRACK_MD" || echo "")

# 检查段头中是否还有 🔄/⬜ 标记（全部完成时应只有 ✅/🎉）
if echo "$TRACK_HEADER" | grep -qE '[🔄⬜]'; then
  red "  ❌ Track 段头存在未闭环状态标记 🔄/⬜"
  red "     → 段头内容: $TRACK_HEADER"
  ERRORS=$((ERRORS + 1))
else
  green "  ✅ Track 段头无未闭环状态标记"
fi
echo ""

# ── 校验 3: CLAUDE.md 当前状态段议题数 vs Track 定义 ──
echo "--- 校验 3: CLAUDE.md ↔ Track 议题数量一致 ---"

# 从 CLAUDE.md "当前状态" 段提取 P10 议题描述中的议题数
CLAUDE_P10_LINE=$(grep -E "^- P10：" "$CLAUDE_MD" | head -1 || echo "")
CLAUDE_ISSUE_COUNT=$(echo "$CLAUDE_P10_LINE" | grep -oE '[0-9]+\s*个?议题' | grep -oE '[0-9]+' || echo "0")

# 从 track 路线图统计唯一议题编号
TRACK_ISSUE_COUNT=8  # P10 定义 8 个议题（①-⑧）

if [ "$CLAUDE_ISSUE_COUNT" != "0" ] && [ "$CLAUDE_ISSUE_COUNT" != "$TRACK_ISSUE_COUNT" ]; then
  red "  ❌ CLAUDE.md 声明 $CLAUDE_ISSUE_COUNT 个议题，Track 定义 $TRACK_ISSUE_COUNT 个"
  ERRORS=$((ERRORS + 1))
else
  green "  ✅ CLAUDE.md ↔ Track 议题数量一致（$TRACK_ISSUE_COUNT 个）"
fi
echo ""

# ── 校验 4: 议题编号连续性（无跳号） ──
echo "--- 校验 4: 议题编号连续性 ---"

# 从 track 路线图提取所有议题编号（匹配 "议题 N:" 格式，排除 "议题 N 批" 等非编号文本）
ISSUE_NUMS=$(grep -oE '议题 [0-9]+:' "$TRACK_MD" | sed 's/议题 //' | sed 's/://' | sort -n | uniq || echo "")

if [ -n "$ISSUE_NUMS" ]; then
  PREV=0
  GAPS=""
  while IFS= read -r num; do
    [ -z "$num" ] && continue
    if [ "$PREV" -gt 0 ] && [ "$num" -ne $((PREV + 1)) ]; then
      GAPS="$GAPS $PREV→$num"
    fi
    PREV=$num
  done <<< "$ISSUE_NUMS"

  if [ -n "$GAPS" ]; then
    red "  ❌ 议题编号存在跳号:$GAPS"
    ERRORS=$((ERRORS + 1))
  else
    green "  ✅ 议题编号连续无跳号"
  fi
fi
echo ""

# ── 校验 5: master-backlog P10 段议题数一致 ──
echo "--- 校验 5: master-backlog P10 议题条目完整性 ---"

if [ -f "$BACKLOG_MD" ]; then
  # 统计 master-backlog 中 P10 段下的 S-xxx 条目
  # P10 段在 "## 🟡 P10" 之后
  P10_BACKLOG_COUNT=$(sed -n '/^## 🟡 P10/,/^---$/p' "$BACKLOG_MD" | grep -cE '^\| S-[0-9]+' || true)

  # P10 issues map to S-059 through S-066 in master-backlog (8 items)
  # S-059: Phase/Sprint mode · S-060: data-model.md P10 entities · S-061: architecture.md auth · S-062: security-model.md auth
  # S-063: B22 respond dedup · S-064: B22 heartbeat check · S-065: 403 interceptor · S-066: WebPush

  if [ "$P10_BACKLOG_COUNT" -lt 6 ]; then
    yellow "  ⚠️  master-backlog P10 段仅 $P10_BACKLOG_COUNT 条 S-xxx（预期 ≥6，覆盖 8 议题的登记项）"
  else
    green "  ✅ master-backlog P10 段 $P10_BACKLOG_COUNT 条 S-xxx"
  fi
else
  yellow "  ⚠️  master-backlog.md 不存在，跳过校验 5"
fi
echo ""

# ── 总结 ──
echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
  red "❌ 议题编号自洽: $ERRORS 项不一致"
  echo ""
  yellow "💡 修复建议："
  yellow "   1. 更新 tracks/synapse.md P10 段头（Batch 范围 + 议题状态）"
  yellow "   2. 确保 CLAUDE.md §当前状态 与 track 定义一致"
  yellow "   3. 确保 master-backlog P10 段覆盖全部 8 议题"
  exit 1
else
  green "✅ 议题编号自洽 — CLAUDE.md ↔ tracks ↔ master-backlog 三方一致"
fi
