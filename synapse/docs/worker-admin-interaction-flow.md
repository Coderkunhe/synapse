# Worker-Admin 交互流程架构

> P10-B32~B45：议题⑦ 通知通道全链路 — Worker 侧 WS Push + HTTP Poll（B31/B32）+ Admin 侧 Email（B33）+ Webhook（B34）+ WebPush（B44/B45）= 完整四通道闭环 🎉
> 最后更新：2026-07-18（P10-B46 L5 拉通议题⑦）

## §1 概述

Synapse 协调平台中，Worker（AI Agent / CLI 工具）在执行任务时可能遇到权限不足或需要人工决策的场景。系统通过 **AuthorizationRequest** 机制处理这些场景。

### Worker 侧：双通道发现

Worker 通过两条互补通道发现待处理的授权请求：

| 通道 | 延迟 | 说明 |
|------|:--:|------|
| **WS Push**（主） | <1s | /v1/ws → auto-subscribe → push 即时通知 |
| **HTTP Poll**（fallback） | ≤30s | GET /workers/me/authorization-requests · WS 断连时自动回退 |

### Admin 侧：四通道通知

Admin 通过四条互补通道接收授权请求通知：

| 通道 | 延迟 | Batch | 说明 |
|------|:--:|:--:|------|
| **WS Push** | <1s | B32 | 团队广播 — Admin Web UI 实时感知 |
| **Email** | 秒级 | B33 | 邮件通知 — Human admin 异步感知 |
| **Webhook** | 秒级 | B34 | HTTP POST — 外部系统集成 |
| **WebPush** | <1s | B44/B45 | 浏览器推送 — Admin 桌面通知 |

```
┌──────────────────────────────────────────────────────────┐
│  Worker (CLI / Agent)                                    │
│    │                                                     │
│    ├── WebSocket Push (主通道, <1s)                       │
│    │   └─ /v1/ws → auto-subscribe → push 即时通知         │
│    │                                                     │
│    └── HTTP Poll (fallback, ≤30s)                         │
│        └─ GET /workers/me/authorization-requests          │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  Synapse API                                             │
│    ├─ require_project_role → 403→202 拦截器 (B31)         │
│    ├─ authorization_service → 四通道通知分发              │
│    │   ├─ WS Push to Worker (B32)                        │
│    │   ├─ Email to Admins (B33)                          │
│    │   ├─ Webhook POST (B34)                             │
│    │   └─ WebPush to Admin browsers (B44/B45)            │
│    └─ auto-grant on approval (B31)                       │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  Admin                                                  │
│    ├─ Web UI: /approvals → PATCH respond → approve/deny  │
│    ├─ Email: auth_request_notification 模板              │
│    ├─ Webhook: HTTP POST event to external URL           │
│    └─ Browser: Service Worker push → notification        │
└──────────────────────────────────────────────────────────┘
```

**两种请求类型**：

| 类型 | 触发条件 | 示例场景 |
|------|---------|---------|
| `api_auth` | Worker 尝试访问其没有角色的 Project 资源 | Worker 第一次在 Project 上执行操作 |
| `interactive_prompt` | 系统/Admin 需要 Worker 的操作者做决策 | handoff 确认、方案选择、版本号输入 |

---

## §2 场景一：Worker 请求项目权限（api_auth）

### §2.1 HTTP 202 路径（B31 已实现）

```
Worker 发起 API 请求（带 API Key）
  → require_project_role 检查
    ├─ 有 role → 放行 ✅
    └─ 无 role → _infer_operation() 推断操作
         → authorization_service.create_authorization_request()
         → raise AuthorizationPendingError(status_code=202)
              {
                "error": "authorization_pending",
                "details": {
                  "authorization_request_id": "ar_xxx",
                  "status": "pending"
                }
              }
```

### §2.2 通知通道分发（B32→B45 四通道）

`create_authorization_request()` 完成后依次触发四条通知通道：

```
authorization_service.create_authorization_request()
  │
  ├─ [B32] WS Push to Worker (fire-and-forget)
  │   └─ ws_manager.broadcast_to_actor(worker_id, {
  │        "type": "event",
  │        "data": {
  │          "event_type": "authorization_request.created",
  │          "authorization_request_id": "ar_xxx",
  │          "status": "pending",
  │          "request_type": "api_auth",
  │          "operation": "POST:/v1/projects/p1/tasks"
  │        }
  │      })
  │
  ├─ [B33] Email to Project Admins (fire-and-forget)
  │   └─ notify_project_admins() → list admin/lead Workers
  │       → Worker.user_id → User.email
  │       → send_email(auth_request_notification.html)
  │
  ├─ [B34] Webhook POST (fire-and-forget)
  │   └─ notify_webhook() → Project.webhook_url
  │       → httpx POST {event_type, request_id, worker_name, ...}
  │
  └─ [B45] WebPush to Admin Browsers (fire-and-forget)
      └─ notify_webpush() → list admin/lead Workers
          → User.push_subscriptions → pywebpush send
```

Worker 收到 WS push → 展示给用户 "等待管理员审批..." → 无需轮询，等待 push 通知审批结果。

Admin 通过 Email / WebPush / Webhook 收到通知 → Web UI /approvals 审批。

### §2.3 管理员审批 → Auto-Grant → Worker 重试

```
Admin Web UI: /approvals → 看到 pending request → PATCH respond
  → authorization_service.respond_to_request()
    ├─ status = "approved" + request_type = "api_auth"
    │   → _auto_grant_project_membership(worker_id, project_id, role="member")
    ├─ event_store.record()           [团队广播]
    └─ ws_manager.broadcast_to_actor(record.worker_id, ...)  [Worker push]
         {
           "type": "event",
           "data": {
             "event_type": "authorization_request.responded",
             "authorization_request_id": "ar_xxx",
             "status": "approved",
             "request_type": "api_auth"
           }
         }

Worker 收到 "approved" push → 重试原始请求
  → require_project_role 检查 → member role ✅ → 放行 🎉
```

**Auto-Grant 安全策略**：
- 仅 `api_auth` 类型触发（`interactive_prompt` 不触发）
- 仅授予最小权限 `member` 角色
- Worker 已有角色时保留不降级（`_auto_grant_project_membership` L378-379）

---

## §3 场景二：系统请求人工决策（interactive_prompt）

### §3.1 Prompt 创建

两种创建路径：

| 路径 | 触发方式 | 示例 |
|------|---------|------|
| **Handoff** | A2A 对话中检测到需要人工决策 | `POST /v1/conversations/{id}/messages` + message_type="handoff_request" |
| **Admin 手动** | Admin 通过 API 直接创建 | `POST /v1/authorization-requests` |

### §3.2 Worker 发现（双通道）

```
主通道 (WS Push):
  authorization_service.create_authorization_request()
    → ws_manager.broadcast_to_actor(worker_id, {
        "event_type": "authorization_request.created",
        "request_type": "interactive_prompt",
        "prompt_type": "confirm",    // or "choice" / "input"
        "prompt_message": "..."
      })
  Worker 在线 → 即时收到 → 展示给用户（CLI/UI 渲染）

Fallback (HTTP Poll):
  Worker WS 断连 → 每 30s GET /workers/me/authorization-requests?status=pending
  → 发现 pending prompts → 展示给用户
```

### §3.3 CLI 渲染 → 用户响应 → PATCH respond

```
Worker 收到 prompt 后，根据 prompt_type 渲染给用户：

  prompt_type = "confirm":  展示问题 + [Yes] [No]
  prompt_type = "choice":   展示选项列表，用户选一个
  prompt_type = "input":    展示输入框，用户自由输入

用户响应 → Worker PATCH /v1/authorization-requests/{id}/respond
  → authorization_service.respond_to_request()
    → ws_manager.broadcast_to_actor(worker_id, {
        "event_type": "authorization_request.responded",
        "status": "approved"  // or "denied" for confirm/cancel
      })
```

---

## §4 WebSocket 协议详解

### §4.1 连接认证

```
GET /v1/ws?token=<api_key_or_jwt>

认证流程:
  1. Token 以 "sk-syn-" 开头 → verify_api_key() → Worker
  2. 否则 → decode_access_token() → Human (JWT)
  3. 验证失败 → 接受连接后立即 close(code=4001)
```

### §4.2 自动订阅

Worker 连接成功后，系统自动订阅以下 topic：

| Topic | 触发时机 |
|-------|---------|
| `authorization_request.created` | 新授权请求创建 |
| `authorization_request.responded` | 管理员审批/拒绝 |
| `authorization_request.expired` | 请求超时过期 |
| `authorization_request.cancelled` | Worker 重启级联取消 |

Worker 不需要发送 `{"type": "subscribe", "topics": [...]}` 消息 — 系统在连接时自动处理。

### §4.3 事件消息格式

**Worker 专用 push**（via `broadcast_to_actor`）— 简化版，直接可操作：

```json
{
  "type": "event",
  "data": {
    "event_type": "authorization_request.created",
    "authorization_request_id": "ar_xxx",
    "status": "pending",
    "request_type": "api_auth",
    "operation": "POST:/v1/projects/p1/tasks"
  }
}
```

**团队广播**（via `event_store → broadcast_to_team`）— 完整审计记录：

```json
{
  "type": "event",
  "data": {
    "id": "evt_xxx",
    "event_type": "authorization_request.created",
    "actor_type": "worker",
    "actor_id": "w_xxx",
    "target_type": "authorization_request",
    "target_id": "ar_xxx",
    "payload": {
      "project_id": "p1",
      "worker_id": "w_xxx",
      "request_type": "api_auth",
      "operation": "POST:/v1/projects/p1/tasks"
    },
    "team_id": "t_xxx",
    "created_at": "2026-07-18T12:00:00Z"
  }
}
```

**Worker 客户端去重**：按 `authorization_request_id` 去重。简化版用于快速 UI 响应，完整版用于审计日志。

### §4.4 心跳保活

- 服务端每 30s 发送 `{"type": "ping"}`
- 客户端回复 `{"type": "ping"}` → 服务端更新 `last_pong`
- 60s 无 pong → 断开连接
- Worker 断连后自动回退到 HTTP Poll

---

## §5 数据模型总览

### AuthorizationRequest 状态机

```
                    ┌─────────┐
        create ──→  │ pending │  ← Worker heartbeat 续期
                    └────┬────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
        approved      denied      expired
        (auto-grant   (记录拒绝    (超时自动
         if api_auth)  原因)       过期)


Worker 重启 ──→ pending 全部标记为 cancelled
```

### 两种请求类型的字段映射

| 字段 | api_auth | interactive_prompt |
|------|:--:|:--:|
| `operation` | ✅ 必填 | ❌ |
| `target_resource_type` | ✅ 可选 | ❌ |
| `target_resource_id` | ✅ 可选 | ❌ |
| `prompt_type` | ❌ | ✅ 必填 (confirm/choice/input) |
| `prompt_message` | ❌ | ✅ 必填 |
| `prompt_choices_json` | ❌ | ✅ choice 类型必填 |
| `response_data_json` | ❌ | ✅ Worker 响应时填写 |

---

## §6 端点速查表

| 端点 | 方法 | 认证 | 说明 |
|------|:--:|------|------|
| `/v1/ws` | WS | API Key / JWT | WebSocket 连接（Worker 自动订阅 auth topics） |
| `/v1/authorization-requests` | POST | JWT/API Key | 创建授权请求 |
| `/v1/authorization-requests/{id}` | GET | API Key (owner) / JWT (admin) | 查询单个请求状态 |
| `/v1/authorization-requests/{id}/respond` | PATCH | JWT (admin) | 审批/拒绝 请求 |
| `/v1/authorization-requests/{id}/heartbeat` | PATCH | API Key (owner) | Worker 心跳续期 |
| `/v1/workers/me/authorization-requests` | GET | API Key | Worker 自查询 pending 请求（HTTP fallback） |

---

## §7 时序图

### 场景一：api_auth（WS 在线）

```mermaid
sequenceDiagram
    participant CLI as Worker CLI
    participant WS as Synapse WS
    participant API as Synapse API
    participant Admin as Admin Web UI

    CLI->>WS: connect /v1/ws?token=sk-...
    WS-->>CLI: {"type": "connected"} (auto-subscribed to auth topics)

    CLI->>API: POST /v1/projects/p1/tasks
    API->>API: require_project_role → Worker has no role
    API->>API: create_authorization_request(api_auth)
    API->>WS: broadcast_to_actor(worker_id, auth_request.created)
    WS-->>CLI: {"type": "event", "data": {"event_type": "authorization_request.created", ...}}
    API-->>CLI: 202 { authorization_request_id: "ar_xxx" }

    CLI-->>CLI: Show: "Waiting for admin approval..."

    Admin->>API: PATCH /authorization-requests/ar_xxx/respond {status: "approved"}
    API->>API: respond_to_request → auto-grant member role
    API->>WS: broadcast_to_actor(worker_id, auth_request.responded)
    WS-->>CLI: {"type": "event", "data": {"event_type": "authorization_request.responded", "status": "approved"}}

    CLI->>API: Retry POST /v1/projects/p1/tasks
    API-->>CLI: 200 OK ✅
```

### 场景二：interactive_prompt（WS 断连 → Fallback）

```mermaid
sequenceDiagram
    participant CLI as Worker CLI
    participant WS as Synapse WS
    participant API as Synapse API
    participant Admin as Admin Web UI

    Note over CLI,WS: WS disconnected (network issue)

    Admin->>API: POST /authorization-requests (interactive_prompt for Worker)
    API->>API: create_authorization_request → broadcast_to_actor (dropped, Worker offline)

    loop Every 30s (HTTP Poll Fallback)
        CLI->>API: GET /workers/me/authorization-requests?status=pending
        API-->>CLI: [{id: "ar_yyy", request_type: "interactive_prompt", prompt_type: "confirm", ...}]
    end

    CLI-->>CLI: Render prompt to user: "Proceed with migration? [Y/n]"
    CLI-->>CLI: User selects: Yes

    CLI->>API: PATCH /authorization-requests/ar_yyy/respond {status: "approved", response_data: "Yes"}

    Note over CLI,WS: WS reconnects → auto-subscribe → back to push mode
    CLI->>WS: connect /v1/ws?token=sk-...
    WS-->>CLI: {"type": "connected"}
```

### Worker 重连流程

```mermaid
sequenceDiagram
    participant CLI as Worker CLI
    participant WS as Synapse WS
    participant API as Synapse API

    Note over CLI,WS: Worker restarted — WS disconnected

    CLI->>WS: connect /v1/ws?token=sk-...
    WS->>WS: verify token → auto-subscribe auth topics
    WS-->>CLI: {"type": "connected"}

    CLI->>API: POST /agents/{id}/handshake
    API->>API: cancel_worker_requests(worker_id) → all pending → cancelled
    API->>WS: broadcast_to_actor(worker_id, auth_request.cancelled) [×N]
    WS-->>CLI: {"type": "event", "data": {"status": "cancelled", ...}}

    CLI->>API: GET /workers/me/authorization-requests?status=pending
    API-->>CLI: [] (all cleared)

    Note over CLI,API: Clean state — ready for new tasks
```
