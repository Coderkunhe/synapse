#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# worker-health-report.sh — Worker 心跳健康摘要 CLI（P16-B6 任务 C）
# ──────────────────────────────────────────────────────────────────
# 使用场景：
#   1. 人类排障：快速看某个 Worker 最近 24h 心跳稳不稳
#   2. 脚本化监控：对接 GET /v1/workers/{worker_id}/health-summary
#
# 用法：
#   tools/worker-health-report.sh <worker_id>
#
# 依赖环境变量（env 未设时回退读 .claude/.env，与仓库其它 *.sh 一致）：
#   SYNAPSE_API_URL   — e.g. http://127.0.0.1:8000
#   SYNAPSE_API_KEY   — Bearer token
#
# 退出码：
#   0 — 成功（六字段表格输出到 stdout）
#   1 — 端点非 2xx / 网络失败（错误信息含 HTTP 状态码，打到 stderr）
#   2 — 缺参数（usage 打到 stderr）
#   3 — 缺 SYNAPSE_API_URL / SYNAPSE_API_KEY（stderr 报错）
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

# ── 参数门禁 ─────────────────────────────────────────────────────
if [ $# -lt 1 ]; then
    echo "usage: tools/worker-health-report.sh <worker_id>" >&2
    exit 2
fi

WORKER_ID="$1"

# ── 环境变量加载 ─────────────────────────────────────────────────
# 与 synapse-heartbeat.sh 一致：env 未设时尝试 .claude/.env
if [ -z "${SYNAPSE_API_URL:-}" ] || [ -z "${SYNAPSE_API_KEY:-}" ]; then
    if [ -f ".claude/.env" ]; then
        set -a; . ".claude/.env"; set +a
    fi
fi

if [ -z "${SYNAPSE_API_URL:-}" ]; then
    echo "worker-health-report: error: SYNAPSE_API_URL is not set" >&2
    exit 3
fi

if [ -z "${SYNAPSE_API_KEY:-}" ]; then
    echo "worker-health-report: error: SYNAPSE_API_KEY is not set" >&2
    exit 3
fi

# ── 调端点 ───────────────────────────────────────────────────────
# -w '\n%{http_code}' 在 body 后追加一行 HTTP 状态码，便于区分 body 与状态码。
API_URL="${SYNAPSE_API_URL%/}"

if ! HTTP_OUT="$(curl -s -m 10 -w $'\n%{http_code}' \
        -H "Authorization: Bearer ${SYNAPSE_API_KEY}" \
        "${API_URL}/v1/workers/${WORKER_ID}/health-summary")"; then
    echo "worker-health-report: error: request failed (${API_URL})" >&2
    exit 1
fi

# 最后一行是状态码，前面是响应 body
HTTP_CODE="${HTTP_OUT##*$'\n'}"
BODY="${HTTP_OUT%$'\n'*}"

if [[ ! "$HTTP_CODE" =~ ^2[0-9][0-9]$ ]]; then
    echo "worker-health-report: error: GET ${API_URL}/v1/workers/${WORKER_ID}/health-summary returned HTTP ${HTTP_CODE}" >&2
    if [ -n "$BODY" ]; then
        echo "$BODY" >&2
    fi
    exit 1
fi

# ── 六字段表格化输出（表头 + 值，列对齐） ──────────────────────
echo "$BODY" | python3 -c '
import sys, json

def fmt(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    return str(v)

d = json.load(sys.stdin)
rows = [
    ("worker_id", d["worker_id"]),
    ("last_heartbeat_at", d["last_heartbeat_at"]),
    ("heartbeat_count", d["heartbeat_count"]),
    ("avg_interval_seconds", d["avg_interval_seconds"]),
    ("is_online", d["is_online"]),
    ("window_hours", d["window_hours"]),
]
width = max(len(k) for k, _ in rows)
for k, v in rows:
    print(k.ljust(width) + "  " + fmt(v))
'

exit 0
