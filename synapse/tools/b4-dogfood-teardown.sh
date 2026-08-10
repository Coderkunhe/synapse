#!/usr/bin/env bash
# P14-B4 狗粮善后脚本
# 用法: bash synapse/tools/b4-dogfood-teardown.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "🧹 P14-B4 狗粮善后..."

# 1. 删除 worktrees
for wt in p14-b4-b1 p14-b4-b2; do
  WT_PATH="$REPO_ROOT/.claude/worktrees/$wt"
  if [ -d "$WT_PATH" ]; then
    echo "   删除 worktree: $wt"
    git -C "$REPO_ROOT" worktree remove "$WT_PATH" --force 2>/dev/null || rm -rf "$WT_PATH"
  fi
done

# 2. 删除对应分支
for branch in p14-b4-b1 p14-b4-b2; do
  if git -C "$REPO_ROOT" branch --list "$branch" | grep -q "$branch"; then
    echo "   删除分支: $branch"
    git -C "$REPO_ROOT" branch -D "$branch" 2>/dev/null || true
  fi
done

# 3. 清理 worktree 引用
git -C "$REPO_ROOT" worktree prune 2>/dev/null || true

# 4. 清理 .env 文件
rm -f "$REPO_ROOT/synapse/.env.worker-o"

# 5. 移除 dogfood 门禁
rm -f "$REPO_ROOT/synapse/.claude/dogfood-active"

# 6. Worker 数据需通过 API 删除（或手动清理 DB）
echo ""
echo "⚠️  Worker + Task 数据需手动清理："
echo "   O:  ag_019fe9795df07e9d"
echo "   B1: ag_019fe9795df67879"
echo "   B2: ag_019fe9795dfa71e4"
echo "   Project: prj_019fe9795de47a26"
echo ""
echo "   或者通过 API:"
echo "   curl -X DELETE http://localhost:8001/v1/projects/prj_019fe9795de47a26 \\"
echo "     -H 'Authorization: Bearer <admin-token>'"
echo ""
echo "✅ B4 狗粮善后完成"
