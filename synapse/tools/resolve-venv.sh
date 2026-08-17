#!/usr/bin/env bash
# resolve-venv.sh — 解析项目 .venv 绝对路径（P100-B144 · 主仓 + git worktree 均可用）
#
# 根因：稀疏 worktree 无 .venv（gitignored + 未 checkout），
#       Makefile/check-contracts.sh 硬编码 `.venv/bin/python` → worktree 门禁全挂。
# 本脚本单源解析 venv，供 Makefile 与 shell 门禁复用（P12-3 脚本化优先）。
#
# 优先级：
#   1. 本地 .venv（主仓）
#   2. 主仓 .venv（worktree 回退，经 --git-common-dir 定位）
#   3. 兜底本地路径（让调用方明确报错，而非静默错位）
#
# Usage: bash tools/resolve-venv.sh   # 输出 venv 绝对路径
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"   # synapse/

# 1. 本地 venv（主仓）
if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  echo "$PROJECT_DIR/.venv"
  exit 0
fi

# 2. 主仓 venv（worktree 回退）
MAIN_GITDIR="$(git -C "$PROJECT_DIR" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [ -n "$MAIN_GITDIR" ]; then
  MAIN_ROOT="$(dirname "$MAIN_GITDIR")"
  if [ -x "$MAIN_ROOT/synapse/.venv/bin/python" ]; then
    echo "$MAIN_ROOT/synapse/.venv"
    exit 0
  fi
fi

# 3. 兜底：本地路径（调用方会因 python 不存在而明确报错）
echo "$PROJECT_DIR/.venv"
