#!/usr/bin/env bash
# Synapse Agent→Worker 术语一致性扫描
# 来源: P100-B38 / S-023 — 跨文档+跨代码术语一致性扫描器
# 用法: bash tools/check-agent-worker-consistency.sh
#
# 检查项:
#   1. 文档一致性 — docs/*.md 中 agent vs worker 术语混合检测
#   2. 前端 API Client vs UI — client.ts 用 Agent 命名 vs 页面用 Worker 术语
#   3. i18n Key vs Display Value — agents.* namespace 键名 vs Worker 显示文本
#   4. 文件命名 — 含 "agent" 的文件名清单（S-016 重命名范围）
#   5. 后端代码基线 — src/ 中 agent 引用计数（S-016 验证基线）
#
# 退出码: 始终 0（首部署警告级）— TODO: S-016 落地后升级为 exit 1
# ⚡ 首部署为警告，S-016 执行后改为阻断

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
ERRORS=0
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

echo "=== Agent → Worker 术语一致性扫描 ==="
echo ""

# ── 1. 文档一致性 ──────────────────────────────────────────

echo "--- 1. 文档一致性 ---"
echo ""

DOC_DIR="$PROJECT_DIR/docs"
EXCEPTIONS="CHANGELOG.md|requirements-log.md"

DOC_MIXED=0
DOC_CLEAN=0
DOC_TOTAL=0

for f in "$DOC_DIR"/*.md; do
  [ ! -f "$f" ] && continue
  bname=$(basename "$f")

  # 跳过历史记录文件（必然包含两种术语）
  if echo "$bname" | grep -qE "$EXCEPTIONS"; then
    continue
  fi

  AGENT_COUNT=$( { grep -oi '\bagent\b' "$f" 2>/dev/null || true; } | wc -l | tr -d ' ')
  WORKER_COUNT=$( { grep -oi '\bworker\b' "$f" 2>/dev/null || true; } | wc -l | tr -d ' ')

  # 跳过两者都为零的文件
  if [ "$AGENT_COUNT" -eq 0 ] && [ "$WORKER_COUNT" -eq 0 ]; then
    continue
  fi

  DOC_TOTAL=$((DOC_TOTAL + 1))

  # 判断是否混合：两者都存在 AND 少数 > 10% of 多数
  MIXED=0
  RATIO=0
  if [ "$AGENT_COUNT" -gt 0 ] && [ "$WORKER_COUNT" -gt 0 ]; then
    if [ "$AGENT_COUNT" -ge "$WORKER_COUNT" ]; then
      RATIO=$(( WORKER_COUNT * 100 / AGENT_COUNT ))
    else
      RATIO=$(( AGENT_COUNT * 100 / WORKER_COUNT ))
    fi
    if [ "$RATIO" -gt 10 ]; then
      MIXED=1
    fi
  fi

  if [ "$MIXED" -eq 1 ]; then
    yellow "  ⚠️  $bname — 术语混合 (agent:$AGENT_COUNT, worker:$WORKER_COUNT, 少数占比 $RATIO%)"
    DOC_MIXED=$((DOC_MIXED + 1))
    WARNINGS=$((WARNINGS + 1))
  else
    DOMINANT="agent"
    [ "$WORKER_COUNT" -gt "$AGENT_COUNT" ] && DOMINANT="worker"
    green "  ✅ $bname — $DOMINANT 主导 (agent:$AGENT_COUNT, worker:$WORKER_COUNT)"
    DOC_CLEAN=$((DOC_CLEAN + 1))
  fi
done

echo ""
echo "  文档统计: $DOC_TOTAL 个文件 · $DOC_CLEAN 清洁 · $DOC_MIXED 混合"
echo ""

# ── 2. 前端 API Client vs UI 术语 ──────────────────────────

echo "--- 2. 前端 API Client vs UI 术语 ---"
echo ""

CLIENT_TS="$PROJECT_DIR/frontend/src/api/client.ts"
PAGES_DIR="$PROJECT_DIR/frontend/src/pages"

if [ -f "$CLIENT_TS" ]; then
  # 统计 client.ts 中 Agent 命名的函数/类型
  CLIENT_AGENT_FUNCS=$( { grep -oE '\b(fetchAgent|createAgent|suspendAgent|resumeAgent|deleteAgent|agentHandshake|fetchAgents|AgentSummary|AgentDetail|AgentCreatePayload|AgentCreateResponse)\b' "$CLIENT_TS" 2>/dev/null || true; } | wc -l | tr -d ' ')
  CLIENT_WORKER_FUNCS=$( { grep -oE '\b(fetchWorker|createWorker|WorkerSummary|WorkerDetail)\b' "$CLIENT_TS" 2>/dev/null || true; } | wc -l | tr -d ' ')

  echo "  client.ts: $CLIENT_AGENT_FUNCS 个 Agent 命名 · $CLIENT_WORKER_FUNCS 个 Worker 命名"

  if [ "$CLIENT_AGENT_FUNCS" -gt 0 ] && [ "$CLIENT_WORKER_FUNCS" -eq 0 ]; then
    yellow "  ⚠️  client.ts 全部使用 Agent 命名函数（fetchAgent / createAgent / ...）"
    yellow "      页面组件使用 Worker 术语（/workers 路由 · WorkerDetail.tsx · WorkerList.tsx）"
    yellow "      这是预期的 pre-S-016 分裂 — API 层命名待 S-016 统一"
    WARNINGS=$((WARNINGS + 1))
  fi
else
  yellow "  ⚠️  client.ts 不存在 — 跳过前端 Client 检查"
fi

# 统计页面组件中的 Worker 术语
if [ -d "$PAGES_DIR" ]; then
  WORKER_PAGE_FILES=$( { grep -rl '\bWorker\b' "$PAGES_DIR" --include="*.tsx" 2>/dev/null || true; } | while read -r pf; do
    basename "$pf"
  done | sort)
  WORKER_PAGE_COUNT=$(echo "$WORKER_PAGE_FILES" | grep -v '^$' | wc -l | tr -d ' ')

  if [ "$WORKER_PAGE_COUNT" -gt 0 ]; then
    echo "  页面组件: $WORKER_PAGE_COUNT 个文件使用 Worker 术语"
    echo "$WORKER_PAGE_FILES" | while read -r pname; do
      [ -z "$pname" ] && continue
      echo "    - $pname"
    done
  fi
fi

echo ""

# ── 3. i18n Key vs 显示文本 ────────────────────────────────

echo "--- 3. i18n Key vs 显示文本 ---"
echo ""

TRANS_FILE="$PROJECT_DIR/frontend/src/i18n/translations.ts"

if [ -f "$TRANS_FILE" ]; then
  # 提取 agents: { ... } 块中英文值的 Worker 引用
  # 注意: awk range pattern 依赖 translations.ts 的缩进格式（2 空格）
  AGENT_NS_WORKER_VALS=$(awk '/^  agents: \{/,/^  \},/' "$TRANS_FILE" 2>/dev/null | \
    grep -cE "['\"][^'\"]*[Ww]orker[^'\"]*['\"]" || echo "0")
  AGENT_NS_WORKER_VALS=$(echo "$AGENT_NS_WORKER_VALS" | tr -d ' ')

  # 同时统计 agents.* 键数量和 workerDetail.* 键数量
  AGENT_NS_KEYS=$(grep -cE '^\s+[a-zA-Z]+:' "$TRANS_FILE" 2>/dev/null || echo "0")
  AGENT_NS_KEYS=$(echo "$AGENT_NS_KEYS" | tr -d ' ')

  if [ "$AGENT_NS_WORKER_VALS" -gt 0 ]; then
    yellow "  ⚠️  agents.* i18n namespace: $AGENT_NS_WORKER_VALS 个键的显示文本包含 Worker"
    yellow "      这是 known structural inconsistency — 键名用 agents.* 但显示文本用 Worker"
    yellow "      e.g. nav.agents → 'Workers', agents.loading → 'Loading workers...'"
    WARNINGS=$((WARNINGS + 1))
  else
    green "  ✅ i18n agents.* namespace 显示文本与键名一致"
  fi
else
  yellow "  ⚠️  translations.ts 不存在 — 跳过 i18n 检查"
fi

echo ""

# ── 4. 文件命名 — Agent 文件清单 ──────────────────────────

echo "--- 4. 文件命名 — Agent 文件清单（S-016 重命名范围）---"
echo ""

# src/ 中含 "agent" 的文件
AGENT_SRC_FILES=$(find "$PROJECT_DIR/src" -name "*agent*" -type f -not -path "*__pycache__*" 2>/dev/null | while read -r f; do
  echo "  $(echo "$f" | sed "s|$PROJECT_DIR/||")"
done)
AGENT_SRC_COUNT=$(echo "$AGENT_SRC_FILES" | { grep -v '^$' || true; } | wc -l | tr -d ' ')

# tests/ 中含 "agent" 的文件
AGENT_TEST_FILES=$(find "$PROJECT_DIR/tests" -name "*agent*" -type f -not -path "*__pycache__*" 2>/dev/null | while read -r f; do
  echo "  $(echo "$f" | sed "s|$PROJECT_DIR/||")"
done)
AGENT_TEST_COUNT=$(echo "$AGENT_TEST_FILES" | { grep -v '^$' || true; } | wc -l | tr -d ' ')

# tools/ 中含 "agent" 的文件
AGENT_TOOL_FILES=$(find "$PROJECT_DIR/tools" -name "*agent*" -type f 2>/dev/null | while read -r f; do
  echo "  $(echo "$f" | sed "s|$PROJECT_DIR/||")"
done)
AGENT_TOOL_COUNT=$(echo "$AGENT_TOOL_FILES" | { grep -v '^$' || true; } | wc -l | tr -d ' ')

TOTAL_AGENT_FILES=$((AGENT_SRC_COUNT + AGENT_TEST_COUNT + AGENT_TOOL_COUNT))

echo "  src/    $AGENT_SRC_COUNT 个文件:"
if [ "$AGENT_SRC_COUNT" -gt 0 ]; then
  echo "$AGENT_SRC_FILES"
fi
echo ""
echo "  tests/  $AGENT_TEST_COUNT 个文件:"
if [ "$AGENT_TEST_COUNT" -gt 0 ]; then
  echo "$AGENT_TEST_FILES"
fi
echo ""
echo "  tools/  $AGENT_TOOL_COUNT 个文件:"
if [ "$AGENT_TOOL_COUNT" -gt 0 ]; then
  echo "$AGENT_TOOL_FILES"
fi
echo ""
echo "  合计: $TOTAL_AGENT_FILES 个 agent-命名文件 — S-016 需重命名"
echo ""

# ── 5. 后端代码基线 ────────────────────────────────────────

echo "--- 5. 代码基线计数 ---"
echo ""

# src/ 中 agent vs worker 引用
SRC_AGENT=$( { grep -r -o -i '\bagent\b' "$PROJECT_DIR/src" --include="*.py" 2>/dev/null || true; } | wc -l | tr -d ' ')
SRC_WORKER=$( { grep -r -o -i '\bworker\b' "$PROJECT_DIR/src" --include="*.py" 2>/dev/null || true; } | wc -l | tr -d ' ')

# tests/ 中 agent vs worker 引用（信息性，不标记）
TESTS_AGENT=$( { grep -r -o -i '\bagent\b' "$PROJECT_DIR/tests" --include="*.py" 2>/dev/null || true; } | wc -l | tr -d ' ')

# frontend/ 中 agent vs worker 引用
FE_AGENT=$( { grep -r -o -i '\bagent\b' "$PROJECT_DIR/frontend/src" --include="*.ts" --include="*.tsx" 2>/dev/null || true; } | wc -l | tr -d ' ')
FE_WORKER=$( { grep -r -o -i '\bworker\b' "$PROJECT_DIR/frontend/src" --include="*.ts" --include="*.tsx" 2>/dev/null || true; } | wc -l | tr -d ' ')

# docs/ 中 agent vs worker 引用
DOCS_AGENT=$( { grep -r -o -i '\bagent\b' "$PROJECT_DIR/docs" --include="*.md" 2>/dev/null || true; } | wc -l | tr -d ' ')
DOCS_WORKER=$( { grep -r -o -i '\bworker\b' "$PROJECT_DIR/docs" --include="*.md" 2>/dev/null || true; } | wc -l | tr -d ' ')

echo "  区域        agent    worker"
echo "  ─────────  ─────    ──────"
printf "  src/        %-5s    %-5s\n" "$SRC_AGENT" "$SRC_WORKER"
printf "  tests/      %-5s    (跳过)\n" "$TESTS_AGENT"
printf "  frontend/   %-5s    %-5s\n" "$FE_AGENT" "$FE_WORKER"
printf "  docs/       %-5s    %-5s\n" "$DOCS_AGENT" "$DOCS_WORKER"
echo ""

green "  ✅ 基线已记录 — S-016 执行后用于验证重命名一致性"
echo ""

# ── 总结 ──────────────────────────────────────────────────

echo "=========================================="
echo "  Agent → Worker 术语一致性扫描 总结"
echo "=========================================="
echo ""

CONSISTENCY_ISSUES=$WARNINGS
echo "  术语不一致发现: $CONSISTENCY_ISSUES 个"
echo ""

if [ "$CONSISTENCY_ISSUES" -eq 0 ]; then
  green "  ✅ 所有术语使用一致 — 无需干预"
else
  yellow "  ╔══════════════════════════════════════════════════════════╗"
  yellow "  ║  ⚠️  首部署为警告 — S-016 落地后升级为阻断                ║"
  yellow "  ║                                                        ║"
  yellow "  ║  Known split points (pre-S-016):                       ║"
  yellow "  ║  - Backend src/ : uses 'agent' universally             ║"
  yellow "  ║  - Frontend UI  : uses 'Worker' display                ║"
  yellow "  ║  - Frontend API : uses 'Agent' functions               ║"
  yellow "  ║  - i18n keys    : agents.* namespace                   ║"
  yellow "  ║  - Docs         : mixed (depends on document age)      ║"
  yellow "  ║                                                        ║"
  yellow "  ║  Action: S-016 will unify → re-run this scanner        ║"
  yellow "  ╚══════════════════════════════════════════════════════════╝"
fi

echo ""
echo "  基线计数 (agent 引用):"
printf "    src/      %s\n" "$SRC_AGENT"
printf "    tests/    %s\n" "$TESTS_AGENT"
printf "    frontend/ %s (worker: %s)\n" "$FE_AGENT" "$FE_WORKER"
printf "    docs/     %s (worker: %s)\n" "$DOCS_AGENT" "$DOCS_WORKER"
echo ""

# 始终 exit 0 — 首部署警告级
# TODO: S-016 落地后，将下面改为 exit 1（如果 WARNINGS > 0）
green "✅ check-agent-worker-consistency 完成（警告级，不阻断）"
exit 0
