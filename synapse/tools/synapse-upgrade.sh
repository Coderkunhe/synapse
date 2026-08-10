#!/usr/bin/env bash
# synapse-upgrade.sh — Synapse Worker 一键升级/回滚（P14-B1 · C6）
#
# 消灭狗粮前手工 git pull + restart — 一条命令完成 Worker 升级/回滚。
# 复用 synapse-health-check.sh（P13-B1）做 post-verify，
# 复用 synapse-launchd.sh（P12-B3）做 daemon 管理。
#
# Usage:
#   bash tools/synapse-upgrade.sh upgrade  <project-dir> <worker_id>
#       git pull → pre-check → health-verify → launchd reload → done
#
#   bash tools/synapse-upgrade.sh rollback <project-dir> <worker_id> [commit]
#       git checkout <prev> → health-verify → launchd reload → done
#
#   bash tools/synapse-upgrade.sh status   <project-dir> <worker_id>
#       commit + branch + last upgrade time + health summary
#
# Options:
#   --force            跳过 pre-upgrade health check（升级前不验证当前状态）
#   --no-restart       跳过 launchd restart（仅 git 操作 + health check）
#   --ref <commit>     upgrade 到指定 commit（默认 git pull 即 origin/main）
#   --dry-run          仅打印将执行的操作，不实际执行
#
# Environment:
#   脚本内部读取 Worker 的 .claude/.env 获取 SYNAPSE_* 变量传给 health-check。
#
# Exit codes:
#   0 — 成功
#   1 — 升级/回滚失败
#   2 — pre-check 失败（当前状态不健康，拒绝升级）
#   3 — 参数错误

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Color helpers ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── State ──
UPGRADE_STATE_FILE=".claude/synapse-upgrade-state.json"
FORCE=false
NO_RESTART=false
DRY_RUN=false
TARGET_REF=""

usage() {
    cat << 'EOF'
Usage: synapse-upgrade.sh <command> [OPTIONS] <project-dir> <worker_id>

Synapse Worker 一键升级/回滚 — P14-B1 (C6)

COMMANDS:
  upgrade    git pull → health-verify → launchd reload
  rollback   git checkout <prev> → health-verify → launchd reload
  status     当前 commit + 分支 + 最近升级时间 + 健康摘要

OPTIONS:
  --force          跳过 pre-upgrade health check
  --no-restart     跳过 daemon restart（仅 git + health verify）
  --ref <commit>   upgrade 到指定 commit（默认 origin/main）
  --dry-run        仅打印操作，不执行

EXAMPLES:
  # 升级到最新:
  bash tools/synapse-upgrade.sh upgrade ~/my-builder wa_abc123

  # 回滚到上一次升级前的 commit:
  bash tools/synapse-upgrade.sh rollback ~/my-builder wa_abc123

  # 回滚到指定 commit:
  bash tools/synapse-upgrade.sh rollback ~/my-builder wa_abc123 abc123def

  # 查看当前状态:
  bash tools/synapse-upgrade.sh status ~/my-builder wa_abc123
EOF
    exit 3
}

# ── Parse args ──
COMMAND=""
PROJECT_DIR=""
WORKER_ID=""

POS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)       FORCE=true; shift ;;
        --no-restart)  NO_RESTART=true; shift ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --ref)
            shift
            TARGET_REF="${1:-}"
            if [[ -z "$TARGET_REF" ]]; then
                echo -e "${RED}❌ --ref 需要参数${NC}"
                exit 3
            fi
            shift
            ;;
        -h|--help)     usage ;;
        *)
            POS+=("$1")
            shift
            ;;
    esac
done

COMMAND="${POS[0]:-}"
PROJECT_DIR="${POS[1]:-}"
WORKER_ID="${POS[2]:-}"

[[ -z "$COMMAND" ]] && { echo -e "${RED}❌ 缺少命令 (upgrade|rollback|status)${NC}"; usage; }
[[ "$COMMAND" =~ ^(upgrade|rollback|status)$ ]] || { echo -e "${RED}❌ 未知命令: $COMMAND${NC}"; usage; }
[[ -z "$PROJECT_DIR" ]] && { echo -e "${RED}❌ 缺少 project-dir${NC}"; usage; }
[[ -z "$WORKER_ID" ]] && { echo -e "${RED}❌ 缺少 worker_id${NC}"; usage; }

# ── Resolve project dir ──
if [[ ! -d "$PROJECT_DIR" ]]; then
    echo -e "${RED}❌ 项目目录不存在: $PROJECT_DIR${NC}"
    exit 3
fi
PROJECT_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd)"

# ── Validation helpers ──
validate_worker_project() {
    local dir="$1"

    # Check for .claude/ directory (Claude Code Worker)
    if [[ ! -d "$dir/.claude" ]]; then
        echo -e "${RED}❌ 不是 Synapse Worker 项目 — 缺少 .claude/ 目录${NC}"
        echo -e "  ${CYAN}💡${NC} 先用 bootstrap-worker.sh 创建 Worker 环境"
        exit 3
    fi

    # Check for git repo
    if ! git -C "$dir" rev-parse --git-dir &>/dev/null; then
        echo -e "${RED}❌ 不是 git 仓库 — 无法升级/回滚${NC}"
        exit 3
    fi
}

validate_worker_id() {
    local wid="$1"
    if [[ ! "$wid" =~ ^w ]]; then
        echo -e "${YELLOW}⚠️  Worker ID '${wid}' 格式异常（预期 w* 前缀）${NC}"
        echo "   继续执行 — 如果 health-check 失败，检查 SYNAPSE_WORKER_ID"
    fi
}

# ── Health check wrapper ──
run_health_check() {
    local label="$1"
    local env_file="$PROJECT_DIR/.claude/.env"

    echo ""
    echo -e "${BOLD}── ${label} → synapse-health-check.sh ──${NC}"

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将运行: synapse-health-check.sh"
        return 0
    fi

    if [[ ! -f "$env_file" ]]; then
        echo -e "  ${YELLOW}⚠️${NC}  缺少 .claude/.env — 跳过 health check"
        echo -e "  ${CYAN}💡${NC} health-check 需要 SYNAPSE_API_URL 等环境变量"
        return 1
    fi

    # Source .env in a subshell and run health-check
    (
        set -a
        # shellcheck disable=SC1090
        source "$env_file" 2>/dev/null || true
        set +a
        bash "$PROJECT_ROOT/tools/synapse-health-check.sh" -v
    )
    local rc=$?

    if [[ $rc -eq 0 ]]; then
        echo -e "  ${GREEN}✅${NC} ${label} — 健康检查通过"
        return 0
    elif [[ $rc -eq 3 ]]; then
        echo -e "  ${YELLOW}⚠️${NC}  ${label} — 健康检查通过（有警告）"
        return 0
    else
        echo -e "  ${RED}❌${NC} ${label} — 健康检查失败 (exit=$rc)"
        return 1
    fi
}

# ── Launchd restart ──
restart_daemon() {
    local label="$1"

    if $NO_RESTART; then
        echo -e "  ${YELLOW}⏭️${NC}  --no-restart · 跳过 daemon 重启"
        return 0
    fi

    echo ""
    echo -e "${BOLD}── ${label} → synapse-launchd.sh ──${NC}"

    local launchd_script="$PROJECT_ROOT/tools/synapse-launchd.sh"
    if [[ ! -f "$launchd_script" ]]; then
        echo -e "  ${YELLOW}⚠️${NC}  找不到 synapse-launchd.sh — 跳过 daemon 管理"
        echo -e "  ${CYAN}💡${NC} 手动重启 daemon: launchctl unload/load 或重新启动终端"
        return 0
    fi

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将运行: synapse-launchd.sh uninstall $WORKER_ID && install $PROJECT_DIR $WORKER_ID"
        return 0
    fi

    # Uninstall old, then install fresh
    echo -e "  ▎ 卸载现有 launchd job..."
    bash "$launchd_script" uninstall "$WORKER_ID" 2>/dev/null || true

    echo -e "  ▎ 安装新 launchd job..."
    if bash "$launchd_script" install "$PROJECT_DIR" "$WORKER_ID"; then
        echo -e "  ${GREEN}✅${NC} launchd 重启完成"
        return 0
    else
        echo -e "  ${RED}❌${NC} launchd 重启失败"
        return 1
    fi
}

# ── State file management ──
read_state() {
    local state_path="$PROJECT_DIR/$UPGRADE_STATE_FILE"
    if [[ -f "$state_path" ]]; then
        cat "$state_path"
    else
        echo "{}"
    fi
}

write_state() {
    local prev_commit="$1"
    local state_path="$PROJECT_DIR/$UPGRADE_STATE_FILE"

    local now
    now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    cat > "$state_path" << JSONEOF
{
  "previous_commit": "${prev_commit}",
  "last_upgrade_at": "${now}",
  "last_upgrade_by": "synapse-upgrade.sh (P14-B1)",
  "worker_id": "${WORKER_ID}"
}
JSONEOF
}

# ═══════════════════════════════════════════════════════════════════════
# upgrade
# ═══════════════════════════════════════════════════════════════════════

cmd_upgrade() {
    echo ""
    echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
    echo -e "${BOLD}│  Synapse Worker 升级 · P14-B1 (C6)            │${NC}"
    echo -e "${BOLD}│  ${PROJECT_DIR}${NC}"
    echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
    echo ""

    validate_worker_project "$PROJECT_DIR"
    validate_worker_id "$WORKER_ID"

    local current_commit
    current_commit=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    local current_branch
    current_branch=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD)

    echo -e "  当前 commit:  ${CYAN}${current_commit:0:12}${NC} (${current_branch})"

    # ── Pre-upgrade health check ──
    if $FORCE; then
        echo -e "  ${YELLOW}⚠️${NC}  --force · 跳过 pre-upgrade health check"
    else
        if ! run_health_check "Pre-upgrade 检查"; then
            echo ""
            echo -e "${RED}${BOLD}❌ 升级中止 — 当前 Worker 状态不健康${NC}"
            echo -e "  ${CYAN}💡${NC} 先排查问题，或使用 --force 跳过检查强制升级"
            exit 2
        fi
    fi

    # ── Git fetch/pull ──
    echo ""
    echo -e "${BOLD}── git fetch + checkout ──${NC}"

    if $DRY_RUN; then
        if [[ -n "$TARGET_REF" ]]; then
            echo -e "  ${YELLOW}[dry-run]${NC} 将运行: git fetch && git checkout ${TARGET_REF}"
        else
            echo -e "  ${YELLOW}[dry-run]${NC} 将运行: git fetch origin && git checkout origin/${current_branch}"
        fi
    else
        git -C "$PROJECT_DIR" fetch origin

        if [[ -n "$TARGET_REF" ]]; then
            echo -e "  ▎ 切换到指定 ref: ${TARGET_REF}"
            git -C "$PROJECT_DIR" checkout "$TARGET_REF"
        else
            local remote_ref="origin/${current_branch}"
            echo -e "  ▎ 切换到: ${remote_ref}"
            git -C "$PROJECT_DIR" checkout "$remote_ref" 2>/dev/null || {
                echo -e "  ${YELLOW}⚠️${NC}  无法 checkout ${remote_ref} — 尝试 git pull"
                git -C "$PROJECT_DIR" pull origin "$current_branch"
            }
        fi
    fi

    local new_commit
    new_commit=$(git -C "$PROJECT_DIR" rev-parse HEAD)
    echo -e "  新 commit:    ${GREEN}${new_commit:0:12}${NC}"

    if [[ "$current_commit" == "$new_commit" ]]; then
        echo -e "  ${YELLOW}⚠️${NC}  没有变化 — 已是最新"
    fi

    # ── Post-upgrade health check ──
    if ! run_health_check "Post-upgrade 验证"; then
        echo ""
        echo -e "${RED}${BOLD}❌ 升级后健康检查失败！${NC}"
        echo -e "  ${CYAN}💡${NC} 回滚: bash tools/synapse-upgrade.sh rollback $PROJECT_DIR $WORKER_ID $current_commit"
        # Save state so rollback knows where to go
        write_state "$current_commit"
        exit 1
    fi

    # ── Restart daemon ──
    restart_daemon "重启 daemon"

    # ── Save state ──
    write_state "$current_commit"

    echo ""
    echo -e "${GREEN}${BOLD}✅ 升级完成${NC}"
    echo -e "  ${current_commit:0:12} → ${GREEN}${new_commit:0:12}${NC}"
    echo -e "  ${CYAN}💡${NC} 如需回滚: bash tools/synapse-upgrade.sh rollback $PROJECT_DIR $WORKER_ID"
}

# ═══════════════════════════════════════════════════════════════════════
# rollback
# ═══════════════════════════════════════════════════════════════════════

cmd_rollback() {
    echo ""
    echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
    echo -e "${BOLD}│  Synapse Worker 回滚 · P14-B1 (C6)            │${NC}"
    echo -e "${BOLD}│  ${PROJECT_DIR}${NC}"
    echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
    echo ""

    validate_worker_project "$PROJECT_DIR"
    validate_worker_id "$WORKER_ID"

    local current_commit
    current_commit=$(git -C "$PROJECT_DIR" rev-parse HEAD)

    # Determine rollback target
    local rollback_target="${POS[3]:-}"

    if [[ -z "$rollback_target" ]]; then
        # Read from state file
        local state_json
        state_json=$(read_state)
        rollback_target=$(echo "$state_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('previous_commit',''))" 2>/dev/null || echo "")

        if [[ -z "$rollback_target" ]]; then
            echo -e "${RED}❌ 没有记录的上一次 commit — 无法自动回滚${NC}"
            echo -e "  ${CYAN}💡${NC} 手动指定: bash tools/synapse-upgrade.sh rollback $PROJECT_DIR $WORKER_ID <commit>"
            echo -e "  ${CYAN}💡${NC} 可用 git log 查看历史 commit"
            exit 3
        fi
        echo -e "  回滚目标:    ${CYAN}${rollback_target:0:12}${NC} (从 state file 读取)"
    else
        echo -e "  回滚目标:    ${CYAN}${rollback_target:0:12}${NC} (手动指定)"
    fi

    # Verify rollback target exists
    if ! git -C "$PROJECT_DIR" cat-file -e "$rollback_target" 2>/dev/null; then
        echo -e "${RED}❌ 回滚目标 commit 不存在: $rollback_target${NC}"
        exit 3
    fi

    echo -e "  当前 commit:  ${CYAN}${current_commit:0:12}${NC}"

    # ── Git checkout ──
    echo ""
    echo -e "${BOLD}── git checkout ──${NC}"

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将运行: git checkout ${rollback_target}"
    else
        git -C "$PROJECT_DIR" checkout "$rollback_target"
        echo -e "  ${GREEN}✅${NC} 已切换到: ${rollback_target:0:12}"
    fi

    # ── Post-rollback health check ──
    if ! run_health_check "Post-rollback 验证"; then
        echo ""
        echo -e "${RED}${BOLD}❌ 回滚后健康检查失败！${NC}"
        echo -e "  ${CYAN}💡${NC} 回滚后的状态仍然不健康 — 可能需要人工排查"
        exit 1
    fi

    # ── Restart daemon ──
    restart_daemon "重启 daemon"

    echo ""
    echo -e "${GREEN}${BOLD}✅ 回滚完成${NC}"
    echo -e "  ${current_commit:0:12} → ${CYAN}${rollback_target:0:12}${NC}"
}

# ═══════════════════════════════════════════════════════════════════════
# status
# ═══════════════════════════════════════════════════════════════════════

cmd_status() {
    echo ""
    echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
    echo -e "${BOLD}│  Synapse Worker 状态 · P14-B1 (C6)            │${NC}"
    echo -e "${BOLD}│  ${PROJECT_DIR}${NC}"
    echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
    echo ""

    validate_worker_project "$PROJECT_DIR"
    validate_worker_id "$WORKER_ID"

    # ── Git info ──
    echo -e "${BOLD}── Git ──${NC}"
    local commit branch
    commit=$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")
    branch=$(git -C "$PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    echo -e "  Commit:  ${CYAN}${commit:0:12}${NC}"
    echo -e "  Branch:  ${CYAN}${branch}${NC}"

    # Last commit message
    local last_msg
    last_msg=$(git -C "$PROJECT_DIR" log -1 --format=%s 2>/dev/null || echo "unknown")
    echo -e "  最近:    ${last_msg}"

    # Dirty check
    if git -C "$PROJECT_DIR" diff --quiet 2>/dev/null; then
        echo -e "  Status:  ${GREEN}clean${NC}"
    else
        local dirty_count
        dirty_count=$(git -C "$PROJECT_DIR" diff --stat 2>/dev/null | tail -1 | awk '{print $1}' || echo "?")
        echo -e "  Status:  ${YELLOW}dirty (${dirty_count:-?} files)${NC}"
    fi

    echo ""

    # ── Upgrade state ──
    echo -e "${BOLD}── 升级记录 ──${NC}"
    local state_json
    state_json=$(read_state)
    local prev_commit last_upgrade
    prev_commit=$(echo "$state_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('previous_commit','-'))" 2>/dev/null || echo "-")
    last_upgrade=$(echo "$state_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('last_upgrade_at','-'))" 2>/dev/null || echo "-")

    if [[ "$prev_commit" == "-" ]]; then
        echo -e "  状态:    ${YELLOW}无升级记录${NC}"
        echo -e "  ${CYAN}💡${NC} 运行 upgrade 后会自动记录"
    else
        echo -e "  上次升级: ${CYAN}${last_upgrade}${NC}"
        echo -e "  回滚目标: ${CYAN}${prev_commit:0:12}${NC}"
        if git -C "$PROJECT_DIR" cat-file -e "$prev_commit" 2>/dev/null; then
            echo -e "  可用性:  ${GREEN}commit 可访问${NC}"
        else
            echo -e "  可用性:  ${RED}commit 不可访问（已被 gc 或 force-push）${NC}"
        fi
    fi

    echo ""

    # ── Health check (quick mode) ──
    echo -e "${BOLD}── 健康检查 ──${NC}"
    local env_file="$PROJECT_DIR/.claude/.env"
    if [[ -f "$env_file" ]]; then
        (
            set -a
            # shellcheck disable=SC1090
            source "$env_file" 2>/dev/null || true
            set +a
            bash "$PROJECT_ROOT/tools/synapse-health-check.sh" -q 2>/dev/null
        )
        local hc_rc=$?
        case $hc_rc in
            0) echo -e "  结果:    ${GREEN}✅ 全部通过${NC}" ;;
            3) echo -e "  结果:    ${YELLOW}⚠️  通过（有警告）${NC}" ;;
            *) echo -e "  结果:    ${RED}❌ 未通过 (exit=$hc_rc)${NC}" ;;
        esac
    else
        echo -e "  ${YELLOW}⚠️${NC}  缺少 .claude/.env — 跳过健康检查"
        echo -e "  ${CYAN}💡${NC} 手动运行: bash tools/synapse-health-check.sh"
    fi

    echo ""

    # ── Daemon status ──
    echo -e "${BOLD}── Daemon ──${NC}"
    local launchd_script="$PROJECT_ROOT/tools/synapse-launchd.sh"
    if [[ -f "$launchd_script" ]]; then
        bash "$launchd_script" status "$WORKER_ID" 2>/dev/null || echo -e "  ${YELLOW}⚠️${NC}  launchd status 查询失败"
    else
        echo -e "  ${YELLOW}⚠️${NC}  synapse-launchd.sh 不可用"
    fi
}

# ── Main dispatch ──
case "$COMMAND" in
    upgrade)  cmd_upgrade  ;;
    rollback) cmd_rollback ;;
    status)   cmd_status   ;;
    *) usage ;;
esac
