#!/usr/bin/env bash
# Synapse Checkpoint 新鲜度门禁 — GAP-3 (G-031) · P100-B91
# 检测条件: staged 包含 synapse/ 文件 → 要求 memory/active/*.md 今日已更新
# 用法: bash tools/check-checkpoint-freshness.sh [--skip-checkpoint-check]
# 来源: hook-gap-audit.md GAP-3 — /clear 前 checkpoint 无强制 → pre-commit 机械门禁
# Phase: P100 — 治理基建
#
# 设计原理：
#   Claude Code 的 /clear 命令不支持 hook，无法在 clear 时触发检查。
#   因此将 checkpoint 新鲜度检查提前到 pre-commit：每次提交 synapse/
#   内容时，强制要求 memory/active/*.md 中至少有一个今天更新过。
#   这比原规则（/clear 前 checkpoint）更严格，但机械上可执行。

set -euo pipefail

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

# ── Flag parsing ──────────────────────────────────────────
SKIP=false
for arg in "$@"; do
  case "$arg" in
    --skip-checkpoint-check) SKIP=true ;;
  esac
done

if [ "$SKIP" = true ]; then
  yellow "⚠️  Checkpoint 新鲜度门禁已通过 --skip-checkpoint-check 跳过（GAP-3 bypass）"
  exit 0
fi

# ── 检测是否有 synapse/ 变更 ──────────────────────────────
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
  exit 0
fi

# 匹配 synapse/ 下的实质性文件（排除纯机械文件）
SYNAPSE_FILES=$(echo "$STAGED_FILES" | grep '^synapse/' || true)

if [ -z "$SYNAPSE_FILES" ]; then
  # 没有 synapse 内容变更 → 不需要 checkpoint
  exit 0
fi

echo ""
echo "=== Checkpoint 新鲜度门禁（GAP-3 · G-031）==="
echo ""

# ── 定位 memory 目录 ──────────────────────────────────────
# 与 session-checkpoint.sh 保持一致的路径逻辑
MEM_DIR="${SYNAPSE_MEM_DIR:-$HOME/.claude/projects/-Users-hunter-projects-personal-ai-ai-synapse/memory}"
ACTIVE_DIR="$MEM_DIR/active"

if [ ! -d "$ACTIVE_DIR" ]; then
  yellow "⚠️  memory/active/ 目录不存在 — 跳过 checkpoint 检查"
  yellow "   路径: $ACTIVE_DIR"
  echo ""
  exit 0
fi

# ── 检查 active topic 文件新鲜度 ──────────────────────────
TODAY=$(date +%Y-%m-%d)
FRESH_FOUND=false
STALE_FILES=""

for f in "$ACTIVE_DIR"/*.md; do
  [ -f "$f" ] || continue
  FNAME=$(basename "$f")
  # 获取文件最后修改日期（跨平台兼容）
  if [[ "$OSTYPE" == "darwin"* ]]; then
    MOD_DATE=$(stat -f "%Sm" -t "%Y-%m-%d" "$f" 2>/dev/null || echo "")
  else
    MOD_DATE=$(stat -c "%y" "$f" 2>/dev/null | cut -d' ' -f1 || echo "")
  fi

  if [ "$MOD_DATE" = "$TODAY" ]; then
    FRESH_FOUND=true
    green "   ✅ $FNAME — 今日已更新 ($MOD_DATE)"
  else
    STALE_FILES="$STALE_FILES   • $FNAME (最后更新: ${MOD_DATE:-未知})\n"
  fi
done

if [ "$FRESH_FOUND" = true ]; then
  echo ""
  green "✅ Checkpoint 新鲜度门禁通过"
  exit 0
fi

# ── 全部过期 → 阻断 ──────────────────────────────────────
red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
red "🔴  Checkpoint 新鲜度门禁失败（GAP-3 · G-031）"
red "🔴"
red "🔴  本 commit 包含 synapse/ 文件变更，但所有 active topic checkpoint"
red "🔴  均未在今天更新过。请先更新 session checkpoint 再提交。"
red "🔴"
red "🔴  过期文件："
if [ -n "$STALE_FILES" ]; then
  echo -e "$STALE_FILES"
fi
red "🔴"
red "🔴  请执行 CLAUDE.md §3（协作纪律 §3 接头暗号）："
red "🔴  1. 确定当前 topic（p100 / p11 / landing）"
red "🔴  2. 更新 memory/active/<topic>.md（暗号 + 下一站 + 上下文）"
red "🔴  3. 更新 memory/MEMORY.md 的「🟢 Active Sessions」表"
red "🔴"
red "🔴  紧急跳过：export SYNAPSE_SKIP_CHECKPOINT_CHECK=1"
red "🔴  或：bash tools/check-checkpoint-freshness.sh --skip-checkpoint-check"
red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit 1
