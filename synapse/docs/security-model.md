# Synapse 安全模型

> 版本：v1.4 · 2026-07-18（P100-B80 S-036 全量对齐审计 — §7.2 事件类型对齐源码·§8 传输安全诚实化·§2.2 OAuth Provider 修正·access token cookie 补充·§2.3 吊销描述修正）
> 依赖：data-model.md（实体+角色）· protocol.md（端点+操作）
> 被引用：architecture.md §5.4 授权管道 · §8 地基文档
> 最后更新：2026-07-18
>
> ⚠️ **v1.4 Update Notes**：S-036 全量对齐审计完成。§7.2 事件类型确认为 60 种（`authorization_request.approved/denied`→`responded/heartbeat`，代码 EventType 共 60 成员）。§8 传输安全：HTTPS/HSTS/CSP 诚实标注为部署层职责（应用层仅 CORS + Cookie）。§2.2 OAuth Provider 修正为仅 GitHub。access token httpOnly cookie 补充文档化。v1.3 已将 §3 重写为 P10 三层授权模型，§6+§10-12 提取到 appendix。

---

## 1. 安全设计原则

| 原则 | 说明 |
|------|------|
| **租户强制隔离** | Team 边界在数据访问层强制执行，不依赖应用逻辑 |
| **最小权限** | Member 和 Agent 默认无权，按角色和能力显式授权 |
| **Agent 沙箱** | Agent 只能看到分配给它的 Task，不能遍历团队所有数据 |
| **API Key 不可逆** | Key 存储使用哈希，生成后仅返回一次明文 |
| **事件不可篡改** | Event 表 append-only，无 update/delete 权限 |
| **深度防御** | 认证 → 授权 → 租户隔离 → 审计日志，层层校验 |

---

## 2. 认证（Authentication）

### 2.1 双通道认证

```
        ┌──────────────────┐
        │    Synapse API    │
        └────┬─────────┬────┘
             │         │
    ┌────────┴──┐  ┌──┴──────────┐
    │  JWT      │  │  API Key    │
    │  (人类)   │  │  (Agent)    │
    └───────────┘  └─────────────┘
```

统一入口 `get_current_actor()`（`src/dependencies.py`）自动识别 Bearer token 前缀：
- `sk-syn-` → API Key 验证 → `ActorInfo(actor_type="agent", role=None, ...)`
- `eyJ...`（JWT header）→ JWT 验证 → `ActorInfo(actor_type="member", role=..., ...)`

| 通道 | 适用对象 | 凭证 | 有效期 | 刷新 |
|------|---------|------|--------|------|
| JWT (OAuth 2.0) | Member（人类） | Access Token + Refresh Token | 15min / 7d | `/auth/refresh` |
| API Key | Agent（AI） | `sk-syn-...` 前缀密钥 | 永久（可吊销） | 重新生成 |

### 2.2 JWT 认证（Member）

**OAuth 2.0 Authorization Code Flow + PKCE**：

```
人类用户 → 前端 → Synapse Auth Service → OAuth Provider (GitHub)
                                           ↓
                                    JWT (Access + Refresh)
```

**Access Token Payload**：
```json
{
  "sub": "user_7a3b2c1d",
  "teamId": "tea_7a3b2c1d",
  "memberId": "mem_9f4e8d2a",
  "role": "admin",
  "actor_type": "member",
  "iat": 1712345678,
  "exp": 1712346578
}
```

> `actor_type: "member"` 是 `get_current_actor()` 区分 Member vs Agent 的关键字段。Agent 通过 API Key 认证时 `actor_type="agent"`, `role=None`。

**Refresh Token**：
- 存储在 httpOnly cookie（浏览器）或安全存储（CLI）
- 7 天过期，使用一次即轮换（refresh token rotation）
- 检测到重复使用 → 吊销所有 refresh token（防泄露）

**Access Token**：
- 同样通过 httpOnly cookie 传递（`_set_access_cookie`，path=`/v1`），浏览器端不直接操作 token
- 15 分钟过期，通过 `/auth/refresh` 静默刷新

**Dev Token**（仅 `settings.debug=true`）：
- `GET /v1/auth/dev-token` — 自动创建 dev team + member，返回 JWT
- 用于本地开发，生产环境禁用

### 2.3 API Key 认证（Agent）

**生成**：
```
1. Admin 调用 POST /teams/{teamId}/agents
2. 后端生成: sk-syn-{32字节随机}.{agentId前8位}
3. 存储 SHA-256(apiKey)，返回明文一次
4. 明文仅在创建响应中返回，此后不可获取
```

> Key 前缀 `sk-syn-` 由 `settings.api_key_prefix` 配置，`get_current_actor()` 据此自动选择 API Key 验证路径。

**存储**：
```sql
-- 概念示意，非生产表结构
agent.api_key_hash = SHA256(apiKey)  -- 仅存哈希
agent.api_key_prefix = 'sk-syn-...'  -- 前 12 位用于识别
```

**使用**：
```http
Authorization: Bearer sk-syn-a1b2c3d4...7a3b2c1d
```

服务端验证（`src/auth.py: verify_api_key()`）：
```
1. 提取 API Key → SHA-256 → 查 agent.api_key_hash
2. 命中 → 检查 agent.status = active
3. 通过 → 返回 ActorInfo(actor_type="agent", team_id=..., name=...)
4. Agent 身份注入请求上下文
```

**吊销**：
```
DELETE /agents/{agentId} → 硬删除 Agent 记录（含 api_key_hash）
                          → 后续请求立即失效（token 验证失败）
                          → 活跃 WS 连接在下次心跳/重连时断开
```

---

## 3. 授权（Authorization）

### 3.1 三层授权模型（P10 更新）

Synapse 的授权体系从 P9 的 **Member RBAC + Agent actor_type** 双层演进为 P10 的三层：

**第一层：`project_actor_roles` RBAC**（`src/dependencies.py: require_project_role()`）

| 角色 | 作用域 | 说明 |
|------|------|------|
| `admin` | Project | 管理项目设置、分配角色、删除项目 |
| `lead` | Project | 审批授权请求、管理 Workflow、分配任务 |
| `member` | Project | 查看项目、创建/认领 Task |
| `orchestrator` | Project | 规划 Workflow + 验收交付（通常配合 WorkflowRole 使用） |
| `builder` | Project | 执行任务 + 提交验证（通常配合 WorkflowRole 使用） |
| `steward` | Project | 独立审查、安全审计（远期引入） |

`require_project_role("admin", "lead")` 作为 FastAPI 依赖注入到所有项目级端点。替代旧 `require_role()` 的 Team 级 RBAC（旧 `member.role` 保留兼容但不作为主力路径）。Worker（actor_type=agent/human）均匀对待——权限只看 `project_actor_roles` 角色，不看 actor_type。

**第二层：`WorkflowRole` per-Workflow 职能**（`src/models/workflow.py`）

同一 Worker 在不同 Workflow 中可承担不同角色（`orchestrator` / `builder` / `steward` 预留）。WorkflowRole 控制"谁在这个 Workflow 中做什么"，与 ProjectActorRole 正交。详见 `docs/architecture.md` §4.5.6。

**第三层：`AuthorizationRequest` 异步授权管道**（P10-B20~B23/B31）

Worker 遇到权限不足 → 系统自动创建 `api_auth` 请求 → 返回 202 而非 403 → Admin 审批 → Worker 轮询获得授权并重试。详见 §3.4。

**超级管理员绕过**：`user.is_super_admin`（P10-B17）绕过所有 `require_role()` / `require_project_role()` 检查。仅限 `/admin/*` 端点家族使用。

**旧 `require_role()` 状态**：保留兼容旧端点（`/admin/teams/*`），但不作为新功能的主力守卫。新端点统一使用 `require_project_role()`。

### 3.2 权限矩阵

> P10 更新：角色从旧 admin/lead/member 扩展为 6 种 ProjectRole（admin/lead/member/orchestrator/builder/steward）。以下表格用 admin/lead/member 代表三级权限等级（admin=最高，lead=高，member=基础）。orchestrator/builder 的权限与 member 同级（可查看/创建/认领），额外权限由 WorkflowRole 赋予。Worker（含 agent 和 human）统一通过 `project_actor_roles` + `require_project_role()` 校验。

#### Team 级别

| 操作 | admin | lead | member | 守卫方式 |
|------|:-----:|:----:|:------:|------|
| 查看 Team 信息 | ✅ | ✅ | ✅ | Team member 验证 |
| 修改 Team 设置 | ✅ | ❌ | ❌ | `require_role("admin")` |
| 邀请/移除成员 | ✅ | ❌ | ❌ | `require_role("admin")` |
| 修改成员角色 | ✅ | ❌ | ❌ | `require_role("admin")` |
| 注册/管理 Worker | ✅ | ❌ | ❌ | `require_role("admin")` |

#### Project 级别

| 操作 | admin | lead | member | 守卫方式 |
|------|:-----:|:----:|:------:|------|
| 创建 Project | ✅ | ✅ | ❌ | Team member + actor_type 检查 |
| 查看 Project | ✅ | ✅ | ✅ | `require_project_role()` |
| 归档/删除 Project | ✅ | ❌ | ❌ | `require_project_role("admin")` |
| 管理角色分配 | ✅ | ❌ | ❌ | `require_project_role("admin")` |
| 审批 AuthorizationRequest | ✅ | ✅ | ❌ | `require_project_role("admin", "lead")` |

#### Task 级别

| 操作 | admin | lead | member | Worker (owner) | 守卫方式 |
|------|:-----:|:----:|:------:|:------------:|------|
| 创建 Task | ✅ | ✅ | ✅ | ✅ | `require_project_role()` |
| 更新 Task 内容 | ✅ | ✅ | ✅ (自己的) | ✅ (自己的) | ownership OR role |
| 分配 Task | ✅ | ✅ | ❌ | ❌ | `require_project_role("admin", "lead")` |
| 认领 Task | ✅ | ✅ | ✅ | ✅ | `require_project_role()` + 额外允许 |
| 提交验证 | ✅ | ✅ | ✅ (自己的) | ✅ (自己的) | ownership OR role |
| 报告 blocker | ❌ | ❌ | ❌ | ✅ | actor_type 检查 |
| 取消/终止 Task | ✅ | ✅ | ❌ | ❌ | `require_project_role("admin", "lead")` |

#### AuthorizationRequest 级别（P10 新增）

| 操作 | admin | lead | member | Worker (请求者) | 守卫方式 |
|------|:-----:|:----:|:------:|:-------------:|------|
| 查看项目所有请求 | ✅ | ✅ | ❌ | ❌ | `require_project_role("admin", "lead")` |
| 查看自己的请求 | ✅ | ✅ | ✅ | ✅ | ownership |
| 响应请求（approve/deny） | ✅ | ✅ | ❌ | ❌ | `require_project_role("admin", "lead")` |
| 发送 heartbeat | ✅ | ✅ | ✅ | ✅ (自己的) | ownership |
| 取消自己的请求 | ✅ | ✅ | ✅ | ✅ (自己的) | ownership |

> **Worker 403→202 拦截**（P10-B31 S-065）：Worker 执行操作遇 403 → 系统自动创建 `api_auth` AuthorizationRequest → 返回 202 而非 403 → Worker 轮询 `GET /workers/me/authorization-requests?status=pending` 等待审批 → 审批通过后重试原操作。

#### Batch 级别 / Verification 级别 / Event 级别

权限与 Task 级别一致，统一通过 `require_project_role("admin", "lead")` 守卫管理操作，`require_project_role()` 守卫查看操作。

---

### 3.3 Agent Capability 门禁

> ⚠️ **当前状态**：Capability 数据已结构化存储（Agent 握手时声明 → `Agent.capability_tags` + `Capability` 表），但**端点 enforcement 尚未激活**。Agent 的权限控制目前完全依赖各端点的 `actor_type` 检查（见 §3.1 第二层），而非 Capability 匹配。

**设计意图**（Phase 2 落地）：

```
请求到达
  → 验证 API Key（AuthN）
  → 提取 Agent 身份（actor_type="agent"）
  → 检查端点级 actor_type 权限（当前实现）
  → 检查 Capability（Agent 是否声明了此能力）← 待激活
  → 检查速率限制（部分待实现）
  → 执行操作
```

**示例**（目标状态）：
- Agent 想 `POST /tasks/{id}/submit` → actor_type ✅ → Capability 检查：需要 `task.update` ✅ → 执行
- Agent 想 `POST /projects/{id}/tasks` → actor_type ✅ → Capability 检查：需要 `task.create` → 如未声明 → `403 FORBIDDEN_CAPABILITY_REQUIRED`

---

### 3.4 AuthorizationRequest 异步授权生命周期（P10 新增）

Worker（特别是 AI Agent）执行操作时可能因权限不足收到 403。P10 议题 3 引入 AuthorizationRequest 管道，将同步的"拒绝访问"改为异步的"等待审批"。

**状态机**：

```
                  ┌─────────┐
                  │ pending │ ← 创建时默认（TTL 1 小时）
                  └────┬────┘
         ┌─────────┬───┴───┬──────────┐
         ▼         ▼       ▼          ▼
    ┌────────┐ ┌──────┐ ┌──────┐ ┌──────────┐
    │approved│ │denied│ │expired│ │cancelled │
    └────────┘ └──────┘ └──────┘ └──────────┘
```

| 状态 | 触发 | 说明 |
|------|------|------|
| `pending` | 创建时 | 等待审批，TTL 默认 1 小时，heartbeat 可延长 |
| `approved` | Admin 调用 `PATCH respond` | Worker 获得授权，可重试原操作 |
| `denied` | Admin 调用 `PATCH respond` | 拒绝，Worker 收到拒绝通知 |
| `expired` | TTL 到期 | 系统级联失效：`expires_at < now()` 且未响应 |
| `cancelled` | Worker 调用 `PATCH cancel` | Worker 主动取消（如操作已不需要） |

**双请求类型**：

| 类型 | 用途 | 示例 |
|------|------|------|
| `api_auth` | 声明式操作授权—Worker 请求执行特定 API 操作的权限 | "请批准我执行 `task.assign` 将 task_xxx 分配给 worker_yyy" |
| `interactive_prompt` | 交互式人机问答—Worker 在操作过程中需要人类决策 | "你认为这个设计选择 A/B/C 哪个更合适？" |

**Worker 403→202 拦截流程**（P10-B31 S-065）：

```
Worker 请求 POST /v1/projects/{pid}/tasks/{tid}/assign
  → require_project_role("admin", "lead") → 403
  → 拦截器自动创建 AuthorizationRequest(type=api_auth, operation="task.assign")
  → 返回 202 { authorization_request_id, status: "pending", retry_after: 5 }
  → Worker 轮询 GET /workers/me/authorization-requests?status=pending
  → Admin 通过 WS/Email/Webhook 收到通知（议题 ⑦）
  → Admin PATCH respond { status: "approved" }
  → Worker 发现请求 approved → 重试原 POST 请求 → 成功
```

**通知通道**（议题 ⑦）：
- **WS Push**（B32）：Admin WebSocket 实时推送新请求
- **Email**（B33）：Admin 不在线时发送邮件通知
- **Webhook**（B34）：Project 级 webhook URL，第三方集成
- **WebPush**（S-066 远期）：浏览器推送通知

**关键约束**：
- 每个 Worker 最多 5 个 pending 请求（`max_pending_per_worker = 5`）
- 同一个 Worker 对同一 resource 的重复请求 → 返回已有 pending 请求（幂等）
- `responded_by_worker_id` 记录审批人 — 不可变审计链
- `DecisionAudit`（P10-B35）记录每次审批决策，带 risk_level 评估

---

## 4. 多租户隔离

### 4.1 隔离架构

```
请求到达
  → AuthN 提取 ActorInfo（含 teamId）
  → 所有数据访问层注入 WHERE teamId = :teamId
  → 跨 Team 访问 → 404（不暴露存在性）
```

### 4.2 实现策略

**数据库层**（应用层 WHERE 条件，MVP 不做 RLS）：

```sql
-- 所有查询必须带 teamId 条件
-- Team 隔离
SELECT * FROM task t
JOIN project p ON t.project_id = p.id
WHERE p.team_id = :currentTeamId;

-- Agent 数据隔离
SELECT * FROM task
WHERE owner_type = 'agent'
  AND owner_id = :currentAgentId
  AND project_id IN (
    SELECT id FROM project WHERE team_id = :currentTeamId
  );
```

> 设计决策 D-006 解释了为什么 MVP 选择应用层隔离而非数据库 RLS。

### 4.3 跨 Team 操作

**默认禁止**。需要跨 Team 协作的场景（如开源项目的外部贡献者），走独立的 Guest 机制：

| 机制 | 说明 |
|------|------|
| Guest Member | 仅可访问特定 Project，不可查看 Team 全局 |
| Shared Project | 跨 Team 共享的 Project（未来功能，MVP 不做） |

---

## 5. Agent 沙箱约束

Agent 不同于人类——它是一段运行在外部的代码，因此需要额外约束。

### 5.1 可见性约束

| Agent 可以看到 | Agent 看不到 |
|---------------|-------------|
| 分配给自己的 Task | 分配给其他 Agent 的 Task |
| 自己 Task 所在 Project 的名称和描述 | Project 中其他人的 Task 列表 |
| 自己 Task 的评论 | Team 成员列表（除 ID 外） |
| 自己 Task 的 Event 时间线 | Team 级别的 Event 流 |
| 所在 Team 的 ID 和名称 | 其他 Agent 的配置和能力 |

### 5.2 操作约束

| 允许 | 禁止 |
|------|------|
| 更新自己 Task 的状态和进度 | 修改 Task 的 owner（转移给他人） |
| 提交验证 | 通过/拒绝验证（即使是自己的） |
| 创建 Task（需 `task.create` Capability） | 删除 Task |
| 报告 blocker（`POST /tasks/{id}/blocker`） | 修改/删除他人评论 |
| 查看 Project 基础信息 | 修改 Project 设置 |

### 5.3 速率和资源约束

| 约束 | 值 | 实现状态 |
|------|-----|:---:|
| REST 请求 | 60/min | ⬜ 计划中 |
| WebSocket 消息 | 10/s | ✅ 已实现 |
| 并发 Task 数 | `Agent.batch_size` 控制单批任务量 | ✅ 已实现 |
| Agent 运行时状态 | `Agent.runtime_status`（idle/busy/error）| ✅ 已实现 |
| Task 心跳超时 | Agent 心跳检测丢失 → paused | ✅ 已实现 |

---

## 6. API Key 生命周期管理

> 📎 **已提取到 `security-model-appendix.md` §1。** 整节为 Phase 2 aspirational——当前仅 Key 生成+吊销已实现，轮换/过渡期/闲置检测/异常检测均未实现。S-036 全量对齐审计将决定保留/删除/迁移。

---

## 7. 审计日志

### 7.1 Event 即审计日志

Synapse 的 Event 实体天然就是审计日志。不需要单独的审计表。

### 7.2 安全相关事件

当前已实现 **60 种事件类型**（`src/constants.py: EventType`），涵盖 Task/Batch/Worker/Verification/AuthorizationRequest/Workflow/ProtectionReport/CircuitBreaker/DecisionAudit/Conversation 等全生命周期。TokenUsage 为独立实体（`src/models/token_usage.py`），不产生 Event 记录。

| 类别 | 已实现事件类型 | 状态 |
|------|--------------|:---:|
| Worker 生命周期 | `worker.registered`, `worker.handshake`, `worker.deactivated`, `worker.heartbeat`, `worker.runtime.idle`, `worker.runtime.busy`, `worker.runtime.error` | ✅ |
| Task 工作流 | `task.created`, `task.updated`, `task.readied`, `task.assigned`, `task.claimed`, `task.submitted`, `task.paused`, `task.resumed`, `task.completed`, `task.rejected`, `task.cancelled`, `task.lease_expired`, `task.blocker_reported`, `task.review_timeout`, `task.escalated` | ✅ |
| Batch 管理 | `batch.created`, `batch.completed` | ✅ |
| Verification | `verification.executed`, `verification.reset`, `review.overdue` | ✅ |
| Project | `project.created`, `project.updated`, `project.archived` | ✅ |
| Project Role（P10 新增） | `worker.project_role.assigned`, `worker.project_role.changed`, `worker.project_role.revoked` | ✅ |
| AuthorizationRequest（P10 新增） | `authorization_request.created`, `authorization_request.responded`, `authorization_request.expired`, `authorization_request.cancelled`, `authorization_request.heartbeat` | ✅ |
| Workflow（P10 新增） | `workflow.created`, `workflow.updated`, `workflow.completed` | ✅ |
| WorkflowRole（P10 新增） | `workflow_role.assigned`, `workflow_role.changed`, `workflow_role.revoked` | ✅ |
| Conversation（P10 新增） | `conversation.message.created`, `conversation.message.resolved` | ✅ |
| ProtectionReport（P10 新增） | `protection_report.created`, `protection_report.completed` | ✅ |
| CircuitBreaker（P10 新增） | `circuit_breaker.opened`, `circuit_breaker.closed` | ✅ |
| DecisionAudit（P10 新增） | `decision_audit.recorded` | ✅ |
| Member | `member.invited`, `member.removed` | ✅ |
| Team | `team.created`, `team.updated` | ✅ |
| 审计/分析 | `analysis.created`, `scan.executed`, `skill.created`, `skill.updated`, `skill.deprecated` | ✅ |

> 以下事件类型在设计文档中提及但**尚未实现**：`worker.key_rotated`, `worker.key_revoked`, `member.left`, `auth.failed`。将在 Phase 2 随对应功能上线。

### 7.3 审计查询

```sql
-- 查看某个 Worker 的所有安全事件
SELECT * FROM event
WHERE team_id = :teamId
  AND target_type = 'worker'
  AND target_id = :workerId
  AND event_type LIKE 'worker.%'
ORDER BY created_at DESC;

-- 查看某个 Member 的管理操作
SELECT * FROM event
WHERE actor_type = 'member'
  AND actor_id = :memberId
  AND event_type IN ('worker.registered', 'member.removed')
ORDER BY created_at DESC;
```

---

## 8. 数据传输安全

> ⚠️ **当前状态**：应用层仅实现 CORS 白名单 + httpOnly cookie。HTTPS 终止、HSTS、CSP、HTTP→HTTPS 重定向均为**部署层/反向代理职责**（Nginx/CDN/负载均衡），应用层不直接设置。以下标注「部署层」的功能需在部署文档中覆盖，不在应用代码中实现。

| 层面 | 措施 | 状态 |
|------|------|:---:|
| 传输 | 全站 HTTPS（TLS 1.3），HTTP → HTTPS 301 重定向 | ⬜ 部署层 |
| HSTS | `Strict-Transport-Security: max-age=31536000; includeSubDomains` | ⬜ 部署层 |
| API Key | 仅在 Authorization 头传递，不出现在 URL 参数中 | ✅ |
| WebSocket Auth | API Key 通过查询参数 `?token=<jwt_or_apikey>` 传递，`ws.py: _verify_ws_token()` 独立验证 | ✅ |
| CORS | 白名单域名（`frontend_url`），`allow_credentials=True`，禁止 `*` | ✅ |
| CSP | Content-Security-Policy 头限制脚本来源 | ⬜ 部署层 |
| Cookie | access_token + refresh_token 均为 httpOnly + secure（非 debug）+ SameSite=Lax | ✅ |

---

## 9. MVP 与后续安全增强

### 9.1 当前实现状态（P10）

| 功能 | 状态 |
|------|:---:|
| JWT + OAuth 2.0 (GitHub) | ✅ |
| Email/Password 注册+登录 | ✅ P10-B10 |
| Dev Token（debug 模式） | ✅ |
| API Key 生成 + SHA-256 哈希存储 | ✅ |
| 统一 `get_current_actor()` 认证入口 | ✅ |
| `require_project_role()` 项目级 RBAC 守卫 | ✅ P10-B18 |
| `require_super_admin()` 全系统绕过 | ✅ P10-B17 |
| AuthorizationRequest 异步授权管道（POST/GET/PATCH/Heartbeat） | ✅ P10-B22 |
| Worker 403→202 拦截 + auto-grant 重试 | ✅ P10-B31 |
| Workflow + WorkflowRole 数据模型 | ✅ P10-B24 |
| ProjectActorRole 数据模型（6 角色） | ✅ P10-B18 |
| Team 级数据隔离（应用层 WHERE） | ✅ |
| Worker Capability 数据存储 | ✅ |
| Worker Capability 端点 enforcement | ⬜ 计划中 |
| Event 审计日志（60 种事件类型） | ✅ P10 |
| WebSocket 认证 + 限流（10/s） | ✅ |
| WS Push 授权通知（议题 ⑦） | ✅ P10-B32 |
| Email 授权通知（议题 ⑦） | ✅ P10-B33 |
| Webhook 授权通知（议题 ⑦） | ✅ P10-B34 |
| REST 速率限制（60/min） | ⬜ 计划中 |

### 9.2 后续增强（Phase 2+）

| 功能 | 说明 |
|------|------|
| API Key 轮换 + 过渡期 | `rotate-key` 端点 |
| API Key 异常检测 | 异常 IP/地域告警 |
| Agent Capability 门禁激活 | 端点 enforcement |
| REST 速率限制 | 全局限流 + Agent 级限流 |
| 2FA/MFA | 人类用户二次验证 |
| SSO/SAML | 企业单点登录 |
| 细粒度权限 | Team 级自定义角色 |
| 审计报告导出 | 合规需求 |
| 密钥保险箱集成 | HashiCorp Vault / AWS KMS |
| SOC 2 合规 | 若做企业版 |

---

## 10. 设计决策记录

> 📎 **已提取到 `security-model-appendix.md` §2。** D-004（API Key vs OAuth）· D-005（Agent 可见性约束）· D-006（应用层隔离 vs 数据库 RLS）。

## 11. v1.1 Refresh Notes

> 📎 **已提取到 `security-model-appendix.md` §3。** 2026-07-15 P9-B81 刷新记录 + S-036 待办项清单。

## 12. 契约验证

> 📎 **已提取到 `security-model-appendix.md` §4。** data-model ↔ protocol ↔ security-model 三方交叉引用验证表（15 行 × 3 列）。

---

> **核心安全文档 v1.4**。§1-9 覆盖认证→授权→隔离→沙箱→审计→传输→MVP 状态全链路。附录内容（API Key 蓝图·ADR·刷新记录·契约验证）见 `security-model-appendix.md`。
