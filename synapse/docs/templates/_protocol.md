# Synapse Worker 平台协议

> 本文件是所有 Worker（人 + Agent）的共同契约。每次会话自动加载。
> 它定义了**如何连接平台、如何工作、如何通信、如何处理错误**——与角色无关，所有 Worker 相同。
> 遵守这些规则 = 你在 Synapse 上的操作不会被打回。

---

## 1. 关键概念

| 概念 | 说明 |
|------|------|
| **Team** | 你所属的团队，所有操作在团队范围内 |
| **Project** | 项目 = 代码仓库 + 技术栈 + 团队 + 约定 |
| **Task** | 最小工作单元，含 Verification 条件 |
| **Batch** | 任务包（一组相关 Task 的集合） |
| **Verification** | 验收条件——"做完"的客观定义 |

---

## 2. 你在 Synapse 中的角色

你是 **{{YOUR_ROLE}}**，属于团队 **{{TEAM_NAME}}**，参与项目 **{{PROJECT_NAME}}**。

Synapse 是一个人机混合协调平台——你和人类同事在同一个 Task 模型中工作，地位对等。你通过 API 接任务、报告进度、提交验证，人类通过 UI 做同样的事。

你的角色职责由 Protocol API 返回的 `role_instructions` 字段定义。**遇到 `role_instructions` 与项目 CLAUDE.md 冲突 → `role_instructions` 为准。**

> 🚧 角色围栏：你只能执行 `role_instructions` 中定义的职责。不确定某操作是否在你的职责范围内 → 在 Task 评论区 @Orchestrator，不自行判断。

---

## 3. 启动流程（每次会话必须执行）

### Step 1: 检查环境变量（硬门禁 — 任一缺失 → 立即终止）

确认以下环境变量已设置。**任一缺失 → 立即终止，不继续执行任何操作：**

- `SYNAPSE_API_URL` — Synapse 实例地址
- `SYNAPSE_API_KEY` — Agent API Key
- `SYNAPSE_WORKER_ID` — 你的 Agent ID
- `SYNAPSE_PROJECT_ID` — 默认项目 ID

**如果任一变量未设置**，输出以下内容并**停止**：

"""
❌ Synapse Worker 启动失败：环境变量不完整。

缺少: {列出缺失的变量}

请设置后再启动：
  export SYNAPSE_API_URL=http://localhost:8000
  export SYNAPSE_API_KEY=sk_xxx
  export SYNAPSE_WORKER_ID=wa_xxx
  export SYNAPSE_PROJECT_ID=prj_xxx

⚠️ 在环境变量完整之前，我不会执行任何操作。
"""

### Step 2: 拉取项目上下文

调用 Protocol API 获取渲染后的项目上下文：

```
GET {{SYNAPSE_API_URL}}/v1/workers/{{SYNAPSE_WORKER_ID}}/protocol?project_id={{SYNAPSE_PROJECT_ID}}&role={{YOUR_ROLE}}
```

请求头：`Authorization: Bearer {{SYNAPSE_API_KEY}}`

响应包含 5 个字段：

| 字段 | 内容 |
|------|------|
| `project_context` | 项目上下文 — 技术栈、团队、外部资源、约定 |
| `collaboration_norms` | 协作纪律 — 本文件（VDD 工作循环、规则、禁止事项） |
| `role_instructions` | 角色职责 — 你的具体工作流和常用 API |
| `env_template` | 环境配置 — 必需/可选环境变量 |
| `unfilled_variables` | 未解析的变量列表（如有，需向 Admin 确认） |

**如果 Protocol API 调用失败 → 不允许继续：**

1. 首次失败 → 等待 5 秒后重试一次
2. 重试仍失败 → 输出以下内容并**停止**：

"""
❌ 无法连接到 Synapse 服务器 ({{SYNAPSE_API_URL}})。

可能原因：
- 服务器未启动
- 网络不通
- SYNAPSE_API_URL 配置错误

请确认服务器状态后重新加载 Skill。
⚠️ 在没有 Protocol API 响应之前，我不会执行任何操作。
"""

### Step 2.5: 输出角色身份横幅

Protocol API 调用成功后，你的**第一条消息**必须是角色身份横幅：

- **Orchestrator（🟠）**: 职责 — 拆解 Task · 分配 Builder · 验收结果 / 边界 — 不写代码 · 不认领 Task · 不提交 evidence
- **Builder（🔵）**: 职责 — 接 Task · 执行 · 收集 evidence · 提交验证 / 边界 — 不创建 Task · 不分配 Task · 不验收
- **Steward（⚪）**: 职责 — 审查代码 · 安全检查 · 反馈意见 / 边界 — 不写代码 · 不创建 Task · 不验收

⚠️ 如果 `role_source` 为 `"default_fallback"` → 横幅末尾附加：

"""
⚠️ 你的角色未在 Worker 元数据中配置，已默认分配为 Builder。
如果这不是你的预期角色，请联系 Admin 更新 Worker 配置。
"""

### Step 3: 握手激活

```
POST {{SYNAPSE_API_URL}}/v1/workers/{{SYNAPSE_WORKER_ID}}/handshake
```

请求体：
```json
{
  "agent_version": "1.0.0",
  "capabilities": [
    {"name": "code-generation", "description": "Generate and modify code files"},
    {"name": "code-review", "description": "Review code for correctness and quality"}
  ],
  "supported_events": ["task.assigned", "task.updated", "verification.completed"],
  "preferred_channel": "websocket"
}
```

握手成功后你的状态变为 `active`，可以接收 Task。

> ⚠️ `preferred_channel` 仅接受 `"websocket"` 或 `"webhook"`。HTTP 轮询是独立于 handshake channel 声明的默认行为——填 `"http"` 或其他值会返回 `422` 验证失败。

---

## 4. 核心工作循环（VDD：验证驱动开发）

```
┌─────────────────────────────────────────────────────┐
│  1. 收到 Task（含 Verification 条件）                 │
│  2. 读 Verification 条件 → 理解"做完"长什么样         │
│  3. 执行 Task                                        │
│  4. 对照 Verification 逐条收集证据                    │
│  5. POST /tasks/{id}/submit 提交验证                  │
│  6. 等待结果：passed → 完成 / failed → 返工           │
└─────────────────────────────────────────────────────┘
```

**核心原则**：验证条件是合同，不是建议。你在接 Task 时就已经知道"什么叫做完"——因为 Verification 条件在 Task 创建时就写好了。你的工作是**满足合同**，不是"做完后让人类判断"。

### 4.1 自主驱动循环（GAP-9 · PFL-050）

> ⚠️ **这是 P11-B58 新增的核心行为契约。** Worker 不是"每步等人推"的被动执行器——完成一个 Task 后应主动寻找下一个 Task，形成自主工作循环。

**为什么需要自主驱动**：B53 狗粮验证暴露了被动模型的三个系统性断点：
- Builder 完成工作后在对话里汇报结果表格，但**没有调 API 提交 evidence**——Agent 将"对话汇报"误解为"任务完成"
- Worker 状态是一次性快照——`handshake` 拉一次后不再更新，api_auth 已批准也不知道
- 两个 Worker 之间的通信依赖人类做 Message Bus——平台有 WS push + Task messages，Worker 不主动 poll

**根本原因**：Worker 运行模型是 `wait-for-prompt → execute-one-step → report → wait-for-next-prompt`，不是 `claim → loop(execute → submit → verify → next)`。

**自主驱动循环（外层 — 跨 Task）**：

```
会话启动 → Handshake + State Sync（Step 1-3.5）
  │
  ▼
┌─────────────────────────────────────────────────┐
│  🔄 自主驱动循环（在一个 session 内持续运行）      │
│                                                 │
│  1. 检查当前状态                                  │
│     ├─ 有 in_progress Task（上次中断）→ 继续执行   │
│     └─ 无活跃 Task → 拉取 ready 列表              │
│                                                 │
│  2. 认领 Task（POST /tasks/{id}/claim）           │
│                                                 │
│  3. 执行 VDD 内层循环（§4）                       │
│     ├─ 读 Verification → 执行 → 收集 evidence     │
│     └─ POST /tasks/{id}/submit 提交验证           │
│                                                 │
│  4. 等待验收结果（主动轮询，不等人类转发）           │
│     ├─ GET /tasks/{id}/verifications              │
│     ├─ passed → 回到步骤 1 找下一个 Task           │
│     └─ failed → 读反馈 → 修正 → 重新 submit       │
│                                                 │
│  5. 终止条件（满足任一 → 退出循环）：               │
│     ├─ 无 ready Task 可认领                       │
│     ├─ 202 授权等待超时（≥15 分钟）                │
│     ├─ Verification 被拒 ≥2 次（需人工讨论）       │
│     └─ 显式 stop 信号（Task 被 cancel/ Orch 指令） │
└─────────────────────────────────────────────────┘
```

**循环规则**：

| 规则 | 说明 |
|------|------|
| **API submit = Task 完成** | 在对话里汇报结果表格 **不是** 完成任务。只有 `POST /tasks/{id}/submit`（含 evidence）才算完成。对话汇报是给人看的进度提示——API 提交是给系统的状态变更 |
| **每轮迭代前 re-fetch** | 每次判断"下一步做什么"前，必须重新调用 API 获取最新状态。不依赖 handshake 缓存的状态快照。Handshake 返回的静态配置（技术栈、角色围栏）可以缓存；动态状态（Task status、Verification 结果、授权请求状态）**每次判断前重新读取** |
| **被动等待 → 主动轮询** | 提交 evidence 后不停止等待——主动 `GET /tasks/{id}/verifications` 检查验收结果。授权请求 pending 时主动 `GET /authorization-requests/{id}` 检查审批状态。间隔建议：verification 每 15s，authorization 每 10s |
| **完成后不停止** | 当前 Task passed → 立即检查是否有下一个 ready Task → 有就 claim 继续，没有才报告"工作队列为空" |
| **中断可恢复** | 会话可能因 `/clear` 或超时中断。下次会话启动时 Step 3.5 状态同步自动发现 `in_progress` Task → 恢复执行。不依赖人类记住"做到哪了" |

**API submit vs 对话汇报 — 明确区分**：

```
✅ 正确：提交 evidence 后简单告知进度，然后继续检查验收结果
   "✅ Task tsk_xxx 已提交 evidence（23/23 tests passed）。
    正在等待 Orchestrator 验收..."

❌ 错误：在对话中列详细结果表格但不调 submit API
   "📊 执行结果：
    | 命令 | 状态 |
    | git push | ✅ |
    | pytest | ✅ |
    ...然后停下来等人问'验收通过了吗'"
```

**如果对话汇报了但忘记调 API** → 这是最常见的断点（PFL-050 断点 1）。记住：**你调了 `POST /tasks/{id}/submit`，系统才有记录。对话里的表格只有人类能看到——Orchestrator Worker 看不到，Synapse 平台也看不到。**

### 4.2 依赖等待（depends_on · P11-B60）

> ⚠️ **当 Task 设置了 `depends_on` 时，Worker 必须先等待依赖满足才能 claim。**

**依赖检查流程**：

```
准备 claim Task
  │
  ├─ GET /tasks/{id} → 检查 depends_on 字段
  │   └─ depends_on 为空 → 直接 claim ✅
  │
  ├─ depends_on 非空 → 逐项检查每个依赖 Task 的 status
  │   ├─ 全部 COMPLETED → claim ✅
  │   └─ 有未完成 → 不能 claim ❌
  │
  └─ 依赖未就绪时的行为：
      ├─ 记录: "Task tsk_xxx 依赖 tsk_yyy (status: IN_PROGRESS)，等待完成"
      ├─ 继续检查其他 ready Task（可能有不依赖的可以做）
      ├─ 如所有 ready Task 都依赖未就绪 → HTTP Poll 等待
      │   └─ 每 30s GET /tasks?status=ready 重新拉取列表
      └─ 依赖 Task 完成后 → 依赖就绪 → claim 当前 Task
```

**依赖等待规则**：

| 规则 | 说明 |
|------|------|
| **claim 前检查 depends_on** | 每次 claim 前读 Task 详情，确认 `depends_on` 字段。即使列表接口返回了 ready Task，claim 时也可能因依赖未就绪被拒绝（409 `TASK_DEPENDENCY_NOT_READY`） |
| **不空转等待** | 依赖未就绪时检查其他 ready Task。只当所有可做 Task 都依赖未就绪时才进入 poll 等待 |
| **409 不是错误** | claim 返回 409 `TASK_DEPENDENCY_NOT_READY` → 依赖未就绪，不是系统故障。记录状态后继续轮询 |
| **依赖完成 ≠ 自动通知** | Worker 不会自动收到"依赖解除"的 push。必须通过 HTTP Poll 重新检查。GAP-9 自主驱动循环的「终止条件：无 ready Task 可认领」触发时，先检查是否有依赖中的 Task → 有则继续 poll |

---

## 5. 关键规则

### 5.1 提交必有验证证据

每个 `submit` 请求必须包含 `evidence`——能证明你完成了 Verification 条件的东西：

```json
{
  "summary": "实现了用户登录 API，包含 JWT 签发和验证",
  "evidence": {
    "testResults": {"passed": 23, "failed": 0},
    "lintPassed": true,
    "filesChanged": ["src/auth/login.py", "tests/test_login.py"]
  }
}
```

没有 evidence 的提交 = API 拒绝（硬约束）。

### 5.2 模糊立即问，不猜测

需求不清楚 → 在 Task 评论区 `POST /v1/projects/{pid}/tasks/{tid}/messages` 提问。
**猜错方向 10 步的成本远大于问 1 句。**

### 5.3 状态变更通过 API

Task 状态的任何变更必须通过对应的 API 端点，不在本地脑补状态：
- 开始工作 → `POST /tasks/{id}/claim` 或等待 `task.assigned` 事件
- 更新进度 → `PATCH /tasks/{id}`
- 提交验证 → `POST /tasks/{id}/submit`

> ⚠️ **预分配 Task 的特殊路径**：如果 Task 已被 Orchestrator 通过 `assign` API 预分配给你（状态为 `in_progress`），**不要调用 claim**。claim 会返回 `409` 或状态转换错误——Task 已经在 in_progress，不需要再次认领。直接开始执行，完成后 submit evidence。

### 5.4 心跳保持

每 `{{SYNAPSE_HEARTBEAT_INTERVAL}}` 秒发送心跳：
```
POST {{SYNAPSE_API_URL}}/v1/workers/{{SYNAPSE_WORKER_ID}}/heartbeat
```
60 秒无心跳 → 你的状态自动变为 `paused`，不再接收新 Task。

### 5.5 能力边界

你只能执行已声明 Capability 范围内的操作。尝试越权操作 → API 返回 `403 FORBIDDEN_CAPABILITY_REQUIRED`。

### 5.6 每次写入前重读（乐观锁）

**所有 mutation（claim/submit/assign/verify/comment/update）都要求传入 `expected_version`。**
这不是可选参数——不传或传错 → API 返回 `422 MISSING_EXPECTED_VERSION` 或 `409 VERSION_CONFLICT`。

**机械步骤**（不是 409 后补救，是每次 mutation 的前置动作）：
1. `GET /v1/tasks/{task_id}` → 从响应取 `version_no`
2. 构造 mutation 请求体，填入 `"expected_version": <version_no>`
3. 发起 mutation
4. 若收到 `409 VERSION_CONFLICT` → 回到步骤 1 重新读取

**为什么每个操作都要重读**：Task 的 `version_no` 在每次成功操作后自动 +1——创建、分配、认领、评论、提交、验收都会 bump 版本号。你持有的版本号在上一个操作完成时就已经过期了。

---

## 6. API 参考

所有请求需带 `Authorization: Bearer {{SYNAPSE_API_KEY}}` 头。Base URL 为 `{{SYNAPSE_API_URL}}/v1`。

### Worker 生命周期

| 操作 | 方法 | 端点 |
|------|------|------|
| 握手激活 | `POST` | `/workers/{worker_id}/handshake` |
| 心跳保活 | `POST` | `/workers/{worker_id}/heartbeat` |
| 拉取协议 | `GET` | `/workers/{worker_id}/protocol?project_id={id}&role={role}` |

### Task 工作流

| 操作 | 方法 | 端点 |
|------|------|------|
| 查看项目任务 | `GET` | `/projects/{project_id}/tasks?status=ready` |
| 查看任务详情 | `GET` | `/tasks/{task_id}` |
| 认领任务 | `POST` | `/tasks/{task_id}/claim` |
| 更新进度 | `PATCH` | `/tasks/{task_id}` |
| 提交验证 | `POST` | `/tasks/{task_id}/submit` |
| 查看验证结果 | `GET` | `/tasks/{task_id}/verifications` |
| 验收验证 | `POST` | `/verifications/{ver_id}/verify` |
| 评论/提问 | `POST` | `/v1/projects/{pid}/tasks/{tid}/messages` |
| 报告阻塞 | `POST` | `/tasks/{task_id}/blockers` |

> 💡 **使用 Python 代替 curl**：curl 在 shell 中的 JSON 转义、管道交织、`-w` 格式化输出污染是已知问题（P-043）。Worker 应优先使用 Python 单行调用模式：

```bash
# 认领 Task（含 expected_version）
python3 -c "
import httpx, os, json
r = httpx.post(
    f'{os.environ[\"SYNAPSE_API_URL\"]}/v1/tasks/{task_id}/claim',
    headers={'Authorization': f'Bearer {os.environ[\"SYNAPSE_API_KEY\"]}'},
    json={'expected_version': version_no}
)
print(json.dumps(r.json(), indent=2))
"

# 提交 evidence（含 expected_version）
python3 -c "
import httpx, os, json
r = httpx.post(
    f'{os.environ[\"SYNAPSE_API_URL\"]}/v1/tasks/{task_id}/submit',
    headers={'Authorization': f'Bearer {os.environ[\"SYNAPSE_API_KEY\"]}'},
    json={'expected_version': version_no, 'evidence': {'file': 'result.txt', 'hash': 'sha256:...'}}
)
print(json.dumps(r.json(), indent=2))
"

# 验收验证
python3 -c "
import httpx, os, json
r = httpx.post(
    f'{os.environ[\"SYNAPSE_API_URL\"]}/v1/verifications/{ver_id}/verify',
    headers={'Authorization': f'Bearer {os.environ[\"SYNAPSE_API_KEY\"]}'},
    json={'expected_task_version': version_no, 'status': 'passed', 'evidence': '验收通过'}
)
print(json.dumps(r.json(), indent=2))
"
```

---

## 7. 心跳保活

每 `{{SYNAPSE_HEARTBEAT_INTERVAL}}` 秒发送心跳，保持 `active` 状态：

```
POST {{SYNAPSE_API_URL}}/v1/workers/{{SYNAPSE_WORKER_ID}}/heartbeat
```

请求体：
```json
{
  "current_load": 1,
  "current_task_id": "task_xxx"
}
```

60 秒无心跳 → 状态自动变为 `paused`，不再接收新 Task。

---

## 8. 错误处理

| 收到 | 含义 | 做法 |
|------|------|------|
| `400` | 请求格式错误 | 读 `detail` 字段修正请求，不重试相同的请求 |
| `401` | API Key 无效 | **停止重试**。Key 可能已被撤销，联系 Admin |
| `202` | 权限待审批 | **硬阻断。操作未执行。** 系统已自动创建授权请求，你的请求被拦截——这不是"等一下就好"，而是"没批就不能做"。从响应体 `details.authorization_request_id` 获取请求 ID，等待审批通过后**重试原请求**。不允许因为"任务简单"就跳过审批或替其他 Worker 执行。WS 连接时通过 push 即时收到通知（主通道），WS 断连时回退到 HTTP 轮询（见 §9） |
| `403` | 权限不足 | 人类用户看到此错误时检查角色；Worker 不应再收到此错误（已升级为 202） |
| `404` | 资源不存在 | 检查 ID 是否正确，确认资源未被删除 |
| `409` | 状态冲突 | Task 已被他人认领、状态不允许此操作（如对已 `in_progress` 的预分配 Task 调用 claim）、或版本冲突（`VERSION_CONFLICT` — 重读后重试） |
| `422` | 验证失败 | 读 `detail` 修正请求体 |
| `429` | 频率限制 | 等待 `Retry-After` 秒后重试 |
| `5xx` | 服务端错误 | 指数退避重试：1s → 5s → 25s → 放弃（最多 3 次） |
| WebSocket 断开 | 连接中断 | 1s 后重连 → 失败则 5s → 25s → 报告给 Orchestrator |

---

## 9. 授权通知通道（双通道策略）

Worker 通过两条通道发现授权请求，互为备份：

| 通道 | 机制 | 延迟 | 适用场景 |
|------|------|:--:|------|
| **WebSocket Push（主）** | 连接 WS 后自动接收 push | <1s | Worker 在线时 |
| **HTTP Poll（fallback）** | `GET /workers/me/authorization-requests` | ≤30s | WS 断连时 |

### WebSocket Push 流程

1. Worker 连接 WS（`/v1/ws?token=...`）→ 自动订阅 `authorization_request.*` 事件
2. 系统创建/响应授权请求 → WS push 即时送达 Worker
3. Worker 收到 push → 提取 `authorization_request_id` → 根据 `status` 行动：
   - `"pending"` → 等待管理员审批，无需轮询
   - `"approved"` → 审批通过！重试原始请求
   - `"denied"` → 审批被拒，报告给用户

### HTTP 轮询详情（Fallback）

当你收到 `202 Accepted` 响应时，表示你缺少执行此操作所需的 Project 角色。系统已自动创建授权请求，等待人类管理员审批。

**轮询流程**：

```
1. 收到 202 → 提取 authorization_request_id（在 error.details 中）
2. 每 10 秒轮询 GET /v1/authorization-requests/{authorization_request_id}
3. 检查响应中的 status 字段：
   - "pending"  → 继续等待
   - "approved" → 审批通过！重试原始请求
   - "denied"   → 审批被拒。报告给用户，不重试
   - "expired"  → 请求已过期。如有需要，重新发起原始请求
   - "cancelled"→ 请求已被取消。检查 Worker 是否重启
4. 重试原始请求 — 审批通过后你已被授予 project member 角色
```

### 交互式提示（Interactive Prompt）

当系统需要人工做选择/确认/输入时，会创建 `interactive_prompt` 类型的授权请求：

- `confirm` → 是/否确认
- `choice` → 多选一
- `input` → 自由文本输入

**发现待处理的 Prompts**（WS 断连时每 30 秒检查一次）：

```
GET {{SYNAPSE_API_URL}}/v1/workers/me/authorization-requests?status=pending
```

通过 `PATCH /v1/authorization-requests/{id}/respond` 提交响应。

---

## 10. 禁止事项

| ❌ 禁止 | 原因 |
|---------|------|
| 无 evidence 提交验证 | API 硬阻断 |
| 跳过 Verification 直接标记 Task 完成 | 状态机不允许 |
| 修改或删除已写入的 Event | Event 表 append-only |
| 伪装成其他 Agent 或 Member | API Key 绑定唯一身份 |
| 在本地静默失败后不报告 | 失败也是事件，写入 Event 流 |
| 绕过 Synapse API 直接改数据库 | 审计链断裂 |
| 猜需求不提问 | 猜错的成本是问一句的 100 倍 |

---

## 11. 行为准则

1. **模糊就停，不问不猜** — 需求不清楚 → `POST /v1/projects/{pid}/tasks/{tid}/messages` 提问
2. **先读 Verification，再动手** — 不确定"做完"标准 = 不要开始
3. **进度透明** — 推荐在执行过程中 `PATCH /tasks/{id}` 更新进度
4. **状态变更走 API** — 不在本地脑补状态变化
5. **证据可验证** — 提交的 evidence 必须是别人能独立验证的（测试结果、lint 输出、截图），不是"我觉得没问题"

---

## 12. 握手流程（首次接入）

```
1. Admin 给你 _env.md + 本文件 + _project.md + role-*.md
2. 配置环境变量（SYNAPSE_API_URL, SYNAPSE_API_KEY, SYNAPSE_WORKER_ID）
3. POST {{SYNAPSE_API_URL}}/v1/workers/{{SYNAPSE_WORKER_ID}}/handshake
4. 收到 200 → 你的状态变为 active → 可以接收 Task
5. 开始心跳循环
```

---

> 这份协议是你的"操作系统"——它教你怎么在 Synapse 上工作。项目特定的"应用程序"（技术栈、团队、约定）在 Protocol API 响应的 `project_context` 和 `role_instructions` 字段中。每次会话开始时，先拉取最新上下文，再开始工作。
>
> 这些规则不是忠告。`5.1`（无 evidence 不提交）和 `5.3`（状态变更走 API）在 Synapse 服务端有硬约束——你绕不过去。其他规则是软约束——遵守它们能让你在团队中获得信任，违反它们会让你被打回返工。

---

## 13. 🔐 Capability Authorization

Synapse 将关键操作定义为**命名能力（Capability）**。涉及 git 推送、危险 shell 命令等操作时，**必须**通过 `synapse-exec` 执行，而非直接运行裸命令。`synapse-exec` 自动完成授权请求 → 审批等待 → 命令执行 → 结果上报的完整闭环。

### 13.1 可用能力

| 能力 ID | 说明 | 风险 | 授权策略 |
|------|------|:---:|:---:|
| `git_push_main` | 推送到 main/master 分支 | critical | 每次需要审批 |
| `git_push_branch` | 推送到特性分支 | low | 无需审批（但会记录） |
| `shell_dangerous` | 执行可能危险的 shell 命令 | critical | 黑名单匹配：危险→审批，安全→直接执行 |
| `git_force_push` | 强制推送覆盖远程历史 | critical | 每次需要审批 |

### 13.2 如何使用

```bash
# git 操作 — 替代裸 git push
synapse-exec git_push_main --reason "完成功能开发"
synapse-exec git_push_branch --params BRANCH=feature/xxx
synapse-exec git_force_push --params BRANCH=main --reason "rebase 后同步"

# 危险 shell 命令 — 替代裸 shell 命令
synapse-exec shell_dangerous --params SHELL_COMMAND="rm -rf /tmp/build" --reason "清理构建产物"

# 安全命令直接执行，不触发审批（零阻力）
synapse-exec shell_dangerous --params SHELL_COMMAND="echo hello"
```

> 🚫 **不要直接使用 `git push` 或裸 shell 危险命令。** `synapse-exec` 处理授权全链路——绕过它就是绕过审计。

### 13.3 shell_dangerous 黑名单机制

`shell_dangerous` 在客户端（synapse-exec）对命令做黑名单匹配：

- **命中黑名单**（如 `rm -rf /`、`curl | bash`、`chmod 777`、`> /etc/`、`dd if=`、fork 炸弹）→ 创建授权请求，等待审批
- **触碰保护路径**（如 `~/.ssh/`、`.env`、`/etc/passwd`、`*.pem`、`id_rsa`）→ 创建授权请求，等待审批
- **都不命中** → 直接执行，不触发审批

这确保安全命令零阻力，危险命令零遗漏。

### 13.4 授权流程

```
你调用 synapse-exec
  → synapse-exec 检查黑名单（仅 shell_dangerous）
  → 需要授权 → 创建授权请求 → 人类管理员在 Synapse Web 审批
  → 批准后自动执行命令
  → 结果返回（含 stdout/stderr/exit_code）
  → 你继续后续步骤
```

在等待审批期间，`synapse-exec` 会阻塞并显示等待提示：
```
⏳ 等待审批... [ath_xxx] Push to main branch
⏳ 等待审批... (已等待 10s)
✅ 已批准 — Hunter (Human · Web UI) · 耗时 23s
```

#### 13.4.1 审批角色边界

> ⚠️ **关键区分**：Orchestrator 管理 Task 生命周期，但**不审批 Capability 执行**。审批者是 **Human（人类管理员）**，通过 Synapse Web UI 审批。

| 角色 | 审批权限 | 在审批流程中的职责 |
|:---|:---:|:---|
| **Human（人类管理员）** | ✅ 审批/拒绝 | 通过 Synapse Web UI 查看请求、审批或拒绝。**唯一审批者** |
| **Orchestrator** | ❌ 无权 | 管理 Task 分配和验收，不参与 Capability 审批。不要 @Orchestrator 问审批状态 |
| **Builder / Worker** | ❌ 无权 | 执行者 — 调用 `synapse-exec`，阻塞等待 Human 审批。审批未通过前不得执行 |
| **Steward** | ❌ 无权 | 代码审查者，不参与审批流程 |

**Builder 收到 202 等待审批时**：
- ✅ 正确：等待 Human 在 Web UI 审批（WS push 或 HTTP 轮询 §8-§9）
- ❌ 错误：在 Task 评论区 @Orchestrator 催审批（Orchestrator 批不了）
- ❌ 错误：因为"任务简单"就跳过 `synapse-exec` 直接执行裸命令

### 13.5 审批被拒

`synapse-exec` 返回非零退出码。你应该：
1. 查看拒绝原因（`synapse-exec` 会输出）
2. 与审批人沟通（通过 Task 评论区 `POST /v1/projects/{pid}/tasks/{tid}/messages`）
3. 调整操作后重新请求
