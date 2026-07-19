#!/usr/bin/env bash
# Synapse 文件行数上限检查 — 机械拦截 >800 行
# 用法: bash tools/check-line-count.sh [limit]
# 默认上限: 800 行
# 来源: P5-B16

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LIMIT="${1:-800}"
ERRORS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }

echo "=== 文件行数上限检查（>$LIMIT 行）==="
echo ""

# 扫描 src/ 和 tests/ 下所有 .py 文件
VIOLATIONS=()
while IFS= read -r -d '' file; do
  lines=$(wc -l < "$file" | tr -d ' ')
  if [ "$lines" -gt "$LIMIT" ]; then
    VIOLATIONS+=("$lines $file")
  fi
done < <(find "$PROJECT_DIR/src" "$PROJECT_DIR/tests" -name "*.py" -print0 2>/dev/null)

if [ ${#VIOLATIONS[@]} -eq 0 ]; then
  green "✅ 所有 .py 文件 ≤ $LIMIT 行"
  echo ""
  exit 0
fi

echo "❌ 以下文件超过 ${LIMIT} 行上限:"
echo ""
for entry in "${VIOLATIONS[@]}"; do
  lines=$(echo "$entry" | awk '{print $1}')
  file=$(echo "$entry" | awk '{print $2}')
  rel="${file#$PROJECT_DIR/}"
  printf "  %-70s %s 行\n" "$rel" "$lines"
done
echo ""
red "💀 ${#VIOLATIONS[@]} 个文件超标 — 请拆分后再提交"
exit 1
