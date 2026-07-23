#!/usr/bin/env bash
# check-key-isolation.sh — Worker API Key 隔离审计
#
# 扫描所有 Worker 工作目录，检测：
# 1. .env 文件中是否存在明文 API Key（SYNAPSE_API_KEY=sk-syn-...）
# 2. .env 文件权限是否过于宽松（非 600）
# 3. 密钥链集成状态（macOS Keychain / Linux secret-tool）
#
# P11-B35: Key 隔离 — 防止跨 Worker API Key 冒充 (P-045)
#
# Usage:
#   check-key-isolation.sh [--fix] [--strict]
#     --fix      自动修复文件权限（chmod 600）
#     --strict   明文 Key 视为 ERROR（退出码非零），否则 WARNING
#
# Exit codes:
#   0 - 所有 Worker 密钥隔离达标
#   1 - 发现暴露的 API Key（--strict 模式）
#   2 - 脚本执行错误

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

STRICT=false
FIX=false
EXIT_CODE=0

for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=true ;;
        --fix)    FIX=true ;;
        *)        echo "Unknown arg: $arg"; exit 2 ;;
    esac
done

# ── Config: paths to scan ──
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARENT_DIR="$(dirname "$PROJECT_ROOT")"

# ── Detect keychain availability ──
KEYCHAIN_AVAILABLE=false
if [[ "$(uname -s)" == "Darwin" ]] && command -v security &>/dev/null; then
    KEYCHAIN_TYPE="macOS Keychain"
    KEYCHAIN_AVAILABLE=true
elif command -v secret-tool &>/dev/null; then
    KEYCHAIN_TYPE="Linux Secret Service"
    KEYCHAIN_AVAILABLE=true
else
    KEYCHAIN_TYPE="不可用"
fi

echo "┌──────────────────────────────────────────┐"
echo "│  Synapse Key Isolation Audit             │"
echo "│  P11-B35 — P-045 Key 冒充防护            │"
echo "│  密钥链: ${KEYCHAIN_TYPE}                 │"
echo "└──────────────────────────────────────────┘"
echo ""

FOUND_PLAINTEXT=0
FOUND_PERM_ISSUE=0
WORKER_COUNT=0

# ── Scan for Worker directories ──
scan_worker_dir() {
    local dir="$1"
    local env_file="${dir}/.env"

    if [[ ! -f "$env_file" ]]; then
        return 0  # No .env, skip
    fi

    # Check if this is a Synapse Worker .env (has SYNAPSE_WORKER_ID)
    if ! grep -q "SYNAPSE_WORKER_ID=" "$env_file" 2>/dev/null; then
        return 0  # Not a Synapse Worker
    fi

    WORKER_COUNT=$((WORKER_COUNT + 1))
    local worker_id
    worker_id=$(grep "SYNAPSE_WORKER_ID=" "$env_file" | head -1 | cut -d'=' -f2 | tr -d ' ')
    local dir_name
    dir_name=$(basename "$dir")

    echo -e "${BLUE}▎ Worker: ${dir_name} (${worker_id})${NC}"

    # ── Check 1: Plaintext API key in .env ──
    if grep -qE "^SYNAPSE_API_KEY=sk-syn-" "$env_file" 2>/dev/null; then
        FOUND_PLAINTEXT=$((FOUND_PLAINTEXT + 1))
        local key_preview
        key_preview=$(grep -E "^SYNAPSE_API_KEY=sk-syn-" "$env_file" | head -1 | cut -c1-60)

        if $STRICT; then
            echo -e "  ${RED}❌ 明文 API Key 暴露: ${key_preview}...${NC}"
            EXIT_CODE=1
        else
            echo -e "  ${YELLOW}⚠️  明文 API Key 暴露: ${key_preview}...${NC}"
        fi
        echo -e "  ${YELLOW}   → 迁移: synapse-key.sh store ${worker_id} \$(grep SYNAPSE_API_KEY .env | cut -d= -f2)${NC}"
    else
        echo -e "  ${GREEN}✅ .env 无明文 Key${NC}"
    fi

    # ── Check 2: File permissions ──
    local perms
    perms=$(stat -f "%Lp" "$env_file" 2>/dev/null || stat -c "%a" "$env_file" 2>/dev/null || echo "unknown")
    if [[ "$perms" != "600" && "$perms" != "unknown" ]]; then
        FOUND_PERM_ISSUE=$((FOUND_PERM_ISSUE + 1))
        echo -e "  ${YELLOW}⚠️  文件权限: ${perms}（建议 600）${NC}"
        if $FIX; then
            chmod 600 "$env_file"
            echo -e "  ${GREEN}  → 已修复: chmod 600${NC}"
        fi
    else
        echo -e "  ${GREEN}✅ 文件权限: ${perms}${NC}"
    fi

    # ── Check 3: Keychain integration ──
    if $KEYCHAIN_AVAILABLE; then
        if [[ "$(uname -s)" == "Darwin" ]]; then
            if security find-generic-password -a "synapse-worker-${worker_id}" -s "synapse" &>/dev/null 2>&1; then
                echo -e "  ${GREEN}✅ 密钥链已集成${NC}"
            else
                echo -e "  ${YELLOW}⚠️  密钥链未集成 — 运行: synapse-key.sh store${NC}"
            fi
        fi
    else
        echo -e "  ${BLUE}ℹ️  密钥链不可用 — .env 为唯一存储${NC}"
    fi

    echo ""
}

# ── Scan: current project Workers (synapse-builder, synapse-orchestrator, etc.) ──
for dir in "$PARENT_DIR"/synapse-*/; do
    [[ -d "$dir" ]] || continue
    dir_name=$(basename "$dir")

    # Skip main synapse repo
    [[ "$dir_name" == "synapse" ]] && continue
    # Skip non-Worker dirs (like synapse-co* if they exist)
    [[ "$dir_name" =~ ^synapse-(builder|orchestrator|steward|worker) ]] || continue

    scan_worker_dir "$dir"
done

# ── Also check main synapse/.env (server config, not Worker) ──
if [[ -f "$PROJECT_ROOT/synapse/.env" ]]; then
    if grep -qE "^SYNAPSE_API_KEY=sk-syn-" "$PROJECT_ROOT/synapse/.env" 2>/dev/null; then
        echo -e "${YELLOW}⚠️  synapse/.env 包含 API Key（服务端 .env 不应存储 Worker Key）${NC}"
    fi
fi

# ── Summary ──
echo "────────────────────────────────────────────"
echo -e "Workers 扫描: ${WORKER_COUNT}"
echo -e "明文 Key 暴露: ${FOUND_PLAINTEXT}"
echo -e "权限问题: ${FOUND_PERM_ISSUE}"

if [[ $WORKER_COUNT -eq 0 ]]; then
    echo -e "${YELLOW}⚠️  未发现 Worker 目录${NC}"
fi

if [[ $FOUND_PLAINTEXT -eq 0 && $FOUND_PERM_ISSUE -eq 0 ]]; then
    echo -e "\n${GREEN}✅ 所有 Worker 密钥隔离达标${NC}"
elif $STRICT && [[ $FOUND_PLAINTEXT -gt 0 ]]; then
    echo -e "\n${RED}❌ 严格模式: 发现 ${FOUND_PLAINTEXT} 个明文 Key 暴露${NC}"
else
    echo -e "\n${YELLOW}⚠️  存在 ${FOUND_PLAINTEXT} 个明文 Key + ${FOUND_PERM_ISSUE} 个权限问题${NC}"
    echo -e "${YELLOW}   → P-045 短期规则(禁止 Key 冒充)已生效 · 建议迁移到密钥链${NC}"
fi

exit $EXIT_CODE
