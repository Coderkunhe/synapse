#!/usr/bin/env bash
# Synapse Batch 编号连续性检查
# 来源: P5-B14 — GlassCortex 制度审计 E5 + LRN-2026-057 防呆三原则
# 用法: bash tools/check-batch-numbers.sh
#
# 检查项:
#   1. 连续性 — 编号无跳号（跨 Phase 纯数字递增）
#   2. 无重复 — 同一编号不在多处定义
#   3. 无子编号 — 拒绝 Batch Na/Nb、Px-By[a-z]、Px-By.a 模式（含 plan 文件 + 全局 .claude/plans）
#   4. 跨文档一致 — roadmap + requirements-log + CLAUDE.md 最大 Batch 对齐
#   5. roadmap 覆盖 — roadmap.md 是否包含所有已交付 Batch（warning）
#   6. Phase 覆盖 — roadmap.md 是否缺整个 Phase（warning）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
STAGED_MODE=0
if [ "${1:-}" = "--staged" ]; then
  STAGED_MODE=1
fi
ERRORS=0
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

# ── staged 模式：只扫 staged 内容子编号（V-008 防呆 · P100-B169）──────
# 真根因：check-batch-numbers 之前只接 `make check`（手动），未接 commit 门禁，
# 且 SCAN_FILES 缺 pitfalls/tracks/daily → V-008 第3次复发（字母后缀子编号落文档漏网）。
# 此处扫 `git diff --cached` 新增行，覆盖所有文件 + 补裸「B<数字><字母>」模式。
check_staged_subnumbers() {
  local sub_found=0
  local pattern='\b(Batch [0-9]+[a-z]|P[0-9]+-B[0-9]+[a-z]|P[0-9]+-B[0-9]+\.[a-z]|B[0-9]+[a-z])\b'
  local staged_files
  staged_files=$(git diff --cached --name-only 2>/dev/null || echo "")
  if [ -z "$staged_files" ]; then
    green "  ✅ 无 staged 变更 — 跳过子编号检查"
    return 0
  fi
  for f in $staged_files; do
    local added
    added=$(git diff --cached -- "$f" 2>/dev/null | grep -E '^\+' | grep -vE '^\+\+\+' || true)
    if [ -z "$added" ]; then
      continue
    fi
    local hits
    hits=$(echo "$added" | grep -oE "$pattern" 2>/dev/null | sort -u || true)
    if [ -n "$hits" ]; then
      while IFS= read -r h; do
        red "  ❌ 子编号发现: $h (in $f)"
        ERRORS=$((ERRORS + 1))
        sub_found=1
      done <<< "$hits"
    fi
  done
  if [ "$sub_found" -eq 0 ]; then
    green "  ✅ staged 内容无子编号"
  fi
}

if [ "$STAGED_MODE" -eq 1 ]; then
  echo "=== Batch 子编号检查（staged 模式）==="
  echo ""
  check_staged_subnumbers
  echo ""
  if [ "$ERRORS" -gt 0 ]; then
    red "❌ staged 子编号检查: $ERRORS 个硬错误"
    exit 1
  fi
  green "✅ staged 子编号检查通过"
  exit 0
fi

echo "=== Batch 编号连续性 ==="
echo ""

# ── 1. 从各文档提取 Batch 编号 ──────────────────────────

extract_batches_from_roadmap() {
  # 匹配三种格式: | Phase N Batch M | / | Batch N | / Px-By
  grep -oE '\b(Phase [0-9]+ Batch [0-9]+|Batch [0-9]+|P[0-9]+-B[0-9]+)\b' \
    "$PROJECT_DIR/docs/roadmap.md" 2>/dev/null | \
    grep -oE '[0-9]+$' | sort -n | uniq || true
}

extract_batches_from_reqlog() {
  # 匹配 section headers: ## Phase N Batch M: / ## Batch N:
  grep -oE '^## (Phase [0-9]+ )?Batch [0-9]+' \
    "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | \
    grep -oE '[0-9]+$' | sort -n | uniq || true
}

extract_batches_from_claude() {
  # 匹配"当前状态"段中 ✅ 完成 的 Phase N Batch M 行
  # 只提取已完成批次，过滤掉 Px-By 格式（可能是 planned 而非 completed）
  sed -n '/^## 当前状态/,/^---$/p' "$PROJECT_DIR/CLAUDE.md" 2>/dev/null | \
    grep '✅' | \
    grep -oE '\bPhase [0-9]+ Batch [0-9]+\b' | \
    grep -oE '[0-9]+$' | sort -n | uniq || true
}

ROADMAP_BATCHES=$(extract_batches_from_roadmap)
REQLOG_BATCHES=$(extract_batches_from_reqlog)
CLAUDE_BATCHES=$(extract_batches_from_claude)

# ── 2. 检查子编号 ──────────────────────────────────────

echo "--- 子编号检查 ---"
SUB_FOUND=0

# Regex patterns for illegal sub-numbering:
#   1. Batch Na / Batch Nb          (e.g. "Batch 6a" — old format)
#   2. Px-By[a-z]                   (e.g. "P3-B6a" — Phase.Batch format)
#   3. Px-By.a / Px-By.b            (e.g. "P3-B6.a" — dotted variant)
SUB_PATTERN1='\bBatch [0-9]+[a-z]\b'
SUB_PATTERN2='\bP[0-9]+-B[0-9]+[a-z]\b'
SUB_PATTERN3='\bP[0-9]+-B[0-9]+\.[a-z]\b'

# Files to scan (project docs + plan files + CLAUDE.md)
SCAN_FILES=(
  "$PROJECT_DIR/docs/roadmap.md"
  "$PROJECT_DIR/docs/requirements-log.md"
  "$PROJECT_DIR/CLAUDE.md"
)

# Also scan plan files if the directory exists
if [ -d "$PROJECT_DIR/docs/plans" ]; then
  while IFS= read -r -d '' f; do
    SCAN_FILES+=("$f")
  done < <(find "$PROJECT_DIR/docs/plans" -name "*.md" -print0 2>/dev/null)
fi

# Also scan .claude/plans (Claude's plan dir, may be symlink)
CLAUDE_PLANS_DIR="$PROJECT_DIR/.claude/plans"
if [ -d "$CLAUDE_PLANS_DIR" ]; then
  while IFS= read -r -d '' f; do
    SCAN_FILES+=("$f")
  done < <(find "$CLAUDE_PLANS_DIR" -name "*.md" -print0 2>/dev/null)
fi

# Also scan global Claude plans at $HOME/.claude/plans (plan files live here)
GLOBAL_PLANS_DIR="${HOME}/.claude/plans"
if [ -d "$GLOBAL_PLANS_DIR" ]; then
  while IFS= read -r -d '' f; do
    SCAN_FILES+=("$f")
  done < <(find "$GLOBAL_PLANS_DIR" -name "*.md" -print0 2>/dev/null)
fi

for f in "${SCAN_FILES[@]}"; do
  if [ -f "$f" ]; then
    for pattern in "$SUB_PATTERN1" "$SUB_PATTERN2" "$SUB_PATTERN3"; do
      hits=$(grep -oE "$pattern" "$f" 2>/dev/null || true)
      if [ -n "$hits" ]; then
        for h in $hits; do
          red "  ❌ 子编号发现: $h (in $(basename "$f"))"
          ERRORS=$((ERRORS + 1))
          SUB_FOUND=1
        done
      fi
    done
  fi
done
if [ "$SUB_FOUND" -eq 0 ]; then
  green "  ✅ 无子编号"
fi
echo ""

# ── 3. 合并所有文档的 Batch 编号，检查连续性 ────────────

echo "--- 编号连续性 ---"

# 收集所有已完成 Batch（从 reqlog: ✅ 标记的批次）
COMPLETED_BATCHES=$(grep -B1 '✅ 完成' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | \
  grep -oE 'Batch [0-9]+' | grep -oE '[0-9]+' | sort -n | uniq || true)

# 收集所有已知 Batch（从所有文档）
ALL_BATCHES=$(echo -e "$ROADMAP_BATCHES\n$REQLOG_BATCHES\n$CLAUDE_BATCHES" | sort -n | uniq | grep -v '^$' || true)

if [ -z "$ALL_BATCHES" ]; then
  yellow "  ⚠️  未找到任何 Batch 编号 — 跳过连续性检查"
else
  # 检查跳号
  PREV=0
  FIRST=1
  for n in $ALL_BATCHES; do
    if [ "$FIRST" -eq 1 ]; then
      FIRST=0
    else
      EXPECTED=$((PREV + 1))
      if [ "$n" -ne "$EXPECTED" ]; then
        yellow "  ⚠️  跳号: Batch $PREV → Batch $n (缺 Batch $EXPECTED)"
        WARNINGS=$((WARNINGS + 1))
      fi
    fi
    PREV=$n
  done
  green "  ✅ 已分析 $(echo "$ALL_BATCHES" | wc -l | tr -d ' ') 个 Batch 编号"
fi
echo ""

# ── 4. 检查重复（每个文档内部） ──────────────────────

echo "--- 重复检查 ---"
DUP_FOUND=0
for source in "roadmap" "requirements-log" "CLAUDE.md"; do
  case $source in
    roadmap) L="$ROADMAP_BATCHES" ;;
    requirements-log) L="$REQLOG_BATCHES" ;;
    CLAUDE.md) L="$CLAUDE_BATCHES" ;;
  esac
  DUPS=$(echo "$L" | grep -v '^$' | sort -n | uniq -d || true)
  if [ -n "$DUPS" ]; then
    red "  ❌ $source 内部重复 Batch 编号: $DUPS"
    ERRORS=$((ERRORS + 1))
    DUP_FOUND=1
  fi
done
if [ "$DUP_FOUND" -eq 0 ]; then
  green "  ✅ 各文档内部无重复编号"
fi
echo ""

# ── 5. 跨文档一致性 ────────────────────────────────────

echo "--- 跨文档一致性 ---"
MAX_REQLOG=$(echo "$REQLOG_BATCHES" | tail -1 2>/dev/null)
MAX_REQLOG=${MAX_REQLOG:-0}
MAX_CLAUDE=$(echo "$CLAUDE_BATCHES" | tail -1 2>/dev/null)
MAX_CLAUDE=${MAX_CLAUDE:-0}

if [ "$MAX_REQLOG" != "0" ] && [ "$MAX_CLAUDE" != "0" ]; then
  if [ "$MAX_REQLOG" -gt "$MAX_CLAUDE" ]; then
    yellow "  ⚠️  requirements-log 最大 Batch ($MAX_REQLOG) > CLAUDE.md ($MAX_CLAUDE) — CLAUDE.md 可能需更新"
    WARNINGS=$((WARNINGS + 1))
  elif [ "$MAX_CLAUDE" -gt "$MAX_REQLOG" ]; then
    yellow "  ⚠️  CLAUDE.md 最大 Batch ($MAX_CLAUDE) > requirements-log ($MAX_REQLOG) — requirements-log 可能需更新"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ requirements-log ($MAX_REQLOG) ↔ CLAUDE.md ($MAX_CLAUDE) 一致"
  fi
fi
echo ""

# ── 6. roadmap 覆盖检查 ─────────────────────────────────

echo "--- roadmap 覆盖 ---"
ROADMAP_MAX=$(echo "$ROADMAP_BATCHES" | tail -1 2>/dev/null || echo "0")
if [ "$ROADMAP_MAX" != "0" ] && [ "$MAX_REQLOG" != "0" ]; then
  if [ "$ROADMAP_MAX" -lt "$MAX_REQLOG" ]; then
    yellow "  ⚠️  roadmap.md 最大 Batch ($ROADMAP_MAX) 落后于 requirements-log ($MAX_REQLOG)"
    yellow "     requirements-log 中有但 roadmap 缺失的 Batch:"
    for b in $REQLOG_BATCHES; do
      if ! echo "$ROADMAP_BATCHES" | grep -q "^${b}$" 2>/dev/null; then
        yellow "       Batch $b"
      fi
    done
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ roadmap 覆盖完整"
  fi
else
  yellow "  ⚠️  数据不足 — 跳过 roadmap 覆盖检查"
fi
echo ""

# ── 7. Phase 覆盖检查 ──────────────────────────────────

echo "--- Phase 覆盖 ---"
# 从 requirements-log 提取 Phase 编号
PHASES_IN_REQLOG=$(grep -oE 'Phase [0-9]+' "$PROJECT_DIR/docs/requirements-log.md" 2>/dev/null | \
  grep -oE '[0-9]+' | sort -n | uniq || true)
PHASES_IN_ROADMAP=$(grep -oE 'Phase [0-9]+' "$PROJECT_DIR/docs/roadmap.md" 2>/dev/null | \
  grep -oE '[0-9]+' | sort -n | uniq || true)

if [ -n "$PHASES_IN_REQLOG" ] && [ -n "$PHASES_IN_ROADMAP" ]; then
  MISSING_PHASES=""
  for p in $PHASES_IN_REQLOG; do
    if ! echo "$PHASES_IN_ROADMAP" | grep -q "^${p}$" 2>/dev/null; then
      MISSING_PHASES="$MISSING_PHASES Phase $p"
    fi
  done
  if [ -n "$MISSING_PHASES" ]; then
    yellow "  ⚠️  roadmap.md 缺 Phase:$MISSING_PHASES"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ roadmap 包含所有 Phase"
  fi
else
  yellow "  ⚠️  数据不足 — 跳过 Phase 覆盖检查"
fi
echo ""

# ── 总结 ────────────────────────────────────────────────

echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
  red "❌ Batch 编号检查: $ERRORS 个硬错误 · $WARNINGS 个警告"
  exit 1
else
  green "✅ Batch 编号检查通过"
  if [ "$WARNINGS" -gt 0 ]; then
    yellow "💡 $WARNINGS 个警告（不阻断，建议关注）"
  fi
fi
