#!/usr/bin/env bash
# generate-skill.sh — Synapse Worker Skill 包生成器
#
# 用法:
#   bash tools/generate-skill.sh --role <role> --target <claude|codex> --output <path>
#   bash tools/generate-skill.sh --client [--target <claude|codex|cursor>] --output <path>
#   bash tools/generate-skill.sh --from-api --output <path> [--api-url <url>] [--worker-id <id>] [--project-id <id>] [--role <role>] [--api-key <key>]
#
# 示例:
#   bash tools/generate-skill.sh --role orchestrator --target claude --output /path/to/project
#   bash tools/generate-skill.sh --role builder --target codex --output /path/to/project
#   bash tools/generate-skill.sh --client --output .                       # Claude Code（默认）
#   bash tools/generate-skill.sh --client --target codex --output .         # Codex CLI
#   bash tools/generate-skill.sh --client --target cursor --output .        # Cursor IDE
#   bash tools/generate-skill.sh --from-api --api-url http://localhost:8000 --worker-id wa_xxx --project-id prj_xxx --role builder --api-key sk_xxx --output /path/to/project
#   bash tools/generate-skill.sh --check-version --output .                                        # 检查模板是否过期
#   bash tools/generate-skill.sh --upgrade --output . [--api-url <url>] [--worker-id <id>] ...      # 自动升级到最新模板
#
# 源文件: docs/templates/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATES_DIR="$PROJECT_ROOT/docs/templates"

# ─── 参数解析 ───

ROLE=""
TARGET=""
OUTPUT=""
CLIENT_MODE=false
FROM_API=false
CHECK_VERSION=false
UPGRADE_MODE=false
API_URL="${SYNAPSE_API_URL:-}"
WORKER_ID="${SYNAPSE_WORKER_ID:-}"
PROJECT_ID="${SYNAPSE_PROJECT_ID:-}"
API_KEY="${SYNAPSE_API_KEY:-}"
ROLE="${SYNAPSE_ROLE:-}"

usage() {
    echo "用法:"
    echo "  $0 --role <orchestrator|builder|steward> --target <claude|codex> --output <path>"
    echo "  $0 --client [--target <claude|codex|cursor>] --output <path>"
    echo "  $0 --from-api --output <path> [--api-url <url>] [--worker-id <id>] [--project-id <id>] [--role <role>] [--api-key <key>]"
    echo ""
    echo "模式 1 — 项目模板（Admin 为新项目生成 Worker Skill 模板）:"
    echo "  角色:"
    echo "    orchestrator  规划/拆任务/验收/监工"
    echo "    builder       编码/实现/提交验证"
    echo "    steward       挑错/安全/规范审查"
    echo "  客户端:"
    echo "    claude   输出到 .claude/skills/synapse/"
    echo "    codex    输出到 .agents/skills/synapse-{role}/SKILL.md"
    echo ""
    echo "模式 2 — Synapse Client Skill（Agent 即插即用）:"
    echo "  --client  生成薄协议 Skill，一份 canonical base → 多客户端输出"
    echo "  客户端:"
    echo "    claude   输出到 .claude/skills/synapse/SKILL.md + _env.md（默认）"
    echo "    codex    输出到 .agents/skills/synapse/SKILL.md + _env.md"
    echo "    cursor   输出到 .cursor/rules/synapse-worker.mdc（⛔ P12 已废弃 — 零实战数据 · 未安装）"
    echo ""
    echo "模式 3 — API 渲染模式（调用 Synapse Protocol API 获取渲染后的 Skill）:"
    echo "  --from-api  从 Synapse 实例拉取已渲染的协议内容（0 未填充 VAR）"
    echo "  参数（可从环境变量读取）:"
    echo "    --api-url <url>       Synapse 实例地址（或 \$SYNAPSE_API_URL）"
    echo "    --worker-id <id>      Worker ID（或 \$SYNAPSE_WORKER_ID）"
    echo "    --project-id <id>     Project ID（或 \$SYNAPSE_PROJECT_ID）"
    echo "    --role <role>         角色（或 \$SYNAPSE_ROLE）"
    echo "    --api-key <key>       API Key（或 \$SYNAPSE_API_KEY）"
    echo ""
    echo "模式 4 — 模板版本管理（P11-B94 · PFL-084 升级链）:"
    echo "  --check-version  对比本地版本与 Server 版本，exit 0=same 1=stale 2=error"
    echo "  --upgrade        从 Server 拉取最新模板，重新生成 Skill 文件"
    echo "  参数（--upgrade 支持 --from-api 的全部参数）"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --role)       ROLE="$2"; shift 2 ;;
        --target)     TARGET="$2"; shift 2 ;;
        --output)     OUTPUT="$2"; shift 2 ;;
        --client)        CLIENT_MODE=true; shift ;;
        --from-api)      FROM_API=true; shift ;;
        --check-version) CHECK_VERSION=true; shift ;;
        --upgrade)       UPGRADE_MODE=true; shift ;;
        --api-url)    API_URL="$2"; shift 2 ;;
        --worker-id)  WORKER_ID="$2"; shift 2 ;;
        --project-id) PROJECT_ID="$2"; shift 2 ;;
        --api-key)    API_KEY="$2"; shift 2 ;;
        -h|--help)    usage ;;
        *) echo "未知参数: $1"; usage ;;
    esac
done

# ─── 校验 ───

if [[ -z "$OUTPUT" ]]; then
    echo "❌ 缺少必需参数: --output"
    usage
fi

# ── Mode 3: --from-api (mutually exclusive with --client) ──
# --role is allowed with --from-api: it provides a role hint for the
# Protocol API call (line 104 reads it from CLI or SYNAPSE_ROLE env).
if $FROM_API; then
    if $CLIENT_MODE; then
        echo "❌ --from-api 与 --client 互斥"
        exit 1
    fi

    # Resolve params from env vars if not provided on CLI
    API_URL="${API_URL:-${SYNAPSE_API_URL:-}}"
    WORKER_ID="${WORKER_ID:-${SYNAPSE_WORKER_ID:-}}"
    PROJECT_ID="${PROJECT_ID:-${SYNAPSE_PROJECT_ID:-}}"
    ROLE="${ROLE:-${SYNAPSE_ROLE:-}}"
    API_KEY="${API_KEY:-${SYNAPSE_API_KEY:-}}"

    # Validate required params
    MISSING=""
    [[ -z "$API_URL" ]]   && MISSING="$MISSING SYNAPSE_API_URL"
    [[ -z "$WORKER_ID" ]] && MISSING="$MISSING SYNAPSE_WORKER_ID"
    [[ -z "$PROJECT_ID" ]] && MISSING="$MISSING SYNAPSE_PROJECT_ID"
    [[ -z "$ROLE" ]]      && MISSING="$MISSING SYNAPSE_ROLE"
    [[ -z "$API_KEY" ]]   && MISSING="$MISSING SYNAPSE_API_KEY"

    if [[ -n "$MISSING" ]]; then
        echo "❌ --from-api 缺少必需参数（可通过 CLI 参数或环境变量提供）:"
        for m in $MISSING; do
            echo "   缺少: $m"
        done
        echo ""
        echo "示例:"
        echo "  export SYNAPSE_API_URL=http://localhost:8000"
        echo "  export SYNAPSE_WORKER_ID=wa_xxx"
        echo "  export SYNAPSE_PROJECT_ID=prj_xxx"
        echo "  export SYNAPSE_ROLE=builder"
        echo "  export SYNAPSE_API_KEY=sk_xxx"
        echo "  $0 --from-api --output /path/to/output"
        exit 1
    fi

    if [[ ! "$ROLE" =~ ^(orchestrator|builder|steward)$ ]]; then
        echo "❌ 无效角色: ${ROLE}（支持 orchestrator | builder | steward）"
        exit 1
    fi

    # Check dependencies
    if ! command -v curl &>/dev/null; then
        echo "❌ --from-api 需要 curl（未安装）"
        exit 1
    fi
    if ! command -v jq &>/dev/null; then
        echo "❌ --from-api 需要 jq（未安装）"
        exit 1
    fi

# ── Mode 4: --check-version / --upgrade (P11-B94 · PFL-084) ──
elif $CHECK_VERSION || $UPGRADE_MODE; then
    VERSION_FILE="$OUTPUT/.claude/synapse-version.json"

    # Resolve API_URL from env if not provided
    API_URL="${API_URL:-${SYNAPSE_API_URL:-}}"
    if [[ -z "$API_URL" ]]; then
        echo "❌ 需要 SYNAPSE_API_URL（通过 --api-url 或 \$SYNAPSE_API_URL 提供）"
        exit 2
    fi

    VERSIONS_URL="${API_URL%/}/v1/templates/versions"

    # ── Fetch server version ──
    SERVER_RESP=$(curl -sS -w '\n%{http_code}' "$VERSIONS_URL" 2>&1) || {
        echo "❌ 无法连接到 Synapse Server: $API_URL"
        exit 2
    }
    HTTP_CODE=$(echo "$SERVER_RESP" | tail -1)
    SERVER_BODY=$(echo "$SERVER_RESP" | sed '$d')

    if [[ "$HTTP_CODE" != "200" ]]; then
        echo "❌ Server 返回 HTTP ${HTTP_CODE}"
        exit 2
    fi

    SERVER_VERSION=$(echo "$SERVER_BODY" | jq -r '.version // empty')
    if [[ -z "$SERVER_VERSION" ]]; then
        echo "❌ Server 响应缺少 version 字段"
        exit 2
    fi

    # ── Read local version ──
    LOCAL_VERSION=""
    if [[ -f "$VERSION_FILE" ]]; then
        LOCAL_VERSION=$(jq -r '.version // empty' "$VERSION_FILE" 2>/dev/null || true)
    fi

    if $CHECK_VERSION; then
        # ── check-version: compare and exit ──
        if [[ -z "$LOCAL_VERSION" ]]; then
            echo "⚠️  本地无版本记录（${VERSION_FILE} 不存在或无效）"
            echo "Server 版本: ${SERVER_VERSION}"
            exit 1
        fi

        if [[ "$LOCAL_VERSION" == "$SERVER_VERSION" ]]; then
            echo "✅ 模板已是最新（${SERVER_VERSION:0:16}...）"
            exit 0
        else
            echo "⚠️  模板已过期"
            echo "  本地: ${LOCAL_VERSION:0:16}..."
            echo "  Server: ${SERVER_VERSION:0:16}..."
            echo ""
            echo "运行 generate-skill.sh --upgrade 以升级"
            exit 1
        fi
    fi

    if $UPGRADE_MODE; then
        # ── upgrade: compare, regenerate if stale ──
        if [[ -n "$LOCAL_VERSION" && "$LOCAL_VERSION" == "$SERVER_VERSION" ]]; then
            echo "✅ 模板已是最新，无需升级"
            exit 0
        fi

        # Resolve upgrade params
        WORKER_ID="${WORKER_ID:-${SYNAPSE_WORKER_ID:-}}"
        PROJECT_ID="${PROJECT_ID:-${SYNAPSE_PROJECT_ID:-}}"
        ROLE="${ROLE:-${SYNAPSE_ROLE:-}}"
        API_KEY="${API_KEY:-${SYNAPSE_API_KEY:-}}"

        if [[ -z "$WORKER_ID" || -z "$PROJECT_ID" || -z "$ROLE" || -z "$API_KEY" ]]; then
            echo "❌ --upgrade 需要完整的 Worker 凭据（--worker-id --project-id --role --api-key）"
            echo ""
            echo "缺少:"
            [[ -z "$WORKER_ID" ]]  && echo "  SYNAPSE_WORKER_ID"
            [[ -z "$PROJECT_ID" ]] && echo "  SYNAPSE_PROJECT_ID"
            [[ -z "$ROLE" ]]       && echo "  SYNAPSE_ROLE"
            [[ -z "$API_KEY" ]]    && echo "  SYNAPSE_API_KEY"
            exit 2
        fi

        echo ""
        echo "┌──────────────────────────────────────────────┐"
        echo "│  Synapse 模板升级 (P11-B94 · PFL-084)         │"
        if [[ -n "$LOCAL_VERSION" ]]; then
            echo "│  本地: ${LOCAL_VERSION:0:16}... → Server: ${SERVER_VERSION:0:16}... │"
        else
            echo "│  首次部署 → Server: ${SERVER_VERSION:0:16}...           │"
        fi
        echo "└──────────────────────────────────────────────┘"
        echo ""

        # ── Re-run self with --from-api to regenerate ──
        echo "▎ 从 Server 拉取最新模板..."
        "$0" --from-api \
            --api-url "$API_URL" \
            --worker-id "$WORKER_ID" \
            --project-id "$PROJECT_ID" \
            --role "$ROLE" \
            --api-key "$API_KEY" \
            --output "$OUTPUT"

        # ── Write version file ──
        echo "$SERVER_BODY" > "$VERSION_FILE"
        echo ""
        echo "  ✅ .claude/synapse-version.json 已更新"

        echo ""
        echo "✅ 升级完成。"
        echo ""
        echo "⚠️  Skill 文件已更新，建议重启 Claude Code 会话以加载最新指令。"
        echo ""
        echo "验证: 重新运行 generate-skill.sh --check-version --output ${OUTPUT}"
        exit 0
    fi

elif $CLIENT_MODE; then
    # ── Client mode: generate thin protocol Skill ──
    SYNAPSE_CLIENT="$TEMPLATES_DIR/synapse-client/SKILL.md"
    if [[ ! -f "$SYNAPSE_CLIENT" ]]; then
        echo "❌ 源文件不存在: $SYNAPSE_CLIENT"
        exit 1
    fi
    # Default target for client mode is claude（向后兼容）
    if [[ -z "$TARGET" ]]; then
        TARGET="claude"
    fi
    if [[ ! "$TARGET" =~ ^(claude|codex|cursor)$ ]]; then
        echo "❌ 无效客户端: ${TARGET}（支持 claude | codex | cursor）"
        exit 1
    fi
else
    # ── Traditional mode: generate project-specific templates ──
    if [[ -z "$ROLE" || -z "$TARGET" ]]; then
        echo "❌ 缺少必需参数（非 --client 模式需要 --role 和 --target）"
        usage
    fi

    if [[ ! "$ROLE" =~ ^(orchestrator|builder|steward)$ ]]; then
        echo "❌ 无效角色: ${ROLE}（支持 orchestrator | builder | steward）"
        exit 1
    fi

    if [[ ! "$TARGET" =~ ^(claude|codex)$ ]]; then
        echo "❌ 无效客户端: ${TARGET}（支持 claude | codex）"
        exit 1
    fi
fi

if $CLIENT_MODE; then
    # ── Client mode: skip traditional source checks ──
    true
else
    # 源文件
    PROTOCOL="$TEMPLATES_DIR/_protocol.md"
    PROJECT="$TEMPLATES_DIR/_project.md"
    ENV="$TEMPLATES_DIR/_env.md"
    ROLE_FILE="$TEMPLATES_DIR/role-${ROLE}.md"
    TASK_CURRENT="$TEMPLATES_DIR/_task-current.md"

    for f in "$PROTOCOL" "$PROJECT" "$ENV" "$ROLE_FILE" "$TASK_CURRENT"; do
        if [[ ! -f "$f" ]]; then
            echo "❌ 源文件不存在: $f"
            exit 1
        fi
    done
fi

# ─── 工具函数 ───

# 检测未填充的 {{VAR}} 占位符
check_unfilled() {
    local file="$1"
    grep -n '{{[A-Z_][A-Z_]*}}' "$file" 2>/dev/null || true
}

# ─── Claude Code 输出 ───

generate_claude() {
    local OUT_DIR="$OUTPUT/.claude/skills/synapse"
    mkdir -p "$OUT_DIR"

    echo "▎ Claude Code → $OUT_DIR"

    cp "$ENV"           "$OUT_DIR/_env.md"
    cp "$PROTOCOL"      "$OUT_DIR/_protocol.md"
    cp "$PROJECT"       "$OUT_DIR/_project.md"
    cp "$ROLE_FILE"     "$OUT_DIR/role-${ROLE}.md"
    cp "$TASK_CURRENT"  "$OUT_DIR/_task-current.md"

    echo "  ✅ _env.md"
    echo "  ✅ _protocol.md"
    echo "  ✅ _project.md"
    echo "  ✅ role-${ROLE}.md"
    echo "  ✅ _task-current.md"

    # ── L2b: 复制约定文件（按技术栈）──
    local CONVENTIONS_FRONTEND="$TEMPLATES_DIR/conventions-frontend.md"
    local CONVENTIONS_BACKEND="$TEMPLATES_DIR/conventions-backend.md"
    if [[ -f "$CONVENTIONS_FRONTEND" ]]; then
        cp "$CONVENTIONS_FRONTEND" "$OUT_DIR/conventions-frontend.md"
        echo "  ✅ conventions-frontend.md"
    fi
    if [[ -f "$CONVENTIONS_BACKEND" ]]; then
        cp "$CONVENTIONS_BACKEND" "$OUT_DIR/conventions-backend.md"
        echo "  ✅ conventions-backend.md"
    fi

    # ── P100-B96: 复制 scripts/ 目录（Node.js Worker 工具）──
    local SCRIPTS_SRC="$TEMPLATES_DIR/synapse-client/scripts"
    if [[ -d "$SCRIPTS_SRC" ]]; then
        rm -rf "$OUT_DIR/scripts"
        cp -r "$SCRIPTS_SRC" "$OUT_DIR/scripts"
        echo "  ✅ scripts/ (api-client + keychain + heartbeat)"
    fi

    # 检查未填充变量
    local WARNINGS=0
    for f in "$OUT_DIR"/*.md; do
        local unfilled
        unfilled=$(check_unfilled "$f")
        if [[ -n "$unfilled" ]]; then
            WARNINGS=$((WARNINGS + 1))
            while IFS= read -r line; do
                echo "  ⚠️  $(basename "$f"):$line"
            done <<< "$unfilled"
        fi
    done

    if [[ $WARNINGS -gt 0 ]]; then
        echo ""
        echo "⚠️  发现 $WARNINGS 个文件含未填充的 {{VAR}} 占位符。"
        echo "   请编辑上述文件，将 {{...}} 替换为实际值。"
    fi

    # ── B111 PFL-111: Generate Worker CLAUDE.md (role anchor) ──
    write_claude_md "$OUTPUT" "$ROLE" "claude"

    # ── P12-B3: Generate launchd plist (macOS daemon persistence) ──
    write_launchd_plist "$OUTPUT" "$ROLE"

    # ── B110 Layer 3: Generate SessionStart hook + permissions ──
    write_settings_json "$OUTPUT"
    write_settings_local "$OUTPUT"
}

# ─── Codex 输出 ───

generate_codex() {
    local OUT_DIR="$OUTPUT/.agents/skills/synapse-${ROLE}"
    mkdir -p "$OUT_DIR"

    local SKILL_FILE="$OUT_DIR/SKILL.md"

    echo "▎ Codex CLI → $OUT_DIR"

    # 角色描述映射
    local ROLE_DESC
    case "$ROLE" in
        orchestrator) ROLE_DESC="规划任务、拆解需求、写验收条件、验收交付物、监控进度——定义'做完'长什么样" ;;
        builder)      ROLE_DESC="编码实现、执行任务、收集验证证据、提交验证——把任务做成" ;;
        steward)      ROLE_DESC="代码审查、安全检查、规范审计、边界条件探测——独立复核，质量防线" ;;
    esac

    # 写入 SKILL.md（YAML frontmatter + 合并内容）
    cat > "$SKILL_FILE" <<EOF
---
name: synapse-${ROLE}
description: Synapse ${ROLE} Worker — ${ROLE_DESC}. 当需要执行 Synapse 协调平台上的 ${ROLE} 任务时使用。
---

EOF

    # 合并内容
    echo "<!-- 以下内容合并自 _protocol.md + _project.md + role-${ROLE}.md + _task-current.md -->" >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"

    cat "$PROTOCOL"      >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"
    echo "---" >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"
    cat "$PROJECT"       >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"
    echo "---" >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"
    cat "$ROLE_FILE"     >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"
    echo "---" >> "$SKILL_FILE"
    echo "" >> "$SKILL_FILE"
    cat "$TASK_CURRENT"  >> "$SKILL_FILE"

    echo "  ✅ SKILL.md（合并: _protocol + _project + role-${ROLE} + _task-current）"

    # 同时复制 _env.md（Codex 需要单独配置环境变量）
    cp "$ENV" "$OUT_DIR/_env.md"
    echo "  ✅ _env.md"

    # ── B100-A3: Copy scripts/ (Codex traditional mode) ──
    copy_scripts "$OUT_DIR"

    # 检查未填充变量
    local unfilled
    unfilled=$(check_unfilled "$SKILL_FILE")
    if [[ -n "$unfilled" ]]; then
        echo ""
        while IFS= read -r line; do
            echo "  ⚠️  SKILL.md:$line"
        done <<< "$unfilled"
        echo "⚠️  发现未填充的 {{VAR}} 占位符。请编辑 SKILL.md，将 {{...}} 替换为实际值。"
    fi
}

# ─── 共享工具：生成 _env.md ───

write_client_env() {
    local OUT_DIR="$1"
    cat > "$OUT_DIR/_env.md" <<'ENVEOF'
# Synapse Worker 环境配置

> Agent 启动前配置以下 3 个环境变量。项目上下文通过 B21 Protocol API 在运行时拉取。

## 🫵 Your Identity（P11-B129 · PFL-124 修复）

> 🚨 **This is YOUR identity on the Synapse platform.**
>
> Your Worker ID is **`{{SYNAPSE_WORKER_ID}}`**. When you see this ID anywhere —
> in a task's `owner_id`, in an API response, in a log message — **that means YOU**.
> There is no "other Worker" with this ID. This is your unique identifier.
>
> **PFL-124 lesson**: Builder saw `owner_id` matching its own Worker ID and reported
> "another Worker claimed this task." The Worker failed to recognize itself.
> Know your ID. Own your tasks.

## 必需变量

| 变量 | 说明 | 获取方式 |
|------|------|----------|
| `SYNAPSE_API_URL` | Synapse 实例地址 | 向 Admin 索取，如 `http://localhost:8000` |
| `SYNAPSE_API_KEY` | Agent API Key | Admin 创建 Agent 时一次性返回，妥善保管 |
| `SYNAPSE_WORKER_ID` | 你的 Worker ID | Admin 创建 Agent 时返回，格式 `wa_xxxxxxxx` |

## 可选变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SYNAPSE_PROJECT_ID` | 默认 Project ID | 可在 API 调用时通过 `?project_id=` 覆盖 |
| `SYNAPSE_WORKER_ROLE` | 角色标识 | `builder` / `orchestrator` / `steward` · `session-init.js` 用此区分角色行为 |

## 配置方式

```bash
export SYNAPSE_API_URL="http://localhost:8000"
export SYNAPSE_API_KEY="sk-syn-..."
export SYNAPSE_WORKER_ID="wa_xxxxxxxx"
export SYNAPSE_PROJECT_ID="prj_xxxxxxxx"
export SYNAPSE_WORKER_ROLE="builder"   # 或 "orchestrator" / "steward"
```

> ⚠️ 不要将 API Key 提交到版本控制。建议使用 `.env` 文件（已加入 `.gitignore`）。
ENVEOF
}

# 验证输出不含未填充变量
verify_client_output() {
    local FILE="$1"
    local LABEL="$2"
    local unfilled
    unfilled=$(check_unfilled "$FILE")
    if [[ -n "$unfilled" ]]; then
        echo ""
        while IFS= read -r line; do
            echo "  ⚠️  ${LABEL}:$line"
        done <<< "$unfilled"
        echo "⚠️  ${LABEL} 含未填充变量——这不应该发生（Client Skill 是静态协议）。"
    else
        echo "  ✅ 无未填充变量（纯协议，0 占位符）"
    fi
}

# ── 共享工具：复制 scripts/ 目录 ──

# B100: 从模板源复制 Node.js Worker 脚本到输出目录。
# 所有客户端模式都应调用此函数以避免 B100-A2/A3 覆盖盲区。
copy_scripts() {
    local DEST_DIR="$1"
    local SCRIPTS_SRC="$TEMPLATES_DIR/synapse-client/scripts"
    local LABEL="${2:-scripts/}"
    if [[ -d "$SCRIPTS_SRC" ]]; then
        rm -rf "$DEST_DIR/scripts"
        cp -r "$SCRIPTS_SRC" "$DEST_DIR/scripts"
        echo "  ✅ ${LABEL} (api-client + keychain + heartbeat + session-init)"
    fi
}

# ─── 共享工具：生成 Worker 根目录 CLAUDE.md ───
#
# P11-B111 PFL-111: Bootstrap/generate-skill 必须生成 Worker CLAUDE.md。
# 根因: 没有 CLAUDE.md → Claude Code 把 SKILL.md 当参考文档而非执行指令 →
#       Worker 冷启动后"卡住"，等人类 prompt。
# 修复: setup/bootstrap 阶段在 Worker 根目录写入角色锚点 CLAUDE.md，
#       含启动协议 + 铁律，让 Worker 知道自己该主动干活。
#
# 幂等: 如果 CLAUDE.md 已存在则跳过，不覆盖用户手动定制。

write_claude_md() {
    local WORKER_ROOT="$1"
    local ROLE="${2:-}"
    local TARGET="${3:-claude}"  # P11-B119 PFL-121: target 区分协议文件引用

    local CLAUDE_FILE="$WORKER_ROOT/CLAUDE.md"

    if [[ -f "$CLAUDE_FILE" ]]; then
        echo "  ⏭️  CLAUDE.md (already exists — skipping)"
        return
    fi

    # P11-B119 PFL-121: Claude 模式不生成 SKILL.md（分散为 _protocol + role-{ROLE}）
    local PROTOCOL_STEP
    if [[ "$TARGET" == "claude" ]]; then
        PROTOCOL_STEP="3. 读 \`.claude/skills/synapse/_protocol.md\` + \`.claude/skills/synapse/role-${ROLE}.md\` — 完整角色协议（含 VDD 循环、API 端点、异常处理）"
    else
        PROTOCOL_STEP="3. 读 \`.claude/skills/synapse/SKILL.md\` — 完整角色协议（含 VDD 循环、API 端点、异常处理）"
    fi

    local ROLE_DESC IRON_RULES

    case "$ROLE" in
        orchestrator)
            ROLE_DESC="拆解需求、分配任务、写验收条件、验收交付物 — 定义\"做完\"长什么样"
            IRON_RULES=$(cat <<'EOF'
- 不要写代码 — 你的工作是拆解、分配、验收
- 不要认领 task — 那是 Builder 的工作
- 每次判断前先调 API 获取最新状态（`_task-current.md` 只是启动快照）
- 退出前必须调 ScheduleWakeup 设闹钟让自己回来
- 收到需求先 challenge — 模糊不清的需求必须先追问澄清，不清晰绝不拆解
- 空闲时（无待验收+无待分配+无进行中）→ 主动向 Human 打招呼："Orchestrator 空闲中，喂我需求"
EOF
)
            ;;
        builder)
            ROLE_DESC="编码实现、执行任务、收集验证证据、提交验证 — 把任务做成"
            IRON_RULES=$(cat <<'EOF'
- 你的工作是编码实现，不是拆解任务 — 那是 Orchestrator 的活
- 完成任务后调 submit_task 提交验证，不要等别人来问
- 遇到阻塞不要静默卡住 → 调 API 查状态 → 在 Task 评论区 @Orchestrator
- 每次判断前先调 API 获取最新状态（`_task-current.md` 只是启动快照）
- 退出前必须调 ScheduleWakeup 设闹钟让自己回来
EOF
)
            ;;
        steward)
            ROLE_DESC="代码审查、安全检查、规范审计、边界条件探测 — 独立复核，质量防线"
            IRON_RULES=$(cat <<'EOF'
- 你的工作是审查和挑错，不是写实现 — 那是 Builder 的活
- 审查完成后在评论区报告发现，不要直接改代码
- 每次判断前先调 API 获取最新状态
- 退出前必须调 ScheduleWakeup 设闹钟让自己回来
EOF
)
            ;;
        *)
            ROLE_DESC="Synapse Worker — 启动后通过 Protocol API 确定具体角色"
            # P11-B119 PFL-121: 默认角色也按 target 区分协议文件引用
            local DEFAULT_PROTOCOL_REF
            if [[ "$TARGET" == "claude" ]]; then
                DEFAULT_PROTOCOL_REF="- 启动后立即读 \`.claude/skills/synapse/_protocol.md\` + \`.claude/skills/synapse/role-${ROLE}.md\`（若存在）了解完整协议"
            else
                DEFAULT_PROTOCOL_REF="- 启动后立即读 \`.claude/skills/synapse/SKILL.md\` 了解完整协议"
            fi
            IRON_RULES=$(cat <<EOF
${DEFAULT_PROTOCOL_REF}
- 每次判断前先调 API 获取最新状态（\`_task-current.md\` 只是启动快照）
- 退出前必须调 ScheduleWakeup 设闹钟让自己回来
EOF
            )
            ;;
    esac

    cat > "$CLAUDE_FILE" << CLAUDEEOF
# Synapse ${ROLE} Worker

你是 Synapse 平台上的 **${ROLE}** Worker。${ROLE_DESC}。

**冷启动**：每次打开新窗口时，人类输入 \`@_boot-prompt.md\` 即可一键启动。
此后 CronCreate + ScheduleWakeup 会保持你在线，无需再次手动启动。

**启动时严格按以下顺序执行：**

0. 如果这是冷启动（新窗口），确认人类已输入 \`@_boot-prompt.md\` — 该文件由 session-init.js 每次 SessionStart 自动刷新
1. 读 \`.claude/skills/synapse/_task-current.md\` — 当前任务快照
2. 执行 FIRST ACTION banner 中的 CronCreate 指令
${PROTOCOL_STEP}
4. 按角色指令进入工作循环

**铁律：**
${IRON_RULES}

> ⚠️ 本文件由 generate-skill.sh 自动生成（B111 PFL-111 修复 · B112 _boot-prompt.md 冷启动 · B119 PFL-121 路径修复）。
> 如需永久定制，删除此注释后脚本将在后续运行时跳过此文件。
CLAUDEEOF

    echo "  ✅ CLAUDE.md (${ROLE} Worker 角色锚点 · B111 PFL-111 · B112 _boot-prompt · B119 PFL-121 target=${TARGET})"
}

# ─── 共享工具：生成 SessionStart hook ───

# ─── 共享工具：生成 per-Worker settings.local.json ───
#
# B110 Layer 3: 在 Worker setup 时直接生成权限文件，消除鸡生蛋问题。
# 之前的流程: SessionStart hook → session-init.js → ensureWorkerSettings()
# 问题: 如果 root settings.local.json 阻止 SessionStart hook 执行，session-init.js
#       永远不会运行，per-Worker settings.local.json 永远不会生成，Worker 永久死锁。
# 修复: generate-skill.sh 在 setup 阶段直接生成，不依赖任何脚本运行。
#
# 此函数与 session-init.js 的 ensureWorkerSettings() 是 belt-and-suspenders 关系:
#   - generate-skill.sh: 治本 — setup 时创建 (不依赖任何东西运行)
#   - session-init.js:   兜底 — 如果文件被删除则在下次 SessionStart 重建
#
# 幂等: 如果 settings.local.json 已存在则跳过，不覆盖用户手动定制。

write_settings_local() {
    local WORKER_ROOT="$1"
    local SETTINGS_FILE="$WORKER_ROOT/.claude/settings.local.json"

    if [[ -f "$SETTINGS_FILE" ]]; then
        echo "  ⏭️  .claude/settings.local.json (already exists — skipping)"
        return
    fi

    # Resolve absolute paths for Read permissions
    local ABS_WORKER
    ABS_WORKER="$(cd "$WORKER_ROOT" 2>/dev/null && pwd)" || ABS_WORKER="$WORKER_ROOT"

    # Synapse shared dir: only add if it exists as a sibling
    local SYNAPSE_ENTRY=""
    if [[ -d "$WORKER_ROOT/../synapse" ]]; then
        local ABS_SYNAPSE
        ABS_SYNAPSE="$(cd "$WORKER_ROOT/../synapse" 2>/dev/null && pwd)" || true
        if [[ -n "$ABS_SYNAPSE" && "$ABS_SYNAPSE" != "/" ]]; then
            SYNAPSE_ENTRY="\"Read(${ABS_SYNAPSE}/**)\","
        fi
    fi

    local HOME_DIR="$HOME"

    if [[ -n "$SYNAPSE_ENTRY" ]]; then
    cat > "$SETTINGS_FILE" << SETEOF
{
  "permissions": {
    "allow": [
      "Read(${ABS_WORKER}/**)",
      ${SYNAPSE_ENTRY}
      "Read(${HOME_DIR}/.claude/**)",
      "Bash(curl -s *)",
      "Bash(set -a; . ./.claude/.env; set +a; node .claude/skills/synapse/scripts/*)",
      "Bash(node .claude/skills/synapse/scripts/*)",
      "Bash(echo *)",
      "Bash(cat *)",
      "Bash(ls *)",
      "Bash(grep *)",
      "Bash(find *)",
      "Bash(which *)",
      "Bash(git *)",
      "Bash(env)",
      "Bash(source .claude/.env *)",
      "Bash(python3 -c *)",
      "Bash(python3 -m json.tool)",
      "Bash(security find-generic-password *)",
      "CronCreate",
      "ScheduleWakeup",
      "Skill(synapse)"
    ]
  }
}
SETEOF
    else
    cat > "$SETTINGS_FILE" << SETEOF
{
  "permissions": {
    "allow": [
      "Read(${ABS_WORKER}/**)",
      "Read(${HOME_DIR}/.claude/**)",
      "Bash(curl -s *)",
      "Bash(set -a; . ./.claude/.env; set +a; node .claude/skills/synapse/scripts/*)",
      "Bash(node .claude/skills/synapse/scripts/*)",
      "Bash(echo *)",
      "Bash(cat *)",
      "Bash(ls *)",
      "Bash(grep *)",
      "Bash(find *)",
      "Bash(which *)",
      "Bash(git *)",
      "Bash(env)",
      "Bash(source .claude/.env *)",
      "Bash(python3 -c *)",
      "Bash(python3 -m json.tool)",
      "Bash(security find-generic-password *)",
      "CronCreate",
      "ScheduleWakeup",
      "Skill(synapse)"
    ]
  }
}
SETEOF
    fi

    echo "  ✅ .claude/settings.local.json (Worker permissions · B110 Layer 3)"
}

# ─── 共享工具：生成 SessionStart hook ───

write_settings_json() {
    local CLIENT_ROOT="$1"
    local CLAUDE_DIR="$CLIENT_ROOT/.claude"
    local SETTINGS_FILE="$CLAUDE_DIR/settings.json"

    mkdir -p "$CLAUDE_DIR"

    if [[ -f "$SETTINGS_FILE" ]]; then
        # 已有 settings.json，合并 hook（用 python 处理 JSON）
        # P11-B83 PFL-076: 升级为合并单 hook 新格式 + . 替代 source
        python3 -c "
import json, sys
with open('$SETTINGS_FILE') as f:
    cfg = json.load(f)
cfg.setdefault('hooks', {})
hooks = cfg['hooks'].setdefault('SessionStart', [])
# PFL-076/B115: always upgrade to current command (no heartbeat.js &)
NEW_CMD = 'set -a; . ./.claude/.env; set +a; node ./.claude/skills/synapse/scripts/session-init.js'
has_synapse = False
for h in hooks:
    if 'command' in h and 'session-init.js' in h.get('command',''):
        h['hooks'] = [{'type': 'command', 'command': NEW_CMD}]
        h.pop('command', None)
        h.pop('matcher', None)
        has_synapse = True
    if 'hooks' in h:
        for c in h['hooks']:
            if 'session-init.js' in c.get('command',''):
                c['command'] = NEW_CMD  # B115: always upgrade
                has_synapse = True
if not has_synapse:
    hooks.append({
        'matcher': '',
        'hooks': [{'type': 'command', 'command': NEW_CMD}]
    })
with open('$SETTINGS_FILE', 'w') as f:
    json.dump(cfg, f, indent=2)
    f.write('\\n')
"
    else
        # 首次创建
        # P11-B83 PFL-076: 单 hook 新格式 + . 替代 source + 合并命令（避免 env 隔离）
        cat > "$SETTINGS_FILE" << 'SETEOF'
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "set -a; . ./.claude/.env; set +a; node ./.claude/skills/synapse/scripts/session-init.js"
          }
        ]
      }
    ]
  }
}
SETEOF
    fi

    echo "  ✅ .claude/settings.json（SessionStart → .env + session-init · PFL-076/B115）"
}

# ── P12-B3: Launchd plist generation (macOS only) ──────────────────────
# Generates a launchd plist for daemon persistence. Does NOT auto-install —
# the user must run synapse-launchd.sh install manually.
# Only runs on macOS (uname -s = Darwin). On Linux, prints a systemd pointer.

write_launchd_plist() {
    local OUT_DIR="$1"
    local ROLE="${2:-}"

    # Skip if role is unknown (client mode without --role flag)
    if [[ -z "$ROLE" ]] || [[ ! "$ROLE" =~ ^(orchestrator|builder)$ ]]; then
        echo "  ℹ️  launchd plist skipped — role unknown (use --role to specify)"
        return 0
    fi

    # macOS check
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "  ℹ️  launchd not available on $(uname -s) — skipping plist generation"
        echo "     (Linux: use systemd user unit — P13)"
        return 0
    fi

    # Find the launchd script
    local LAUNCHD_SCRIPT="$SCRIPT_DIR/synapse-launchd.sh"
    if [[ ! -f "$LAUNCHD_SCRIPT" ]]; then
        echo "  ⚠️  synapse-launchd.sh not found — skipping plist generation"
        return 0
    fi

    # Generate plist to LaunchAgents/ directory in output
    local PLIST_DIR="$OUT_DIR/LaunchAgents"
    mkdir -p "$PLIST_DIR"
    local PLIST_FILE="$PLIST_DIR/com.synapse.worker-${ROLE}.plist"

    # Use the launchd script's plist subcommand for canonical generation
    local plist_err
    plist_err="$(bash "$LAUNCHD_SCRIPT" plist "$OUT_DIR" "$ROLE" > "$PLIST_FILE" 2>&1)"
    if [[ $? -eq 0 ]] && [[ -s "$PLIST_FILE" ]]; then
        echo "  ✅ LaunchAgents/com.synapse.worker-${ROLE}.plist（launchd daemon — P12-B3）"
        echo ""
        echo "  ┌─────────────────────────────────────────────────────────────┐"
        echo "  │  🚀 launchd daemon plist generated. To activate:            │"
        echo "  │                                                             │"
        echo "  │  bash tools/synapse-launchd.sh install ${OUT_DIR} ${ROLE}   │"
        echo "  │                                                             │"
        echo "  │  This keeps session-init.js --health running every 60s,     │"
        echo "  │  independent of Claude Code /clear, exit, or restart.       │"
        echo "  └─────────────────────────────────────────────────────────────┘"
        echo ""
    else
        echo "  ⚠️  plist generation failed: ${plist_err}"
        echo "     Run manually: bash tools/synapse-launchd.sh install ${OUT_DIR} ${ROLE}"
    fi
}

# ─── Client Skill: Claude Code ───

generate_client_claude() {
    local OUT_DIR="$OUTPUT/.claude/skills/synapse"
    mkdir -p "$OUT_DIR"

    echo "▎ Claude Code → $OUT_DIR"

    cp "$SYNAPSE_CLIENT" "$OUT_DIR/SKILL.md"
    echo "  ✅ SKILL.md（Synapse Worker 协议）"

    write_client_env "$OUT_DIR"
    echo "  ✅ _env.md（3 个必需环境变量）"

    # ── P100-B96: 复制 scripts/ 目录（Node.js Worker 工具）──
    local SCRIPTS_SRC="$TEMPLATES_DIR/synapse-client/scripts"
    if [[ -d "$SCRIPTS_SRC" ]]; then
        rm -rf "$OUT_DIR/scripts"
        cp -r "$SCRIPTS_SRC" "$OUT_DIR/scripts"
        echo "  ✅ scripts/ (api-client + keychain + heartbeat)"
    fi

    write_settings_json "$OUTPUT"
    write_settings_local "$OUTPUT"

    # ── B111 PFL-111: Generate Worker CLAUDE.md ──
    # Client mode may not have --role; try env var, fall back to generic
    local CLIENT_ROLE="${ROLE:-${SYNAPSE_WORKER_ROLE:-}}"
    write_claude_md "$OUTPUT" "$CLIENT_ROLE" "$TARGET"

    # ── P12-B3: Generate launchd plist (macOS daemon persistence) ──
    write_launchd_plist "$OUTPUT" "$CLIENT_ROLE"

    verify_client_output "$OUT_DIR/SKILL.md" "SKILL.md"
}

# ─── Client Skill: Codex CLI ───

generate_client_codex() {
    local OUT_DIR="$OUTPUT/.agents/skills/synapse"
    mkdir -p "$OUT_DIR"

    echo "▎ Codex CLI → $OUT_DIR"

    cp "$SYNAPSE_CLIENT" "$OUT_DIR/SKILL.md"
    echo "  ✅ SKILL.md（Synapse Worker 协议 · name=synapse → 目录名匹配）"

    write_client_env "$OUT_DIR"
    echo "  ✅ _env.md（3 个必需环境变量）"

    # ── B100-A3: Copy scripts/ (Codex client mode) ──
    copy_scripts "$OUT_DIR"

    verify_client_output "$OUT_DIR/SKILL.md" "SKILL.md"
}

# ─── Client Skill: Cursor IDE ───

generate_client_cursor() {
    local OUT_DIR="$OUTPUT/.cursor/rules"
    mkdir -p "$OUT_DIR"
    local RULES_FILE="$OUT_DIR/synapse-worker.mdc"

    echo "▎ Cursor IDE → $OUT_DIR"

    # 从 canonical base 提取 description
    local DESC
    DESC=$(grep '^description:' "$SYNAPSE_CLIENT" | head -1 | sed 's/^description: *//')

    # 写 Cursor rules frontmatter（description + alwaysApply，无 name 字段）
    cat > "$RULES_FILE" <<CURSOREOF
---
description: ${DESC}
alwaysApply: true
---

CURSOREOF

    # 追加 body（跳过源文件的 YAML frontmatter 块）
    awk 'BEGIN {in_fm=0; fm_done=0}
         /^---$/ { if (!in_fm) { in_fm=1; next } else if (in_fm && !fm_done) { fm_done=1; in_fm=0; next } }
         fm_done { print }' "$SYNAPSE_CLIENT" >> "$RULES_FILE"

    # 追加环境配置段
    cat >> "$RULES_FILE" <<'CURSOREOF'

---

## 环境配置

> Agent 启动前配置以下 3 个环境变量。项目上下文通过 B21 Protocol API 在运行时拉取。

### 必需变量

| 变量 | 说明 | 获取方式 |
|------|------|----------|
| `SYNAPSE_API_URL` | Synapse 实例地址 | 向 Admin 索取，如 `http://localhost:8000` |
| `SYNAPSE_API_KEY` | Agent API Key | Admin 创建 Agent 时一次性返回，妥善保管 |
| `SYNAPSE_WORKER_ID` | 你的 Worker ID | Admin 创建 Agent 时返回，格式 `wa_xxxxxxxx` |

### 可选变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SYNAPSE_PROJECT_ID` | 默认 Project ID | 可在 API 调用时通过 `?project_id=` 覆盖 |

```bash
export SYNAPSE_API_URL="http://localhost:8000"
export SYNAPSE_API_KEY="sk-syn-..."
export SYNAPSE_WORKER_ID="wa_xxxxxxxx"
export SYNAPSE_PROJECT_ID="prj_xxxxxxxx"
```

> ⚠️ 不要将 API Key 提交到版本控制。建议使用 `.env` 文件（已加入 `.gitignore`）。

> 💡 Cursor 在每次会话中自动加载此规则文件（`alwaysApply: true`）。配置好环境变量后，Agent 启动时通过 B21 Protocol API 拉取项目上下文。
CURSOREOF

    echo "  ✅ synapse-worker.mdc（Cursor rules · alwaysApply: true · env 已内联）"

    # ── B100-A3: Copy scripts/ (Cursor — .cursor/scripts/) ──
    copy_scripts "$OUTPUT/.cursor" "scripts/ (Cursor)"

    verify_client_output "$RULES_FILE" "synapse-worker.mdc"
}

# ─── Mode 3: API-rendered Skill ──────────────────────────────────────

generate_from_api() {
    local PROTOCOL_URL="${API_URL%/}/v1/workers/${WORKER_ID}/protocol?project_id=${PROJECT_ID}&role=${ROLE}"

    echo ""
    echo "┌──────────────────────────────────────────────┐"
    echo "│  Synapse Skill 包生成器 — API 渲染模式        │"
    echo "│  API: ${API_URL}                              │"
    echo "│  Worker: ${WORKER_ID}                         │"
    echo "│  Project: ${PROJECT_ID}                       │"
    echo "│  角色: ${ROLE}                                │"
    echo "│  输出: ${OUTPUT}                              │"
    echo "└──────────────────────────────────────────────┘"
    echo ""

    # ── Call Protocol API ──
    echo "▎ 调用 Protocol API..."
    local RESP
    RESP=$(curl -sS -w '\n%{http_code}' \
        -H "Authorization: Bearer ${API_KEY}" \
        "$PROTOCOL_URL" 2>&1) || {
        echo "❌ API 调用失败: curl 错误"
        echo "   URL: $PROTOCOL_URL"
        exit 1
    }

    # Extract HTTP status code (last line)
    local HTTP_CODE
    HTTP_CODE=$(echo "$RESP" | tail -1)
    local BODY
    BODY=$(echo "$RESP" | sed '$d')

    if [[ "$HTTP_CODE" != "200" ]]; then
        echo "❌ API 返回错误 (HTTP ${HTTP_CODE})"
        echo "$BODY" | jq -r '.detail // . // empty' 2>/dev/null || echo "$BODY"
        exit 1
    fi

    echo "  ✅ 协议数据已获取"

    # ── Extract rendered fields ──
    local PROJECT_CTX COLLAB ROLE_INST ENV_TMPL UNFILLED
    PROJECT_CTX=$(echo "$BODY" | jq -r '.project_context')
    COLLAB=$(echo "$BODY" | jq -r '.collaboration_norms')
    ROLE_INST=$(echo "$BODY" | jq -r '.role_instructions')
    ENV_TMPL=$(echo "$BODY" | jq -r '.env_template')
    UNFILLED=$(echo "$BODY" | jq -r '.unfilled_variables | join(", ")')

    if [[ -z "$PROJECT_CTX" || "$PROJECT_CTX" == "null" ]]; then
        echo "❌ API 返回的 project_context 为空"
        exit 1
    fi

    # ── Write rendered files ──
    echo ""
    echo "▎ 写入渲染后的 Skill 文件 → $OUTPUT"

    echo "$PROJECT_CTX" > "$OUTPUT/_project.md"
    echo "  ✅ _project.md（已渲染 · 0 未填充 VAR）"

    echo "$COLLAB" > "$OUTPUT/_protocol.md"
    echo "  ✅ _protocol.md（已渲染 · 0 未填充 VAR）"

    echo "$ROLE_INST" > "$OUTPUT/role-${ROLE}.md"
    echo "  ✅ role-${ROLE}.md（已渲染 · 0 未填充 VAR）"

    echo "$ENV_TMPL" > "$OUTPUT/_env.md"
    echo "  ✅ _env.md（已渲染）"

    # ── Copy static convention files ──
    local CONVENTIONS_FRONTEND="$TEMPLATES_DIR/conventions-frontend.md"
    local CONVENTIONS_BACKEND="$TEMPLATES_DIR/conventions-backend.md"
    if [[ -f "$CONVENTIONS_FRONTEND" ]]; then
        cp "$CONVENTIONS_FRONTEND" "$OUTPUT/conventions-frontend.md"
        echo "  ✅ conventions-frontend.md"
    fi
    if [[ -f "$CONVENTIONS_BACKEND" ]]; then
        cp "$CONVENTIONS_BACKEND" "$OUTPUT/conventions-backend.md"
        echo "  ✅ conventions-backend.md"
    fi

    # ── B100-A2: Copy scripts/ (SessionStart hooks reference them) ──
    mkdir -p "$OUTPUT/.claude/skills/synapse"
    copy_scripts "$OUTPUT/.claude/skills/synapse"

    # ── Write _task-current.md with guidance ──
    cat > "$OUTPUT/_task-current.md" <<'TASKEOP'
# 当前任务

> ⚠️ 此文件为手动填写模板。Task 级变量（TASK_ID / TASK_TITLE / TASK_PRIORITY / TASK_EFFORT / TASK_VERIFICATIONS / TASK_CONTEXT）无法在 Project 层面解析——它们属于具体的 Task assignment。
>
> 一期使用时，Admin 根据实际分配的 Task 填写以下字段。二期将由 Synapse handshake API 自动返回当前 Task。

---

## 当前活跃 Task

| 字段 | 值 |
|------|-----|
| Task ID | `请填写 Task ID（如 task_xxx）` |
| 标题 | `请填写 Task 标题` |
| 优先级 | `请填写（high / medium / low）` |
| 预估 effort | `请填写（如 2h / 1d）` |

## Verification 条件（合同）

请列出此 Task 的 Verification 条件——每条必须是机器可判定的。

示例：
- `pytest tests/test_xxx.py -v` 全部通过
- `make check` 零新增告警
- `cd frontend && npm run build` 通过

## 关联上下文

请填写与当前 Task 相关的额外上下文（关联 PR、设计文档、依赖的 Task 等）。
TASKEOP
    echo "  ✅ _task-current.md（模板 · 含手动填写指引）"

    # ── B100-A10: Generate SKILL.md glue file ──
    # from-api mode outputs 4 independent rendered files but needs a SKILL.md
    # entry point so Claude Code recognises this as a Skill directory.
    cat > "$OUTPUT/SKILL.md" <<SKILLEOF
---
name: synapse-${ROLE}
description: Synapse ${ROLE} Worker — API-rendered skill for project ${PROJECT_ID}
---

# Synapse Worker — ${ROLE}

> API-rendered by \`generate-skill.sh --from-api\` at $(date -u +%Y-%m-%dT%H:%M:%SZ)
> Source: ${API_URL} · Worker: ${WORKER_ID} · Project: ${PROJECT_ID}

## 项目上下文

参见 [\_project.md](./_project.md)

## 协作协议

参见 [\_protocol.md](./_protocol.md)

## 角色指令

参见 [role-${ROLE}.md](./role-${ROLE}.md)

## 环境配置

参见 [\_env.md](./_env.md)

## 当前任务

参见 [\_task-current.md](./_task-current.md)
SKILLEOF
    echo "  ✅ SKILL.md（胶水文件 · 索引 5 个渲染片段）"

    # ── Report unfilled vars ──
    if [[ -n "$UNFILLED" && "$UNFILLED" != "null" && "$UNFILLED" != "" ]]; then
        echo ""
        echo "⚠️  API 报告以下变量未解析: ${UNFILLED}"
        echo "   这些通常是 Task 级变量（TASK_ID/TASK_TITLE/...），需在 _task-current.md 中手动填写。"
    fi

    # ── B111 PFL-111: Generate Worker CLAUDE.md ──
    write_claude_md "$OUTPUT" "$ROLE" "$TARGET"

    # ── P12-B3: Generate launchd plist (macOS daemon persistence) ──
    write_launchd_plist "$OUTPUT" "$ROLE"

    # ── Generate SessionStart hook ──
    write_settings_json "$OUTPUT"
    write_settings_local "$OUTPUT"

    echo ""
    echo "✅ 完成。Skill 文件已渲染，0 未填充 VAR（Task 级除外）。"
    echo ""
    echo "下一步:"
    echo "  1. 编辑 _task-current.md 填写当前 Task 信息"
    echo "  2. 配置环境变量（参见 _env.md）"
    echo "  3. Agent 启动 → 自动加载 Skill 文件"
}

# ─── 执行 ───

if $FROM_API; then
    generate_from_api
elif $CLIENT_MODE; then
    # 客户端标签映射
    CLIENT_LABEL=""
    case "$TARGET" in
        claude) CLIENT_LABEL="Claude Code" ;;
        codex)  CLIENT_LABEL="Codex CLI" ;;
        cursor) CLIENT_LABEL="Cursor IDE" ;;
    esac

    echo ""
    echo "┌──────────────────────────────────────────────┐"
    echo "│  Synapse Skill 包生成器 — Client Mode         │"
    echo "│  客户端: ${CLIENT_LABEL}                      │"
    echo "│  输出: ${OUTPUT}                              │"
    echo "└──────────────────────────────────────────────┘"
    echo ""

    case "$TARGET" in
        claude) generate_client_claude ;;
        codex)  generate_client_codex ;;
        cursor) generate_client_cursor ;;
    esac

    echo ""
    echo "✅ 完成。"
    echo ""
    echo "下一步:"
    echo "  1. 配置 3 个环境变量（参见 _env.md）"
    echo "  2. Agent 启动 → 自动加载 Skill → 调用 GET /workers/{id}/protocol 拉取项目上下文"
    echo "  3. 握手 → 就绪"
else
    echo ""
    echo "┌──────────────────────────────────────────────┐"
    echo "│  Synapse Skill 包生成器                       │"
    echo "│  角色: ${ROLE}                                │"
    echo "│  客户端: ${TARGET}                            │"
    echo "└──────────────────────────────────────────────┘"
    echo ""

    case "$TARGET" in
        claude) generate_claude ;;
        codex)  generate_codex ;;
    esac

    echo ""
    echo "✅ 完成。"
    echo ""
    echo "下一步:"
    echo "  1. 检查并填入所有 {{VAR}} 占位符"
    echo "  2. 配置环境变量（参见 _env.md）"
    echo "  3. Agent 启动 → 自动加载 Skill 文件 → POST /workers/{id}/handshake"
fi
