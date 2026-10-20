#!/bin/bash
# push-both.sh — 一次 push 两个库（gitee 完整 · github 精简）
#
# 用法：bash tools/push-both.sh
#
# 设计原则（2026-10-20 公开化复盘）：
#   本地 master 永远保留完整内容（含 landing/research/daily/archive/plans 等内部过程）。
#   gitee 是内部主仓库 → 推完整 master。
#   github 是公开仓库 → 动态过滤掉内部内容后推精简版。
#   ⚠️ 绝不用 filter-repo 重写本地 master 历史（会污染 gitee），过滤只发生在 push github 的临时克隆里。
set -euo pipefail

GITHUB_REMOTE="git@github.com:Coderkunhe/synapse.git"

# github 公开仓库需要排除的「内部过程/竞品/品牌/宣传」内容
EXCLUDE_PATHS=(
  'synapse/docs/landing'
  'synapse/docs/research'
  'synapse/docs/daily'
  'synapse/docs/archive'
  'synapse/docs/plans'
  'synapse/docs/l5'
  'memory'
  'synapse/docs/pitfalls.md'
  'synapse/docs/process-violations.md'
  'synapse/docs/requirements-log.md'
  'synapse/docs/master-backlog.md'
  'synapse/docs/agent-comparison.md'
  'synapse/docs/process-infrastructure.md'
  'synapse/data/b77-findings.json'
  'synapse/data/s016-scout-report.md'
)

echo "① push 完整 master → gitee"
git push origin master

echo "② 生成精简版 → github"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q . "$TMP/lean"
cd "$TMP/lean"

ARGS=(--invert-paths)
for p in "${EXCLUDE_PATHS[@]}"; do
  ARGS+=(--path "$p")
done

git filter-repo --force "${ARGS[@]}" >/dev/null 2>&1

git remote add github "$GITHUB_REMOTE"
git push github master --force

echo "✅ 双库推送完成：gitee 完整 + github 精简"
