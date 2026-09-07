#!/usr/bin/env bash
# Synapse 会话 checkpoint — /clear 前自动提醒 + 上下文窗口评估
# 检测条件：当前会话 ≥2 Batch 或 ≥1 小时无 checkpoint
# 用法：bash tools/session-checkpoint.sh
# 来源：从 glasscortex 暗号机制提炼 + 机械防呆
# V-007 防呆（P100-B18）：上下文窗口预估 — batch 计数 + 变更量级估算

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

echo "=== Synapse 会话 checkpoint 检查 ==="
echo ""

# ── 检查是否存在 checkpoint ──────────────────────────
# SYNAPSE_MEM_DIR env var allows test override of memory directory
MEM_DIR="${SYNAPSE_MEM_DIR:-$HOME/.claude/projects/-Users-hunter-projects-personal-ai-synapse/memory}"
LATEST=$(ls -t "$MEM_DIR"/synapse-session-*.md 2>/dev/null | head -1 || echo "")

if [ -z "$LATEST" ]; then
  red "  ❌ 未找到 Synapse 会话 checkpoint"
  echo "  💡 /clear 前请执行："
  echo "     1. 约定接头暗号（如「继续 Synapse 数据模型」）"
  echo "     2. AI 写入 memory/synapse-session-YYYY-MM-DD.md"
  echo "     3. AI 更新 MEMORY.md 索引"
  exit 1
fi

# ── 检查 checkpoint 新鲜度 ───────────────────────────
CHECKPOINT_DATE=$(grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' "$LATEST" 2>/dev/null | head -1 || echo "")
TODAY=$(date +%Y-%m-%d)

if [ "$CHECKPOINT_DATE" != "$TODAY" ]; then
  yellow "  ⚠️  最近 checkpoint 日期($CHECKPOINT_DATE) ≠ 今天($TODAY)"
  echo "  💡 本次会话结束后请更新 checkpoint"
fi

# ── 验证 checkpoint 完整性 ───────────────────────────
if grep -q "接头暗号" "$LATEST" 2>/dev/null; then
  green "  ✅ checkpoint 含接头暗号"
else
  yellow "  ⚠️  checkpoint 缺少「接头暗号」字段 — 新会话无法快速定位"
fi

if grep -q "下一站" "$LATEST" 2>/dev/null; then
  green "  ✅ checkpoint 含下一站方向"
else
  yellow "  ⚠️  checkpoint 缺少「下一站」字段"
fi

# ── 上下文窗口预估（V-007 防呆）──────────────────────
echo ""
echo "--- 上下文窗口预估 ---"

GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || echo "")
BATCH_FILE="${GIT_DIR}/batch-counter-synapse"
SESSION_BATCHES=0
ESTIMATED_TOKENS=0

if [ -n "$GIT_DIR" ] && [ -f "$BATCH_FILE" ]; then
  read -r SESSION_BATCHES _ < "$BATCH_FILE" 2>/dev/null || SESSION_BATCHES=0
fi

# 粗略估算：每 Batch 平均约 3-5 文件 × 200 行 × 讨论往返
# 经验值：1 Batch ≈ 8K-15K tokens 上下文消耗（含 CLAUDE.md + memory + 文件读写 + 讨论）
BATCH_TOKEN_AVG=12000
ESTIMATED_TOKENS=$(( SESSION_BATCHES * BATCH_TOKEN_AVG ))

# 统计本会话的变更量级（辅助判断）
if [ -n "$GIT_DIR" ]; then
  # 找到今天的所有 commit 并统计总变更行数
  TODAY_COMMITS=$(git log --since="$(date +%Y-%m-%d)T00:00:00" --oneline 2>/dev/null | wc -l | tr -d ' ')
  TODAY_LINES=$(git log --since="$(date +%Y-%m-%d)T00:00:00" --shortstat 2>/dev/null \
    | { grep -E 'file|insertion|deletion' || true; } \
    | awk '{ins+=$4; del+=$6} END {print ins+del}' 2>/dev/null)
  TODAY_LINES=${TODAY_LINES:-0}
else
  TODAY_COMMITS=0
  TODAY_LINES=0
fi

printf "  本会话 Batch 数: %s\n" "$SESSION_BATCHES"
printf "  估算上下文消耗: ~%s tokens\n" "$ESTIMATED_TOKENS"
printf "  今日 commits: %s · 变更行数: %s\n" "$TODAY_COMMITS" "$TODAY_LINES"

# 阈值判断（~200K 上下文窗口，50% 为警戒线）
CONTEXT_WARN=100000
CONTEXT_CRITICAL=150000

if [ "$ESTIMATED_TOKENS" -ge "$CONTEXT_CRITICAL" ] 2>/dev/null; then
  red "  🔴 上下文窗口可能已消耗 ~${ESTIMATED_TOKENS} tokens（>75%）"
  echo "  ⚠️  强烈建议立即做 checkpoint + /clear，避免信息丢失"
elif [ "$ESTIMATED_TOKENS" -ge "$CONTEXT_WARN" ] 2>/dev/null; then
  yellow "  🟡 上下文窗口可能已消耗 ~${ESTIMATED_TOKENS} tokens（>50%）"
  echo "  💡 本 Batch 结束后建议 checkpoint + /clear"
elif [ "$SESSION_BATCHES" -ge 2 ] 2>/dev/null; then
  yellow "  🟡 本会话已累积 ${SESSION_BATCHES} Batch"
  echo "  💡 建议在下一个 Batch 前 checkpoint + /clear（参见 CLAUDE.md §3）"
else
  green "  ✅ 上下文窗口充足（${SESSION_BATCHES} Batch, ~${ESTIMATED_TOKENS} tokens）"
fi

# ── V-021 会话执行成本预警 ──────────────────────────
# 补 V-021（会话执行超标）机械门禁：不仅看 token 估算，还看执行密度
# 信号 A：今日 commits 数（已有 TODAY_COMMITS）
# 信号 B：今日累积变更行数（已有 TODAY_LINES）
# 信号 C：今日修改的独立文件数（新增）
echo ""
echo "--- 会话执行成本 (V-021 防呆) ---"

if [ -n "$GIT_DIR" ]; then
  TODAY_FILES=$(git log --since="$(date +%Y-%m-%d)T00:00:00" --name-only --pretty=format: 2>/dev/null \
    | { grep -v '^$' || true; } | sort -u | wc -l | tr -d ' ')
  TODAY_FILES=${TODAY_FILES:-0}
else
  TODAY_FILES=0
fi

printf "  今日 commits: %s · 变更行数: %s · 独立文件: %s\n" "$TODAY_COMMITS" "$TODAY_LINES" "$TODAY_FILES"

# 阈值判断（三级 · 首部署警告级）
V021_WARN=false
V021_CRIT=false
if [ "$TODAY_COMMITS" -ge 6 ] 2>/dev/null \
    || [ "$TODAY_LINES" -ge 1000 ] 2>/dev/null \
    || [ "$TODAY_FILES" -ge 25 ] 2>/dev/null; then
  V021_CRIT=true
elif [ "$TODAY_COMMITS" -ge 4 ] 2>/dev/null \
    || [ "$TODAY_LINES" -ge 500 ] 2>/dev/null \
    || [ "$TODAY_FILES" -ge 15 ] 2>/dev/null; then
  V021_WARN=true
fi

if [ "$V021_CRIT" = true ]; then
  red "  🔴 V-021 违纪风险：会话执行超标（今日 ${TODAY_COMMITS} commits · ${TODAY_LINES} 行 · ${TODAY_FILES} files）"
  echo "     立即做 checkpoint + /clear · 详见 CLAUDE.md §协作纪律 §5"
elif [ "$V021_WARN" = true ]; then
  yellow "  🟡 会话执行密度偏高（今日 ${TODAY_COMMITS} commits · ${TODAY_LINES} 行 · ${TODAY_FILES} files）"
  echo "     建议本 Batch 结束后 checkpoint · 参考 docs/process-violations.md V-021"
else
  green "  ✅ 会话执行密度正常"
fi

# ── L5 状态自检 (V-024 防呆 · P100-B71) ─────────────────
echo ""
echo "--- L5 拉通状态 (V-024 防呆) ---"

L5_CHECKPOINT="$PROJECT_DIR/.claude/l5-checkpoint.json"

if [ -f "$L5_CHECKPOINT" ]; then
  L5_BATCHES=$(python3 -c "
import json
with open('${L5_CHECKPOINT}') as f:
    data = json.load(f)
print(data.get('batchesSinceLastL5', 0))
" 2>/dev/null || echo "?")
  L5_LAST=$(python3 -c "
import json
with open('${L5_CHECKPOINT}') as f:
    data = json.load(f)
print(data.get('lastL5Batch', 'unknown')[:80])
" 2>/dev/null || echo "unknown")

  if [ "$L5_BATCHES" = "?" ]; then
    yellow "  ⚠️  无法读取 L5 checkpoint"
  elif [ "$L5_BATCHES" -ge 2 ] 2>/dev/null; then
    red "  🔴 L5 累积 ${L5_BATCHES}/2 — 必须先执行 L5 拉通再开新 Batch！"
    echo "     上次 L5: ${L5_LAST}"
    echo "     ⚠️  新会话第一步：执行 L5 拉通 → l5-reset.sh → 再开新 Batch"
  elif [ "$L5_BATCHES" -eq 1 ] 2>/dev/null; then
    yellow "  🟡 L5 累积 ${L5_BATCHES}/2 — 本批完成后将触发 L5 拉通"
    echo "     上次 L5: ${L5_LAST}"
  else
    green "  ✅ L5 累积 ${L5_BATCHES}/2 — 计数器正常"
    echo "     上次 L5: ${L5_LAST}"
  fi
else
  yellow "  ⚠️  L5 checkpoint 文件不存在 — 请检查 .claude/l5-checkpoint.json"
fi

echo ""
echo "=== 当前checkpoint ==="
head -20 "$LATEST"
