#!/usr/bin/env bash
# Dogfood gate 管理 — 替代手动 touch/rm dogfood-active
#
# 用法:
#   dogfood-gate.sh on       → 激活狗粮门禁（touch flag）
#   dogfood-gate.sh off      → 关闭狗粮门禁（rm flag）
#   dogfood-gate.sh status   → 查询当前门禁状态
#
# 为什么需要脚本化:
#   HK-4 之前是 🔴 手动操作 — God's-eye 需要手动 touch/rm flag 文件。
#   脚本化后任何 Worker（含 Builder）都能通过 synapse-exec 调用，
#   不再需要 God's-eye 亲自操作文件系统。
#
# D1 Scout: HK-4 🔴→🟢 (P12-B15)

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$(dirname "$0")/../.." && pwd)")"
DOGFOOD_FLAG="$REPO_ROOT/synapse/.claude/dogfood-active"

usage() {
  echo "Usage: dogfood-gate.sh <on|off|status>"
  echo ""
  echo "  on      Activate dogfood gate — blocks God's-eye src/ changes"
  echo "  off     Deactivate dogfood gate — allows all commits"
  echo "  status  Show current gate state"
  exit 1
}

cmd="${1:-}"
case "$cmd" in
  on)
    if [[ -f "$DOGFOOD_FLAG" ]]; then
      echo "🐕 Dogfood gate is already ACTIVE (flag exists at synapse/.claude/dogfood-active)"
    else
      touch "$DOGFOOD_FLAG"
      echo "🐕 Dogfood gate ACTIVATED — God's-eye src/ changes are now blocked"
      echo "   Flag: synapse/.claude/dogfood-active"
    fi
    ;;
  off)
    if [[ -f "$DOGFOOD_FLAG" ]]; then
      rm "$DOGFOOD_FLAG"
      echo "🐕 Dogfood gate DEACTIVATED — all commits allowed"
    else
      echo "🐕 Dogfood gate is already INACTIVE (no flag file)"
    fi
    ;;
  status)
    if [[ -f "$DOGFOOD_FLAG" ]]; then
      echo "🐕 Dogfood gate: ACTIVE"
      echo "   Flag: synapse/.claude/dogfood-active"
      echo "   Effect: pre-commit blocks God's-eye src/ changes"
      echo "   Deactivate: dogfood-gate.sh off"
    else
      echo "🐕 Dogfood gate: INACTIVE"
      echo "   All commits allowed (no flag file)"
      echo "   Activate: dogfood-gate.sh on"
    fi
    ;;
  *)
    usage
    ;;
esac
