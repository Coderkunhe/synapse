#!/usr/bin/env bash
# check-env-pollution.sh — ENV-1: Shell 环境变量污染检测
#
# 检测全局 shell 环境中残留的 SYNAPSE_* 变量是否与 Worker .env 冲突。
# R5 狗粮根因：全局 shell 残留旧 SYNAPSE_API_KEY → Worker 使用错误凭据，~10min 诊断。
# B135 session-init.js 已通过 inline-env 绕过污染，但缺乏自动检测和告警能力。
#
# 两个检测维度：
#   1. 当前 shell 环境变量（printenv）— 与所有 Worker .env SHA-256 比对
#   2. Shell profile 文件（~/.zshrc, ~/.bashrc 等）— 扫描 export SYNAPSE_* 行
#
# P12-B26: D1 ENV-1 🟡→🟢 — 对标 B24 ENV-2 (check-env-consistency.sh) 架构
#
# Usage:
#   check-env-pollution.sh [--fix] [--strict]
#     --fix      注释 profile 文件中的污染行（自动备份）+ 生成 shell unset 命令
#     --strict   任何污染视为 ERROR（退出码 1），否则 WARNING（退出码 0）
#
# Exit codes:
#   0 - 无污染或非严格模式下仅有 WARNING
#   1 - 发现污染（--strict 模式）或 --fix 修复失败
#   2 - 脚本执行错误

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

STRICT=false
FIX=false
EXIT_CODE=0
FIX_MARKER='# [synapse:disabled by check-env-pollution.sh P12-B26]'

for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=true ;;
        --fix)    FIX=true ;;
        *)        echo "Unknown arg: $arg"; echo "Usage: check-env-pollution.sh [--fix] [--strict]"; exit 2 ;;
    esac
done

# ── Path resolution (same as ENV-2) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
GRANDPARENT_DIR="$(dirname "$(dirname "$PROJECT_DIR")")"

# ── Counters ──
WORKER_COUNT=0
SHELL_POLLUTION_COUNT=0
PROFILE_LINES_FOUND=0
PROFILE_LINES_FIXED=0
UNSET_VARS=()

# ── Collect all Worker .env keys for cross-referencing ──
declare -A WORKER_ENV_KEYS  # var_name → sha256 (from first Worker; flag mismatch if different Workers have different keys)
declare -A WORKER_ENV_TAILS # var_name → tail8
declare -A WORKER_KEY_SOURCES # var_name → "WorkerName:.env"

# ── Helpers ──
key_tail() {
    local key="$1"
    echo "${key: -8}"
}

sha_of() {
    local val="$1"
    if [[ -z "$val" ]]; then
        echo "EMPTY"
    else
        echo "$val" | shasum -a 256 | cut -d' ' -f1
    fi
}

read_env_var() {
    local env_file="$1"
    local var_name="$2"
    grep "^${var_name}=" "$env_file" 2>/dev/null | head -1 | sed "s/^${var_name}=//" || echo ""
}

# ── Phase 0: Collect all Worker .env values ──
collect_worker_envs() {
    for dir in "$GRANDPARENT_DIR"/synapse-*/; do
        [[ -d "$dir" ]] || continue
        local dir_name
        dir_name=$(basename "$dir")

        # Skip main synapse repo
        [[ "$dir_name" == "synapse" ]] && continue
        # Skip non-Worker dirs
        [[ "$dir_name" =~ ^synapse-(builder|orchestrator|steward|worker) ]] || continue

        # Try .claude/.env first (Claude Code), then bare .env (Codex)
        local env_file=""
        if [[ -f "$dir/.claude/.env" ]]; then
            env_file="$dir/.claude/.env"
        elif [[ -f "$dir/.env" ]]; then
            env_file="$dir/.env"
        else
            continue
        fi

        WORKER_COUNT=$((WORKER_COUNT + 1))

        for var in SYNAPSE_API_KEY SYNAPSE_WORKER_ID SYNAPSE_API_URL SYNAPSE_TEAM_ID; do
            local val
            val=$(read_env_var "$env_file" "$var")
            if [[ -n "$val" ]]; then
                local vsha
                vsha=$(sha_of "$val")
                # Store first-seen; if different Workers have different values for the same var,
                # that's expected (each Worker has its own key/id). We just need to know
                # that the shell value doesn't match ANY Worker.
                WORKER_ENV_KEYS["${var}|${vsha}"]=1
                WORKER_ENV_TAILS["${var}|${vsha}"]=$(key_tail "$val")
                WORKER_KEY_SOURCES["${var}|${vsha}"]="${dir_name}:.env"
            fi
        done
    done
}

# ── Check if a shell value matches ANY Worker .env ──
matches_any_worker() {
    local var_name="$1"
    local shell_val="$2"
    local shell_sha
    shell_sha=$(sha_of "$shell_val")

    for key in "${!WORKER_ENV_KEYS[@]}"; do
        if [[ "$key" == "${var_name}|${shell_sha}" ]]; then
            return 0  # match found
        fi
    done
    return 1  # no match → pollution
}

# ── Phase 1: Current shell environment ──
check_shell_env() {
    echo -e "${BLUE}🔍 维度 1: 当前 Shell 环境变量${NC}"
    echo "────────────────────────────────────────────"

    local found_any=false

    for var in SYNAPSE_API_KEY SYNAPSE_WORKER_ID SYNAPSE_API_URL SYNAPSE_TEAM_ID; do
        local shell_val="${!var:-}"
        if [[ -z "$shell_val" ]]; then
            continue
        fi

        found_any=true

        if matches_any_worker "$var" "$shell_val"; then
            echo -e "  ${GREEN}✅ \$${var} — 与 Worker .env 一致 (尾号 ...$(key_tail "$shell_val"))${NC}"
        else
            echo -e "  ${RED}❌ \$${var} — 污染！与所有 Worker .env 均不匹配${NC}"
            echo -e "     shell 尾号: ...${BLUE}$(key_tail "$shell_val")${NC}"
            # Show what Workers have for comparison
            for key in "${!WORKER_ENV_KEYS[@]}"; do
                if [[ "$key" == ${var}\|* ]]; then
                    local worker_tail="${WORKER_ENV_TAILS[$key]}"
                    local worker_src="${WORKER_KEY_SOURCES[$key]}"
                    echo -e "     ${worker_src} 尾号: ...${CYAN}${worker_tail}${NC}"
                fi
            done
            SHELL_POLLUTION_COUNT=$((SHELL_POLLUTION_COUNT + 1))
            UNSET_VARS+=("$var")
        fi
    done

    if ! $found_any; then
        echo -e "  ${GREEN}ℹ️  当前 shell 未设置 SYNAPSE_* 变量 — 无污染风险${NC}"
    fi

    echo ""
}

# ── Phase 2: Shell profile files ──
check_profile_files() {
    echo -e "${BLUE}🔍 维度 2: Shell Profile 文件${NC}"
    echo "────────────────────────────────────────────"

    local profiles=()
    local home_dir="$HOME"

    # Build list of existing profile files to scan
    for candidate in "$home_dir/.zshenv" "$home_dir/.zshrc" "$home_dir/.zprofile" \
                     "$home_dir/.bashrc" "$home_dir/.bash_profile" "$home_dir/.profile"; do
        if [[ -f "$candidate" ]]; then
            profiles+=("$candidate")
        fi
    done

    if [[ ${#profiles[@]} -eq 0 ]]; then
        echo -e "  ${GREEN}ℹ️  未发现 shell profile 文件${NC}"
        echo ""
        return
    fi

    local any_found=false
    # Collect (profile, line_num) pairs for deferred reverse-order fixing
    declare -A PROFILE_BAK_CREATED
    local fix_lines=()  # "profile:line_num" pairs

    for profile in "${profiles[@]}"; do
        local profile_name
        profile_name=$(basename "$profile")

        # Find lines with SYNAPSE_ exports (exclude already-fixed lines by marker)
        local matches
        matches=$(grep -nE '(export[[:space:]]+)?SYNAPSE_[[:upper:]_]+=' "$profile" 2>/dev/null | grep -vF "$FIX_MARKER" || true)

        if [[ -z "$matches" ]]; then
            continue
        fi

        any_found=true
        echo -e "  ${CYAN}📄 ${profile_name}${NC}"

        local line_has_pollution=false

        while IFS= read -r match_line; do
            local line_num
            line_num=$(echo "$match_line" | cut -d: -f1)
            local line_content
            line_content=$(echo "$match_line" | cut -d: -f2-)

            # Skip lines that are already comments (commented-out exports without our marker)
            if echo "$line_content" | grep -qE '^[[:space:]]*#'; then
                continue
            fi

            # Extract variable name and value
            # Patterns: export SYNAPSE_VAR=value, SYNAPSE_VAR=value, export SYNAPSE_VAR="value"
            local var_name=""
            local var_value=""

            if echo "$line_content" | grep -qE '^[[:space:]]*export[[:space:]]+SYNAPSE_[[:upper:]_]+='; then
                var_name=$(echo "$line_content" | sed -n 's/^[[:space:]]*export[[:space:]]\{1,\}\(SYNAPSE_[A-Z_]*\)=.*/\1/p')
                var_value=$(echo "$line_content" | sed -n 's/^[[:space:]]*export[[:space:]]\{1,\}SYNAPSE_[A-Z_]*=//p' | sed 's/^"//;s/"$//;s/^'\''//;s/'\''$//')
            elif echo "$line_content" | grep -qE '^[[:space:]]*SYNAPSE_[[:upper:]_]+='; then
                var_name=$(echo "$line_content" | sed -n 's/^[[:space:]]*\(SYNAPSE_[A-Z_]*\)=.*/\1/p')
                var_value=$(echo "$line_content" | sed -n 's/^[[:space:]]*SYNAPSE_[A-Z_]*=//p' | sed 's/^"//;s/"$//;s/^'\''//;s/'\''$//')
            fi

            if [[ -z "$var_name" ]]; then
                continue
            fi

            PROFILE_LINES_FOUND=$((PROFILE_LINES_FOUND + 1))

            if matches_any_worker "$var_name" "$var_value"; then
                echo -e "    ${GREEN}✅ L${line_num}: \$${var_name} — 与 Worker .env 一致${NC}"
            else
                echo -e "    ${RED}❌ L${line_num}: \$${var_name} — 污染！值不匹配任何 Worker${NC}"
                echo -e "       profile 尾号: ...${BLUE}$(key_tail "$var_value")${NC}"
                for key in "${!WORKER_ENV_KEYS[@]}"; do
                    if [[ "$key" == ${var_name}\|* ]]; then
                        local worker_tail="${WORKER_ENV_TAILS[$key]}"
                        local worker_src="${WORKER_KEY_SOURCES[$key]}"
                        echo -e "       ${worker_src} 尾号: ...${CYAN}${worker_tail}${NC}"
                    fi
                done
                line_has_pollution=true
                SHELL_POLLUTION_COUNT=$((SHELL_POLLUTION_COUNT + 1))
                UNSET_VARS+=("$var_name")

                if $FIX; then
                    fix_lines+=("${profile}:${line_num}")
                else
                    echo -e "       → 修复: check-env-pollution.sh --fix"
                fi
            fi
        done <<< "$matches"

        if ! $line_has_pollution; then
            echo -e "    ${GREEN}✅ 无污染行${NC}"
        fi
        echo ""
    done

    # ── Deferred --fix: apply in reverse line-number order per profile ──
    if $FIX && [[ ${#fix_lines[@]} -gt 0 ]]; then
        # Sort by profile, then by line_num descending (so we edit bottom-up, preserving line numbers)
        local sorted_lines
        sorted_lines=$(printf '%s\n' "${fix_lines[@]}" | sort -t: -k1,1 -k2,2nr)

        local current_profile=""
        while IFS= read -r entry; do
            local pf="${entry%%:*}"
            local ln="${entry##*:}"

            if [[ "$pf" != "$current_profile" ]]; then
                current_profile="$pf"
                # Create backup once per profile
                if [[ -z "${PROFILE_BAK_CREATED[$pf]:-}" ]]; then
                    local bak="${pf}.bak.$(date +%Y%m%d-%H%M%S)"
                    cp "$pf" "$bak"
                    PROFILE_BAK_CREATED[$pf]=1
                    echo -e "       ${BLUE}📋 备份: ${bak}${NC}"
                fi
            fi

            # Comment out line + append marker on same line (works bottom-up, no line-shift issues)
            if [[ "$(uname -s)" == "Darwin" ]]; then
                sed -i '' "${ln}s|^.*$|# &  ${FIX_MARKER}|" "$pf"
            else
                sed -i "${ln}s|^.*$|# &  ${FIX_MARKER}|" "$pf"
            fi
            echo -e "       ${GREEN}🔧 已注释 L${ln}${NC}"
            PROFILE_LINES_FIXED=$((PROFILE_LINES_FIXED + 1))
        done <<< "$sorted_lines"
    fi

    if ! $any_found; then
        echo -e "  ${GREEN}ℹ️  Profile 文件中未发现 SYNAPSE_* 配置行${NC}"
        echo ""
    fi
}

# ════════════════════════════════════════════════════════════
echo "════════════════════════════════════════════════"
echo -e "${BLUE}🔍 ENV-1: Shell 环境变量污染检测${NC}"
echo "════════════════════════════════════════════════"
echo ""

# Phase 0: Collect Worker env values
collect_worker_envs

if [[ $WORKER_COUNT -eq 0 ]]; then
    echo -e "${YELLOW}⚠️  未发现 Worker 目录（搜索路径: ${GRANDPARENT_DIR}/synapse-*/）${NC}"
    echo -e "${YELLOW}   跳过污染检测 — 无 Worker .env 可对比${NC}"
    exit 0
fi

echo -e "${BLUE}📊 发现 ${WORKER_COUNT} 个 Worker(s)${NC}"
echo ""

# Phase 1: Current shell
check_shell_env

# Phase 2: Profile files
check_profile_files

# ── Fix: generate unset commands for current shell ──
if $FIX && [[ ${#UNSET_VARS[@]} -gt 0 ]]; then
    # Deduplicate
    unique_vars=($(printf '%s\n' "${UNSET_VARS[@]}" | sort -u))
    echo "────────────────────────────────────────────"
    echo -e "${YELLOW}💡 当前 shell 中存在污染变量。运行以下命令清理:${NC}"
    echo ""
    printf "   unset"
    for var in "${unique_vars[@]}"; do
        printf " %s" "$var"
    done
    echo ""
    echo ""
    echo -e "   ${BLUE}或者复制粘贴一键执行:${NC}"
    printf "   unset"
    for var in "${unique_vars[@]}"; do
        printf " %s" "$var"
    done
    echo " && exec \$SHELL -l"
    echo ""
fi

# ── Summary ──
echo "────────────────────────────────────────────"
echo -e "Workers 扫描:        ${WORKER_COUNT}"
echo -e "Shell 环境污染:      ${SHELL_POLLUTION_COUNT}"
echo -e "Profile 污染行:      ${PROFILE_LINES_FOUND}"

if $FIX && [[ $PROFILE_LINES_FIXED -gt 0 ]]; then
    echo -e "\n${GREEN}🔧 --fix: 已注释 ${PROFILE_LINES_FIXED} 行（已创建 .bak 备份）${NC}"
    echo -e "${GREEN}   运行 source ~/.zshrc（或对应 profile）使变更生效${NC}"
fi

if [[ $SHELL_POLLUTION_COUNT -eq 0 ]]; then
    echo -e "\n${GREEN}✅ 未发现 SYNAPSE_* 环境变量污染${NC}"
elif $STRICT; then
    echo -e "\n${RED}❌ 严格模式: 发现 ${SHELL_POLLUTION_COUNT} 项污染${NC}"
    EXIT_CODE=1
else
    echo -e "\n${YELLOW}⚠️  发现 ${SHELL_POLLUTION_COUNT} 项污染${NC}"
    echo -e "${YELLOW}   → session-init.js (B135) 会在启动时以 .env 覆盖，不会导致运行时错误${NC}"
    echo -e "${YELLOW}   → 但 synapse-exec 等脚本直接读取 shell env，可能受影响${NC}"
    echo -e "${YELLOW}   → 建议: check-env-pollution.sh --fix 清理 profile 文件${NC}"
fi

exit $EXIT_CODE
