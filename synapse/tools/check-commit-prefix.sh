#!/usr/bin/env bash
# commit-msg 前缀门禁 helper — 由 tools/commit-msg 调用（非独立 hook）· 验证 monorepo 中 commit 前缀包含项目名
# 来源: 2026-07-04 隔离审计发现 — 5/6 synapse commits 缺少项目前缀

set -euo pipefail

COMMIT_MSG_FILE="$1"
COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

# 获取本次 commit 涉及的文件
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)

# 检查是否触及 synapse/
TOUCHES_SYNAPSE=$(echo "$STAGED_FILES" | grep -c "^synapse/" || true)
# 检查是否触及 glasscortex/
TOUCHES_GLASSMIND=$(echo "$STAGED_FILES" | grep -c "^glasscortex/" || true)

# 有效的项目前缀模式
SYNAPSE_PATTERN="^(feat|fix|docs|refactor|test|chore)\(synapse\):"
GLASSCORTEX_PATTERN="^(feat|fix|docs|refactor|test|chore)\((glasscortex|Phase)"


if [ "$TOUCHES_SYNAPSE" -gt 0 ]; then
  if ! echo "$COMMIT_MSG" | grep -qE "$SYNAPSE_PATTERN"; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  🚨 COMMIT PREFIX VIOLATION — Synapse                    ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  提交涉及 synapse/ 文件，但缺少 synapse: 前缀。         ║"
    echo "║                                                          ║"
    echo "║  当前: $(echo "$COMMIT_MSG" | head -1)                    "
    echo "║                                                          ║"
    echo "║  要求格式:                                                ║"
    echo "║    feat(synapse): Batch N — 简短描述                      ║"
    echo "║    fix(synapse): 简短描述                                  ║"
    echo "║    docs(synapse): 简短描述                                 ║"
    echo "║                                                          ║"
    echo "║  参考: [[synapse-batch-numbering-convention]]             ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
  fi
fi

if [ "$TOUCHES_GLASSMIND" -gt 0 ]; then
  if ! echo "$COMMIT_MSG" | grep -qE "$GLASSCORTEX_PATTERN"; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  🚨 COMMIT PREFIX VIOLATION — GlassCortex                ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║  提交涉及 glasscortex/ 文件，但缺少 glasscortex:/Phase 前缀║"
    echo "║                                                          ║"
    echo "║  当前: $(echo "$COMMIT_MSG" | head -1)                    "
    echo "║                                                          ║"
    echo "║  要求格式:                                                ║"
    echo "║    feat(glasscortex): 简短描述                             ║"
    echo "║    feat(Phase 1000 Batch N): 简短描述                      ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    exit 1
  fi
fi

# 如果同时触及两个项目，额外警告
if [ "$TOUCHES_SYNAPSE" -gt 0 ] && [ "$TOUCHES_GLASSMIND" -gt 0 ]; then
  echo ""
  echo "╔══════════════════════════════════════════════════════════╗"
  echo "║  ⚠️  本次提交同时触及 synapse/ 和 glasscortex/            ║"
  echo "║  请确保这是有意为之，commit message 需说明原因。        ║"
  echo "╚══════════════════════════════════════════════════════════╝"
  echo ""
fi

exit 0
