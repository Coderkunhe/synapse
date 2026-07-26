#!/usr/bin/env bash
# Dogfood active gate — 多 Worker 协作狗粮期间 God's-eye 禁止直接修改 src/
#
# 适用范围: 仅多 Worker 协作推进时的狗粮期。单 Worker 测试/API 验证不需要。
# 激活方式: 由人类 owner 手动 touch flag（非自动）— 你认为需要角色隔离时才设。
#
# 机制:
#   开始: touch synapse/.claude/dogfood-active
#   结束: rm synapse/.claude/dogfood-active
#   commit 时检测: dogfood-active 存在 + staged 含 src/ → 硬阻断
#   人类 owner 绕行: rm synapse/.claude/dogfood-active 再 commit
#
# 为什么: 多 Worker 协作狗粮期，God's-eye 只观察、排错、登记，不写实现代码。
#        发现问题走 VDD 循环而不是自己上手修，保证验证的真实性。
#        不是所有狗粮都需要——只有多 Worker 同时活跃、角色容易串戏时才设。

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
DOGFOOD_FLAG="$REPO_ROOT/synapse/.claude/dogfood-active"

# 标记不存在 → 放行
if [[ ! -f "$DOGFOOD_FLAG" ]]; then
  exit 0
fi

STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || echo "")

# 无 staged 文件 → 放行
if [[ -z "$STAGED_FILES" ]]; then
  exit 0
fi

SRC_FILES=$(echo "$STAGED_FILES" | grep -E '^synapse/src/|^synapse/frontend/src/' || true)

if [[ -n "$SRC_FILES" ]]; then
  echo ""
  echo "🐕━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "🐕  多 Worker 协作狗粮期 — God's-eye 禁止直接修改 src/"
  echo "🐕"
  echo "🐕  检测到 synapse/.claude/dogfood-active 存在"
  echo "🐕  以下 staged 文件触碰了 src/ 或 frontend/src/："
  echo "$SRC_FILES" | while read -r f; do echo "🐕    • $f"; done
  echo "🐕"
  echo "🐕  规则: 多 Worker 协作期间 God's-eye 只观察、排错、登记，不写实现代码。"
  echo "🐕        发现问题 → 登记 PFL → 走 VDD 循环（创建 Task → Builder 实现）。"
  echo "🐕"
  echo "🐕  绕行: rm synapse/.claude/dogfood-active  # 人类 owner 确认后手动关闭"
  echo "🐕━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  exit 1
fi

exit 0
