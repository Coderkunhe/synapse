#!/usr/bin/env bash
# G-007 · Fresh-eyes 契约层复审门禁
#
# 检查 .git/synapse-pending-fresh-eyes marker 是否存在。
# 存在 → 警告 "上批含契约变更（onboarding/protocol/schema/api）未 fresh-eyes 复审"。
# 首部署不阻断（warning-only），验证 2 批后可升级 exit 1。
#
# Marker 生命周期：
#   - post-commit hook 检测 commit msg 含契约关键词 → 写 marker
#   - 后续 commit msg 含 "fresh-eyes" → post-commit 自动清除 marker
#   - 人力：手动 `rm .git/synapse-pending-fresh-eyes` 亦可
#
# 集成：
#   - make check-fresh-eyes（独立 target）
#   - make check（聚合管道）
#
# 用法：bash tools/check-fresh-eyes.sh
# 退出码：0 = 通过/警告 · 1 = 阻断（首部署未启用，验证期后启用）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

yellow() { echo -e "\033[33m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
bold()   { echo -e "\033[1m$1\033[0m"; }

GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || echo "")
if [ -z "$GIT_DIR" ]; then
  yellow "  ⚠️  非 git 仓库，跳过 fresh-eyes 检测"
  exit 0
fi

MARKER="${GIT_DIR}/synapse-pending-fresh-eyes"

echo ""
bold "=== Fresh-eyes 复审门禁 (G-007) ==="
echo ""

if [ ! -f "$MARKER" ]; then
  green "  ✅ 无 pending fresh-eyes marker — 契约层复审无待办"
  echo ""
  exit 0
fi

# Marker 存在 → 警告
COMMIT_HASH=""
TS=""
read -r COMMIT_HASH TS < "$MARKER" 2>/dev/null || true

yellow "  ┌──────────────────────────────────────────────────────────────┐"
yellow "  │  ⚠️  G-007 · Fresh-eyes 复审待做                             │"
yellow "  ├──────────────────────────────────────────────────────────────┤"
printf  "  │  Marker: %-52s │\n" "${MARKER#${PROJECT_DIR}/}"
printf  "  │  触发 commit: %-47s │\n" "${COMMIT_HASH:0:12}"
yellow "  │                                                              │"
yellow "  │  上批含契约变更（onboarding/protocol/schema/api/contract），   │"
yellow "  │  必须新会话逐条 checklist 复审对齐源码，避免同批自审盲区。      │"
yellow "  │                                                              │"
yellow "  │  完成方式：                                                   │"
yellow "  │    ① commit msg 含 \"fresh-eyes\" → post-commit 自动清 marker  │"
yellow "  │    ② 手动 rm .git/synapse-pending-fresh-eyes                 │"
yellow "  │                                                              │"
yellow "  │  参考：docs/lessons-learned.md LL14 · docs/methodology.md    │"
yellow "  │  ⚡ 首部署为警告 — 验证 2 批后升级为阻断（exit 1）             │"
yellow "  └──────────────────────────────────────────────────────────────┘"
echo ""

# 首部署警告级，验证期后改为 exit 1
exit 0
