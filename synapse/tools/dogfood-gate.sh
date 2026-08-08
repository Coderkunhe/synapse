#!/usr/bin/env bash
# Dogfood gate 管理 — 替代手动 touch/rm dogfood-active
#
# 用法:
#   dogfood-gate.sh on              → 激活狗粮门禁（touch flag）
#   dogfood-gate.sh off             → 关闭狗粮门禁（rm flag）
#   dogfood-gate.sh status          → 查询当前门禁状态
#   dogfood-gate.sh check-vcriteria → 检查上次狗粮 V-criteria 是否已回填（D-P12-042）
#
# 为什么需要脚本化:
#   HK-4 之前是 🔴 手动操作 — God's-eye 需要手动 touch/rm flag 文件。
#   脚本化后任何 Worker（含 Builder）都能通过 synapse-exec 调用，
#   不再需要 God's-eye 亲自操作文件系统。
#
# D1 Scout: HK-4 🔴→🟢 (P12-B15)
# D-P12-042: V-criteria 完整性检查 (P12-B52)

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$(dirname "$0")/../.." && pwd)")"
DOGFOOD_FLAG="$REPO_ROOT/synapse/.claude/dogfood-active"
STATUS_FILE="$REPO_ROOT/synapse/tests/dogfood/d4/status.md"

usage() {
  echo "Usage: dogfood-gate.sh <on|off|status|check-vcriteria>"
  echo ""
  echo "  on               Activate dogfood gate — blocks God's-eye src/ changes"
  echo "  off              Deactivate dogfood gate — allows all commits"
  echo "  status           Show current gate state"
  echo "  check-vcriteria  Check previous dogfood V-criteria all filled (D-P12-042)"
  exit 1
}

check_vcriteria() {
  if [[ ! -f "$STATUS_FILE" ]]; then
    echo "🐕 V-criteria check: SKIPPED — no status file at tests/dogfood/d4/status.md"
    return 0
  fi

  # Find all ⬜ (unfilled) V-criteria markers in the file
  # ⬜ is U+2B1C (UTF-8: e2 ac 9c)
  local unfilled
  unfilled=$(grep -c '⬜' "$STATUS_FILE" 2>/dev/null | tr -d '\n' || echo "0")
  unfilled="${unfilled:-0}"

  if [[ "$unfilled" -gt 0 ]]; then
    echo "┌──────────────────────────────────────────────────────────────┐"
    echo "│  🐕 D-P12-042: 狗粮 V-criteria 未回填 — 阻断新狗粮           │"
    echo "├──────────────────────────────────────────────────────────────┤"
    echo "│  文件: tests/dogfood/d4/status.md                           │"
    echo "│  未填充 V-criteria: $unfilled 项                              │"
    echo "│                                                              │"
    echo "│  P12-B52 门禁规则: 上次狗粮的 V-criteria 必须全部回填        │"
    echo "│  后才能激活新狗粮。这是机械门禁，不是软约定。                │"
    echo "│                                                              │"
    echo "│  修复: 编辑 status.md，将所有 ⬜ 替换为 ✅/❌/🟡              │"
    echo "│  然后重新运行: dogfood-gate.sh check-vcriteria               │"
    echo "└──────────────────────────────────────────────────────────────┘"
    return 1
  fi

  echo "🐕 V-criteria check: ✅ 全部已回填 (0 unfilled)"
  return 0
}

cmd="${1:-}"
case "$cmd" in
  on)
    # D-P12-042: gate activation must pass V-criteria check first
    if ! check_vcriteria; then
      echo ""
      echo "❌ 狗粮门禁激活被阻断 — 请先回填上次狗粮的 V-criteria"
      exit 1
    fi

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
  check-vcriteria)
    check_vcriteria
    ;;
  *)
    usage
    ;;
esac
