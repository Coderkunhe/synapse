#!/usr/bin/env bash
# check-l5-consistency.sh — L5 五关双向 lattice 机械校验
#
# P100-B115: 替代手工五关校验。实现 CLAUDE.md Rule #2 定义的完整五关:
#   Gate 1: roadmap ↔ reqlog       (双向批覆盖 · 仅活跃 Phase)
#   Gate 2: reqlog ↔ commit        (批→commit 可追溯 · 仅 L5 周期内)
#   Gate 3: commit ↔ checkpoint    (commit 计数 vs batchesSinceLastL5)
#   Gate 4: checkpoint ↔ CLAUDE.md (计数器+引用一致性)
#   Gate 5: CLAUDE.md ↔ roadmap    (Phase 状态+批号对齐)
#
# P13-B3: --critical-only 模式 (三源 counter 一致性 · pre-commit 机械门禁)
#   Gate 4a:  batchesSinceLastL5  (checkpoint ↔ CLAUDE.md status row)
#   Gate 4a-2: counter=           (checkpoint ↔ CLAUDE.md header)
#   Gate 4e:  counter=            (checkpoint ↔ memory/active/*.md)
#
# Usage:
#   bash tools/check-l5-consistency.sh [--strict] [--critical-only]
#   bash tools/check-l5-consistency.sh --skip-l5-check   (bypass)
#   bash tools/check-l5-consistency.sh --memory-dir <path>
#
# Exit codes:
#   0 — 检查通过
#   1 — 发现不一致（--strict 模式，--critical-only counter 不匹配，或 batchesSinceLastL5 ≥ 2 时硬错误）
#   2 — 脚本自身错误

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
STRICT=false
CRITICAL_ONLY=false
SKIP_CHECK=false
MEMORY_DIR=""
WARNINGS=0
ERRORS=0

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=true ;;
    --critical-only) CRITICAL_ONLY=true ;;
    --skip-l5-check) SKIP_CHECK=true ;;
    --memory-dir=*) MEMORY_DIR="${arg#*=}" ;;
    --memory-dir) shift; MEMORY_DIR="$1" ;;
  esac
done

# ── Bypass mechanism (P13-B3) ──────────────────────────────────

if [ "$SKIP_CHECK" = true ] || [ "${SYNAPSE_SKIP_L5_CHECK:-0}" = "1" ]; then
  BYPASS_LOG="$PROJECT_DIR/.claude/l5-check-bypass.log"
  BYPASS_METHOD="flag"
  [ "$SKIP_CHECK" != true ] && BYPASS_METHOD="env"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) skip-l5-check bypass=$BYPASS_METHOD" >> "$BYPASS_LOG" 2>/dev/null || true
  echo -e "[33m⚠️  L5 一致性检查已跳过（--skip-l5-check / SYNAPSE_SKIP_L5_CHECK=1）[0m"
  echo -e "[33m   bypass 已记录: $BYPASS_LOG[0m"
  exit 0
fi

# ── Memory directory resolution (P13-B3) ──────────────────────

if [ -z "$MEMORY_DIR" ]; then
  REPO_ROOT=$(git -C "$PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$PROJECT_DIR")
  MEM_DIR_DERIVED="$HOME/.claude/projects/-$(echo "$REPO_ROOT" | sed 's|^/||; s|/|-|g')/memory"
  MEMORY_DIR="${SYNAPSE_MEM_DIR:-$MEM_DIR_DERIVED}"
fi
ACTIVE_MEM_DIR="$MEMORY_DIR/active"

# ── Source files ─────────────────────────────────────────────────

CHECKPOINT="$PROJECT_DIR/.claude/l5-checkpoint.json"
CLAUDE_MD="$PROJECT_DIR/CLAUDE.md"
ROADMAP="$PROJECT_DIR/docs/roadmap.md"
REQLOG="$PROJECT_DIR/docs/requirements-log.md"
TRACK="$PROJECT_DIR/tracks/synapse.md"

red()    { echo -e "\033[31m$*\033[0m"; }
green()  { echo -e "\033[32m$*\033[0m"; }
yellow() { echo -e "\033[33m$*\033[0m"; }
bold()   { echo -e "\033[1m$*\033[0m"; }

die() { red "FATAL: $*"; exit 2; }
warn() { yellow "  ⚠️  $*"; WARNINGS=$((WARNINGS + 1)); }
err()  { red "  ❌ $*"; ERRORS=$((ERRORS + 1)); }
ok()   { green "  ✅ $*"; }

# P100-B153 (PFL-264): 治理计数器是全局主仓状态 — worktree 里跳过 critical-only 门禁。
# worktree 自带陈旧 .claude/l5-checkpoint.json + CLAUDE.md + memory 副本，
# 三源 counter 在 worktree 里必然不一致 → 门禁反向惩罚守规矩的 Builder。
if [ "$CRITICAL_ONLY" = true ]; then
  GIT_DIR_ABS="$(git -C "$PROJECT_DIR" rev-parse --path-format=absolute --git-dir 2>/dev/null || true)"
  GIT_COMMON_ABS="$(git -C "$PROJECT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [ -n "$GIT_DIR_ABS" ] && [ -n "$GIT_COMMON_ABS" ] && [ "$GIT_DIR_ABS" != "$GIT_COMMON_ABS" ]; then
    yellow "⚠️  git worktree — 治理计数器门禁只作用于主仓，跳过 L5 一致性门禁"
    exit 0
  fi
fi

# ── Helper: safe integer from possibly-multiline grep output ─────
safe_int() {
  local val="$1"
  val=$(echo "$val" | head -1 | tr -d '[:space:]')
  echo "${val:-0}"
}

# ── Prerequisites ────────────────────────────────────────────────

command -v python3 >/dev/null 2>&1 || die "python3 is required"
[ -f "$CHECKPOINT" ] || die "l5-checkpoint.json not found at $CHECKPOINT"
[ -f "$CLAUDE_MD" ]   || die "CLAUDE.md not found"
[ -f "$ROADMAP" ]     || die "roadmap.md not found"
[ -f "$REQLOG" ]      || die "requirements-log.md not found"
[ -f "$TRACK" ]       || die "tracks/synapse.md not found"

# ── Extract checkpoint values ────────────────────────────────────

L5_COUNTER=$(python3 -c "import json; print(json.load(open('$CHECKPOINT'))['batchesSinceLastL5'])" 2>/dev/null) || die "Cannot read batchesSinceLastL5"
L5_LAST_BATCH=$(python3 -c "import json; print(json.load(open('$CHECKPOINT'))['lastL5Batch'])" 2>/dev/null) || die "Cannot read lastL5Batch"
L5_TIMESTAMP=$(python3 -c "import json; print(json.load(open('$CHECKPOINT'))['lastL5Timestamp'])" 2>/dev/null) || die "Cannot read lastL5Timestamp"

# P100-B125: Define TODAY early — used by Gate 3 same-day tolerance
TODAY=$(date +%Y-%m-%d)

# git --since needs a time component for same-day commits
GIT_SINCE="${L5_TIMESTAMP}"
if ! echo "$GIT_SINCE" | grep -q ' '; then
  GIT_SINCE="${GIT_SINCE} 00:00:00"
fi

# ── Detect active phases ─────────────────────────────────────────
# Active = phases in CLAUDE.md status table that are NOT fully closed.
# "全量闭环" = closed (P11). Everything else = active (P12, P100).

ACTIVE_PHASES=""
while IFS= read -r line; do
  ph=$(echo "$line" | grep -oE '\*\*P[0-9]+\*\*' | head -1 | sed 's/\*\*//g')
  if [ -n "$ph" ]; then
    # Skip phases marked as fully closed
    if echo "$line" | grep -q '全量闭环'; then
      continue
    fi
    if [ -z "$ACTIVE_PHASES" ]; then
      ACTIVE_PHASES="$ph"
    elif ! echo "$ACTIVE_PHASES" | grep -q "$ph"; then
      ACTIVE_PHASES="$ACTIVE_PHASES,$ph"
    fi
  fi
done < "$CLAUDE_MD"

# Fallback: also check track file
if [ -z "$ACTIVE_PHASES" ]; then
  while IFS= read -r line; do
    ph=$(echo "$line" | grep -oE '\*\*P[0-9]+\*\*' | head -1 | sed 's/\*\*//g')
    if [ -n "$ph" ] && ! echo "$line" | grep -q '全量闭环'; then
      if [ -z "$ACTIVE_PHASES" ]; then
        ACTIVE_PHASES="$ph"
      elif ! echo "$ACTIVE_PHASES" | grep -q "$ph"; then
        ACTIVE_PHASES="$ACTIVE_PHASES,$ph"
      fi
    fi
  done < "$TRACK"
fi

# P13-B3: detect 🎯 (current focus) phase — these are always active
FOCUS_PHASE=$(grep '🎯' "$CLAUDE_MD" 2>/dev/null | grep -oE '\*\*P[0-9]+' | head -1 | sed 's/\*\*//' || echo "")
if [ -n "$FOCUS_PHASE" ] && ! echo "$ACTIVE_PHASES" | grep -q "$FOCUS_PHASE"; then
  if [ -z "$ACTIVE_PHASES" ]; then
    ACTIVE_PHASES="$FOCUS_PHASE"
  else
    ACTIVE_PHASES="$ACTIVE_PHASES,$FOCUS_PHASE"
  fi
fi

# Last fallback
if [ -z "$ACTIVE_PHASES" ]; then
  ACTIVE_PHASES="P12"
  yellow "无法自动检测活跃 Phase，默认使用 P12"
fi

IFS=',' read -ra PHASE_ARRAY <<< "$ACTIVE_PHASES"

# ── Helper: extract batch IDs from a file (only active phases) ───
# P100-B125: Context-aware extraction.
# - requirements-log.md: anchored to section headers only (^## or ^###)
#   to exclude archive references (> **P100-B14**), supplement text
#   mentions, and inline links.
# - roadmap.md: unanchored (table rows use | P100-B1 | format).
# - Other files: unanchored fallback.
extract_batches() {
  local file="$1"
  local pattern=""
  for ph in "${PHASE_ARRAY[@]}"; do
    pattern="${pattern}${ph}-B[0-9]+|"
  done
  pattern="${pattern%|}"
  if [ -z "$pattern" ]; then
    return 0
  fi
  local basename="${file##*/}"
  if [ "$basename" = "requirements-log.md" ]; then
    # Only section headers — excludes archive refs (blockquotes)
    grep -E "^(##|###) " "$file" 2>/dev/null | grep -oE "$pattern" | sort -u || true
  else
    # Unanchored — works for table rows, inline references, etc.
    grep -oE "$pattern" "$file" 2>/dev/null | sort -u || true
  fi
}

# ── Helper: extract batch IDs from git log since timestamp ───────
extract_commits_since() {
  local since="$1"
  git -C "$PROJECT_DIR" log --since="$since" --format="%s" 2>/dev/null \
    | grep -oE '(P[0-9]+-B[0-9]+)' \
    | sort -u || true
}

echo ""
bold "══════════════════════════════════════════════════════════"
bold "  L5 五关双向 Lattice 一致性检查"
bold "  活跃 Phases: ${ACTIVE_PHASES}"
bold "  Checkpoint: counter=$L5_COUNTER · since=$L5_TIMESTAMP"
bold "══════════════════════════════════════════════════════════"

if [ "$CRITICAL_ONLY" = true ]; then
  echo ""
  bold "  Mode: --critical-only (三源 counter 一致性 · 跳过 Gates 1-3,5)"
else
  # ═══════════════════════════════════════════════════════════════════
  # Gate 1: roadmap ↔ reqlog (双向批覆盖 · 仅活跃 Phase)
# ═══════════════════════════════════════════════════════════════════

echo ""
bold "── Gate 1: roadmap ↔ requirements-log ──"

ROADMAP_BATCHES=$(extract_batches "$ROADMAP")
REQLOG_BATCHES=$(extract_batches "$REQLOG")

ROADMAP_COUNT=$(echo "$ROADMAP_BATCHES" | grep -c 'B[0-9]' 2>/dev/null || echo "0")
ROADMAP_COUNT=$(safe_int "$ROADMAP_COUNT")
REQLOG_COUNT=$(echo "$REQLOG_BATCHES" | grep -c 'B[0-9]' 2>/dev/null || echo "0")
REQLOG_COUNT=$(safe_int "$REQLOG_COUNT")

echo "  活跃 Phase (${ACTIVE_PHASES}) roadmap batch 条目: $ROADMAP_COUNT"
echo "  活跃 Phase (${ACTIVE_PHASES}) requirements-log 条目: $REQLOG_COUNT"

# 1a: roadmap → reqlog
MISSING_IN_REQLOG=0
for batch in $ROADMAP_BATCHES; do
  [ -z "$batch" ] && continue
  if ! grep -q "$batch" "$REQLOG" 2>/dev/null; then
    warn "roadmap 有 $batch 但 requirements-log 缺失"
    MISSING_IN_REQLOG=$((MISSING_IN_REQLOG + 1))
  fi
done
if [ "$MISSING_IN_REQLOG" -eq 0 ] && [ "$ROADMAP_COUNT" -gt 0 ]; then
  ok "roadmap → reqlog: ${ROADMAP_COUNT}/${ROADMAP_COUNT} 全覆盖"
fi

# 1b: reqlog → roadmap
MISSING_IN_ROADMAP=0
for batch in $REQLOG_BATCHES; do
  [ -z "$batch" ] && continue
  if ! grep -q "$batch" "$ROADMAP" 2>/dev/null; then
    warn "reqlog 有 $batch 但 roadmap 缺失"
    MISSING_IN_ROADMAP=$((MISSING_IN_ROADMAP + 1))
  fi
done
if [ "$MISSING_IN_ROADMAP" -eq 0 ] && [ "$REQLOG_COUNT" -gt 0 ]; then
  ok "reqlog → roadmap: ${REQLOG_COUNT}/${REQLOG_COUNT} 全覆盖"
fi

# ═══════════════════════════════════════════════════════════════════
# Gate 2: reqlog ↔ commit (批→commit 可追溯 · 仅最近 L5 周期)
# ═══════════════════════════════════════════════════════════════════

echo ""
bold "── Gate 2: requirements-log ↔ git commits (L5 周期内) ──"

# Only check batches committed since last L5 (current cycle)
COMMIT_BATCHES=$(extract_commits_since "$GIT_SINCE")
COMMIT_COUNT=$(echo "$COMMIT_BATCHES" | grep -c 'B[0-9]' 2>/dev/null || echo "0")
COMMIT_COUNT=$(safe_int "$COMMIT_COUNT")

echo "  commits (since $GIT_SINCE) 中的 batch: $COMMIT_COUNT"

# 2a: commits since L5 → reqlog (every recent batch commit should be in reqlog)
MISSING_IN_REQLOG2=0
for batch in $COMMIT_BATCHES; do
  [ -z "$batch" ] && continue
  if ! grep -q "$batch" "$REQLOG" 2>/dev/null; then
    warn "commit $batch 在 requirements-log 中无对应条目"
    MISSING_IN_REQLOG2=$((MISSING_IN_REQLOG2 + 1))
  fi
done
if [ "$MISSING_IN_REQLOG2" -eq 0 ] && [ "$COMMIT_COUNT" -gt 0 ]; then
  ok "commit → reqlog: ${COMMIT_COUNT}/${COMMIT_COUNT} 全覆盖"
elif [ "$COMMIT_COUNT" -eq 0 ]; then
  echo "  (L5 周期内无 batch commit · 可能刚完成 L5 复位)"
fi

# 2b: reqlog → commit — check batches from current L5 cycle only
# P100-B125: Cache full git log to avoid pipefail+SIGPIPE bug.
# `git log | grep -q` fails under `set -o pipefail`: grep exits 0 on
# first match → git gets SIGPIPE (exit 141) → pipefail returns 141 ≠ 0.
GIT_FULL_LOG=$(git -C "$PROJECT_DIR" log --format="%s" 2>/dev/null || true)
MISSING_COMMIT=0
for batch in $REQLOG_BATCHES; do
  [ -z "$batch" ] && continue
  if ! echo "$COMMIT_BATCHES" | grep -q "$batch" 2>/dev/null; then
    # Check full git history (may predate L5 cycle)
    if echo "$GIT_FULL_LOG" | grep -q "$batch" 2>/dev/null; then
      : # Has commit, just not in current L5 cycle — OK
    else
      warn "reqlog 有 $batch 但 git log 中无对应 commit"
      MISSING_COMMIT=$((MISSING_COMMIT + 1))
    fi
  fi
done
if [ "$MISSING_COMMIT" -eq 0 ]; then
  ok "reqlog → commit: 所有活跃 Phase batch 均可追溯"
fi

# ═══════════════════════════════════════════════════════════════════
# Gate 3: commit ↔ checkpoint (commit 计数 vs batchesSinceLastL5)
# ═══════════════════════════════════════════════════════════════════

echo ""
bold "── Gate 3: git commits ↔ l5-checkpoint.json ──"

TOTAL_COMMITS_SINCE=$(git -C "$PROJECT_DIR" log --since="$GIT_SINCE" --oneline 2>/dev/null | wc -l | tr -d ' ')
TOTAL_COMMITS_SINCE=$(safe_int "$TOTAL_COMMITS_SINCE")
echo "  commits since $GIT_SINCE: $TOTAL_COMMITS_SINCE"
echo "  checkpoint batchesSinceLastL5: $L5_COUNTER"

# Count batch-labeled commits since L5
BATCH_COMMITS=$(git -C "$PROJECT_DIR" log --since="$GIT_SINCE" --format="%s" 2>/dev/null \
  | grep -cE '(P[0-9]+-B[0-9]+)' 2>/dev/null || echo "0")
BATCH_COMMITS=$(safe_int "$BATCH_COMMITS")

echo "  batch-labeled commits (Px-By since L5): $BATCH_COMMITS"

# P100-B125: When L5 reset happened today, same-day commits before the
# reset time are included in the git --since count but NOT in
# batchesSinceLastL5 (which only counts post-reset commits).
# Use a wider tolerance for same-day resets.
if [ "$L5_TIMESTAMP" = "$TODAY" ]; then
  GATE3_TOLERANCE=25
  echo "  (same-day L5 reset: using ±${GATE3_TOLERANCE} tolerance)"
else
  GATE3_TOLERANCE=1
fi
DIFF=$((BATCH_COMMITS - L5_COUNTER))
DIFF_ABS=${DIFF#-}
DIFF_ABS=$(safe_int "$DIFF_ABS")
if [ "$DIFF_ABS" -gt "$GATE3_TOLERANCE" ]; then
  warn "batch 提交数 ($BATCH_COMMITS) vs batchesSinceLastL5 ($L5_COUNTER) 偏差 $DIFF_ABS (容差: $GATE3_TOLERANCE)"
else
  ok "batch 提交数 ($BATCH_COMMITS) ≈ batchesSinceLastL5 ($L5_COUNTER) · 偏差 ≤ ${GATE3_TOLERANCE}"
fi

# 3b: completedBatches 中的 batch 是否都有 commit
COMPLETED=$(python3 -c "
import json
data = json.load(open('$CHECKPOINT'))
print(' '.join(data.get('completedBatches', [])))
" 2>/dev/null || echo "")

if [ -n "$COMPLETED" ] && [ "$COMPLETED" != " " ]; then
  MISSING_CB_COMMIT=0
  for batch in $COMPLETED; do
    [ -z "$batch" ] && continue
    if ! echo "$GIT_FULL_LOG" | grep -q "$batch" 2>/dev/null; then
      warn "completedBatches 有 $batch 但 git log 中无对应 commit"
      MISSING_CB_COMMIT=$((MISSING_CB_COMMIT + 1))
    fi
  done
  if [ "$MISSING_CB_COMMIT" -eq 0 ]; then
    ok "completedBatches: 全部有 git commit 可追溯"
  fi
else
  echo "  (completedBatches 为空，跳过)"
fi
fi  # --critical-only: end of Gates 1-3 skip block

# ═══════════════════════════════════════════════════════════════════
# Gate 4: checkpoint ↔ CLAUDE.md (计数器+引用一致性 · P13-B3 增强: 行号 + header counter + memory)
# ═══════════════════════════════════════════════════════════════════

echo ""
bold "── Gate 4: l5-checkpoint.json ↔ CLAUDE.md ──"

# 4a: batchesSinceLastL5 多文件一致性 (P13-B3: +行号)
CLAUDE_L5_LINE_NUM=$(grep -nE 'batchesSinceLastL5=[0-9]+' "$CLAUDE_MD" 2>/dev/null | head -1 | cut -d: -f1)
CLAUDE_L5=$(grep -oE 'batchesSinceLastL5=[0-9]+' "$CLAUDE_MD" 2>/dev/null | head -1 | sed 's/.*=//' | tr -d '[:space:]')
CLAUDE_L5=$(safe_int "$CLAUDE_L5")
if [ -n "$CLAUDE_L5" ] && [ "$CLAUDE_L5" != "$L5_COUNTER" ]; then
  err "CLAUDE.md:$CLAUDE_L5_LINE_NUM batchesSinceLastL5=$CLAUDE_L5 ≠ checkpoint batchesSinceLastL5=$L5_COUNTER"
elif [ -n "$CLAUDE_L5" ] && [ "$CLAUDE_L5" -eq "$L5_COUNTER" ] 2>/dev/null; then
  ok "CLAUDE.md:$CLAUDE_L5_LINE_NUM batchesSinceLastL5=$CLAUDE_L5 ✓"
else
  warn "未在 CLAUDE.md 中找到 batchesSinceLastL5 声明"
fi

# 4a-2: CLAUDE.md header counter=N 检查 (P13-B3: 捕获 header 漂移)
echo ""
echo "  --- header counter= 检查 ---"
HEADER_COUNTER_LINE=$(head -5 "$CLAUDE_MD" | grep -nE 'counter=[0-9]+' | head -1 || echo "")
if [ -n "$HEADER_COUNTER_LINE" ]; then
  HEADER_COUNTER_LINE_NUM=$(echo "$HEADER_COUNTER_LINE" | cut -d: -f1)
  HEADER_COUNTER=$(echo "$HEADER_COUNTER_LINE" | grep -oE 'counter=[0-9]+' | sed 's/counter=//' | tr -d '[:space:]')
  HEADER_COUNTER=$(safe_int "$HEADER_COUNTER")
  if [ "$HEADER_COUNTER" != "$L5_COUNTER" ]; then
    err "CLAUDE.md:$HEADER_COUNTER_LINE_NUM header counter=$HEADER_COUNTER ≠ checkpoint batchesSinceLastL5=$L5_COUNTER"
  else
    ok "CLAUDE.md:$HEADER_COUNTER_LINE_NUM header counter=$HEADER_COUNTER ✓"
  fi
else
  warn "CLAUDE.md header (line 1-5) 中未找到 counter= 声明"
fi

# 4a-3: CLAUDE.md 所有 counter=N 行全面扫描 (P13-B3)
echo ""
echo "  --- 全面 counter= 扫描 ---"
ALL_COUNTER_LINES=$(grep -nE 'counter=[0-9]+' "$CLAUDE_MD" 2>/dev/null || echo "")
if [ -n "$ALL_COUNTER_LINES" ]; then
  while IFS= read -r hit; do
    [ -z "$hit" ] && continue
    hit_linenum=$(echo "$hit" | cut -d: -f1)
    hit_value=$(echo "$hit" | grep -oE 'counter=[0-9]+' | sed 's/counter=//' | tr -d '[:space:]')
    hit_value=$(safe_int "$hit_value")
    if [ -n "$hit_value" ]; then
      if [ "$hit_value" != "$L5_COUNTER" ]; then
        err "CLAUDE.md:$hit_linenum counter=$hit_value ≠ checkpoint batchesSinceLastL5=$L5_COUNTER"
      else
        ok "CLAUDE.md:$hit_linenum counter=$hit_value ✓"
      fi
    fi
  done <<< "$ALL_COUNTER_LINES"
else
  echo "  (CLAUDE.md 中未找到 counter= 引用)"
fi

# 4e: Memory 文件 counter 校验 (P13-B3: checkpoint ↔ memory/active/*.md)
echo ""
echo "  --- Memory 文件 counter= 校验 ---"
if [ ! -d "$ACTIVE_MEM_DIR" ]; then
  echo "  (memory/active/ 目录不存在: $ACTIVE_MEM_DIR — 跳过)"
else
  MEM_COUNTER_FOUND=false
  for memfile in $ACTIVE_MEM_DIR/*.md; do
    [ -f "$memfile" ] || continue
    memname=$(basename "$memfile")
    # P13-B3: only check counter in active phase files (skip closed phases)
    mem_phase=$(echo "$memname" | grep -oE 'p[0-9]+' || echo "")
    if [ -n "$mem_phase" ]; then
      mem_phase_upper=$(echo "$mem_phase" | tr '[:lower:]' '[:upper:]')
      if ! echo "$ACTIVE_PHASES" | grep -q "$mem_phase_upper"; then
        continue  # Skip closed/inactive phase memory files
      fi
    fi
    while IFS= read -r hit; do
      [ -z "$hit" ] && continue
      hit_linenum=$(echo "$hit" | cut -d: -f1)
      hit_value=$(echo "$hit" | grep -oE 'counter=[0-9]+' | sed 's/counter=//' | tr -d '[:space:]')
      hit_value=$(safe_int "$hit_value")
      if [ -n "$hit_value" ]; then
        MEM_COUNTER_FOUND=true
        if [ "$hit_value" != "$L5_COUNTER" ]; then
          err "memory/active/$memname:$hit_linenum counter=$hit_value ≠ checkpoint batchesSinceLastL5=$L5_COUNTER"
        else
          ok "memory/active/$memname:$hit_linenum counter=$hit_value ✓"
        fi
      fi
    done < <(grep -nE 'counter=[0-9]+' "$memfile" 2>/dev/null || true)
  done
  if [ "$MEM_COUNTER_FOUND" = false ]; then
    echo "  (memory/active/*.md 中未找到 counter= 引用 — 跳过)"
  fi
fi

# 4b: lastL5Batch 在 CLAUDE.md 中被引用
L5_TARGET=$(echo "$L5_LAST_BATCH" | grep -oE 'B[0-9]+' | tail -1 || echo "")
if [ -n "$L5_TARGET" ]; then
  CLAUDE_REF_COUNT=$(grep -c "$L5_TARGET" "$CLAUDE_MD" 2>/dev/null || echo "0")
  CLAUDE_REF_COUNT=$(safe_int "$CLAUDE_REF_COUNT")
  if [ "$CLAUDE_REF_COUNT" -eq 0 ]; then
    warn "CLAUDE.md 未引用 L5 目标批次 $L5_TARGET"
  else
    ok "CLAUDE.md 引用 $L5_TARGET (${CLAUDE_REF_COUNT} 处)"
  fi
fi

# 4c: lastL5Timestamp 新鲜度
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "yesterday" +%Y-%m-%d 2>/dev/null || echo "")
if [ "$L5_TIMESTAMP" = "$TODAY" ] || [ "$L5_TIMESTAMP" = "$YESTERDAY" ]; then
  ok "L5 timestamp: $L5_TIMESTAMP (新鲜)"
else
  warn "L5 timestamp: $L5_TIMESTAMP (非今天/昨天 · 可能 L5 逾期)"
fi

# 4d: Track file pointers
TRACK_P12=$(grep -E '^\| \*\*P12\*\*' "$TRACK" 2>/dev/null | head -1 || echo "")
if [ -n "$TRACK_P12" ]; then
  TRACK_LAST=$(echo "$TRACK_P12" | grep -oE 'P12-B[0-9]+' | head -1 || echo "")
  TRACK_NEXT=$(echo "$TRACK_P12" | grep -oE 'P12-B[0-9]+' | tail -1 || echo "")
  echo "  track P12: last=$TRACK_LAST · next=$TRACK_NEXT"
fi
TRACK_P100=$(grep -E '^\| \*\*P100\*\*' "$TRACK" 2>/dev/null | head -1 || echo "")
if [ -n "$TRACK_P100" ]; then
  P100_LAST=$(echo "$TRACK_P100" | grep -oE 'P100-B[0-9]+' | head -1 || echo "")
  echo "  track P100: last=$P100_LAST"
fi

if [ "$CRITICAL_ONLY" != true ]; then
# ═══════════════════════════════════════════════════════════════════
# Gate 5: CLAUDE.md ↔ roadmap (Phase 状态+批号对齐)
# ═══════════════════════════════════════════════════════════════════

echo ""
bold "── Gate 5: CLAUDE.md ↔ roadmap ──"

# 5a: Each active phase should have a section in roadmap
for ph in "${PHASE_ARRAY[@]}"; do
  phase_num="${ph#P}"
  if grep -q "Phase ${phase_num}" "$ROADMAP" 2>/dev/null || grep -q "$ph " "$ROADMAP" 2>/dev/null; then
    ok "$ph: CLAUDE.md 状态表 ↔ roadmap 章节 存在"
  else
    warn "$ph: CLAUDE.md 有状态表但 roadmap 中未找到对应章节"
  fi
done

# 5b: CLAUDE.md header 版本日期是否新鲜
HEADER_DATE=$(head -5 "$CLAUDE_MD" | grep -oE '20[0-9]{2}-[0-9]{2}-[0-9]{2}' | head -1 || echo "")
if [ -n "$HEADER_DATE" ]; then
  if [ "$HEADER_DATE" = "$TODAY" ]; then
    ok "CLAUDE.md header 日期: $HEADER_DATE (今天)"
  elif [ "$L5_COUNTER" -ge 2 ]; then
    warn "CLAUDE.md header 日期 ($HEADER_DATE) 非今天 · L5 已逾期 · 可能未刷新"
  else
    echo "  CLAUDE.md header 日期: $HEADER_DATE"
  fi
fi

# 5c: L5 status banner in CLAUDE.md should be present
L5_BANNER=$(grep -oE 'batchesSinceLastL5=[0-9]+[^)]*' "$CLAUDE_MD" 2>/dev/null | head -1 || echo "")
if [ -z "$L5_BANNER" ]; then
  warn "CLAUDE.md 缺少 L5 状态 banner · 可能未执行 Rule #2 刷新"
else
  ok "CLAUDE.md L5 banner 存在"
fi
fi  # --critical-only: end of Gate 5 skip block

# ═══════════════════════════════════════════════════════════════════
# P13-B3: --critical-only mode summary (precedes normal summary)
# ═══════════════════════════════════════════════════════════════════

if [ "$CRITICAL_ONLY" = true ]; then
  echo ""
  bold "══════════════════════════════════════════════════════════"
  printf "  L5 三源 counter 一致性结果: "
  if [ "$ERRORS" -gt 0 ]; then
    red "${ERRORS} 错误"
  else
    green "0 错误"
  fi
  printf " · "
  if [ "$WARNINGS" -gt 0 ]; then
    yellow "${WARNINGS} 警告"
  else
    green "0 警告"
  fi
  bold "══════════════════════════════════════════════════════════"

  if [ "$ERRORS" -gt 0 ]; then
    red ""
    red "❌ L5 三源一致性检查未通过 — 发现 ${ERRORS} 项硬错误"
    red "   请修正上述 counter 不一致后重新提交。"
    red "   预期值: batchesSinceLastL5=$L5_COUNTER (来源: l5-checkpoint.json)"
    red "   紧急跳过: SYNAPSE_SKIP_L5_CHECK=1 git commit ..."
    exit 1
  fi

  if [ "$WARNINGS" -gt 0 ]; then
    yellow ""
    yellow "⚠️  L5 三源一致性: ${WARNINGS} 项警告 (非阻断 · 建议修复)"
  fi

  green ""
  green "✅ L5 三源 counter 一致性通过 (checkpoint counter=$L5_COUNTER)"
  exit 0
fi

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════

echo ""
bold "══════════════════════════════════════════════════════════"
printf "  L5 五关一致性结果: "
if [ "$ERRORS" -gt 0 ]; then
  red "${ERRORS} 错误"
else
  green "0 错误"
fi
printf " · "
if [ "$WARNINGS" -gt 0 ]; then
  yellow "${WARNINGS} 警告"
else
  green "0 警告"
fi
bold "══════════════════════════════════════════════════════════"

# Determine exit code
if [ "$ERRORS" -gt 0 ]; then
  red ""
  red "❌ L5 五关检查未通过 — 发现 ${ERRORS} 项硬错误"
  red "   请执行 L5 拉通后再提交。"
  exit 1
fi

# In --strict mode, warnings also fail
if [ "$STRICT" = true ] && [ "$WARNINGS" -gt 0 ]; then
  yellow ""
  yellow "⚠️  L5 五关检查: --strict 模式，${WARNINGS} 项警告视为失败"
  exit 1
fi

# When batchesSinceLastL5 >= 2, treat warnings as errors (L5 is overdue)
if [ "$L5_COUNTER" -ge 2 ] && [ "$WARNINGS" -gt 0 ]; then
  red ""
  red "❌ L5 五关检查未通过 — batchesSinceLastL5=${L5_COUNTER} (>=2) 且存在 ${WARNINGS} 项警告"
  red "   必须先执行 L5 拉通再继续提交。"
  exit 1
fi

if [ "$WARNINGS" -gt 0 ]; then
  yellow ""
  yellow "⚠️  L5 五关检查: ${WARNINGS} 项警告 (非阻断 · 建议在下一 L5 拉通时处理)"
else
  green ""
  green "✅ L5 五关双向 lattice 全部通过"
fi

exit 0
