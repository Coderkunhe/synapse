#!/usr/bin/env bash
# Synapse 讨论→登记管道 — 孤儿 D-ID 检测
# 来源: P100-B14 — G-005-a 讨论→登记管道建设
# 用法: bash tools/check-discussions.sh
#
# 检查项:
#   1. 🧭 段存在性 — 每个 session memory 是否含 🧭 战略决策登记段
#   2. D-ID 状态扫描 — 🟡/🔴/⬜ 未闭环条目统计
#   3. 目标可达性 — D-ID 的「目标 ID」在目的地文件中是否真实存在
#      （仅对标准 ID 格式做机械验证：P{N}-XXX / G-XXX / P-NNN / LL# / S-XXX）
#   4. 文件级引用 — 目标为 memory 文件名时检查文件是否存在
#
# D4 🧭 段标准格式（5 列）:
#   | D-ID | 内容摘要 | → 目的地 | 目标 ID | 状态 |
#
# 旧格式兼容（3-4 列）:
#   | D-ID | 内容 | → Backlog | 状态 |
#
# 退出码: 始终 0（警告级门禁，不阻断 make check）

set -eo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
MEM_DIR="$HOME/.claude/projects/-Users-hunter-projects-personal-ai-agent-instances/memory"
ERRORS=0
WARNINGS=0
ORPHANS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

# ── 目标文件路径 ──────────────────────────────────────────

MASTER_BACKLOG="$PROJECT_DIR/docs/master-backlog.md"
PITFALLS="$PROJECT_DIR/docs/pitfalls.md"
LESSONS="$PROJECT_DIR/docs/lessons-learned.md"
ROADMAP="$PROJECT_DIR/docs/roadmap.md"
P100_GOVERNANCE="$MEM_DIR/synapse-p100-governance.md"

echo "=== 讨论→登记管道 孤儿 D-ID 检测 ==="
echo ""

# ── 0. 目录存在性 ─────────────────────────────────────────

if [ ! -d "$MEM_DIR" ]; then
  red "  ❌ memory 目录不存在: $MEM_DIR"
  echo "  💡 检查 CLAUDE.md §10 的 memory 路径配置"
  exit 0
fi

# ── 1. 扫描所有 session memory 文件 ──────────────────────

SESSION_FILES=$(ls -t "$MEM_DIR"/synapse-session-*.md 2>/dev/null || true)

if [ -z "$SESSION_FILES" ]; then
  yellow "  ⚠️  未找到 synapse-session-*.md 文件 — 跳过讨论检测"
  exit 0
fi

FILE_COUNT=$(echo "$SESSION_FILES" | wc -l | tr -d ' ')
echo "--- 扫描范围: $FILE_COUNT 个 session memory 文件 ---"
echo ""

# ── 辅助函数 ──────────────────────────────────────────────

# 在文件中搜索目标 ID（单词边界匹配）
target_exists_in() {
  local target_id="$1"
  local file_path="$2"

  [ ! -f "$file_path" ] && return 1

  # 转义特殊字符用于 grep
  local escaped
  escaped=$(echo "$target_id" | sed 's/[.[\*^$()+?{|]/\\&/g')

  if grep -qE "\b${escaped}\b" "$file_path" 2>/dev/null; then
    return 0
  fi
  return 1
}

# 根据目标 ID 模式推断目的地文件
# 返回文件路径，无法推断则返回空
resolve_target_file() {
  local target_id="$1"

  case "$target_id" in
    P[0-9]*-[0-9]*)   echo "$MASTER_BACKLOG" ;;   # P7-005
    S-[0-9]*)          echo "$MASTER_BACKLOG" ;;   # S-013
    G-[0-9]*)          echo "$P100_GOVERNANCE" ;;   # G-005
    P-[0-9][0-9]*)     echo "$PITFALLS" ;;         # P-013
    LL[0-9]*)          echo "$LESSONS" ;;           # LL11
    B[0-9]*)           echo "$ROADMAP" ;;           # B12
    *)                 echo "" ;;
  esac
}

# 检查目标 ID 是否为 memory 文件名（不含路径，如 p8-design-principles）
is_memory_filename() {
  local name="$1"
  # memory 文件名模式: 小写+连字符，以 .md 结尾或不含扩展名
  if echo "$name" | grep -qE '\.md$'; then
    return 0
  fi
  # 不含扩展名的短横线命名（如 p8-design-principles, skill-definition）
  if echo "$name" | grep -qE '^[a-z][a-z0-9-]+$' && [ "${#name}" -gt 5 ]; then
    return 0
  fi
  return 1
}

# ── 2. 逐文件扫描 🧭 段 ──────────────────────────────────

TOTAL_D_IDS=0
CLOSED_D_IDS=0
FILES_WITH_COMPASS=0
FILES_WITHOUT_COMPASS=0

while IFS= read -r session_file; do
  [ -z "$session_file" ] && continue

  BASENAME=$(basename "$session_file")

  # 检查是否含 🧭 段
  if ! grep -q "🧭" "$session_file" 2>/dev/null; then
    FILES_WITHOUT_COMPASS=$((FILES_WITHOUT_COMPASS + 1))
    continue
  fi

  FILES_WITH_COMPASS=$((FILES_WITH_COMPASS + 1))

  # 找到 🧭 段的行号
  COMPASS_LINE=$(grep -n "🧭 战略决策登记" "$session_file" 2>/dev/null | head -1 | cut -d: -f1 || true)
  [ -z "$COMPASS_LINE" ] && continue

  # 从 🧭 行之后提取内容，直到下一个 ## 标题或空行段落结束
  # 使用 awk 提取 🧭 标题后到下一个 ## 之间的内容
  SECTION_CONTENT=$(awk "NR >= $COMPASS_LINE { print }" "$session_file" 2>/dev/null | \
    awk 'NR==1 {print; next} /^## / {exit} {print}' || true)

  # 从 section 中提取表格行（以 | 开头且第一列是 D- 格式）
  TABLE_ROWS=$(echo "$SECTION_CONTENT" | grep -E '^\|' | \
    grep -E '^\|[[:space:]]*D-' | head -40 || true)

  if [ -z "$TABLE_ROWS" ]; then
    yellow "  ⚠️  $BASENAME — 🧭 段存在但无 D-ID 表格行"
    WARNINGS=$((WARNINGS + 1))
    continue
  fi

  # 逐行解析
  while IFS= read -r row; do
    [ -z "$row" ] && continue

    # 跳过表头行
    if echo "$row" | grep -qE '^\|[- ]*D-ID'; then
      continue
    fi
    if echo "$row" | grep -qE '^\|[- ]*内容'; then
      continue
    fi

    # 用 awk 按 | 分隔提取各列（trim 空格）
    COL1=$(echo "$row" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); print $2}' || echo "")
    COL2=$(echo "$row" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $3); print $3}' || echo "")
    COL3=$(echo "$row" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $4); print $4}' || echo "")
    COL4=$(echo "$row" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $5); print $5}' || echo "")
    COL5=$(echo "$row" | awk -F'|' '{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $6); print $6}' || echo "")

    # COL1 必须是 D-XXX 或 D-P{N}-XXX 格式
    DID="$COL1"
    if ! echo "$DID" | grep -qE '^D-'; then
      # 跳过非 D-ID 行（可能是其他表格混入）
      continue
    fi

    TOTAL_D_IDS=$((TOTAL_D_IDS + 1))
    SUMMARY="${COL2:-}"
    DEST_HINT="${COL3:-}"

    # ── 状态检测 ──────────────────────────────────────────
    # 优先从最后一列检测，兼容 3/4/5 列格式
    STATUS=""
    for col in "$COL5" "$COL4" "$COL3"; do
      if echo "$col" | grep -qE '✅'; then
        STATUS="✅"
        break
      elif echo "$col" | grep -qE '🔴'; then
        STATUS="🔴"
        break
      elif echo "$col" | grep -qE '🟡'; then
        STATUS="🟡"
        break
      elif echo "$col" | grep -qE '⬜'; then
        STATUS="⬜"
        break
      fi
    done

    case "$STATUS" in
      ✅)
        CLOSED_D_IDS=$((CLOSED_D_IDS + 1))
        ;;
      🔴)
        red "  🔴 孤儿: $DID — $BASENAME"
        red "        「$SUMMARY」"
        ORPHANS=$((ORPHANS + 1))
        ;;
      🟡)
        yellow "  🟡 待处理: $DID — $BASENAME"
        yellow "        「$SUMMARY」"
        WARNINGS=$((WARNINGS + 1))
        ;;
      ⬜)
        yellow "  ⬜ 未启动: $DID — $BASENAME"
        yellow "        「$SUMMARY」"
        WARNINGS=$((WARNINGS + 1))
        ;;
    esac

    # ── 目标可达性验证 ────────────────────────────────────
    # D4 格式: COL3=→目的地, COL4=目标ID, COL5=状态
    # 旧格式: COL3=→Backlog/P7-005, COL4=状态
    TARGET_ID="$COL4"

    # 如果 COL4 看起来是状态而非目标 ID，尝试 COL3
    if [ -n "$TARGET_ID" ] && echo "$TARGET_ID" | grep -qE '^[✅🟡🔴⬜]'; then
      TARGET_ID="$COL3"
    fi

    # 跳过空目标 ID
    [ -z "$TARGET_ID" ] && continue
    # 跳过纯状态列
    echo "$TARGET_ID" | grep -qE '^[✅🟡🔴⬜]+$' && continue

    # 清理目标 ID（去除状态 emoji 残留文本）
    TARGET_ID=$(echo "$TARGET_ID" | sed 's/[✅🟡🔴⬜].*//' | xargs)

    # 跳过已闭环的 D-ID（✅ 状态不需要验证目标）
    [ "$STATUS" = "✅" ] && continue

    # 尝试标准 ID 模式验证
    DEST_FILE=$(resolve_target_file "$TARGET_ID")

    if [ -n "$DEST_FILE" ]; then
      # 标准 ID 模式 — 机械验证
      if [ ! -f "$DEST_FILE" ]; then
        red "  🔴 目标文件缺失: $DID → $TARGET_ID — $(basename "$DEST_FILE") 不存在"
        ORPHANS=$((ORPHANS + 1))
      elif ! target_exists_in "$TARGET_ID" "$DEST_FILE"; then
        red "  🔴 目标不存在: $DID → $TARGET_ID — 在 $(basename "$DEST_FILE") 中未找到"
        ORPHANS=$((ORPHANS + 1))
      fi
    elif is_memory_filename "$TARGET_ID"; then
      # Memory 文件名引用 — 检查文件是否存在
      if [ -f "$MEM_DIR/${TARGET_ID}.md" ]; then
        : # 文件存在，OK
      elif [ -f "$MEM_DIR/synapse-${TARGET_ID}.md" ]; then
        : # 带 synapse- 前缀也存在
      else
        yellow "  ⚠️  memory 文件未找到: $DID → ${TARGET_ID}.md — $BASENAME"
        WARNINGS=$((WARNINGS + 1))
      fi
    fi

  done <<< "$TABLE_ROWS"

done <<< "$SESSION_FILES"

echo ""

# ── 3. 汇总报告 ──────────────────────────────────────────

echo "--- 扫描汇总 ---"
green "  扫描文件:    $FILE_COUNT"
green "  含 🧭 段:   $FILES_WITH_COMPASS"
if [ "$FILES_WITHOUT_COMPASS" -gt 0 ]; then
  yellow "  缺 🧭 段:   $FILES_WITHOUT_COMPASS"
fi
green "  D-ID 总数:   $TOTAL_D_IDS"
green "  已闭环:      $CLOSED_D_IDS"
if [ "$ORPHANS" -gt 0 ]; then
  red "  🔴 孤儿:     $ORPHANS"
fi
if [ "$WARNINGS" -gt 0 ]; then
  yellow "  ⚠️  警告:    $WARNINGS"
fi
echo ""

# ── 4. 目的地文件存在性 ──────────────────────────────────

echo "--- 目的地文件状态 ---"
for f in "$MASTER_BACKLOG" "$PITFALLS" "$LESSONS" "$ROADMAP" "$P100_GOVERNANCE"; do
  if [ -f "$f" ]; then
    green "  ✅ $(basename "$f")"
  else
    yellow "  ⚠️  $(basename "$f") — 不存在"
  fi
done
echo ""

# ── 5. 缺 🧭 段的文件列表（仅显示最近 10 个） ────────────

if [ "$FILES_WITHOUT_COMPASS" -gt 0 ]; then
  echo "--- 最近 10 个缺少 🧭 段的文件 ---"
  COUNT=0
  while IFS= read -r session_file; do
    [ -z "$session_file" ] && continue
    if ! grep -q "🧭" "$session_file" 2>/dev/null; then
      COUNT=$((COUNT + 1))
      [ "$COUNT" -gt 10 ] && break
      echo "    $(basename "$session_file")"
    fi
  done <<< "$SESSION_FILES"
  if [ "$FILES_WITHOUT_COMPASS" -gt 10 ]; then
    echo "    ... 及其他 $((FILES_WITHOUT_COMPASS - 10)) 个文件"
  fi
  echo ""
fi

# ── 总结 ────────────────────────────────────────────────

echo "========================================="
if [ "$ORPHANS" -gt 0 ]; then
  red "💡 讨论→登记管道: $ORPHANS 个孤儿 D-ID 需要关注"
  echo ""
  echo "  处理步骤:"
  echo "    1. 找到对应 session memory 文件中的 🧭 段"
  echo "    2. 确认讨论是否仍然有效 → 无效则标记 ❌ 已关闭"
  echo "    3. 有效 → 补登记到对应目的地（backlog/pitfalls/lessons/P100）"
  echo "    4. 更新 D-ID 状态为 ✅"
  green "  提示: 这是警告级门禁，不阻断 make check"
elif [ "$WARNINGS" -gt 0 ]; then
  yellow "💡 讨论→登记管道: $WARNINGS 个待处理项"
  green "  提示: 这是警告级门禁，不阻断 make check"
else
  green "✅ 讨论→登记管道: 所有 D-ID 已闭环"
fi

if [ "$FILES_WITHOUT_COMPASS" -gt 0 ]; then
  echo ""
  yellow "💡 $FILES_WITHOUT_COMPASS 个 session memory 缺少 🧭 段"
  echo "   原因: 这些文件在 D4 决策之前创建，当时 🧭 段尚未成为强制格式"
  echo "   行动: 不需要回填历史文件。从 P100-B14 起，新 session memory 必须包含 🧭 段"
fi

# 警告级门禁 — 始终以 0 退出
exit 0
