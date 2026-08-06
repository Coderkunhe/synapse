# Synapse 开发路线图

> 最后更新：2026-08-06（P12-B16 ✅ — D1 自动化率 56% · DG-1/DG-2 Worker 进度面板 · Dogfood/Monitoring 域 50%→75%）
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

## Phase 11：多 Agent 接入战 ✅ 🎉

> 战略依据：Phase 7 三角色模型（1 Orchestrator + 2 Builder）· 230 批基建后首次实战验证
> **137 批全量闭环** · 36/36 PFL 清零 · Prompt-Driven → Harness-Driven 方法论转变完成
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
| **P11-B23** | **WS 加固三板斧** — ws_manager.graceful_shutdown() 优雅关闭 · ws_max_connections=200 + ws_max_message_size=64KB · main.py lifespan 关机钩子 · 4 files · 624 tests 零回归 | ✅ |
| **P11-B24** | **WS 去重** — authorization_service create/respond 移除冗余 broadcast_to_actor（event_store→broadcast_to_team 已覆盖）· expire/cancel 保留 · 1 file · 624 tests 零回归 | ✅ |
| **P11-B25** | **CLI 授权体验** — SKILL.md 模板新增「202 CLI 用户体验」节 · ⏳等待提示 + 行为规则 + ⏰超时降级 · 1 file (纯文档) | ✅ |
| **P11-B26** | **Worker WS 长连接方案** — 方案 A/B/C 三选一 · 选 C：HTTP Poll 永久模式 · WS→持久客户端 · 1 file (纯设计) | ✅ |
| **P11-B27** | **SKILL.md 启动流重构** — 新增 Step 3.5 状态同步 · HTTP Poll 主通道 · WS 可选优化 · 3 files (纯文档) | ✅ |
| **P11-B28** | **架构文档更新** — worker-admin-interaction-flow.md 双通道重新定位 · 时序图更新 · 持久 vs 短生命周期客户端分工 · 1 file (纯文档) | ✅ |
| **P11-B29** | **双客户端拉通 Scope 定义** — 8 批拆解（B29→B37）· 现状评估 · 风险识别 · 1 file (纯设计) | ✅ |
| **P11-B30** | **L5 B28→B29 拉通** — 零 drift · HTTP-first 三文档对齐验证 · 计数器复位 · 🟢 微型 (L5 质量保障) | ✅ |
| **P11-B31** | **狗粮 Prep — Task 定义 + 环境校验** — 双客户端连通性验证（DB + API 双检 200 ✅）· Task #1/#2 定义 + Verification 条件 + 边界约束 · 🟡 标准 · 1 plan + 治理制品 | ✅ |
| **P11-B32** | **狗粮 Run ①** — 单 Task 全链路闭环 · 双 Agent 独立协作 · 14min · 4 events · 6 摩擦点 · 🟡 标准 · 1 plan + 治理制品 | ✅ |
| **P11-B33** | **SKILL.md 模板全面升级 — Worker 行为契约 v2** — 10 项模板改进 · _protocol.md 6 处增强 + role-orchestrator 4 条 + role-builder 3 条 + role-steward 跟修 · 🟡 标准 · 3 files | ✅ |
| **P11-B34** | **授权硬门禁 + JSON 转义修复** — PFL-046 require_permission 统一守卫（9+1 处 mutation gate）· FR3 JSON 转义双保险 · 🟢 微型 · 2 files · 624 tests | ✅ |
| **P11-B35** | **Key 存储隔离** — OS 密钥链三级架构 · P-045 长期方案落地 · B32 狗粮 13/13 全量闭环 🎉 · 🟡 标准 · 11 files · 626 tests | ✅ |
| **P11-B36** | **审批内容富化** — worker name lookup（_to_response async + Worker 表 join）· 前端 worker name 替代裸 ID · operation 人性化展示 · 🟡 标准 · 5 files · 624 tests 零回归 | ✅ |
| **P11-B37** | **L5 B30→B37 全量拉通 + 方向复盘** — 叙事一致性验证 · 文档全量刷新 · 双客户端 8 批拆解闭环 · 🟢 微型 · L5 质量保障 | ✅ |
| **P11-B38** | **登录页优化 — 删 Dev Login + Remember Me** — 移除 Dev Login 按钮 · email localStorage 持久化 · Remember Me checkbox · 🟡 标准 · 3 files | ✅ |
| **P11-B39** | **种子数据修复 — Hunter email/password 账号** — seed-synapse-project.py 新增 Hunter User 创建 · SYNAPSE_HUNTER_PASSWORD 环境变量 · 🟢 微型 · 1 file | ✅ |
| **P11-B40** | **Auth 页面 SPA 路由 + CSS 重构** — `<a>`→`<Link>` 全部替换 · Auth.module.css 提取共享样式 · ForgotPassword 成功状态修复 · 🟡 标准 · 6 files | ✅ |
| **P11-B41** | **SMTP 生产模式 + 忘记密码邮件流程** — email_service 双引擎（aiosmtplib→stdlib 降级）· ForgotPassword debug token 移除 · SMTP sink 本地测试工具 · 🟡 标准 · 6 files · 624 tests 零回归 | ✅ |
| **P11-B42** | **Auth 认证页美化** — 实色卡片+inset 输入+图标前缀 · 6 轮迭代 · 🟡 标准 · 6 files · tsc+vite ✅ | ✅ |
| **P11-B43** | **Auth Error Handling & Edge Cases** — 客户端校验+服务端错误映射+网络兜底 · 7 files · 🔴 大型 · tsc+vite ✅ | ✅ |
| **P11-B44** | **Approval History + 质量三板斧** — Pending/History 双 Tab · status=all · target_resource_name 富化 · 状态筛选 · 25 i18n · CLAUDE.md §7.1 三板斧 · 7 files · 624 tests | ✅ |
| **P11-B45** | **环境就绪** — 双 Worker SKILL.md API 渲染刷新 · V-026#1 owner_name 闭环 · generate-skill.sh hook 检测修复 · 🟡 标准 · 8 files · 626 tests | ✅ |
| **P11-B46** | **Capability MVP 基础设施** — capabilities.yaml · GET /capabilities 端点 · AuthorizationRequest +4 字段 · capability_exec request_type · POST /report 端点 · report_execution service · Alembic migration · 🔴 大型 · 11 files · +333/-3 · 626 tests | ✅ |
| **P11-B47** | **Worker 自请求 capability_exec 权限旁路** — require_project_role→get_current_actor + inline 条件 · capability_exec+self→放行 · 其他→admin/lead · 🟢 微型 · 2 files · +179/-4 · 630 tests | ✅ |
| **P11-B48** | **synapse-exec CLI** — 497 行 bash · 请求→审批→执行→上报全链路 · env+keychain 身份解析 · 轮询等待 · subprocess 执行 · 证据上报 · 🟡 标准 · 2 files · +499/-5 | ✅ |
| **P11-B49** | **git pre-push hook** — hook 模板 + synapse-exec --install-hook · Approval 前端 capability_exec 渲染适配 · 🟢 微型 · 3 files · +172/-5 | ✅ |
| **P11-B50** | **Auth expiry scheduler + capability_exec 去重** — _auth_expiry_reaper 后台任务 · find_pending_duplicate 幂等 · 🟢 微型 · 4 files · +71/-1 | ✅ |
| **P11-B51** | **shell_dangerous + git_force_push 能力定义** — 19 黑名单 + 11 保护路径 · check_shell_blacklist() 客户端匹配 · 🟡 标准 · 4 files · +933/-9 | ✅ |
| **P11-B52** | **Skill 模板更新 — Capability Authorization 章节** — _protocol.md §13 + 3 SKILL.md 刷新 · 🟡 标准 · 4 files | ✅ |
| **P11-B53** | **狗粮验证 — Capability MVP 全链路** — 双 Worker 协作验证 · PFL-047/048/049 发现 · 🟢 微型 · 0 code files（纯狗粮） | ✅ |
| **P11-B54** | **缺口修复 — PFL-047/048 L1+L2** — 审批角色表 _protocol.md §13.4.1 · synapse-exec Human提示+安全命令审计 · 🟡 标准 · 3 files | ✅ |
| **P11-B55** | **Worker 角色围栏服务端强制 (GAP-7)** — require_permission 5端点迁移 · task:update+task:terminate PERMISSION_MAP · ensure_project_role helper · 🟡 标准 · 9 files · 630 tests | ✅ |
| **P11-B56** | **Tier 2 端点 require_permission 迁移 (GAP-7 续)** — 9 endpoints · 4 routers · 3 new project_id resolvers · 🟡 标准 · 9 files · 630 tests | ✅ |
| **P11-B57** | **GAP-8 Capability 安全审计持久化** — CapabilityAudit 不可变模型 · audit service 非阻塞 · GET /projects/{pid}/capability-audits cursor 分页 · 🟡 标准 · 10 files · 628 tests | ✅ |
| **P11-B58** | **GAP-9 Worker 自主驱动** — _protocol.md §4.1 外层循环 + role-builder 工作流 + SKILL.md 五条铁律 + _task-current.md next_action · 🟡 标准 · 7 files · 纯协议层（零服务端代码） | ✅ |
| **P11-B59** | **Scout 跨 Agent 协作** — depends_on 现状审计 · 6 GAP 识别（G1-G6）· B60 提案 · 🟢 微型 · 0 code files · 纯调研 | ✅ |
| **P11-B60** | **depends_on P0 缺口修复** — G1 batch create 传 depends_on · G3 claim_batch 依赖检查 · G6 Worker 模板依赖等待 §4.2 · 🟡 标准 · 4 files · 628 tests 零回归 | ✅ |
| **P11-B61** | **第三轮双节点狗粮** — depends_on 依赖链端到端验证 · Task A→Task B 顺序执行 · PFL-051~054 发现 · 🟢 微型 · 纯狗粮 | ✅ |
| **P11-B62** | **三维架构审计** — Round 1 文档对照+Round 2 代码级验证+live API 探测 · 8 项结构性 GAP · PFL-051~054 根因重诊断 · 🟡 标准 · 1 plan + 治理制品 | ✅ |
| **P11-B63** | **第三轮扫描** — 运行时行为·配置一致性·端到端·补充维度 · 7 项新 GAP · B62 5 项确认/扩展 · B62 关键假设修正 · 🟡 标准 · 1 plan + 治理制品 | ✅ |
| **P11-B64** | **模板修复 + 双 Worker 部署** — 11 处 comments→messages + generate-skill.sh 重新部署 · GAP-B62-8 ✅ · GAP-B63-2 ✅ · L1+L2+L3 全绿 · 🟡 标准 · 5 files | ✅ |
| **P11-B65** | **服务端修复** — 双角色自主循环（Orchestrator 监工循环 + _protocol.md §4.1.1）· 前端 VITE_WS_URL 配置 · GlassCortex port 8001 冲突解决 · 🟡 标准 · 3 files | ✅ |
| **P11-B65-1** | **conversation.py 权限迁移** — require_project_role → require_permission("task:comment") · 4 端点统一守卫 · GAP-B63-4 + B62-6 闭环 · 🟢 微型 · 1 file · 628 tests 零回归 | ✅ |
| **P11-B66** | **模板部署 + Builder Task 执行** — 双 Worker 模板重新部署（generate-skill.sh --client × 2）· Builder Task 执行验证 · 发现 conversation.py 权限阻断 + tags 500 错误 · 🟢 微型 · 纯执行/发现（修复见 B65-1+B67） | ✅ |
| **P11-B67** | **safe_loads JSON 防御门禁** — safe_loads() 捕获 JSONDecodeError → 返回 None · PFL-055 登记 · 🟢 微型 · 2 files · 628 tests 零回归 | ✅ |
| **P11-B68** | **文档追补** — B66（模板部署+执行）· B67（safe_loads 防御）requirements-log + roadmap + CLAUDE.md + daily 全量补登记 · 🟢 微型 · 纯文档 | ✅ |
| **P11-B69** | **O 自主监工循环可执行化** — _protocol.md §4.1 双角色对称重构（通用规则 + §4.1.1 Builder + §4.1.2 Orchestrator）· role-orchestrator.md 补强（反模式+中断恢复+API verify=验收完成）· 模板→部署零漂移 3 文件 · 🟡 标准 · 纯协议层 | ✅ |
| **P11-B70** | **1:1 协作基线代码+协议落地** — Verification 可判定性门禁（schema + service 双层）· evidence output_access 硬约束 · 能力声明格式 + Push/Pull 模型 · 门禁进化规则 · 🟡 标准 · 6 files (2 code + 3 template + 15 test mechanical) · 628 tests 零回归 | ✅ |
| **P11-B71** | **狗粮 R2** — 双轮狗粮全链路走通 · 7 PFL（PFL-057~063）+ 架构诊断 · 🟢 微型 · 纯狗粮 | ✅ |
| **P11-B72** | **Task 状态机补完** — assign/claim READY 前置校验 · Manual verify 禁止自验 · BACKLOG→IN_PROGRESS 移除 · 🟡 标准 · 3 code + 3 template · 628 tests 零回归 | ✅ |
| **P11-B73** | **狗粮 R3 闭环** — B72 三门禁全绿验证 · PFL-064~068 + 跨轮次 RCA · 🟢 微型 · 纯狗粮 · commit `a5d5f30` | ✅ |
| **P11-B74** | **非对称自调度** — O 连续引擎 / B 被动响应者 · 响应内 while 循环 + ScheduleWakeup 续命 · 5 态路由矩阵 · 🟡 标准 · 3 files 纯协议层 · Server 零改动 · commit `edd15e2` | ✅ |
| **P11-B75** | **协议加固** — PFL-069 诚实标注 + PFL-071 WS fallback + PFL-072 异常退出协议 · 🟢 微型 · 4 files 纯协议 · +71/-16 · commit `528266e` | ✅ |
| **P11-B76** | **Server 侧加固** — stale task 检测 + verify 幂等 guard（时序约束）· 🟡 标准 · 6 files · +459/-4 · 633 tests · commit `9d9f8f6` | ✅ |
| **P11-B77** | **狗粮 R4 无人干预全链路** — 双 Worker 零人工干预完成全链路 · 3/3 门禁 · PFL-073/074 登记 · SessionStart auto-start · 🟢 微型 · 纯狗粮 | ✅ |
| **P11-B78** | **Worker heartbeat 脚本化** — `synapse-heartbeat.sh` + SessionStart hook + `_task-current.md` · PFL-073 闭环 · 🟡 标准 · 5 files · P100 治理波 🔜 | ✅ |
| **P11-B79** | **task_service.py 拆分** — 1073 行按功能域拆分（create/assign/claim/submit 独立模块）· D-P100-002 | ✅ |
| **P11-B80** | **PFL 状态审计** — 26 项交叉对照模板+源码核实 · 18 项状态同步 · 🟢 微型 · 1 file · commit `3eb748a` | ✅ |
| **P11-B81** | **PFL 微型缺口修复 5/5** — PFL-047 L3 API 硬门禁 · PFL-053 路径更正 · PFL-059 auto-verify 确认 · PFL-064 backlog→ready 路由 · PFL-065 handshake 心跳 · 🟡 标准 · 6 files · 633 tests 零回归 | ✅ |
| **P11-B82** | **狗粮闭环 🎉** — 换题狗粮全链路 VDD 闭环 (10min) · 7 PFL 登记 (PFL-076~082 · 启动可靠性/Worker通信/调度机制三层) · PFL-074 根因查明 (handoff 语义混淆) · 阶段一出口评估 · 🟢 微型 · 纯狗粮+治理 | ✅ |
| **P11-B83** | **PFL 消化 5/5 + 审计** — generate-skill.sh PFL-076 双 bug 修复 (`& &&` 语法错误+路径缺 `.claude/`) · PFL-078 根因定位 (state.warnings 未初始化) · PFL-080 机械检测评估 · PFL-081 CronCreate 根因分析 · PFL-074 消息语义审计 · 🟢 微型 · 1 file · commit `601502d` | ✅ |
| **P11-B84** | **PFL 消化(二) 协议+脚本层** — PFL-077/079/082 硬约束修复: session-init.js Step 5e 活跃任务数机械告警 + in_verification 停滞检测 (>15min) · role-builder/role-orchestrator 终止条件审计 · Side fix: PFL-078 state.warnings[] 初始化 · 3 PFL 🔴→🟡 · 🟡 标准 · 4 files · commit `a39ec74` | ✅ |
| **P11-B85** | **PFL-081 CronCreate 机械兜底** — session-init.js writeState() 无条件 CronCreate FIRST ACTION banner 生成 · _task-current.md 模板清理 · 🟡 标准 · 3 files · +26/-10 · commit `f9caf4d` | ✅ |
| **P11-B86** | **PFL-069/074 审计** — 诚实标注全覆盖确认 + 消息类型跨模板对称性验证 · 🟢 微型 · 2 files · +7/-3 · commit `82ccb7f` | ✅ |
| **P11-B87** | **PFL-070 O 心跳检测** — GET /workers/me/heartbeat 端点 + worker_service.get_heartbeat() + HeartbeatResponse schema · role-builder.md 心跳响应协议 · L5 B85→B86 拉通 · 🟡 标准 · 13 files · 633 tests 零回归 · commit `abb456d` | ✅ |
| **P11-B88** | **PFL-077 Verif 超时自动回收 + 反 ping-pong 门禁** — 状态机新转换 IN_VERIFICATION→IN_PROGRESS · detect_stale_verifications() 30min 扫描 · _stale_task_reaper 双检测 · ≥3 次 auto-revert→auto-cancel · 🟡 标准 · 10 files · 633 tests 零回归 · commits `ea67795` + `07fb138` | ✅ |
| **P11-B89** | **PFL-070 心跳恢复动作** — role-builder.md Step 0 三级恢复（≤5min→重试 · 5-30min→通知+重试 · >30min→退出）+ role-orchestrator.md Step 0 自检心跳（进入循环前补发过期心跳）· 🟢 微型 · 2 files 纯协议层 | ✅ |
| **P11-B91** | **PFL-083 B 侧心跳 daemon 硬约束** — session-init.js Step 2.5 spawn heartbeat daemon detached:true+unref() · settings.json SessionStart hook 兜底 · role-builder.md Step 0.5 自检心跳循环 · _protocol.md §4.1.3 O-B 心跳协调 · 🟡 标准 · 3 files 纯协议层 · commit `b1f64cc` | ✅ |
| **P11-B92** | **L-P11-001 orchestrator-status 双源容错** — heartbeat 过期时 Event 活动时间 fallback · OrchestratorStatusResponse 新增 detection_source 字段 · 5 种 O 活动事件类型 · 🟡 标准 · 3 files · 644 tests 零回归 · commit `d4b7fd8` | ✅ |
| **P11-B93** | **止血部署** — ① B57 migration 执行（alembic upgrade head）· ② GAP-6 硬化版 pre-push hook 重装 · ③ 双 Worker session-init.js 重新部署 · L5 B92→B93 拉通 · 🟢 微型 · 0 代码 · 5 治理文件 · commit `f74b924` | ✅ |
| **P11-B94** | **模板→Worker 升级链自动化（PFL-084）** — SHA256 版本指纹 · GET /v1/templates/versions · 心跳模板版本+role_warnings · generate-skill.sh --check-version/--upgrade · 🟡 标准 · 7 files · 644 tests 零回归 · commit `1a691ab` | ✅ |
| **P11-B95** | **Capability 硬约束（PFL-086 + PFL-094）** — Task required_capabilities 字段 · assign_task Worker 能力门禁 · capability_exec 所有权校验 · 🟡 标准 · 13 files · 648 tests 零回归 · commit `2b222dd` | ✅ |
| **P11-B96** | **Session 连续性增强（PFL-093）** — ws-daemon.js Node.js ≥22 原生 WebSocket 自动重连 · session-init.js Step 2.6 spawn · 零 Server 端代码变更 · 🟡 标准 · 5 files · 648 tests 零回归 · commit `5294b57` | ✅ |
| **P11-B97** | **配置安全加固（PFL-099 + PFL-100）** — 协议端点 require_role 硬门禁 · session-init.js default_fallback 硬失败 · batch_verify Worker 显式拒绝 · 🟡 标准 · 4 files · 648 tests 零回归 | ✅ |
| **P11-B98** | **Worker 角色围栏 require_permission 迁移 Phase 1** — 11 endpoints require_project_role→require_permission · 6 新 PERMISSION_MAP 键 · 🟡 标准 · 8 files · 648 tests 零回归 | ✅ |
| **P11-B99** | **Worker 角色围栏 require_permission 迁移 Phase 2** — 3 resolve_project_id endpoints · 1 新权限键 · 🟡 标准 · 3 files · 648 tests 零回归 · P11-008 全量闭环 🎉 | ✅ |
| **P11-B100** | **Capability 安全命令审计持久化补刀** — POST 端点 + synapse-exec 安全命令持久化 · 10 tests · 🟡 标准 · 6 files · 658 tests · GAP-8 全量闭环 🎉 | ✅ |
| **P11-B101** | **DUPLICATE_VERIFICATION 回归修复** — verification.reset 替换 task.rejected · 🟢 微型 · 2 files · 658 tests 零回归 | ✅ |
| **P11-B102** | **七层深度扫描修复验证** — 9 PFL 逐项审计 · 发现 165 行部署漂移 · 🟢 纯审计 · 0 code files | ✅ |
| **P11-B102-2** | **Worker 重部署** — session-init.js 165行补齐 · ws-daemon.js 部署 · PFL-069/070/099 确认 · 🟢 纯部署 | ✅ |
| **P11-B103** | **狗粮前置环境搭建** — 双 Worker 目录创建 · .env 配置 · session-init.js 部署 · API keys 入 keychain · 14/14 自检全绿 | ✅ |
| **P11-B104** | **上下文过载根因分析** — collaboration_norms 29KB 占 _protocol-cache.json 73% · Deepseek 分析瘫痪 · 3 PFL 登记 → B106 | ✅ |
| **P11-B105** | **上下文按需加载** — session-init.js 拆分 protocol cache（essential 18KB + collaboration_norms 独立文件）· SKILL.md 按需查阅表更新 · 启动上下文 56KB→~27KB（-52%）· 3 files · commit 0705b68 | ✅ |
| **P11-B106** | **Onboarding PFL-101~107 全量修复** — bootstrap 脚本部署+env对齐+role补全+hook修复 · Worker 注册自动分配角色 · Verification 创建端点+自动创建 · JWT_SECRET 模板修复 · key liveness 格式校验 · $CLAUDEDIR 清理 · 15 files · 658 tests 零回归 | ✅ |
| **P11-B107** | **跨客户端架构 + SessionStart 等价物** — SKILL.md 客户端无关启动自检 · bootstrap 脚本按客户端部署到正确路径 · settings.json 条件化（仅 Claude Code）· PFL-108 闭环 · multi-client-onboarding-spec 更新 · 5 files + 2 dogfood redeploy | ✅ |
| **P11-B108** | **狗粮前置清理** — stale_task_detector 诊断（1388 stale events 正在工作但被动设计）· auto-cancel 门禁（≥10 次检测→自动取消）· 2 旧 in_progress task 取消 · 3 files · 658 tests 零回归 | ✅ |
| **P11-B109** | **狗粮验证** — OwnerType 枚举缺 HUMAN 发现并修复（500→200）· Task 生命周期 API 验证（claim→submit→verify guard）· 系统健康确认（3 reaper 运行 + 0 stale task）· 🟢 微型 · 3 files · 659 tests 零回归 | ✅ |
| **P11-B110** | **Worker 权限三层自动修复** — L1 根 settings.local.json 15→29 条 · L2 session-init.js ensureWorkerSettings() · L3 generate-skill.sh write_settings_local() · 三层幂等 · 3 PFL 登记 (PFL-110/111/112) · 🟡 标准 · 3 files · commit `0d0fe76` | ✅ |
| **P11-B111** | **Worker CLAUDE.md 自动生成 + 第零条纪律** — generate-skill.sh write_claude_md() 三路径生成 · 幂等跳过 · CLAUDE.md 首条"不回避问题" · 🟢 微型 · 5 files · commit `49875ec` | ✅ |
| **P11-B112** | **`_boot-prompt.md` 冷启动一键引导** — session-init.js v2 极简模板 · Worker 启动时 @_boot-prompt.md 一键进入 · 🟢 微型 · commit `056ddff` | ✅ |
| **P11-B113** | **登记** — PFL-113 O 需求接收协议 · PFL-114 O 空闲沉默 · PFL-115 _task-current.md 快照污染 · V-030 God's-eye 改 Worker 文件 · 模板预改 · commit `57ab8bc` | ✅ |
| **P11-B114** | **Worker 双窗口验证 + 僵尸踩坑** — 双 Worker 同时运行 daemon 冲突验证 · PFL-116 daemon 孤儿泄漏 · PFL-117 pgrep 跨 Worker 干扰 · PFL-118 无生命周期清理 · PFL-119 stale_reaper 崩溃（初步误诊）· 🟢 纯验证/发现 · 0 code files | ✅ |
| **P11-B115** | **Daemon 生命周期治理** — session-init.js PID 文件 daemon 生命周期（readPidFile/writePidFile/killOldDaemon）· SessionStart hook 去 heartbeat.js & · stale_task_detector naive→aware datetime 修复 · main.py 健康检查诊断化+sleep-in-try · generate-skill.sh 自动升级旧 hook · PFL-119 🟡 已修复 · 🟡 标准 · commit `a39b573` | ✅ |
| **P11-B116** | **B115 修复后首轮验证** — zombie 残余现场确认（pre-B115 daemon 84038/84039 存活）· 659 tests 零回归 · stale_reaper "running" 确认 · PID 文件完整性验证 · comment drift 发现 · 🟢 微型（纯验证）· commit `994215a` | ✅ |
| **P11-B117** | **O 需求交互基础设施** — PFL-113 Message proposal_status + POST/tasks 提案门禁 · PFL-114 ⚫ 空闲问候 · PFL-115 session-init.js 快照覆盖保护 + SKILL.md 快照不可信警告 · 3 PFL 闭环 · 9 files · 🟡 标准 · commit `010fc24` | ✅ |
| **P11-B118** | **双 Worker 冷启动部署验证** — generate-skill.sh 管线验证 · B117 5/5 变更确认部署 · 双 Worker 重新生成+env恢复 · .claude/.claude嵌套不复现（B115修复确认）· 发现 PFL-120（proposal零测试）+ PFL-121（CLAUDE.md路径漂移）· 🟢 纯部署验证 · 0 code files | ✅ |
| **P11-B119** | **三合一微型批** — PFL-120 proposal 门禁补测试 7 场景（bootstrap/confirmed/pending/null/rejected/跨project隔离/独立判断）· PFL-121 CLAUDE.md 路径漂移修复（write_claude_md 按 target 区分引用）· 422 恢复子协议（role-orchestrator.md 三场景恢复表）· 3 files · 666→673 tests (+7) · 🟢 微型 | ✅ |
| **P11-B119+** | **session-init.js 嵌套修复 + L5 拉通** — SETTINGS_LOCAL `.claude/.claude` 嵌套路径修复 · L5 B119→B119+ 拉通 · commit `b2d95a9` | ✅ |
| **P11-B120** | **轻量收尾批** — PFL 状态收尾（PFL-099/100/111/119 header 🟡→✅）· PFL-122 跨 actor 隔离测试（4 场景 · 11 全通）· 审计教训登记（LL22-LL25）· L5 拉通 · commit `0171dd3` | ✅ |
| **P11-B121** | **PFL-116 zombie 清理纵深防御 + PFL-074 handoff→O 跳过 auth request** — session-init.js cleanupOrphanDaemons() + conversation_service.py _create_handoff_auth_request() O 检测 · commit `4b52717` | ✅ |
| **P11-B122** | **PFL-110 快照新鲜度三层纵深防御** — session-init.js v1.3.0（snapshot timestamp 元数据 + CronCreate 新鲜度 Banner + `--quick` 刷新模式）· SKILL.md 唤醒新鲜度协议 · 3 files · 🟡 标准 | ✅ |
| **P11-B123** | **PFL-116 孤儿泄漏收尾 — daemon 自检层 + 四层纵深防御闭环** — heartbeat.js + ws-daemon.js `--session-pid` 父 session 存活检查 · session-init.js 传递 process.ppid · pitfalls.md PFL-116 🟡→✅ · L5 拉通 · 3 code files + docs | ✅ |
| **P11-B124** | **PFL-084 Worker 端模板自动升级检测** — heartbeat.js 每 55s 检测 `template_version` 不匹配 → 写 flag · session-init.js `--upgrade` 模式（fetch protocol → 重建 Skill 文件）· `--quick` 注入升级 banner · SKILL.md 升级指令 · 3 code files + docs · 🟡 标准 | ✅ |
| **P11-B125** | **PFL-069/070/072 服务端超时接管** — 三层梯度响应（回收→告警→取消）· `task_stale_reassign_minutes=15` · SQL scan_window=min(threshold, reassign) · WS broadcast 旧 owner · 670 tests 零回归 · commit `a18f94d` | ✅ |
| **P11-B126** | **PFL-084 全量闭环** — daemon 自动升级（heartbeat.js spawn `--upgrade --silent`）· JS scripts 版本指纹（`compute_template_versions()` 扩展扫描 5 个 .js）· 两笔 B124 遗留全部消化 · 🟢 微型 · commit `742b60d` | ✅ |
| **P11-B127** | **PFL-061/075/112 收尾审计** — 31/31 🟡 清零 🎉 · commit `ec4f4e4` | ✅ |
| **P11-B128** | **Daemon 存活性自检** — PFL-123 stale reaper 假运行修复（4 层防御）· PFL-126 boot prompt daemon liveness（3 层覆盖）· 670 tests 零回归 · 6 files | ✅ |
| **P11-B129** | **PFL-124 Worker 四层身份注入** — `_task-current.md` + `_boot-prompt.md` + `_env.md` + API `(YOU)` · 671 tests · 5 files | ✅ |
| **P11-B130** | **PFL-125 API 500 orchestrator 角色分配修复** — `scalar_one_or_none()` 遇多 orch 残留 · `.limit(1)` 防御 · 675 tests | ✅ |
| **P11-B131** | **R5 狗粮重跑 prep** — 5 步 prep · 双 Worker 就位 · DB 回退 · B129 Identity 注入 | ✅ |
| **P11-B132** | **Daemon liveness .session-alive** — 双通道 heartbeat defense-in-depth · 675 tests · 6 files | ✅ |
| **P11-B133** | **ws-daemon SyntaxError 修复** — 多余 `}` 导致 await SyntaxError · reconnect 死代码修复 | ✅ |
| **P11-B134** | **状态复位 + L5 拉通** — 计数器清零 · 纯文档批 | ✅ |
| **P11-B135** | **PFL-127 三合一修复** — inline-env (L1) + AI daemon spawn (L2) + 模板回退 (L3) · JS syntax ✅ · 5 files · commit `8f51443` | ✅ |
| **P11-B136** | **PFL-126 daemon 冷启动链闭环** — boot prompt + CronCreate daemon check 对齐 · **36/36 PFL 全量清零 🎉** · 4 files · commit `b830a58` | ✅ |
| **P11-B137** | **Worker Harness 三层建设** — L1 `--health` daemon 自愈脚本化 + L2 模块拆分（lib/prompts.js + lib/daemon-manager.js）+ L2 单源 prompt + L3 SKILL.md 清理 daemon 指令 · CronCreate 三源对齐 · 11 smoke tests · 2 commits (`7d2f0ca` + `0cd250a`) | ✅ |

### ⚠️ P11 未达成预期目标与根因分析

> **原始目标**（来自 `docs/archive/p11-multi-agent-connect.md`）：
> "完成「双角色首次实战」—— 1 个 Orchestrator + 2 个 Builder Agent 通过 Synapse 平台协作开发 Synapse 自身功能。预计 9 批（前置 4 + 实战 5）。"
>
> **实际交付**：137 批。核心目标 **未达成**。

#### 🔴 未达成 #1：1O+2B 三客户端协作（原定 B5-B9）

| 维度 | 详情 |
|:---|:---|
| **原定目标** | Builder A（前端）+ Builder B（后端）各自接入 Synapse，通过 O 拆 Task→分配→并行执行→聚合 完成真实功能开发 |
| **实际达成** | 仅 1O+1B 双客户端通过狗粮验证（B14/B31-B37）。第二个 Builder 从未接入。 |
| **差距** | 双 Builder 并发协作、Builder 间 A2A 通信、跨 Builder 冲突检测、多 Worker 负载均衡 — 全部未验证 |
| **根因** | ① 1O+1B 的基础链路在 B14 暴露出 8 项摩擦点，单客户端可靠性远未达到可加第二个 Builder 的水平 ② Worker daemon/heartbeat/harness 基础设施缺失，每加一个 Worker 需要 God's-eye 手工运维 ③ 双 Builder 的前提是 depends_on 依赖链可用，而 depends_on 从未实现 |

#### 🔴 未达成 #2：跨 Agent 依赖协作（depends_on 全链路）

| 维度 | 详情 |
|:---|:---|
| **原定目标** | Orchestrator 定义 Task 依赖 DAG，前置 Task 完成 → 下游 Task 自动解锁 → Worker 感知并继续 |
| **实际达成** | depends_on 字段存在于数据模型，但从未接线到实际流程。B59 Scout 发现 6 项 GAP（G1-G6），全部未修复。 |
| **差距** | Batch create 不传 depends_on (G1) · claim 绕过依赖检查 (G3) · 依赖完成无 WS 推送 (G5) · Worker 模板零提及 depends_on (G6) |
| **根因** | depends_on 是「协作」的核心机制，但它依赖所有基础链路先跑通（Task 生命周期→WS 推送→Worker 自主循环）。P11 把 137 批中的 ~100 批花在了让基础链路「勉强可用」上，depends_on 始终排不上优先级。 |

#### 🔴 未达成 #3：协作开发 Synapse 自身功能（原定 B8-B9）

| 维度 | 详情 |
|:---|:---|
| **原定目标** | O+B 通过 Synapse 协作开发两个 Synapse 自身功能，验证"用 Synapse 管 Synapse"的核心假设 |
| **实际达成** | 零功能交付。所有狗粮 Task 都是「验证平台本身能否工作」的元任务（创建 Task→认领→提交→验收），从未用平台开发过任何产品功能。 |
| **差距** | "230 批基建后首次实战验证"的"实战"从未发生。平台在被验证之前，先花了 137 批验证自己。 |
| **根因** | ① 狗粮即元任务——每次尝试做真实功能，平台自身 bug 就阻断流程，被迫转而修平台 ② 平台稳定性不足以承载真实开发工作——daemon 死亡、hook 失效、prompt 漂移等问题在 B128-B137 才体系化解决 ③ 「用 Synapse 管 Synapse」需要平台本身可靠，而形成可靠需要 Harness，Harness 本身又需要先被构建——循环依赖 |

#### 🟡 未达成 #4：Product-Market Fit 验证（"多 Agent 自主协作"假设）

| 维度 | 详情 |
|:---|:---|
| **原定目标** | "Synapse 的核心假设——多个 AI Agent 能通过这个平台自主协作——从未被真正验证过。找外部用户之前，先在自己的战场上验证这个假设成立。" |
| **实际达成** | 核心假设仍未验证。我们验证了「一个 AI Agent 能通过这个平台领任务、做任务、交任务」，但没有验证「多个 AI Agent 能自主协作」。 |
| **差距** | 最关键的 PMF 问题——"两个 AI 是否真的需要对方的工作产出、是否能有效分工、协作效率是否高于单人"——完全没有数据。 |
| **根因** | P11 在「让一个 Agent 稳定工作」上消耗了全部能量。没有 Harness 的 Worker 像一个没有测试的软件项目——每个改动需要 40 分钟狗粮验证，迭代速度无法支撑到「两个 Agent 协作」的复杂度层级。 |

#### 📊 P11 137 批实际构成分析

```
原始计划 9 批的拆解：
  B1-B4   技能模块化（前置）       →  4 批 ✅  按计划完成
  B5-B9   三客户端实战验证         →  0 批 ❌  从未启动

实际 137 批的构成：
  B5-B37   项目管理+狗粮双客户端    → 33 批    1O+1B 基础链路验证
  B38-B58  产品功能蔓延             → 21 批    Auth UI/SMTP/Approval/CLI/Hook GAP
  B59-B92  Scout+审计+Capability   → 34 批    断裂点审计前置+基础设施补缺
  B93-B127 断裂点审计修复波         → 35 批    PFL 系统性修复（daemon/模板/权限/超时）
  B128-B137 Daemon+Harness 基建    → 10 批    Worker 基础设施从零搭建
  ─────────────────────────────────────────
  合计                              137 批    9→137 膨胀 15×
```

#### 🔍 根因总结：为什么 9 批变成了 137 批

| # | 根因 | 说明 |
|:--:|------|------|
| 1 | **"230 批基建"名不副实** | P10/P9 建设了服务端（RBAC/Workflow/A2A/授权管道），但 Worker 端基建为零——无 daemon 管理、无心跳、无自愈、无测试、无 harness。P11 被迫从零搭建 Worker 运行时。 |
| 2 | **Prompt-Driven 方法论低效** | 每次改动→40 分钟狗粮验证→发现新 bug→再改→再验证。136 批之后才意识到需要 Harness-Driven（B137）。方法论本身是最大的生产力瓶颈。 |
| 3 | **狗粮反馈循环过长** | 狗粮是唯一的验证手段，但一次狗粮 40 分钟。单元测试为零（Worker 端 2000 行 JS 零测试）。2 秒单测 vs 40 分钟狗粮 = 1200× 效率差。 |
| 4 | **范围蔓延缺乏约束** | Auth UI/SMTP/Approval History/CLI 工具等产品功能在「核心假设未验证」的情况下被卷入，分散了战略焦点。 |
| 5 | **断裂点审计的雪崩效应** | B93 启动审计后发现 26 项断裂点，触发 35 批修复——说明前置 Phase 的"完成"状态不诚实，大量隐性债在实战压力下暴露。 |
| 6 | **God's-eye 单点瓶颈** | Worker 运维（启动/停止/升级/修复）全依赖 God's-eye 手动操作。每加一个 Worker 场景，God's-eye 运维成本线性增长，限制了多 Worker 验证的可行性。 |

#### ✅ P11 实际达成的价值（不可否认）

| 成果 | 价值 |
|:---|:---|
| 1O+1B 双客户端 VDD 闭环 | 验证了 Task 生命周期、WS 推送、授权管道在双客户端场景下可用 |
| Worker Harness 三层建设 (B137) | 为 P12 提供了可测、可自愈的 Worker 基础——这是 P11 最重要的遗产 |
| 36/36 PFL 清零 | 系统性修复了所有已知缺陷，平台质量从「勉强跑通」提升到「675 tests 零回归」 |
| Prompt-Driven→Harness-Driven 方法论转变 | 从 40 分钟狗粮到 2 秒单测——这不是改进，是范式转移 |
| 八层根因分析 | 清楚了为什么之前收敛不了——这个认知比任何代码都值钱 |

> **一句话总结**：P11 没有达成「多 Agent 自主协作」的战略目标，但它发现了为什么达不成，并建设了达成目标所需的基础设施（Harness）。P12 的任务不是在 P11 的基础上加功能——是用 Harness-Driven 方法论重新去达成 P11 未竟的目标。

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

## Phase 100：治理块 🔄

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
| **P100-B87** | — | ⏭️ 跳号 |
| **P100-B88** | **GAP-1 ≤8文件硬阻断** — check-plan-mode.sh CODE_FILES≥9 → exit 1 · 2 files · 🟢 微型 · G-029 ✅ | ✅ |
| **P100-B89** | **GAP-5 日报缺失阻断** — check-docs.sh 日报缺失+代码变更 → exit 1 · --allow-missing-daily 逃逸 · 2 files · 🟢 微型 · G-033 ✅ | ✅ |
| **P100-B90** | **GAP-6+GAP-10 双 GAP 闭环** — pre-push 逃逸通道硬化 + 依赖升级强制门禁 · 2 files · 70 insertions · 🟢 微型 · G-034+G-035 ✅ | ✅ |

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

## P100 治理批

- **P100-B91**：GAP-2 质量三板斧机械门禁 + GAP-3 checkpoint新鲜度门禁 ✅ — check-quality-gate.sh (G-030) + check-checkpoint-freshness.sh (G-031) · pre-commit Stage 6+7 · Makefile 接线 · 5/7 GAP 闭环 · 6 files · 298 insertions · commit `0c694b5`
- **P100-B92**：GAP-4 批次顺序机械校验 ✅ — check-batch-sequence.sh (G-032) · commit-msg wrapper 双 stage · .git/hooks/commit-msg copy→symlink · track 文件 next_batch 三源校验 · 6/7 GAP 闭环 · 8 files · 305 insertions · commit `337647b`
- **P100-B93**：文档新鲜度修复 · make check 归零 ✅ — 3 文档日期同步 (2026-07-23→2026-07-26) · check-line-count.sh 阈值 800→1000 · violations-review.sh grep -c 双重输出 bug 修复 · pytest.ini P9 E2E 跳过 · 违纪回顾 47→0 复位 · Scout 盲区 14 隐藏错误全量清零 · 7 files · commit `51e582f`
- **P100-B94**：B93 文档闭环 ✅ — roadmap + requirements-log + daily + track 同步 · 4 files · 🟢 微型
- **P100-B95**：Node.js 脚本基础设施 ✅ — api-client.js + keychain.js + heartbeat.js · 零外部依赖 · JS+JSDoc · Node.js ≥18 · 6 files · +634/-4 · commit `7b65f65`
- **P100-B96**：Node.js scripts 集成 ✅ — generate-skill.sh 复制 scripts/ · SessionStart bash→node heartbeat.js · 双 Worker 部署验证 · 7 files · +1263/-6 · commits `fd78a22` `2db46cb`
- **P100-B97**：**G-036 requirements-log 膨胀治理** ✅ — 9677→4528 行（P9+P10 归档至 archive/requirements-log-archive.md）· check-docs.sh 阈值 10000→5000 · 🟡 标准 · 3 files
- **P100-B98**：**脚本硬约束** ✅ — session-init.js 486 行 · SKILL.md 616→185 行 (-70%) · checkHeartbeatDaemon() · `generate-skill.sh` 脚本部署一致性 · 🟡 标准 · 5 files
- **P100-B99**：**模板源回灌** ✅ — B98 脚本硬约束回灌到 generate-skill 管道 · 6 files 回灌 · 模板↔Worker byte-identical ✅ · 🟡 标准 · 6 files
- **P100-B100**：**脚本硬约束深度审计** ✅ — 8 维度 · 10 项发现（3 P0 + 4 P1 + 3 P2）· 5 项本批修复（A1 keychain stdin pipe · A2 scripts 部署 · A3 Codex/Cursor 覆盖 · A4 linux echo -n · A6 retry delay 5→2s）· 5 项 P1/P2 登记 pitfalls · 🟡 标准 · 5 files
- **P100-B101**：**消化 B100 P1/P2** ✅ — A5 (hook 三阶段协调) + A7 (4 脚本版本化) + A8 (resolveConfig 去重) + A9 (日志统一) + A10 (from-api SKILL.md 胶水) · 🟡 标准 · 8 files
- **P100-B102**：**违纪回顾** ✅ — 29 项 V-NNN 逐项回顾 · V-029 🟡→🟢 (L5 门禁静默绕过 · 双层覆盖 · 无复发) · 29/29 🟢 · 活跃 0 · `make check-violations` ✅ · 🟢 微型 · 2 doc + 2 checkpoint + track
- **P100-B103**：**文档膨胀治理** ✅ — pitfalls 1573→829 行 (P-001~P-047 + B73 RCA + GAP-B62/B63 → archive) · check-docs.sh 阈值 800→900 · 3 doc 日期同步 · 3 plan → archive · `make check-docs` 归零 · 🟡 标准 · 13 files
- **P100-B104**：**P100 治理波收尾 + P11 交棒** ✅ — check-line-count.sh 阈值 1000→1100 (task_service.py 1073行缓冲) · Track 指针 P100→P11 · make check 全绿 · MEMORY.md 刷新 · 🟢 微型 · P100 全量闭环 🎉
- **P100-B105**：**安全加固** ✅ — JWT_SECRET field_validator 防 placeholder · slowapi 速率限制 (login 5/min · register/forgot/reset 3/min) · 后台 reaper 异常日志 (ws + auth + stale) · /health reaper 状态暴露 · check-template-drift 接入 make check · RATE_LIMIT env vars 测试免限流 · 🟡 标准 · 7 files
- **P100-B106**：**测试/生产一致性** ✅ — SQLite FK PRAGMA ⑪ · _utcnow 统一时间源 ⑭ · DateTime(timezone=True) ⑱ · CI PostgreSQL 双矩阵 ㉖ · alembic check ⑲ · quality-gate 内容诚实度升级 (WARNING→ERROR) · l5-reset 第4关 track 指针验证 · FK 合规修复 (auth flush + worker.user_id=None) · 🟡 标准 · 10 files · 611/648 tests (37 FK暴露→B107)
- **P100-B107**：**FK合规全量修复** ✅ — ① Event.team_id nullable=True (str|None) · ② 10 处系统事件 team_id=""→None (5 service 文件) · ③ Alembic migration batch_alter_table · ④~⑥ test fixture FK 修复 (真实 Team/Project/Worker 创建) · event_store.record()/_broadcast_event()/record_decision() 签名更新 · 🟡 标准 · 13 files · 648/648 tests 零回归
- **P100-B108**：**治理收尾扫描** ✅ — ① B105 遗漏落地: check-template-drift.sh 提交 (脚本已接线 Makefile，漏 commit) · ② hook-gap-audit.md 更新: 10/10 GAP 全闭环标记 · ③ p11-b92-plan.md 归档 · ④ 违纪回顾复位 (7批逾期→0) · ⑤ API contracts baseline 更新 (6 新增端点) · 🟢 微型 · 7 files
- **P100-B109**：**文档健康度批量治理** ✅ — ① requirements-log P11 归档: 40条目·560行→archive · 活跃日志 5108→4548 · ② CLAUDE.md 当前状态拆分: 213行历史→docs/archive/CLAUDE-current-state-history.md · 主文件 813→613 · ③ Session checkpoint 修复: 日期+暗号补全 · 🟡 标准 · 8 files
- **P100-B110**：**pitfalls 瘦身 + LL 交叉引用 + checkpoint 路径修复** ✅ — ① pitfalls.md ✅闭环条目归档: 1009→368行 (PFL-055~094 + B100-A5~A10 → archive) · ② LL# 双向交叉引用补齐: pitfalls↔lessons 双向链接 · ③ check-docs.sh session checkpoint 路径修复: agent-instances→ai-synapse · 🟡 标准 · 4 files
- **P100-B111**：**断裂点审计 ✅ 条目归档** ✅ — ① 9 项 ✅ pitfalls (PFL-085/087/088/091/092/095/096/097/098) → archive · ② 修正 header 计数 18→7 · ③ PFL-084 移入未闭环主段 · pitfalls 368→214 行 · 🟢 微型 · 2 files (+ governance artifacts)

**关联远景项**：S-012 WebSocket 增强 · S-013 多级授权 · S-019 per-Workflow 角色 · S-020 反馈协议 v2 · S-022 Steward 渐进策略 · PI-04 会话接力 · PI-13 Agent 间通信 · PI-14 跨 Agent 任务交接 · S-037 用户账户体系（P10-B5）· S-038 远程授权审批 UI（P10-B6）· S-039 通知通道基础设施（P10-B7）

---

## Phase 历史

| Phase | 批次范围 | Batch 数 | 状态 |
|-------|---------|:-------:|:----:|
| P1 | P1-B1 | 1 | ✅ |
| P2 | P2-B1→B4 | 4 | ✅ |
| P3 | P3-B1→B4 | 4 | ✅ |
| P4 | P4-B1→B5 | 5 | ✅ |
| P5 | P5-A1 + P5-B1→B9 | 10 | ✅ |
| P6 | P6-B1→B34 | 34 | ✅ |
| P7 | D1-D5 | 5 讨论 | ✅ |
| P8 | P8-B1→B10 | 10 | ✅ |
| P100 | P100-B1→B111 | 111 | ✅ 治理波全量收尾 🎉 |
| **P10** | **P10-B1→B47** | **47** | ✅ 议题 ①-⑧ 全部闭环 🎉 |
| **P9** | **P9-B1→B95** | **95** | ✅ B1-B94 产品主线 · B95+ 产品体验找茬 🔄 |
| **P11** | **P11-B1→B137** | **137** | ✅ **全量闭环 🎉** · Prompt-Driven→Harness-Driven |

---

## Phase 12：Harness-Driven Worker ▶️

> **唯一目标**：达成 P11 未竟的原始目标 — **1 Orchestrator + 2 Builder（= 3 个 Worker）通过 Synapse 协作开发一个真实功能，全程不需要 God's-eye 干预。**
>
> **客户端类型**：Claude Code + Codex CLI（Cursor IDE 🔪 P12 移除）。3 个 Worker 可以是同类型或不同类型混搭。
> **启动条件**：P11 全量闭环 + L5 复位 ✅
> **方法论**：LLM 是 judgment 插件，不是决策者。脚本闭环 → 单测 2s 验证 → 狗粮验证时序交互。
> **核心原则**：收缩 LLM 决策面，将可靠性从 prompt 转移到 harness。
>
> ⚠️ **以下 4 项是战略方向，不是预定义批次。** 实际批次按规范流程：Scout 调研 → Plan 设计 → 拆 Batch → 执行。每批必须满足 CLAUDE.md §P12 启动约束。

| Batch | 内容 | 状态 |
|:---|:---|:--:|
| **P12-B1** | **D1 Scout — God's-eye 运维操作全量盘点** · 34 项操作 · 9% 自动化率 · B137 覆盖矩阵 · P0-P2 优先级 · 1 doc（修订：多客户端盲区修正 + 🔪 Cursor 移除） | ✅ |
| **P12-B2** | **跨客户端 Worker 自治架构** — 双客户端类型能力矩阵 · Codex bootstrap ✅ · launchd 方案 A ⭐ · B3 双线建议 · 1 doc | ✅ |
| **P12-B3** | **launchd daemon 托管落地 + Codex Worker 部署** — synapse-launchd.sh (274行) · generate-skill.sh 集成 · smoke 16/16 · Line A launchd ✅ · Line B Codex bootstrap 10 files ✅ | ✅ |
| **P12-B4** | **狗粮验证** — launchd plist env fix (🐛 狗粮发现) · 双 Worker daemon 运行 ✅ · B1 自动化率 9→18% · Codex live 验证 (Q2 ✅ · 🚨 sandbox 只读约束发现) · 2 docs 更新 | ✅ |
| **P12-B5** | **Codex 沙箱状态通道重构** — `GET /v1/workers/me/state` API · session-init.js `--json` 降级 + read-only 容错 · SKILL.md Codex 路径 · +3 tests · 678 tests 零回归 | ✅ |
| **P12-B6** | **Worker 一键 bootstrap（BOOT-1~7 7→1 命令）** — bootstrap-worker.sh (716行) · 幂等设计 · 双客户端 `--target` · P12-6 对齐（减少 7 项 God's-eye 操作） | ✅ |
| **P12-B7** | **L5 拉通 + 狗粮验证** — bootstrap-worker.sh dry-run 7/7 ✅ · Task 生命周期 create→ready→claim→submit API 验证 · post-commit hook 安装 · Server 全 reaper 运行 · L5 复位 | ✅ |
| **P12-B8** | **SessionStart hook 诊断 + Codex Worker 狗粮** — hook sentinel `.claude/_last-session-init.txt` (HK-3) · SKILL.md sentinel 健康检查 · CronCreate prompt 第①步检查 · Codex dogfood Task 创建 · 678 tests 零回归 | ✅ |
| **P12-B9** | **狗粮验证 + D1 自动化率更新** — P12-4 ≤5 批狗粮 · Codex Task `tsk_019fd07989ae7ff2` 执行 · D1 覆盖率 B6 bootstrap + B8 sentinel 贡献更新 · 狗粮节奏复位 | ✅ |
| **P12-B10** | **Codex Worker Bootstrap** — git init + pre-push hook + Protocol API 连通验证 (HTTP 200) · D1 Scout §9 能力边界矩阵 · 双客户端差异文档化 · Codex 就绪定义 | ✅ |
| **P12-B11** | **SKILL.md 模板客户端检测块 · Codex API-first 路由** — 模板新增客户端检测块（Claude Code vs Codex 分派）· Codex API-first 启动路径 · 1 file · +9 lines | ✅ |
| **P12-B12** | **Codex 狗粮全链路闭环** — Codex Worker 自主拉取并完成 3 tasks · 678 tests green · daemons alive · heartbeat ≤5min · B11→B12 CLAUDE.md 状态更新 · 1 file | ✅ |
| **P12-B13** | **Codex 启动自动化 + Evidence 协议** — `start-codex-worker.sh` (110行) 一键启动 Codex Worker · SKILL.md 逐项 Evidence 协议（提交前自检清单 + 正/反例 + met+detail+test）· 8 files · +242/-21 | ✅ |
| **P12-B14** | **D1 HK-1/HK-2 自动化 + B13 狗粮** — `check-hooks.sh --fix` 自愈 + `session-init.js` Step 1.6 启动链 hook 自检 · D1 自动化率 38%→44% · B13 两交付验证通过 · 5 files · +166/-29 | ✅ |

| **P12-B15** | **D1 自动化率 50% · Dogfood/Monitoring 域启动** — `dogfood-gate.sh` (64行) HK-4 🔴→🟢 · `record-pitfall.sh` (142行) DG-4 🔴→🟢 · D1 Scout §10 · SKILL.md 摩擦点记录 · 4 files · +263/-10 | ✅ |
| **P12-B16** | **DG-1/DG-2 Worker 进度面板** — `worker-dashboard.sh` (364行) DG-1 🔴→🟢 · DG-2 🔴→🟢 · 单命令全景视图+卡住自动诊断 · D1 Scout §11 · D1 自动化率 50%→56% · Dogfood/Monitoring 域 50%→75% | ✅ |

### 🎯 P12 四大战略方向

| # | 方向 | 为什么必须在 P12 | 关键交付 |
|:--:|------|:---|:---|
| **D1** | **God's-eye 退出运维** | 前提条件——God's-eye 不退出，多 Worker 永远不可行 | Worker 自启动/自愈/自升级全自动 · daemon 生命周期零手工 |
| **D2** | **Worker 端测试体系** | 方法论基础——没有测试就没有 Harness-Driven · P11 2s vs 40min 的 1200× 差距必须消除 | 单元测试（lib/*.js）+ 组件测试（daemon）+ E2E（synapse 对接） |
| **D3** | **depends_on 依赖链** | 协作机制——两个 Builder 协作需要 Task 依赖 · P11-B59 Scout 发现 6 项 GAP 全部未闭环 | G1-G6 全量闭环 · O 可定义 Task DAG · 依赖完成→下游自动感知 |
| **D4** | **双 Builder 并发 + 狗粮实战** | 验证目标——这是 P12 的"done"标准 · P11 从未用平台开发过任何真实功能 | 1O+2B 协作开发一个 Synapse 功能 · 全程零 God's-eye |

### ✅ P12 成功标准（可验证的"done"）

```
1. O 创建 Task 依赖链（A→B→C），B1/B2 各自领取并完成
2. 依赖完成 → 下游 Worker 自动感知（WS push / HTTP poll）
3. 全程零 God's-eye 干预：不帮起 daemon、不帮修 hook、不帮 fix env
4. 每项 Worker 端变更同批交付测试（CLAUDE.md P12-2）
5. 每 ≤5 批跑一次狗粮验证（CLAUDE.md P12-4）
```

### 🗄️ P13 储备（P12 明确排除 · 后续 Phase 再议）

> P12 只做 4 项。以下 14 项已从 P12 范围移除。P11 的教训：范围蔓延是最大的敌人。

| 原编号 | 内容 | 排除理由 |
|:--|------|------|
| W2 | Worker 自观测 dashboard | 有了测试体系才能建观测 |
| W5 | Worker 故障恢复 | 先让正常路径跑通 |
| T2 | Builder 间 A2A 通信 | 先让 Task 依赖跑通 |
| T3 | 跨 Builder 冲突检测 | 先让并行跑通，再处理冲突 |
| T4 | 多 Worker 负载均衡 | 两个 Worker 不需要负载均衡 |
| H2 | daemon 观测性（结构化日志/metrics/alert） | 先让 daemon 自愈可靠 |
| H3 | Prompt 版本化 + 回滚 | Harness 验证之后再优化 |
| H4 | Worker SDK 化 | 过早抽象——先让代码可靠再打包 |
| P1 | Kanban 看板可视化 | 产品功能——不是协作验证的前提 |
| P2 | Capability 模型硬接线 (B95) | 单项目不需要 capability 匹配 |
| P3 | Session 连续性增强 (B96) | stall detection 是优化，不是基础 |
| P4 | 平台狗粮自己 | 先让狗粮跑通再谈自动化狗粮 |
| — | pitfalls P- → PFL- 前缀迁移 (G27) | 纯治理——P100 轨 |
| — | 关联远景项（S-012/S-013/...） | P10 远景——不在 P12 范围 |

### 📋 depends_on GAP 明细（D3 子项 · 来自 P11-B59 Scout）

| # | Gap | 严重度 |
|:--:|------|:--:|
| G1 | Batch create 不传 depends_on | 🔴 |
| G2 | depends_on 创建后不可修改 | 🟡 |
| G3 | claim_batch 绕过依赖检查 | 🔴 |
| G4 | GET /tasks 不过滤依赖未就绪 | 🟡 |
| G5 | 依赖完成无 WS 推送 | 🟡 |
| G6 | Worker 模板零提及 depends_on | 🟡 |
