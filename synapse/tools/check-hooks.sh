#!/usr/bin/env bash
# check-hooks.sh — 验证 git hooks 完整性（V-028 防呆）
# 接入 make check 管道，每次门禁都验证 hooks 是否安装。
# 新 clone / 迁库后首次 make check 即可发现缺失。
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -z "$REPO_ROOT" ]; then
  echo "⚠️  Not in a git repository — skipping hook check"
  exit 0
fi

HOOKS_DIR="$REPO_ROOT/.git/hooks"
MISSING=()

for hook in pre-commit commit-msg post-commit; do
  if [ ! -f "$HOOKS_DIR/$hook" ] || [ ! -x "$HOOKS_DIR/$hook" ]; then
    MISSING+=("$hook")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo "🔴 ERROR: Git hooks 缺失 — L5 门禁未武装（V-028 防呆）"
  echo "   缺失: ${MISSING[*]}"
  echo "   原因: git clone 不会复制 .git/hooks/，迁库/新拉仓库后必须重装"
  echo "   修复: cd synapse && make hooks"
  echo ""
  exit 1
fi

echo "✅ Git hooks: 全部就位"
exit 0
