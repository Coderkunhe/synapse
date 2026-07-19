#!/usr/bin/env bash
# check-plan-mode.sh — V-003 防呆：Plan Mode 入口检测
#
# 在 pre-commit 时检测当前 batch 的代码变更是否经过了 Plan Mode。
# 阈值来自 CLAUDE.md §13 Plan 分级制度：
#   🟢 ≤2 代码文件 + 无接口变更 → 微型，不需要 Plan → 放行
#   🟡 ≥3 代码文件 且无 plan → 警告（首部署警告，验证 2 批后升级阻断）
#   🟡 接口/协议变更 且无 plan → 警告
#
# Plan 文件匹配逻辑：
#   1. 从 tracks/synapse.md frontmatter 读取 next_batch
#   2. 在 docs/plans/ 搜索匹配文件（{phase}*b{batch-num}* 或 {phase}*plan*）
#   3. Fallback: 检查 docs/plans/ 是否有今日修改的文件
#
# 集成：
#   - make check-plan-mode（独立 target）
#   - make check（聚合管道）
#   - pre-commit hook（Stage 4）
#
# 用法：bash tools/check-plan-mode.sh
# 退出码：0 = 通过/警告 · 1 = 阻断（验证期后启用）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

red()    { echo -e "\033[31m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
yellow() { echo -e "\033[33m$1\033[0m"; }
bold()   { echo -e "\033[1m$1\033[0m"; }

# ── Count staged code files ───────────────────────────────────────
# 从 git diff 获取变更文件（优先 staged，fallback 到 working tree）
STAGED=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null || echo "")
if [ -z "$STAGED" ]; then
  STAGED=$(git diff --name-only --diff-filter=ACMR 2>/dev/null || echo "")
fi

if [ -z "$STAGED" ]; then
  # 没有变更文件 — 可能是纯文档 batch 或无变更
  echo "  ℹ️  无代码变更文件，跳过 Plan Mode 检测"
  exit 0
fi

# 代码文件分类：排除文档/配置/工具链/测试数据
# 注意：monorepo 中 git diff 输出含 synapse/ 前缀，case 的 * 不跨越 /
CODE_FILES=0
INTERFACE_FILES=0
CODE_FILE_LIST=""
for f in $STAGED; do
  case "$f" in
    */docs/*|*/*.md|*.md|*/tools/*|*/Makefile|Makefile|.gitignore|*.txt|*.json|*.yml|*.yaml|*.ini|*.example|*.toml|*.cfg|*/tracks/*|*.pyc|*/__pycache__/*)
      continue ;;
  esac
  CODE_FILES=$((CODE_FILES + 1))
  CODE_FILE_LIST="${CODE_FILE_LIST}  ${f}\n"

  # 接口/协议变更检测：schemas, models, api routers, protocol, data-model
  case "$f" in
    */schemas/*|*/models/*|*/api/*|*/protocol*|*/data-model*)
      INTERFACE_FILES=$((INTERFACE_FILES + 1)) ;;
  esac
done

# ── V-020 Scope-shift 信号检测 ────────────────────────────────────
# Batch 开始时按 🟢 微型规划，scout 后规模跃迁未重评是 V-020 的根因。
# 信号 A：staged 文件总数（含所有类型：code/doc/tool/memory）
# 信号 B：git diff 显示 pitfalls/lessons/master-backlog 新增 P-XXX/LL/S-XXX 条目数
# 触发条件：new_entries ≥ 3 OR total_staged ≥ 5 → 疑似跃迁
TOTAL_STAGED=0
for _f in $STAGED; do TOTAL_STAGED=$((TOTAL_STAGED + 1)); done

NEW_ENTRIES=0
for scope_doc in synapse/docs/pitfalls.md synapse/docs/lessons-learned.md synapse/docs/master-backlog.md; do
  # 只看 staged diff · 匹配新增行以 P-NNN / LL# / S-NNN 开头的模式
  if git diff --cached --unified=0 -- "$scope_doc" 2>/dev/null \
      | grep -E '^\+[^+]' \
      | grep -cE '(P-[0-9]+|LL[0-9]+|S-[0-9]+|## V-[0-9]+)' > /tmp/_scope_shift_count 2>/dev/null; then
    _c=$(cat /tmp/_scope_shift_count 2>/dev/null || echo 0)
    NEW_ENTRIES=$((NEW_ENTRIES + _c))
  fi
done
rm -f /tmp/_scope_shift_count

# ── Read next_batch from track file frontmatter ──────────────────
TRACK_FILE="$PROJECT_DIR/tracks/synapse.md"
if [ ! -f "$TRACK_FILE" ]; then
  yellow "⚠️  tracks/synapse.md 不存在，跳过 Plan Mode 检测"
  exit 0
fi

NEXT_BATCH=$(sed -n '/^---$/,/^---$/p' "$TRACK_FILE" | grep -E '^next_batch:' | awk '{print $2}' || echo "")
if [ -z "$NEXT_BATCH" ]; then
  yellow "⚠️  无法从 track 文件解析 next_batch，跳过 Plan Mode 检测"
  exit 0
fi

# Parse: P100-B19 → phase=p100, num=19
PHASE=$(echo "$NEXT_BATCH" | tr '[:upper:]' '[:lower:]' | sed 's/-b[0-9].*//')
BATCH_NUM=$(echo "$NEXT_BATCH" | sed 's/.*-[bB]//')

# ── Search for matching plan file ─────────────────────────────────
PLANS_DIR="$PROJECT_DIR/docs/plans"
HAS_PLAN=false
PLAN_MATCHES=""

if [ -d "$PLANS_DIR" ]; then
  # Match 1: exact-ish glob — {phase}*b{batch_num}* (e.g., p100-b19-plan.md, p100-b19-b22-plan.md)
  PLAN_MATCHES=$(find "$PLANS_DIR" -maxdepth 1 \( -name "${PHASE}*b${BATCH_NUM}*" -o -name "${PHASE}*B${BATCH_NUM}*" \) 2>/dev/null || echo "")
  if [ -n "$PLAN_MATCHES" ]; then
    HAS_PLAN=true
  fi

  # Match 2: any plan touching this phase (loose — warns but doesn't pass)
  if [ "$HAS_PLAN" = false ]; then
    PHASE_PLANS=$(find "$PLANS_DIR" -maxdepth 1 -name "${PHASE}*" 2>/dev/null || echo "")
    if [ -n "$PHASE_PLANS" ]; then
      HAS_PLAN=maybe
    fi
  fi

  # Match 3: plan file touched today (fallback heuristic)
  if [ "$HAS_PLAN" = false ]; then
    TODAY_PLAN=$(find "$PLANS_DIR" -maxdepth 1 -name "*.md" -newermt "$(date +%Y-%m-%d)T00:00:00" 2>/dev/null | head -1 || echo "")
    if [ -n "$TODAY_PLAN" ]; then
      HAS_PLAN=maybe
      PHASE_PLANS="$TODAY_PLAN"
    fi
  fi
fi

# ── Gate logic ────────────────────────────────────────────────────
echo ""
bold "=== Plan Mode 入口检测 (V-003 防呆) ==="
echo ""
printf "  当前 Batch: %s  ·  代码文件: %d  ·  接口变更: %d\n" "$NEXT_BATCH" "$CODE_FILES" "$INTERFACE_FILES"
printf "  Staged 总文件: %d  ·  新增待办条目: %d (P-XXX/LL/S-XXX)\n" "$TOTAL_STAGED" "$NEW_ENTRIES"

# ── V-020 Scope-shift 警告（顶层设计：Scout→Execute 重评） ──
SCOPE_SHIFT_WARN=false
if [ "$NEW_ENTRIES" -ge 3 ] || [ "$TOTAL_STAGED" -ge 5 ]; then
  SCOPE_SHIFT_WARN=true
fi

if [ "$SCOPE_SHIFT_WARN" = true ] && [ "$HAS_PLAN" != true ]; then
  echo ""
  yellow "  ┌──────────────────────────────────────────────────────────────┐"
  yellow "  │  ⚠️  V-020 违纪风险：疑似 scope 跃迁                          │"
  yellow "  ├──────────────────────────────────────────────────────────────┤"
  printf "  │  新增待办: %-2d 条  ·  Staged 总文件: %-3d                     │\n" "$NEW_ENTRIES" "$TOTAL_STAGED"
  yellow "  │                                                              │"
  yellow "  │  若原 Plan 分级为 🟢 微型 → 请 stop → 重 EnterPlanMode 分级    │"
  yellow "  │  CLAUDE.md §13 明文规则：Scout→Execute 分级重评              │"
  yellow "  │                                                              │"
  yellow "  │  参考：docs/process-violations.md V-020                       │"
  yellow "  └──────────────────────────────────────────────────────────────┘"
fi

# Helper: display matched plan files
show_plans() {
  local plans="$1"
  if [ -n "$plans" ]; then
    echo "$plans" | while read -r p; do
      [ -n "$p" ] && echo "    → $(basename "$p")"
    done
  fi
}

# ── 微型变更（≤2 文件，无接口变更）→ 放行 ──
if [ "$CODE_FILES" -le 2 ] && [ "$INTERFACE_FILES" -eq 0 ]; then
  echo ""
  green "  ✅ 微型变更（≤2 代码文件，无接口变更）— Plan Mode 非必需"
  echo ""
  exit 0
fi

# ── 有匹配的 plan → 放行 ──
if [ "$HAS_PLAN" = true ]; then
  echo "  Plan 文件: 已匹配"
  show_plans "$PLAN_MATCHES"
  echo ""
  green "  ✅ Plan Mode 检测通过 — 已找到对应 plan 文件"
  echo ""
  exit 0
fi

# ── 有同 Phase plan 但未确认覆盖 → 弱警告 ──
if [ "$HAS_PLAN" = maybe ]; then
  echo "  Plan 文件: 找到同 Phase plan（未确认覆盖本 Batch）"
  show_plans "${PHASE_PLANS:-}"
  echo ""
  yellow "  🟡 无法确认 plan 覆盖当前 batch — 请核实后继续"
  echo ""
  exit 0
fi

# ── 无 plan → 警告（验证期后升级为阻断）──
echo "  Plan 文件: ❌ 未找到"
echo ""

if [ "$CODE_FILES" -ge 3 ]; then
  yellow "  ┌──────────────────────────────────────────────────────────────┐"
  yellow "  │  ⚠️  V-003 违纪风险：≥3 代码文件变更但未找到 Plan 文件         │"
  yellow "  ├──────────────────────────────────────────────────────────────┤"
  printf "  │  当前 batch: %-12s  ·  代码文件: %-2d                        │\n" "$NEXT_BATCH" "$CODE_FILES"
  yellow "  │                                                              │"
  yellow "  │  CLAUDE.md §13: ≥3 文件 或 接口变更 → 需进入 Plan Mode        │"
  yellow "  │                                                              │"
  printf "  │  Action: 创建 docs/plans/%s-b%s-plan.md                 │\n" "$PHASE" "$BATCH_NUM"
  yellow "  │                                                              │"
  yellow "  │  ⚡ 首部署为警告 — 验证 2 批后升级为阻断（exit 1）            │"
  yellow "  └──────────────────────────────────────────────────────────────┘"
  echo ""
  # 首部署警告，验证期后改为 exit 1
  exit 0
fi

if [ "$INTERFACE_FILES" -ge 1 ]; then
  yellow "  ┌──────────────────────────────────────────────────────────────┐"
  yellow "  │  ⚠️  V-003 违纪风险：接口/协议变更但未找到 Plan 文件            │"
  yellow "  ├──────────────────────────────────────────────────────────────┤"
  yellow "  │  CLAUDE.md §13: 接口/协议变更需进入 Plan Mode                  │"
  yellow "  │  变更涉及 schemas/models/api/protocol — 建议记录设计决策       │"
  yellow "  │  Action: 创建 plan 文件或确认已有 plan 覆盖                    │"
  yellow "  └──────────────────────────────────────────────────────────────┘"
  echo ""
  exit 0
fi

green "  ✅ Plan Mode 检测通过"
echo ""
