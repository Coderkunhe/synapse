#!/usr/bin/env bash
# Synapse 代码注释质量扫描
# 来源: P5-B14 — 制度审计 follow-up，机械防呆
# 用法: bash tools/check-comments.sh
#
# 检查项:
#   1. TODO/FIXME/HACK/XXX 注释统计（信息性，不阻断）
#   2. 模块 docstring 覆盖率（⚠️ 缺失文件告警）
#   3. NOTE 注释统计（信息性输出）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

SRC_DIR="$PROJECT_DIR/src"

echo "=== 代码注释质量扫描 ==="
echo ""

# ── 1. TODO/FIXME/HACK/XXX 扫描 ───────────────────────

echo "--- TODO / FIXME / HACK / XXX ---"

# 直接 grep 所有文件的结果
TODO_RESULT=$(grep -rnE '#.*(TODO|FIXME|HACK|XXX)' "$SRC_DIR" --include="*.py" 2>/dev/null || true)

if [ -n "$TODO_RESULT" ]; then
  TODO_COUNT=$(echo "$TODO_RESULT" | wc -l | tr -d '[:space:]')
  yellow "  📝 发现 $TODO_COUNT 条 TODO/FIXME/HACK/XXX 注释:"
  echo "$TODO_RESULT" | while IFS= read -r line; do
    rel=$(echo "$line" | sed "s|$PROJECT_DIR/||")
    yellow "     $rel"
  done
  WARNINGS=$((WARNINGS + TODO_COUNT))
else
  green "  ✅ 零 TODO/FIXME/HACK/XXX 注释"
fi
echo ""

# ── 2. 模块 docstring 检查 ─────────────────────────────

echo "--- 模块 docstring ---"

DOCSTRING_MISSING=0
# 使用 tempfile 避免 subshell 变量问题
TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

find "$SRC_DIR" -name "*.py" -not -path "*__pycache__*" -print0 2>/dev/null | \
  while IFS= read -r -d '' f; do
    # 跳过空文件
    if [ ! -s "$f" ]; then
      continue
    fi
    rel=$(echo "$f" | sed "s|$PROJECT_DIR/||")
    has_docstring=$(python3 -c "
import ast
try:
    with open('$f') as fh:
        tree = ast.parse(fh.read())
    doc = ast.get_docstring(tree)
    print('yes' if doc else 'no')
except Exception:
    print('error')
" 2>/dev/null)
    if [ "$has_docstring" = "no" ]; then
      echo "$rel" >> "$TMPFILE"
    fi
  done

if [ -s "$TMPFILE" ]; then
  DOCSTRING_MISSING=$(wc -l < "$TMPFILE" | tr -d '[:space:]')
  while IFS= read -r rel; do
    [ -z "$rel" ] && continue
    yellow "  ⚠️  $rel — 缺少模块 docstring"
    WARNINGS=$((WARNINGS + 1))
  done < "$TMPFILE"
else
  green "  ✅ 所有模块有 docstring"
fi
echo ""

# ── 3. NOTE 注释统计（信息性） ──────────────────────────

echo "--- NOTE 注释 ---"

NOTE_RESULT=$(grep -rn '#.*NOTE:' "$SRC_DIR" --include="*.py" 2>/dev/null || true)

if [ -n "$NOTE_RESULT" ]; then
  NOTE_COUNT=$(echo "$NOTE_RESULT" | wc -l | tr -d '[:space:]')
  green "  ℹ️  共 $NOTE_COUNT 条 NOTE 注释:"
  echo "$NOTE_RESULT" | while IFS= read -r line; do
    [ -z "$line" ] && continue
    rel=$(echo "$line" | sed "s|$PROJECT_DIR/||")
    yellow "     $rel"
  done
else
  green "  ℹ️  无 NOTE 注释"
fi
echo ""

# ── 4. Python 文件统计 ─────────────────────────────────

echo "--- 文件统计 ---"
PY_FILES=$(find "$SRC_DIR" -name "*.py" -not -path "*__pycache__*" -not -name "__init__.py" 2>/dev/null || true)
PY_COUNT=$(echo "$PY_FILES" | grep -v '^$' | wc -l | tr -d '[:space:]')
PY_LINES=$(find "$SRC_DIR" -name "*.py" -not -path "*__pycache__*" -print0 2>/dev/null | xargs -0 wc -l 2>/dev/null | tail -1 | awk '{print $1}')
green "  ✅ $PY_COUNT 个模块, $PY_LINES 行 Python 代码"
echo ""

# ── 总结 ────────────────────────────────────────────────

echo "========================================="
green "✅ 代码注释扫描完成"
if [ "$WARNINGS" -gt 0 ]; then
  yellow "💡 $WARNINGS 个发现（不阻断，供参考）"
else
  green "✅ 代码注释质量良好"
fi
exit 0
