#!/usr/bin/env bash
# post-commit hook — 项目感知的 Batch 计数门禁
# Install: ln -sf ../../synapse/tools/post-commit.sh .git/hooks/post-commit
# 相邻 commit 间隔 >30 min 视为新会话，计数器重置
# 来源: 从 glasscortex tools/post-commit.sh 移植 + 项目感知化 (2026-07-04)

set -euo pipefail

GIT_DIR=$(git rev-parse --git-dir)
NOW=$(date +%s)
SESSION_GAP=1800

LAST_COMMIT=$(git rev-parse HEAD)
CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r "$LAST_COMMIT")
TOUCHES_SYNAPSE=$(echo "$CHANGED_FILES" | grep -c "^synapse/" || true)
TOUCHES_GLASSMIND=$(echo "$CHANGED_FILES" | grep -c "^glasscortex/" || true)

BRANCH=$(git branch --show-current)

count_project() {
  local PROJECT=$1
  local COUNTER_FILE="${GIT_DIR}/batch-counter-${PROJECT}"
  if [ -f "$COUNTER_FILE" ]; then
    read -r COUNT LAST_TS < "$COUNTER_FILE"
    local GAP=$(( NOW - LAST_TS ))
    if [ "$GAP" -gt "$SESSION_GAP" ]; then COUNT=1; else COUNT=$(( COUNT + 1 )); fi
  else
    COUNT=1
  fi
  echo "$COUNT $NOW" > "$COUNTER_FILE"
  echo "$COUNT"
}

echo ""

if [ "$TOUCHES_SYNAPSE" -gt 0 ]; then
  SYNAPSE_COUNT=$(count_project "synapse")
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║  📊 Synapse Batch 计数                                   ║"
  echo "╠══════════════════════════════════════════════════════════╣"
  printf "║  分支: %-48s ║\n" "$BRANCH"
  printf "║  本会话 Batch 数: %-37s ║\n" "$SYNAPSE_COUNT"

  # ── Sync L5 checkpoint (skip during rebase) ─────────────
  # Rebasing replays commits sequentially; modifying a tracked
  # file in post-commit dirties the working tree and conflicts
  # with the next replayed commit touching the same file.
  SYNAPSE_DIR=$(git rev-parse --show-toplevel)/synapse
  L5_CHECKPOINT="$SYNAPSE_DIR/.claude/l5-checkpoint.json"
  IN_REBASE=false
  if [ -d "${GIT_DIR}/rebase-merge" ] || [ -d "${GIT_DIR}/rebase-apply" ]; then
    IN_REBASE=true
  fi
  # COMMIT_MSG 统一在此计算一次（L5 checkpoint + violations 两个 counter 块共用 · B134 去重）
  COMMIT_MSG=$(git log -1 --pretty=%s 2>/dev/null || echo "")
  if [ -f "$L5_CHECKPOINT" ] && [ "$IN_REBASE" = false ]; then
    L5_COMMIT_MSG="$COMMIT_MSG" python3 -c "
import json, os, re
commit_msg = os.environ.get('L5_COMMIT_MSG', '')
is_governance_reset = bool(re.search(r'\bL5\b', commit_msg)) or ('拉通' in commit_msg) or ('违纪回顾' in commit_msg)
with open('$L5_CHECKPOINT') as f:
    data = json.load(f)
if not is_governance_reset:
    data['batchesSinceLastL5'] = data.get('batchesSinceLastL5', 0) + 1
# 治理复位 commit（L5 拉通 / 违纪回顾）本身不 increment — 它 IS 复位点
with open('$L5_CHECKPOINT', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
# B133 (P12-3 脚本化): sync CLAUDE.md counter — post-commit bumped the checkpoint
# but left CLAUDE.md header `counter=N` + status `batchesSinceLastL5=N` one behind,
# causing the pre-commit 三源校验 (check-l5-consistency --critical-only) to drift/block.
# Now they move together. 治理复位 commit（L5 拉通 / 违纪回顾）skips both — it IS the reset point.
if not is_governance_reset:
    new_count = data.get('batchesSinceLastL5', 0)
    claude_md = '$SYNAPSE_DIR/CLAUDE.md'
    if os.path.exists(claude_md):
        with open(claude_md) as f:
            content = f.read()
        updated = re.sub(r'batchesSinceLastL5=[0-9]+', f'batchesSinceLastL5={new_count}', content)
        updated = re.sub(r'counter=[0-9]+', f'counter={new_count}', updated)
        if updated != content:
            with open(claude_md, 'w') as f:
                f.write(updated)
" 2>/dev/null || true
    L5_COUNT=$(python3 -c "import json; print(json.load(open('$L5_CHECKPOINT')).get('batchesSinceLastL5', 0))" 2>/dev/null || echo "?")
    printf "║  L5 累积: %-48s ║\n" "${L5_COUNT}/2"
  elif [ "$IN_REBASE" = true ]; then
    printf "║  L5 累积: (rebase 中跳过)                              ║\n"
  fi

  # ── S-072: Sync violations checkpoint counter ────────────
  # PI-01 fix — batchesSinceLastReview was never incremented,
  # causing check-violations.sh "≥5 batches" hard-gate to
  # never fire.  Increment on non-L5 batches only (violations-review.sh
  # resets it explicitly on review).
  # B134: L5 拉通非业务 batch — 对称于上方 L5 counter skip，不 bump violations counter。
  #   否则 L5 commit + amend 会误 bump（B133 后手工校准 4→1 的根因）。
  VIOLATIONS_CHECKPOINT="$SYNAPSE_DIR/.claude/violations-checkpoint.json"
  if [ -f "$VIOLATIONS_CHECKPOINT" ] && [ "$IN_REBASE" = false ]; then
    V_COMMIT_MSG="$COMMIT_MSG" python3 -c "
import json, os, re
commit_msg = os.environ.get('V_COMMIT_MSG', '')
is_governance_reset = bool(re.search(r'\bL5\b', commit_msg)) or ('拉通' in commit_msg) or ('违纪回顾' in commit_msg)
with open('$VIOLATIONS_CHECKPOINT') as f:
    data = json.load(f)
if not is_governance_reset:
    data['batchesSinceLastReview'] = data.get('batchesSinceLastReview', 0) + 1
with open('$VIOLATIONS_CHECKPOINT', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
" 2>/dev/null || true
  fi

  if [ "$SYNAPSE_COUNT" -ge 2 ]; then
    echo "╠══════════════════════════════════════════════════════════╣"
    if [ "${SYNAPSE_ALLOW_MULTI_BATCH:-0}" = "1" ]; then
      echo "║  ⚠️  Synapse 已累积 ≥2 Batch（逃逸模式，放行）          ║"
      echo "║  🔄 计数器已自动重置                                    ║"
      echo "╚══════════════════════════════════════════════════════════╝"
      rm -f "${GIT_DIR}/batch-counter-synapse"
    else
      echo "║  🚫 Synapse 已累积 ≥2 Batch — V-022 硬阻断              ║"
      echo "╠══════════════════════════════════════════════════════════╣"
      echo "║  同会话不允许连续执行两个 Batch（CLAUDE.md §3）         ║"
      echo "║  请 /clear 重开新会话后再提交。                         ║"
      echo "║  逃逸: SYNAPSE_ALLOW_MULTI_BATCH=1 git commit ...       ║"
      echo "╚══════════════════════════════════════════════════════════╝"
      exit 1
    fi
  else
    echo "║  ✅ 计数正常 (${SYNAPSE_COUNT}/2)                                    ║"
    echo "╚══════════════════════════════════════════════════════════╝"
  fi

  # ── G-007: Fresh-eyes 契约层标记 ───────────────────────
  # 契约变更批（onboarding/protocol/schema/api）必须 fresh-eyes 复审才 close。
  # 检测 commit msg 关键词 → 写 pending marker。若 msg 自证 fresh-eyes → 清 marker。
  FRESH_EYES_KEYWORDS="onboarding|protocol|schema|contract|契约|api\b|API\b"
  MARKER="${GIT_DIR}/synapse-pending-fresh-eyes"

  if echo "$COMMIT_MSG" | grep -iq "fresh-eyes"; then
    if [ -f "$MARKER" ]; then
      rm -f "$MARKER"
      echo ""
      echo -e "\033[32m  ✅ G-007: commit msg 含 'fresh-eyes' → 自动清除 pending marker\033[0m"
    fi
  elif echo "$COMMIT_MSG" | grep -iEq "$FRESH_EYES_KEYWORDS"; then
    echo "$LAST_COMMIT $NOW" > "$MARKER"
    echo ""
    echo -e "\033[33m  ⚠️  G-007: 检测到契约变更（onboarding/protocol/schema/api），fresh-eyes 复审待做\033[0m"
    echo "     Marker: ${MARKER#$(git rev-parse --show-toplevel)/}"
    echo "     完成方式：commit msg 含 'fresh-eyes' 自动清除，或手动 rm marker"
    echo "     参考：docs/lessons-learned.md LL14 · docs/methodology.md §Fresh-eyes"
  fi
fi

if [ "$TOUCHES_GLASSMIND" -gt 0 ]; then
  GC_COUNT=$(count_project "glasscortex")
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║  📊 GlassCortex Batch 计数                               ║"
  echo "╠══════════════════════════════════════════════════════════╣"
  printf "║  分支: %-48s ║\n" "$BRANCH"
  printf "║  本会话 Batch 数: %-37s ║\n" "$GC_COUNT"
  if [ "$GC_COUNT" -ge 2 ]; then
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  ⚠️  GlassCortex 已累积 ≥2 Batch。建议 /clear 重开。    ║"
    echo "║  🔄 计数器已自动重置                                    ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    rm -f "${GIT_DIR}/batch-counter-glasscortex"
  else
    echo "║  ✅ 计数正常 (${GC_COUNT}/2)                                    ║"
    echo "╚══════════════════════════════════════════════════════════╝"
  fi
fi

echo ""
