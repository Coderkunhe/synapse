#!/usr/bin/env bash
# check-hooks.sh — 验证 git hooks 完整性（V-028 防呆 · G-028）
# 接入 make check 管道，每次门禁都验证 hooks 是否安装且内容完整。
# 新 clone / 迁库后首次 make check 即可发现缺失。
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -z "$REPO_ROOT" ]; then
  echo "⚠️  Not in a git repository — skipping hook check"
  exit 0
fi

HOOKS_DIR="$REPO_ROOT/.git/hooks"
SYNAPSE_TOOLS="$REPO_ROOT/synapse/tools"
MISSING=()
TRUNCATED=()

# ── 检查每个 hook 存在 + 可执行 + 内容非空 ──────────────
for hook in pre-commit commit-msg post-commit; do
  hook_path="$HOOKS_DIR/$hook"

  if [ ! -f "$hook_path" ] || [ ! -x "$hook_path" ]; then
    MISSING+=("$hook")
    continue
  fi

  # 内容完整性：非空（防止截断/损坏的 hook 文件蒙混过关）
  line_count=$(wc -l < "$hook_path" 2>/dev/null || echo "0")
  if [ "$line_count" -lt 3 ]; then
    TRUNCATED+=("$hook ($line_count lines)")
  fi
done

# ── pre-commit 是 symlink → 校验目标脚本存在且可执行 ────
if [ -L "$HOOKS_DIR/pre-commit" ]; then
  target=$(readlink "$HOOKS_DIR/pre-commit")
  if [ ! -f "$HOOKS_DIR/$target" ] && [ ! -f "$REPO_ROOT/$target" ]; then
    MISSING+=("pre-commit target (broken symlink → $target)")
  fi
fi

# ── 报告 ─────────────────────────────────────────────────
rc=0

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo "🔴 ERROR: Git hooks 缺失 — L5 门禁未武装（V-028 防呆）"
  echo "   缺失: ${MISSING[*]}"
  echo "   原因: git clone 不会复制 .git/hooks/，迁库/新拉仓库后必须重装"
  echo "   修复: cd synapse && make hooks"
  echo ""
  rc=1
fi

if [ ${#TRUNCATED[@]} -gt 0 ]; then
  echo ""
  echo "🟡 WARNING: Git hooks 内容异常（可能已损坏）"
  echo "   异常: ${TRUNCATED[*]}"
  echo "   修复: cd synapse && make hooks （覆盖重装）"
  echo ""
  # 警告不阻断，但需要让运维看到
fi

if [ "$rc" -eq 0 ]; then
  echo "✅ Git hooks: 3/3 就位 · 内容完整"
fi
exit $rc
