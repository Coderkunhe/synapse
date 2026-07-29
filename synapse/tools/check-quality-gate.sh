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
# P100-B106: 内容深度升级 — 从"文件存在性"升级为"内容诚实度"。
# 不再只检查 checkbox 数量，而是验证 scout/自检区段有实质性内容。
# 缺失实质性内容 → ERROR（阻断 commit），不再是 WARNING。

# 取最近修改的自检文件
LATEST_SELF_CHECK=$(echo "$SELF_CHECK_FILES" | head -1)
SELF_CHECK_NAME=$(basename "$LATEST_SELF_CHECK")

echo "📋 最近自检文件: $SELF_CHECK_NAME"

# 检查是否在 staged 中（AI 应一并提交自检文件）
SELF_CHECK_STAGED=$(echo "$STAGED_FILES" | grep ".claude/self-check-" || true)
if [ -z "$SELF_CHECK_STAGED" ]; then
  yellow "   ⚠️  自检文件未包含在本次 commit 中 — 建议一并提交"
fi

GATE_ERRORS=0

# ── Rule 1: 最小行数（≥ 15 行 — 空文件/骨架文件拦截）──────
SELF_CHECK_LINES=$(wc -l < "$LATEST_SELF_CHECK" 2>/dev/null | tr -d '[:space:]')
SELF_CHECK_LINES=${SELF_CHECK_LINES:-0}
if [ "$SELF_CHECK_LINES" -lt 15 ]; then
  red "   🔴 自检文件不足 15 行（当前: ${SELF_CHECK_LINES} 行）"
  red "      空文件或骨架文件不能替代真正的 Scout + 自检。"
  red "      请完成编码前 Scout（三问）+ 编码后自检（四问），写入实质性内容。"
  GATE_ERRORS=$((GATE_ERRORS + 1))
fi

# ── Rule 2: Scout 区段实质性内容（≥ 3 个有实质回答的 checkbox）──
# 检测模式: "- [x] " 后跟 ≥ 20 个非空字符（不只是勾了框）
SCOUT_SUBSTANTIVE=$(grep -cE '^\- \[[xX]\] .{20,}' "$LATEST_SELF_CHECK" 2>/dev/null || true)
SCOUT_SUBSTANTIVE=${SCOUT_SUBSTANTIVE:-0}
SCOUT_SUBSTANTIVE=$(echo "$SCOUT_SUBSTANTIVE" | tr -d '[:space:]')

# 也检测 Scout 区段是否存在（关键字匹配）
HAS_SCOUT_SECTION=$(grep -cE '数据流拉通|Scout.*三问|编码前.*Scout' "$LATEST_SELF_CHECK" 2>/dev/null || true)
HAS_SCOUT_SECTION=${HAS_SCOUT_SECTION:-0}
HAS_SCOUT_SECTION=$(echo "$HAS_SCOUT_SECTION" | tr -d '[:space:]')

if [ "$HAS_SCOUT_SECTION" -eq 0 ]; then
  red "   🔴 编码前 Scout 区段缺失 — 未找到 '数据流拉通' / 'Scout 三问' / '编码前 Scout' 标记"
  GATE_ERRORS=$((GATE_ERRORS + 1))
elif [ "$SCOUT_SUBSTANTIVE" -lt 3 ]; then
  red "   🔴 Scout 区段实质性内容不足（${SCOUT_SUBSTANTIVE}/3 项有 ≥20 字回答）"
  red "      Scout 三问每项必须有实质性回答（≥20 字符），不只是打勾。"
  GATE_ERRORS=$((GATE_ERRORS + 1))
fi

# ── Rule 3: 自检区段实质性内容（≥ 4 个有实质回答的 checkbox）──
SELFCHECK_SUBSTANTIVE=$(grep -cE '^\- \[[xX]\] .{20,}' "$LATEST_SELF_CHECK" 2>/dev/null || true)
SELFCHECK_SUBSTANTIVE=${SELFCHECK_SUBSTANTIVE:-0}
SELFCHECK_SUBSTANTIVE=$(echo "$SELFCHECK_SUBSTANTIVE" | tr -d '[:space:]')

HAS_SELFCHECK_SECTION=$(grep -cE '乐观路径|自检.*四问|编码后.*自检' "$LATEST_SELF_CHECK" 2>/dev/null || true)
HAS_SELFCHECK_SECTION=${HAS_SELFCHECK_SECTION:-0}
HAS_SELFCHECK_SECTION=$(echo "$HAS_SELFCHECK_SECTION" | tr -d '[:space:]')

# 自检区段实质性内容需要 ≥ 4 项（四问），但 Scout 回答也计入总计数。
# 用总实质性 checkbox - Scout 实质性 = 自检实质性。
# 简化：总实质性 checkbox ≥ 7（Scout 三问 + 自检四问）
TOTAL_SUBSTANTIVE=$SCOUT_SUBSTANTIVE  # 已在上面计算了总数，这里算总计数
TOTAL_SUBSTANTIVE=$(grep -cE '^\- \[[xX]\] .{20,}' "$LATEST_SELF_CHECK" 2>/dev/null || true)
TOTAL_SUBSTANTIVE=${TOTAL_SUBSTANTIVE:-0}
TOTAL_SUBSTANTIVE=$(echo "$TOTAL_SUBSTANTIVE" | tr -d '[:space:]')

if [ "$HAS_SELFCHECK_SECTION" -eq 0 ]; then
  red "   🔴 编码后自检区段缺失 — 未找到 '乐观路径' / '自检四问' / '编码后自检' 标记"
  GATE_ERRORS=$((GATE_ERRORS + 1))
fi

if [ "$TOTAL_SUBSTANTIVE" -lt 7 ]; then
  red "   🔴 实质性 checkbox 不足（${TOTAL_SUBSTANTIVE}/7 — Scout 三问 + 自检四问各需 ≥20 字回答）"
  red "      只打勾不写内容不能通过门禁。每项 checkbox 后面必须有实质性分析。"
  GATE_ERRORS=$((GATE_ERRORS + 1))
fi

# ── 汇总 ──────────────────────────────────────────────────
# checkbox 计数（信息展示）
CHECKED=$(grep -cE '^\- \[[xX]\]' "$LATEST_SELF_CHECK" 2>/dev/null || true)
CHECKED=${CHECKED:-0}
UNCHECKED=$(grep -cE '^\- \[ \]' "$LATEST_SELF_CHECK" 2>/dev/null || true)
UNCHECKED=${UNCHECKED:-0}
CHECKED=$(echo "$CHECKED" | tr -d '[:space:]')
UNCHECKED=$(echo "$UNCHECKED" | tr -d '[:space:]')

echo "   行数: ${SELF_CHECK_LINES} · checkbox: ${CHECKED} 已完成 / $((CHECKED + UNCHECKED)) 总计 · 实质性: ${TOTAL_SUBSTANTIVE}"

if [ "$UNCHECKED" -gt 0 ] 2>/dev/null; then
  yellow "   ⚠️  ${UNCHECKED} 项未打勾 — 请确认是否故意留空"
fi

if [ "$GATE_ERRORS" -gt 0 ]; then
  echo ""
  red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  red "🔴  质量三板斧门禁失败（GAP-2 · P100-B106 内容诚实度升级）"
  red "🔴"
  red "🔴  ${GATE_ERRORS} 项内容深度不达标。自检文件不能只存在——必须有实质性内容。"
  red "🔴"
  red "🔴  要求："
  red "🔴  - 自检文件 ≥ 15 行"
  red "🔴  - Scout 三问区段：每问 ≥ 20 字实质性回答"
  red "🔴  - 自检四问区段：每问 ≥ 20 字实质性回答"
  red "🔴  - 总计 ≥ 7 个实质性 checkbox（Scout 3 + 自检 4）"
  red "🔴"
  red "🔴  修复：补全 .claude/self-check-*.md 中的实质性内容后重新 commit。"
  red "🔴  紧急跳过：bash tools/check-quality-gate.sh --skip-quality-gate"
  red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

echo ""
green "✅ 质量三板斧门禁通过"
exit 0
