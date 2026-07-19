# Synapse 术语表

> 最后更新：2026-07-19（P10-B47 — Guardian→Steward 清零 · 日期同步）
> 新人阅读路径：先看 PRD → 遇到陌生术语 → 查本表 → 仍有疑问 → 查对应详细文档。

---

## 核心实体

| 术语 | 英文 | 定义 | 详细文档 |
|------|------|------|----------|
| **Team** | Team | 团队的顶层容器。一个 Team 下可以有多个 Member（人类）和 Agent（AI），以及多个 Project。 | [data-model.md](data-model.md) §3.1 |
| **Member** | Member | 人类团队成员。通过 OAuth 2.0 登录，拥有 JWT Token。与 Agent 在任务模型中对等——都可以 claim/submit/verify Task。 | [data-model.md](data-model.md) §3.2 |
| **Agent** | Agent | AI 智能体。通过 API Key 认证，在 Synapse 中与人类 Member 同等对待。每个 Agent 有 type（claude/codex/custom）、role（Orchestrator/Builder/Steward）、capabilities（能力声明）和 batch_size（最大并行任务数）。 | [data-model.md](data-model.md) §3.3 · [onboarding.md](onboarding.md) |
| **Worker** | Worker | Agent 和 Member 的统称。当讨论"谁在做任务"时使用——不区分人还是 AI。PRD 的核心洞察之一：Task 的 owner 不应该只限人类。 | [prd.md](prd.md) §核心价值主张 |
| **Task** | Task | 最小工作单元。属性：title、description、status（backlog→ready→in_progress→review→done）、priority、effort、deadline、depends_on（前置依赖）、assigned_to（当前认领者）。 | [data-model.md](data-model.md) §3.6 |
| **Batch** | Batch | 任务执行包。把多个 Task 打包成一个原子分配单元——Batch 内的所有 Task 分配给同一个 Worker 执行。概念上类似"一个 sprint 内的一个子任务组"或"一个 Claude 会话的一次会话任务清单"。 | [data-model.md](data-model.md) §3.7 |
| **Project** | Project | 项目空间。Task 和 Batch 都属于某个 Project。Project 提供隔离边界——不同 Project 的 Task 互不可见。 | [data-model.md](data-model.md) §3.5 |
| **Capability** | Capability | Agent 的能力声明。注册时声明自己能做什么（如 `code_review`、`frontend`、`backend`），用于任务匹配和分配。格式为自由标签列表。 | [data-model.md](data-model.md) §3.4 |
| **Verification** | Verification | 验证条件。Task 完成后需要满足的检查项（如 "pytest 全部通过"、"代码审查通过"）。多条 Verification 全部通过 → Task 状态可从 review 迁移到 done。 | [data-model.md](data-model.md) §3.8 |
| **Event** | Event | 事件。系统中所有状态变更都记录为 Event——谁在什么时间对什么 Task 做了什么操作。事件流不可篡改，是"过程即资产"的技术基础。 | [data-model.md](data-model.md) §3.9 |
| **AnalysisRecord** | AnalysisRecord | 分析记录。Worker 提交 Task 时附带的分析/总结（如"这个 bug 的根因是..."），不是代码产物本身。 | [data-model.md](data-model.md) §3.10 |
| **TokenLedger** | TokenLedger | Token 消耗账本。记录 Agent 执行 Task 时的 Token 消耗量，用于成本追踪和效能分析。按 Agent + Project + 日期三维聚合。 | [data-model.md](data-model.md) §3.11 |

---

## 工作流概念

| 术语 | 定义 | 相关端点/文档 |
|------|------|-------------|
| **handshake** | Agent 激活协议。Agent 注册后需通过 handshake 端点确认在线状态和能力版本。handshake 失败 → Agent 状态为 `inactive`，无法接收任务。 | `POST /v1/agents/{id}/handshake` |
| **claim** | 认领操作。Worker 声明"我来做这个 Task/Batch"。claim 后 Task 状态 → `in_progress`，其他 Worker 不可重复认领。claim Batch 时需提供 `expected_version` 防止并发冲突。 | `POST /v1/tasks/{id}/claim` · `POST /v1/batches/{id}/claim` |
| **submit** | 提交操作。Worker 完成任务后提交——附带 AnalysisRecord 和 Verification 结果。Task 状态 → `review`。 | `POST /v1/tasks/{id}/submit` |
| **verify** | 验证操作。对 submit 后的 Task 进行验证确认——所有 Verification 通过后 Task 状态 → `done`。 | `POST /v1/tasks/{id}/verify` |
| **cancel** | 取消操作。将 Task 从当前状态回退到 `backlog`，释放认领者。用于任务分配错误或 Worker 无法继续。 | `POST /v1/tasks/{id}/cancel` |
| **terminate** | 终止操作。永久终止 Task（状态 → `cancelled`），不可恢复。与 cancel 的区别：cancel 是"重新分配"，terminate 是"不再需要"。 | `POST /v1/tasks/{id}/terminate` |
| **生命周期** | Task 的状态流转路径：`backlog → ready → in_progress → review → done`。每个状态迁移都有明确的触发操作和前置条件。 | [data-model.md](data-model.md) §3.6 状态机 |
| **depends_on** | Task 的前置依赖链。depends_on 字段指向必须先完成的 Task——那些 Task 全部 done 之后，当前 Task 才能进入 ready 状态。 | [data-model.md](data-model.md) §3.6 |

---

## 角色与团队拓扑

| 术语 | 定义 | 详细文档 |
|------|------|----------|
| **Orchestrator** | 编排者角色。负责需求拆解、任务规划、Batch 分配。定义"做什么"和"按什么顺序做"。 | [protocol.md](protocol.md) §角色映射 |
| **Builder** | 构建者角色。负责具体实现——编码、测试、文档。执行 Orchestrator 分配的任务。 | [docs/templates/role-builder.md](templates/role-builder.md) |
| **Steward** | 协理角色（原名 Guardian）。负责质量把关——代码审查、安全检查、反馈提供。不是"审查员"而是"质量协作者"。 | [docs/templates/role-steward.md](templates/role-steward.md) |
| **三权分立** | Synapse 的团队组织原则：需求拆解权集中（Orchestrator）、实现权分散（Builder）、质量权独立（Steward）。三者通过 Event 流协调，不通过组织层级。 | [architecture.md](architecture.md) §三权分立 |
| **Actor** | 协议层面的"行为者"抽象——不区分人还是 AI。所有 Worker（Member + Agent）在协议中都是 Actor。 | [protocol.md](protocol.md) §Actor 无关 |

---

## 开发方法论

| 术语 | 定义 | 详细文档 |
|------|------|----------|
| **五层自检金字塔** | Synapse 的质量检查体系：L1 结构层（格式/完整性）→ L2 引用层（交叉引用有效）→ L3 契约层（跨文档一致）→ L4 场景层（用户故事推演）→ L5 拉通层（全链路闭环 + 文档新鲜度）。L1-L4 按变更类型选择性执行，L5 每 2 批强制一次。 | [methodology.md](methodology.md) §五层自检金字塔 |
| **L5 拉通** | 第五层自检——跨批次的叙事一致性检查。确保 CLAUDE.md、Track、Roadmap、Requirements-log 四文档状态一致，日期新鲜，没有"做完但没记录"的 Batch。每累积 2 批强制拉通一次，提交前被硬阻断。 | [methodology.md](methodology.md) §L5 子项选择器 |
| **Batch** | 开发方法论中的 Batch 指一次完整的变更单元——从 Pre-flight 到 Commit 的闭环。通常包含 1-8 个文件变更。不同 Phase 用独立编号（如 P9-B80 指 Phase 9 的第 80 批）。 | [methodology.md](methodology.md) §Batch 隔离 |
| **Phase** | 战略意图容器。不是文件夹——每个 Phase 必须通过五维度检查（主题一致性/自然断点/规模阈值/工作性质/战略意图）。功能 Phase（P1-P99）和治理 Phase（P100-P199）使用不同编号段。 | [phase-criteria.md](phase-criteria.md) |
| **门禁** | 提交前的机械检查——不可跳过，不可手动豁免。包括：L5 间隔、文档新鲜度、违纪回顾、Phase 治理、Batch 编号等。门禁脚本在 `tools/` 目录下，通过 `make check` 统一入口。 | [methodology.md](methodology.md) §Pre-flight |
| **Track** | 轨道文件。每个项目在 `tracks/<project>.md` 中追踪自己的 Batch 进度——frontmatter 中维护 `last_batch` 和 `next_batch` 指针，确保批次顺序执行不跳号。 | `tracks/synapse.md` |
| **Pre-flight** | 每次开工前的战场基线确认——运行 `check-docs.sh` 确认 L5 累积批数、文档新鲜度、需求验证覆盖率。不是"检查是否通过"，是"确认战场状态"。 | [methodology.md](methodology.md) §Pre-flight |
| **Dogfooding** | 自举验证——用 Synapse 管理 Synapse 自己的开发。在真实环境中创建 Project、注册 Agent、提交 Task，发现摩擦点后登记到 pitfalls 并修复。 | [pitfalls.md](pitfalls.md) |
| **发现即待办** | 核心纪律之一。任何讨论/审查中产出的发现（⚠️），必须在同一会话内：当场修复（小问题），或登记到 roadmap backlog 段（需要资源）。不得仅写文档不登记。 | [CLAUDE.md](../CLAUDE.md) §发现即待办 |
| **Batch 隔离 + 会话刷新** | 每批完成后立即 commit。每批独立编号。同一会话不跨 Batch——≥2 Batch 后建议 `/clear` 重开新会话。 | [CLAUDE.md](../CLAUDE.md) §Batch 隔离 |
| **违纪登记** | 流程违规的注册表（V-NNN 编号）。同一规则累计 2 次 → 升级为 🔴 + 必须落地机械防呆。总累计 ≥5 批未回顾 → 硬阻断。 | [process-violations.md](process-violations.md) |
| **讨论即登记** | 用户讨论的方向性内容（"应该..."、"以后要..."）默认登记到对应目的地（backlog/pitfalls/lessons/P100），不需要询问"要不要登记"。 | [CLAUDE.md](../CLAUDE.md) §讨论即登记 |

---

## 认证与安全

| 术语 | 定义 | 详细文档 |
|------|------|----------|
| **API Key** | Agent 的认证凭证。每个 Agent 在注册时生成唯一的 API Key（`sk-syn-...` 格式），用于 API 调用时的 Bearer Token 认证。不可逆存储。 | [security-model.md](security-model.md) §API Key |
| **JWT** | JSON Web Token。人类 Member 通过 OAuth 2.0 登录后获得，用于 Web UI 和 API 调用。包含 `sub`（member ID）、`team_id`、过期时间。 | [security-model.md](security-model.md) §Access Token |
| **OAuth 2.0** | 人类用户的认证协议。使用 Authorization Code Flow + PKCE。当前支持的 Provider：GitHub。 | [security-model.md](security-model.md) §OAuth |
| **handshake** | Agent 激活协议（安全层面）。Agent 的 API Key 只能用于 handshake 和后续任务操作——不能用于管理操作（创建 Agent、修改 Team 设置等）。 | [security-model.md](security-model.md) §Capability 检查 |

---

## 系统架构

| 术语 | 定义 | 详细文档 |
|------|------|----------|
| **Synapse** | 本项目。人机混合团队分布式协调平台——不存代码，只协调工作。 | [README.md](../README.md) |
| **GlassCortex** | 兄弟项目 `../glasscortex/`。Synapse 向其学习开发流程经验但不修改其代码。两个项目独立演进。 | [research/glasscortex-audit.md](research/glasscortex-audit.md) |
| **Skill** | 可复用的 Worker 能力模板。包含 Skill 定义（SKILL.md）+ 配套模板文件（_protocol.md, _project.md, role-*.md 等）。生成的 Skill 包可被 Claude Code / Codex 客户端加载。 | [onboarding.md](onboarding.md) §Skill 模板 |
| **种子数据** | Seed data。开发环境中预置的测试数据——通过 `seed-synapse-project.py` 脚本一键创建 Project + Agents + Tasks + Batches。用于 Dogfooding 和开发测试。 | `tools/seed-synapse-project.py` |

---

## 缩写速查

| 缩写 | 全称 | 含义 |
|------|------|------|
| L1-L5 | Layer 1-5 | 五层自检金字塔的五个层级 |
| ADR | Architecture Decision Record | 架构决策记录——一条决策一个文件，存于 `docs/decisions/` |
| PRD | Product Requirements Document | 产品需求文档 |
| MVP | Minimum Viable Product | 最小可行产品 |
| PUA | Post-User Audit | 用户交互后的 AI 行为校准模式（非正式缩写） |
