#!/usr/bin/env bash
# check-hooks.sh — 验证 git hooks 完整性（V-028 防呆 · G-028 · P12-B14 HK-1/HK-2）
# 接入 make check 管道，每次门禁都验证 hooks 是否安装且内容完整。
# 新 clone / 迁库后首次 make check 即可发现缺失。
#
# P12-B14: --fix 模式 — 检测到 hook 缺失/损坏 → 自动运行 make hooks 修复。
# 用于 Worker 启动链（session-init.js）自愈，消除 God's-eye 手动操作。
set -euo pipefail

FIX_MODE=false
if [[ "${1:-}" == "--fix" ]]; then
  FIX_MODE=true
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "")"
if [ -z "$REPO_ROOT" ]; then
  echo "⚠️  Not in a git repository — skipping hook check"
  exit 0
fi

HOOKS_DIR="$REPO_ROOT/.git/hooks"
SYNAPSE_TOOLS="$REPO_ROOT/synapse/tools"
MISSING=()
TRUNCATED=()
FIXED=()

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

# ── P12-B14: --fix 模式 — 自动修复 ──────────────────────
if [[ "$FIX_MODE" == true ]]; then
  total_issues=$((${#MISSING[@]} + ${#TRUNCATED[@]}))
  if [[ $total_issues -gt 0 ]]; then
    echo "🔧 check-hooks --fix: ${#MISSING[@]} missing + ${#TRUNCATED[@]} truncated → auto-repairing..."

    # 尝试 make hooks（优先使用 synapse 的 Makefile）
    if [[ -f "$REPO_ROOT/synapse/Makefile" ]] || [[ -f "$REPO_ROOT/Makefile" ]]; then
      if make -C "$REPO_ROOT/synapse" hooks 2>/dev/null || make -C "$REPO_ROOT" hooks 2>/dev/null; then
        echo "   ✅ make hooks succeeded"
        FIXED+=("make hooks")
      else
        echo "   ⚠️  make hooks failed — trying synapse-exec --install-hook"
      fi
    fi

    # Fallback: 使用 synapse-exec --install-hook（如果可用）
    if [[ ${#FIXED[@]} -eq 0 ]]; then
      if [[ -x "$REPO_ROOT/synapse/tools/synapse-exec" ]]; then
        if "$REPO_ROOT/synapse/tools/synapse-exec" --install-hook "$REPO_ROOT" 2>/dev/null; then
          echo "   ✅ synapse-exec --install-hook succeeded"
          FIXED+=("synapse-exec --install-hook")
        fi
      fi
    fi

    # 重新检查修复结果
    MISSING=()
    TRUNCATED=()
    for hook in pre-commit commit-msg post-commit; do
      hook_path="$HOOKS_DIR/$hook"
      if [ ! -f "$hook_path" ] || [ ! -x "$hook_path" ]; then
        MISSING+=("$hook")
      fi
      line_count=$(wc -l < "$hook_path" 2>/dev/null || echo "0")
      if [ "$line_count" -lt 3 ]; then
        TRUNCATED+=("$hook ($line_count lines)")
      fi
    done

    if [[ ${#MISSING[@]} -eq 0 && ${#TRUNCATED[@]} -eq 0 ]]; then
      echo "✅ check-hooks --fix: all hooks repaired (${FIXED[*]})"
    else
      echo "🔴 check-hooks --fix: repair incomplete — ${#MISSING[@]} still missing, ${#TRUNCATED[@]} still truncated"
      exit 1
    fi
  else
    echo "✅ Git hooks: 3/3 就位 · 内容完整 (--fix: no action needed)"
  fi
  exit 0
fi

# ── 报告（非 --fix 模式）────────────────────────────────
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
