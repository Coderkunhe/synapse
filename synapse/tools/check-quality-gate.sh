#!/usr/bin/env bash
# Synapse 质量三板斧机械门禁 — GAP-2 (G-030) · P100-B91
# 检测条件: staged 包含代码文件 → 要求 .claude/self-check-*.md 存在且完整
# 用法: bash tools/check-quality-gate.sh [--skip-quality-gate]
# 来源: hook-gap-audit.md GAP-2 — 编码前 Scout + 编码后自检 机械约束
# Phase: P100 — 治理基建

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

# ── Flag parsing ──────────────────────────────────────────
SKIP=false
for arg in "$@"; do
  case "$arg" in
    --skip-quality-gate) SKIP=true ;;
  esac
done

if [ "$SKIP" = true ]; then
  yellow "⚠️  质量三板斧门禁已通过 --skip-quality-gate 跳过（GAP-2 bypass）"
  echo "   $(date -u +%Y-%m-%dT%H:%M:%SZ) skip-quality-gate" >> "$REPO_ROOT/synapse/.claude/quality-gate-bypass.log" 2>/dev/null || true
  exit 0
fi

# ── 检测代码文件 ──────────────────────────────────────────
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

if [ -z "$STAGED_FILES" ]; then
  exit 0
fi

# 代码文件 = synapse/src/ 或 synapse/frontend/src/ 下的文件
CODE_FILES=$(echo "$STAGED_FILES" | grep -E '^synapse/src/|^synapse/frontend/src/' || true)

if [ -z "$CODE_FILES" ]; then
  # 无代码文件变更 → 不需要质量三板斧
  exit 0
fi

echo ""
echo "=== 质量三板斧门禁（GAP-2 · G-030）==="
echo ""
echo "检测到代码文件变更："
echo "$CODE_FILES" | while read -r f; do echo "   • $f"; done
echo ""

# ── 查找自检文件 ──────────────────────────────────────────
SELF_CHECK_DIR="$PROJECT_DIR/.claude"
SELF_CHECK_FILES=$(ls -t "$SELF_CHECK_DIR"/self-check-*.md 2>/dev/null || echo "")

if [ -z "$SELF_CHECK_FILES" ]; then
  red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  red "🔴  质量三板斧门禁失败（GAP-2 · G-030）"
  red "🔴"
  red "🔴  代码文件变更必须先完成编码前 Scout + 编码后自检。"
  red "🔴  未找到 .claude/self-check-*.md 文件。"
  red "🔴"
  red "🔴  请执行以下步骤："
  red "🔴  1. 编码前 Scout（三问）："
  red "🔴     ☐ 数据流拉通 — API 参数约束/返回字段/权限要求"
  red "🔴     ☐ 同类参照 — 至少看一个类似实现，确认风格一致"
  red "🔴     ☐ 用户一句话 — 做完这个，用户看到什么、解决什么问题"
  red "🔴  2. 编码后自检（四问）："
  red "🔴     ☐ 乐观路径 — 正常流程走通"
  red "🔴     ☐ 边界状态 — 空数据/加载中/错误/交互状态"
  red "🔴     ☐ 对比同类 — 风格/宽度/交互一致性"
  red "🔴     ☐ 变更清单口播 — 文件列表 + ≤8 校验"
  red "🔴  3. 将结果写入 .claude/self-check-<batch>.md"
  red "🔴"
  red "🔴  紧急跳过：git commit 前设置 GIT_SKIP_QUALITY_GATE=1"
  red "🔴  或：bash tools/check-quality-gate.sh --skip-quality-gate"
  red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

# ── 验证自检文件完整性 ──────────────────────────────────
# 取最近修改的自检文件
LATEST_SELF_CHECK=$(echo "$SELF_CHECK_FILES" | head -1)
SELF_CHECK_NAME=$(basename "$LATEST_SELF_CHECK")

echo "📋 最近自检文件: $SELF_CHECK_NAME"

# 检查是否在 staged 中（AI 应一并提交自检文件）
SELF_CHECK_STAGED=$(echo "$STAGED_FILES" | grep ".claude/self-check-" || true)
if [ -z "$SELF_CHECK_STAGED" ]; then
  yellow "   ⚠️  自检文件未包含在本次 commit 中 — 建议一并提交"
fi

# 检查必填 checkbox 区段
MISSING_SECTIONS=""

# Scout 三问
if ! grep -qE '数据流拉通|Scout.*三问|编码前.*Scout' "$LATEST_SELF_CHECK" 2>/dev/null; then
  MISSING_SECTIONS="$MISSING_SECTIONS  - 编码前 Scout 区段缺失\n"
fi

# 自检四问
if ! grep -qE '乐观路径|自检.*四问|编码后.*自检' "$LATEST_SELF_CHECK" 2>/dev/null; then
  MISSING_SECTIONS="$MISSING_SECTIONS  - 编码后自检区段缺失\n"
fi

# checkbox 计数 (Markdown: - [x] 或 - [X])
# grep -c exits 1 on 0 matches → || true prevents fallback echo double-counting
CHECKED=$(grep -cE '^\- \[[xX]\]' "$LATEST_SELF_CHECK" 2>/dev/null || true)
CHECKED=${CHECKED:-0}
UNCHECKED=$(grep -cE '^\- \[ \]' "$LATEST_SELF_CHECK" 2>/dev/null || true)
UNCHECKED=${UNCHECKED:-0}
# strip whitespace/newlines for arithmetic
CHECKED=$(echo "$CHECKED" | tr -d '[:space:]')
UNCHECKED=$(echo "$UNCHECKED" | tr -d '[:space:]')
TOTAL_CHECKBOXES=$((CHECKED + UNCHECKED))

echo "   Checkbox: ${CHECKED}/${TOTAL_CHECKBOXES} 已完成"

if [ -n "$MISSING_SECTIONS" ]; then
  yellow "   ⚠️  自检文件结构不完整："
  echo -e "$MISSING_SECTIONS"
  yellow "   ⚠️  当前为警告模式 — 请在下次 commit 前补全"
fi

if [ "$TOTAL_CHECKBOXES" -lt 3 ] 2>/dev/null; then
  yellow "   ⚠️  自检文件 checkbox 不足（最少 3 项: Scout 三问）"
  yellow "   ⚠️  当前为警告模式 — 请在下次 commit 前补充"
fi

if [ "$UNCHECKED" -gt 0 ] 2>/dev/null; then
  yellow "   ⚠️  ${UNCHECKED} 项未打勾 — 请确认是否故意留空"
fi

echo ""
green "✅ 质量三板斧门禁通过"
exit 0
