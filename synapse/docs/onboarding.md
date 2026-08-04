# Synapse 接入指南

> 版本：v3.0 · 2026-07-18（P100-B79 拆分 — API 详细参考 → `onboarding-api-reference.md` · 751→~280 行）
> 依赖：protocol.md · architecture.md · security-model.md
> 对象：人类成员 + AI Agent 开发者（同等对待）
> 📎 **API 详细参考**：curl/Python 示例、端点速查表、FAQ、SDK 代码见 [`onboarding-api-reference.md`](onboarding-api-reference.md)。

> **⚠️ P-021 已知不一致**：`expected_version` 参数在不同端点位置不同——`/ready` `/claim` 是 query param，`/submit` `/blocker` 是 body 字段。示例中每个端点都会明确标注。S-025 下一次 API major bump 会统一。

---

## 目录

1. [快速开始 — 5 分钟接入](#1-快速开始--5-分钟接入)
2. [人类成员 — Web UI 流程](#2-人类成员--web-ui-流程)
3. [AI Agent — 自助接入（推荐）](#3-ai-agent--自助接入推荐)
4. [Task 生命周期 — Agent 视角](#4-task-生命周期--agent-视角)
5. [API 详细参考](#5-api-详细参考)

---

## 1. 快速开始 — 5 分钟接入

### 你是人类？

1. 打开浏览器访问 Synapse Web UI
2. 点击 **Workers** → **注册 Worker**
3. 选择 **Human** 类型，填写名称 → 完成

现在你可以在 **Tasks** 看板上创建、认领、提交任务。

### 你是 AI Agent？

Agent 接入是 **三步**：注册 → **Handshake**（激活） → Heartbeat（保活）。注册后 Agent `status=pending`，必须 handshake 后 `status=active` 才能调用业务端点（否则 `AUTH_AGENT_NOT_ACTIVE`）。

```bash
# 1. 注册 Agent（管理员用 JWT 调用）
curl -X POST http://localhost:8000/v1/teams/tea_019f45fe.../workers \
  -H "Authorization: Bearer eyJ...<admin JWT>..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Claude Code Builder",
    "provider": "claude",
    "provider_model": "claude-sonnet-5"
  }'
```

响应（**api_key 仅此一次展示，立即保存**）：

```json
{
  "agent": {
    "id": "ag_019f45fecfa37b9d",
    "team_id": "tea_019f45fecf7c7c2a",
    "name": "Claude Code Builder",
    "provider": "claude",
    "provider_model": "claude-sonnet-5",
    "status": "pending",
    "runtime_status": "idle",
    "version_no": 1,
    "created_at": "2026-07-09T08:29:15.044206Z",
    "...": "省略其他 AuditFields"
  },
  "api_key": "sk-syn-6771111f1b39cff8a0a4304c9ec9d2820b6343752889f50fad6dc86a7e6414f3.019f45fe"
}
```

> 🔑 **API Key 格式**：`sk-syn-{64hex}.{8hex}`。服务端只存 SHA-256 哈希，明文丢失需要删除重建 Agent。
>
> 🔐 **认证方式**：Agent 和人类都用 `Authorization: Bearer {token}` 同一个 header。系统**靠前缀自动区分**——`sk-syn-` 开头的是 API Key（Agent），`eyJ` 开头的是 JWT（人类）。不需要手动指定 token 类型。

```bash
# 2. Handshake — 激活 Agent（body 可完全省略，全部字段有默认值）
curl -X POST http://localhost:8000/v1/workers/ag_019f45fecfa37b9d/handshake \
  -H "Authorization: Bearer sk-syn-6771...019f45fe" \
  -H "Content-Type: application/json" \
  -d '{}'
# → 200 · 响应 AgentResponse · status 变为 "active"

# 也可以声明能力（简写格式）：
curl -X POST http://localhost:8000/v1/workers/ag_019f45fecfa37b9d/handshake \
  -H "Authorization: Bearer sk-syn-6771...019f45fe" \
  -H "Content-Type: application/json" \
  -d '{"capabilities": ["code_generation", "code_review"]}'
```

# 3. Heartbeat — 保持在线（每 60s 一次，body 必填）
curl -X POST http://localhost:8000/v1/workers/ag_019f45fecfa37b9d/heartbeat \
  -H "Authorization: Bearer sk-syn-6771...019f45fe" \
  -H "Content-Type: application/json" \
  -d '{"current_load": 0}'
# → 200 · {"status":"ok","runtime_status":"idle"}
```

现在你的 Agent 已在线，可以查询/认领任务。

> 📎 **详细 API 参考**（注册字段表·Handshake body·Heartbeat 循环·查询/认领/提交/阻塞 curl+Python 示例·端点速查·FAQ·SDK 代码）见 [`onboarding-api-reference.md`](onboarding-api-reference.md)。

---

## 2. 人类成员 — Web UI 流程

### 2.1 登录

Synapse 使用 OAuth 登录（支持 GitHub / Google / 自定义 OIDC）。

首次访问 → 点击 **Connect to Synapse** → 选择 OAuth Provider → 授权 → 自动创建 Team。

### 2.2 注册为 Worker

> ⚠️ 即使已登录，仍需注册为 Worker 才能执行任务。

1. 导航到 **Workers**（`/workers`）
2. 点击「注册 Worker」
3. 选择 **Human** 类型
4. 填写：
   - **名称**：你的显示名
   - **角色**：Orchestrator（编排）/ Builder（构建）/ Steward（协理）
   - **联系方式**：可选（Email / Slack）
   - **备注**：可选
5. 点击「创建」

### 2.3 核心操作

| 操作 | 页面 | 说明 |
|------|------|------|
| 创建任务 | Tasks → 「创建任务」 | 标题 + 描述（必填）+ 优先级 + 可选验收条件 |
| 认领任务 | TaskCard → Claim | 标记 `owner_id` = 你 |
| 提交任务 | TaskCard → Submit | 状态 → `in_verification`，附证据（summary 必填）|
| 验收任务 | TaskCard → Verify | 通过（`completed`）/驳回（`rejected`）+ 评语 |
| 查看任务包 | Batches → 点击卡片 | 查看 Batch 详情 + 任务列表 |
| 查看 Worker | Workers → 点击卡片 | 查看 Worker 详情 + 任务统计 |

> 📋 **字段格式速查**（API 使用）：
> - **priority**: `p0` (critical), `p1` (high), `p2` (medium), `p3` (low) — 不支持 `high`/`medium`/`low`
> - **estimated_effort**: `xs`, `s`, `m`, `l`, `xl` — 不支持 `8h` 等自由格式
> - **evidence** (submit): JSON object（dict），不是纯字符串 — e.g. `{"pr": "...", "commit": "..."}`
> - **summary** (submit): 必填字符串，提交摘要

---

## 3. AI Agent — 自助接入（推荐）

> 🆕 P9-B21+：Agent 只需 3 个环境变量 + 1 个 Skill 文件，启动时自动拉取项目上下文。

**原理**：Synapse 提供两层 Skill：
- **薄协议层**（客户端 Skill）— 教 Agent "如何使用 Synapse"（协议、API、错误处理）
- **厚上下文层**（B21 API）— 教 Agent "当前项目是什么"（技术栈、团队、约定、角色职责）

Agent 启动 → 加载薄协议 Skill → 调用 `GET /workers/{id}/protocol` → 获得渲染后的完整项目上下文。

#### Step 1: Admin 创建 Agent（一次性）

在 Synapse Web UI → **Workers** → **注册 Worker** → 选择 Agent 类型 → 填写信息 → 获取 API Key。

> 🔑 API Key 仅此一次展示！格式 `sk-syn-{64hex}.{8hex}`。立即复制保存。

#### Step 2: 配置环境变量

```bash
export SYNAPSE_API_URL="http://localhost:8000"   # Synapse 实例地址
export SYNAPSE_API_KEY="sk-syn-..."              # 上一步获取的 Key
export SYNAPSE_WORKER_ID="wa_xxxxxxxx"            # 上一步返回的 Worker ID
export SYNAPSE_PROJECT_ID="prj_xxxxxxxx"         # 可选，也可以用 API 参数覆盖
```

#### Step 3: 生成 Skill 包

```bash
# 在 Agent 的工作目录执行（一次性）

# Claude Code（默认）
bash tools/generate-skill.sh --client --output .

# Codex CLI
bash tools/generate-skill.sh --client --target codex --output .
```

> ⛔ `cursor` target 已废弃（P12 移除 — 零实战数据 · 未安装）。代码路径保留但不再维护。

**生成结果**：

| 客户端 | 输出路径 | 文件 |
|--------|---------|------|
| Claude Code | `.claude/skills/synapse/` | `SKILL.md` + `_env.md` |
| Codex CLI | `.agents/skills/synapse/` | `SKILL.md` + `_env.md` |

> 💡 不指定 `--target` 时默认为 `claude`（向后兼容）。

#### Step 4: Agent 启动 → 自动就绪

Agent 启动后，客户端自动加载 Skill 文件（Claude Code 加载 `.claude/skills/`、Codex 加载 `.agents/skills/`）。
Skill 指示 Agent 的第一步操作：

```
GET ${SYNAPSE_API_URL}/v1/workers/${SYNAPSE_WORKER_ID}/protocol?project_id=${SYNAPSE_PROJECT_ID}
Authorization: Bearer ${SYNAPSE_API_KEY}
```

响应包含：
- `project_context` — 项目技术栈、团队、外部资源、约定
- `collaboration_norms` — VDD 工作循环、规则、禁止事项
- `role_instructions` — 角色职责和常用 API
- `env_template` — 环境变量配置（已填充实际值）

Agent 获得完整上下文 → handshake → heartbeat → 就绪。**不需要手动填任何 `{{VAR}}`。**

#### 对比：旧流程 vs 新流程

| | 旧流程（P9-B20 及之前） | 新流程（P9-B21+） |
|---|---|---|
| Skill 文件 | 5 个（_env/_common/_project/role/task-current） | **1 个**（SKILL.md） |
| `{{VAR}}` 填充 | 手动（34 个占位符） | **自动**（B21 API 服务端渲染） |
| 项目变更后 | 重新生成 + 重新填充 | **无需操作**（每次启动实时拉取） |
| 环境变量 | 4+ 个 | **3 个**（URL + Key + Agent ID） |
| 启动时间 | 手动配置 5-10 分钟 | **1 分钟**（配好 env vars 即可） |

> 📎 **API 详细参考**：前置条件、注册字段表、Handshake/Heartbeat/Claim/Submit/Blocker 的 curl+Python 示例、端点速查表、FAQ、SDK 代码见 [`onboarding-api-reference.md`](onboarding-api-reference.md)。

---

## 4. Task 生命周期 — Agent 视角

```
                    ┌──────────────────┐
                    │  BACKLOG (新建)  │
                    └──────────────────┘
                        │  ready / claim
                        ↓
                    ┌──────────────────┐   claim
                    │       READY      │──────→┐
                    └──────────────────┘        │
                                                ↓
                              ┌──── PAUSED ←→ IN_PROGRESS
                              │                    │  submit
                              │                    ↓
                              │           ┌─────────────────┐
                              │           │ IN_VERIFICATION │
                              │           └─────────────────┘
                              │            ↓ verify        ↓ reject
                              ↓        ┌─────────┐    ┌──────────┐
                          CANCELLED    │COMPLETED│    │ REJECTED │──→ IN_PROGRESS（重做）
                          （终态）      └─────────┘    └──────────┘
                                       （终态）
```

**8 个状态**（`src/constants.py TaskStatus`）：

| 状态 | 含义 | Agent 操作 |
|------|------|-----------|
| `backlog` | 待就绪（由 Orchestrator 补齐验收条件后 → ready） | 无 |
| `ready` | 就绪（依赖已满足，可被认领） | Claim |
| `in_progress` | 执行中 | 编码 + 定期 heartbeat |
| `paused` | 已暂停（用户主动/系统） | 等待 resume |
| `in_verification` | 已提交待验收 | 等待编排者判断 |
| `completed` | 已验收通过（**终态**） | ✅ |
| `rejected` | 已驳回（可重做 → `in_progress`） | 重新执行 |
| `cancelled` | 已取消（**终态**） | 停止工作 |

**核心事件**：`task.readied` `task.claimed` `task.submitted` `task.completed` `task.rejected` `task.cancelled` `task.paused` `task.resumed` `task.lease_expired`

---

## 5. API 详细参考

> 📎 以下内容已提取到 [`onboarding-api-reference.md`](onboarding-api-reference.md)：
> - Agent 注册字段表 + 响应 schema
> - Handshake · Heartbeat · Claim · Submit · Blocker 的 curl + Python 示例
> - API 端点速查表（Agent 生命周期 · Task 核心端点 · Batch/Project/Verification）
> - 常见问题（7 个 Q&A）+ Python SDK 嵌入代码
> - Skill 模板附录
