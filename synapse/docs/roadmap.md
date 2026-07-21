# Synapse 开发路线图

> 最后更新：2026-07-21（P11-B22 ✅ 授权审批 WS 实时化 · P11-B21 ✅ PFL-041 WS 推送 · P100-B86 ✅ 违纪全量清零 · 10/10 PFLs 闭环 🎉）
> 执行规则：Phase + Batch 两级编号。每批 2-4 个任务，完成即验证。

---

## Phase 10：ADR-004 四实体架构落地 🎉

> 8 个议题全部闭环 🎉。P10-B46 L5 拉通议题⑦ · P10 post-完成整理。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P10-B1 | users + user_auth_methods 表 — 6 files · 369 tests | ✅ |
| P10-B2 | workers 表扩展 — actor_type + user_id + team_id NULLABLE — 5 files · 357 tests | ✅ |
| P10-B3 | registered_by FK member→worker + NULLABLE — 12 files · 357 tests | ✅ |
| P10-B4 | members→users+human workers 数据迁移 — derive_id · migration · registered_by 接线 — 5 files · 359 tests | ✅ |
| P10-B5 | team_members 表创建 — TeamMember 模型 · migration · Team.team_members 关系 — 5 files · 359 tests | ✅ |
| P10-B6 | project_actor_roles 表 — ProjectActorRole 模型 · migration · Project.project_actor_roles 关系 — 5 files · 359 tests | ✅ |
| P10-B7 | JWT Auth Path 迁移 — memberId→actorId · OAuth 自动创建 human Worker — 14 files · 357 tests | ✅ |
| P10-B8 | ActorType.HUMAN 迁移 + api_key_hash NULLABLE — 24 files · 341 tests | ✅ |
| P10-B9 | 议题 2 基础设施 — bcrypt + 密码工具 + auth schemas + refresh_token.user_id — 6 files · 341 tests | ✅ |
| P10-B10 | 议题 2 API 端点 — POST /register /login + auth_service 实现 — 4 files + 12 tests | ✅ |
| P10-B11 | 议题 2 前端登录/注册 — Login 表单 + Register 页面 + AuthContext email 方法 + i18n — 8 files · 371 tests | ✅ |
| P10-B12 | 议题 2 Password Reset 后端 — forgot-password + reset-password 端点 + auth_service — 380 tests | ✅ |
| P10-B13 | 议题 2 Password Reset 前端 — ForgotPassword.tsx + ResetPassword.tsx + client + routes + i18n — 6 files | ✅ |
| P10-B14 | 议题 2 收尾 — Password Reset 全链路 E2E 验证 + migration 修复 + L5 B1→B13 拉通 — 5 files | ✅ |
| P10-B15 | Email 基础设施 — SMTP + email_service + 模板 + Token 泄露修复 — 9 files · 34 tests | ✅ |
| P10-B16 | DB 宽列 migration — user.is_super_admin + user.force_password_change + password_reset_token.created_by_admin — 4 files · 391 tests | ✅ |
| P10-B17 | **RBAC 基础层** — is_super_admin 首用 + JWT 增强 + require_super_admin + require_role 超管绕过 — 7 files · 406 tests | ✅ |
| P10-B18 | **project_actor_roles 接线** — Service + require_project_role 依赖 + Admin CRUD 端点 — 6 files · 409 tests (+15) | ✅ |
| P10-B19 | **require_project_role 端点接线** — 4 routers + project_service 创建者自动 admin — 7 files · 396 tests (+3) · 议题 3 基础设施完成 | ✅ |
| P10-B20 | **AuthorizationRequest 数据模型** — 双类型单表 + Schema + Migration — 5 files · 442 tests (+18) · 议题 3 授权管道后半段启动 | ✅ |
| P10-B21 | **AuthorizationRequest Service 层** — create/respond/heartbeat/expire/cancel + 流控(max_pending≤5) + 级联失效 — 4 files · 456 tests (+26) | ✅ |
| P10-B22 | **AuthorizationRequest API 端点** — POST/GET list/PATCH respond/PATCH heartbeat — 3 files · 473 tests (+19) | ✅ |
| P10-B23 | **前端审批 UI** — /approvals 跨 Project 聚合 + 审批卡片 + API client + i18n — 6 files · 475 tests · 议题 3 闭环 🎉 | ✅ |
| P10-B24 | **议题 4 数据模型** — Workflow + WorkflowRole 表 · ProjectRole 枚举 · WorkflowStatus 枚举 · batch.workflow_id · Migration — 8 files · 475 tests | ✅ |
| P10-B25 | **议题 4 Schemas + Service 层** — WorkflowCreate/Update/Response + WorkflowRoleAssign/Entry · Workflow CRUD + WorkflowRole CRUD (upsert) + EventStore 集成 — 4 files · 493 tests (+18) | ✅ |
| P10-B26 | **议题 4 API 路由层** — 8 端点 (Workflow CRUD 5 + WorkflowRole 3) · require_role("admin") 守卫 · 对标 admin.py project_roles 模式 — 3 files · 511 tests (+16) | ✅ |
| P10-B27 | **议题 4 收尾** — data-model.md §3.13-3.14 Workflow/WorkflowRole 实体补齐 · ER/关系矩阵/ID 表同步 · L5 B24→B27 拉通 — 5 files · 议题 4 完整闭环 🎉 | ✅ |
| P10-B28 | **议题 5 A2A 数据模型** — task_worker_conversation 表 · ConversationMessageType 枚举 (4值) · 15字段+6FK+AuditMixin · twc_ 前缀 · Migration — 8 files · 523 tests (+14) | ✅ |
| P10-B29 | **议题 5 A2A Service 层** — conversation_service.py · 消息 CRUD + @mention 解析 + handoff→AuthorizationRequest 管道 · EventStore 集成 — 2 files · 559 tests (+34) | ✅ |
| P10-B30 | **议题 5 A2A API 路由层** — 4 端点 (POST/GET list/GET by id/PATCH) · require_project_role 守卫 · cursor 分页 — 2 files · 557 tests 零回归 | ✅ |
| P10-B31 | **S-065 403 拦截器 + Agent 客户端授权闭环** — AuthorizationPendingError(202) · require_project_role auto-create api_auth · auto-grant on approval · GET polling + SKILL.md 轮询 — 6 files · 557 tests · 议题 5 A2A 全链路闭环 🎉 | ✅ |
| P10-B32 | **议题 ⑦ WS Push 授权通知** — authorization_service WS push · ws.py auto-subscribe · SKILL.md 双通道文档 · worker-admin-interaction-flow.md 新建 — 5 files · 557 tests · 议题 ⑦ 通知通道 🟡 | ✅ |
| P10-B33 | **议题 ⑦ Email 通知通道** — notification_service.py (notify_project_admins) + auth_request_notification 邮件模板 · authorization_service 接线 — 4 files · 557 tests · 议题 ⑦ Email ✅ | ✅ |
| P10-B34 | **议题 ⑦ Webhook 通道 + L5 补缺** — Project.webhook_url + Migration · notification_service.notify_webhook() · httpx POST fire-and-forget · expire/cancel WS push 对称补缺 · WebPush S-066 登记 — 7 files · 559 tests · 议题 ⑦ 🟡 3/4 | ✅ |
| P10-B35 | **议题 ⑥ 数据模型** — ProtectionReport + CircuitBreaker + DecisionAudit 三张新表 · 6 新枚举 + 5 EventType · 3 ID 前缀 · Migration — 7 files · 559 tests · 议题 ⑥ 启动 🔜 Service+API | ✅ |
| P10-B36 | **议题 ⑥ Service 层** — protection_service (CRUD+骨架检测) · circuit_breaker_service (状态机:check/record_failure/record_success/reset) · decision_audit_service (record/list/get) · authorization_service 集成 DecisionAudit — 7 files · 602 tests (+45) | ✅ |
| P10-B37 | **议题 ⑥ API 层** — 9 端点 (保护报告 CRUD+run · 熔断器查询+复位 · 决策审计查询) · schemas/protection.py · 3 新 router · 604 tests 零回归 · 议题 ⑥ 全链路闭环 🎉 | ✅ |
| P100-B70 | **流程瓶颈修复** — L5 单 commit 工作流 · 同议题连续层合并豁免 · PI-16 make sync-docs 登记 — 7 files · CLAUDE.md §1/§4/§13 | ✅ |
| P100-B71 | **V-023 防呆 v2 + V-024 P1** — l5-reset.sh 证据质量门禁（长度+路径+动词 三关机械校验）· session-checkpoint.sh L5 状态输出 · V-023 🟢 闭环 · V-024 🟢 闭环 | ✅ |
| P10-B38 | **文档债收尾** — S-060 data-model.md §3.15-3.18 四实体补齐 (User/UserAuthMethod/TeamMember/ProjectActorRole) · S-061 architecture.md ADR D-018~D-020 + §4.5.6 Workflow 数据模型 · S-062 security-model.md §3 三层授权重写 + §7.2 Event 39→60 + §9.1 P10 同步 — 6 files · 604 tests 零回归（纯文档） | ✅ |
| P10-B39 | **S-063+S-064 B22 代码债修复** — S-063 respond 端点去重: 提取 check_project_role() 共享函数替代手动复刻 · S-064 heartbeat 加 project 成员校验: api_auth 免检 · 3 files · 606 tests (+2) 零回归 | ✅ |
| P10-B40 | **议题 ⑧ Phase/Sprint 模式** — S-059 · use_phase_mode + current_phase on Project · 8 files · 604 tests 零回归 · 议题 ⑧ 启动 | ✅ |
| P10-B41 | **议题 ⑧ Phase 编号自动派生** — create_batch() auto-derive phase + batch_number from project · 1 file · 604 tests | ✅ |
| P10-B42 | **议题 ⑧ 前端 Phase 编号显示** — "P10-B42" 组合徽章 + auto-fill · 4 files · 604 tests | ✅ |
| P10-B43 | **议题 ⑧ 收尾** — L5 B41→B43 拉通 · data-model.md §3.5 补齐 · 议题⑧ 闭环 🎉 · 6 files | ✅ |
| P10-B44 | **议题 ⑦ WebPush 后端** — UserPushSubscription 模型 + VAPID 配置 + notify_webpush() · 10 files · 604 tests · 议题⑦ 🟡 | ✅ |
| P10-B45 | **议题 ⑦ WebPush 前端+API** — subscribe/unsubscribe 端点 · Service Worker · usePushNotification hook · authorization_service hook · 8 files · 604 tests · 议题⑦ 全链路闭环 🎉 | ✅ |
| P10-B46 | **P10 post-完成整理** — L5 拉通议题⑦ (6 发现修复) · architecture.md v2.0 · worker-admin-interaction-flow.md 四通道更新 · P10 全量闭环 🎉 | ✅ |
| **P10-B47** | **角色归属纠正 + Guardian→Steward 清零 + 1-O 约束** — WorkerList 去 role 选择器 · 前端 guardian→steward · 1-O 约束 · template_service VALID_ROLES 去 steward | ✅ |

---

## Phase 11：多 Agent 接入战 🔜

> 战略依据：Phase 7 三角色模型（1 Orchestrator + 2 Builder）· 230 批基建后首次实战验证
> 详细设计：`docs/archive/p11-multi-agent-connect.md`（原始规划，已归档·ADR-006 重拆后路线见 track）

| Batch | 内容 | 状态 |
|-------|------|:----:|
| **P11-B1** | **ADR-006 角色隔离 · 围栏落地（L0/L1）** — 三角色模板负面清单+SKILL.md硬门禁+CLAUDE.md G6门禁+L5拉通 | ✅ |
| **P11-B2** | **ADR-006 角色隔离 · 观测 + 服务端（L2/L3）** — _protocol.md合并+check-role-isolation.sh+VALID_ROLES补Steward+role_source | ✅ |
| **P11-B3** | **Skill 内容升级 · 方法论** — Orchestrator拆Task+Verification+Batch打包 · Builder Evidence+自检+提问模板+返工 · Steward工具链+审查流程+决策矩阵 | ✅ |
| **P11-B4** | **项目约定 + 生成管线** — conventions-frontend/backend.md · generate-skill.sh L1/L2 适配+guardian→steward · architecture.md L2b 补全 · L5 P11-B1→B4 拉通 🎉 | ✅ |
| **P11-B5** | **项目管理增强** — Projects始终可见+侧边栏导航+ProjectDetail(Info/Roles/Conventions)+admin role API接前端 · 8 files | ✅ |
| **P11-B6** | **Skill 生成管道闭环** — 约定API化+VAR填充管道+generate-skill.sh --from-api · template_service.py conventions读取路径修复 · _task-current.md决策落地 · 3 files | ✅ |
| **P11-B7** | **串联就绪审查** — 🚧停止点·7维前置验证·全链路VAR管道测试·判定GO ✅ → B8启动 | ✅ |
| **P11-B8** | **地基** — project_key + 权限引擎（PERMISSION_MAP + require_permission）+ PENDING修复 · 5 files | ✅ |
| **P11-B9** | **接线 + 项目发现** — 2端点require_permission接线 + GET /workers/me/projects + Protocol project_key鉴权 · 5 files | ✅ |
| **P11-B10** | **模板适配** — SYNAPSE_AGENT_ID→SYNAPSE_WORKER_ID 变量名一致性修复 · 3 files | ✅ |
| **P11-B11** | **前置阻断项全量审计** — 11 项（3 阻断 + 5 摩擦 + 3 决策）· 非产品 Batch · 0 code files · memory 登记 | ✅ |
| **P11-B12** | **Feature Scope 定义** — "Worker 名称富化" 决策 · 狗粮范围锁定 · 0 code files（ADR-006 重拆后从"阻断修复"重定义为 Scope） | ✅ |
| **P11-B13** | **阻断修复 + 环境搭建** — project_key + orchestrator + 角色绑定 + 模板修复 · 双 Worker + Dogfood Task + Skill 生成 · 5 项发现闭环 · generate-skill.sh bugfix · 7 files · DB 验证通过 | ✅ |
| **P11-B14** | **狗粮全链路验证** — Orchestrator + Builder 双终端 · Task 全生命周期走通 · 8 项摩擦点 + 2 项违纪 · Worker 名称富化 · bootstrap 端点随此批提交 | ✅ |
| **P11-B15** | **权限修复** — PFL-034 assign_task + PFL-039 verify guard · require_role→require_permission · PFL-040 Swagger token 登记 · 3 code + 2 doc | ✅ |
| **P11-B16** | **God's-eye 角色边界 + SessionStart hook** — PFL-037 God's-eye 角色边界正式化 · PFL-038 SessionStart hook 部署 · 双客户端 settings.json · CLAUDE.md 新增角色边界专节 | ✅ |
| **P11-B17** | **狗粮发现消化** — PFL-035 ready 强制 Verification · PFL-036 handshake WS URL · PFL-040 Swagger Bearer auth · 5 files · PFL-041 登记 | ✅ |
| **P11-B18** | **Worker 可见性 + Catch-22** — PFL-032 get_task() 角色感知过滤 · PFL-033 version_no schema 补齐 + claim 错误消息去死锁 · 3 files | ✅ |
| **P11-B19** | **Bootstrap router 接线** — B14 遗留缺陷修复 · 2 行 fix · 18 tests 0→18 · V-027 幽灵 Batch 清理 + 违纪登记 | ✅ |
| **P11-B20** | **hooks 补测 + 裸奔期防御验证** — check-hooks.sh 三场景(正常/缺失/截断)验证 · L5 gate 阻塞确认 · 裸奔期 12 commits 审计无违规 · 5 层防御充足 · PFL-041 WS 推送剩余 2/3 登记 · L5 拉通复位 | ✅ |
| **P11-B21** | **PFL-041 WS 推送 3/3 步全量闭环** — task_service.py 9 函数 + verification_service.py COMPLETED/REJECTED → ws_manager.broadcast_to_actor() · ws.py auto-subscribe task.* (Workers + Humans) · Worker SKILL.md 模板 WS push 文档化 · dogfood Task tsk_019f82022c10741b 创建 · 624 tests 零回归 · PFL-041 🟡→🟢 | ✅ |
| **P11-B22** | **授权审批 WS 实时化** — ws.py humans auto-subscribe authorization_request.* · Approvals.tsx useWebSocket 实时刷新 · event_store → broadcast_to_team 闭环 · 2 files · 624 tests 零回归 | ✅ |

---

## Phase 1：项目启动 ✅

| 任务 | 内容 | 状态 |
|-------|------|:----:|
| 启动 | 项目命名 + 目录结构 + CLAUDE.md 铁律移植 | ✅ |
| 启动 | 五层自检框架 + methodology.md 落地 | ✅ |
| 启动 | Glassmind 全盘审计 + 5 项机械门禁落地 | ✅ |
| 启动 | PRD 初稿 + 产品边界定义 | ✅ |
| 启动 | 三个地基文档（data-model + protocol + security-model）| ✅ |
| 启动 | Round 1 产品对齐 + architecture.md（16 条设计决策）| ✅ |

---

## Phase 2：MVP Sprint ✅（DDL: 2026-07-06 20:00）

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P2-B1 | Skill 模板（7 文件）+ generate-skill.sh（Claude + Codex 双客户端） | ✅ |
| P2-B2 | MVP 边界定义 + FastAPI 骨架 + docker-compose | ✅ |
| P2-B3 | 核心 API 端点（Agent 注册/Task 流转/Verification） | ✅ |
| P2-B4 | 端到端验收 + L5 拉通 | ✅ |

## Phase 3：Post-MVP 增强

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P3-B1 | WebSocket 实时通道 | ✅ |
| P3-B2 | OAuth 接入 | ✅ |
| P3-B3 | 前端页面补全（Agents + TaskDetail） | ✅ |
| P3-B4 | OAuth 前端 UI + E2E 测试 | ✅ |

## Phase 4：质量治理

> 来源：2026-07-04 全盘审计（35 项发现，分 5 批修复）

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P4-B1 | Bug 修复（datetime 混用/CORS/count 查询/slug 约束） | ✅ |
| P4-B2 | 文档同步（protocol.md §7/§8 + README.md） | ✅ |
| P4-B3 | 设计改善（索引 + JSON 去重） | ✅ |
| P4-B4 | 错误统一（HTTPException → SynapseError） | ✅ |
| P4-B5 | 常量化（9 StrEnum + 模型接入） | ✅ |

## Phase 5：制度基础设施 ✅

> 来源：GlassCortex 制度审计 Phase 1（35 项差异表）。P5-A1 深度审计 → P5-B1→B9 逐项修复。
> 结果：29 项结构化待办中 P0/P1 全量闭环，P2 核心项闭环。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P5-A1 | GlassCortex 制度审计 Phase 1（深度审计，35 项差异表） | ✅ |
| P5-B1 | Makefile + check-docs 增强 + master-backlog | ✅ |
| P5-B2 | methodology.md 补章（10 缺失章节） | ✅ |
| P5-B3 | Batch 编号连续性 + LRN 防呆 + check-comments | ✅ |
| P5-B4 | TaskContinuityDetector（SessionBoundaryDetector 改编） | ✅ |
| P5-B5 | check-all 全栈门禁 + 文件行数上限 | ✅ |
| P5-B6 | router.py 拆分 + check-line-count 入标准门禁 | ✅ |
| P5-B7 | check-contracts + ADR + 关注点分离契约 | ✅ |
| P5-B8 | Batch + Project Service 抽取 | ✅ |
| P5-B9 | Team + Member Service 抽取 + EventStore 查询 | ✅ |

## Phase 6：MVP v2.0 — 制度深化 + Worker 全流程

> 来源：MVP v2.0 范围重定义（`docs/mvp-boundary.md`）。宽数据结构 + 薄实现。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P6-B1 | AnalysisRecord 数据模型 + 基础设施（模型/常量/ID/Schema） | ✅ |
| P6-B2 | AnalysisRecord 服务 + 路由 + 测试 | ✅ |
| P6-B3 | AnalysisRecord 前端页面 | ✅ |
| P6-B4 | pre-commit 项目隔离 + 文档同步补刀 | ✅ |
| P6-B5 | ComplianceScan 数据模型 + Schema + 常量 | ✅ |
| P6-B6 | ComplianceScan Service + Router + Tests（规则引擎 + 2 rules） | ✅ |
| P6-B7 | ComplianceScan GET endpoints + team_id 列 | ✅ |
| P6-B8 | ComplianceScan 前端页面（list + trigger scan + nav） | ✅ |
| P6-B9 | Skill 数据模型 + Schema + 常量 + 迁移 | ✅ |
| P6-B10 | Skill Service + Router + Tests（17 tests） | ✅ |
| P6-B11 | Skill 前端页面（list + create + edit + deprecate + nav） | ✅ |
| P6-B12 | 前端写能力补齐：list_projects/list_batches 端点 + Projects 前端页面 | ✅ |
| P6-B13 | Batches 前端页面（list + create + expand） | ✅ |
| P6-B14 | Task 创建表单（verifications 子表单） | ✅ |
| P6-B15 | 前端重构 — 工具层（useApi/useWebSocket/formatters） | ✅ |
| P6-B16 | 前端重构 — 组件抽取（TaskCard/ConfirmModal/IntentPill） | ✅ |
| P6-B17 | 前端重构 — Auth 迁移（ProtectedRoute/OAuthCallback） | ✅ |
| P6-B18 | 前端重构 — i18n 基础设施（t()/TranslationsProvider/lang switch） | ✅ |
| P6-B19 | 前端重构 — 导航修复 + 布局统一 | ✅ |
| P6-B20 | 前端重构 — 违纪体系建立 | ✅ |
| P6-B21 | 违纪体系闭环（check-violations + violations-review + 防呆评估） | ✅ |
| P6-B22 | i18n 全量翻译（8 页 EN/中文切换） | ✅ |
| P6-B23 | UX 修复 4 项（ProjectSelect/BatchSelect/nav highlight） | ✅ |
| P6-B24 | 批次重编号 B40→B43（违纪升级触发） | ✅ |
| P6-B25 | DB 底座 — AuditMixin 核心 + 6 表简单继承 | ✅ |
| P6-B26 | DB 底座 — 复杂模型 8 表 AuditMixin 升级 | ✅ |
| P6-B27 | DB 底座 — Alembic 迁移 + Schema Response 同步 | ✅ |
| P6-B28 | DB 底座 — Service create_user_id 接入 + task version_no 统一 | ✅ |
| P6-B29 | i18n 表单页清零（7 页硬编码全部接入 t()） | ✅ |
| P6-B30 | i18n 展示页清零（badge/date/fallback + formatDate lang） | ✅ |
| P6-B31 | WS 修复 + ProtectedRoute + 404 + 品牌基础（5 文件） | ✅ |
| P6-B32 | 品牌标语 + 表单体验（slogan/motto/textarea/字段扩展） | ✅ |
| P6-B33 | Teams 前端 + 架构收敛（列表/详情/成员管理/导航） | ✅ |
| P6-B34 | 文档刷新 + L5 拉通 + track 同步（全量收官） | ✅ |

> 注：B44-B46 为 GlassCortex 轨道编号，非 Synapse 空缺。
> P6-SCAN 56 项全量清零（[归档](archive/master-backlog-archive.md#p6-scan)）。P6-B25→B34 共 10 批。

---

## Phase 7：战略路线制定 ✅

> 来源：P6 闭环后战略方向讨论。不写代码，只定方向。

| ID | 内容 | 状态 |
|:---|------|:--:|
| D1 | 三层 Agent 架构定义（Orchestrator/Builder/Steward）→ v2 团队化模型（2026-07-08 评审），详见 `architecture.md` §4.5 | ✅ |
| D2 | 人机混合团队模型设计 | ✅ |
| D3 | Worker Skill 协议 v1 | ✅ |
| D4 | 多 Agent 协调机制 PRD | ✅ |
| D5 | Phase 路线图规划（P8-P12） | ✅ |
| P7-B1 | Batch 概念重定义——从「逻辑集合」升级为「执行原子（任务包）」 | ✅ |
| P7-B2 | P0 审计迁移——GlassCortex 制度扫描 + 4 项方法论落地（Plan 分级·五层分级矩阵·L5 模板·反模式速查） 🔄 重分类至 P100 治理 | ✅ |

> P7-B2 内容实质为治理/方法论迁移（四项全中 P100 准入标准），P7-B3 纠正为 P100-B16。
> P7 战略 Phase 已闭环（D1-D5），后续不再追加。

---

## Phase 8：人机协调引擎 ✅

> 来源：P7 D4 多 Agent 协调 PRD 落地。核心引擎实现。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P8-B1 | Agent 生命周期管理（handshake → heartbeat → drain） | ✅ |
| P8-B2 | Task 状态机（BACKLOG→READY→IN_PROGRESS→REVIEW→DONE） | ✅ |
| P8-B3 | Worker 调度器（claim/complete/release + 乐观锁） | ✅ |
| P8-B4 | 故障检测器（heartbeat 超时 → ERROR + 任务释放） | ✅ |
| P8-B5 | Verification 系统（多验证项 + 聚合判定） | ✅ |
| P8-B6 | Event Store（完整审计链 + cursor 分页） | ✅ |
| P8-B7 | Block/Blocker 报告机制 | ✅ |
| P8-B8 | report_blocker 收敛（apply_transition + override_event_type） | ✅ |
| P8-B9 | Gate + Signal recovery 闭环 | ✅ |
| P8-B10 | E2E 测试全覆盖（298 tests） | ✅ |

---

## Phase 100：治理块 ✅

> 来源：工程制度系统化建设。治理 Phase（P100-P199），持续开放不关闭。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P100-B1 | Phase 治理基础设施（G-003 phase-criteria + G-004 check-phase） | ✅ |
| P100-B2 | 中文化 — 状态机 + 常量 + 配置 | ✅ |
| P100-B3 | 中文化 — src/models/ 模型层 (8 files) | ✅ |
| P100-B4 | 中文化 — src/models/ 模型层(下) (7 files) | ✅ |
| P100-B5 | 中文化 — src/services/ 服务层(上) (8 files) | ✅ |
| P100-B6 | 中文化 — src/services/ 服务层(下)-A (5 files) | ✅ |
| P100-B7 | 中文化 — src/services/ 服务层(下)-B (5 files) | ✅ |
| P100-B8 | 中文化 — src/api/ + schemas/ 核心 (8 files) | ✅ |
| P100-B9 | 中文化 — src/schemas/ 实体层 (8 files) | ✅ |
| P100-B10 | 中文化 — tests/ 第一批 (8 files) | ✅ |
| P100-B11 | 中文化 — tests/ 第二批 (8 files) | ✅ |
| P100-B12 | 中文化 — tests/ 第三批 (7 files, 111 tests) | ✅ |
| — | B13 跳号（P8 遗留技术债重编号为 B15） | ⏭️ |
| P100-B14 | 讨论→登记管道（G-005-a+b）+ 批次顺序前置校验 | ✅ |
| P100-B15 | P8 遗留技术债清零（C1+C2+C3 · 5 files） | ✅ |
| P100-B16 | GlassCortex 深度扫描第二轮 → P1 四项迁移（Shared Module Governance + 违纪闭环升级 + 依赖升级纪律 + 文件健康诊断） | ✅ |
| P100-B17 | V-002 防呆闭环 — make check-frontend 路径封装 | ✅ |
| P100-B18 | V-007 + V-012 防呆 — session-checkpoint token 估算 + post-commit batch counter | ✅ |
| P100-B19 | V-003 防呆 — check-plan-mode.sh Plan Mode 入口检测 | ✅ |
| P100-B20 | V-004 防呆 — mypy type checking + check-types target | ✅ |
| P100-B21 | V-005 防呆 — execution-checklist 五段式清单 | ✅ |
| P100-B22 | V-011 防呆 — check-docs.sh CLAUDE↔methodology 交叉引用检测 | ✅ |
| P100-B23 | 🔴 止血 — B28-B40 反向工程补登记 pitfalls P-014~P-017 + lessons LL11~LL12 + 违纪 V-019 | ✅ |
| P100-B24 | 🛡️ 防呆 — execution-checklist 登记项 + CLAUDE.md §15 流程紧急修复 + methodology.md 同步 | ✅ |
| P100-B25 | 三药方止血 — V-020 scope-shift + V-021 会话超标 + G-007 fresh-eyes 机械化 · 8 files | ✅ |
| P100-B26 | P100-B25 自检修复 — V-020 monorepo 路径 + V-021 pipefail 崩溃 + MEM_DIR + 二次复发 · 5 files | ✅ |
| P100-B27 | 防呆有效性验证 — V-020/V-021/G-007 gate tests 9/9 全绿 · 三药方 🟢 闭环 · 6 files | ✅ |
| P100-B28 | CLAUDE.md §13 Scout→Execute 分级重评规则补完 · D-P9-020 闭环 · 2 files | ✅ |
| P100-B29 | S-021 远期项堆积修剪 + master-backlog 状态刷新 · 注册日期补标 · check-docs.sh 增强 | ✅ |
| P100-B30 | 文档迁移管道 — make db-sync + --check 一致性门禁 + methodology.md §文档迁移策略 | ✅ |
| P100-B31 | 系统健康 Sprint — CLAUDE.md 481→400 · backlog 402→298 · 远期项 20→12 · Track 追平 B80 | ✅ |
| P100-B32 | glossary + agent-comparison — M-006/M-007 补齐 · P0 清零 🎉 | ✅ |
| P100-B33 | 产品健康审视 — S-035 + PRD 刷新 + P9-B81→B90 路线校准 | ✅ |
| P100-B34 | L5 B31→B33 拉通 — 日报补登记 · L5 计数器复位 | ✅ |
| **P100-B35** | **L5 拉通 P100-B34→P9-B81** — 文档新鲜度 + 叙事一致性 · 计数器复位 | ✅ |
| **P100-B36** | **S-011 日报章节完善** — methodology.md 日报门禁详解 | ✅ |
| **P100-B37** | **make check 零警告** — L5 拉通 + 6 项清零 | ✅ |
| **P100-B38** | **S-023 一致性扫描** — 扫描工具就位 | ✅ |
| **P100-B39** | **S-016 Scout** — 纯分析 · 文件清单 + 分层方案 | ✅ |
| **P100-B40** | **S-016 (1/6)** — DB + Model 层重命名 | ✅ |
| **P100-B41** | **S-016 (2/6)** — Schema + Constants 层重命名 | ✅ |
| **P100-B42** | **S-016 (3/6)** — Service 层重命名 | ✅ |
| **P100-B43** | **S-016 (4/6)** — Schema 收尾 + API 路由 · 双路由器向后兼容 | ✅ |
| **P100-B44** | **S-016 (5/6)** — 路由收尾 + tasks/ws/token_usage/dashboard | ✅ |
| **P100-B45** | **S-016 (6/6)** — 测试改名 + 前端 client + i18n 合并 · L5 拉通 | ✅ |
| **P100-B46** | **违纪回顾 + PI Review** — V-019 🟢闭环 · V-022 评估 · 停车场 7→8 | ✅ |
| **P100-B47** | **治理 backlog 消化(1)** — V-022 🟢闭环 · G3 · G5 · 7 files | ✅ |
| **P100-B48** | **治理 backlog 消化(2)** — G23 ws.py KeyError · G4 · G18 · G15 · 5 files | ✅ |
| **P100-B49** | **治理 backlog 消化(3)** — G8 · G11 · G12 · G14 · G19 · 8 files | ✅ |
| **P100-B50** | **治理 backlog 消化(4)** — G2 · G10 · G16 · G17 · G20 · 7 files | ✅ |
| **P100-B51** | **治理 backlog 消化(5)** — G6 scan 端点单数→复数 · 4 files | ✅ |
| **P100-B52** | **治理 backlog 消化(6)** — G13 t() 变量插值 · 7 files | ✅ |
| **P100-B53** | **治理 backlog 消化(7)** — G7 Dashboard SQL → Service · 2 files | ✅ |
| **P100-B54** | **治理 backlog 消化(8)** — G9 DOM 绕过 React · 4 files | ✅ |
| **P100-B55** | **治理 backlog 消化(9)** — G21 S-042 空catch console.error · 6 files | ✅ |
| **P100-B56** | **治理 backlog 消化(10)** — G22 S-043 分页契约收尾 · 8 files · 22/23 G 级已消化 | ✅ |
| **P100-B57** | **违纪停车场消化** — 7 项 🟡→🟢 闭环 · 7 files · P100 治理 backlog 全量闭环 🎉 | ✅ |
| **P100-B58** | **G1 httpOnly cookie** — JWT localStorage→httpOnly cookie · 8 files · P100 全量闭环 🎉 | ✅ |
| **P100-B59** | **遗留 doc 清理** — P100-B57 防呆 doc 提交（7 项违纪 🟡→🟢 闭环）· 3 files | ✅ |
| **P100-B60** | **分页常量收敛** — DEFAULT_PAGE_SIZE + MAX_PAGE_SIZE · 13 处 → 常量 · 11 files | ✅ |
| **P100-B61→B69** | **审计项全量闭环** — B61 enum→docstring · B62-B64 schemas enum 迁移（auth/status/actor_type）· B65-B66 services 层（ws/lease_detector）· B67-B68 routers（tasks/events/token_usage/ws）· B69 审计收尾 · 全量 300+ 枚举同步 | ✅ |
| **P100-B70** | **流程瓶颈修复** — L5 单 commit 工作流 · 同议题连续层合并豁免 · PI-16 登记 · 7 files | ✅ |
| **P100-B71** | **V-023 防呆 v2 + V-024 P1** — l5-reset.sh 三关证据质量门禁 · session-checkpoint.sh L5 状态输出 | ✅ |
| **P100-B72** | **G25 文档膨胀治理 + G26 议题编号自洽** — methodology.md §5.6 文档生命周期 · check-docs.sh 文档行数扫描 · check-issue-numbers.sh | ✅ |
| **P100-B73** | **Plan 清理 + 阈值升级** — 17 plan→archive · >800 WARNING→ERROR · Backlog 补日期 | ✅ |
| **P100-B74** | **data-model.md 拆分** — §3 实体→data-model-entities.md · 1032→285 行 | ✅ |
| **P100-B75** | **methodology.md 拆分** — 五层金字塔+SMG+反模式等→methodology-reference.md · 761→399 行 | ✅ |
| **P100-B76** | **S-061 architecture.md 授权管道补齐** — §5.4 三层授权模型+AuthorizationRequest+Worker闭环 · v2.0→v2.1 | ✅ |
| **P100-B77** | **security-model.md 拆分+S-062 闭环** — §6+§10-12→security-model-appendix.md · 595→499 行 | ✅ |
| **P100-B78** | **data-model.md 实体补齐+S-060 闭环** — 议题⑤⑥ 4 实体文档化 · 19→23 实体 | ✅ |
| **P100-B79** | **onboarding.md 拆分** — §3.1-3.8+§5+§6+Appendix→onboarding-api-reference.md · 751→273 行 | ✅ |
| **P100-B80** | **S-036 security-model 全量对齐审计** — 8 项 doc↔code drift 修复 · 60→59 事件类型 · §8 传输安全诚实化 | ✅ |
| **P100-B81** | **文档全局刷新** — master-backlog S-036✅+统计 · roadmap B61-B80 补登记 · requirements-log B76-B80 补 · daily B78-B80 追 · 含 post-commit.sh L5 豁免修复（原 B81a） | ✅ |
| **P100-B82** | **战略决策登记** — PI-05 多级授权降为远期 · S-013 确认远期 · 全局治理扫描 S-067~S-072 登记 | ✅ |
| **P100-B82 L5** | **L5 拉通** — 治理扫描批 · 3文件自洽 · 0发现 · 计数器复位 | ✅ |
| **P100-B83** | **SMG RA + doc 漂移修复** — S-067 EventType 59→60 · S-068 P10 header 刷新 · S-069 ScanResult 实体补齐(23→24) · S-070 SMG Critical RA(4 模块) | ✅ |
| **P100-B84** | **依赖锁定 + 违纪计数器修复** — S-071 requirements-lock.txt 生成 · S-072 post-commit.sh violations checkpoint 递增 | ✅ |
| **P100-B85** | **G-028 治理基础设施独立批** — check-hooks.sh V-028 防呆 + make check 管道 + CLAUDE.md 启动自检 · 3 files · 🟢 微型 | ✅ |
| **P100-B86** | **违纪回顾 + 全量清零** — V-027/V-028 🔴→🟢 闭环 · violations-review 复位(batchesSinceLastReview 11→0) · 26/27 🟢 已闭环 · 活跃 0 🎉 · 3 files · 🟢 微型 | ✅ |

### P5 交付总结

| 维度 | 交付 |
|------|------|
| 工具脚本 | 7（check-docs/batch-numbers/lessons/comments/line-count/contracts + L5 gate） |
| 服务模块 | 3（batch_service + project_service + team_service） |
| 文档 | 5（master-backlog + ADR×2 + contracts baseline + methodology 补章） |
| 枚举 | 19 事件类型，覆盖率 100% |
| 测试 | 44 tests，零回归 |
| 架构 | architecture.md §5.3 分层契约 + 4/4 技术债清零 |

### Batch 1 交付清单

| 文件 | 说明 |
|------|------|
| `docs/templates/_env.md` | 环境变量模板（`{{VAR}}` 占位约定） |
| `docs/templates/_protocol.md` | L1 平台协议（合并原 `_common.md` 协作纪律 + VDD 核心循环）🆕 P11-B2 |
| `docs/templates/_project.md` | 项目上下文 + 技术栈（方案 A） |
| `docs/templates/role-orchestrator.md` | 编排者（规划/拆任务/验收/监工） |
| `docs/templates/role-builder.md` | 构建者（编码/实现/提交验证） |
| `docs/templates/role-steward.md` | 协理（安全/规范/仲裁/绩效/评估） |
| `docs/templates/_task-current.md` | 当前任务占位符（二期动态生成） |
| `tools/generate-skill.sh` | 双客户端生成脚本（`--target claude\|codex`） |

---

## Glassmind 审计后续移植 Backlog

> 来源：`docs/research/glassmind-audit.md`（2026-07-03）
> 标注：🟠 适配后可用 · 🟡 有代码后再抄 · ⚪ 设计思想

### 🟠 适配后可用（设计阶段可映射）

| ID | 内容 | 来源 |
|----|------|------|
| G2.1 | 产品优先级四层框架 — L0(架构堵点) > L1(用户断点) > L2(体验弧线) > L3(深度打磨) | methodology.md §优先级 |
| G2.2 | 核心议题追踪 — 每议题 × 四维评分(P/D/Dep/F) | core_issues.md |
| G2.3 | Agent 对比框架 — 8 维评估 × 多 agent 横向对比 | model-comparison.md |
| G2.4 | ADR 架构决策模板 — 问题→方案对比→决策→为什么 | ci-cd.md |
| G2.5 | 数据模型版本快照 — schema snapshot + 变更影响分析 | .contract-snapshot.json |

### 🟡 有代码后再抄

| ID | 内容 | 来源 |
|----|------|------|
| G3.1 | Makefile 分层门禁体系 | Makefile |
| G3.2 | Shared Module Governance 工具 | check_shared_modules.py | ✅ P100-B16 |
| G3.3 | 测试骨架检测 | Makefile L2e |

### ⚪ 设计思想（持续参考）

| ID | 内容 | 来源 |
|----|------|------|
| G4.1 | 三层沉淀架构（意志→肌肉→骨骼） | methodology.md |
| G4.2 | 品类-验证对齐（不同产物不同验证策略） | methodology.md |
| G4.3 | UI/UX 通用模式手册（10 模式） | ui-ux-patterns.md |
| G4.4 | 四支柱研究框架 | research-strategy.md |

---

## Phase 9：产品主线 ✅ B1-B80 · ▶️ B81-B90

> 来源：2026-07-06 产品内核定调。Task 是入口，其余都是标签。
> B1 启动：2026-07-07 · B80 收官：2026-07-15（Dogfooding v8 5/5 全绿）· B81-B90 路线校准：P100-B33

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P9-B1 | 侧边栏精简（9→3）+ Task 入口放松（ProjectSelect → 可选文本 + resolve API） | ✅ |
| P9-B2 | Workers 页面（合并 Agents + Team 标签化） | ✅ |
| P9-B3 | Task 工作流闭环（claim/submit/verify 按钮） | ✅ |
| P9-B4 | Tasks 404 修复（全量列表端点 + DB schema）+ Dogfooding 验证 + L5 拉通 | ✅ |
| P9-B5 | 3 fixes: Dashboard Worker 命名 + 401 跳转 + Tasks 404 恢复 | ✅ |
| P9-B6 | Task depends_on + Batch phase/batch_number + claim 依赖就绪检查 | ✅ |
| P9-B7 | depends_on 校验补刀 + Synapse 自举数据录入 | ✅ |
| P9-B8 | 前端 depends_on/Batch 展示 + 多 Worker 端到端验收 | ✅ |
| P9-B9 | depends_on 创建 UI + TaskCard 增强 + BatchSelect 过滤 + type 字段修复 | ✅ |
| P9-B10 | Task 编辑/更新 UI + 批量操作 | ✅ |
| P9-B11 | Batch 创建表单补 phase/batch_number 字段 | ✅ |
| — | P9-B10→B11 L5 拉通（26 状态组合 · 全文档新鲜 · 309 tests） | ✅ |
| P9-B12 | 导航补全：Batches 加入侧边栏 | ❌ 回滚（P9-B14） |
| P9-B13 | 任务包中文化（17 键 批次→任务包）+ 徽章关联（彩色哈希 + hover 联动 + tooltip） | ✅ |
| P9-B14 | 回滚 B12 — 侧边栏恢复 3 项（Batches 非一级导航，归属 Tasks 二级视图） | ✅ |
| P9-B15 | Batch badge 一键跳转 — TaskCard/TaskDetail → Batches 页面（?batch= 自动展开 + 返回链接） | ✅ |
| P9-B16 | Worker 详情页 — 点击 Agent 卡查看信息 + 任务统计 + 任务列表（owner_id API 过滤） | ✅ |
| P9-B17 | Worker 注册表单 — type/role/provider/model/expiry + API key 一次性展示 | ✅ |
| P9-B18 | Task 全景过滤 — 关键词搜索 + Worker/Batch 下拉框 + API 查询参数扩展 | ✅ |
| P9-B19 | Batch 详情页 — 对标 WorkerDetail 穿透视图 · info card + task stats + task list | ✅ |
| P9-B20 | 接入指南 — Agent/人类 如何接入平台（onboarding.md） | ✅ |
| P9-B21 | 模板渲染引擎 + Agent Protocol API — `GET /agents/{id}/protocol` | ✅ |
| P9-B22 | Skill 包开发（Claude Code 客户端）— 薄协议层 + generate-skill.sh --client + onboarding §3.0 | ✅ |
| P9-B23 | 多客户端转换层闭环 — canonical base → claude/codex/cursor 三 target + L5 拉通 | ✅ |
| P9-B24 | B20-B23 端到端拉通验证 — API key 前缀修复 + 12 E2E tests + migration 修复 | ✅ |
| P9-B25 | 文档挂载 Web UI — Docs 页面 + WorkerDetail 接入指引 + ChipSelect 修复 | ✅ |
| P9-B26 | Dogfooding — 用 Synapse 管 Synapse · track 指针 + Makefile fix + 种子数据 P9 化 | ✅ |
| P9-B27 | Docs 分类 + Skill 下载 + CHANGELOG | ✅ |
| P9-B28 | Worker 头像区分（type 图标）+ type/role 卡片展示 | ✅ |
| P9-B29 | 截止日期快捷按钮（1h/2h/6h/1d/3d）+ 任务创建后引导 | ✅ |
| P9-B30 | 标签 autocomplete + 依赖搜索 + L5 拉通 | ✅ |
| P9-B31 | Worker 卡片优化（human 隐藏 provider）+ 暂停帐号（is_disabled）+ 状态筛选 | ✅ |
| P9-B32 | 禁用/删除 Worker — 硬删除 + ConfirmModal + WorkerDetail 操作按钮 | ✅ |
| P9-B33 | 错误消息修复 — ApiError 解析服务端错误体 + pre-submit 校验 | ✅ |
| P9-B34 | 成功引导增强 — 继续创建按钮 + 空看板 CTA | ✅ |
| P9-B35 | 任务生命周期引导 — 步进器 + 状态上下文横幅 | ✅ |
| P9-B36 | Worker 待认领任务池 — Tab 切换 + 快捷过滤 + owner 高亮 | ✅ |
| P9-B37 | 全链路一步引导 — 快捷操作按钮 + 上下文引导横幅 | ✅ |
| P9-B38 | 认领按钮错误中文化 — 6 个错误码翻译 + 快捷操作错误映射 | ✅ |
| P9-B39 | P7 架构评审提交 — Guardian→Steward 重命名 + 三层团队模型 + PITCH.md | ✅ |
| P9-B40 | 前端 typecheck 修复 — TaskDetail task null check 前移 | ✅ |
| P9-B41 | Dogfooding v2 — 种子数据刷新 + V-019 防呆首次实战验证 + P-018 登记 | ✅ |
| P9-B42 | Dogfooding v3 — 纯 API 认领 flow E2E · 12 项 friction 登记（P-019~P-022, LL13, S-024/S-025） | ✅ |
| P9-B43 | onboarding.md 全量修复（S-024 前半） · 12 处 doc↔code drift 全量修 · 版本升 v2.0 · Prep 用 pytest E2E 真跑一遍拿真实响应回贴 | ✅ |
| P9-B43 fresh-eyes fix | Fresh eyes 复审抓 /cancel 端点表 2 处漏修（expected_version body→query · auth 收紧 JWT admin/lead）+ /terminate 补齐 + LL14 契约层 fresh-eyes 方法论 | ✅ |
| P9-B44 | S-024 后半段 — doc curl 块 subprocess E2E 机械门禁（onboarding.md curl 示例自动化验证）· 7 gate tests 全绿 | ✅ |
| P9-B45 | S-025 seed Task 数据层 — `_ensure_tasks()` + B42-B44 补登记 · 52 tasks · 369 tests | ✅ |
| P9-B46 | 文档闭环 — 五文档同步 + Web UI Dogfood 验证 · S-025 收尾 | ✅ |
| P9-B47 | S-026 Tasks 历史视图 方案A 双Tab — 进行中/历史双Tab · 7 文件 · 纯前端 | ✅ |
| P9-B48 | P7-006 闭环 — Batch 概念重定义代码层对齐（BatchStatus 枚举 + 模型 docstring） | ✅ |
| P9-B49 | P7-002 流程化 — 自举同步规范落地 · 种子数据追平 B48 · 4 files | ✅ |
| P9-B50 | **S-006 TokenLedger** — API + 数据模型（BigInteger + cost 预埋 + POST/GET 端点）· 10 files | ✅ |
| P9-B51 | **自举同步 B49+B50** — seed 脚本补 B49/B50 数据 + 标准文档闭环 | ✅ |
| P9-B52 | **S-006 TokenLedger 前端** — WorkerDetail 使用统计面板（StatCard + CSS 柱状图）· 4 code files | ✅ |
| P9-B53 | **S-027/S-028 补刀** — data-model.md §3.11 TokenUsage · requirements-log B46/B47 补登记 | ✅ |
| P9-B54 | **S-006 TokenLedger 增强** — 双页面可见性 + 日粒度时间序列 + cost 启用 · Dashboard + WorkerDetail · 7 files | ✅ |
| P9-B55 | **P7-004 数据防误删** — is_protected + archived_at + 7 天冷静期 + 硬删除 · protection toggle API + 前端保护锁 + 条件删除 · 9 files | ✅ |
| P9-B56 | **S-029 data-model.md 字段补齐** — §3.5 Project +5 字段 + 状态机扩展 deleted 终态 · 1 file | ✅ |
| P9-B57 | **P7-007 Batch 原子性 — 分配原子落地** — Agent.batch_size + Batch.assigned_to + POST /batches/{id}/assign · 8 files | ✅ |
| P9-B58 | **P7-007 前端补齐** — batch_size + assigned worker UI（WorkerDetail + BatchDetail + WorkerList 表单）· 4 files | ✅ |
| P9-B59 | **Dogfooding v4 种子刷新** — P9_BATCHES +8（B51-B58）+ P9_TASKS +8 tasks · 1 file | ✅ |
| P9-B60 | **Dogfooding v4 backlog tasks** — +4 tasks（2 ready + 2 backlog）+ _ensure_tasks ready 修复 · L5 1/2 | ✅ |
| P9-B61 | **Dogfooding 实操验证** — claim→submit→verify 全链路通过 · 🟢 微型（纯实操）· 7 friction | ✅ |
| P9-B62 | **F-B61-1 Human claim 修复** — claim/batch_claim 端点允许 member actor · 🟢 微型 · 1 file | ✅ |
| P9-B63 | **API 一致性** — expected_version query→body 统一 + Verify status 接受 approved/rejected · 🟡 标准 · 6 files | ✅ |
| P9-B64 | **B61 friction 三合一清扫** — 81 Agent 清理 + Bearer 前缀说明 + API key 醒目警告 · 🟢 微型 · 6 files | ✅ |
| P9-B65 | **F-B61-4 Handshake 简化** — agent_version 可选 + capabilities 接受 str 简写 · 🟡 标准 · 3 files | ✅ |
| P9-B66 | **F-B61-1 service 层补刀** — claim_task/claim_batch actor_type 动态化 · 🟢 微型 · 3 files | ✅ |
| P9-B67 | **F-B66-N2/N4 friction 清扫** — API key 警告 + 种子数据 B60-B66 追平 · 🟢 微型 · 3+2 files | ✅ |
| P9-B68 | **Dogfooding v6 PM 视角审计** — 8 friction + 5 missing cap · 🟢 微型 · 0 代码变更 | ✅ |
| P9-B69 | **F-B68-N5/N3 blocking friction** — description required + verifications optional + ready 时自动创建默认 verification · 🟡 标准 · 4 files (+7 test mechanical) | ✅ |
| P9-B70 | **F-B68-N1/N2/N6/N7 字段格式文档化** — priority/effort/evidence/summary Field descriptions + onboarding.md 速查表 · 🟢 微型 · 2 files | ✅ |
| P9-B71 | **M-B68-N1 项目进度 Dashboard** — per-project breakdown + 完成率进度条 · 🟡 标准 · 5 files · S-032 | ✅ |
| P9-B72 | **M-B68-N3 批量任务操作** — batch ready/assign/priority · 🟡 标准 · 6 files · S-033 | ✅ |
| P9-B73 | **M-B68-N4 Worker 负载视图** — 任务计数 + 容量指示 · 🟡 标准 · 6 files | ✅ |
| P9-B74 | **M-B68-N2 deadline 提醒** — is_overdue + overdue filter + TaskCard 红色标记 · 🟢 微型 · 7 files · S-034 | ✅ |
| **P9-B75** | **B68 Dogfooding v6 总结 — ADR-003 归档 · B68→B74 修复链叙事 · 🟢 微型 · 纯文档** | ✅ |
| **P9-B76** | **L5 B68→B75 拉通 — B73+B74 requirements-log 补登记 · 文档新鲜度 · 🟢 微型 · 纯文档** | ✅ |
| **P9-B77** | **Dogfooding v7 — PM 全链路审计 · 5 findings (3 P1 + 2 P2) · 🟢 微型 · 纯实操** | ✅ |
| **P9-B78** | **F-v7-01/02/03 P1 friction 修复 — provider Literal + handshake 引导 + claim expected_version 引导 · 🟢 微型 · 6 files** | ✅ |
| **P9-B79** | **F-v7-04 + M-v7-01 P2 — overdue_only→status=overdue + Worker active_batches count · 🟡 标准 · 7 files · B77 Dogfooding v7 全量闭环 🎉** | ✅ |
| **P9-B80** | **Dogfooding v8 修复验证 — 5/5 全绿 · 0 代码变更 · B77 v7 质量闭环 🎉 · L5 B78→B80 拉通** | ✅ |

### P9 产品主线 ✅ B1-B80 全量 · ▶️ 收尾（B81 完成·B82→B85 待 P100 后恢复）

> 来源：P100-B33 产品健康审视 + 2026-07-15 B81 完成后 P100/P9 双轨分治决策。
> B81 自举数据刷新 ✅。B82→B85 在 P100 S-016 攻坚完成后启动（API 契约稳定后再做极简模式）。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| **P9-B81** | **自举数据刷新 + 文档审计** — seed 追平 B67-B80 · security-model.md v1.1 防误导刷新 · CLAUDE.md 402→393 行 · S-036 登记 | ✅ |
| **P9-B82** | **S-015 配置化极简模式 POC** — config flag + project_count=1 / batch_size=1 开关 + UI 条件渲染 | ✅ |
| **P9-B83** | **S-015 前端落地** — Teams 开关 + 极简模式 CSS 精简 | ✅ |
| **P9-B84** | **最终 Dogfooding v9** — PM 全链路实操 · Web UI 逐页验证 · F-B84-1 bug fix | ✅ |
| **P9-B85** | **P9 收官** — 全文档终版刷新 · L5 最终拉通 · Phase 9 闭合 · P10 路线展望 | ✅ |
| **P9-B86** | **5 项文档微修** — phase-criteria/data-model/glossary/pitfalls/onboarding 文档刷新 · 与 B87 合并提交（`P9-B86+B87 Phase 9 清理`） | ✅ |
| **P9-B87** | **侧边栏收敛** — 7→3 导航项 + 页面整合 · Layout/Dashboard/Tasks/CSS/i18n · 12 files | ✅ |
| **P9-B88** | **P10 路线更新** — D-P9-003/004/006 全量登记 · 双轨结构 · 6 files | ✅ |
| **P9-B89** | **S-037 S-015 断链修复** — 3 处 feature flag gate 补齐 | ✅ |
| **P9-B90** | **S-038 API 错误契约修复** — AGENT_→WORKER_ + SynapseError + 路径修正 · 8 files | ✅ |
| **P9-B91** | **S-039 XSS 防护 + fetch 收敛** — DOMPurify + 8 处 raw fetch→client · 6 files | ✅ |
| **P9-B92** | **S-040 i18n 硬编码清零** — 17 处 → t() · 4 组件 · 13 新 key · 5 files | ✅ |
| **P9-B93** | **S-041 UX 可读性** — 裸 ID→名称 · 空看板 · Analyses 展开 · Scan 消息 · 9 files | ✅ |
| **P9-B94** | **S-044 UI 细节打磨** — verifyNone · placeholder i18n · Docs 骨架屏 · 4 files · P9 最后一批 🎉 | ✅ |
| **P9-B95** | **三路审计登记** — 三路 Explore Agent · 107 项发现 · S-045~S-058 入库 · P9 重开 | ✅ |
| **P9-B96** | **a11y 阻断修复** — S-045 TaskCard nested controls + S-048 form labels htmlFor/id + focus-visible · 10 files | ✅ |
| **P9-B97** | **S-048 sweep + 文档漂移** — form labels 机械 sweep（7 页 50 labels）+ S-046/S-047/S-058 文档修复 | ✅ |
| **P9-B98** | **S-050 + S-053 + S-057 UX 修复** — console.error→用户可见 + Loading→Saving + description 校验 · 8 files | ✅ |
| **P9-B99** | **S-052 + S-056 体验修复** — 裸 ID→可读名（6 处 card footer）+ Skills deprecate 确认弹窗 · 7 files | ✅ |
| **P9-B100** | **S-051 + S-054 + S-055 Bug 修复** — Dashboard worker fetch 用户可见 + OAuth 欢迎名 + HistoryList completed_at · 4 files | ✅ |

> P9-B82 ✅ S-015 POC — 7 files (3 backend + 4 frontend) · FeaturesConfig + /v1/features + FeaturesContext + conditional routes/nav · 2026-07-16

> 原 B81→B90 路线校准中 5 项治理类工作（S-016·S-023·make check 零警告·S-011·S-008）已重新分类至 P100-B35→B45。P9 仅保留产品功能（S-015 极简模式）+ 验证收官。

---

## 技术选型 ✅

| 维度 | 选型 | 状态 |
|------|------|:--:|
| 前端框架 | React 19 + TypeScript (Vite) | ✅ |
| 后端语言 | Python 3.12 + FastAPI | ✅ |
| 数据库 | SQLite → PostgreSQL（Alembic 迁移） | ✅ |
| 部署方式 | Docker Compose | ✅ |
| 开源策略 | 待定 | ⬜ |

---

## P10 路线展望（2026-07-16 · P9-B88 P10 路线更新）

> P9 产品主线 B1-B87 全量闭环。以下方向为 P10 候选，正式启动时由当时上下文重新规划。
> 更新：P9-B88 登记 D-P9-003/004/006 — 用户基础设施 + 通知通道 + API Docs 迁移。

**主题**：分布式 Agent 协调基础设施 + 用户基础设施

**战略意图**：双轨并进——(A) 完成 L0/L1/L2 多级授权 + Agent 间通信 + Worker 任务交接，使人机混合团队能自主运转；(B) 建立用户账户体系 + 远程授权 UI + 通知通道，使人类能异步参与 Agent 协作而不被实时打断。

### Phase 10: ADR-004 四实体架构 🔄 进行中

> 启动：2026-07-17 · 议题 1（四实体数据模型 + User 表）进行中
> 执行节奏：一次一个议题 → 深挖碰撞 → 设计闭环 → 拆 Batch → 执行

| Batch | 内容 | 状态 |
|-------|------|:----:|
| **P10-B1** | **users + user_auth_methods 表** — 2 新模型 + migration + schema · 6 files · 369 tests | ✅ |

### 轨道 A：Agent 协调基础设施（原 P10 路线）

- ~~P10-B1~~：多级授权 L0/L1/L2 数据模型 + 策略引擎（合并 S-013 + PI-05）→ 已按 ADR-004 重新规划
- **P10-B2**：Agent-to-Agent 通信协议 + WS 增强（合并 S-012 + PI-13）
- **P10-B3**：Worker per-Workflow 角色 + 渐进信任（合并 S-019 + S-022 + PI-09）
- **P10-B4**：保护报告 + 熔断机制（S-007 + PI-10 + PI-11）

### 轨道 B：用户基础设施（D-P9-003/004/006 登记）

- ~~P10-B5~~：用户账户体系 — 注册/登录/Profile + Worker→User 归属 → 已按 ADR-004 重新规划
- **P10-B6**：远程授权 UI — 授权审批队列（人在 Web/手机端异步审批 Agent 提交的 L1/L2 操作请求，不再需要实时在电脑前点确认）
- **P10-B7**：通知通道 — Web Push + Email + Webhook 基础设施（授权请求通知、Task 状态变更、Worker 异常告警）
- **P10-B8**：Project 详情页增强 — API Docs 链接迁移到 Project 元数据层（当前全局侧边栏外链 → Project 级别配置项，对齐 D-P9-006）

**关联远景项**：S-012 WebSocket 增强 · S-013 多级授权 · S-019 per-Workflow 角色 · S-020 反馈协议 v2 · S-022 Steward 渐进策略 · PI-04 会话接力 · PI-13 Agent 间通信 · PI-14 跨 Agent 任务交接 · S-037 用户账户体系（P10-B5）· S-038 远程授权审批 UI（P10-B6）· S-039 通知通道基础设施（P10-B7）
