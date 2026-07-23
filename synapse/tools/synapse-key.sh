#!/usr/bin/env bash
# synapse-key.sh — Synapse Worker API Key 隔离存储（OS Keychain 集成）
#
# 将 Worker API Key 存储在操作系统密钥链中，而非磁盘明文文件，
# 防止同一主机上其他 Worker 会话读取 API Key 进行角色冒充（P-045）。
#
# Usage:
#   synapse-key.sh store  <worker_id> <api_key>   — 存入密钥链
#   synapse-key.sh get    <worker_id>              — 从密钥链读取（输出到 stdout）
#   synapse-key.sh delete <worker_id>              — 从密钥链删除
#   synapse-key.sh check  <worker_id>              — 检查密钥是否存在（exit code）
#   synapse-key.sh verify <worker_id> <api_url>    — 验证密钥是否有效（调 API）
#
# Tier 1 (macOS):  security add-generic-password / find-generic-password
# Tier 2 (Linux):  secret-tool store / lookup (libsecret)
# Tier 3 (fallback): 警告 + 返回 .env 明文（兼容性兜底）
#
# P11-B35: Key 隔离 — 防止跨 Worker API Key 冒充

set -euo pipefail

SERVICE_NAME="synapse"
KEYCHAIN_ACCOUNT_PREFIX="synapse-worker-"

# ── Color helpers ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

usage() {
    echo "Usage: $0 <store|get|delete|check|verify> <worker_id> [api_key|api_url]"
    echo ""
    echo "Commands:"
    echo "  store  <worker_id> <api_key>    Store API key in OS keychain"
    echo "  get    <worker_id>              Retrieve API key from keychain"
    echo "  delete <worker_id>              Remove API key from keychain"
    echo "  check  <worker_id>              Verify key exists (exit 0) or not (exit 1)"
    echo "  verify <worker_id> <api_url>    Test key against Synapse API"
    exit 1
}

# ── Tier detection ──

detect_tier() {
    if [[ "$(uname -s)" == "Darwin" ]] && command -v security &>/dev/null; then
        echo "macos-keychain"
    elif command -v secret-tool &>/dev/null; then
        echo "linux-libsecret"
    else
        echo "fallback"
    fi
}

# ── macOS Keychain ──

store_macos() {
    local worker_id="$1"
    local api_key="$2"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    # Delete existing entry (idempotent)
    security delete-generic-password -a "$account" -s "$SERVICE_NAME" &>/dev/null || true

    # Store
    security add-generic-password \
        -a "$account" \
        -s "$SERVICE_NAME" \
        -w "$api_key" \
        -U \
        -T "$(command -v security)" 2>/dev/null

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✅ API Key 已存入 macOS Keychain (worker: ${worker_id})${NC}"
    else
        echo -e "${RED}❌ macOS Keychain 写入失败${NC}" >&2
        return 1
    fi
}

get_macos() {
    local worker_id="$1"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    security find-generic-password \
        -a "$account" \
        -s "$SERVICE_NAME" \
        -w 2>/dev/null
}

delete_macos() {
    local worker_id="$1"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    if security delete-generic-password -a "$account" -s "$SERVICE_NAME" &>/dev/null; then
        echo -e "${GREEN}✅ API Key 已从 macOS Keychain 删除 (worker: ${worker_id})${NC}"
    else
        echo -e "${YELLOW}⚠️  未找到 keychain 条目 (worker: ${worker_id})${NC}"
    fi
}

check_macos() {
    local worker_id="$1"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    security find-generic-password -a "$account" -s "$SERVICE_NAME" &>/dev/null
}

# ── Linux libsecret ──

store_linux() {
    local worker_id="$1"
    local api_key="$2"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    # libsecret doesn't have a "delete first" pattern — store overwrites
    echo -n "$api_key" | secret-tool store \
        --label="Synapse Worker ${worker_id}" \
        account "$account" \
        service "$SERVICE_NAME" 2>/dev/null

    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✅ API Key 已存入 Secret Service (worker: ${worker_id})${NC}"
    else
        echo -e "${RED}❌ Secret Service 写入失败（dbus/libsecret 是否运行？）${NC}" >&2
        return 1
    fi
}

get_linux() {
    local worker_id="$1"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    secret-tool lookup account "$account" service "$SERVICE_NAME" 2>/dev/null
}

delete_linux() {
    local worker_id="$1"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    if secret-tool clear account "$account" service "$SERVICE_NAME" 2>/dev/null; then
        echo -e "${GREEN}✅ API Key 已从 Secret Service 删除 (worker: ${worker_id})${NC}"
    else
        echo -e "${YELLOW}⚠️  未找到 secret (worker: ${worker_id})${NC}"
    fi
}

check_linux() {
    local worker_id="$1"
    local account="${KEYCHAIN_ACCOUNT_PREFIX}${worker_id}"

    [[ -n "$(secret-tool lookup account "$account" service "$SERVICE_NAME" 2>/dev/null)" ]]
}

# ── Fallback (plaintext .env) ──

warn_fallback() {
    echo -e "${YELLOW}⚠️  操作系统密钥链不可用（无 security CLI / secret-tool）。${NC}" >&2
    echo -e "${YELLOW}   API Key 将回退到 .env 文件 — 请确保文件权限为 600。${NC}" >&2
}

# ── Main dispatch ──

main() {
    if [[ $# -lt 2 ]]; then
        usage
    fi

    local cmd="$1"
    local worker_id="$2"
    local tier
    tier=$(detect_tier)

    case "$cmd" in
        store)
            if [[ $# -lt 3 ]]; then
                echo -e "${RED}❌ store 需要 <worker_id> <api_key>${NC}" >&2
                usage
            fi
            local api_key="$3"
            case "$tier" in
                macos-keychain) store_macos "$worker_id" "$api_key" ;;
                linux-libsecret) store_linux "$worker_id" "$api_key" ;;
                fallback)
                    warn_fallback
                    echo -e "${YELLOW}   store 操作在 fallback 模式下无效果 — 请手动管理 .env。${NC}"
                    ;;
            esac
            ;;
        get)
            case "$tier" in
                macos-keychain) get_macos "$worker_id" ;;
                linux-libsecret) get_linux "$worker_id" ;;
                fallback)
                    echo -e "${YELLOW}⚠️  密钥链不可用。请从 .env 文件中读取 SYNAPSE_API_KEY。${NC}" >&2
                    exit 1
                    ;;
            esac
            ;;
        delete)
            case "$tier" in
                macos-keychain) delete_macos "$worker_id" ;;
                linux-libsecret) delete_linux "$worker_id" ;;
                fallback)
                    echo -e "${YELLOW}⚠️  密钥链不可用。请手动从 .env 中删除 SYNAPSE_API_KEY。${NC}" >&2
                    ;;
            esac
            ;;
        check)
            case "$tier" in
                macos-keychain) check_macos "$worker_id" ;;
                linux-libsecret) check_linux "$worker_id" ;;
                fallback)
                    echo -e "${YELLOW}⚠️  密钥链不可用。无法检查。${NC}" >&2
                    exit 1
                    ;;
            esac
            ;;
        verify)
            if [[ $# -lt 3 ]]; then
                echo -e "${RED}❌ verify 需要 <worker_id> <api_url>${NC}" >&2
                usage
            fi
            local api_url="$3"
            local key
            key=$("$0" get "$worker_id" 2>/dev/null) || {
                echo -e "${RED}❌ 无法获取 API Key${NC}" >&2
                exit 1
            }
            local http_code
            http_code=$(curl -sS -o /dev/null -w "%{http_code}" \
                -H "Authorization: Bearer $key" \
                "${api_url}/v1/workers/${worker_id}/me" 2>&1) || true

            if [[ "$http_code" == "200" ]]; then
                echo -e "${GREEN}✅ API Key 有效 (HTTP ${http_code})${NC}"
                exit 0
            else
                echo -e "${RED}❌ API Key 验证失败 (HTTP ${http_code})${NC}" >&2
                exit 1
            fi
            ;;
        *)
            echo -e "${RED}❌ 未知命令: $cmd${NC}" >&2
            usage
            ;;
    esac
}

main "$@"
