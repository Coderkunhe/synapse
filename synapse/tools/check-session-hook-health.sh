#!/usr/bin/env bash
# check-session-hook-health.sh — C13 Hook 诊断（P13-B11）
# 检测 Claude Code SessionStart hook 是否实际执行（非仅配置存在）
# 依赖: canary 时间戳文件（由 SessionStart hook 链中的 canary hook 写入）
#
# 用法:
#   bash tools/check-session-hook-health.sh            默认: 完整诊断报告 + 恢复指引
#   bash tools/check-session-hook-health.sh --gate     门禁模式: 静默 pass/fail (exit code)
#   bash tools/check-session-hook-health.sh --json     JSON 输出: 供 script/program 消费
#
# 检测逻辑:
#   canary <5min    → 🟢 HEALTHY  (hook 本会话正常执行)
#   canary 5-30min  → 🟡 STALE    (hook 可能未在本会话触发)
#   canary >30min   → 🔴 STALE    (hook 最后一次执行距今已久)
#   canary 缺失     → 🔴 MISSING  (hook 从未在此仓库执行)
set -euo pipefail

# ── 常量 ──────────────────────────────────────────────
HEALTHY_THRESHOLD=300    # 5 分钟: 新鲜
STALE_THRESHOLD=1800     # 30 分钟: 开始变黄（当前未使用分层）
WARN_THRESHOLD=1800      # 30 分钟: 超过此值 → 🔴

# ── 路径解析 ──────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"                       # synapse/
REPO_ROOT="$(dirname "$PROJECT_DIR")"                        # ai-synapse/（git root · Claude Code 启动目录）
CANARY_FILE="$PROJECT_DIR/.claude/session-hook-canary"
SETTINGS_FILE="$REPO_ROOT/.claude/settings.json"

# ── 模式检测 ──────────────────────────────────────────
GATE_MODE=false
JSON_MODE=false
for arg in "$@"; do
  case "$arg" in
    --gate) GATE_MODE=true ;;
    --json) JSON_MODE=true ;;
  esac
done

# ── 辅助函数 ──────────────────────────────────────────
now_epoch() { date +%s; }

age_seconds() {
  local canary_ts="$1"
  echo $(( $(now_epoch) - canary_ts ))
}

age_human() {
  local seconds="$1"
  if [ "$seconds" -lt 60 ]; then
    echo "${seconds}s ago"
  elif [ "$seconds" -lt 3600 ]; then
    echo "$(( seconds / 60 ))m ago"
  elif [ "$seconds" -lt 86400 ]; then
    echo "$(( seconds / 3600 ))h $(( (seconds % 3600) / 60 ))m ago"
  else
    echo "$(( seconds / 86400 ))d ago"
  fi
}

# ── 主检测逻辑 ────────────────────────────────────────
STATUS=""
STATUS_LABEL=""
CANARY_TS=""
AGE_SEC=0
RECOVERY_HINT=""

check_canary() {
  if [ ! -f "$CANARY_FILE" ]; then
    STATUS="MISSING"
    STATUS_LABEL="🔴 MISSING"
    RECOVERY_HINT="SessionStart hook 从未在此仓库执行。
  1. 确认 settings.json 在正确位置: $SETTINGS_FILE
  2. 确认 settings.json 中的 SessionStart hooks 配置未被覆盖
  3. 检查 Claude Code 版本是否支持 SessionStart hook
  4. 手动运行: bash tools/reset-batch-counter.sh"
    return
  fi

  CANARY_TS=$(cat "$CANARY_FILE" 2>/dev/null | head -1)
  # 验证是纯数字
  if ! [[ "$CANARY_TS" =~ ^[0-9]+$ ]]; then
    STATUS="CORRUPT"
    STATUS_LABEL="🔴 CORRUPT"
    RECOVERY_HINT="canary 文件内容异常（非时间戳）: $CANARY_TS
  1. 删除损坏文件: rm $CANARY_FILE
  2. 重新启动会话让 hook 写入新 canary
  3. 如果持续异常，检查 settings.json hook 命令是否有输出重定向冲突"
    return
  fi

  AGE_SEC=$(age_seconds "$CANARY_TS")

  if [ "$AGE_SEC" -lt "$HEALTHY_THRESHOLD" ]; then
    STATUS="HEALTHY"
    STATUS_LABEL="🟢 HEALTHY"
    RECOVERY_HINT=""
  elif [ "$AGE_SEC" -lt "$WARN_THRESHOLD" ]; then
    STATUS="STALE"
    STATUS_LABEL="🟡 STALE"
    RECOVERY_HINT="hook 最后执行于 $(age_human $AGE_SEC)，可能未在本会话触发。
  1. 尝试 /clear 重开会话（新会话触发 SessionStart hook）
  2. 检查 Claude Code 启动时是否有 permission prompt 被静默拒绝
  3. 如果持续异常，手动运行: bash synapse/tools/reset-batch-counter.sh"
  else
    STATUS="STALE"
    STATUS_LABEL="🔴 STALE"
    RECOVERY_HINT="hook 最后执行于 $(age_human $AGE_SEC) — 本会话大概率未触发。
  1. 尝试 /clear 重开会话
  2. 检查 Claude Code 版本 — SessionStart hook 可能需要特定版本
  3. 验证 $SETTINGS_FILE 语法是否正确 (trailing commas?)
  4. 检查 ~/.claude/settings.json 是否有冲突的 hook 配置
  5. 手动兜底: bash synapse/tools/reset-batch-counter.sh"
  fi
}

check_settings_exists() {
  if [ ! -f "$SETTINGS_FILE" ]; then
    if $JSON_MODE; then
      echo '{"status":"NO_SETTINGS","label":"🔴 NO_SETTINGS","age_seconds":0,"age_human":"N/A","canary_file":"'$CANARY_FILE'","settings_file":"'$SETTINGS_FILE'","recovery":"settings.json 不存在 — 无法配置 SessionStart hook。创建 .claude/settings.json（项目根目录）并添加 SessionStart hook 配置。"}'
    elif $GATE_MODE; then
      echo "🔴 SESSION-HOOK: NO_SETTINGS — $SETTINGS_FILE 不存在"
    else
      echo "🔴 NO_SETTINGS: $SETTINGS_FILE 不存在"
      echo "   SessionStart hook 无法在没有 settings.json 的情况下运行。"
      echo "   修复: 创建 .claude/settings.json（项目根目录）并添加 SessionStart hook 配置。"
    fi
    exit 1
  fi
}

# ── 输出 ──────────────────────────────────────────────

check_settings_exists
check_canary

# ── JSON 模式 ─────────────────────────────────────────
if $JSON_MODE; then
  cat <<JSON
{
  "status": "$STATUS",
  "label": "$STATUS_LABEL",
  "age_seconds": $AGE_SEC,
  "age_human": "$(age_human $AGE_SEC)",
  "canary_file": "$CANARY_FILE",
  "canary_timestamp": ${CANARY_TS:-0},
  "settings_file": "$SETTINGS_FILE",
  "thresholds": {"healthy": $HEALTHY_THRESHOLD, "warn": $WARN_THRESHOLD},
  "recovery": "$RECOVERY_HINT"
}
JSON
  [ "$STATUS" = "HEALTHY" ] && exit 0 || exit 1
fi

# ── Gate 模式 ─────────────────────────────────────────
if $GATE_MODE; then
  case "$STATUS" in
    HEALTHY)
      echo "✅ SESSION-HOOK: $STATUS_LABEL ($(age_human $AGE_SEC))"
      exit 0
      ;;
    STALE)
      echo "🟡 SESSION-HOOK: $STATUS_LABEL ($(age_human $AGE_SEC)) — 可能未在本会话触发"
      exit 0  # gate 模式不阻断（STALE 是警告，不是硬错误）
      ;;
    MISSING|CORRUPT)
      echo "🔴 SESSION-HOOK: $STATUS_LABEL — $RECOVERY_HINT" | head -1
      exit 1
      ;;
  esac
fi

# ── 默认: 完整诊断报告 ────────────────────────────────
echo "╔══════════════════════════════════════════════════════╗"
echo "║  🔍 SessionStart Hook 健康诊断 (C13 · P13-B11)     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  状态: $STATUS_LABEL"
echo "  Canary: $CANARY_FILE"

if [ "$STATUS" != "MISSING" ] && [ "$STATUS" != "CORRUPT" ]; then
  echo "  最后执行: $(age_human $AGE_SEC) (timestamp: $CANARY_TS)"
  echo "  阈值: 新鲜 <$(age_human $HEALTHY_THRESHOLD) | 告警 >$(age_human $WARN_THRESHOLD)"
fi

echo ""

if [ -n "$RECOVERY_HINT" ]; then
  echo "  ── 恢复指引 ──"
  echo ""
  while IFS= read -r line; do
    echo "  $line"
  done <<< "$RECOVERY_HINT"
  echo ""
fi

# settings.json 诊断
if [ -f "$SETTINGS_FILE" ]; then
  if grep -q "SessionStart" "$SETTINGS_FILE" 2>/dev/null; then
    hook_count=$(grep -c '"type"' "$SETTINGS_FILE" 2>/dev/null || echo "?")
    echo "  📄 $SETTINGS_FILE: SessionStart 已配置 ($hook_count hook(s))"
  else
    echo "  ⚠️  $SETTINGS_FILE: 存在但未找到 SessionStart 配置"
  fi
else
  echo "  🔴 $SETTINGS_FILE: 不存在"
fi

echo ""
echo "  ── 说明 ──"
echo ""
echo "  SessionStart hook 是 Claude Code 启动时自动执行的脚本。"
echo "  本诊断通过 canary 文件（hook 执行时写入的时间戳）判断 hook 是否实际执行。"
echo "  canary 文件由 SessionStart hook 链的第一个 hook 写入。"
echo ""

case "$STATUS" in
  HEALTHY) exit 0 ;;
  *)       exit 1 ;;
esac
