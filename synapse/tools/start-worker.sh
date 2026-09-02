#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# start-worker.sh — Synapse headless worker driver（P16-B3）
# ──────────────────────────────────────────────────────────────────
# 角色无关执行环：heartbeat 轮询 state-router 的 next_action → 按
# 角色分派一个动作单元给 `claude -p`（headless）→ 无活时 idle backoff。
#
# O 和 B 共用本脚本，只是轮询到的 next_action 语义不同（见
# src/services/state_router.py）：O = verify/split/assign/monitor/idle；
# B = execute/claim/idle。worker 的身份/角色/SKILL/key 由 bootstrap-worker.sh
# 生成的目录（.claude/.env + .claude/skills/synapse）承载，本脚本只驱动循环。
#
# 为什么不用交互式 Claude Code + CronCreate 自唤醒（P16 scope）：
#   P15 证伪了 CronCreate（session-only 调度在 worker 会话不可靠），且交互式
#   会话没有自动 user turn。本脚本的 while 循环是代码级确定性循环，idle backoff
#   由 bash 控制，不依赖 LLM 的 ScheduleWakeup。
#
# Usage:
#   # 默认当前目录为 worker 目录，无限循环：
#   bash tools/start-worker.sh
#
#   # 指定 worker 目录（worktree 隔离 · DG-1）：
#   bash tools/start-worker.sh --project-dir /path/to/.claude/worktrees/p16-b4-o
#
#   # 只跑一轮就退出（调试 / 手动 kick）：
#   bash tools/start-worker.sh --once
#
#   # 试运行（打印将执行的命令，不真跑 claude -p）：
#   bash tools/start-worker.sh --dry-run
#
# 依赖环境变量（由 .claude/.env 提供 · bootstrap-worker.sh 生成）：
#   SYNAPSE_API_URL      — e.g. http://127.0.0.1:8001
#   SYNAPSE_WORKER_ID    — e.g. wa_xxx
#   SYNAPSE_PROJECT_ID   — 默认项目（heartbeat 请求体带此值做 project 解析）
#   SYNAPSE_API_KEY      — Bearer token（优先 OS 密钥链 fallback）
#   SYNAPSE_WORKER_ROLE  — 可选（builder/orchestrator · server 端 project role 优先）
#
# 可选调参（环境变量覆盖）：
#   SYNAPSE_IDLE_SLEEP_MIN   idle 初始退避秒数（默认 20）
#   SYNAPSE_IDLE_SLEEP_MAX   idle 退避上限秒数（默认 300）
#   SYNAPSE_CLAUDE_TIMEOUT   claude -p 单次超时兜底秒数（默认 900 · 15min）
#                            P16-B5 (PFL-249)：旧默认 360 来自 B1 spike「O 单次
#                            判断 3min21s」，但一个 next_action 是完整 agentic
#                            loop 而非单次判断——B4 实测 O 拆解 14min40s，360s
#                            把它杀死、0 子任务，且超时后立即重派形成紧循环。
#                            P16-B8 (PFL-261)：超时不再单值一刀切，按 next_action
#                            分档——split 1800s（B4 实测 880s）、execute 2400s（写+
#                            全量测试+mypy，B1 两次 900s 被刀切）、轻动作 900s。
#                            见下方 SYNAPSE_TIMEOUT_SPLIT / _EXECUTE / _LIGHT。
#   SYNAPSE_FAIL_SLEEP_MAX   分派失败/超时后的退避上限秒数（默认 300）
#   SYNAPSE_ALLOWED_TOOLS    claude -p 工具面白名单（默认 Bash,Read,Write,Edit,Grep,Glob）
# ──────────────────────────────────────────────────────────────────

# 不设 -e：driver 循环必须容忍 claude -p 失败 / curl 失败，而非整体退出。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 默认值（可被环境变量覆盖）──────────────────────────────
IDLE_SLEEP_MIN="${SYNAPSE_IDLE_SLEEP_MIN:-20}"
IDLE_SLEEP_MAX="${SYNAPSE_IDLE_SLEEP_MAX:-300}"
CLAUDE_TIMEOUT="${SYNAPSE_CLAUDE_TIMEOUT:-900}"   # 兜底（轻动作默认）
# P16-B8 (PFL-261)：超时按 next_action 分档，不再单值一刀切
ACTION_TIMEOUT_SPLIT="${SYNAPSE_TIMEOUT_SPLIT:-1800}"
ACTION_TIMEOUT_EXECUTE="${SYNAPSE_TIMEOUT_EXECUTE:-2400}"
ACTION_TIMEOUT_LIGHT="${SYNAPSE_TIMEOUT_LIGHT:-900}"
FAIL_SLEEP_MIN=30
FAIL_SLEEP_MAX="${SYNAPSE_FAIL_SLEEP_MAX:-300}"
HEARTBEAT_TIMEOUT=10
KEEPALIVE_INTERVAL="${SYNAPSE_KEEPALIVE_INTERVAL:-30}"   # 后台保活心跳间隔（< worker_heartbeat_timeout 300s）
ALLOWED_TOOLS="${SYNAPSE_ALLOWED_TOOLS:-Bash,Read,Write,Edit,Grep,Glob}"

# ── Color helpers（对齐 bootstrap-worker.sh 风格）────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── 参数解析 ────────────────────────────────────────────────
WORKER_DIR="."
ONCE=false
DRY_RUN=false
ROLE_OVERRIDE=""

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Synapse headless worker driver（P16-B3）— 角色无关执行环。

OPTIONS:
  --project-dir <path>   Worker 目录（默认当前目录 · DG-1 建议 worktree）
  --role <builder|orchestrator|steward>  覆盖 .env 的 SYNAPSE_WORKER_ROLE
  --once                只跑一轮循环后退出（调试 / 手动 kick）
  --dry-run             只打印将执行的命令，不真跑 claude -p
  -h, --help            显示帮助

EXAMPLES:
  $0 --project-dir .claude/worktrees/p16-b4-o
  $0 --once --dry-run
  SYNAPSE_CLAUDE_TIMEOUT=1800 $0        # 兜底上限（分档默认已覆盖 split/execute）
  SYNAPSE_TIMEOUT_EXECUTE=3600 $0       # 单独给 execute 更长上限
EOF
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)  WORKER_DIR="$2"; shift 2 ;;
        --role)         ROLE_OVERRIDE="$2"; shift 2 ;;
        --once)         ONCE=true; shift ;;
        --dry-run)      DRY_RUN=true; shift ;;
        -h|--help)      usage ;;
        *) echo -e "${RED}❌ 未知参数: $1${NC}"; usage ;;
    esac
done

# ── 进入 worker 目录（worktree 隔离 · DG-1）──────────────────
if [[ ! -d "$WORKER_DIR" ]]; then
    echo -e "${RED}❌ Worker 目录不存在: $WORKER_DIR${NC}"
    echo -e "${YELLOW}提示: 先用 bootstrap-worker.sh 初始化 worker 目录${NC}"
    exit 1
fi
cd "$WORKER_DIR" || { echo -e "${RED}❌ 无法进入 $WORKER_DIR${NC}"; exit 1; }

# ── 环境变量加载（复用 synapse-heartbeat.sh 模式）────────────
# 未设置时从 .claude/.env 加载（bootstrap-worker.sh BOOT-3 生成）
if [[ -z "${SYNAPSE_WORKER_ID:-}" ]]; then
    if [[ -f ".claude/.env" ]]; then
        set -a; . ".claude/.env"; set +a
    elif [[ -f ".env" ]]; then
        set -a; . ".env"; set +a
    fi
fi

# API key fallback：优先 OS 密钥链（P11-B35 key 隔离）
if [[ -z "${SYNAPSE_API_KEY:-}" && -n "${SYNAPSE_WORKER_ID:-}" ]]; then
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

# role 覆盖（--role 参数优先于 .env）
if [[ -n "$ROLE_OVERRIDE" ]]; then
    SYNAPSE_WORKER_ROLE="$ROLE_OVERRIDE"
fi

# ── 门禁检查 ────────────────────────────────────────────────
if [[ -z "${SYNAPSE_WORKER_ID:-}" ]]; then
    echo -e "${RED}❌ 缺少 SYNAPSE_WORKER_ID${NC}"
    echo -e "${YELLOW}提示: 在 .claude/.env 或环境中设置${NC}"
    exit 1
fi
if [[ -z "${SYNAPSE_API_KEY:-}" ]]; then
    echo -e "${RED}❌ 缺少 SYNAPSE_API_KEY${NC}"
    echo -e "${YELLOW}提示: 运行 synapse-key.sh store <worker_id> <key> 存入密钥链，或在 .claude/.env 设置${NC}"
    exit 1
fi

API_URL="${SYNAPSE_API_URL:-http://127.0.0.1:8001}"

# ── claude CLI 检查 ─────────────────────────────────────────
if ! command -v claude &>/dev/null; then
    echo -e "${RED}❌ claude CLI 未安装或不在 PATH 中${NC}"
    exit 1
fi

# ── PUA/settings 继承检查（B1 spike 连带发现）────────────────
# B1 发现嵌套 claude -p 会继承父环境 settings.json/hook，导致 flavor 泄漏进
# worker 输出。B3 只能从 worker 目录启动 + 提示，worktree 隔离的完整验证在 B4。
if [[ -f ".claude/settings.json" ]]; then
    echo -e "${GREEN}✅${NC} worker 自有 .claude/settings.json（隔离基线存在）"
else
    echo -e "${YELLOW}⚠️${NC}  worker 目录无 .claude/settings.json — 可能继承父环境 hook/flavor"
    echo -e "  ${CYAN}💡${NC} B4 狗粮需验证 worktree 隔离（bootstrap-worker.sh 应已生成）"
fi

# ════════════════════════════════════════════════════════════
# heartbeat — 调用 state-router，返回原始 JSON（供 parse 函数解析）
# ════════════════════════════════════════════════════════════
heartbeat() {
    curl -s -m "$HEARTBEAT_TIMEOUT" -X POST \
        "${API_URL%/}/v1/workers/${SYNAPSE_WORKER_ID}/heartbeat" \
        -H "Authorization: Bearer ${SYNAPSE_API_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"current_load\":0,\"project_id\":\"${SYNAPSE_PROJECT_ID:-}\"}" 2>/dev/null
}

# ════════════════════════════════════════════════════════════
# keepalive 心跳 — 与主循环解耦（P16-B7 PFL-262）
# ════════════════════════════════════════════════════════════
# 主循环在 run_with_timeout 同步 wait `claude -p` 期间不再发心跳，模型调用
# 卡死 / 大 split 超过 300s 时 Worker.last_heartbeat_at 陈旧 → 被
# _worker_heartbeat_monitor 判 OFFLINE、被 stale 回收误判僵尸。本函数在独立
# 子进程里持续发心跳，与同步执行解耦。body 不带 active_task_id → 三态语义
# 「缺省=保持」，不会擦掉 claim/assign 挂上的活跃任务。
keepalive_loop() {
    while true; do
        heartbeat >/dev/null 2>&1
        sleep "$KEEPALIVE_INTERVAL"
    done
}

start_keepalive() {
    keepalive_loop &
    KEEPALIVE_PID=$!
}

stop_keepalive() {
    if [[ -n "${KEEPALIVE_PID:-}" ]] && kill -0 "$KEEPALIVE_PID" 2>/dev/null; then
        kill "$KEEPALIVE_PID" 2>/dev/null
        wait "$KEEPALIVE_PID" 2>/dev/null
    fi
}

# ── 用 python3 解析 heartbeat JSON（对齐 synapse-heartbeat.sh）──
parse_field() {
    # $1 = JSON 文本 · $2 = 字段名（支持 dotted path）
    local json="$1" field="$2"
    python3 -c "
import sys, json
try:
    data = json.loads(sys.argv[1])
    for key in sys.argv[2].split('.'):
        data = data.get(key) if isinstance(data, dict) else None
    if isinstance(data, (dict, list)):
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(data if data is not None else '')
except Exception:
    print('')
" "$json" "$field" 2>/dev/null
}

# ════════════════════════════════════════════════════════════
# 构造分派 prompt — 定向 + 有界（一个动作单元）+ 明确退出
# ════════════════════════════════════════════════════════════
build_prompt() {
    local next_action="$1" role="$2" active_task_id="$3" queue="$4"
    cat <<PROMPT
你是 Synapse 平台的 ${role} worker（worker_id=${SYNAPSE_WORKER_ID}）。

state-router 本轮判定：
  role=${role}
  next_action=${next_action}
  active_task_id=${active_task_id:-<无>}
  queue=${queue}

先读 SKILL.md 与 _task-current.md 了解你的职责与当前状态，然后**只执行
next_action 对应的一个动作单元**（不要空转、不要等待、不要循环）：

  - verify：验收一个 in_verification 任务（POST /verifications/{id}/verify）
  - split ：把一个 backlog 任务拆解为子任务 + 定义可被 verification_conditions
             机械判定的验收条件（三问 checklist，含糊则发 clarification）
  - assign：把一个 ready 任务分配给匹配 worker（POST /tasks/{id}/assign）
  - monitor：检查 in_progress 任务的评论区/停滞状态
  - execute：继续执行 active_task_id 任务（或 claim 一个 ready 任务后执行）
  - claim ：认领一个 ready 任务（POST /tasks/{id}/claim）

完成后用一句话报告你做了什么，然后退出。driver 会立即再次轮询 heartbeat
拿到新的 next_action，所以不需要你在这里自循环或等待。
PROMPT
}

# ════════════════════════════════════════════════════════════
# 限时执行 — macOS 无 GNU timeout，用后台 + wait + kill 兜底
# ════════════════════════════════════════════════════════════
run_with_timeout() {
    local timeout_secs="$1"; shift
    local pid elapsed=0
    "$@" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        if [[ $elapsed -ge $timeout_secs ]]; then
            echo -e "${YELLOW}⏱️  claude -p 超时（${timeout_secs}s）— 终止并进入下一轮${NC}"
            kill -TERM "$pid" 2>/dev/null
            sleep 2
            kill -KILL "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            return 124
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    wait "$pid"
    return $?
}

# ════════════════════════════════════════════════════════════
# 启动 keepalive 心跳（P16-B7 PFL-262 · dry-run 不发）
# ════════════════════════════════════════════════════════════
KEEPALIVE_PID=""
if ! $DRY_RUN; then
    trap stop_keepalive EXIT
    start_keepalive
    echo -e "${CYAN}🫀 keepalive 心跳已启动（每 ${KEEPALIVE_INTERVAL}s）${NC}"
fi

# ════════════════════════════════════════════════════════════
# 主循环
# ════════════════════════════════════════════════════════════
echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}│  Synapse Headless Worker Driver · P16-B3      │${NC}"
echo -e "${BOLD}│  ${CYAN}role=${SYNAPSE_WORKER_ROLE:-<auto>}  worker=${SYNAPSE_WORKER_ID}${BOLD}  │${NC}"
echo -e "${BOLD}│  ${CYAN}api=${API_URL}${BOLD}  │${NC}"
echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
echo ""

idle_sleep="$IDLE_SLEEP_MIN"
fail_sleep="$FAIL_SLEEP_MIN"   # P16-B5 PFL-249: 连续失败/超时的退避
consecutive_fails=0

while true; do
    # ── 1. heartbeat → state-router ──
    RESP=$(heartbeat) || RESP=""
    if [[ -z "$RESP" ]]; then
        echo -e "$(date -u +%H:%M:%S) ${YELLOW}🫀 heartbeat: API unreachable — ${API_URL} · ${idle_sleep}s 后重试${NC}"
        sleep "$idle_sleep"
        continue
    fi

    NEXT_ACTION=$(parse_field "$RESP" "next_action")
    ROLE=$(parse_field "$RESP" "role")
    ACTIVE_TASK_ID=$(parse_field "$RESP" "active_task_id")
    QUEUE=$(parse_field "$RESP" "queue")

    # role_warnings（诊断：无 Project 归属 / 多项目）→ 打印不中断
    WARNINGS=$(parse_field "$RESP" "role_warnings")
    if [[ -n "$WARNINGS" && "$WARNINGS" != "[]" ]]; then
        echo -e "$(date -u +%H:%M:%S) ${YELLOW}⚠️  role_warnings: $WARNINGS${NC}"
    fi

    case "$NEXT_ACTION" in
        # ── 无活：指数退避 ──
        idle|"")
            echo -e "$(date -u +%H:%M:%S) ${CYAN}😴 idle（queue=${QUEUE}）· backoff ${idle_sleep}s${NC}"
            sleep "$idle_sleep"
            idle_sleep=$((idle_sleep * 2))
            [[ $idle_sleep -gt $IDLE_SLEEP_MAX ]] && idle_sleep=$IDLE_SLEEP_MAX
            ;;

        # ── 有活：分派 claude -p 一个动作单元 ──
        verify|split|assign|monitor|execute|claim)
            idle_sleep="$IDLE_SLEEP_MIN"  # 有活即复位退避
            # P16-B8 (PFL-261)：超时按动作分档——split/execute 重，轻动作短
            case "$NEXT_ACTION" in
                split)   ACTION_TIMEOUT="$ACTION_TIMEOUT_SPLIT" ;;
                execute) ACTION_TIMEOUT="$ACTION_TIMEOUT_EXECUTE" ;;
                *)       ACTION_TIMEOUT="$ACTION_TIMEOUT_LIGHT" ;;
            esac
            PROMPT=$(build_prompt "$NEXT_ACTION" "${ROLE:-${SYNAPSE_WORKER_ROLE:-builder}}" "$ACTIVE_TASK_ID" "$QUEUE")
            echo -e "$(date -u +%H:%M:%S) ${GREEN}🎯 next_action=${NEXT_ACTION} · dispatch claude -p（timeout=${ACTION_TIMEOUT}s）${NC}"

            if $DRY_RUN; then
                echo -e "${YELLOW}── [dry-run] 将执行 ──${NC}"
                echo "  claude -p <prompt> --allowedTools \"$ALLOWED_TOOLS\" --permission-mode bypassPermissions"
                echo -e "${YELLOW}── [dry-run] prompt 预览 ──${NC}"
                echo "$PROMPT" | sed 's/^/  | /'
                echo ""
            else
                printf '%s\n' "$PROMPT" | run_with_timeout "$ACTION_TIMEOUT" \
                    claude -p \
                    --allowedTools "$ALLOWED_TOOLS" \
                    --permission-mode bypassPermissions 2>&1
                dispatch_rc=$?

                if [[ $dispatch_rc -eq 0 ]]; then
                    consecutive_fails=0
                    fail_sleep="$FAIL_SLEEP_MIN"
                else
                    # P16-B5 (PFL-249): 失败/超时路径必须退避。此前 idle_sleep
                    # 一见「有活」就复位，超时后立即重派 → 紧循环烧 token
                    # （B4 实测：360s 超时被杀 → 立刻再派 → 反复）。
                    consecutive_fails=$((consecutive_fails + 1))
                    if [[ $dispatch_rc -eq 124 ]]; then
                        reason="超时 ${ACTION_TIMEOUT}s"
                    else
                        reason="异常退出 code=${dispatch_rc}"
                    fi
                    echo -e "$(date -u +%H:%M:%S) ${YELLOW}⚠️  claude -p ${reason} — 连续第 ${consecutive_fails} 次 · ${fail_sleep}s 后重试${NC}"
                    sleep "$fail_sleep"
                    fail_sleep=$((fail_sleep * 2))
                    [[ $fail_sleep -gt $FAIL_SLEEP_MAX ]] && fail_sleep=$FAIL_SLEEP_MAX
                fi
            fi
            ;;

        *)
            echo -e "$(date -u +%H:%M:%S) ${YELLOW}❓ 未知 next_action=${NEXT_ACTION} · ${idle_sleep}s 后重试${NC}"
            sleep "$idle_sleep"
            ;;
    esac

    # ── --once：单轮后退出 ──
    if $ONCE; then
        echo -e "${CYAN}── --once 模式：单轮结束，退出 ──${NC}"
        break
    fi
done
