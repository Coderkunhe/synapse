# Synapse PRD

> 最后更新：2026-09-26（P17-B1 战略定性 · 护城河从「智能层」切回「协作层」）

## 一句话定义

**不存代码，只协调工作。** 分布式人/机（Claude、Codex、人）混合团队的软件开发协作平台。

## 解决的痛点

| 现状 | 问题 |
|------|------|
| Jira/Linear/Notion | 设计给纯人类团队，没有"agent 作为 task owner"的概念 |
| GitHub Issues | 只有人和人的协作模型 |
| 多 Claude 会话 | 会话间无状态共享，靠 CLAUDE.md + memory 手工对齐 |
| 跨工具协作 | Claude、Codex、人都用不同"频道"，无法统一跟踪 |

## 核心价值主张

- **人机对等**：agent 和人在任务模型中是同一层级，只是执行方式不同
- **过程即资产**：需求→拆解→实现→验证的完整链路可视化和可追溯
- **工具无关**：不绑定任何特定 AI 工具，通过协议桥接
- **不碰代码**：与 GitHub/GitLab 等代码托管共存，不做代码存储

## 战略方向（2026-09-26 锚定）

> **护城河在「协作层」，不在「智能层」。** Synapse 不主攻「让 agent 更自主」——基模/agent 产品升级会免费吃掉能力层；但「多个 agent + 人如何协作」（组织/状态/约束/上下文双向卸载）基模解决不了，这才是 Synapse 的护城河。
>
> agent 能力层告一段落；下一阶段主攻「人机协作协调层」——让真人能像 agent 一样认领任务、读规范（skills）、同步状态，与 agent 在同一 Task 模型中对等协作（对应 P7-D2「人机混合团队模型」落地）。
>
> **上下文卸载是命门**：worker 只带「任务切片 + 依赖」，全貌按需查平台。这哲学是双向的，但当前只做了 agent 侧——人仍是 `human-as-context-bus`（脑子承载全团队全貌）。这是协作第一增量要消灭的问题。

## 不做什么

- ❌ 不存代码（不是 GitHub 竞品）
- ❌ 不跑 CI/CD
- ❌ 不替代 Slack/钉钉（不做即时通讯）
- ❌ 不写代码（不是 IDE）

## 产品内核（Product Kernel）

> 来源：2026-07-06 P9 启动前深度讨论 · [[synapse-product-kernel]]

### 原子单位：开发者 + Workers，不是组织

传统 B2B PM 工具的根节点是 Organization → Team → Project → Task。
**Synapse 的根节点是 Developer → Workers → Tasks。**

AI 时代的最小协作单元是一个开发者 + 他的几个 AI Worker。他不是「组织管理员」，他是想让自己和几个 AI 干活更顺的人。

### 渐进演化：标签 → 结构

| 阶段 | Project | Team | Batch |
|------|---------|------|-------|
| Phase 1（极简） | Task 上的 `project_name` 字符串 | Worker 上的 `team_name` 字符串 | 1 Task = 1 Batch |
| Phase 2 | 标签多到需要管理 → 下拉选择 | 共享成员需求 → Team 实体浮现 | 多 Task 打包 → Batch 实体浮现 |
| Phase 3+ | 多项目切换、权限、隔离 | 多团队治理 | 原子性、粒度动态化 |

**核心原则**：Task 是入口，其余都是标签。标签不拦用户创建 Task，填不填都行。标签多到需要管理时，自然升级为实体——升级是用户需求**拉动**的，不是产品设计**推动**的。

### 架构哲学：地基按终局打，房间按 Phase 开

- 数据模型支持未来的企业视角（FK、实体关系、权限字段已埋好）
- UI 只暴露当前阶段需要的复杂度
- 不是「做不做企业功能」，是企业功能应该在用户撞到天花板时出现
- 代码不删——FK、实体、API 是提前浇好的地基，Phase 1 的 UI 只是第一个房间

### 远景：配置化极简模式

极简版本验证后，通过配置开关控制 UI 复杂度，同代码库呈现多种产品形态：

```yaml
features:
  project_count: 1     # 1 = 无 Project 列表，退化为 Task 标签
  batch_size: 1        # 1 = 无 Batch UI，1 Task = 1 Batch
  teams: false         # false = Team 退化为 Worker 属性
```

详见 [[synapse-configurable-minimal-mode]]

## 核心数据概念

- **Team**：一组人+agent 的集合
- **Member**：人类团队成员，具有角色（admin/lead/member）和权限
- **Worker（Agent）**：AI Worker，通过 handshake 协议注册，声明 capabilities
- **Project**：一个软件项目的协调空间
- **Task**：最小工作单元，有 owner（可以是人也可以是 agent）。状态机：BACKLOG→READY→IN_PROGRESS→IN_VERIFICATION→DONE
- **Batch（任务包）**：分布式执行的最小分配单元（执行原子）。将一组相关 Task 打包分配给单个 Worker，减少协调开销
- **Verification**：Task 完成的验证条件（多验证项 + 聚合判定）
- **Event**：所有状态变更的不可变事件流（完整审计链）
- **TokenUsage**：AI Worker 的 Token 消耗追踪（按日粒度 + 按 Worker/Batch 聚合）
- **AnalysisRecord**：结构化分析记录（actor 明确 + 可溯源）
- **ComplianceScan**：合规扫描（宽规则引擎 + 薄实现）
- **Skill**：Worker 能力模板（既是入职资料也是 API 通信协议）

## MVP 范围（已交付 ✅）

P9 B1-B84 已实现以下核心能力（详见 `docs/roadmap.md` Phase 9）：

1. **Team + Member 管理** — 创建团队、邀请成员、角色权限（admin/lead/member）
2. **Project 管理** — 多项目空间、项目级进度 Dashboard
3. **Task 全生命周期** — 创建→拆分→分配→认领(claim)→提交(submit)→验证(verify)→完成(DONE)
4. **Batch 任务包** — 多 Task 打包分配、批量操作（ready/assign/priority）
5. **Worker 注册协议** — Handshake→Heartbeat→Capability 声明→多客户端 Skill 包
6. **Kanban 看板** — 4 列（backlog/ready/in_progress/in_verification）+ 历史视图
7. **Event 审计链** — 所有状态变更不可变记录 + cursor 分页
8. **故障检测** — 四条检测线（心跳超时/进度超时/租约过期/审核超时）
9. **TokenLedger** — AI Worker Token 消耗追踪 + 使用统计面板
10. **OAuth 认证** — JWT + API Key 双通道
11. **多客户端转换层** — Claude Code / Codex / Cursor 三 target Skill 包生成
12. **数据防误删** — is_protected + 7 天冷静期 + 硬删除

## 技术方案

| 维度 | 选型 | 理由 |
|------|------|------|
| 后端框架 | **FastAPI** (Python 3.12) | 异步原生 + Pydantic v2 类型安全 + OpenAPI 自动生成 |
| 前端框架 | **React 18 + TypeScript** (Vite) | 组件化 + 类型安全 + 快速 HMR |
| 数据库 | **SQLite** (开发) → **PostgreSQL** (生产) | SQLite 零配置开发；Alembic 迁移支持平滑升级 |
| ORM | **SQLAlchemy 2.0** (async) | 成熟生态 + 异步支持 + 迁移工具链 |
| 实时通信 | **WebSocket** (FastAPI 原生) | 事件广播 + 低延迟 |
| 部署 | **Docker Compose** | 一键启动全栈 |
| 测试 | **pytest** (369 tests) + **pytest-asyncio** | 异步测试 + fixtures 复用 |
| 认证 | **JWT** (人类) + **API Key** (Worker) | 双通道 + OAuth 2.0 扩展 |
| 迁移 | **Alembic** | 版本化 schema 变更 |
| 开源 | 待定 | — |
