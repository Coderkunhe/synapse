#!/usr/bin/env bash
# check-env-consistency.sh — ENV-2: .env ↔ Keychain ↔ launchd 密钥一致性检查
#
# 扫描所有 Worker 工作目录，检测：
# 1. .env 中 SYNAPSE_API_KEY 与 macOS Keychain 值是否一致
# 2. launchd plist EnvironmentVariables 中的 SYNAPSE_API_KEY 是否与 .env 一致
# 3. SYNAPSE_WORKER_ID 是否与 keychain account 名一致
#
# P12-B24: D1 ENV-2 🔴→🟢 — 覆盖 session-init.js checkEnv() 盲区
#   现有检查只看 keychain entry 存在性和 .env 格式，不看值是否一致
#
# Usage:
#   check-env-consistency.sh [--fix] [--strict]
#     --fix      以 .env 值为准，自动重写 keychain（调用 synapse-key.sh store）
#     --strict   任何不一致视为 ERROR（退出码非零），否则 WARNING
#
# Exit codes:
#   0 - 所有 Worker 的 .env ↔ keychain ↔ launchd 一致
#   1 - 发现不一致（--strict 模式）或 --fix 修复失败
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

# ── Path resolution ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
# Workers live alongside the ai-synapse repo, not inside it
# ai-synapse/synapse/tools → ai-synapse/synapse → ai-synapse → ai/
GRANDPARENT_DIR="$(dirname "$(dirname "$PROJECT_DIR")")"

# ── Detect keychain availability ──
KEYCHAIN_AVAILABLE=false
if [[ "$(uname -s)" == "Darwin" ]] && command -v security &>/dev/null; then
    KEYCHAIN_AVAILABLE=true
fi

# ── Locate synapse-key.sh ──
SYNAPSE_KEY_SCRIPT="$SCRIPT_DIR/synapse-key.sh"

# ── Counters ──
WORKER_COUNT=0
KEYCHAIN_MISMATCH=0
LAUNCHD_MISMATCH=0
FIXED=0

# ── Helper: get tail of API key (last 8 chars, for safe printing) ──
key_tail() {
    local key="$1"
    echo "${key: -8}"
}

# ── Helper: SHA-256 of a value (for comparison without printing) ──
sha_of() {
    local val="$1"
    if [[ -z "$val" ]]; then
        echo "EMPTY"
    else
        echo "$val" | shasum -a 256 | cut -d' ' -f1
    fi
}

# ── Helper: read env var from .env file ──
read_env_var() {
    local env_file="$1"
    local var_name="$2"
    grep "^${var_name}=" "$env_file" 2>/dev/null | head -1 | sed "s/^${var_name}=//" || echo ""
}

check_worker_consistency() {
    local worker_dir="$1"
    local dir_name
    dir_name=$(basename "$worker_dir")

    local env_file="$worker_dir/.claude/.env"
    if [[ ! -f "$env_file" ]]; then
        echo -e "  ${YELLOW}⚠️  无 .claude/.env — 跳过${NC}"
        return
    fi

    local worker_id
    worker_id=$(read_env_var "$env_file" "SYNAPSE_WORKER_ID")
    local env_key
    env_key=$(read_env_var "$env_file" "SYNAPSE_API_KEY")

    if [[ -z "$worker_id" ]]; then
        echo -e "  ${YELLOW}⚠️  .env 缺少 SYNAPSE_WORKER_ID — 跳过${NC}"
        return
    fi

    if [[ -z "$env_key" ]]; then
        echo -e "  ${RED}❌ .env 缺少 SYNAPSE_API_KEY${NC}"
        EXIT_CODE=1
        return
    fi

    WORKER_COUNT=$((WORKER_COUNT + 1))
    local had_error=false

    # ── Check 1: .env vs Keychain ──
    if $KEYCHAIN_AVAILABLE; then
        local keychain_account="synapse-worker-${worker_id}"
        local keychain_key
        keychain_key=$(security find-generic-password -a "$keychain_account" -s "synapse" -w 2>/dev/null || echo "")

        if [[ -z "$keychain_key" ]]; then
            echo -e "  ${YELLOW}⚠️  Keychain 中无 ${keychain_account} entry${NC}"
            echo -e "     → 建议: synapse-key.sh store ${worker_id} <key>"
        else
            local env_sha keychain_sha
            env_sha=$(sha_of "$env_key")
            keychain_sha=$(sha_of "$keychain_key")

            if [[ "$env_sha" != "$keychain_sha" ]]; then
                echo -e "  ${RED}❌ .env ↔ Keychain 不一致${NC}"
                echo -e "     .env key 尾号: ...${BLUE}$(key_tail "$env_key")${NC}"
                echo -e "     Keychain 尾号: ...${BLUE}$(key_tail "$keychain_key")${NC}"
                KEYCHAIN_MISMATCH=$((KEYCHAIN_MISMATCH + 1))
                had_error=true

                if $FIX; then
                    echo -e "     ${GREEN}→ --fix: 以 .env 值为准重写 keychain...${NC}"
                    if bash "$SYNAPSE_KEY_SCRIPT" store "$worker_id" "$env_key" 2>/dev/null; then
                        echo -e "     ${GREEN}  ✅ 已修复${NC}"
                        FIXED=$((FIXED + 1))
                        had_error=false
                    else
                        echo -e "     ${RED}  ❌ 修复失败 — 检查 synapse-key.sh 权限${NC}"
                    fi
                else
                    echo -e "     → 修复: check-env-consistency.sh --fix 或 synapse-key.sh store ${worker_id} <key>"
                fi
            else
                echo -e "  ${GREEN}✅ .env ↔ Keychain 一致 (尾号 ...$(key_tail "$env_key"))${NC}"
            fi
        fi
    else
        echo -e "  ${BLUE}ℹ️  密钥链不可用 — 跳过 keychain 比对${NC}"
    fi

    # ── Check 2: .env vs launchd plist (macOS only) ──
    if [[ "$(uname -s)" == "Darwin" ]]; then
        local plist_path="$HOME/Library/LaunchAgents/com.synapse.worker-${dir_name#synapse-}.plist"
        # Also try without the role suffix (e.g., com.synapse.worker-builder.plist)
        if [[ ! -f "$plist_path" ]]; then
            # Try to find any plist that references this worker_id
            local found_plist
            found_plist=$(grep -l "$worker_id" "$HOME/Library/LaunchAgents"/com.synapse.worker-*.plist 2>/dev/null | head -1 || echo "")
            if [[ -n "$found_plist" ]]; then
                plist_path="$found_plist"
            fi
        fi

        if [[ -f "$plist_path" ]]; then
            # Extract SYNAPSE_API_KEY from plist EnvironmentVariables dict
            local plist_key
            plist_key=$(/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:SYNAPSE_API_KEY" "$plist_path" 2>/dev/null || echo "")

            if [[ -n "$plist_key" ]]; then
                local plist_sha
                plist_sha=$(sha_of "$plist_key")

                if [[ "$plist_sha" != "$(sha_of "$env_key")" ]]; then
                    echo -e "  ${RED}❌ .env ↔ launchd plist 不一致${NC}"
                    echo -e "     plist: $(basename "$plist_path")"
                    echo -e "     .env key 尾号: ...${BLUE}$(key_tail "$env_key")${NC}"
                    echo -e "     plist key 尾号: ...${BLUE}$(key_tail "$plist_key")${NC}"
                    LAUNCHD_MISMATCH=$((LAUNCHD_MISMATCH + 1))
                    had_error=true
                    echo -e "     → 修复: 更新 plist 中的 SYNAPSE_API_KEY 或重新运行 bootstrap-worker.sh"
                else
                    echo -e "  ${GREEN}✅ .env ↔ launchd plist 一致${NC}"
                fi
            fi
        fi
    fi

    if $had_error; then
        EXIT_CODE=1
    fi

    echo ""
}

# ════════════════════════════════════════════════════════════
echo "════════════════════════════════════════════════"
echo -e "${BLUE}🔍 ENV-2: .env ↔ Keychain ↔ launchd 一致性检查${NC}"
echo "════════════════════════════════════════════════"
echo ""

# ── Scan: Worker directories (same pattern as check-key-isolation.sh) ──
for dir in "$GRANDPARENT_DIR"/synapse-*/; do
    [[ -d "$dir" ]] || continue
    dir_name=$(basename "$dir")

    # Skip main synapse repo
    [[ "$dir_name" == "synapse" ]] && continue
    # Skip non-Worker dirs
    [[ "$dir_name" =~ ^synapse-(builder|orchestrator|steward|worker) ]] || continue

    echo -e "${BLUE}📁 ${dir_name}${NC}"
    check_worker_consistency "$dir"
done

# ── Summary ──
echo "────────────────────────────────────────────"
echo -e "Workers 扫描: ${WORKER_COUNT}"
echo -e ".env ↔ Keychain 不一致: ${KEYCHAIN_MISMATCH}"
echo -e ".env ↔ launchd 不一致:  ${LAUNCHD_MISMATCH}"

if $FIX && [[ $FIXED -gt 0 ]]; then
    echo -e "\n${GREEN}🔧 --fix: 已修复 ${FIXED} 项${NC}"
fi

if [[ $WORKER_COUNT -eq 0 ]]; then
    echo -e "\n${YELLOW}⚠️  未发现 Worker 目录 — 检查 GRANDPARENT_DIR=${GRANDPARENT_DIR}${NC}"
elif [[ $KEYCHAIN_MISMATCH -eq 0 && $LAUNCHD_MISMATCH -eq 0 ]]; then
    echo -e "\n${GREEN}✅ 所有 Worker 的 .env ↔ keychain ↔ launchd 一致${NC}"
elif $STRICT; then
    echo -e "\n${RED}❌ 严格模式: 发现 ${KEYCHAIN_MISMATCH} 个 keychain 不一致 + ${LAUNCHD_MISMATCH} 个 launchd 不一致${NC}"
else
    echo -e "\n${YELLOW}⚠️  发现 ${KEYCHAIN_MISMATCH} 个 keychain 不一致 + ${LAUNCHD_MISMATCH} 个 launchd 不一致${NC}"
    echo -e "${YELLOW}   → 运行 check-env-consistency.sh --fix 自动修复 keychain 不一致${NC}"
    echo -e "${YELLOW}   → launchd 不一致需手动更新 plist 或重跑 bootstrap-worker.sh${NC}"
fi

exit $EXIT_CODE
