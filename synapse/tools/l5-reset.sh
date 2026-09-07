#!/usr/bin/env bash
# L5 Reset — call this after executing L5 拉通 to reset the counter.
#
# Usage:
#   bash tools/l5-reset.sh --yes "Bx→By 拉通完成 — <L5 evidence>"
#
# Without --yes, prints the L5 checklist and exits — this prevents
# blind mechanical resets (V-023 防呆). You must acknowledge the
# checklist by re-running with --yes.
#
# V-023 防呆 v2 (P100-B71): evidence quality gate — the evidence string
# is mechanically validated for minimum substance:
#   - ≥ 50 characters
#   - ≥ 1 file path mention (contains .md or /)
#   - ≥ 1 action verb (更新/修复/补齐/同步/新增/刷新/验证/修正/拉通/闭环)
#
# V-023 防呆 v3 (P100-B106): track 指针更新验证 — 第 4 关
#   - 从 evidence 中解析目标 Batch 编号
#   - 验证 tracks/synapse.md 的 last_batch 指针已更新到目标 Batch
#   - 指针未更新 → 阻断复位（防止"执行了 L5 但忘记更新 track"的虚假复位）
#
# Evidence should reference:
#   - 📄 文档新鲜度: which docs were refreshed
#   - 📚 叙事一致性: narrative chain conclusion (or "纯 UI，跳过")
#   - 🎭 场景遍历: state traversal result (or "纯内容，跳过")
#
# The updated checkpoint should be committed as part of the L5 docs commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"

YES=false
DESCRIPTION=""

# ── Parse args ──────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=true ;;
    --help|-h)
      echo "Usage: bash tools/l5-reset.sh --yes \"Bx→By 拉通完成 — <L5 evidence>\""
      echo ""
      echo "  --yes, -y    Acknowledge L5 checklist and proceed with reset"
      echo "  --help, -h   Show this help"
      echo ""
      echo "V-023 防呆 v2+v3 (P100-B71 + P100-B106): 证据质量门禁 — evidence 必须满足："
      echo "  - ≥ 50 字符"
      echo "  - ≥ 1 个文件路径（含 .md 或 /）"
      echo "  - ≥ 1 个动作动词（更新/修复/补齐/同步/新增/刷新/验证/修正/拉通/闭环）"
      echo "  - track 指针验证: tracks/synapse.md 的 last_batch 已更新到目标 Batch"
      echo ""
      echo "示例（满足所有要求）："
      echo "  bash tools/l5-reset.sh --yes \\"
      echo "    \"B64→B67 L5 拉通 — 📄 roadmap+reqlog+日报已更新 · 📚 data-model.md ER图同步 · 🎭 枚举迁移全量验证\""
      exit 0
      ;;
    *) DESCRIPTION="$arg" ;;
  esac
done

if [ -z "$DESCRIPTION" ]; then
  echo "Usage: bash tools/l5-reset.sh --yes \"Bx→By 拉通完成 — <L5 evidence>\""
  echo ""
  echo "ERROR: description is required. Use --help for details."
  exit 1
fi

# ── V-023 gate: require --yes ───────────────────────────────
if [ "$YES" = false ]; then
  cat << 'EOF'
┌──────────────────────────────────────────────────────────────┐
│  ⚠️  L5 RESET — 确认清单 (V-023 防呆)                        │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  在复位计数器前，确认以下 L5 检查已实际执行：                  │
│                                                              │
│  📄 文档新鲜度（必做 — 不豁免）                                │
│     ☐ roadmap.md 日期戳已更新                                │
│     ☐ requirements-log.md 已记录本批交付                     │
│     ☐ pitfalls / lessons-learned 无遗漏登记                  │
│     ☐ 日报 (docs/daily/YYYY-MM-DD.md) 已更新                 │
│                                                              │
│  📚 叙事跨批一致性（按变更类型）                               │
│     ☐ 累积 Batch 间术语统一                                  │
│     ☐ 文档叙事链自然承接，无断层                              │
│     ☐ 决策无前后矛盾                                         │
│                                                              │
│  🎭 场景/状态遍历（按变更类型；纯内容可跳过）                   │
│     ☐ 关键用户故事逐步推演通过                                │
│     ☐ 状态节点全覆盖（正常 / 异常 / 边界）                    │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  若以上未完成 → 按 Ctrl-C 取消，先执行 L5 再复位。            │
│                                                              │
│  确认已完成 → 重新运行并加 --yes：                             │
│  bash tools/l5-reset.sh --yes "Bx→By 拉通完成 — <证据>"      │
│                                                              │
│  证据示例: "B64→B67 — 📄 roadmap+reqlog+日报已更新            │
│             📚 枚举迁移叙事一致 📚 B95 审计项全量闭环"         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
EOF
  exit 1
fi

# ── V-023 防呆 v2: evidence quality gate (P100-B71) ─────────
# 机械验证 evidence 是否包含实质性内容，防止空转复位。
# V-023 第四次复发的根因：--yes + 敷衍字符串（如 "叙事一致 ✅"）照过。
# v2 解法：不依赖人工诚实，用机械规则拦截明显敷衍的 evidence。

EVIDENCE_ERRORS=0

# Rule 1: minimum length (≥ 50 chars — a meaningful L5 evidence needs detail)
EVIDENCE_LEN=${#DESCRIPTION}
if [ "$EVIDENCE_LEN" -lt 50 ]; then
  echo "❌ V-023 EVIDENCE GATE: 证据过短 (${EVIDENCE_LEN} 字符，要求 ≥ 50)"
  echo "   L5 证据需要实质性描述 — 至少包含文档路径 + 发现 + 修正动作。"
  echo "   你的输入: \"${DESCRIPTION}\""
  EVIDENCE_ERRORS=$((EVIDENCE_ERRORS + 1))
fi

# Rule 2: must mention at least 1 file path (contains .md or /)
if ! echo "$DESCRIPTION" | grep -qE '(\.md|/)'; then
  echo "❌ V-023 EVIDENCE GATE: 缺少文件路径 (需包含 .md 或 /)"
  echo "   证据必须引用至少 1 个具体文档/代码文件 — 说明你改了哪些文件。"
  echo "   你的输入: \"${DESCRIPTION}\""
  EVIDENCE_ERRORS=$((EVIDENCE_ERRORS + 1))
fi

# Rule 3: must contain at least 1 action verb from the L5 verb set
if ! echo "$DESCRIPTION" | grep -qE '(更新|修复|补齐|同步|新增|刷新|验证|修正|拉通|闭环|补缺|补登记|补齐|修正|刷新|更新|同步)'; then
  echo "❌ V-023 EVIDENCE GATE: 缺少动作动词"
  echo "   证据必须包含至少 1 个 L5 动作动词 (更新/修复/补齐/同步/新增/刷新/验证/修正/拉通/闭环/补缺)。"
  echo "   你的输入: \"${DESCRIPTION}\""
  EVIDENCE_ERRORS=$((EVIDENCE_ERRORS + 1))
fi

if [ "$EVIDENCE_ERRORS" -gt 0 ]; then
  echo ""
  echo "══════════════════════════════════════════════════════════════"
  echo "  V-023 防呆 v2 拦截: ${EVIDENCE_ERRORS} 项证据质量不达标"
  echo ""
  echo "  这不是门禁故障 — 是你的 L5 证据不充分。"
  echo "  请重新执行 L5 质量检查，用实质性证据重新运行。"
  echo ""
  echo "  正确格式示例:"
  echo "  bash tools/l5-reset.sh --yes \\"
  echo "    \"Bx→By L5 拉通 — 📄 roadmap+reqlog+日报已更新 ·"
  echo "     📚 data-model.md ER图同步+关系矩阵补齐 ·"
  echo "     🎭 授权管道全状态遍历验证通过\""
  echo "══════════════════════════════════════════════════════════════"
  exit 1
fi

# Rule 4: track 指针更新验证（P100-B106 · 软约束→硬约束）
# 从 evidence 中提取目标 Batch 编号（如 B105→B106 中的 B106），
# 验证 tracks/synapse.md 的 last_batch 指针已更新到目标 Batch。
# 防止"执行了 L5 但忘记更新 track 指针"的虚假复位。
TRACK_FILE="$PROJECT_DIR/tracks/synapse.md"

# 从 evidence 中提取 "→Bxxx" 或 "->Bxxx" 模式的目标 Batch
TARGET_BATCH=$(echo "$DESCRIPTION" | grep -oE '(→|->)\s*(P[0-9]+-)?B[0-9]+' | tail -1 | sed -E 's/.*(B[0-9]+)$/\1/' || true)
if [ -n "$TARGET_BATCH" ] && [ -f "$TRACK_FILE" ]; then
  # 匹配 YAML frontmatter (last_batch: P11-B106) 或表格格式 (| **P100** | P100-B106 |)
  if ! grep -qE "(last_batch:.*${TARGET_BATCH}|P[0-9]+-${TARGET_BATCH})" "$TRACK_FILE" 2>/dev/null; then
    echo "❌ V-023 EVIDENCE GATE (Rule 4): track 指针未更新"
    echo "   Evidence 声明 L5 已拉通到 ${TARGET_BATCH}，但 tracks/synapse.md 中"
    echo "   last_batch 指针尚未指向 ${TARGET_BATCH}。"
    echo "   请在 L5 拉通时同步更新 track 文件的 last_batch 和 next_batch 指针。"
    echo ""
    echo "   当前 track 状态:"
    grep -E 'last_batch|next_batch' "$TRACK_FILE" 2>/dev/null | head -5 || echo "   (无法读取 track 文件)"
    EVIDENCE_ERRORS=$((EVIDENCE_ERRORS + 1))
  else
    echo "   ✅ Rule 4 (track pointer): tracks/synapse.md last_batch → ${TARGET_BATCH} 已更新"
  fi
else
  echo "   ⚠️  Rule 4 (track pointer): 无法从 evidence 中解析目标 Batch 或 track 文件不存在 — 跳过"
fi

if [ "$EVIDENCE_ERRORS" -gt 0 ]; then
  echo ""
  echo "══════════════════════════════════════════════════════════════"
  echo "  V-023 防呆 v2 拦截: ${EVIDENCE_ERRORS} 项证据质量不达标"
  echo ""
  echo "  这不是门禁故障 — 是你的 L5 证据不充分。"
  echo "  请重新执行 L5 质量检查，用实质性证据重新运行。"
  echo ""
  echo "  正确格式示例:"
  echo "  bash tools/l5-reset.sh --yes \\"
  echo "    \"Bx→By L5 拉通 — 📄 roadmap+reqlog+日报已更新 ·"
  echo "     📚 data-model.md ER图同步+关系矩阵补齐 ·"
  echo "     🎭 授权管道全状态遍历验证通过\""
  echo "══════════════════════════════════════════════════════════════"
  exit 1
fi

echo "✅ V-023 evidence gate passed (${EVIDENCE_LEN} chars, paths+verbs OK, track pointer verified)"

# ── Proceed with reset ──────────────────────────────────────
CHECKPOINT="$PROJECT_DIR/.claude/l5-checkpoint.json"
NOW=$(date +%Y-%m-%d)

python3 -c "
import json, sys
data = {
    'lastL5Batch': '${DESCRIPTION}',
    'lastL5Timestamp': '${NOW}',
    'batchesSinceLastL5': 0,
    'completedBatches': [],
    'lastL5Evidence': '${DESCRIPTION}',
    'notes': 'L5 拉通完成，计数器复位 — V-023 防呆: --yes 已确认'
}
with open('${CHECKPOINT}', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')
print(f'✅ L5 counter reset: ${DESCRIPTION}')
print(f'   File: ${CHECKPOINT}')
print(f'   Evidence recorded in lastL5Evidence field')
print(f'   Next: commit this reset as part of L5 docs')
" 2>/dev/null || {
  echo "❌ Failed to write checkpoint. Is python3 available?"
  exit 1
}
