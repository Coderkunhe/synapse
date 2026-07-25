# Synapse Capability Gateway — MVP 设计

> Agent 的关键操作必须经过 Synapse。用户只在一个地方审批：Synapse Web。
> 2026-07-24 · MVP 范围：四个能力 · 一个人 · 10 天
> B51 更新 (2026-07-25): +shell_dangerous +git_force_push

---

## 0. 范围锁定

```
MVP 必须完成：
  ✅ 四个 Capability 完整闭环（git_push_main + git_push_branch + shell_dangerous + git_force_push）
  ✅ synapse-exec CLI（请求 → 等待 → 获取结果 → 调用 executor）
  ✅ Synapse Web 审批页面（已有 B44，微调即可）
  ✅ git pre-push hook（硬门禁）
  ✅ Skill 模板更新（告诉 Agent 用 synapse-exec）
  ✅ Shell 黑名单匹配（dangerous_patterns + protected_paths → 客户端判定）

MVP 明确不做：
  ❌ MCP server
  ❌ 多客户端深度集成
  ❌ 企业 IAM / RBAC
  ❌ 全局 OS 级拦截
  ❌ Secret store（MVP 用环境变量）
  ❌ 服务端黑名单校验（P2 纵深防御）
```

---

## 1. Capability Model

### 1.1 能力定义

```yaml
# synapse/config/capabilities.yaml
# MVP: 四个能力 — git_push_main · git_push_branch · shell_dangerous · git_force_push

capabilities:
  - id: "git_push_main"
    name: "Push to main branch"
    description: "git push origin main — 推送到生产分支"
    category: "git"
    risk: "critical"
    approval_policy: "always"          # always | once_per_session | never
    command: "git push origin ${BRANCH}"
    cwd: "${SYNAPSE_WORKSPACE}"        # 从环境变量注入
    timeout: 60
    evidence_required: true            # 执行后必须上报结果

  - id: "git_push_branch"
    name: "Push to feature branch"
    description: "git push origin ${BRANCH} — 推送到特性分支"
    category: "git"
    risk: "low"
    approval_policy: "never"           # 不需要审批，但会记录
    command: "git push origin ${BRANCH}"
    cwd: "${SYNAPSE_WORKSPACE}"
    timeout: 30
    evidence_required: false

  # ── B51: shell_dangerous + git_force_push ──

  - id: "shell_dangerous"
    name: "Dangerous Shell Command"
    description: "Execute a potentially dangerous shell command"
    category: "shell"
    risk: "critical"
    approval_policy: "always"
    command: "${SHELL_COMMAND}"        # 实际命令由 --params 传入
    cwd: "${SYNAPSE_WORKSPACE}"
    timeout: 120
    evidence_required: true
    dangerous_patterns:                # 🆕 黑名单 — 命中 → 审批
      - "rm -rf /"
      - "sudo rm"
      - "chmod 777"
      - "curl | bash"
      - ...
    protected_paths:                   # 🆕 保护路径 — 命中 → 审批
      - "~/.ssh/"
      - ".env"
      - "/etc/passwd"
      - ...

  - id: "git_force_push"
    name: "Force Push to Branch"
    description: "git push --force origin ${BRANCH}"
    category: "git"
    risk: "critical"
    approval_policy: "always"
    command: "git push --force origin ${BRANCH}"
    cwd: "${SYNAPSE_WORKSPACE}"
    timeout: 60
    evidence_required: true
```

`git_push_branch` 的作用不是拦截，是建立基线——让 Agent 习惯用 `synapse-exec`，即使低风险操作也走这条路径，养成肌肉记忆。

### 1.2 shell_dangerous — 黑名单模式（B51）

`shell_dangerous` 与其他能力不同：它不绑定固定命令，而是接受任意 `SHELL_COMMAND` 参数，在客户端（synapse-exec）做黑名单匹配。

**流程**：

```
synapse-exec shell_dangerous --params SHELL_COMMAND="rm -rf /tmp/foo"
  → 加载 capability（含 dangerous_patterns + protected_paths）
  → check_shell_blacklist():
      SHELL_COMMAND 匹配 dangerous_patterns 任一 → 危险
      SHELL_COMMAND 包含 protected_paths 任一 → 危险
      都不匹配 → 安全
  → 危险 → 创建授权请求 → 等待审批 → 执行 → 上报
  → 安全 → 直接执行（跳过审批）
```

**黑名单字段**：

| 字段 | 类型 | 匹配方式 | 说明 |
|:---|:---|:---|:---|
| `dangerous_patterns` | `list[str]` | 子串匹配 | 危险命令模式（`rm -rf /`, `curl \| bash`, `chmod 777`...） |
| `protected_paths` | `list[str]` | 子串匹配 | 受保护的文件/目录（`~/.ssh/`, `.env`, `/etc/passwd`...） |

**设计原则**：
- 客户端匹配 — 安全命令不创建 auth request，减少审批噪音
- 即时生效 — 改 YAML → API 即时返回新黑名单 → 下次 synapse-exec 调用生效
- 用户可自定义 — `dangerous_patterns` 和 `protected_paths` 可在 YAML 中自由增删

**使用示例**：

```bash
# 安全命令 — 直接执行，不走审批
synapse-exec shell_dangerous --params SHELL_COMMAND="echo hello world"

# 危险命令 — 触发审批
synapse-exec shell_dangerous --params SHELL_COMMAND="rm -rf /tmp/build" --reason "清理构建产物"

# 触碰保护路径 — 触发审批
synapse-exec shell_dangerous --params SHELL_COMMAND="cat ~/.ssh/config" --reason "检查 SSH 配置"
```

### 1.2 加载方式

MVP 阶段：能力定义从配置文件加载（不建数据库表）。

```
synapse-exec 启动时：
  1. 读取 $SYNAPSE_CAPABILITIES_FILE（默认 ~/.synapse/capabilities.yaml）
  2. 或者从 API GET /v1/workers/{id}/capabilities 拉取
  3. 校验能力定义的合法性
  4. 缓存到内存
```

---

## 2. synapse-exec CLI

### 2.1 命令格式

```bash
synapse-exec <capability_id> [--params KEY=VALUE ...] [--reason "..."] [--timeout N]
```

实际使用：

```bash
# Agent 调用
synapse-exec git_push_main --reason "完成 P11-B46 狗粮验证"

# 带参数的能力
synapse-exec git_push_branch --params BRANCH=feature/b47 --reason "新功能分支"

# B51: shell_dangerous — 危险命令走审批
synapse-exec shell_dangerous --params SHELL_COMMAND="rm -rf /tmp/build" --reason "清理构建产物"

# B51: git_force_push — 强制推送走审批
synapse-exec git_force_push --params BRANCH=main --reason "rebase 后同步"

# 指定超时
synapse-exec git_push_main --timeout 300 --reason "紧急 hotfix"
```

### 2.2 执行流程

```
synapse-exec git_push_main --reason "完成狗粮验证"
  │
  ├─ Step 1: 身份解析
  │   从 .env + keychain 读取: SYNAPSE_API_URL, SYNAPSE_WORKER_ID, SYNAPSE_API_KEY
  │
  ├─ Step 2: 能力匹配
  │   加载 capabilities.yaml → 匹配 id="git_push_main"
  │   → 获取: risk=critical, approval_policy=always, command="git push origin main"
  │
  ├─ Step 2b (B51 · 仅 shell_dangerous): 黑名单检查
  │   SHELL_COMMAND 匹配 dangerous_patterns / protected_paths
  │   → 安全 → 跳至 Step 5 直接执行
  │   → 危险 → 继续 Step 3
  │
  ├─ Step 3: 创建授权请求
  │   POST /v1/auth-requests
  │   Body: {
  │     "capability_id": "git_push_main",
  │     "action": "Push to main branch",
  │     "target": "git push origin main",
  │     "reason": "完成狗粮验证",
  │     "risk_level": "critical",
  │     "worker_id": "ag_xxx",
  │     "project_id": "prj_xxx"
  │   }
  │   → Response: { "id": "ath_xxx", "status": "pending" }
  │
  ├─ Step 4: 等待审批
  │   轮询 GET /v1/auth-requests/ath_xxx
  │   间隔: 2s · 超时: 120s（可配置）
  │   
  │   终端输出:
  │   ⏳ 等待审批... [ath_xxx] Push to main branch
  │   ⏳ 等待审批... (已等待 10s)
  │   ✅ 已批准 — Hunter · 耗时 23s
  │
  ├─ Step 5: 执行能力
  │   subprocess.run("git push origin main", cwd=$SYNAPSE_WORKSPACE)
  │   → capture stdout, stderr, exit_code
  │
  ├─ Step 6: 上报证据
  │   POST /v1/auth-requests/ath_xxx/report
  │   Body: {
  │     "outcome": "success",         # success | failure
  │     "exit_code": 0,
  │     "stdout": "abc1234..main\n",
  │     "duration_ms": 3200,
  │     "task_id": "tsk_xxx"          # 可选，关联 Task
  │   }
  │
  └─ Step 7: 返回结果
      exit 0 (success) 或 exit 1 (denied/failed)
      stdout 原样透传
```

### 2.3 审批等待机制

```bash
# synapse-exec 内部 wait 逻辑（伪代码）

wait_approval() {
    local auth_id=$1
    local timeout=${2:-120}
    local elapsed=0
    
    while [ $elapsed -lt $timeout ]; do
        response=$(curl -s "$API_URL/v1/auth-requests/$auth_id" \
            -H "Authorization: Bearer $API_KEY")
        
        status=$(echo "$response" | jq -r '.status // .decision // "pending"')
        
        case "$status" in
            "approved")
                echo "✅ 已批准 — $(echo "$response" | jq -r '.responded_by_name // "admin"')"
                return 0
                ;;
            "denied"|"rejected")
                reason=$(echo "$response" | jq -r '.denial_reason // "无理由"')
                echo "❌ 已拒绝 — $reason"
                return 1
                ;;
            "expired")
                echo "⏰ 审批超时 — 请求已过期"
                return 2
                ;;
            *)
                sleep 2
                elapsed=$((elapsed + 2))
                echo "⏳ 等待审批... (已等待 ${elapsed}s)"
                ;;
        esac
    done
    
    echo "⏰ 等待超时 (${timeout}s)"
    return 2
}
```

### 2.4 身份认证

```
synapse-exec 读取 Worker 身份的优先级：

1. 环境变量（SessionStart hook 已设置）
   SYNAPSE_API_URL=http://127.0.0.1:8000
   SYNAPSE_WORKER_ID=ag_xxx
   SYNAPSE_PROJECT_ID=prj_xxx
   SYNAPSE_API_KEY=sk-syn-xxx（从 keychain 注入）

2. 如果环境变量缺失 → 尝试读取 ~/.synapse/config

3. 如果全部缺失 → 报错退出
   "❌ 未找到 Synapse Worker 身份。请先配置 .env 或 ~/.synapse/config"
```

**不需要额外登录流程**。Worker 的身份在 B35 已经建立好——keychain 中的 API key + .env 中的 Worker ID。synapse-exec 直接复用。

### 2.5 request_id 与 task_id 关联

```
request_id (ath_xxx)
  → 一次授权请求的唯一 ID
  → 由 Synapse API 在 POST /auth-requests 时生成
  → synapse-exec 用它在 Step 4 轮询、Step 6 上报

task_id (tsk_xxx)  
  → 关联的 Synapse Task（可选）
  → 如果 Agent 当前在 Task 上下文中执行操作
  → synapse-exec --task-id tsk_xxx git_push_main
  → 审批记录和 Task 关联，审计时可追溯
```

### 2.6 完整 CLI 实现骨架

```bash
#!/usr/bin/env bash
# synapse-exec — Synapse Capability Executor
# 用法: synapse-exec <capability_id> [--params k=v] [--reason "..."] [--timeout N] [--task-id id]

set -euo pipefail

# ── 身份解析 ──
SYNAPSE_API_URL="${SYNAPSE_API_URL:-}"
SYNAPSE_WORKER_ID="${SYNAPSE_WORKER_ID:-}"  
SYNAPSE_PROJECT_ID="${SYNAPSE_PROJECT_ID:-}"
SYNAPSE_API_KEY="${SYNAPSE_API_KEY:-}"

if [ -z "$SYNAPSE_API_KEY" ]; then
    # 尝试 keychain
    if command -v security &>/dev/null; then
        SYNAPSE_API_KEY=$(security find-generic-password \
            -a "synapse-worker-${SYNAPSE_WORKER_ID}" -s "synapse" -w 2>/dev/null || true)
    fi
fi

[ -z "$SYNAPSE_API_URL" ] && { echo "❌ SYNAPSE_API_URL 未设置"; exit 1; }
[ -z "$SYNAPSE_WORKER_ID" ] && { echo "❌ SYNAPSE_WORKER_ID 未设置"; exit 1; }
[ -z "$SYNAPSE_API_KEY" ] && { echo "❌ SYNAPSE_API_KEY 未设置"; exit 1; }

# ── 参数解析 ──
CAP_ID="${1:-}"
[ -z "$CAP_ID" ] && { echo "用法: synapse-exec <capability_id> [--params k=v] [--reason ...]"; exit 1; }
shift

PARAMS=""
REASON=""
TIMEOUT=120
TASK_ID=""

while [ $# -gt 0 ]; do
    case "$1" in
        --params) PARAMS="$2"; shift 2 ;;
        --reason) REASON="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        --task-id) TASK_ID="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# ── 能力匹配 ──
# 从 API 拉取能力定义
CAP=$(curl -sS "$SYNAPSE_API_URL/v1/workers/$SYNAPSE_WORKER_ID/capabilities" \
    -H "Authorization: Bearer $SYNAPSE_API_KEY" | \
    jq -r ".[] | select(.id == \"$CAP_ID\")")

[ -z "$CAP" ] && { echo "❌ 未知能力: $CAP_ID"; exit 1; }

POLICY=$(echo "$CAP" | jq -r '.approval_policy')
CMD=$(echo "$CAP" | jq -r '.command')
RISK=$(echo "$CAP" | jq -r '.risk')

# ── 变量替换 ──
CMD="${CMD//\$\{BRANCH\}/$PARAMS}"  # 简化版，实际做完整 envsubst

# ── 如果需要授权，创建请求 ──
AUTH_ID=""
if [ "$POLICY" != "never" ]; then
    REQ_BODY=$(jq -n \
        --arg cap_id "$CAP_ID" \
        --arg action "$(echo "$CAP" | jq -r '.name')" \
        --arg target "$CMD" \
        --arg reason "$REASON" \
        --arg risk "$RISK" \
        --arg worker_id "$SYNAPSE_WORKER_ID" \
        --arg project_id "$SYNAPSE_PROJECT_ID" \
        --arg task_id "$TASK_ID" \
        '{capability_id: $cap_id, action: $action, target: $target, 
          reason: $reason, risk_level: $risk, worker_id: $worker_id,
          project_id: $project_id, task_id: $task_id}')
    
    RESP=$(curl -sS "$SYNAPSE_API_URL/v1/auth-requests" \
        -H "Authorization: Bearer $SYNAPSE_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$REQ_BODY")
    
    AUTH_ID=$(echo "$RESP" | jq -r '.id')
    echo "📋 授权请求已创建: $AUTH_ID"
    
    # ── 等待审批 ──
    ELAPSED=0
    while [ $ELAPSED -lt $TIMEOUT ]; do
        STATUS=$(curl -sS "$SYNAPSE_API_URL/v1/auth-requests/$AUTH_ID" \
            -H "Authorization: Bearer $SYNAPSE_API_KEY" | \
            jq -r '.status // .decision // "pending"')
        
        case "$STATUS" in
            approved)
                APPROVER=$(curl -sS "$SYNAPSE_API_URL/v1/auth-requests/$AUTH_ID" \
                    -H "Authorization: Bearer $SYNAPSE_API_KEY" | \
                    jq -r '.responded_by_name // "admin"')
                echo "✅ 已批准 — $APPROVER · 耗时 ${ELAPSED}s"
                break
                ;;
            denied|rejected)
                echo "❌ 已拒绝"
                exit 1
                ;;
            expired)
                echo "⏰ 审批超时 — 请求已过期"
                exit 2
                ;;
            *)
                sleep 2
                ELAPSED=$((ELAPSED + 2))
                echo "⏳ 等待审批... (${ELAPSED}s)"
                ;;
        esac
    done
    
    [ $ELAPSED -ge $TIMEOUT ] && { echo "⏰ 等待超时 (${TIMEOUT}s)"; exit 2; }
fi

# ── 执行能力 ──
echo "▸ 执行: $CMD"
START_TIME=$(date +%s%3N)

eval "$CMD" 2>&1  # 实际用 subprocess
EXIT_CODE=$?

END_TIME=$(date +%s%3N)
DURATION=$((END_TIME - START_TIME))

# ── 上报证据 ──
if [ -n "$AUTH_ID" ]; then
    OUTCOME="success"
    [ $EXIT_CODE -ne 0 ] && OUTCOME="failure"
    
    curl -sS "$SYNAPSE_API_URL/v1/auth-requests/$AUTH_ID/report" \
        -H "Authorization: Bearer $SYNAPSE_API_KEY" \
        -H "Content-Type: application/json" \
        -d "$(jq -n \
            --arg outcome "$OUTCOME" \
            --arg exit_code "$EXIT_CODE" \
            --arg duration "$DURATION" \
            '{outcome: $outcome, exit_code: $exit_code|tonumber, 
              duration_ms: $duration|tonumber}')" \
        > /dev/null
    
    echo "📊 结果已上报 (exit=$EXIT_CODE · ${DURATION}ms)"
fi

exit $EXIT_CODE
```

---

## 3. Capability Executor

### 3.1 MVP 设计

Executor 不独立部署——它是 synapse-exec CLI 内的 `eval`/`subprocess.run()` 调用。

```
┌────────────── synapse-exec ──────────────┐
│                                           │
│  request → wait → executor → report      │
│                      │                    │
│                      ▼                    │
│              subprocess.run(cmd)          │
│              capture: stdout+stderr+code  │
│                                           │
└───────────────────────────────────────────┘
```

**为什么 MVP 不做独立 Executor？**

独立 executor（如 daemon 或 sidecar）的价值在于：
- 凭证隔离（executor 持有凭证，Agent 看不到）
- 执行环境沙箱（Docker、VM）
- 审计不可篡改

这些是 P2 的能力。MVP 的目标是打通链路，不是做安全产品。

### 3.2 各能力执行方式

| 能力 | executor | 说明 |
|:---|:---|:---|
| `git_push_main` | `git push origin main` | shell 直接执行 |
| `git_push_branch` | `git push origin $BRANCH` | shell 直接执行 |
| `deploy_production` (P2) | `curl -X POST $WEBHOOK` | WEBHOOK 存在环境变量，不在 Agent 可见范围 |
| `db_migrate` (P2) | `alembic upgrade head` | DB URL 存在环境变量 |

---

## 4. git pre-push hook

### 4.1 设计

```bash
#!/usr/bin/env bash
# .git/hooks/pre-push — 由 synapse hooks install 安装
#
# 逻辑：
#   1. 检测当前分支
#   2. 如果是 main/master → 必须通过 Synapse 审批
#   3. 检查是否有有效审批记录（最近 N 分钟的 approved 请求）
#   4. 如果没有 → 调用 synapse-exec git_push_main
#   5. synapse-exec 内部完成授权 → 执行 → 返回

set -euo pipefail

REMOTE="$1"
URL="$2"
BRANCH=$(git branch --show-current)

# 只拦截 main/master 分支
if [[ "$BRANCH" != "main" ]] && [[ "$BRANCH" != "master" ]]; then
    exit 0  # feature 分支直接放行
fi

# 检查是否有 Synapse 配置
if [ -z "${SYNAPSE_API_URL:-}" ]; then
    echo "⚠️  Synapse 未配置。跳过授权检查。"
    echo "   安装: synapse hooks install"
    exit 0  # 宽松模式：未配置时不阻断
fi

echo "🛡️  Synapse: 推送到 $BRANCH 需要审批"
echo ""

# 调用 synapse-exec（它内部会完成 请求→审批→执行→上报）
synapse-exec git_push_main --reason "git push $BRANCH → $URL"
```

### 4.2 安装方式

```bash
# 由 synapse CLI 安装
synapse hooks install --repo /path/to/repo

# 实际执行：
# 1. 检测 git 仓库
# 2. 复制 pre-push hook 模板到 .git/hooks/pre-push
# 3. chmod +x .git/hooks/pre-push
# 4. 验证 hook 可执行
```

### 4.3 检测仓库绑定

```bash
# 仓库与 Project 的绑定关系存在本地配置
# ~/.synapse/repo-bindings.yaml

bindings:
  - repo: /Users/USERNAME/projects/personal/ai/ai-synapse
    project_id: prj_019f6e082ec572fd
    capabilities:
      - git_push_main
      - git_push_branch
```

`synapse hooks install` 时自动写入绑定。hook 执行时读取绑定确定 project_id。

### 4.4 如何检查审批

MVP 不检查"有没有之前的审批"（那是缓存逻辑，P2）。每次 push main 都走完整 request → wait 流程。

### 4.5 如何阻止未授权 push

```
如果用户绕过 synapse-exec 直接 git push:
  → pre-push hook 被触发
  → hook 调用 synapse-exec git_push_main
  → synapse-exec 走 request → wait 流程
  → 用户必须在 Synapse Web 点 Allow
  → Allow → executor git push → exit 0 → hook 放行
  → Deny → synapse-exec exit 1 → hook exit 1 → git 阻断 push
```

**这就是硬门禁**。git 自身机制保证 pre-push hook exit ≠ 0 时 push 被阻断。

但有一个逃生通道：

```bash
# 如果用户主动删除 pre-push hook
rm .git/hooks/pre-push
git push  # 绕过了

# 缓解：
# 1. synapse hooks install 可以设置为重复安装（类似 npm install 恢复 node_modules）
# 2. P2: CI/CD 侧校验（GitHub required status check）
# 3. MVP 承认：删 hook = 绕过。但这是有意行为，不是"忘了"。
```

---

## 5. 与现有 Synapse 基础设施的对齐

### 已有（零改动）

| 组件 | 批次 | 能力 |
|:---|:---:|:---|
| AuthorizationRequest 模型 | B22 | POST + GET + PATCH |
| WS 实时推送 | B22 | Web UI 即时收到新请求 |
| Approvals Web 页面 | B44 | Pending/History 双 Tab + 审批按钮 |
| Worker 身份 (keychain) | B35 | synapse-exec 直接复用 |
| SKILL.md 模板 | B33 | 授权章节更新 |

### 需新增

| # | 组件 | 文件 | 行数 | 说明 | 状态 |
|:---:|:---|:---|:---:|:---|:---:|
| 1 | Capability 配置 | `config/capabilities.yaml` | ~80 | 四个能力定义（含黑名单） | B51 ✅ |
| 2 | GET /workers/{id}/capabilities | `api/routers/capabilities.py` | ~30 | 从 yaml 读取并返回 | B46 ✅ |
| 3 | POST /auth-requests/{id}/report | `api/routers/authorization_requests.py` | ~20 | 接收执行结果 | B46 ✅ |
| 4 | synapse-exec CLI | `tools/synapse-exec` | ~600 | 主 CLI + 黑名单匹配 | B48+B51 ✅ |
| 5 | synapse hooks install | `tools/synapse-exec` 子命令 | ~30 | hook 安装器 | B49 ✅ |
| 6 | pre-push hook 模板 | `tools/git-hooks/pre-push` | ~25 | hook 模板 | B49 ✅ |
| 7 | Skill 模板更新 | `docs/templates/_protocol.md` | +30 | 授权引导 | B52 🔜 |
| 8 | 本设计文档 | `docs/capability-mvp.md` | 本文 | - | B51 ✅ |

**总计：~640 行代码/配置。**

---

## 6. Skill 模板更新

`docs/templates/_protocol.md` 新增章节：

```markdown
## 🔐 Capability Authorization

Synapse 将关键操作定义为命名能力。使用能力前需要获得授权。

### 如何使用

执行任何以下操作时，**必须**使用 `synapse-exec`：

```bash
# git 操作
synapse-exec git_push_main --reason "完成功能开发"
synapse-exec git_push_branch --params BRANCH=feature/xxx
synapse-exec git_force_push --params BRANCH=main --reason "rebase 后同步"

# 危险 shell 命令
synapse-exec shell_dangerous --params SHELL_COMMAND="rm -rf /tmp/build" --reason "清理构建产物"
# 安全命令会直接执行，不触发审批
synapse-exec shell_dangerous --params SHELL_COMMAND="echo hello"

# 注意：不要直接使用 git push 或裸 shell 命令。
# synapse-exec 会自动处理授权并在批准后执行。
```

### 授权策略

| 能力 | 风险 | 授权策略 |
|------|:---:|:---:|
| `git_push_main` | critical | 每次需要审批 |
| `git_push_branch` | low | 无需审批（但会记录） |
| `shell_dangerous` | critical | 危险命令需审批，安全命令直接放行 |
| `git_force_push` | critical | 每次需要审批 |

### 授权流程

```
你调用 synapse-exec → Synapse 创建授权请求
→ 人在 Synapse Web 审批 → 批准后自动执行
→ 结果返回给你 → 继续工作
```

在等待审批期间，你的对话会暂停在 synapse-exec 调用处。
审批完成后 synapse-exec 返回结果，你继续执行后续步骤。

### 如果审批被拒绝

synapse-exec 会返回非零退出码。你应该：
1. 查看拒绝原因（synapse-exec 会输出）
2. 与审批人沟通
3. 调整操作后重新请求
```

---

## 7. 10 天开发顺序

```
Day 1-2: 基础设施
  ├─ config/capabilities.yaml（2 个能力定义）
  ├─ GET /v1/workers/{id}/capabilities 端点
  └─ 验证：curl 可拉取能力列表

Day 3-5: synapse-exec CLI
  ├─ 身份解析（env + keychain）
  ├─ 能力匹配（从 API 拉取）
  ├─ 授权请求创建（POST /auth-requests）
  ├─ 审批等待（轮询 + 超时 + 终端提示）
  ├─ 能力执行（subprocess + stdout/stderr 捕获）
  ├─ 证据上报（POST /auth-requests/{id}/report）
  └─ 验证：synapse-exec git_push_main → 全链路走通

Day 6: report 端点
  ├─ POST /v1/auth-requests/{id}/report
  ├─ AuthorizationRequest 模型更新（加 outcome/exit_code/duration 字段）
  └─ 验证：执行后 Approval History 可看到结果

Day 7: git pre-push hook
  ├─ 模板编写
  ├─ synapse hooks install 子命令
  ├─ 仓库绑定配置
  └─ 验证：git push main 触发 hook → 走完整审批链

Day 8: Skill 模板 + Web 微调
  ├─ _protocol.md 授权章节
  ├─ Approvals 页面展示 capability_id + outcome（可选微调）
  └─ 验证：双 Worker SKILL.md 刷新后包含授权章节

Day 9: 狗粮验证
  └─ 双 Worker 全链路：CLI 请求 → Web 审批 → 执行 → 审计

Day 10: 文档 + bugfix
  └─ README 更新 · 使用指南 · 已知限制
```

### 每天必须验证的门禁

| Day | 验证命令 | 预期 |
|:---:|:---|:---|
| 2 | `curl localhost:8000/v1/workers/{id}/capabilities` | 返回 2 个能力 |
| 5 | `synapse-exec git_push_main --reason "测试"` | 等待审批 → Allow → git push 执行 |
| 6 | `curl localhost:8000/v1/auth-requests/{id}` | outcome + exit_code + duration 有值 |
| 7 | `git push origin main`（有 hook） | 触发 hook → synapse-exec → 审批 |
| 9 | 双 Worker 全链路 | Approvals 页面收到 → 审批 → Agent 继续 |

---

## 8. 用户可见的完整体验

```
场景：Agent 完成了 P11-B46 狗粮验证，需要 git push main

Agent 终端：
  $ synapse-exec git_push_main --reason "P11-B46 狗粮验证完成"
  📋 授权请求已创建: ath_abc123
  ⏳ 等待审批... (2s)
  ⏳ 等待审批... (4s)
  ✅ 已批准 — Hunter · 耗时 23s
  ▸ 执行: git push origin main
  Enumerating objects: 15, done.
  Counting objects: 100% (15/15), done.
  ...
  To github.com:hunter/project.git
     abc1234..def5678  main -> main
  📊 结果已上报 (exit=0 · 3200ms)

用户侧（Synapse Web）：
  Approvals 页面 → Pending Tab 出现：
  ┌──────────────────────────────────────────┐
  │ ⚠ critical  Push to main branch         │
  │ Agent: Builder (ag_xxx)                 │
  │ Reason: P11-B46 狗粮验证完成             │
  │ 创建时间: 刚刚                           │
  │                                          │
  │ [Allow]  [Deny]                          │
  └──────────────────────────────────────────┘

  点击 Allow 后 → History Tab 出现：
  ┌──────────────────────────────────────────┐
  │ ✅ approved  Push to main branch         │
  │ Approved by: Hunter · 23s ago           │
  │ Outcome: success (exit 0) · 3.2s        │
  │ Commit: abc1234 → def5678               │
  └──────────────────────────────────────────┘
```
