#!/usr/bin/env bash
# synapse-health-check.sh — Worker 启动后 5 项健康自检（P13-B1）
#
# P13 Scout S3 信号：PFL-126/127/131/148/153 共同模式「Worker 在残缺状态静默运行」
# 本脚本在 Worker 启动链末尾运行，5 项全部通过 = Worker 就绪。
# 任一项失败 → 终端告警 + 非零退出码 + 诊断建议。
#
# Usage:
#   source .claude/.env 2>/dev/null || true
#   bash tools/synapse-health-check.sh          # 标准模式（仅输出失败项）
#   bash tools/synapse-health-check.sh -v       # 详细模式（输出全部检查结果）
#   bash tools/synapse-health-check.sh -q       # 安静模式（仅退出码，零 stdout — CI 友好）
#
# Environment:
#   SYNAPSE_API_URL      — Synapse Server 地址 (e.g. http://localhost:8001)
#   SYNAPSE_WORKER_ID    — Worker ID (e.g. wa_xxx)
#   SYNAPSE_API_KEY      — Bearer token
#   SYNAPSE_PROJECT_ID   — 所属 Project ID (optional, state file freshness 宽松判定时用)
#
# Exit codes:
#   0 — 5/5 通过
#   1 — 1+ 项失败
#   2 — 环境变量缺失（无法执行检查）
#   3 — 全部通过但有 ⚠️ 警告
#
# P13-3: 脚本化优先 — 本脚本替代"启动后手工检查 Worker 是否在线"的软约定。

set -euo pipefail

# ── Color helpers ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

VERBOSE=false
QUIET=false

# ── Parse flags ──
for arg in "$@"; do
    case "$arg" in
        -v|--verbose) VERBOSE=true ;;
        -q|--quiet) QUIET=true ;;
        -h|--help)
            echo "Usage: $0 [-v|--verbose] [-q|--quiet]"
            echo "  -v  详细模式（输出全部检查项）"
            echo "  -q  安静模式（仅退出码，CI 友好）"
            echo "  -h  帮助"
            exit 0
            ;;
    esac
done

$QUIET && VERBOSE=false

# ── State tracking ──
PASS=0
FAIL=0
WARN=0
CHECKS=()
FAILURES=()

# ── Log helpers ──
log_pass()  { PASS=$((PASS + 1)); CHECKS+=("✅ $1"); $QUIET || $VERBOSE && echo -e "  ${GREEN}✅${NC} $1"; }
log_fail()  { FAIL=$((FAIL + 1)); CHECKS+=("❌ $1"); $QUIET || echo -e "  ${RED}❌${NC} $1 — $2"; FAILURES+=("$1: $2"); }
log_warn()  { WARN=$((WARN + 1)); CHECKS+=("⚠️  $1"); $QUIET || $VERBOSE && echo -e "  ${YELLOW}⚠️${NC}  $1 — $2"; }

banner() {
    $QUIET && return
    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  Synapse Worker Health Check${NC}"
    echo -e "${BOLD}  $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# ── Prerequisites: verify env vars ──
check_env() {
    local missing=()
    for var in SYNAPSE_API_URL SYNAPSE_WORKER_ID SYNAPSE_API_KEY; do
        if [ -z "${!var:-}" ]; then
            missing+=("$var")
        fi
    done

    if [ ${#missing[@]} -gt 0 ]; then
        $QUIET || echo -e "${RED}❌ 缺少环境变量: ${missing[*]}${NC}"
        $QUIET || echo "   请先 source .claude/.env 或设置对应变量"
        exit 2
    fi

    $VERBOSE && echo -e "  ${GREEN}✓${NC} 环境变量齐全 (SYNAPSE_API_URL=$SYNAPSE_API_URL, WORKER=$SYNAPSE_WORKER_ID)"
}

# ── Check 1: API reachable + worker exists ──
check_api_worker() {
    local resp http_code
    resp=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer ${SYNAPSE_API_KEY}" \
        "${SYNAPSE_API_URL}/v1/workers/${SYNAPSE_WORKER_ID}" 2>&1) || true
    http_code=$(echo "$resp" | tail -1)
    local body=$(echo "$resp" | sed '$d')

    if [ "$http_code" = "200" ]; then
        local status name provider
        status=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "parse_error")
        name=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','unknown'))" 2>/dev/null || echo "unknown")
        provider=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('provider','unknown'))" 2>/dev/null || echo "unknown")

        case "$status" in
            ACTIVE|PENDING)
                log_pass "API 可达 · Worker 存在 · status=$status · provider=$provider · name=$name"
                ;;
            OFFLINE|SUSPENDED)
                log_warn "Worker status=$status (非 ACTIVE) — 可能已被标记离线 · 请检查 heartbeat" "status=$status"
                ;;
            *)
                log_fail "Worker status=$status — 意外状态 · 预期 ACTIVE" "unexpected status=$status"
                ;;
        esac
    elif [ "$http_code" = "404" ]; then
        log_fail "Worker 不存在 ($SYNAPSE_WORKER_ID) — 请检查 SYNAPSE_WORKER_ID 是否正确" "HTTP $http_code"
    elif [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
        log_fail "API 认证失败 — 请检查 SYNAPSE_API_KEY 是否有效" "HTTP $http_code"
    else
        log_fail "API 不可达 — HTTP $http_code · 请检查 SYNAPSE_API_URL=$SYNAPSE_API_URL" "HTTP $http_code"
    fi
}

# ── Check 2: Handshake — POST /workers/{id}/handshake → 200 ──
check_handshake() {
    local resp http_code
    resp=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SYNAPSE_API_KEY}" \
        "${SYNAPSE_API_URL}/v1/workers/${SYNAPSE_WORKER_ID}/handshake" 2>&1) || true
    http_code=$(echo "$resp" | tail -1)

    if [ "$http_code" = "200" ]; then
        log_pass "Handshake 成功 (POST /workers/{id}/handshake → 200)"
    elif [ "$http_code" = "409" ]; then
        # 409 = already ACTIVE (handshake is idempotent-ish)
        log_pass "Handshake 跳过 (Worker 已 ACTIVE · 409 视为正常)"
    else
        log_fail "Handshake 失败 — HTTP $http_code · Worker 可能无法正确注册" "HTTP $http_code"
    fi
}

# ── Check 3: Heartbeat fresh — POST /workers/{id}/heartbeat → 200 ──
check_heartbeat() {
    local resp http_code server_time
    resp=$(curl -s -w "\n%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SYNAPSE_API_KEY}" \
        -H "Content-Type: application/json" \
        -d '{}' \
        "${SYNAPSE_API_URL}/v1/workers/${SYNAPSE_WORKER_ID}/heartbeat" 2>&1) || true
    http_code=$(echo "$resp" | tail -1)
    local body=$(echo "$resp" | sed '$d')

    if [ "$http_code" = "200" ]; then
        # Extract server time from response for freshness check
        server_time=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('server_time',''))" 2>/dev/null || echo "")
        if [ -n "$server_time" ]; then
            log_pass "Heartbeat 成功 · server_time=$server_time"
        else
            log_pass "Heartbeat 成功 (HTTP 200)"
        fi
    else
        log_fail "Heartbeat 失败 — HTTP $http_code · daemon 可能未运行" "HTTP $http_code"
    fi
}

# ── Check 4: State file fresh — _task-current.md exists + recently modified ──
check_state_file() {
    # P12-B32: session-init.js writes to skills/synapse/_task-current.md + root copy
    # Check both locations
    local state_file=""
    local candidate_paths=(
        "${PWD}/.claude/skills/synapse/_task-current.md"
        "${PWD}/_task-current.md"
    )

    for p in "${candidate_paths[@]}"; do
        if [ -f "$p" ]; then
            state_file="$p"
            break
        fi
    done

    if [ -z "$state_file" ]; then
        log_fail "State file 不存在 — session-init.js 可能未运行 · 检查路径: ${candidate_paths[*]}" \
            "找不到 _task-current.md (尝试了 ${#candidate_paths[@]} 个路径)"
        return
    fi

    # Check freshness: modified within last 10 minutes (= 600 seconds)
    local now mtime age_min
    now=$(date +%s)
    mtime=$(stat -f %m "$state_file" 2>/dev/null || stat -c %Y "$state_file" 2>/dev/null || echo "0")
    age_sec=$((now - mtime))
    age_min=$((age_sec / 60))

    if [ "$age_sec" -lt 600 ]; then
        log_pass "State file 存在且新鲜 · ${age_min}min 前更新 · $state_file"
    elif [ "$age_sec" -lt 1800 ]; then
        log_warn "State file 较旧 · ${age_min}min 前更新 · 可能 SessionStart hook 未触发 · 建议检查 .claude/_last-session-init.txt" \
            "age=${age_min}min (阈值 10min)"
    else
        log_fail "State file 过期 · ${age_min}min 前更新 · session-init.js 可能未运行或 hook 未触发" \
            "age=${age_min}min (>30min 过期)"
    fi
}

# ── Check 5: Hook sentinel — SessionStart hook 是否触发过 ──
check_hook_sentinel() {
    local sentinel="${PWD}/.claude/_last-session-init.txt"

    if [ -f "$sentinel" ]; then
        local age_sec age_min now mtime
        now=$(date +%s)
        mtime=$(stat -f %m "$sentinel" 2>/dev/null || stat -c %Y "$sentinel" 2>/dev/null || echo "0")
        age_sec=$((now - mtime))
        age_min=$((age_sec / 60))

        if [ "$age_sec" -lt 600 ]; then
            log_pass "Hook sentinel 存在且新鲜 · ${age_min}min 前 · SessionStart hook 正常触发"
        else
            log_warn "Hook sentinel 较旧 · ${age_min}min 前 · SessionStart hook 可能未在最近会话触发（CronCreate 唤醒属正常）" \
                "sentinel age=${age_min}min"
        fi
    else
        log_fail "Hook sentinel 缺失 — SessionStart hook 从未触发 · session-init.js 不运行 → daemon 不启动 → Worker 假在线" \
            "缺少 .claude/_last-session-init.txt"
    fi
}

# ── Daemon process check (bonus · not counted in 5) ──
check_daemon_processes() {
    $VERBOSE || return 0

    local hb_count ws_count
    hb_count=$(pgrep -f "heartbeat.js" 2>/dev/null | wc -l | tr -d ' ')
    ws_count=$(pgrep -f "ws-daemon.js" 2>/dev/null | wc -l | tr -d ' ')

    if [ "${hb_count:-0}" -gt 0 ] && [ "${ws_count:-0}" -gt 0 ]; then
        echo -e "  ${GREEN}ℹ${NC}  Daemon 进程: heartbeat=${hb_count} · ws-daemon=${ws_count}"
    elif [ "${hb_count:-0}" -eq 0 ] && [ "${ws_count:-0}" -eq 0 ]; then
        echo -e "  ${YELLOW}ℹ${NC}  Daemon 进程未检测到 (heartbeat=0 · ws-daemon=0) — 如果 Worker 不是本机运行，此检查不适用"
    else
        echo -e "  ${YELLOW}ℹ${NC}  Daemon 进程部分运行: heartbeat=${hb_count:-0} · ws-daemon=${ws_count:-0}"
    fi
}

# ── Summary ──
summary() {
    $QUIET && exit $([ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ] && echo 0 || [ "$FAIL" -gt 0 ] && echo 1 || echo 3)

    echo ""
    echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    local total=$((PASS + FAIL + WARN))
    if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
        echo -e "  ${GREEN}${BOLD}✅ 全部通过${NC} · ${PASS}/${total} 项健康检查通过"
        echo -e "  ${GREEN}Worker 就绪 — 可以开始工作${NC}"
        echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        exit 0
    elif [ "$FAIL" -eq 0 ]; then
        echo -e "  ${YELLOW}${BOLD}⚠️  通过（有警告）${NC} · ${PASS}/${total} 通过 · ${WARN} 警告"
        echo -e "  ${YELLOW}Worker 基本可用，但建议修复警告项${NC}"
        echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        exit 3
    else
        echo -e "  ${RED}${BOLD}❌ 未通过${NC} · ${FAIL}/${total} 项失败"
        echo ""
        echo -e "  ${RED}失败项:${NC}"
        for f in "${FAILURES[@]}"; do
            echo -e "    ${RED}▸${NC} $f"
        done
        echo ""
        echo -e "  ${YELLOW}诊断建议:${NC}"
        echo "    1. 确认 .claude/.env 中的 SYNAPSE_API_KEY 有效"
        echo "    2. 确认 Synapse Server 正在运行: curl \$SYNAPSE_API_URL/health"
        echo "    3. 确认 session-init.js 已运行: node scripts/session-init.js"
        echo "    4. 如果 hook sentinel 缺失: 新开会话或手动运行 session-init.js"
        echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        exit 1
    fi
}

# ── Main ──
main() {
    banner
    check_env

    $QUIET || echo -e "${BOLD}健康检查 (5 项):${NC}"
    check_api_worker
    check_handshake
    check_heartbeat
    check_state_file
    check_hook_sentinel

    $VERBOSE && check_daemon_processes

    summary
}

main "$@"
