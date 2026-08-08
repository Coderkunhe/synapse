#!/usr/bin/env bash
# check-env.sh — Synapse Worker 环境变量完整性门禁（P12-B50 · PFL-153）
#
# 逐变量检查 SYNAPSE_* 是否全部设为非空、非占位符、非注释的实际值。
# bootstrap-worker.sh 在 BOOT-1~7 完成后自动调用此脚本作为最后一道门禁。
#
# Usage:
#   bash tools/check-env.sh [.env 文件路径]
#   # 默认路径: .claude/.env（Claude Code Worker）
#   # 也可指定: bash tools/check-env.sh /path/to/worker/.env
#
# Exit codes:
#   0 — 全部 5 个变量通过
#   1 — 至少一个变量未通过
#   2 — .env 文件不存在或不可读

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ENV_FILE="${1:-.claude/.env}"

# ── 边界检查 ──
if [[ ! -f "$ENV_FILE" ]]; then
    echo -e "${RED}❌ .env 文件不存在: ${ENV_FILE}${NC}"
    exit 2
fi

if [[ ! -r "$ENV_FILE" ]]; then
    echo -e "${RED}❌ .env 文件不可读: ${ENV_FILE}${NC}"
    exit 2
fi

# ── 变量定义 ──
REQUIRED_VARS=(
    "SYNAPSE_API_URL"
    "SYNAPSE_WORKER_ID"
    "SYNAPSE_PROJECT_ID"
    "SYNAPSE_WORKER_ROLE"
    "SYNAPSE_API_KEY"
)

# 占位符模式（大小写不敏感匹配）
PLACEHOLDER_PATTERNS='changeme|placeholder|your-|replace|xxx|todo|fill'

# ── 门禁检查 ──
echo ""
echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}│  Synapse Env 完整性门禁                          │${NC}"
echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
echo ""

FAILED=0
PASSED=0

for var in "${REQUIRED_VARS[@]}"; do
    # 从 .env 中提取变量的实际值（过滤注释行，取最后一个匹配的赋值）
    value=$(grep -v '^\s*#' "$ENV_FILE" 2>/dev/null | grep "^${var}=" | tail -1 | sed "s/^${var}=//" | xargs)

    if [[ -z "$value" ]]; then
        echo -e "  ${RED}❌${NC} ${var}: 未设置或值为空"
        FAILED=$((FAILED + 1))
        continue
    fi

    # 检查是否为占位符
    if echo "$value" | grep -qiE "$PLACEHOLDER_PATTERNS"; then
        echo -e "  ${RED}❌${NC} ${var}: 值疑似占位符 → \"${value}\""
        FAILED=$((FAILED + 1))
        continue
    fi

    # 额外检查：API_URL 必须包含协议头
    if [[ "$var" == "SYNAPSE_API_URL" ]] && [[ ! "$value" =~ ^https?:// ]]; then
        echo -e "  ${RED}❌${NC} ${var}: URL 缺少协议头 → \"${value}\"（期望 http:// 或 https://）"
        FAILED=$((FAILED + 1))
        continue
    fi

    # 额外检查：WORKER_ID 必须以 wa_ 开头
    if [[ "$var" == "SYNAPSE_WORKER_ID" ]] && [[ ! "$value" =~ ^wa_ ]]; then
        echo -e "  ${RED}❌${NC} ${var}: Worker ID 格式异常 → \"${value}\"（期望 wa_ 前缀）"
        FAILED=$((FAILED + 1))
        continue
    fi

    # 额外检查：API_KEY 必须以 sk-syn- 开头
    if [[ "$var" == "SYNAPSE_API_KEY" ]] && [[ ! "$value" =~ ^sk-syn- ]]; then
        echo -e "  ${RED}❌${NC} ${var}: API Key 格式异常 → \"${value}\"（期望 sk-syn- 前缀）"
        FAILED=$((FAILED + 1))
        continue
    fi

    # 通过 ✓
    echo -e "  ${GREEN}✅${NC} ${var}: ${value}"
    PASSED=$((PASSED + 1))
done

echo ""
echo -e "${BOLD}── 结果 ──${NC}"
echo -e "  通过: ${GREEN}${PASSED}${NC} / 失败: ${RED}${FAILED}${NC}"

if [[ $FAILED -gt 0 ]]; then
    echo ""
    echo -e "${RED}${BOLD}❌ Env 门禁不通过 — ${FAILED} 项失败${NC}"
    echo ""
    echo -e "${CYAN}💡${NC} 修复方式:"
    echo -e "  1. 手动编辑 ${ENV_FILE}"
    echo -e "  2. 或重新运行: ${BOLD}bash tools/bootstrap-worker.sh --interactive${NC}"
    exit 1
fi

echo -e "${GREEN}${BOLD}✅ Env 门禁全量通过 — 5/5 变量就绪${NC}"
echo ""
exit 0
