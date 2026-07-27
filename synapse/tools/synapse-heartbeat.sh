#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# synapse-heartbeat.sh — 无脑幂等 Worker heartbeat
# ──────────────────────────────────────────────────────────────────
# 使用场景：
#   1. SessionStart hook 自动调用（每次 /clear 自动 heartbeat）
#   2. Worker Agent 在 _task-current.md 第一个 [REQUIRED] 步调用
#   3. 手动调用：bash tools/synapse-heartbeat.sh
#
# 依赖环境变量（由 SessionStart hook 或 .env 提供）：
#   SYNAPSE_API_URL   — e.g. http://127.0.0.1:8001
#   SYNAPSE_WORKER_ID — e.g. ag_019f7a7c7a6f7886
#   SYNAPSE_API_KEY   — Bearer token
#
# 退出码：
#   0 — 成功（即使 API 不可达也 exit 0，不阻断 hook 链）
#   非零仅用于脚本自身语法错误
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

# ── 环境变量加载 ──────────────────────────────────────────────
# 如果 env vars 未设置，尝试从 Worker 目录的 .env 加载
if [ -z "${SYNAPSE_WORKER_ID:-}" ] && [ -n "${CLAUDEDIR:-}" ]; then
    WORKER_DIR="${CLAUDEDIR}/.."
    if [ -f "$WORKER_DIR/.env" ]; then
        set -a; source "$WORKER_DIR/.env"; set +a
    fi
fi

# API key fallback：尝试 OS keychain（macOS / Linux）
if [ -z "${SYNAPSE_API_KEY:-}" ] && [ -n "${SYNAPSE_WORKER_ID:-}" ]; then
    if command -v security &>/dev/null; then
        SYNAPSE_API_KEY=$(security find-generic-password \
            -a "synapse-worker-${SYNAPSE_WORKER_ID}" \
            -s "synapse" -w 2>/dev/null || true)
    elif command -v secret-tool &>/dev/null; then
        SYNAPSE_API_KEY=$(secret-tool lookup \
            account "synapse-worker-${SYNAPSE_WORKER_ID}" \
            service "synapse" 2>/dev/null || true)
    fi
fi

# ── 门禁检查 ──────────────────────────────────────────────────
if [ -z "${SYNAPSE_WORKER_ID:-}" ]; then
    echo "🫀 heartbeat: SKIP (no SYNAPSE_WORKER_ID)"
    exit 0
fi

if [ -z "${SYNAPSE_API_KEY:-}" ]; then
    echo "🫀 heartbeat: SKIP (no API key — keychain may need setup)"
    exit 0
fi

API_URL="${SYNAPSE_API_URL:-http://127.0.0.1:8001}"

# ── Heartbeat 调用 ─────────────────────────────────────────────
# 超时 5s — heartbeat 不应阻塞 session 启动
RESP=$(curl -s -m 5 -X POST "${API_URL}/v1/workers/${SYNAPSE_WORKER_ID}/heartbeat" \
    -H "Authorization: Bearer ${SYNAPSE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"current_load":0}' 2>&1) || {
    echo "🫀 heartbeat: WARN (API unreachable — ${API_URL})"
    exit 0
}

# ── 结果解析 ──────────────────────────────────────────────────
RUNTIME=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('runtime_status','unknown'))" 2>/dev/null || echo "unknown")

case "$RUNTIME" in
    idle|busy|error)
        echo "🫀 heartbeat: ${RUNTIME}"
        ;;
    *)
        echo "🫀 heartbeat: done (raw: ${RUNTIME})"
        ;;
esac

exit 0
