#!/usr/bin/env bash
# check-venv.sh — venv console-script shebang 一致性防呆（P100-B136 · PFL-239）
#
# 检测 .venv/bin/* 里 shebang / VIRTUAL_ENV 是否指向当前 venv 路径。
# 根因：项目目录迁移后，venv console-script 的 shebang 仍指向旧路径，
#       直接执行 .venv/bin/pytest / uvicorn / alembic 会报 "bad interpreter"。
# 已知受害（迁移一次）：uvicorn / pytest / alembic / pip / fastapi / mypy 等 30 个脚本。
# 盲区：Makefile check-tests 用 `.venv/bin/python -m pytest`（-m 绕行），
#       所以 make check 一直不会暴露此问题 —— 本脚本专补这个盲区。
#
# Usage:
#   bash tools/check-venv.sh            # 报告（默认 warning 级，exit 0）
#   bash tools/check-venv.sh --strict   # 发现 stale → exit 1（门禁用）
#   bash tools/check-venv.sh --fix      # 自愈：stale 路径重写为当前 venv 路径
#
# Exit codes:
#   0 - 无 stale（或 .venv 不存在，跳过）
#   1 - 发现 stale（仅 --strict 模式）
#   2 - 脚本执行错误（未知参数）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
BIN_DIR="$VENV_DIR/bin"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

STRICT=false
FIX=false
for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=true ;;
    --fix)    FIX=true ;;
    --help|-h)
      sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$BIN_DIR" ]; then
  echo "✅ check-venv: 无 .venv（$VENV_DIR 不存在）— 跳过"
  exit 0
fi

# 当前 venv 真实路径（pwd -P 解析 symlink，容忍 /tmp→/private/tmp 差异）
REAL_CUR="$(cd "$VENV_DIR" 2>/dev/null && pwd -P || echo "$VENV_DIR")"

STALE_COUNT=0
for f in "$BIN_DIR"/*; do
  # 跳过 symlink（python/python3/python3.14 → homebrew）与非常规文件
  [ -L "$f" ] && continue
  [ -f "$f" ] || continue

  # 提取文件里出现的绝对 .venv 路径（shebang 或 VIRTUAL_ENV="..."）
  refs="$(grep -IoE '/[^[:space:]"<>]+\.venv' "$f" 2>/dev/null | sort -u || true)"
  [ -n "$refs" ] || continue

  for ref in $refs; do
    # 归一化到真实路径比较（容忍 symlink 差异）
    real_ref="$ref"
    [ -e "$ref" ] && real_ref="$(cd "$ref" 2>/dev/null && pwd -P || echo "$ref")"

    if [ "$real_ref" != "$REAL_CUR" ]; then
      STALE_COUNT=$((STALE_COUNT + 1))
      if [ "$FIX" = true ]; then
        sed -i '' "s|${ref}|${VENV_DIR}|g" "$f"
        echo "${YELLOW}  🔧 修复${NC} $(basename "$f")"
        echo "       ${RED}${ref}${NC} → ${GREEN}${VENV_DIR}${NC}"
      else
        echo "${YELLOW}  ⚠️  stale${NC} $(basename "$f")"
        echo "       指向 ${RED}${ref}${NC}"
        echo "       应为 ${GREEN}${VENV_DIR}${NC}"
      fi
    fi
  done
done

echo ""
if [ "$FIX" = true ]; then
  echo "✅ check-venv 修复完成（${STALE_COUNT} 处 stale → 已重写）"
  exit 0
elif [ "$STALE_COUNT" -gt 0 ]; then
  echo "${YELLOW}⚠️  check-venv: 发现 ${STALE_COUNT} 处 stale shebang/VIRTUAL_ENV${NC}"
  echo "   自愈：bash tools/check-venv.sh --fix"
  [ "$STRICT" = true ] && exit 1
  exit 0
else
  echo "${GREEN}✅ check-venv: venv shebang 与当前路径一致${NC}"
  exit 0
fi
