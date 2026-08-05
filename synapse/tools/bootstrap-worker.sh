#!/usr/bin/env bash
# bootstrap-worker.sh — Synapse Worker 一键 bootstrap（P12-B6）
#
# 将 BOOT-1~7 七个手工步骤整合为一条命令，从零到就绪的 Worker 环境。
#
# Usage:
#   # 非交互模式（CI/CD / 脚本化）：
#   bash tools/bootstrap-worker.sh \
#     --role builder \
#     --target claude \
#     --output /path/to/worker \
#     --api-url http://localhost:8000 \
#     --worker-id wa_xxx \
#     --project-id prj_xxx \
#     --api-key sk-syn-xxx
#
#   # 交互模式（手动输入）：
#   bash tools/bootstrap-worker.sh --interactive
#
#   # 混合模式（部分参数 + 交互补充）：
#   bash tools/bootstrap-worker.sh --role builder --target claude --output . --interactive
#
# 对应 BOOT 步骤：
#   BOOT-1  创建 Worker 目录结构
#   BOOT-2  运行 generate-skill.sh 生成模板
#   BOOT-3  配置 .env 文件（5 个 SYNAPSE_* 变量）
#   BOOT-4  写入 OS 密钥链（synapse-key.sh store）
#   BOOT-5  安装 git hooks（synapse-exec --install-hook）
#   BOOT-6  验证 Worker 连通性（Protocol API 200）
#   BOOT-7  配置 settings.json（SessionStart hook + keychain hook）
#
# P12-6: 每批需减少一项 God's-eye 手动运维操作。B6 将 BOOT-1~7 从 7 步手工 → 1 条命令。

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

# ── State tracking ──
BOOT_STATUS=()
CURRENT_STEP=0
INTERACTIVE=false

# ── Config values (populated from CLI args or interactive prompts) ──
ROLE=""
TARGET=""
OUTPUT=""
API_URL=""
WORKER_ID=""
PROJECT_ID=""
API_KEY=""

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Synapse Worker 一键 bootstrap — 从零到就绪。

OPTIONS (non-interactive):
  --role <builder|orchestrator|steward>
  --target <claude|codex>
  --output <path>            Worker 项目根目录
  --api-url <url>            Synapse Server 地址
  --worker-id <id>           Worker ID
  --project-id <id>          Project ID
  --api-key <key>            Worker API Key

OPTIONS (interactive):
  --interactive              交互式引导模式（逐个提示输入）

OPTIONS (misc):
  --dry-run                  仅检查，不执行
  -h, --help                 显示帮助

EXAMPLES:
  # 一键创建 Claude Code Builder:
  $0 --role builder --target claude --output ./my-builder \\
     --api-url http://localhost:8000 --worker-id wa_xxx \\
     --project-id prj_xxx --api-key sk-syn-xxx

  # 交互式引导:
  $0 --interactive

  # 混合: 已知角色和目标，交互输入凭据:
  $0 --role builder --target claude --output . --interactive
EOF
    exit 1
}

# ── Argument parsing ──
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --role)          ROLE="$2"; shift 2 ;;
        --target)        TARGET="$2"; shift 2 ;;
        --output)        OUTPUT="$2"; shift 2 ;;
        --api-url)       API_URL="$2"; shift 2 ;;
        --worker-id)     WORKER_ID="$2"; shift 2 ;;
        --project-id)    PROJECT_ID="$2"; shift 2 ;;
        --api-key)       API_KEY="$2"; shift 2 ;;
        --interactive)   INTERACTIVE=true; shift ;;
        --dry-run)       DRY_RUN=true; shift ;;
        -h|--help)       usage ;;
        *) echo -e "${RED}❌ 未知参数: $1${NC}"; usage ;;
    esac
done

# ── Helper: mark step status ──
step_pass() { BOOT_STATUS+=("✅ $1"); }
step_skip() { BOOT_STATUS+=("⏭️  $1 (已就绪)"); }
step_fail() { BOOT_STATUS+=("❌ $1"); }

# ── Helper: interactive prompt ──
prompt() {
    local var_name="$1"
    local prompt_text="$2"
    local current_value="${!var_name}"
    local default="${3:-}"

    if [[ -n "$current_value" ]]; then
        echo -e "  ${CYAN}${prompt_text}${NC} [${BOLD}${current_value}${NC}]: "
        read -r input
        if [[ -n "$input" ]]; then
            eval "$var_name=\"$input\""
        fi
    else
        if [[ -n "$default" ]]; then
            echo -e "  ${CYAN}${prompt_text}${NC} [${BOLD}${default}${NC}]: "
        else
            echo -e "  ${CYAN}${prompt_text}${NC}: "
        fi
        read -r input
        if [[ -n "$input" ]]; then
            eval "$var_name=\"$input\""
        elif [[ -n "$default" ]]; then
            eval "$var_name=\"$default\""
        fi
    fi
}

# ── Helper: validate required value ──
require() {
    local var_name="$1"
    local label="$2"
    if [[ -z "${!var_name:-}" ]]; then
        echo -e "${RED}❌ 缺少必需参数: ${label}${NC}"
        echo "   通过 --${var_name,,} 或交互模式提供"
        return 1
    fi
    return 0
}

# ── Helper: print step header ──
step_header() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "${BOLD}── BOOT-${CURRENT_STEP}: $1 ──${NC}"
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-1: 创建 Worker 目录结构
# ═══════════════════════════════════════════════════════════════════════

boot1_create_directories() {
    step_header "创建 Worker 目录结构"

    local target_dir="$OUTPUT"
    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将创建: ${target_dir}"
        step_pass "BOOT-1 (dry-run)"
        return 0
    fi

    if [[ -d "$target_dir" ]]; then
        echo -e "  ${GREEN}✅${NC} 目录已存在: ${target_dir}"
        # Check if it already has Worker structure
        if [[ -d "$target_dir/.claude/skills/synapse" ]] || [[ -d "$target_dir/.agents/skills" ]]; then
            echo -e "  ${YELLOW}⚠️${NC}  检测到已有 Worker 结构 — 将跳过不覆盖"
        fi
    else
        mkdir -p "$target_dir"
        echo -e "  ${GREEN}✅${NC} 创建目录: ${target_dir}"
    fi

    # Create .gitignore if not exists
    local gitignore="$target_dir/.gitignore"
    if [[ ! -f "$gitignore" ]]; then
        cat > "$gitignore" <<'GITIGNOREEOF'
# Synapse Worker
.claude/.env
.claude/skills/synapse/_protocol-cache.json
.claude/skills/synapse/scripts/node_modules/
.claude/.daemon-*.pid
.claude/.session-alive
.claude/template-upgrade-needed
.claude/synapse-version.json
_task-current.md
_boot-prompt.md
GITIGNOREEOF
        echo -e "  ${GREEN}✅${NC} 创建 .gitignore"
    fi

    step_pass "BOOT-1"
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-2: 运行 generate-skill.sh 生成模板
# ═══════════════════════════════════════════════════════════════════════

boot2_generate_skill() {
    step_header "生成 Worker Skill 模板"

    local gen_script="$PROJECT_ROOT/tools/generate-skill.sh"
    if [[ ! -f "$gen_script" ]]; then
        echo -e "${RED}❌ 找不到 generate-skill.sh: ${gen_script}${NC}"
        step_fail "BOOT-2"
        return 1
    fi

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将运行: generate-skill.sh --client --target ${TARGET} --output ${OUTPUT}"
        step_pass "BOOT-2 (dry-run)"
        return 0
    fi

    echo -e "  ▎ 运行 generate-skill.sh --client --target ${TARGET} --output ${OUTPUT} ..."
    if bash "$gen_script" --client --target "$TARGET" --output "$OUTPUT"; then
        echo -e "  ${GREEN}✅${NC} 模板生成完成"
        step_pass "BOOT-2"
    else
        echo -e "${RED}❌ generate-skill.sh 执行失败 (exit code: $?)${NC}"
        step_fail "BOOT-2"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-3: 配置 .env 文件
# ═══════════════════════════════════════════════════════════════════════

boot3_configure_env() {
    step_header "配置 .env 文件"

    local env_file
    if [[ "$TARGET" == "claude" ]]; then
        env_file="$OUTPUT/.claude/.env"
    else
        # Codex: .agents/ is read-only sandbox (P12-B5). Write .env to project root.
        # The user must `source .env` before starting Codex — no auto-load mechanism.
        env_file="$OUTPUT/.env"
    fi

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将写入: ${env_file}"
        step_pass "BOOT-3 (dry-run)"
        return 0
    fi

    # Check if .env already exists and has content
    if [[ -f "$env_file" ]] && grep -q "SYNAPSE_API_URL" "$env_file" 2>/dev/null; then
        echo -e "  ${YELLOW}⚠️${NC}  .env 已存在且包含 SYNAPSE_API_URL"
        echo -n "  是否覆盖？[y/N] "
        read -r overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            echo -e "  ${GREEN}✅${NC} 保留现有 .env"
            step_skip "BOOT-3"
            return 0
        fi
    fi

    # Ensure directory exists
    mkdir -p "$(dirname "$env_file")"

    # Write .env
    cat > "$env_file" <<ENVEOF
# Synapse Worker — 环境配置
# 由 bootstrap-worker.sh 自动生成 · P12-B6
# 生成时间: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Synapse Server
SYNAPSE_API_URL=${API_URL}
SYNAPSE_WORKER_ID=${WORKER_ID}
SYNAPSE_PROJECT_ID=${PROJECT_ID}

# Worker Role
SYNAPSE_WORKER_ROLE=${ROLE}

# API Key — 优先从 OS 密钥链读取（BOOT-4），此处为 fallback
# 如果已存入密钥链，可删除此行让 session-init.js 走 keychain fallback
SYNAPSE_API_KEY=${API_KEY}

ENVEOF

    # Set restrictive permissions
    chmod 600 "$env_file" 2>/dev/null || true

    echo -e "  ${GREEN}✅${NC} .env 已写入: ${env_file}"
    echo -e "  ${YELLOW}🔐${NC} 权限已设为 600"
    step_pass "BOOT-3"
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-4: 写入 OS 密钥链
# ═══════════════════════════════════════════════════════════════════════

boot4_keychain_store() {
    step_header "写入 OS 密钥链"

    local key_script="$PROJECT_ROOT/tools/synapse-key.sh"
    if [[ ! -f "$key_script" ]]; then
        echo -e "${YELLOW}⚠️${NC}  找不到 synapse-key.sh — 跳过密钥链存储（.env fallback 可用）"
        step_skip "BOOT-4 (script not found)"
        return 0
    fi

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将运行: synapse-key.sh store ${WORKER_ID} <key>"
        step_pass "BOOT-4 (dry-run)"
        return 0
    fi

    # Check if key already exists
    if bash "$key_script" check "$WORKER_ID" 2>/dev/null; then
        echo -e "  ${YELLOW}⚠️${NC}  密钥链中已存在 ${WORKER_ID} 的记录"
        echo -n "  是否覆盖？[y/N] "
        read -r overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            echo -e "  ${GREEN}✅${NC} 保留现有密钥链记录"
            step_skip "BOOT-4"
            return 0
        fi
    fi

    if bash "$key_script" store "$WORKER_ID" "$API_KEY"; then
        echo -e "  ${GREEN}✅${NC} API Key 已存入 OS 密钥链"
        echo -e "  ${CYAN}💡${NC} session-init.js 将优先从密钥链读取（keychain.js → getKey fallback）"
        step_pass "BOOT-4"
    else
        echo -e "${YELLOW}⚠️${NC}  密钥链存储失败 — .env fallback 仍可用"
        echo -e "  ${CYAN}💡${NC} 非 macOS/Linux 系统或密钥链不可用时可跳过此步"
        step_skip "BOOT-4 (keychain unavailable, .env fallback active)"
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-5: 安装 git hooks
# ═══════════════════════════════════════════════════════════════════════

boot5_install_hooks() {
    step_header "安装 git hooks"

    # Check if OUTPUT is a git repository
    if ! git -C "$OUTPUT" rev-parse --git-dir &>/dev/null; then
        echo -e "  ${YELLOW}⚠️${NC}  ${OUTPUT} 不是 git 仓库 — 跳过 hook 安装"
        echo -e "  ${CYAN}💡${NC} 在 git 仓库中运行: cd ${OUTPUT} && git init && 重新运行此脚本"
        step_skip "BOOT-5 (not a git repo)"
        return 0
    fi

    local exec_script="$PROJECT_ROOT/tools/synapse-exec"
    if [[ ! -f "$exec_script" ]]; then
        echo -e "${YELLOW}⚠️${NC}  找不到 synapse-exec — 跳过 hook 安装"
        step_skip "BOOT-5 (script not found)"
        return 0
    fi

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将运行: synapse-exec --install-hook ${OUTPUT}"
        step_pass "BOOT-5 (dry-run)"
        return 0
    fi

    echo -e "  ▎ 安装 git hooks 到 ${OUTPUT}/.git/hooks/ ..."
    if bash "$exec_script" --install-hook "$OUTPUT"; then
        echo -e "  ${GREEN}✅${NC} git hooks 安装完成"
        step_pass "BOOT-5"
    else
        echo -e "${RED}❌ hook 安装失败 (exit code: $?)${NC}"
        echo -e "  ${CYAN}💡${NC} 可稍后手动运行: synapse-exec --install-hook ${OUTPUT}"
        step_fail "BOOT-5"
        return 1
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-6: 验证 Worker 连通性
# ═══════════════════════════════════════════════════════════════════════

boot6_verify_connectivity() {
    step_header "验证 Worker 连通性"

    local protocol_url="${API_URL%/}/v1/workers/${WORKER_ID}/protocol?project_id=${PROJECT_ID}&role=${ROLE}"

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将请求: GET ${protocol_url}"
        step_pass "BOOT-6 (dry-run)"
        return 0
    fi

    # Check dependencies
    if ! command -v curl &>/dev/null; then
        echo -e "${YELLOW}⚠️${NC}  curl 不可用 — 跳过连通性验证"
        step_skip "BOOT-6 (curl not found)"
        return 0
    fi

    echo -e "  ▎ 测试 Protocol API: GET ${protocol_url}"

    local http_code
    local curl_error
    curl_error=$(mktemp)
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${API_KEY}" \
        --connect-timeout 5 \
        --max-time 10 \
        "${protocol_url}" 2>"$curl_error") || true
    local curl_stderr
    curl_stderr=$(cat "$curl_error" 2>/dev/null || true)
    rm -f "$curl_error"

    case "$http_code" in
        200)
            echo -e "  ${GREEN}✅${NC} Protocol API 可达 (HTTP 200)"
            step_pass "BOOT-6"
            ;;
        401)
            echo -e "${RED}❌ HTTP 401 — API Key 无效${NC}"
            echo -e "  ${CYAN}💡${NC} 检查 SYNAPSE_API_KEY 是否正确、是否过期"
            step_fail "BOOT-6"
            return 1
            ;;
        404)
            echo -e "${RED}❌ HTTP 404 — Worker ID 或 Project ID 不存在${NC}"
            echo -e "  ${CYAN}💡${NC} 确认 Worker 已在 Synapse Server 上注册"
            step_fail "BOOT-6"
            return 1
            ;;
        422)
            echo -e "${RED}❌ HTTP 422 — Worker 角色未配置${NC}"
            echo -e "  ${CYAN}💡${NC} 在 Synapse 中为 Worker 配置角色: POST /v1/projects/{pid}/workers/{wid}/roles"
            step_fail "BOOT-6"
            return 1
            ;;
        *)
            echo -e "${RED}❌ 连接失败 (HTTP ${http_code})${NC}"
            if [[ -n "$curl_stderr" ]]; then
                echo -e "  ${RED}   ${curl_stderr}${NC}"
            fi
            echo -e "  ${CYAN}💡${NC} 检查 SYNAPSE_API_URL 是否正确、Server 是否运行"
            step_fail "BOOT-6"
            return 1
            ;;
    esac
}

# ═══════════════════════════════════════════════════════════════════════
# BOOT-7: 验证 settings.json 配置
# ═══════════════════════════════════════════════════════════════════════

boot7_verify_settings() {
    step_header "验证 settings.json 配置"

    if [[ "$TARGET" != "claude" ]]; then
        echo -e "  ${YELLOW}⚠️${NC}  Codex 客户端无 settings.json — 跳过"
        step_skip "BOOT-7 (Codex — not applicable)"
        return 0
    fi

    local settings_file="$OUTPUT/.claude/settings.json"
    local settings_local="$OUTPUT/.claude/settings.local.json"

    if $DRY_RUN; then
        echo -e "  ${YELLOW}[dry-run]${NC} 将检查: ${settings_file}"
        step_pass "BOOT-7 (dry-run)"
        return 0
    fi

    # generate-skill.sh should have created settings.json with SessionStart hook
    if [[ -f "$settings_file" ]]; then
        echo -e "  ${GREEN}✅${NC} settings.json 存在: ${settings_file}"

        # Verify SessionStart hook is present
        if grep -q "SessionStart" "$settings_file" 2>/dev/null; then
            echo -e "  ${GREEN}✅${NC} SessionStart hook 已配置"
        else
            echo -e "  ${YELLOW}⚠️${NC}  SessionStart hook 未找到 — Worker 不会在会话启动时自动初始化"
        fi

        # Verify keychain hook is present (BOOT-7 specific)
        if grep -q "keychain\|Keychain" "$settings_file" 2>/dev/null; then
            echo -e "  ${GREEN}✅${NC} Keychain hook 已配置"
        else
            echo -e "  ${YELLOW}⚠️${NC}  Keychain hook 未配置 — session-init.js 使用 inline-env fallback（B135）"
        fi
    else
        echo -e "  ${YELLOW}⚠️${NC}  settings.json 不存在 — generate-skill.sh 应已生成"
        echo -e "  ${CYAN}💡${NC} 手动运行: bash tools/generate-skill.sh --client --target claude --output ${OUTPUT}"
    fi

    # Check settings.local.json (B110 Layer 2 — per-Worker permissions)
    if [[ -f "$settings_local" ]]; then
        echo -e "  ${GREEN}✅${NC} settings.local.json 存在（per-Worker 权限已生成）"
    else
        echo -e "  ${CYAN}💡${NC} settings.local.json 将在首次 session-init.js 运行时自动生成（B110 Layer 2）"
    fi

    step_pass "BOOT-7"
}

# ═══════════════════════════════════════════════════════════════════════
# Interactive mode: gather all config values
# ═══════════════════════════════════════════════════════════════════════

run_interactive() {
    echo ""
    echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
    echo -e "${BOLD}│  Synapse Worker Bootstrap · 交互式引导        │${NC}"
    echo -e "${BOLD}│  P12-B6 — 一键创建 Worker 环境                │${NC}"
    echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
    echo ""
    echo "按提示输入配置值。已有默认值的按 Enter 保留。"
    echo ""

    # Role
    while [[ ! "$ROLE" =~ ^(builder|orchestrator|steward)$ ]]; do
        prompt ROLE "Worker 角色 (builder/orchestrator/steward)"
        if [[ ! "$ROLE" =~ ^(builder|orchestrator|steward)$ ]]; then
            echo -e "  ${RED}❌ 无效角色: ${ROLE}${NC}"
        fi
    done

    # Target
    while [[ ! "$TARGET" =~ ^(claude|codex)$ ]]; do
        prompt TARGET "客户端类型 (claude/codex)" "claude"
        if [[ ! "$TARGET" =~ ^(claude|codex)$ ]]; then
            echo -e "  ${RED}❌ 无效客户端: ${TARGET}${NC}"
        fi
    done

    # Output
    while [[ -z "$OUTPUT" ]]; do
        prompt OUTPUT "Worker 根目录路径" "$PWD"
    done

    # API URL
    while [[ -z "$API_URL" ]]; do
        prompt API_URL "Synapse Server URL" "${SYNAPSE_API_URL:-http://localhost:8000}"
    done

    # Worker ID
    while [[ -z "$WORKER_ID" ]]; do
        prompt WORKER_ID "Worker ID" "${SYNAPSE_WORKER_ID:-}"
    done

    # Project ID
    while [[ -z "$PROJECT_ID" ]]; do
        prompt PROJECT_ID "Project ID" "${SYNAPSE_PROJECT_ID:-}"
    done

    # API Key
    while [[ -z "$API_KEY" ]]; do
        prompt API_KEY "Worker API Key" "${SYNAPSE_API_KEY:-}"
    done

    echo ""
    echo -e "${BOLD}── 配置确认 ──${NC}"
    echo -e "  角色:      ${GREEN}${ROLE}${NC}"
    echo -e "  客户端:    ${GREEN}${TARGET}${NC}"
    echo -e "  输出目录:  ${GREEN}${OUTPUT}${NC}"
    echo -e "  API URL:   ${GREEN}${API_URL}${NC}"
    echo -e "  Worker ID: ${GREEN}${WORKER_ID}${NC}"
    echo -e "  Project:   ${GREEN}${PROJECT_ID}${NC}"
    echo -e "  API Key:   ${GREEN}${API_KEY:0:16}...${NC}"
    echo ""
    echo -n "确认开始 bootstrap？[Y/n] "
    read -r confirm
    if [[ "$confirm" =~ ^[Nn]$ ]]; then
        echo "已取消。"
        exit 0
    fi
}

# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

main() {
    # ── Interactive mode ──
    if $INTERACTIVE; then
        run_interactive
    fi

    # ── Validate required inputs ──
    echo ""
    echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
    echo -e "${BOLD}│  Synapse Worker Bootstrap · P12-B6            │${NC}"
    echo -e "${BOLD}│  BOOT-1 → BOOT-7 一键拉通                     │${NC}"
    echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"

    local validation_errors=0

    if ! require ROLE "Worker 角色 (--role)"; then validation_errors=$((validation_errors + 1)); fi
    if ! require TARGET "客户端类型 (--target)"; then validation_errors=$((validation_errors + 1)); fi
    if ! require OUTPUT "输出目录 (--output)"; then validation_errors=$((validation_errors + 1)); fi
    if ! require API_URL "Synapse Server URL (--api-url)"; then validation_errors=$((validation_errors + 1)); fi
    if ! require WORKER_ID "Worker ID (--worker-id)"; then validation_errors=$((validation_errors + 1)); fi
    if ! require PROJECT_ID "Project ID (--project-id)"; then validation_errors=$((validation_errors + 1)); fi
    if ! require API_KEY "API Key (--api-key)"; then validation_errors=$((validation_errors + 1)); fi

    # Validate role enum
    if [[ -n "$ROLE" ]] && [[ ! "$ROLE" =~ ^(builder|orchestrator|steward)$ ]]; then
        echo -e "${RED}❌ 无效角色: ${ROLE}（支持 builder | orchestrator | steward）${NC}"
        validation_errors=$((validation_errors + 1))
    fi

    # Validate target enum
    if [[ -n "$TARGET" ]] && [[ ! "$TARGET" =~ ^(claude|codex)$ ]]; then
        echo -e "${RED}❌ 无效客户端: ${TARGET}（支持 claude | codex）${NC}"
        validation_errors=$((validation_errors + 1))
    fi

    # Validate API key format (B104-1: key liveness check)
    if [[ -n "$API_KEY" ]]; then
        if [[ ! "$API_KEY" =~ ^sk-syn- ]] || [[ ${#API_KEY} -lt 32 ]]; then
            echo -e "${YELLOW}⚠️  API Key 格式异常（期望前缀 sk-syn-，长度 ≥32，实际长度 ${#API_KEY}）${NC}"
            echo -e "  ${CYAN}💡${NC} 如果 key 确实正确可忽略此警告"
        fi
    fi

    if [[ $validation_errors -gt 0 ]]; then
        echo ""
        echo -e "${RED}❌ ${validation_errors} 项验证失败。使用 --interactive 进入交互模式。${NC}"
        exit 1
    fi

    # Resolve absolute output path
    OUTPUT="$(cd "$OUTPUT" 2>/dev/null && pwd || echo "$OUTPUT")"
    if [[ ! -d "$OUTPUT" ]]; then
        # Directory doesn't exist yet — BOOT-1 will create it
        OUTPUT="$(cd "$(dirname "$OUTPUT")" 2>/dev/null && pwd)/$(basename "$OUTPUT")" || true
    fi

    echo ""
    echo -e "  角色:      ${GREEN}${ROLE}${NC}"
    echo -e "  客户端:    ${GREEN}${TARGET}${NC}"
    echo -e "  输出目录:  ${GREEN}${OUTPUT}${NC}"
    echo -e "  API URL:   ${GREEN}${API_URL}${NC}"
    echo -e "  Worker ID: ${GREEN}${WORKER_ID}${NC}"
    echo -e "  Project:   ${GREEN}${PROJECT_ID}${NC}"
    echo ""

    # ── Execute BOOT steps ──
    local failed=0

    boot1_create_directories   || failed=$((failed + 1))
    boot2_generate_skill       || failed=$((failed + 1))
    boot3_configure_env        || failed=$((failed + 1))
    boot4_keychain_store       || failed=$((failed + 1))
    boot5_install_hooks        || failed=$((failed + 1))
    boot6_verify_connectivity  || failed=$((failed + 1))
    boot7_verify_settings      || failed=$((failed + 1))

    # ── Summary ──
    echo ""
    echo -e "${BOLD}┌──────────────────────────────────────────────┐${NC}"
    echo -e "${BOLD}│  Bootstrap 完成 · 结果总览                     │${NC}"
    echo -e "${BOLD}└──────────────────────────────────────────────┘${NC}"
    echo ""
    for status in "${BOOT_STATUS[@]}"; do
        echo -e "  ${status}"
    done
    echo ""

    if [[ $failed -eq 0 ]]; then
        echo -e "${GREEN}${BOLD}✅ Worker bootstrap 全量完成！${NC}"
        echo ""
        echo -e "${BOLD}下一步:${NC}"
        case "$TARGET" in
            claude)
                echo -e "  ${CYAN}1.${NC} 打开 Claude Code: ${BOLD}cd ${OUTPUT} && claude${NC}"
                echo -e "  ${CYAN}2.${NC} Worker 将在 SessionStart hook 触发时自动初始化"
                echo -e "  ${CYAN}3.${NC} 或手动冷启动: 在 Claude Code 中输入 ${BOLD}@_boot-prompt.md${NC}"
                ;;
            codex)
                echo -e "  ${CYAN}1.${NC} 加载环境变量: ${BOLD}source .env${NC}"
                echo -e "  ${CYAN}2.${NC} 启动 Codex CLI: ${BOLD}cd ${OUTPUT} && codex${NC}"
                echo -e "  ${CYAN}3.${NC} Worker 将通过 SKILL.md prompt 驱动初始化（无 SessionStart hook）"
                echo -e "  ${CYAN}4.${NC} Worker 通过 API 获取状态: ${BOLD}GET /v1/workers/me/state${NC} (P12-B5)"
                echo -e ""
                echo -e "  ${YELLOW}⚠️${NC}  Codex 约束（B2+B5 确认）："
                echo -e "     - .agents/ 为只读沙箱 — session-init.js 无法写入 _task-current.md"
                echo -e "     - 无 daemon 能力 — 跳过 heartbeat/WS daemon"
                echo -e "     - 无 @ 文件机制 — _boot-prompt.md 不可用"
                echo -e "     - CronCreate/ScheduleWakeup 需通过 prompt 驱动"
                ;;
        esac
        echo ""
        echo -e "${CYAN}💡${NC} 验证 Worker 状态:"
        echo -e "    curl -s -H \"Authorization: Bearer \${SYNAPSE_API_KEY}\" \\"
        echo -e "      \"\${SYNAPSE_API_URL}/v1/workers/me/state?project_id=\${SYNAPSE_PROJECT_ID}\""
    else
        echo -e "${YELLOW}${BOLD}⚠️  Bootstrap 部分完成 — ${failed} 步失败${NC}"
        echo ""
        echo -e "${CYAN}💡${NC} 失败的步骤可手动补执行。已成功的步骤无需重复。"
        echo -e "${CYAN}💡${NC} 重新运行此脚本会跳过已完成的步骤（idempotent）。"
    fi

    echo ""

    if $DRY_RUN; then
        echo -e "${YELLOW}⚠️  dry-run 模式 — 未做任何实际变更${NC}"
    fi

    return $failed
}

main "$@"
