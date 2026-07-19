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
API_URL="${SYNAPSE_API_URL:-}"
WORKER_ID="${SYNAPSE_WORKER_ID:-}"
PROJECT_ID="${SYNAPSE_PROJECT_ID:-}"
API_KEY="${SYNAPSE_API_KEY:-}"

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
    echo "    cursor   输出到 .cursor/rules/synapse-worker.mdc（alwaysApply 规则）"
    echo ""
    echo "模式 3 — API 渲染模式（调用 Synapse Protocol API 获取渲染后的 Skill）:"
    echo "  --from-api  从 Synapse 实例拉取已渲染的协议内容（0 未填充 VAR）"
    echo "  参数（可从环境变量读取）:"
    echo "    --api-url <url>       Synapse 实例地址（或 \$SYNAPSE_API_URL）"
    echo "    --worker-id <id>      Worker ID（或 \$SYNAPSE_WORKER_ID）"
    echo "    --project-id <id>     Project ID（或 \$SYNAPSE_PROJECT_ID）"
    echo "    --role <role>         角色（或 \$SYNAPSE_ROLE）"
    echo "    --api-key <key>       API Key（或 \$SYNAPSE_API_KEY）"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --role)       ROLE="$2"; shift 2 ;;
        --target)     TARGET="$2"; shift 2 ;;
        --output)     OUTPUT="$2"; shift 2 ;;
        --client)     CLIENT_MODE=true; shift ;;
        --from-api)   FROM_API=true; shift ;;
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

# ── Mode 3: --from-api (mutually exclusive with --client / --role) ──
if $FROM_API; then
    if $CLIENT_MODE || [[ -n "$ROLE" ]]; then
        echo "❌ --from-api 与 --client / --role 互斥"
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

## 配置方式

```bash
export SYNAPSE_API_URL="http://localhost:8000"
export SYNAPSE_API_KEY="sk-syn-..."
export SYNAPSE_WORKER_ID="wa_xxxxxxxx"
export SYNAPSE_PROJECT_ID="prj_xxxxxxxx"
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

# ─── Client Skill: Claude Code ───

generate_client_claude() {
    local OUT_DIR="$OUTPUT/.claude/skills/synapse"
    mkdir -p "$OUT_DIR"

    echo "▎ Claude Code → $OUT_DIR"

    cp "$SYNAPSE_CLIENT" "$OUT_DIR/SKILL.md"
    echo "  ✅ SKILL.md（Synapse Worker 协议）"

    write_client_env "$OUT_DIR"
    echo "  ✅ _env.md（3 个必需环境变量）"

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

    # ── Report unfilled vars ──
    if [[ -n "$UNFILLED" && "$UNFILLED" != "null" && "$UNFILLED" != "" ]]; then
        echo ""
        echo "⚠️  API 报告以下变量未解析: ${UNFILLED}"
        echo "   这些通常是 Task 级变量（TASK_ID/TASK_TITLE/...），需在 _task-current.md 中手动填写。"
    fi

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
