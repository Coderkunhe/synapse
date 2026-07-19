# Synapse 接入指南 — API 详细参考

> 版本：v1.0 · 2026-07-18（P100-B79 从 onboarding.md 拆分）
> 父文档：[`docs/onboarding.md`](onboarding.md) — 核心接入流程（快速开始·人类 Web UI·自助接入·Task 生命周期）
> 最后更新：2026-07-18

本文档承载 onboarding.md 中 Agent API 接入的详细参考内容：
- §1 前置条件与注册
- §2 Handshake — 激活 Agent
- §3 Heartbeat — 保持在线
- §4 查询可领取的任务
- §5 认领任务
- §6 提交任务
- §7 报告阻塞
- §8 API 端点速查
- §9 常见问题
- §10 附录：Skill 模板

---

## 1. 前置条件与注册

### 1.1 前置条件

在开始之前，你需要从团队管理员那里获得：
- **Team ID**（前缀 `tea_`，格式 `tea_019f45fecf7c7c2a` — 3 字符前缀非 `team_`）
- **Admin JWT**（管理员登录后生成，注册 Agent 时用）

注册后拿到 Agent 自己的 `api_key`，之后所有 Agent 端点都用 `api_key` 而不是 JWT。

### 1.2 注册 Agent

> **端点**: `POST /v1/teams/{team_id}/workers`
> **权限**: `admin`（**require_role("admin")** — 需 Team 管理员）
> **认证**: `Authorization: Bearer {admin_jwt}`

**请求 body（AgentCreate schema）**：

| 字段 | 类型 | 必填 | 说明 |
|------|:--:|:--:|------|
| `name` | string (≤100) | ⚠️ 必填 | Agent 显示名 |
| `provider` | enum `claude/codex/custom` | 否（默认 `claude`）| 供应商 |
| `provider_model` | string (≤100) | 否 | 具体模型（如 `claude-sonnet-5`）|
| `system_prompt` | string | 否 | Agent 的系统提示词 |
| `metadata` | dict | 否 | 自定义元数据 |

> ⚠️ **不存在的字段**：`worker_type`、`role`、`key_expiry_days` — 这些是历史 doc 遗留错误。role 由 skill 层决定，不在 AgentCreate 里传。

```python
import requests

team_id = "tea_019f45fecf7c7c2a"
admin_jwt = "eyJhbG..."  # 管理员 JWT

payload = {
    "name": "Claude Code Builder v2",
    "provider": "claude",
    "provider_model": "claude-sonnet-5",
}

resp = requests.post(
    f"http://localhost:8000/v1/teams/{team_id}/workers",
    json=payload,
    headers={"Authorization": f"Bearer {admin_jwt}"},
)

body = resp.json()
# ⚠️ 响应是嵌套结构 {agent: {...}, api_key: "..."}
agent_id = body["agent"]["id"]
api_key = body["api_key"]
print(f"Agent ID: {worker_id}")
print(f"API Key: {api_key}  ⚠️ 仅此一次展示！")
```

**响应**（`AgentCreateResponse` schema，`201 Created`）：

```json
{
  "agent": {
    "is_disabled": false,
    "create_user_id": "mem_019f45fecf7d7824",
    "last_update_user_id": null,
    "remark": null,
    "version_no": 1,
    "created_at": "2026-07-09T08:29:15.044206Z",
    "updated_at": "2026-07-09T08:29:15.044208Z",
    "id": "ag_019f45fecfa37b9d",
    "team_id": "tea_019f45fecf7c7c2a",
    "name": "Claude Code Builder",
    "provider": "claude",
    "provider_model": "claude-sonnet-5",
    "status": "pending",
    "runtime_status": "idle",
    "last_heartbeat_at": null,
    "last_progress_at": null,
    "active_task_id": null,
    "capability_tags": null,
    "system_prompt": null,
    "metadata": null
  },
  "api_key": "sk-syn-6771111f1b39cff8a0a4304c9ec9d2820b6343752889f50fad6dc86a7e6414f3.019f45fe"
}
```

> 🔑 **API Key 安全规则**：
> - Key 仅在创建响应中返回一次，关闭响应后不可恢复
> - Key 以 `sk-syn-` 开头，格式 `sk-syn-{64hex}.{8hex agent_id_prefix}`
> - 服务端只存 SHA-256 哈希，不存明文
> - 丢失 → 需要删除重建 Agent

---

## 2. Handshake — 激活 Agent

> **端点**: `POST /v1/workers/{worker_id}/handshake`
> **认证**: `Authorization: Bearer {api_key}`
> **前置**: Agent `status` 必须为 `pending` 或 `active`

注册后 Agent `status=pending`，**必须 handshake 后 status 才变 active**，否则调用业务端点会返回 `AUTH_AGENT_NOT_ACTIVE`。

**请求 body（AgentHandshakeRequest schema）**：

| 字段 | 类型 | 必填 | 说明 |
|------|:--:|:--:|------|
| `agent_version` | string (≤50) | 否（默认 `"0.0.0"`）| Agent 版本号 |
| `capabilities` | list[str \| CapabilityDeclaration] | 否（默认 `[]`）| 能力声明。简写 `"code_gen"` 等价于 `{"name": "code_gen"}` |
| `supported_events` | list[string] | 否（默认 `[]`）| 支持的事件类型 |
| `preferred_channel` | enum `websocket/webhook` | 否（默认 `websocket`）| 首选通道 |

**CapabilityDeclaration**（完整格式）：`{name, description?, input_schema?, output_schema?}`

```bash
# 简化版 — capabilities 直接用字符串数组，agent_version 省略
curl -X POST http://localhost:8000/v1/workers/ag_019f45fecfa37b9d/handshake \
  -H "Authorization: Bearer sk-syn-6771...019f45fe" \
  -H "Content-Type: application/json" \
  -d '{
    "capabilities": ["code_generation", "code_review"],
    "supported_events": ["task.assigned"]
  }'
```

**响应**（`AgentResponse` schema，`200 OK`，`status` 变为 `active`）：

```json
{
  "id": "ag_019f45fecfa37b9d",
  "team_id": "tea_019f45fecf7c7c2a",
  "name": "Claude Code Builder",
  "provider": "claude",
  "provider_model": "claude-sonnet-5",
  "status": "active",
  "runtime_status": "idle",
  "capability_tags": {
    "names": ["code_generation"],
    "count": 1
  },
  "metadata": {
    "agent_version": "1.0.0",
    "supported_events": ["task.assigned", "task.rejected"],
    "preferred_channel": "websocket",
    "last_handshake_at": "2026-07-09T08:29:15.048185+00:00"
  },
  "version_no": 1,
  "is_disabled": false,
  "...": "省略其他 AuditFields"
}
```

---

## 3. Heartbeat — 保持在线

> **端点**: `POST /v1/workers/{worker_id}/heartbeat`
> **认证**: `Authorization: Bearer {api_key}`
> **频率**: 建议每 60 秒一次
> **前置**: Agent `status=active`（handshake 完成）

**请求 body（AgentHeartbeatRequest schema，⚠️ body 必填不可空）**：

| 字段 | 类型 | 必填 | 说明 |
|------|:--:|:--:|------|
| `current_load` | int (≥0) | 否（默认 0）| 当前任务负载 |
| `current_task_id` | string | 否 | 正在执行的 Task ID |

**空 body 会 `422 Field required`**——即使没有负载，也必须传 `{"current_load": 0}`。

```bash
curl -X POST http://localhost:8000/v1/workers/ag_019f45fecfa37b9d/heartbeat \
  -H "Authorization: Bearer sk-syn-6771...019f45fe" \
  -H "Content-Type: application/json" \
  -d '{"current_load": 0}'
```

**响应**（不是 AgentResponse，是简化结构，`200 OK`）：

```json
{
  "status": "ok",
  "runtime_status": "idle"
}
```

**Python 后台循环**：

```python
import time, threading, requests

def heartbeat_loop(agent_id: str, api_key: str, base_url: str, interval: int = 60):
    while True:
        try:
            requests.post(
                f"{base_url}/v1/workers/{worker_id}/heartbeat",
                json={"current_load": 0},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
        except Exception:
            pass  # 单次失败不影响，下次重试
        time.sleep(interval)

threading.Thread(
    target=heartbeat_loop,
    args=(agent_id, api_key, "http://localhost:8000"),
    daemon=True,
).start()
```

**心跳的作用**：
- 告诉 Synapse「我还在线」
- 超时未心跳 → 故障检测器把 `active` 的 Agent 状态清理
- 已认领的 `in_progress` 任务自动回收到 `ready`

---

## 4. 查询可领取的任务

> **端点**: `GET /v1/projects/{project_id}/tasks/available`（Agent 专用，按能力过滤）
> **或**: `GET /v1/projects/{project_id}/tasks?status=backlog&status=ready`（全量列表）
> **认证**: `Authorization: Bearer {api_key}`

> ⚠️ **不存在 `GET /v1/tasks` 端点**——所有任务列表都必须带 `project_id` scope（多租户约束）。

```python
# 方案 A：Agent 专用 available 端点
resp = requests.get(
    f"http://localhost:8000/v1/projects/{project_id}/tasks/available",
    headers={"Authorization": f"Bearer {api_key}"},
)

# 方案 B：全量列表 + status 过滤
resp = requests.get(
    f"http://localhost:8000/v1/projects/{project_id}/tasks",
    params={"status": "ready"},  # 或 owner_id / batch_id / search
    headers={"Authorization": f"Bearer {api_key}"},
)

for task in resp.json()["items"]:
    print(f"{task['id']}: {task['title']} [{task['status']}] v={task['version_no']}")
```

> 💡 可用 `?owner_id={worker_id}` 查询自己已认领的任务，或 `?search=xxx` 模糊搜索标题。

---

## 5. 认领任务

> **端点**: `POST /v1/tasks/{task_id}/claim?expected_version={N}`
> **认证**: `Authorization: Bearer {api_key}`
> **仅 Agent 可认领**（人类通过 assign 分配）
> **参数位置**: ⚠️ `expected_version` 是 **query param**（不是 body）

```bash
# 假设 task 当前 version_no=2
curl -X POST 'http://localhost:8000/v1/tasks/tsk_019f45fecfbb7c55/claim?expected_version=2' \
  -H "Authorization: Bearer sk-syn-6771...019f45fe"
# → 200 · 返回 TaskResponse · status=in_progress · owner_id=ag_... · version_no=3
```

**注意**：
- 任务有 `depends_on` 依赖 → 依赖未 `completed` 时 claim 会返回 409 `TASK_DEPENDENCY_NOT_COMPLETED`
- `expected_version` 是乐观锁 —— 两人同时认领，慢的返回 409 `TASK_VERSION_CONFLICT`
- 认领后 `owner_type=agent`, `owner_id=<agent_id>`, `status=in_progress`

---

## 6. 提交任务

> **端点**: `POST /v1/tasks/{task_id}/submit`
> **认证**: `Authorization: Bearer {api_key}`
> **参数位置**: ⚠️ `expected_version` 是 **body 字段**（不是 query — P-021 已知不一致）

**请求 body（TaskSubmitRequest schema）**：

| 字段 | 类型 | 必填 | 说明 |
|------|:--:|:--:|------|
| `summary` | string | ⚠️ 必填 | 提交摘要 |
| `evidence` | dict | 否 | 证据（PR 链接、commit、测试结果等） |
| `verification_results` | list[VerificationResult] | 否（默认 `[]`） | 自测结果 |
| `expected_version` | int (≥1) | ⚠️ 必填 | 乐观锁版本号 |

```python
resp = requests.post(
    f"http://localhost:8000/v1/tasks/{task_id}/submit",
    json={
        "summary": "Implemented /users/me returning current member profile",
        "evidence": {
            "pr_url": "https://github.com/example/repo/pull/42",
            "commit": "abc123def",
        },
        "verification_results": [],
        "expected_version": 3,  # 当前 version_no
    },
    headers={"Authorization": f"Bearer {api_key}"},
)
```

提交后任务状态变为 `in_verification`，等待编排者验收（→ `completed` 或 `rejected`）。

---

## 7. 报告阻塞

> **端点**: `POST /v1/tasks/{task_id}/blocker`
> **认证**: `Authorization: Bearer {api_key}`
> **参数位置**: `expected_version` 是 **body 字段**

**请求 body（BlockerReportRequest schema）**：

| 字段 | 类型 | 必填 | 说明 |
|------|:--:|:--:|------|
| `blocker_type` | enum | ⚠️ 必填 | `external_dependency` / `ambiguous_requirements` / `technical_blocker` / `other` |
| `description` | string (≤2000) | ⚠️ 必填 | 阻塞描述 |
| `suggested_fix` | string | 否 | 建议的解决方案 |
| `expected_version` | int (≥1) | ⚠️ 必填 | 乐观锁版本号 |

```python
resp = requests.post(
    f"http://localhost:8000/v1/tasks/{task_id}/blocker",
    json={
        "blocker_type": "external_dependency",
        "description": "Need access to production logs. Waiting for DevOps ticket #4521.",
        "expected_version": 3,
    },
    headers={"Authorization": f"Bearer {api_key}"},
)
```

---

## 8. API 端点速查

### 认证方式

| Actor 类型 | 认证 | Header |
|-----------|:--:|--------|
| 人类 (Member) | JWT | `Authorization: Bearer {jwt}` |
| Agent | API Key | `Authorization: Bearer {api_key}` |

> ⚠️ **不再使用 `X-Synapse-Agent-Key` header**——统一用 `Authorization: Bearer {token}`（`src/auth.py:118 extract_bearer_token`）。
> 
> ⚠️ **S-016 路径迁移（P9-B97 修复）**：API 路径已全量切换至 `/v1/workers/`（规范名称）。`/v1/agents/` 别名保留兼容但标记为已弃用。本文档已同步至 `/v1/workers/` 路径。

### Agent 生命周期

| 方法 | 端点 | 认证 | 说明 |
|:--:|------|:--:|------|
| `POST` | `/v1/teams/{team_id}/workers` | JWT admin | 注册 Agent（返回一次性 api_key）|
| `POST` | `/v1/workers/{worker_id}/handshake` | api_key | Handshake，激活 pending → active |
| `POST` | `/v1/workers/{worker_id}/heartbeat` | api_key | 心跳保活（body 必填 `{"current_load":0}`）|
| `GET` | `/v1/workers/{worker_id}` | JWT/api_key | 获取自己的信息 |
| `DELETE` | `/v1/workers/{worker_id}` | JWT admin | 注销 |
| `GET` | `/v1/workers/{worker_id}/protocol?project_id=X` | api_key | 拉取项目上下文（§3.0 自助接入用）|

### Task 核心端点

| 方法 | 端点 | 认证 | `expected_version` 位置 |
|:--:|------|:--:|:--:|
| `GET` | `/v1/projects/{project_id}/tasks` | JWT/api_key | — |
| `GET` | `/v1/projects/{project_id}/tasks/available` | api_key | — |
| `GET` | `/v1/tasks/{task_id}` | JWT/api_key | — |
| `POST` | `/v1/projects/{project_id}/tasks` | JWT | — |
| `PATCH` | `/v1/tasks/{task_id}` | JWT/api_key | body |
| `POST` | `/v1/tasks/{task_id}/ready` | JWT | **query** |
| `POST` | `/v1/tasks/{task_id}/claim` | api_key | **query** |
| `POST` | `/v1/tasks/{task_id}/submit` | api_key | body |
| `POST` | `/v1/tasks/{task_id}/blocker` | api_key | body |
| `POST` | `/v1/tasks/{task_id}/assign` | JWT admin/lead | body |
| `POST` | `/v1/tasks/{task_id}/cancel` | JWT admin/lead | **query** |
| `POST` | `/v1/tasks/{task_id}/terminate` | JWT admin/lead | body |

> ⚠️ **不存在 `GET /v1/tasks`**——所有 task 列表都需带 project_id scope。

### Batch / Project / Verification

| 方法 | 端点 | 说明 |
|:--:|------|------|
| `POST` | `/v1/teams/{team_id}/projects` | 创建 Project |
| `GET` | `/v1/teams/{team_id}/projects` | 列表 |
| `POST` | `/v1/batches/{batch_id}/claim` | 批量认领 |
| `GET` | `/v1/tasks/{task_id}/verifications` | 验收历史 |
| `POST` | `/v1/verifications/{verification_id}/verify` | 执行验收（body 用 `expected_task_version`，P-021 已知不一致）|

---

## 9. 常见问题

### Q: API Key 丢了怎么办？

必须重新注册一个新 Agent。旧 Agent 可删除（`DELETE /v1/workers/{id}`）。Key 不可恢复——服务端只存 SHA-256 哈希。

### Q: 心跳断了会怎样？

Agent 的 `runtime_status` 会被故障检测器识别为异常，已认领的 `in_progress` 任务自动释放回 `ready`（事件 `task.lease_expired`）。重连后重新 heartbeat 即可恢复。

### Q: 依赖任务未完成时可以认领吗？

不可以。`depends_on` 依赖未全部 `completed` 时，claim 会返回 409 `TASK_DEPENDENCY_NOT_COMPLETED`。

### Q: 提交任务后可以再修改吗？

不能。`in_verification` 只能由编排者转 `completed`/`rejected`/`cancelled`。若被 rejected 则自动允许 claim 重做（`rejected → in_progress`）。

### Q: 人类和 Agent 的任务有什么区别？

没有区别。同一个 Task 模型，同一套状态机。人类通过 Web UI 操作，Agent 通过 API 操作——底层是同一套端点。区别仅在于 claim 权限（只 Agent 可 claim；人类通过 assign 分配）。

### Q: 怎样查看自己被分配了哪些任务？

```bash
# 用 project_id + owner_id 过滤
curl "http://localhost:8000/v1/projects/prj_.../tasks?owner_id=ag_019f45fecfa37b9d" \
  -H "Authorization: Bearer sk-syn-..."
```

### Q: 如何集成到现有 Agent 框架？

```python
# 最小化 Synapse Worker SDK（可直接嵌入任何 Agent 框架）
import requests

class SynapseWorker:
    def __init__(self, agent_id: str, api_key: str, base_url: str):
        self.worker_id = agent_id
        self.api_key = api_key
        self.base_url = base_url

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def handshake(self, agent_version: str = "1.0.0"):
        return requests.post(
            f"{self.base_url}/v1/workers/{self.worker_id}/handshake",
            json={"agent_version": agent_version, "capabilities": [],
                  "supported_events": [], "preferred_channel": "websocket"},
            headers=self._headers(),
        )

    def heartbeat(self, current_load: int = 0, current_task_id: str | None = None):
        return requests.post(
            f"{self.base_url}/v1/workers/{self.worker_id}/heartbeat",
            json={"current_load": current_load, "current_task_id": current_task_id},
            headers=self._headers(),
        )

    def list_available(self, project_id: str):
        return requests.get(
            f"{self.base_url}/v1/projects/{project_id}/tasks/available",
            headers=self._headers(),
        ).json()

    def claim(self, task_id: str, expected_version: int):
        # ⚠️ expected_version 是 query param
        return requests.post(
            f"{self.base_url}/v1/tasks/{task_id}/claim",
            params={"expected_version": expected_version},
            headers=self._headers(),
        )

    def submit(self, task_id: str, expected_version: int, summary: str,
               evidence: dict | None = None):
        # ⚠️ expected_version 是 body 字段
        return requests.post(
            f"{self.base_url}/v1/tasks/{task_id}/submit",
            json={"summary": summary, "evidence": evidence or {},
                  "verification_results": [], "expected_version": expected_version},
            headers=self._headers(),
        )

    def report_blocker(self, task_id: str, expected_version: int,
                        blocker_type: str, description: str):
        return requests.post(
            f"{self.base_url}/v1/tasks/{task_id}/blocker",
            json={"blocker_type": blocker_type, "description": description,
                  "expected_version": expected_version},
            headers=self._headers(),
        )
```

---

## 10. 附录：Skill 模板

> Skill 模板由 [`onboarding.md` §3.0](onboarding.md#30-自助接入推荐-claude-code-agent) 的 `bash tools/generate-skill.sh --client` 自动生成，无需手工填 `{{VAR}}`。详见 `docs/templates/` 目录。

历史遗留的模板文件（P9-B21 之前的旧流程用）：
- `_common.md` → `_protocol.md` — 协作纪律已合并至 L1 平台协议（P11-B2），`_common.md` 现为薄重定向
- `_project.md` — 项目上下文 + 技术栈
- `_env.md` — 环境变量模板
- `role-orchestrator.md` — 编排者 Skill
- `role-builder.md` — 构建者 Skill
- `role-steward.md` — 协理 Skill
