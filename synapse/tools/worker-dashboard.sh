#!/usr/bin/env bash
# worker-dashboard.sh — God's-eye Worker 进度面板
#
# 用法:
#   worker-dashboard.sh [--team-id <id>] [--project-id <id>] [--watch] [--json]
#
# 功能:
#   DG-1: 单命令查看所有 Worker 状态（角色/心跳/活跃任务/进度）
#   DG-2: 自动诊断卡住任务（in_progress 超时/心跳过期）
#   --watch: 每 30s 自动刷新
#   --json: 机器可读输出
#
# D1 Scout: DG-1 🔴→🟢 · DG-2 🔴→🟢 (P12-B16)
#
# 依赖: curl + jq

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$SCRIPT_DIR/.." && pwd)")"

# ── 默认值 ────────────────────────────────────────────────────
API_URL="${SYNAPSE_API_URL:-http://localhost:8001}"
API_KEY="${SYNAPSE_API_KEY:-}"
WORKER_ID="${SYNAPSE_WORKER_ID:-}"
PROJECT_ID="${SYNAPSE_PROJECT_ID:-}"
TEAM_ID="${SYNAPSE_TEAM_ID:-}"
WATCH_MODE=false
JSON_MODE=false

# 阈值
STALE_HEARTBEAT_SEC=300       # 5 min — 心跳过期
STALE_PROGRESS_SEC=900        # 15 min — 任务卡住
WARN_HEARTBEAT_SEC=120        # 2 min — 心跳偏慢

# ── 颜色 ──────────────────────────────────────────────────────
BOLD='\033[1m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── 使用说明 ──────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: worker-dashboard.sh [options]

God's-eye Worker 进度面板 — 一次命令看清所有 Worker 的运行状态。

Options:
  --team-id <id>       Team ID（或 \$SYNAPSE_TEAM_ID）
  --project-id <id>    Project ID（或 \$SYNAPSE_PROJECT_ID）
  --api-url <url>      API base URL（默认: \$SYNAPSE_API_URL or http://localhost:8001）
  --api-key <key>      API Key（或 \$SYNAPSE_API_KEY / OS keychain）
  --watch, -w          每 30s 自动刷新
  --json, -j           JSON 格式输出
  --help, -h           显示此帮助

Examples:
  worker-dashboard.sh
  worker-dashboard.sh --watch
  worker-dashboard.sh --team-id t_xxx --json | jq '.alerts'
EOF
  exit 0
}

# ── 参数解析 ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --team-id)       TEAM_ID="$2"; shift 2 ;;
    --project-id)    PROJECT_ID="$2"; shift 2 ;;
    --api-url)       API_URL="$2"; shift 2 ;;
    --api-key)       API_KEY="$2"; shift 2 ;;
    --watch|-w)      WATCH_MODE=true; shift ;;
    --json|-j)       JSON_MODE=true; shift ;;
    --help|-h)       usage ;;
    *)               echo "Unknown option: $1"; usage ;;
  esac
done

# ── 环境变量加载 ──────────────────────────────────────────────
load_env() {
  # 尝试从当前目录 .env 加载
  if [ -z "${API_KEY:-}" ] || [ -z "${WORKER_ID:-}" ]; then
    for env_file in ".claude/.env" ".env"; do
      if [ -f "$env_file" ]; then
        set -a; . "$env_file"; set +a
        API_KEY="${SYNAPSE_API_KEY:-$API_KEY}"
        WORKER_ID="${SYNAPSE_WORKER_ID:-$WORKER_ID}"
        PROJECT_ID="${SYNAPSE_PROJECT_ID:-$PROJECT_ID}"
        TEAM_ID="${SYNAPSE_TEAM_ID:-$TEAM_ID}"
        break
      fi
    done
  fi

  # OS keychain fallback
  if [ -z "${API_KEY:-}" ] && [ -n "${WORKER_ID:-}" ]; then
    if command -v security &>/dev/null; then
      API_KEY=$(security find-generic-password \
        -a "synapse-worker-${WORKER_ID}" \
        -s "synapse" -w 2>/dev/null || true)
    elif command -v secret-tool &>/dev/null; then
      API_KEY=$(secret-tool lookup \
        account "synapse-worker-${WORKER_ID}" \
        service "synapse" 2>/dev/null || true)
    fi
  fi

  # 验证必需参数
  local errs=()
  [ -z "${API_KEY:-}" ]   && errs+=("API_KEY (--api-key or \$SYNAPSE_API_KEY)")
  [ -z "${API_URL:-}" ]   && errs+=("API_URL (--api-url or \$SYNAPSE_API_URL)")

  if [ ${#errs[@]} -gt 0 ]; then
    echo "❌ Missing required config:" >&2
    for e in "${errs[@]}"; do echo "   - $e" >&2; done
    exit 1
  fi

  # Strip trailing slash
  API_URL="${API_URL%/}"
}

# ── API 调用 ──────────────────────────────────────────────────
api_get() {
  local path="$1"
  local qs="${2:-}"
  local url="${API_URL}${path}"
  [ -n "$qs" ] && url="${url}?${qs}"

  curl -sS --max-time 10 \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Accept: application/json" \
    "$url" 2>/dev/null || echo '{"error":"API unreachable"}'
}

# ── 自动发现 team_id ──────────────────────────────────────────
discover_team_id() {
  if [ -n "${TEAM_ID:-}" ]; then
    echo "$TEAM_ID"
    return
  fi

  # 通过当前 Worker 信息获取 team_id
  if [ -n "${WORKER_ID:-}" ]; then
    local worker_json
    worker_json=$(api_get "/v1/workers/${WORKER_ID}")
    TEAM_ID=$(echo "$worker_json" | jq -r '.team_id // empty' 2>/dev/null)
    if [ -n "${TEAM_ID:-}" ]; then
      echo "$TEAM_ID"
      return
    fi
  fi

  echo "❌ Cannot discover team_id — provide --team-id or set \$SYNAPSE_TEAM_ID" >&2
  exit 1
}

# ── 时间工具 ──────────────────────────────────────────────────
now_epoch() { date +%s; }

relative_time() {
  # 输入: ISO 8601 timestamp or unix epoch
  # 输出: "12s ago" / "3m ago" / "1h ago" / "stale"
  local ts_str="$1"
  if [ -z "$ts_str" ] || [ "$ts_str" = "null" ]; then
    echo "never"
    return
  fi

  local ts_epoch
  # ISO 8601 → epoch (macOS date 不支持 --date, 用 Python fallback)
  if command -v python3 &>/dev/null; then
    ts_epoch=$(python3 -c "
import sys, datetime
ts = '${ts_str}'.replace('Z', '+00:00')
try:
    dt = datetime.datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    print(int(dt.timestamp()))
except: print(0)
" 2>/dev/null) || ts_epoch=0
  else
    # fallback: try date command (GNU)
    ts_epoch=$(date -d "$ts_str" +%s 2>/dev/null) || ts_epoch=0
  fi

  if [ "$ts_epoch" = "0" ]; then
    echo "?"
    return
  fi

  local now diff
  now=$(now_epoch)
  diff=$((now - ts_epoch))

  if [ $diff -lt 60 ]; then
    echo "${diff}s ago"
  elif [ $diff -lt 3600 ]; then
    echo "$((diff / 60))m ago"
  elif [ $diff -lt 86400 ]; then
    echo "$((diff / 3600))h ago"
  else
    echo "$((diff / 86400))d ago"
  fi
}

heartbeat_status() {
  # 返回: healthy | warning | stale | never
  local ts_str="$1"
  if [ -z "$ts_str" ] || [ "$ts_str" = "null" ]; then
    echo "never"
    return
  fi

  local ts_epoch
  if command -v python3 &>/dev/null; then
    ts_epoch=$(python3 -c "
import sys, datetime
ts = '${ts_str}'.replace('Z', '+00:00')
try:
    dt = datetime.datetime.fromisoformat(ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    print(int(dt.timestamp()))
except: print(0)
" 2>/dev/null) || ts_epoch=0
  else
    ts_epoch=$(date -d "$ts_str" +%s 2>/dev/null) || ts_epoch=0
  fi

  if [ "$ts_epoch" = "0" ]; then echo "never"; return; fi

  local now diff
  now=$(now_epoch)
  diff=$((now - ts_epoch))

  if [ $diff -lt $WARN_HEARTBEAT_SEC ]; then
    echo "healthy"
  elif [ $diff -lt $STALE_HEARTBEAT_SEC ]; then
    echo "warning"
  else
    echo "stale"
  fi
}

# ── 状态图标 ──────────────────────────────────────────────────
status_icon() {
  case "$1" in
    healthy) echo "🟢" ;;
    warning) echo "🟡" ;;
    stale)   echo "🔴" ;;
    never)   echo "⚫" ;;
    *)       echo "⚪" ;;
  esac
}

# ── JSON 模式 ──────────────────────────────────────────────────
output_json() {
  local team_id="$1"
  local project_id="$2"

  local workers_json o_status_json alerts_json
  workers_json=$(api_get "/v1/teams/${team_id}/workers" | jq '[.items[] | {
    id, name, status, runtime_status,
    actor_type, provider, provider_model,
    last_heartbeat_at, last_progress_at,
    active_task_id, active_task_count, completed_task_count,
    active_batches
  }]' 2>/dev/null || echo '[]')

  o_status_json="null"
  if [ -n "${project_id:-}" ]; then
    o_status_json=$(api_get "/v1/projects/${project_id}/orchestrator-status" 2>/dev/null || echo 'null')
  fi

  # DG-2: 诊断卡住任务
  alerts_json=$(echo "$workers_json" | jq --argjson stale_sec "$STALE_PROGRESS_SEC" --argjson warn_sec "$STALE_HEARTBEAT_SEC" '
    def heartbeat_age($ts):
      if ($ts == null) then 999999
      else (now - ($ts | fromdateiso8601)) end;
    [
      .[] | select(.active_task_id != null) |
      if heartbeat_age(.last_heartbeat_at) > $warn_sec then
        { level: "stale_heartbeat", worker: .id, worker_name: .name, task: .active_task_id,
          heartbeat: .last_heartbeat_at, msg: "Worker heartbeat stale while task active" }
      else empty end
    ] + [
      .[] | select(.active_task_id != null) |
      if heartbeat_age(.last_progress_at // .last_heartbeat_at) > $stale_sec then
        { level: "stuck_task", worker: .id, worker_name: .name, task: .active_task_id,
          last_progress: .last_progress_at, msg: "Task may be stuck — no progress in >15min" }
      else empty end
    ]
  ' 2>/dev/null || echo '[]')

  jq -n --arg project_id "${project_id:-unknown}" \
    --arg updated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --argjson workers "$workers_json" \
    --argjson o_status "$o_status_json" \
    --argjson alerts "$alerts_json" \
    '{
      project_id: $project_id,
      updated_at: $updated_at,
      summary: {
        total_workers: ($workers | length),
        active_workers: ($workers | map(select(.status == "active")) | length),
        total_active_tasks: ($workers | map(.active_task_count) | add // 0),
        alerts: ($alerts | length)
      },
      workers: $workers,
      o_status: $o_status,
      alerts: $alerts
    }'
}

# ── 终端仪表板 ────────────────────────────────────────────────
render_dashboard() {
  local team_id="$1"
  local project_id="$2"

  clear 2>/dev/null || true

  # 拉取 Worker 列表
  local workers_json
  workers_json=$(api_get "/v1/teams/${team_id}/workers" 2>/dev/null || echo '{"items":[]}')

  # O 状态
  local o_healthy="?"
  if [ -n "${project_id:-}" ]; then
    local o_json
    o_json=$(api_get "/v1/projects/${project_id}/orchestrator-status" 2>/dev/null || echo '{}')
    o_healthy=$(echo "$o_json" | jq -r '.healthy // false' 2>/dev/null || echo "false")
  fi

  # ── 头部 ──────────────────────────────────────────────────
  echo ""
  printf "  ${BOLD}${CYAN}🏭 Synapse Worker Dashboard${NC}\n"
  printf "  Project: ${CYAN}%s${NC}  ·  %s\n" "${project_id:-unknown}" "$(date '+%Y-%m-%d %H:%M:%S')"
  echo "  ───────────────────────────────────────────────────────────"

  # ── 汇总行 ──────────────────────────────────────────────
  local total active offline alert_count
  total=$(echo "$workers_json" | jq '.items | length' 2>/dev/null || echo 0)
  active=$(echo "$workers_json" | jq '[.items[] | select(.status == "active")] | length' 2>/dev/null || echo 0)
  offline=$((total - active))

  printf "  Workers: ${GREEN}%d active${NC}" "$active"
  if [ "$offline" -gt 0 ]; then
    printf " · ${RED}%d offline${NC}" "$offline"
  fi
  printf " · %d total\n" "$total"

  # ── Worker 表格 ──────────────────────────────────────────
  echo ""
  printf "  ${BOLD}%-5s %-22s %-6s %-10s %-12s %s${NC}\n" \
    "" "WORKER" "TYPE" "STATUS" "HEARTBEAT" "ACTIVE TASK"
  echo "  ───────────────────────────────────────────────────────────"

  local alerts=()

  while IFS=$'\t' read -r wid wname wstatus wtype wheartbeat wprogress wtask_id wtask_count wcompleted; do
    [ -z "$wid" ] && continue

    local hb_status hb_rel icon
    hb_status=$(heartbeat_status "$wheartbeat")
    hb_rel=$(relative_time "$wheartbeat")
    icon=$(status_icon "$hb_status")

    # 类型缩写
    local type_label
    case "${wtype:-agent}" in
      agent) type_label="🤖" ;;
      human) type_label="👤" ;;
      *)     type_label="❓" ;;
    esac

    printf "  ${icon} %-20s %-4s %-10s %-12s" \
      "${wname:0:20}" "${type_label}" "${wstatus:0:10}" "$hb_rel"

    # 活跃任务
    if [ -n "$wtask_id" ] && [ "$wtask_id" != "null" ]; then
      printf "${YELLOW}%s${NC}" "${wtask_id:0:22}"
      if [ "$wtask_count" -gt 1 ] 2>/dev/null; then
        printf " +%d" "$((wtask_count - 1))"
      fi

      # DG-2: 卡住诊断
      if [ "$hb_status" = "stale" ]; then
        alerts+=("🔴 ${wname}: heartbeat stale (${hb_rel}) with active task ${wtask_id:0:16}... — worker may be dead")
      fi
      pg_rel=$(relative_time "$wprogress")
      if [ "$pg_rel" != "never" ] && [ "$pg_rel" != "?" ]; then
        local pg_epoch
        pg_epoch=$(echo "$pg_rel" | sed 's/[^0-9]//g')
        if [ "${pg_rel: -1}" = "m" ] && [ "${pg_rel:0:1}" != "s" ]; then
          local pg_num
          pg_num=$(echo "$pg_rel" | grep -o '[0-9]*')
          if [ "${pg_num:-0}" -gt 15 ] 2>/dev/null; then
            alerts+=("🟡 ${wname}: task ${wtask_id:0:16}... no progress for ${pg_rel} — may be stuck (DG-2)")
          fi
        elif [ "${pg_rel: -1}" = "h" ] || [ "${pg_rel: -1}" = "d" ]; then
          alerts+=("🟡 ${wname}: task ${wtask_id:0:16}... no progress for ${pg_rel} — may be stuck (DG-2)")
        fi
      fi
    else
      printf "—"
    fi
    printf "\n"

  done < <(echo "$workers_json" | jq -r '.items[] | [
    .id, .name, .status, (.actor_type // "agent"),
    (.provider // "?"), (.last_heartbeat_at // ""),
    (.last_progress_at // ""), (.active_task_id // ""),
    (.active_task_count // 0), (.completed_task_count // 0)
  ] | @tsv' 2>/dev/null)

  # ── 告警 ──────────────────────────────────────────────────
  if [ ${#alerts[@]} -gt 0 ]; then
    echo ""
    echo "  ───────────────────────────────────────────────────────────"
    printf "  ${BOLD}${RED}⚠️  Alerts (DG-2):${NC}\n"
    for a in "${alerts[@]}"; do
      printf "    %s\n" "$a"
    done
  fi

  # ── 底部 ──────────────────────────────────────────────────
  echo ""
  echo "  ───────────────────────────────────────────────────────────"
  printf "  Refresh: ${CYAN}worker-dashboard.sh --watch${NC}"
  printf "  ·  JSON: ${CYAN}worker-dashboard.sh --json${NC}"
  printf "  ·  DG-3: ${YELLOW}worker-dashboard.sh --unblock-stale${NC}\n"
  echo ""
}

# ── 主流程 ────────────────────────────────────────────────────
main() {
  load_env

  local team_id project_id
  team_id=$(discover_team_id)
  project_id="${PROJECT_ID:-}"

  if $JSON_MODE; then
    output_json "$team_id" "$project_id"
    return
  fi

  if $WATCH_MODE; then
    echo "🔄 Watching — refresh every 30s (Ctrl+C to stop)"
    while true; do
      render_dashboard "$team_id" "$project_id"
      sleep 30
    done
  else
    render_dashboard "$team_id" "$project_id"
  fi
}

main "$@"
