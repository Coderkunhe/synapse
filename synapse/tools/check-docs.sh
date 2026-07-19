#!/usr/bin/env bash
# Synapse 文档门禁 — 文档新鲜度 + 验证覆盖率检查
# 来源: 从 glasscortex Makefile L2f 段移植 + Synapse 定制
# 用法: bash tools/check-docs.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ERRORS=0
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

echo "=== Synapse 文档门禁 ==="
echo ""

# ── 文档文件存在性 ──────────────────────────────────
echo "--- 文档存在性 ---"
for f in docs/prd.md docs/methodology.md docs/roadmap.md docs/requirements-log.md docs/pitfalls.md docs/lessons-learned.md; do
  if [ -f "$PROJECT_DIR/$f" ]; then
    green "  ✅ $f"
  else
    yellow "  ⚠️  $f 缺失（尚未创建）"
    WARNINGS=$((WARNINGS + 1))
  fi
done
echo ""

# ── 文档新鲜度 ──────────────────────────────────────
echo "--- 文档新鲜度 ---"
REQ_DATE=""
if [ -f "$PROJECT_DIR/docs/requirements-log.md" ]; then
  REQ_DATE=$(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | head -1 || echo "")
fi

if [ -n "$REQ_DATE" ]; then
  for doc in docs/roadmap.md docs/architecture.md docs/lessons-learned.md docs/methodology.md; do
    if [ -f "$PROJECT_DIR/$doc" ]; then
      DOC_DATE=$(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' "$PROJECT_DIR/$doc" 2>/dev/null | sort -r | head -1 || echo "")
      if [ -n "$DOC_DATE" ] && [ "$DOC_DATE" \< "$REQ_DATE" ]; then
        red "  ❌ $doc 最新日期($DOC_DATE) 落后于需求日志($REQ_DATE)"
        ERRORS=$((ERRORS + 1))
      else
        green "  ✅ $doc 日期新鲜 ($DOC_DATE)"
      fi
    fi
  done
else
  yellow "  ⚠️  requirements-log.md 无日期条目，跳过新鲜度检查"
fi
echo ""

# ── 需求验证覆盖率 ──────────────────────────────────
echo "--- 需求验证覆盖率 ---"
if [ -f "$PROJECT_DIR/docs/requirements-log.md" ]; then
  ENTRIES=$(grep -cE '^### [0-9]{4}-[0-9]{2}-[0-9]{2}' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null || true)
  VERIFIES=$(grep -c '验证' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null || true)
  if [ "$ENTRIES" -gt "$VERIFIES" ]; then
    yellow "  ⚠️  $ENTRIES 条需求, 仅 $VERIFIES 条含验证方式 — 补齐后再提交"
  else
    green "  ✅ $ENTRIES 条需求, $VERIFIES 条有验证方式"
  fi
fi
echo ""

# ── L5 拉通间隔检查 ─────────────────────────────────
# Uses .claude/l5-checkpoint.json (same source as pre-commit gate).
# Single source of truth — no grep-based heuristic.
echo "--- L5 拉通间隔 ---"
L5_JSON="$PROJECT_DIR/.claude/l5-checkpoint.json"
if [ -f "$L5_JSON" ]; then
  COUNT=$(python3 -c "import json; print(json.load(open('$L5_JSON')).get('batchesSinceLastL5', 0))" 2>/dev/null || echo "0")
  LAST=$(python3 -c "import json; print(json.load(open('$L5_JSON')).get('lastL5Batch', 'unknown'))" 2>/dev/null || echo "unknown")
  if [ "$COUNT" -ge 2 ]; then
    echo ""
    red "  ╔══════════════════════════════════════════════════════════╗"
    red "  ║  🚫 L5 硬阻断 — 超过 2 批未拉通，禁止继续              ║"
    printf "  ║  Last L5: %-48s ║\n" "$LAST"
    printf "  ║  Batches since: %-42d ║\n" "$COUNT"
    red "  ║                                                        ║"
    red "  ║  Action: 执行 L5 拉通 → l5-reset.sh → 重试             ║"
    red "  ╚══════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
  else
    green "  ✅ L5 间隔正常（$LAST, 累积 $COUNT/2）"
  fi
else
  yellow "  ⚠️  .claude/l5-checkpoint.json 不存在 — 跳过 L5 检查（首次？）"
fi
echo ""

# ── 日报存在性检查 ──────────────────────────────────
echo "--- 日报 ---"
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d 2>/dev/null || echo "")
if [ -n "$YESTERDAY" ]; then
  DAILY_FILE="$PROJECT_DIR/docs/daily/${YESTERDAY}.md"
  if [ -f "$DAILY_FILE" ]; then
    green "  ✅ 昨日日报存在 (${YESTERDAY}.md)"
  else
    yellow "  ⚠️  昨日日报缺失 (${YESTERDAY}.md) — 从 git log 补写（不阻断 commit）"
    WARNINGS=$((WARNINGS + 1))
  fi
else
  yellow "  ⚠️  无法计算昨天日期 — 跳过日报检查"
fi
echo ""

# ── 骨架测试检测 ───────────────────────────────────
echo "--- 骨架测试检测 ---"
SKELETON_COUNT=0
for test_file in "$PROJECT_DIR"/tests/test_*.py; do
  [ -f "$test_file" ] || continue
  fname=$(basename "$test_file")
  test_funcs=$(python3 -c "
import ast
with open('$test_file') as f:
    tree = ast.parse(f.read())
funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')]
print(len(funcs))
" 2>/dev/null || echo "0")
  if [ "$test_funcs" -eq 0 ]; then
    yellow "  🦴 $fname 没有 test_* 函数 — 骨架文件待加厚"
    SKELETON_COUNT=$((SKELETON_COUNT + 1))
  fi
done
if [ "$SKELETON_COUNT" -eq 0 ]; then
  green "  ✅ 无骨架测试文件"
else
  yellow "  💀 $SKELETON_COUNT 个骨架测试文件 — 不阻断，但请后续加厚"
  WARNINGS=$((WARNINGS + SKELETON_COUNT))
fi
echo ""

echo "--- 会话 checkpoint ---"
MEM_DIR="$HOME/.claude/projects/-Users-hunter-projects-personal-ai-agent-instances/memory"
LATEST=$(ls -t "$MEM_DIR"/synapse-session-*.md 2>/dev/null | head -1 || echo "")
if [ -z "$LATEST" ]; then
  yellow "  ⚠️  未找到 Synapse 会话 checkpoint — /clear 前请创建"
  WARNINGS=$((WARNINGS + 1))
else
  CP_DATE=$(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' "$LATEST" 2>/dev/null | head -1 || echo "")
  TODAY=$(date +%Y-%m-%d)
  if [ "$CP_DATE" != "$TODAY" ]; then
    yellow "  ⚠️  checkpoint 日期($CP_DATE) ≠ 今天($TODAY) — 建议 /clear 前更新"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ checkpoint 今日已更新 ($LATEST)"
  fi
  if ! grep -q "接头暗号" "$LATEST" 2>/dev/null; then
    yellow "  ⚠️  checkpoint 缺少「接头暗号」字段"
    WARNINGS=$((WARNINGS + 1))
  fi
fi
echo ""

# ── Plan 清理提醒 ──────────────────────────────────
echo "--- Plan 清理 ---"
PLAN_DIR="$PROJECT_DIR/docs/plans"
PLAN_COUNT=0
if [ -d "$PLAN_DIR" ]; then
  plans=$(find "$PLAN_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null || true)
  if [ -n "$plans" ]; then
    PLAN_COUNT=$(echo "$plans" | wc -l | tr -d ' ')
  fi
fi
if [ "$PLAN_COUNT" -gt 0 ]; then
  yellow "  📋 $PLAN_COUNT 个 plan 文件存留 — 已执行的 plan 应移入 docs/archive/"
  WARNINGS=$((WARNINGS + 1))
else
  green "  ✅ docs/plans/ 干净，无需清理"
fi
echo ""

# ── 文件健康诊断 ──────────────────────────────────
echo "--- 文件健康诊断 ---"

# 通用核心文档行数扫描（G25 文档膨胀治理 · P100-B72 落地）
# 阈值: >400 WARNING · >800 ERROR 硬阻断
DOCS_DIR="$PROJECT_DIR/docs"
CRITICAL_DOCS="docs/requirements-log.md docs/roadmap.md docs/architecture.md docs/data-model.md docs/methodology.md docs/master-backlog.md docs/lessons-learned.md docs/pitfalls.md docs/security-model.md docs/prd.md docs/glossary.md docs/onboarding.md"

DOC_BLOAT_ERRORS=0
DOC_BLOAT_WARNINGS=0

for doc in $CRITICAL_DOCS; do
  DOC_PATH="$PROJECT_DIR/$doc"
  if [ -f "$DOC_PATH" ]; then
    DOC_LINES=$(wc -l < "$DOC_PATH" | tr -d ' ')
    DOC_NAME=$(basename "$doc")

    if [ "$DOC_LINES" -gt 800 ]; then
      # requirements-log 是特殊历史日志，阈值放宽到 10000
      if [ "$DOC_NAME" = "requirements-log.md" ]; then
        if [ "$DOC_LINES" -gt 10000 ]; then
          yellow "  ⚠️  $doc $DOC_LINES 行（历史日志阈值 10000）— 需归档旧条目到 docs/archive/"
          DOC_BLOAT_WARNINGS=$((DOC_BLOAT_WARNINGS + 1))
          WARNINGS=$((WARNINGS + 1))
        elif [ "$DOC_LINES" -gt 5000 ]; then
          yellow "  ⚠️  $doc $DOC_LINES 行（历史日志 ≥5000，阈值 10000）— 考虑将已完成 Phase 条目归档"
          DOC_BLOAT_WARNINGS=$((DOC_BLOAT_WARNINGS + 1))
          WARNINGS=$((WARNINGS + 1))
        fi
      else
        red "  ❌ $doc $DOC_LINES 行（硬阻断阈值 800）— 必须拆分或归档"
        DOC_BLOAT_ERRORS=$((DOC_BLOAT_ERRORS + 1))
        ERRORS=$((ERRORS + 1))
      fi
    elif [ "$DOC_LINES" -gt 400 ]; then
      yellow "  ⚠️  $doc $DOC_LINES 行（阈值 400）— 建议拆分过长段到子文档或归档旧内容"
      DOC_BLOAT_WARNINGS=$((DOC_BLOAT_WARNINGS + 1))
      WARNINGS=$((WARNINGS + 1))
    fi
  fi
done

if [ "$DOC_BLOAT_ERRORS" -eq 0 ] && [ "$DOC_BLOAT_WARNINGS" -eq 0 ]; then
  green "  ✅ 核心文档行数均在阈值内"
fi

# CLAUDE.md 行数检查（独立，因为不在 docs/ 下）
CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
CLAUDE_LINES=0
if [ -f "$CLAUDE_MD" ]; then
  CLAUDE_LINES=$(wc -l < "$CLAUDE_MD" | tr -d ' ')
  if [ "$CLAUDE_LINES" -gt 400 ]; then
    yellow "  ⚠️  CLAUDE.md $CLAUDE_LINES 行（阈值 400）— 建议拆分过长段到 methodology.md"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ CLAUDE.md $CLAUDE_LINES 行（≤400）"
  fi
else
  yellow "  ⚠️  CLAUDE.md 不存在"
fi

# master-backlog.md 远期项堆积检查（S-021 门禁 · P100-B29 落地）
BACKLOG_MD="$PROJECT_DIR/docs/master-backlog.md"
BACKLOG_LINES=0
if [ -f "$BACKLOG_MD" ]; then
  BACKLOG_LINES=$(wc -l < "$BACKLOG_MD" | tr -d ' ')

  # 1. 行数检查（>400 WARNING）
  if [ "$BACKLOG_LINES" -gt 400 ]; then
    yellow "  ⚠️  master-backlog.md $BACKLOG_LINES 行（阈值 400）— 建议归档已完成段"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ master-backlog.md $BACKLOG_LINES 行（≤400）"
  fi

  # 2. 远期项计数（S-021 — ≥16 ERROR, ≥13 WARNING）
  # 远期项 = ⬜ 远期 F-XXX + P2 标"远期" + P7 ⬜ + B9-GAP
  FAR_F_COUNT=$(sed -n '/^## ⬜ 远期/,/^---$/p' "$BACKLOG_MD" | grep -c '| F-' || true)
  FAR_P2_COUNT=$(sed -n '/^## 🟡 P2/,/^---$/p' "$BACKLOG_MD" | grep -c '| S-.*远期' || true)
  FAR_P7_COUNT=$(sed -n '/^## 🟡 P7/,/^## P8-B9/p' "$BACKLOG_MD" | grep '| P7-' | grep -c '⬜' || true)
  FAR_B9_COUNT=$(sed -n '/^## P8-B9/,$p' "$BACKLOG_MD" | grep -c '| B9-GAP-' || true)
  FAR_TOTAL=$((FAR_F_COUNT + FAR_P2_COUNT + FAR_P7_COUNT + FAR_B9_COUNT))

  if [ "$FAR_TOTAL" -ge 20 ]; then
    yellow "  ⚠️  远期项 $FAR_TOTAL 条（首部署继承债务，>20 WARNING）— P100-B34 修剪后升级为 ERROR (F:$FAR_F_COUNT P2远:$FAR_P2_COUNT P7⬜:$FAR_P7_COUNT B9:$FAR_B9_COUNT)"
    WARNINGS=$((WARNINGS + 1))
  elif [ "$FAR_TOTAL" -ge 16 ]; then
    yellow "  ⚠️  远期项 $FAR_TOTAL 条（超上限 15）— 建议在下次 P100 修剪 (F:$FAR_F_COUNT P2远:$FAR_P2_COUNT P7⬜:$FAR_P7_COUNT B9:$FAR_B9_COUNT)"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ 远期项 $FAR_TOTAL 条（≤15）"
  fi
  # TODO P100-B34: 首次修剪后将 ≥16 → ERROR 硬阻断

  # 3. ⬜ 项注册日期缺失检查（S-021）— 仅检查有 ID 编号的条目行
  MISSING_DATES=$(grep -E '^\| (M-[0-9]+|P-[0-9]+|S-[0-9]+|P7-[0-9]+)' "$BACKLOG_MD" | grep '⬜' | { grep -v 📅 || true; } | wc -l | tr -d ' ')
  if [ "$MISSING_DATES" -gt 0 ]; then
    yellow "  ⚠️  $MISSING_DATES 条 ⬜ 项缺少注册日期 📅"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ 所有 ⬜ 项均有注册日期 📅"
  fi
else
  yellow "  ⚠️  master-backlog.md 不存在"
fi

# ── 归档目录存在性检查（G25 文档生命周期 · P100-B72 落地）──
ARCHIVE_DIR="$PROJECT_DIR/docs/archive"
if [ -d "$ARCHIVE_DIR" ]; then
  ARCHIVE_COUNT=$(find "$ARCHIVE_DIR" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
  green "  ✅ docs/archive/ 存在（$ARCHIVE_COUNT 个归档文件）"
else
  yellow "  ⚠️  docs/archive/ 目录不存在 — 建议创建以支持文档生命周期归档"
  WARNINGS=$((WARNINGS + 1))
fi
echo ""

# ── CLAUDE.md ↔ methodology.md 交叉引用 (V-011 防呆) ──
# 扫描 CLAUDE.md §1-§15 每条规则 → 检查 methodology.md 映射表是否有对应行
# 映射表位置：methodology.md "CLAUDE.md 铁律/纪律 → 方法论章节映射" 段
echo "--- CLAUDE.md ↔ methodology.md 交叉引用 ---"
CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
METHODOLOGY_MD="$PROJECT_DIR/docs/methodology.md"
METHODOLOGY_REF_MD="$PROJECT_DIR/docs/methodology-reference.md"

# 从 CLAUDE.md 提取规则头 (### N. Rule Name)
CLAUDE_RULES_FILE=$(mktemp)
grep -E '^### [0-9]+\. ' "$CLAUDE_MD" | sed 's/### [0-9]*\. //' > "$CLAUDE_RULES_FILE" 2>/dev/null || true

# 从 methodology.md + methodology-reference.md 映射表提取第一列规则名
# 映射表段：从 "| 铁律 | CLAUDE.md 摘要" 到 "### 代码阶段后建立"
# P100-B75: methodology-reference.md 也纳入扫描（映射表可能在该文件中）
METH_RULES_FILE=$(mktemp)
(sed -n '/^| 铁律 | CLAUDE.md 摘要/,/^### 代码阶段后建立/p' "$METHODOLOGY_MD" 2>/dev/null
 sed -n '/^| 铁律 | CLAUDE.md 摘要/,/^### 代码阶段后建立/p' "$METHODOLOGY_REF_MD" 2>/dev/null) \
  | grep -E '^\| [^|]+\|' \
  | grep -v '^| 铁律 \|^|---' \
  | awk -F'|' '{print $2}' | sed 's/^ *//;s/ *$//' > "$METH_RULES_FILE" 2>/dev/null || true

# 为每条 CLAUDE.md 规则定义应在 methodology 映射表中出现的关键词
# 格式：CLAUDE标题关键词 → methodology映射表检索词（空格分隔，任一命中即匹配）
declare -A RULE_CHECKS
RULE_CHECKS["五层自检"]="五层自检"
RULE_CHECKS["发现即待办"]="发现即待办"
RULE_CHECKS["Batch 隔离"]="Batch 隔离|Batch"
RULE_CHECKS["粒度控制"]="文件数门禁|粒度"
RULE_CHECKS["文档闭环"]="文档闭环"
RULE_CHECKS["日报铁律"]="日报铁律"
RULE_CHECKS["Batch 启动门禁"]="Batch 启动门禁|启动门禁"
RULE_CHECKS["即时澄清"]="即时澄清"
RULE_CHECKS["流程共建"]="流程共建"
RULE_CHECKS["讨论即登记"]="讨论即登记"
RULE_CHECKS["Phase 治理"]="Phase 治理"
RULE_CHECKS["批次顺序前置校验"]="批次顺序|Batch Sequence"
RULE_CHECKS["Plan 分级"]="Plan 分级"
RULE_CHECKS["依赖升级"]="依赖升级"
RULE_CHECKS["流程紧急修复"]="流程紧急修复"

MISSING_RULES=""
MISSING_COUNT=0
MATCHED_COUNT=0

while IFS= read -r rule; do
  [ -z "$rule" ] && continue
  FOUND=false

  # 遍历 RULE_CHECKS 查找匹配的检查模式
  for check_key in "${!RULE_CHECKS[@]}"; do
    if echo "$rule" | grep -qi "$check_key"; then
      # 用检查模式在 methodology 映射表中搜索
      IFS='|' read -ra TERMS <<< "${RULE_CHECKS[$check_key]}"
      for term in "${TERMS[@]}"; do
        if grep -qi "$term" "$METH_RULES_FILE" 2>/dev/null; then
          FOUND=true
          break
        fi
      done
      break
    fi
  done

  if [ "$FOUND" = true ]; then
    MATCHED_COUNT=$((MATCHED_COUNT + 1))
  else
    SHORT_NAME=$(echo "$rule" | cut -c1-40)
    MISSING_RULES="${MISSING_RULES}  · ${SHORT_NAME}\n"
    MISSING_COUNT=$((MISSING_COUNT + 1))
  fi
done < "$CLAUDE_RULES_FILE"

rm -f "$CLAUDE_RULES_FILE" "$METH_RULES_FILE"

if [ "$MISSING_COUNT" -gt 0 ]; then
  echo ""
  yellow "  ┌──────────────────────────────────────────────────────────────┐"
  yellow "  │  ⚠️  V-011 违纪风险：CLAUDE.md 规则未同步到 methodology.md    │"
  yellow "  ├──────────────────────────────────────────────────────────────┤"
  printf "  │  已映射: %-2d 条  ·  缺失: %-2d 条                               │\n" "$MATCHED_COUNT" "$MISSING_COUNT"
  yellow "  │                                                              │"
  yellow "  │  以下 CLAUDE.md 规则在 methodology.md 映射表中缺失：          │"
  printf "$MISSING_RULES"
  yellow "  │                                                              │"
  yellow "  │  Action: 在 methodology.md 或 methodology-reference.md 映射表中补充对应行"
  yellow "  │  映射表位置：§\"CLAUDE.md 铁律/纪律 → 方法论章节映射\"          "
  yellow "  └──────────────────────────────────────────────────────────────┘"
  echo ""
  WARNINGS=$((WARNINGS + 1))
else
  green "  ✅ CLAUDE.md 全部 $MATCHED_COUNT 条规则已在 methodology.md 映射"
fi
echo ""

# ── Shared Module Governance ───────────────────────
echo "--- Shared Module Governance ---"
SHARED_MOD_OUTPUT=$(python3 "$PROJECT_DIR/tools/check_shared_modules.py" 2>&1)
SHARED_MOD_EXIT=$?
# Extract summary line for compact display
echo "$SHARED_MOD_OUTPUT" | grep -E '📊|🔴.*Critical|✅ 所有共享' || true
if [ "$SHARED_MOD_EXIT" -ne 0 ]; then
  yellow "  ⚠️  check_shared_modules exit=$SHARED_MOD_EXIT（详见 make check-shared-modules）"
fi
echo ""

# ── 总结 ────────────────────────────────────────────
echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
  red "❌ $ERRORS 个硬错误 · $WARNINGS 个警告"
  exit 1
else
  green "✅ 文档门禁通过"
  if [ "$WARNINGS" -gt 0 ]; then
    yellow "💡 $WARNINGS 个警告（不阻断，建议关注）"
  fi
fi
