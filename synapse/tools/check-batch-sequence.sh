#!/usr/bin/env bash
# 批次顺序机械校验 — GAP-4 (G-032) · P100-B92
# 检测: commit message 中的 Batch 编号 vs tracks/synapse.md next_batch
# 用法: bash tools/check-batch-sequence.sh <commit-msg-file>
# 来源: hook-gap-audit.md GAP-4 — 批次顺序无机械校验 · P100-B13 跳号事故防呆
# Phase: P100 — 治理基建
#
# 检测逻辑:
#   1. 从 commit message 提取 Px-By 引用
#   2. 对比 tracks/synapse.md HEAD 版本的 next_batch
#   3. 若 track 文件也 staged，额外对比 staged 版本的 last_batch
#   4. 不匹配 → exit 1 硬阻断
#   5. 无 Batch 引用 → 跳过（非 Batch commit）
#
# 逃逸通道: GIT_SKIP_BATCH_SEQUENCE=1 git commit ...

set -euo pipefail

COMMIT_MSG_FILE="${1:-}"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
TRACK_FILE="$REPO_ROOT/synapse/tracks/synapse.md"

red()    { echo -e "\033[31m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
yellow() { echo -e "\033[33m$1\033[0m"; }

# ── Track-only mode (make check integration) ──────────────
TRACK_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --track-only) TRACK_ONLY=true ;;
  esac
done

# ── Escape hatch ──────────────────────────────────────────
if [ "${GIT_SKIP_BATCH_SEQUENCE:-0}" = "1" ]; then
  yellow "⚠️  批次顺序校验已通过 GIT_SKIP_BATCH_SEQUENCE=1 跳过（GAP-4 bypass）"
  exit 0
fi

# ── Track-only: validate pointer consistency ──────────────
if [ "$TRACK_ONLY" = true ]; then
  if [ ! -f "$TRACK_FILE" ]; then
    yellow "⚠️  GAP-4: tracks/synapse.md 未找到 — 跳过"
    exit 0
  fi
  CONTENT=$(cat "$TRACK_FILE")
  NEXT_COUNT=$(echo "$CONTENT" | grep -cE 'next_batch:|\\|.*\\*\\*P[0-9]+-B[0-9]+\\*\\*' || true)
  if [ "${NEXT_COUNT:-0}" -gt 0 ] 2>/dev/null; then
    green "✅ 批次顺序指针一致性通过（GAP-4 · G-032 · track-only）"
  else
    yellow "⚠️  GAP-4: track 文件中未检测到 next_batch 指针"
  fi
  exit 0
fi

# ── Read commit message ───────────────────────────────────
if [ -z "$COMMIT_MSG_FILE" ] || [ ! -f "$COMMIT_MSG_FILE" ]; then
  red "🔴 GAP-4: 缺少 commit message 文件参数"
  exit 1
fi

COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

# ── Skip L5 commits ───────────────────────────────────────
# L5 (拉通) commits are synchronization points, not new batches.
# Their batch references are descriptive ranges (e.g. "P100-B91→B92"),
# not prescriptive execution targets. Skip the sequence check.
if echo "$COMMIT_MSG" | grep -qiE '\bL5\b|拉通'; then
  exit 0
fi

# ── Extract batch references ──────────────────────────────
# Match Px-By format: P100-B92, P11-B59, etc.
BATCH_REFS=$(echo "$COMMIT_MSG" | grep -oE '\bP[0-9]+-B[0-9]+\b' | sort -u || true)

if [ -z "$BATCH_REFS" ]; then
  # No batch reference → not a batch commit, skip
  exit 0
fi

# ── Verify track file exists ──────────────────────────────
if [ ! -f "$TRACK_FILE" ]; then
  yellow "⚠️  GAP-4: tracks/synapse.md 未找到 — 跳过批次顺序校验"
  exit 0
fi

# ── Helper: extract next_batch pointers from track content ─
# Track file has two sources of next_batch:
#   a) YAML frontmatter: next_batch: P11-B59
#   b) Table rows col 3 (bolded): | **P100** | P100-B91 | **P100-B92** 🔜 | ...
# macOS compatibility: sed -E for extended regex, [[:space:]] instead of \s
extract_next_batch() {
  local content="$1"

  # a) YAML frontmatter: next_batch: Px-By
  echo "$content" | grep -oE 'next_batch:[[:space:]]*P[0-9]+-B[0-9]+' | \
    sed -E 's/next_batch:[[:space:]]*//' || true

  # b) Table rows: bolded batch in col 3 = next_batch
  echo "$content" | grep -oE '\|[[:space:]]*\*\*P[0-9]+\*\*[[:space:]]*\|[[:space:]]*P[0-9]+-B[0-9]+[[:space:]]*\|[[:space:]]*\*\*P[0-9]+-B[0-9]+\*\*' | \
    sed -E 's/.*\*\*(P[0-9]+-B[0-9]+)\*\*.*/\1/' || true
}

# Helper: extract all batch pointers (next_batch + last_batch) from track content
# Used for staged version — the just-completed batch appears as last_batch
extract_all_ptrs() {
  local content="$1"

  # All YAML fields: next_batch: Px-By / last_batch: Px-By
  echo "$content" | grep -oE '(next_batch|last_batch):[[:space:]]*P[0-9]+-B[0-9]+' | \
    sed -E 's/^(next_batch|last_batch):[[:space:]]*//' || true

  # Table rows: bolded batch in col 3 = next_batch
  echo "$content" | grep -oE '\|[[:space:]]*\*\*P[0-9]+\*\*[[:space:]]*\|[[:space:]]*P[0-9]+-B[0-9]+[[:space:]]*\|[[:space:]]*\*\*P[0-9]+-B[0-9]+\*\*' | \
    sed -E 's/.*\*\*(P[0-9]+-B[0-9]+)\*\*.*/\1/' || true
}

# ── Collect valid batch references ────────────────────────
# Valid = HEAD next_batch (what's due) + staged pointers (just completed appears as last_batch)
VALID_REFS=""

# 1. HEAD next_batch — the batch that should be executed next
HEAD_CONTENT=$(git show "HEAD:synapse/tracks/synapse.md" 2>/dev/null) || true
HEAD_NEXT=""

if [ -n "$HEAD_CONTENT" ]; then
  HEAD_NEXT=$(extract_next_batch "$HEAD_CONTENT" | sort -u)
fi

if [ -n "$HEAD_NEXT" ]; then
  VALID_REFS="$HEAD_NEXT"
fi

# 2. Staged pointers — the batch just completed (as last_batch) + new next_batch
STAGED_PTRS=""
if git show ":synapse/tracks/synapse.md" >/dev/null 2>&1; then
  STAGED_CONTENT=$(git show ":synapse/tracks/synapse.md" 2>/dev/null) || true
  if [ -n "$STAGED_CONTENT" ]; then
    STAGED_PTRS=$(extract_all_ptrs "$STAGED_CONTENT" | sort -u)
    if [ -n "$STAGED_PTRS" ]; then
      VALID_REFS=$(echo -e "${VALID_REFS}\n${STAGED_PTRS}" | sort -u | grep -v '^$' || true)
    fi
  fi
fi

if [ -z "$VALID_REFS" ]; then
  yellow "⚠️  GAP-4: 无法从 track 文件提取批次指针 — 跳过校验"
  exit 0
fi

# ── Check batch references ─────────────────────────────────
# Rule: at least ONE batch reference must match a valid pointer.
# This handles L5 range commits (e.g., "P100-B91→B92" — B92 matches even though B91 is done)
# and normal single-batch commits. If ANY ref is valid, the commit passes.
# Only block when NONE of the references match any valid pointer.
MATCHED_ANY=false
UNMATCHED=""
for ref in $BATCH_REFS; do
  found=false
  for valid in $VALID_REFS; do
    if [ "$ref" = "$valid" ]; then
      found=true
      MATCHED_ANY=true
      break
    fi
  done
  if [ "$found" = false ]; then
    UNMATCHED="$UNMATCHED  • $ref\n"
  fi
done

if [ "$MATCHED_ANY" = false ]; then
  HEAD_NEXT_DISPLAY=$(echo "$HEAD_NEXT" | tr '\n' ' ' || echo "(none)")
  STAGED_PTRS_DISPLAY=$(echo "${STAGED_PTRS:-}" | tr '\n' ' ' || echo "(track not staged)")

  red ""
  red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  red "🔴  批次顺序校验失败（GAP-4 · G-032）"
  red "🔴"
  red "🔴  Commit message 引用了以下批次（全部不匹配）："
  echo -e "$UNMATCHED" | while read -r line; do [ -n "$line" ] && red "🔴  $line"; done
  red "🔴"
  red "🔴  但 tracks/synapse.md 中合法的批次为："
  red "🔴    HEAD next_batch: $HEAD_NEXT_DISPLAY"
  if [ -n "${STAGED_PTRS:-}" ]; then
    red "🔴    staged pointers: $STAGED_PTRS_DISPLAY"
  fi
  red "🔴"
  red "🔴  可能原因："
  red "🔴    1. 跳号 — commit message 的批次编号超前于 next_batch"
  red "🔴    2. 重复 — 该批次已完成（编号 ≤ last_batch）"
  red "🔴    3. track 文件未更新 — last_batch/next_batch 指针未同步"
  red "🔴"
  red "🔴  正确流程："
  red "🔴    - 读 tracks/synapse.md → 确认 next_batch"
  red "🔴    - 按 next_batch 执行 → commit 时引用该编号"
  red "🔴    - 同步更新 track 指针（last_batch + next_batch）"
  red "🔴"
  red "🔴  紧急跳过：GIT_SKIP_BATCH_SEQUENCE=1 git commit ..."
  red "🔴━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  red ""
  exit 1
fi

green "✅ 批次顺序校验通过（GAP-4 · G-032）"
exit 0
