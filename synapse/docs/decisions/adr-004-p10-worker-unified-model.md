# ADR-004: P10 Worker 统一模型 — User/Worker/Team/Project 四实体架构

> 日期：2026-07-17
> 状态：✅ 已批准
> 来源：P10 规划 — User/Worker/Team/Project 架构讨论

---

## 背景

P10 规划中，上回已完成的四项设计（授权管道、A2A 通信、per-Workflow 角色、用户账户体系）对核心数据模型提出了重构需求。当前系统存在以下结构性偏差：

| 偏差 | 现状 | 问题 |
|:---|:---|:---|
| `members` 表做权限门禁 | role 字段直接控制 API 权限 | Team 降级后不应再硬管权限 |
| `workers` 表只有 AI agent | 没有人类执行者的 worker 记录 | "人机对等"只在协议层，数据层不对等 |
| Worker 必须挂 Team | `team_id` NOT NULL | 外部开发者无法加入 Project 而不加入 Team |
| Project 无角色表 | 权限靠 Member.role + Task.owner 隐式推导 | 颗粒度太粗，无法精确控制 per-Project 权限 |

---

## 决策

### 四实体重新定位

| 实体 | 一句话 | 定位 | 类比 |
|:---|:---|:---|:---|
| **User** | 你是谁，怎么登录进来的 | 认证层 | 身份证 |
| **Worker** | 你能干什么活，人和 AI 的统一身份 | 执行层 | 工牌（人是自动发的，AI 是手动注册的） |
| **Team** | 一群人的微信群 | 可选标签 | 微信群 |
| **Project** | 干活的地方，权限的真正主体 | 权限主体 | 工作空间 |

### 实体关系

```
User（认证层）
  │
  │ 1:1 (human 型，user_id 非空时全局唯一)
  │ 1:N (agent 型，optional owner)
  ▼
Worker（执行层）
  │
  ├── 可选 → team_members → Team（微信群，不加也能干活）
  │
  └── 必须 → project_actor_roles → Project（干活的地方，硬权限）
```

### Worker 统一模型

```sql
-- workers 表（当前只有 AI agent，P10 扩展为统一执行者）

actor_type:   'human' | 'agent'   ← 人还是 AI
user_id:      FK → users (NULLABLE) ← 人类必有，agent 可选
team_id:      FK → teams (NULLABLE) ← 可选标签（降级后不再 NOT NULL）

-- 共享字段（human 和 agent 都有）
api_key_hash:    API Key 哈希（人类也能用 Postman/脚本接入）
api_key_prefix:  Key 前缀（UI 显示用）

-- agent 专用字段（human 行全 NULL）
provider:        claude | codex | custom
provider_model:  模型标识
system_prompt:   系统级 prompt 模板
batch_size:      默认 3
registered_by:   FK → workers.id（谁注册的这个 agent，系统自建可为 NULL）
```

### 三个不变式

```sql
-- ① 一个 User 全局最多一条 human worker
CREATE UNIQUE INDEX ON workers (user_id) WHERE user_id IS NOT NULL AND actor_type = 'human'

-- ② 一个 Worker 在一个 Project 里只有一个角色
CREATE UNIQUE INDEX ON project_actor_roles (project_id, worker_id)

-- ③ 一个 Worker 在一个 Team 里只有一条 membership
CREATE UNIQUE INDEX ON team_members (team_id, worker_id)
```

### 认证路径

| | 人类 | Agent |
|:---|:---|:---|
| 登录（Web UI） | JWT / OAuth / Email+Password | — |
| API 接入 | API Key ✅（跟 Agent 一样） | API Key |
| user_id | **必须有** | 可选 |
| api_key_hash | 自动生成（1 per worker） | 注册时生成 |

**人类 Worker 有 API Key**：用户注册后自动获得人类 worker + API Key，跟 Agent 一样可在列表查看、用 Postman/脚本接入。

**不做 API-Key-only 人类**（P10 不做，远期也不做）。

理由：
- 人类 = 决策者 + 责任主体，必须可追溯。user_id=NULL 的人类 worker = 匿名操作
- 产品层面：外部开发者注册账号 = 获客 + 留存
- 如果远期出现"人类只想用 API"的需求，解法是降低注册门槛（一键 GitHub），不是放宽约束

**远期：人类 Worker 多 Key 管理**（P10 不做，预埋设计）

> 远期允许人类 worker 创建多个 API Key，每个 Key 可设独立有效期。数据模型预埋 `worker_api_keys` 表空间：
>
> ```sql
> -- 远期：worker_api_keys（P10 只做 1 worker = 1 key）
> -- worker_id, key_hash, key_prefix, label, expires_at, created_at
> -- UNIQUE (worker_id, key_prefix)
> ```
>
> P10 阶段一个 worker 只有一个 key，存储在 `workers.api_key_hash` 中。远期拆分到独立表即可支持多 Key。

### 人类 Worker 创建时机

人类 Worker 由系统自动创建，**不开放手动注册**。注册 Worker 页面只能注册 Agent。

| 场景 | 触发 | 动作 |
|:---|:---|:---|
| User 注册 | 账号创建 | 自动创建 human worker（`actor_type='human'`, `user_id=当前用户`, `team_id=NULL`, 自动生成 API Key） |
| User 被添加到 Project | `project_actor_roles` 插入 | 先确保 human worker 存在 → 再插入角色 |
| User 被添加到 Team | `team_members` 插入 | human worker 已存在 → 插入 team_members 映射 |

**约束**：
- 一个 User 全局永远只有一条 human worker（`UNIQUE (user_id) WHERE actor_type='human'`）
- 人类 Worker 不开放手动创建——注册 Worker 表单只能创建 Agent
- 人类 Worker 不可删除、不可暂停（状态始终 `active`）
- 人类 Worker 自动获得 API Key，跟 Agent 一样可以在列表查看、用 Postman 等工具接入

### 解析链路（每次请求）

```
JWT 携带 user_id
  → SELECT * FROM workers WHERE user_id = ? AND actor_type = 'human'
  → 全局唯一一条，不需要 team_id 参与查询
  → 进 Project 时：SELECT role FROM project_actor_roles WHERE worker_id = ? AND project_id = ?
  → 得到权限。完成。
```

### 消灭的表

| 表 | 去向 |
|:---|:---|
| `members` | 被 `workers` 吸收。旧数据迁移到 workers (actor_type='human') |

### 新增的表

| 表 | 用途 |
|:---|:---|
| `users` | 认证身份（email, password_hash, display_name, avatar_url） |
| `user_auth_methods` | 多 provider 绑定（GitHub, Google, Email/Password） |
| `team_members` | Team → Worker 可选映射（含 role 标签 + notes 备注字段） |
| `project_actor_roles` | Project → Worker 权限映射（硬权限，替代 Member.role） |

---

## 后果

### 正面

- **人机对等在数据层拉通**：同一张 workers 表，同一种查询，同一套状态机
- **外部开发者无需加入 Team**：worker.team_id NULLABLE + project_actor_roles 即可干活
- **权限颗粒度提升**：per-Project 角色替代 per-Team 角色，精确到项目级别
- **认证路径简单**：人类走 JWT/OAuth，Agent 走 API Key，不交叉

### 负面

- 迁移成本：members → workers（actor_type='human'），需仔细处理 `(user_id, team_id)` 映射
- `registered_by` 从指向 Member 改为指向 Worker，需更新关联查询
- 多个表的外键关系变更（Task.owner_id, Event.actor_id 等曾引用 members 的地方统一改为 workers）

### 风险

- **中**：members 迁移到 workers 的数据完整性。缓解：迁移脚本 + 验证查询 + 回滚计划
- **低**：现有代码中散落的 `Member.role` 权限检查需全量扫描替换

---

## 与上回 P10 设计的关系

本 ADR 是 P10 数据模型的基础层决策，上层工作项全部建立在此模型之上：

| 工作项 | 依赖本 ADR 的 |
|:---|:---|
| 授权管道 | `project_actor_roles` 决定谁能审批，`workers` 统一授权请求的发起者 |
| A2A 通信 | 消息的 `sender_id` 和 `@mention` 目标统一为 `workers.id` |
| per-Workflow 角色 | `project_worker_roles` → 升级为 `project_actor_roles`，人和 AI 统一 |
| 用户账户 | `users` 表是本 ADR 的认证层基础 |
| Workers 列表 UI | 同表不同卡，`actor_type` 驱动分层渲染 |

---

## Workers 列表 UI 设计参考

> 以下为设计方向参考，不一定是最终实现。

### 列表层：统一列表，分层卡片 · 人类优先

同一 Workers 列表，人类 Worker 排在最前面，Agent 在后。卡片结构由 `actor_type` 驱动：

```
┌─────────────────────────────────────────────────────────────┐
│ 🙋 人类 (2)                                    ← 人类排最前  │
│                                                             │
│ 👤 张三 (你) · Human · admin                                │
│    API Key: sk_****abcd · 参与 3 个项目      [查看详情]      │
│                                                             │
│ 👤 李四 · Human · lead                                      │
│    API Key: sk_****efgh · 参与 2 个项目      [查看详情]      │
│                                                             │
│ 🤖 AI Agent (2)                                             │
│                                                             │
│ 🤖 Claude-Architect · Agent · active                        │
│    Claude · claude-opus-4-8 · API Key: sk_****ijkl          │
│    注册者: 张三 · 参与 2 个项目                              │
│    [暂停] [View Profile] [删除]                             │
│                                                             │
│ 🤖 Codex-Builder · Agent · active                           │
│    OpenAI · codex-4 · API Key: sk_****mnop                  │
│    注册者: 张三 · 参与 1 个项目                              │
│    [暂停] [View Profile] [删除]                             │
└─────────────────────────────────────────────────────────────┘
```

### 规则

- **人类分组排最前**：卡片分组排列：人类组（🙋）→ AI Agent 组（🤖），各自按加入时间排序
- **人类卡片**：显示 API Key 前缀 + 参与项目数，`[查看详情]` 展开完整 worker 信息
- **当前用户自己**：加 `(你)` 标记
- **Agent 卡片**：保持现有信息密度 + 补"注册者"字段 + API Key 前缀
- **筛选器**：顶部 `全部 | 人类 | AI` 三个 tab
- **人类不暂停不删除**：无 Pause/Delete 操作

### 详情层

```
Worker 详情页（人类）
  ┌──────────────────────────────────────┐
  │ 👤 张三 · human · admin              │
  │                                      │
  │ API Key: sk_1b4d8f2e...    [复制]    │  ← 有 Key！可用 Postman 接入
  │                                      │
  │ 参与的项目                            │
  │ ┌─────────────────────────────────┐  │
  │ │ synapse · Orchestrator · 🔒保护  │  │
  │ │ glasscortex · Builder           │  │
  │ │ adventurex · Steward            │  │
  │ └─────────────────────────────────┘  │
  │                                      │
  │ 注册的 Agent                         │  ← 该人类注册的所有 AI
  │ ┌─────────────────────────────────┐  │
  │ │ Claude-Architect · active       │  │
  │ │ Codex-Builder · active          │  │
  │ └─────────────────────────────────┘  │
  └──────────────────────────────────────┘

Worker 详情页（Agent）
  ┌──────────────────────────────────────┐
  │ 🤖 Claude-Architect · agent · active │
  │                                      │
  │ Provider: Claude · claude-opus-4-8   │
  │ API Key: sk_****ijkl      [复制]     │
  │ 注册者: 张三                          │
  │ 参与 2 个项目                         │
  │                                      │
  │ [暂停] [删除]                        │
  └──────────────────────────────────────┘
```

### 远期：人类 Worker 多 Key 管理

> **P10 不做，数据模型预埋。**

- 人类 Worker 可创建多个 API Key，每个 Key 可设独立有效期
- `worker_api_keys` 表：`worker_id, key_hash, key_prefix, label, expires_at, created_at`
- P10 阶段一个 worker 只有一个 key（存在 `workers.api_key_hash`），远期拆到独立表

---

> **关联记忆**：P10 规划 session memory（授权管道 + A2A + per-Workflow + 用户账户）
