---
project: synapse
phase: P11-B54 ✅ 缺口修复 — PFL-047/048/049 L1+L2 · 0 drift
last_batch: P11-B54
next_batch: P11-B55
description: Synapse 主项目 — B54 ✅ 缺口修复 · _protocol.md §13.4.1 审批角色表 · synapse-exec Human审批+审计 · L5 B53→B54 ✅ · 630 tests
---

# Synapse 轨道

## 指针

| 轨道 | last_batch | next_batch | 说明 |
|------|:---:|:---:|------|
| **P10** | P10-B47 | — ✅ | P10 全量闭环 🎉 · 47 批 |
| **P9** | P9-B100 | — ✅ | P9 全量闭环 🎉 · 100 批 |
| **P100** | P100-B87 | **P100-B88** 🔜 | B86 ✅ 违纪回顾（V-027/V-028 🔴→🟢）· B87 ✅ 治理清理（违纪回顾 39→0 + 3doc 日期刷新 Jul 19→23 + D-P11-015 LL18 登记） |
| **P11** | P11-B54 | **P11-B55** 🔜 | B1-B54 ✅ · B53 狗粮验证 ✅ · B54 缺口修复 ✅ · _protocol.md §13.4.1 · synapse-exec · L5 B53→B54 ✅ |

## P11 路线图：多 Agent 接入战

> 战略依据：Phase 7 三角色模型（1 Orchestrator + 2 Builder）· 230 批基建后首次实战验证
> 启动：2026-07-19 · 重拆：2026-07-19（ADR-006 范围扩展 · 7→9 批）

```
┌─ 前置：Skill 模块化 + 角色隔离（4 批）────────────┐
│                                                    │
│ P11-B1 ✅ ADR-006 角色隔离 · 围栏落地（L0/L1）       │
│   — 三角色模板负面清单 + SKILL.md 硬门禁 + CLAUDE.md  │
│   — 🟡 标准 · 5 files                              │
│                                                    │
│ P11-B2 ✅ ADR-006 角色隔离 · 观测 + 服务端（L2/L3）   │
│   — _protocol.md + check-role-isolation.sh + 服务端  │
│   — 🟡 标准 · 4 files · L5 拉通 ✅                   │
│                                                    │
│ P11-B3 ✅ Skill 内容升级 · 方法论                    │
│   — 拆Task方法论+Verification+Evidence+工具链        │
│   — 🟡 标准 · 4 files · architecture.md §4.1 修复   │
│                                                    │
│ P11-B4 ✅ 项目约定 + 生成管线 · L5 拉通 🎉         │
│   — conventions-*.md + generate-skill.sh 适配      │
│   — 🟡 标准 · 5 files · Skill 模块化前置全量闭环   │
└────────────────────────────────────────────────────┘
          ↓
┌─ 项目管理补齐（P11 重排）────────────────────────┐
│ P11-B5 ✅ 项目管理增强 · 8 files                  │
│   — Projects 始终可见 + 侧边栏导航                 │
│   — ProjectDetail 页（Info/Roles/Conventions）     │
│   — Admin role API 接前端（assign/revoke/list）    │
│                                                    │
│ P11-B6 ✅ Skill 生成管道闭环 · 3 files            │
│   — conventions 读取路径修复（template_service.py）│
│   — --from-api 模式（generate-skill.sh）          │
│   — _task-current.md D-P11-010 决策落地            │
│                                                    │
│ P11-B7 ✅ 串联就绪审查 🚧                         │
│   — 7 维前置条件逐项验证 · 全链路 VAR 管道测试     │
│   — 判定: GO ✅ → B8 实战验证启动                  │
└────────────────────────────────────────────────────┘
          ↓
┌─ 实战验证（狗粮驱动）────────────────────────────┐
│ P11-B8 ✅ 地基 — project_key + 权限引擎          │
│   — project_key_hash · permissions.py ·          │
│   — verify_api_key PENDING→ACCEPT 修复 · 5 files  │
│                                                    │
│ P11-B9 ✅ 接线 + 项目发现                         │
│   — 2端点角色绑定 · GET /workers/me/projects      │
│   — Protocol API project_key 鉴权 · 5 files       │
│                                                    │
│ P11-B10 ✅ 模板适配                                  │
│   — SYNAPSE_AGENT_ID→SYNAPSE_WORKER_ID · 3 files     │
│                                                    │
│ P11-B11 ✅ 前置阻断项全量审计                          │
│   — 11 项（3 阻断 + 5 摩擦 + 3 决策）· 非产品 Batch    │
│   — 0 code files · memory 登记                        │
│                                                    │
│ P11-B12 ✅ Feature Scope 定义                        │
│   — "Worker 名称富化" — API 消灭裸 Worker ID         │
│   — 狗粮范围决策 · 0 code files                      │
│                                                    │
│ P11-B13 ✅ 阻断修复 + 环境搭建                        │
│   — ✅ project_key · ✅ worker 创建 · ✅ 模板修复     │
│   — ✅ 5 项发现闭环 · generate-skill.sh bugfix       │
│                                                    │
│ P11-B14 ✅ 狗粮全链路验证                             │
│   — Orchestrator + Builder 双终端接入→Task 全生命周期   │
│   — 8 项摩擦点 + 2 项违纪 · Worker 名称富化上线     │
│                                                    │
│ P11-B15 ✅ 权限修复（PFL-034 + PFL-039）              │
│   — assign_task + verify guard require_role→         │
│   — require_permission · 根因修复                    │
│                                                    │
│ P11-B16 ✅ God's-eye 决策 + SessionStart 部署        │
│   — PFL-037 角色正式化 · PFL-038 hook 部署           │
│                                                    │
│ P11-B17 ✅ 狗粮发现消化（PFL-035/036/040）            │
│   — PFL-035 ready 强制 Verification · PFL-036      │
│   — handshake 返回 WS URL · PFL-040 Swagger token   │
│                                                    │
│ P11-B18 ✅ Worker 可见性 + Catch-22（PFL-032/033）    │
│   — _worker_has_project_role() helper              │
│   — get_task() 可见性过滤角色感知化                    │
│   — TaskResponse 新增 version_no                    │
│                                                    │
│ P11-B19 ✅ Bootstrap router 接线                     │
│   — B14 遗留缺陷（router 未挂载）· 2 行 fix · V-027     │
│   — 18 tests 0→18                                  │
│                                                    │
│ P11-B20 ✅ hooks 补测 + 防御验证 + L5 复位             │
│   — check-hooks.sh 四场景 · 裸奔期 12 commits 审计    │
│   — PFL-041 评估 → B21 实施候选                       │
│                                                    │
│ P11-B21 ✅ PFL-041 WS 推送 3/3 步闭环 🎉              │
│   — task_service.py 9 functions → broadcast_to_actor │
│   — verification_service.py COMPLETED/REJECTED → WS  │
│   — ws.py auto-subscribe task.* (Workers + Humans)   │
│   — Worker SKILL.md 模板 WS push 流程文档化            │
│   — 624 tests 零回归 · dogfood Task 已创建            │
│                                                    │
│ P11-B22 ✅ 授权审批 WS 实时化 🎉                        │
│   — ws.py humans auto-subscribe authorization_request.*│
│   — Approvals.tsx useWebSocket hook 实时刷新列表        │
│   — event_store → broadcast_to_team 闭环 · 2 files    │
│                                                    │
│ P11-B23 ✅ WS 加固三板斧 🎉                                │
│   — ws_manager.graceful_shutdown() 优雅关闭                │
│   — ws_max_connections 连接数上限 (200) + 门禁 (4013)       │
│   — ws_max_message_size 消息大小限制 (64KB)                 │
│   — main.py lifespan 关机钩子 · 🟡 标准 · 4 files          │
│                                                    │
│ P11-B24 ✅ 重复事件去重 🎉                                  │
│   — authorization_service create/respond 移除冗余         │
│     broadcast_to_actor（event_store → broadcast_to_team   │
│     已覆盖全队 · Worker 通过 auto-subscribe 收到）         │
│   — expire/cancel 保留（team_id="" 不触发全队广播）        │
│   — task_service.py 巡检通过（P11-B21 新加 · 不同模式）    │
│   — 🟢 微型 · 1 file · 624 tests 零回归                  │
│                                                    │
│ P11-B25 ✅ CLI 授权体验 — 等待提示 + 超时降级                │
│   — SKILL.md 模板新增「202 CLI 用户体验」节                  │
│   — ⏳ 即时响应模板（替代裸错误码）                            │
│   — 等待期间行为规则（WS 静默 / HTTP 一次提示后静默轮询）      │
│   — ✅ 审批通过自动重试 / ❌ 被拒告知用户                     │
│   — ⏰ 超时降级：5 分钟后提供 3 个选项（继续/重试/手动）      │
│   — 降级规则：最多循环 2 次（15 分钟强制降级）+ task blocked  │
│   — 🟢 微型 · 1 file (纯文档)                               │
│                                                    │
│ P11-B26 ✅ Worker WS 长连接方案评估                      │
│   — 方案 A sidecar / B hook / C 接受poll · 三选一       │
│   — 推荐 C：HTTP Poll 为 Worker 永久发现模式              │
│   — WS 留给持久客户端（Admin UI · IDE 插件）              │
│   — 产出设计文档 + 后续 B27/B28 · 🟢 微型 (纯设计)       │
│                                                    │
│ P11-B27 ✅ SKILL.md 启动流重构                        │
│   — 新增 Step 3.5 状态同步（HTTP Poll 拉取待处理状态）     │
│   — 双通道重新定位：HTTP Poll 主通道 · WS 可选优化        │
│   — 模板 + builder + orchestrator 三文件同步              │
│   — 🟢 微型 · 3 files (纯文档)                          │
│                                                    │
│ P11-B28 ✅ 架构文档更新                                │
│   — worker-admin-interaction-flow.md 双通道重新定位      │
│   — 时序图更新 · 持久 vs 短生命周期客户端分工             │
│   — 🟢 微型 · 1 file (纯文档)                           │
│                                                    │
│ P11-B29 ✅ 双客户端拉通 Scope 定义                      │
│   — 8 批拆解（B29→B37）· 狗粮 Prep→Run→收割→修复→闭环   │
│   — 现状评估（B1-B28 全部就绪）· 风险识别 · PFL-042 观察  │
│   — 🟢 微型 · 1 file (纯设计)                           │
│                                                    │
│ P11-B30 ✅ L5 B28→B29 拉通                             │
│   — 零 drift · 2批纯文档 · HTTP-first 三文档对齐验证      │
│   — 计数器复位 · 📄 治理制品全量同步                      │
│   — 🟢 微型 (L5 质量保障)                                │
│                                                    │
│ P11-B31 ✅ 狗粮 Prep — Task 定义 + 环境校验              │
│   — 双客户端连通性验证（DB + API 双检）                    │
│   — Task #1 定义（Orchestrator 视角）                    │
│   — Task #2 定义（Builder 视角）                         │
│   — Verification 条件 + 边界约束 + 失败模式              │
│   — 🟡 标准 · 1 file (plan) + 治理制品                   │
│                                                    │
│ P11-B32 ✅ 狗粮 Run ① — 单 Task 全链路闭环               │
│   — Orchestrator + Builder 双终端独立协作                 │
│   — 14min · 4 events（created→assigned→submitted→completed）│
│   — 6 摩擦点（首轮）+ 7 摩擦点（Redo）→ PFL-039→P-045   │
│   — 🟡 标准 · 1 plan + 治理制品                          │
│                                                    │
│ P11-B33 ✅ SKILL.md 模板全面升级 — v2 🎉                  │
│   — Worker 行为契约 v2 · 10 项模板改进                    │
│   — _protocol.md 6 处 + role-orchestrator 4 条 +         │
│     role-builder 3 条 + role-steward 跟修                │
│   — B32 13 摩擦点 10/13 消化                              │
│   — 🟡 标准 · 3 files                                    │
│                                                    │
│ P11-B34 ✅ 授权硬门禁 + JSON 转义 🎉                       │
│   — PFL-046 授权硬门禁：task_service 9 处 +                │
│     verification_service 1 处 → _check_no_pending_auth()  │
│   — JSON 转义修复：@field_validator 双保险                 │
│   — B32 摩擦点 2/13 消化 + PFL-046 登记                   │
│   — 🟢 微型 · 2 files · 624 tests 零回归                  │
│                                                    │
│ P11-B35 ✅ Key 存储隔离 — P-045 长期方案 🎉🎉              │
│   — OS 密钥链三级架构（Tier1 macOS/Tier2 Linux/Tier3 fallback）│
│   — tools/synapse-key.sh ⭐ 新建                          │
│   — tools/check-key-isolation.sh ⭐ 新建（审计）           │
│   — bootstrap_service.py 密钥链感知化                     │
│   — 双 Worker .env 明文 Key → macOS Keychain              │
│   — B32 狗粮 13/13 全量闭环 🎉                             │
│   — 🟡 标准 · 11 files · 626 tests                        │
│                                                    │
│ P11-B36 ✅ 审批内容富化 🎉                                  │
│   — _to_response async 化 · 2× Worker name lookup         │
│   — 前端 worker_name 替代裸 worker_id · operation 人性化   │
│   — B29 8 批拆解收尾                                       │
│   — 🟡 标准 · 5 files · 624 tests 零回归                   │
│                                                    │
│ P11-B37 ✅ L5 B30→B37 全量拉通 + 方向复盘 🎉               │
│   — 叙事一致性验证（B29→B36 零 drift）                     │
│   — 文档全量刷新（CLAUDE.md + roadmap + track + reqlog）    │
│   — 双客户端 8 批拆解全量闭环                               │
│   — 🟢 微型 · L5 质量保障 · 纯文档                          │
│                                                    │
│ P11-B38 ✅ 登录页优化 — 删 Dev Login + Remember Me         │
│   — 移除 Dev Login 按钮（调试用自动登录）                    │
│   — Remember Me checkbox · email localStorage 持久化        │
│   — 🟡 标准 · 3 files · commit 030c477                      │
│                                                    │
│ P11-B39 ✅ 种子数据修复 — Hunter email/password 账号        │
│   — seed-synapse-project.py 新增 _ensure_hunter_user()      │
│   — Hunter User → Worker → admin ProjectActorRole           │
│   — SYNAPSE_HUNTER_PASSWORD 环境变量配置                     │
│   — 🟢 微型 · 1 file                                        │
│                                                    │
│ P11-B40 ✅ Auth 页面 SPA 路由 + CSS 重构                    │
│   — <a>→<Link> SPA 导航修复（4 页面 × 9 处）                │
│   — Auth.module.css 共享样式提取                            │
│   — ForgotPassword 成功状态判断修复                          │
│   — 🟡 标准 · 6 files                                       │
│                                                    │
│ P11-B41 ✅ SMTP 生产模式 + 忘记密码邮件流程 🎉                │
│   — email_service 双引擎（aiosmtplib→stdlib 降级）           │
│   — ForgotPassword debug token 移除 · 统一生产 UI            │
│   — tools/smtp-sink.py 本地 SMTP 接收器 ⭐ 新建              │
│   — E2E: Forgot→SMTP→Reset→Login→防重用 全链路闭环           │
│   — 🟡 标准 · 6 files · 624 tests 零回归                     │
│                                                    │
│ P11-B44 ✅ Approval History + 质量三板斧 🎉                  │
│   — Approvals 页 Pending/History 双 Tab 拆分                │
│   — status=all + target_resource_name（Task 标题）富化        │
│   — History 卡片：Task 标题 + 操作描述 + 元信息一行            │
│   — 状态筛选（全部/已批准/已拒绝/已过期/已取消）              │
│   — 25 条 EN+ZH i18n · .shell max-width 一致性修复           │
│   — CLAUDE.md §7.1 三板斧（Scout+自检+≤3批Checkpoint）       │
│   — 🟡 标准 · 7 files · 624 tests 零回归                     │
└────────────────────────────────────────────────────┘
```

### P11 后续方向（不预编号，方向指引）

> God's-eye 是开发期拐杖，产品化后去掉。每个方向拆多少批在实践中决定。

| 方向 | 目标 | 关键交付 |
|------|------|------|
| **授权审批实时化** ✅ | 审批人无需盯终端，在 Synapse 网站实时看到授权申请并处理 | ws.py humans 订阅 `authorization_request.*` · Approvals 页面 WS 实时刷新 · P11-B22 |
| **双客户端拉通** ✅ | Orchestrator + Builder 各一个 Claude 会话，通过 Synapse 协作 | Scope ✅ B29 → L5 ✅ B30 → Prep ✅ B31 → 狗粮 B32 ✅ → 消化 B33-B35 ✅ → 收尾 B36 ✅ · B37 待定 |
| **三客户端实战** | 1 Orchestrator + 前端 Builder + 后端 Builder 真实协作 | 多角色并发 · WS 推送贯穿 VDD 循环 |
| **看板可视化** | 任务状态实时看板，拖拽/状态流转可视化 | Dashboard Kanban · 实时 WS 更新 · 拖拽改变状态 |

## 路线图（2026-07-21 更新 · P100/P9 双轨分治）

### P100 治理轨道（B35→B45）

```
P100-B35 L5 拉通 ✅          ← 解门禁，P100-B34 + P9-B81
    ↓
P100-B36 S-011 日报完善 ✅  ← 小·1-2f（methodology.md 日报门禁详解）
P100-B37 make check 零警告 ✅  ← 小·4f（L5 拉通 + 6 项清零）
P100-B38 S-023 一致性扫描 ✅ ← 中·3-4f（扫描工具就位，验证后续改名）
    ↓
P100-B39 S-016 Scout        ← 纯分析·1-2f（产出文件清单 + 分层方案）
P100-B40 S-016 (1/6) ✅     ← DB+Model ✅
P100-B41 S-016 (2/6) ✅     ← Schema+Constants ✅
P100-B42 S-016 (3/6) ✅     ← Service 层 ✅
P100-B43 S-016 (4/6) ✅     ← Schema 收尾 + API 路由 · 9 files · L5 ✅
P100-B44 S-016 (5/6) ✅     ← 剩余路由 + tasks/ws/token_usage/dashboard
P100-B45 S-016 (6/6) ✅     ← 测试改名 + 前端 client + i18n 合并 · L5 拉通
    ↓
P100-B46 S-008 L5 自动化 + 违纪回顾 ✅  ← 违纪回顾（V-019 🟢·V-022 评估）+ PI review · 4 files
    ↓
P100-B47 治理 backlog 消化(1) ✅  ← V-022 🟢 闭环 · G3 agent_id 废弃 key 删除 · G5 死代码清理 · 7 files
    ↓
P100-B48 治理 backlog 消化(2) ✅  ← G23 ws.py KeyError 修复 · G4 _get_worker 改名 · G18 PREFIXES 常量 · G15 死代码 · 5 files
    ↓
P100-B49 治理 backlog 消化(3) ✅  ← G8 from_attributes · G11 console.error · G12 hashBatchColor dedup · G14 TeamResponse.model_validate · G19 localStorage render body · 8 files
    ↓
P100-B50 治理 backlog 消化(4) ✅  ← G2 API_BASE 收敛 · G10 localStorage 文档化 · G16 as never 移除 · G17 useCallback · G20 CursorPage · 7 files
    ↓
P100-B51 治理 backlog 消化(5) ✅  ← G6 scan 端点单数→复数 · 4 files · 17/23 已消化
    ↓
P100-B52 治理 backlog 消化(6) ✅  ← G13 t() 变量插值 · 7 files · 18/23 已消化
    ↓
P100-B53 治理 backlog 消化(7) ✅  ← G7 Dashboard SQL → Service Layer · 2 files · 19/23 已消化 · L5 拉通
    ↓
P100-B54 治理 backlog 消化(8) ✅  ← G9 DOM 绕过 React 修复 · 4 files · 20/23 已消化
    ↓
P100-B55 治理 backlog 消化(9) ✅  ← G21 S-042 空catch console.error · 6 files · 21/23 已消化
    ↓
P100-B56 治理 backlog 消化(10) ✅  ← G22 S-043 分页契约收尾 · 8 files · 22/23 G 级全量消化 🎉
    ↓
P100-B57 违纪停车场消化 ✅  ← 7 项 🟡→🟢 · 7 files · P100 治理 backlog 全量闭环 🎉
    ↓
P100-B58 G1 httpOnly ✅  ← 8 files · G1 JWT localStorage→httpOnly cookie · P100 全量闭环 🎉（23/23 G + 7/7 违纪）
P100-B59 遗留 doc 清理 ✅  ← 3 files · P100-B57 doc 防呆文件提交（7 项 🟡→🟢 闭环）
    ↓
P100-B60 分页常量收敛 ✅  ← 11 files · 13 处 Query(50)→DEFAULT_PAGE_SIZE · P100 重开 🟡 审计项
	    ↓
P100-B61 状态字符串→枚举(1) ✅  ← 8 files · Services 核心层
	    ↓
P100-B62 状态字符串→枚举(2) ✅  ← 8 files · Services 剩余 + auth + ScanVerdictStatus
	    ↓
P100-B63 状态字符串→枚举(3) ✅  ← 6 files · Routers + schemas + B62 补漏 · L5 B61→B63
		    ↓
P100-B64 actor_type/owner_type 基础层 ✅  ← 8 files · ActorType+SYSTEM · Schemas+Auth+Dependencies
		    ↓
P100-B65 actor_type/owner_type 服务层(重) ✅  ← 5 files · task_service+worker_service+failure_detector+cooperation+worker_scheduler
		    ↓
P100-B66 服务层(轻) ✅  ← 3 files · ws_manager+lease_detector+auth_service · ActorType 枚举收尾
		    ↓
P100-B67 路由层 ✅  ← 4 files · tasks+events+token_usage+ws · L5 B64→B67 🎉
		    ↓
P100-B68 收尾 ✅  ← 3 files · docstring 枚举引用更新 · 零残留验证 · B95 🟡 审计全量闭环 🎉
		    ↓
P100-B69 V-023 防呆 (部分) ✅           ← l5-reset.sh --yes 交互式确认 + L5 证据字段 · v1 防呆（不足以防止空转）
P100-B71 V-023 防呆 v2 + V-024 P1 ✅  ← l5-reset.sh 证据质量门禁（长度+路径+动词 三关机械校验）· session-checkpoint.sh L5 状态输出 · V-023 🟢🔴→🟢 闭环 · V-024 🟢 闭环
P100-B72 G25 文档膨胀 + G26 议题编号 ✅  ← methodology.md §5.6 文档生命周期 + check-docs.sh 文档行数扫描 + check-issue-numbers.sh 三方对齐校验 · tracks/synapse.md P10段头修复 · 5 files · G25 🟠→🟢 G26 🟠→🟢
P100-B73 B72 工具发现消化 ✅  ← 17 plan .md → docs/archive/plans/ · >800 WARNING→ERROR 升级 · S-060/S-061/S-062 补 📅 · 5 files
P100-B74 data-model.md 拆分 ✅  ← §3 实体→data-model-entities.md · 1032→285 行 · 3 files
P100-B75 methodology.md 拆分 ✅  ← 五层金字塔+SMG+反模式→methodology-reference.md · 761→399 行 · 4 files
P100-B76 S-061 architecture.md 授权管道补齐 ✅  ← §5.4 三层授权模型+AuthorizationRequest+Worker闭环 · v2.0→v2.1 · 6 files
P100-B77 security-model.md 拆分 ✅  ← §6+§10-12→security-model-appendix.md · 595→499行 · S-062闭环 · 6 files
P100-B78 data-model.md 实体补齐 ✅  ← 议题⑤⑥ 4实体文档化(ProtectionReport/CircuitBreaker/DecisionAudit/TaskWorkerConversation) · 19→23实体 · S-060闭环 · 4 files
	    ↓
P100-B79 onboarding.md 拆分 ✅  ← §3.1-3.8+§5+§6+Appendix→onboarding-api-reference.md · 751→273行 · 4 files
		    ↓
P100-B80 S-036 安全模型审计 ✅  ← 8项doc↔code drift修复 · 60→59事件类型 · §8传输安全诚实化 · 3 files
		    ↓
P100-B81 文档全局刷新 ✅  ← master-backlog/roadmap/requirements-log/daily 全量同步 · 含 L5豁免修复 · 7 files
		    ↓
P100-B82 战略决策登记 ✅  ← PI-05→远期 · S-013 确认远期 · 治理扫描 S-067~S-072 登记 · 2 files
		    ↓
P100-B83 ✅ 治理消化(1)  ← S-070 SMG RA(4 Critical) + S-067 EventType(59→60) + S-068 P10 header(进行中→闭环) + S-069 ScanResult实体(23→24) · S-067~S-070 ✅ · 5 files
		    ↓
P100-B84 ✅ 治理消化(2)  ← S-071 dep lock + S-072 violations counter (~4 files) · S-067~S-072 全量消化 🎉
	    ↓
P100-B85 ✅ G-028 治理基础设施独立批  ← check-hooks.sh 防呆（V-028 修复） + make check 管道接线 + CLAUDE.md 启动自检增强 · 从 P11-B19 L5 commit 中拆出独立 P100 编号
	    ↓
P100-B86 ✅ 违纪回顾 — V-027/V-028 🔴→🟢 闭环 · 26/27 🟢 · 活跃清零 🎉
	    ↓
P100-B87 ✅ 治理清理 — 违纪回顾（39→0 复位 · V-029 状态确认 🟡）· 3 doc 日期刷新（architecture/lessons/methodology Jul 19→23）· D-P11-015 孤儿登记（LL18 授权管道双类型单表设计）· make check 归零
```
> P100 暂告段落（B85）。G-028 原混入 P11-B19 L5 commit（`6c1fdbb`），本批纠正：治理基础设施走 P100 轨道，不混入功能 Phase。

### P100 治理 backlog（P9-B89 Scout + 分流 · 22 项 · P9 闭合后执行）

| # | 内容 | 位置 | 严重度 |
|:--:|------|------|:--:|
| G1 | JWT localStorage + XSS 组合风险 → httpOnly cookie 改造 | AuthContext.tsx | 🔴 | ✅ P100-B58 |
| G2 | `API_BASE` 5 文件重复 → 收敛到 client.ts | AuthContext/Docs/Login/WorkerDetail | 🟠 | ✅ P100-B50 |
| G3 | `verify_api_key` 返回废弃 `agent_id` key | auth.py:110 | 🟠 | ✅ P100-B47 |
| G4 | `_get_agent()` 内部函数 5 处未改名 | worker_scheduler.py | 🟠 | ✅ P100-B48 |
| G5 | `actor_type in ("agent", "worker")` 死代码 2 处 | dependencies/events | 🟠 | ✅ P100-B47 |
| G6 | `POST /v1/scan/` 单数命名 | scans.py | 🟠 | ✅ P100-B51 |
| G7 | Dashboard 内联 SQL — 与 service 层重复 | dashboard.py | 🟠 | ✅ P100-B53 |
| G8 | `ScanResponse`/`AnalysisResponse` 缺 `from_attributes` | scan.py/analysis.py | 🟠 | ✅ P100-B49 |
| G9 | 4 处 DOM 操作绕过 React | WorkerDetail/WorkerList/Tasks/ConfirmModal | 🟠 | ✅ P100-B54 |
| G10 | `ProjectSelect` onChange 隐藏 localStorage 副作用 | ProjectSelect.tsx | 🟠 | ✅ P100-B50 |
| G11 | `console.error` 残留 2 处 | WorkerDetail.tsx | 🟡 | ✅ P100-B49 |
| G12 | `hashBatchColor` 两文件重复定义 | TaskCard/TaskDetail | 🟡 | ✅ P100-B49 |
| G13 | `t()` 用 `.replace()` 而非变量插值 3 处 | Teams/OAuth/HistoryList | 🟡 | ✅ P100-B52 |
| G14 | `TeamResponse` 返回 raw ORM 对象 | teams.py | 🟡 | ✅ P100-B49 |
| G15 | `ScanListResponse` 定义但从未使用 | scan.py | 🟡 | ✅ P100-B48 |
| G16 | `Docs.tsx` 用 `as never` 绕过类型检查 | Docs.tsx | 🟡 | ✅ P100-B50 |
| G17 | `eslint-disable` react-hooks/exhaustive-deps | WorkerList.tsx | 🟡 | ✅ P100-B50 |
| G18 | `generate_api_key` `.replace("ag_", "")` 脆弱 | auth.py | 🟡 | ✅ P100-B48 |
| G19 | WorkerDetail/BatchDetail render body 读 localStorage | WorkerDetail/BatchDetail | 🟡 | ✅ P100-B49 |
| G20 | Scan 端点缺 OpenAPI `responses` 注解 | scans.py | 🟡 | ✅ P100-B50 |
| G21 | S-042 空 catch — 10 处静默吞错修复（D-P9-012 · P9-B89 Scout 分流） | 多文件 | 🟠 | ✅ P100-B55 |
| G22 | S-043 分页契约 — total=None · cursor 校验 · response_model（D-P9-013 · P9-B89 Scout 分流） | API routers | 🟠 | ✅ P100-B56 |
| G23 | ws.py L167 `actor["actor_id"]` KeyError — verify_api_key 返回 key `worker_id` 与 JWT 路径 `actor_id` 不一致（P100-B47 发现） | auth.py + dependencies.py | 🔴 | ✅ P100-B48 |

### P100 治理 backlog（新增 · V-023 防呆 · 2026-07-16）

| # | 内容 | 位置 | 严重度 |
|:--:|------|------|:--:|
| G24 | V-023 防呆 v2 ✅ — `l5-reset.sh` 证据质量门禁（长度+路径+动词 三关机械校验）+ V-024 session-checkpoint.sh L5 状态输出 | tools/l5-reset.sh + session-checkpoint.sh | 🟢 P100-B71 |
| G25 | 文档膨胀治理 — requirements-log 7400+行 · 每批 doc overhead 6-7 files · B32 新建 200行架构文档 · 需建立文档生命周期（新建/合并/归档/删除）机制 | 多文件 | 🟠 → ✅ P100-B72 |
| G26 | 议题编号与状态自洽校验 — B32 将议题 ⑦ 通知通道误标为议题 ⑥ 且误标完成 · 需机械校验：议题编号↔track 定义↔CLAUDE.md 状态三方对齐 | CLAUDE.md + tracks | 🟠 → ✅ P100-B72 |
| G27 | pitfalls 前缀从 P- 改为 PFL- — 与 Phase-Batch P{N}- 彻底区分。新条目直接使用 PFL- 前缀，旧 35 条 P- 逐步迁移 | docs/pitfalls.md | 🟡 待排期 |
| G28 | **Git hooks 完整性防呆** — V-028：迁库后 hooks 静默丢失，L5 三层防线全部失效。check-hooks.sh 三线防御（make check 首位门禁 + CLAUDE.md 启动自检 + `make hooks` 一键安装） | tools/check-hooks.sh + Makefile + CLAUDE.md | 🟢 P100-B85 |

### P10 架构升级（B1→B47 · 议题 ①-⑧ 全部闭环 🎉）

> 8 个议题：① 四实体数据模型 ✅ ② 用户账户体系 ✅ ③ 异步授权管道 ④ per-Workflow 角色 ⑤ A2A 通信 ⑥ 保护报告+熔断+决策审计 ⑦ 通知通道 ⑧ Phase/Sprint 模式

```
P10-B1→B9  议题 1: 数据模型重构 ✅    ← ActorType·User·Worker·Team·ProjectActorRole·ADR-004 四张表落地
    ↓
P10-B10  Email/Password API 端点 ✅   ← POST /register + /login · 4 files + 12 tests · 353 tests
    ↓
P10-B11  前端 Email/Password 登录+注册 ✅  ← Login 表单 + Register 页面 + AuthContext email 方法 + i18n · 8 files · 371 tests
    ↓
P10-B12  Password Reset 后端 ✅        ← forgot-password + reset-password 端点 · 380 tests · L5 B1→B12 拉通复位
    ↓
P10-B13  Password Reset 前端 ✅        ← ForgotPassword.tsx + ResetPassword.tsx · 6 files · API client + routes + i18n
    ↓
P10-B14  议题 2 收尾 ✅                 ← Password Reset 全链路 E2E 验证 + migration 修复 + L5 B1→B13 拉通
	    ↓
P10-B15  Email 基础设施 ✅                  ← SMTP config + email_service + 模板 + Token 泄露修复 · 9 files · 34 tests
	     ↓
P10-B16  DB 宽列 migration ✅                ← user.is_super_admin/force_password_change · prt.created_by_admin
		    ↓
P10-B17  RBAC 基础层 ✅                         ← is_super_admin 首用 · JWT + ActorInfo + require_super_admin + require_role 超管绕过
			    ↓
P10-B18  project_actor_roles 接线 ✅              ← Service + Dependency + Admin 端点 · 三层拉通 · 议题 3 启动
P10-B19  require_project_role 端点接线 ✅          ← 4 routers + 创建者自动 admin · 议题 3 基础设施完成
P10-B20  AuthorizationRequest 数据模型 ✅          ← 双类型单表 + Schema + Migration · 议题 3 后半段启动
P10-B21  AuthorizationRequest Service 层 ✅        ← create/respond/heartbeat/expire/cancel + 流控 + 级联失效
P10-B22  AuthorizationRequest API 端点 ✅          ← POST/GET/PATCH/Heartbeat · 4 endpoints
P10-B23  前端审批 UI ✅                            ← /approvals 跨 Project 聚合 + 审批卡片 + API client + i18n · 议题 3 🎉
P10-B24  议题 4 数据模型 ✅              ← Workflow + WorkflowRole 表 · ProjectRole 枚举 · Migration · 议题 4 启动
P10-B25  议题 4 Schemas + Service ✅      ← Workflow CRUD + WorkflowRole CRUD (upsert) + EventStore
P10-B26  议题 4 API 路由层 ✅             ← 8 端点 + require_role("admin") 守卫 · 议题 4 全链路闭环 🎉
P10-B27  议题 4 收尾 ✅                   ← data-model.md 实体补齐 + L5 B24→B27 拉通 · 议题 4 完整闭环 🎉
P10-B28  议题 5 A2A 数据模型 ✅            ← task_worker_conversation 表 + ConversationMessageType · 议题 5 启动
P10-B29  议题 5 A2A Service ✅               ← 消息 CRUD + @mention + handoff · 同议题合并 B28→B30
P10-B30  议题 5 A2A API ✅                    ← 4 端点 + require_project_role · 议题 5 前半闭环 🎉
P10-B31  S-065 授权闭环 ✅                    ← 403→202 拦截器 + auto-grant + polling endpoint · 议题 5 全链路闭环 🎉
P10-B32  议题 7 WS Push 🟡                    ← authorization_service WS push + ws.py auto-subscribe + 双通道架构文档 · 议题 7 通知通道启动 (WS Push ✅ · Email/WebPush/Webhook ⬜)
P10-B33  议题 7 Email 通知 ✅                   ← notification_service.py (notify_project_admins) + auth_request_notification 模板 · authorization_service 接线 · 4 files · 557 tests
P10-B34  议题 7 Webhook 通道 ✅               ← Project.webhook_url + Migration · notification_service.notify_webhook() · httpx POST fire-and-forget · 7 files · 557 tests · 议题 ⑦ 3/4
P10-B35  议题 6 数据模型 ✅                    ← ProtectionReport + CircuitBreaker + DecisionAudit 三张新表 · 6 枚举 + 5 EventType · 3 ID 前缀 · Migration · 7 files · 559 tests · 议题 ⑥ 启动 🔜 Service+API
P10-B36  议题 6 Service 层 ✅                   ← protection_service + circuit_breaker_service + decision_audit_service · 7 files · 602 tests
P10-B37  议题 6 API 层 ✅                        ← 9 端点 · 议题 ⑥ 全链路闭环 🎉 · 604 tests
P10-B38  文档债收尾 ✅                            ← S-060~S-062 · data-model/architecture/security-model 补齐 · 3 docs · 602 tests
P10-B39  代码债修复 ✅                            ← S-063+S-064 · check_project_role 共享函数 · heartbeat 成员校验 · 3 files · 606 tests
P10-B40  议题 ⑧ Phase/Sprint 模式 ✅             ← S-059 · use_phase_mode + current_phase · 8 files · 604 tests 零回归 · 议题 ⑧ 启动 🎉
P10-B41  议题 ⑧ Phase 编号自动派生 ✅              ← create_batch() auto-derive phase + batch_number · 1 file · 604 tests 零回归
P10-B42  议题 ⑧ 前端 Phase 编号显示 ✅            ← 组合 "P10-B42" 徽章 + auto-fill · 4 files · 604 tests
P10-B43  议题 ⑧ 收尾 ✅                              ← L5 B41→B43 拉通 · data-model.md §3.5 补齐 · 议题⑧ 闭环 🎉 · 6 files
P10-B44  议题 ⑦ WebPush 后端 ✅                         ← UserPushSubscription 模型 + VAPID + notify_webpush() · 10 files · 604 tests · 议题⑦ 🟡
P10-B45  议题 ⑦ WebPush 前端+API ✅                      ← subscribe/unsubscribe 端点 + Service Worker + usePushNotification hook + auth hook · 8 files · 604 tests · 议题⑦ 闭环 🎉
P10-B46  L5 拉通议题⑦ + P10 post-完成整理 ✅              ← 6 L5发现修复 · architecture.md v2.0 · worker-admin-interaction-flow.md 四通道更新 · P10 全量闭环 🎉
```

### P9 产品轨道（B82→B94 · ✅ 全量闭合 🎉 · 🔄 B95+ 重开）

```
P9-B82 S-015 极简 POC       ← ✅ 7f（FeaturesConfig + /v1/features + conditional UI）
P9-B83 S-015 前端落地        ← ✅ 8f（teams flag + BatchSelect hiding + .env.example）
P9-B84 Dogfooding v9         ← ✅ 实操·1f（F-B84-1 bug fix · PM 全链路验证通过 · 369 tests）
P9-B85 P9 收官               ← ✅ 全文档终版刷新 · Phase 9 闭合 · P10 路线展望
P9-B86 文档微修              ← ✅ 5 项（phase-criteria/data-model/glossary/pitfalls/onboarding）
P9-B87 侧边栏收敛            ← ✅ 7→3 导航项 + 页面整合（Layout/Dashboard/Tasks/CSS/i18n）
P9-B88 P10 路线更新          ← ✅ D-P9-003/004/006 登记（用户基础设施 + 通知通道 + API Docs 迁移）
    ↓
P9-B89 ✅ S-037 断链修复          ← 3处 · S-015 极简模式 gate · Dashboard + Tasks
P9-B90 ✅ S-038 错误契约       ← AGENT→WORKER (9项) + HTTPException→SynapseError (5) + /v1/agents/→/v1/workers/ (5) + ConflictError (2) · 8 files
P9-B91 ✅ S-039 XSS+fetch      ← DOMPurify sanitization + 8处 raw fetch→client · 369 tests
P9-B92 ✅ S-040 i18n 清零      ← 17 处硬编码→t() · 4 组件 · 13 新 key · 5 files
P9-B93 ✅ S-041 UX 可读性      ← 裸ID→名称 · 空看板 · Analyses 展开 · Scan 消息 · 9 files
P9-B94 ✅ S-044 UI 细节        ← verifyNone · placeholder i18n · Docs 骨架屏 · 4 files · P9 最后一批 🎉
    ↓
P9-B95 ✅ 审计登记            ← 三路 Explore Agent · 107 项发现 · S-045~S-058 入库 · 3 files · P9 重开
    ↓
P9-B96 ✅ a11y 阻断修复       ← TaskCard nested controls + form labels htmlFor/id + focus-visible · 7 files · S-045 S-048 ✅
	    ↓
P9-B97 ▶️ S-048 延续 + S-046/S-047/S-058  ← form labels 机械 sweep（Projects/Batches/Teams/Skills/Analyses/Scans）+ 文档漂移修复
```

> P9 产品主线 B1-B94（94 批）全量闭合 🎉 · 🔄 B95+ 重开（产品体验找茬）

### 历史路线（P100-B23→P9-B81）

```
P100-B23 🔴 止血（7 files）    → P100-B24 🛡️ 防呆（8 files）
    ↓                               ↓
补登记 B28-B40 漏掉的            execution-checklist 门禁
pitfalls + lessons +             + CLAUDE.md §15 流程紧急修复
违纪 V-015                      + methodology.md 同步
    ↓                               ↓
    └────────── 完成后 ──────────────┘
                    ↓
              P9-B41 Dogfooding v2 ✅（种子数据刷新 · V-019 实战验证 · P-018 登记）
                    ↓
              P9-B42 Dogfood v3 ✅（纯 curl 认领 flow E2E · P-019~P-022 + LL13 + S-024/S-025）
                    ↓
              P9-B43 修 onboarding.md ✅（S-024 前半段 · 12 处 drift 全量修 · Prep pytest E2E）
                    ↓
              P9-B43 fresh-eyes fix ✅（/cancel 2 处漏修 + /terminate 补 + LL14）
                    ↓
              **P100-B25 三药方止血** ✅（V-020🔴 + V-021 + G-007 · 8 files · commit 549446a）
                    ↓
              **P100-B26 P100-B25 自检修复** ✅（4 bugs: V-020 path + V-021 crash + MEM_DIR + V-021 二次）
                    ↓
              **P100-B27 防呆有效性验证** ✅（9 gate tests · V-020/V-021/G-007 🟢 闭环）
                    ↓
              **P100-B28 CLAUDE.md §13 补明文规则** ✅（D-P9-020 闭环 · 2 files · commit f708de6）
                    ↓
              P100 治理段闭合 · 回 P9 主线
                    ↓
              **P9-B44 S-024 后半段** ✅（doc curl 块 subprocess E2E 机械门禁 · 7 gate tests 全绿）
                    ↓
              **P9-B45 S-025 seed Task 数据层** ✅（_ensure_tasks + B42-B44 · 52 tasks · 369 tests）
                    ↓
              **P9-B46 文档闭环** ✅（五文档同步 + Web UI 验证 · S-025 收尾）
                    ↓
              **P9-B47 S-026 Tasks 历史视图** ✅（双Tab 进行中/历史 · 7 files）
                    ↓
              **P9-B48 P7-006 闭环** ✅（Batch 概念重定义代码层对齐 · commit 92a30a9）
                    ↓
              **P9-B49 P7-002 流程化** ✅（自举同步规范 · 种子数据追平 B48 · 4 files）
                    ↓
              **P9-B50 S-006 TokenLedger** ✅（API+模型 · BigInteger + cost 预埋 · 10 files）
                    ↓
              **P9-B51 自举同步 B49+B50** ✅（seed 脚本 B49/B50 补登记 + 标准文档闭环）
                    ↓
              **P9-B52 S-006 TokenLedger 前端** ✅（WorkerDetail 使用统计面板 · StatCard + CSS 柱状图）
                    ↓
              **P9-B53 S-027/S-028 补刀** ✅（data-model.md §3.11 TokenUsage · requirements-log B46/B47）
                    ↓
              **P9-B54 S-006 TokenLedger 增强** ✅（双页面可见性 + 日粒度时间序列 + cost 启用 · 7 files）
                    ↓
              **P9-B55 P7-004 数据防误删** ✅（is_protected + 7天冷静期 + 硬删除 · 9 files · P7 全量闭环 🎉）
                    ↓
              **P9-B56 S-029 字段补齐** ✅（data-model.md §3.5 +5字段 + deleted 终态 · 1 file）
                    ↓
              **P9-B57 P7-007 分配原子** ✅（Agent.batch_size + Batch.assigned_to + assign 端点 · 8 files）
                    ↓
              **P9-B58 P7-007 前端补齐** ✅（batch_size + assigned worker UI · 4 files）
                    ↓
              **P9-B59 Dogfooding v4 种子刷新** ✅（B51-B58 种子数据 · 1 file）
                    ↓
              **P9-B60 Dogfooding v4 backlog tasks** ✅（+4 tasks · _ensure_tasks ready 状态修复）
                    ↓
              **L5 B58→B60 拉通** ✅（清门禁 · 计数器复位）
                    ↓
              **P9-B61 Dogfooding 实操验证** ✅（claim→submit→verify 全链路通过 · 7 friction）
                    ↓
              **P9-B62 F-B61-1 Human claim 修复** ✅（1 file · 2 行 · S-030 闭环）
                    ↓
              **L5 B61→B62 拉通** ✅（文档闭环 · 叙事一致性 · 计数器复位）
                    ↓
              **P9-B63 API 一致性** ✅（expected_version body 统一 · F-B61-2/F-B61-3 闭环 · 6 files）
                    ↓
              **L5 B62→B63 拉通** ✅（文档闭环 · 叙事一致性 · 计数器复位）
                    ↓
              **P9-B64 B61 friction 三合一清扫** ✅（81 Agent 清理 + Bearer 前缀 + API key 警告 · 6 files）
                    ↓
              **L5 B63→B64 拉通** ✅（计数器复位）
                    ↓
              **P9-B65 Handshake 简化** ✅（agent_version 可选 + capabilities str 简写 · 3 files）
                    ↓
              **L5 B64→B65 拉通** ✅（计数器复位）
                    ↓
              **P9-B66 F-B61-1 service 层补刀** ✅（claim_task/claim_batch actor_type 动态化 · 3 files）
                    ↓
              **L5 B65→B66 拉通** ✅（B61 friction 真正全量闭环 🎉 · 计数器复位）
                    ↓
              **P9-B67 Friction 清扫** ✅（F-B66-N2 API key 警告 + N4 种子数据 B60-B66 追平 · 3+2 files）
                    ↓
              **P9-B68** ✅（Dogfooding v6 PM 视角审计 · 8 friction + 5 missing cap）
                    ↓
              **P9-B69→B72** ✅（blocking friction · 字段文档化 · 项目进度视图 · 批量操作 · B68 Dogfooding v6 全量闭环 🎉）
                    ↓
              **P9-B73→B74** ✅（Worker 负载视图 + deadline 提醒 · S-034 闭环）
                    ↓
              **P9-B75→B76** ✅（Dogfooding v6 总结 + L5 B68→B75 拉通）
                    ↓
              **P9-B77→B78** ✅（Dogfooding v7 PM 审计 + F-v7 P1 friction 修复）
                    ↓
              **P9-B79** ✅（F-v7-04 + M-v7-01 P2 · B77 v7 全量闭环 🎉）
                    ↓
              **P9-B80** ✅（Dogfooding v8 修复验证 · 5/5 全绿 · L5 B78→B80 拉通 · B77 v7 质量闭环 🎉）
                    ↓
              **P100-B31** ✅（系统健康 Sprint · CLAUDE.md 481→400 + backlog 402→298 + 远期项 20→12）
122	                    ↓
123	              **P100-B32** ✅（glossary.md + agent-comparison.md · M-006/M-007 补齐 · P0 清零 🎉）
123	                    ↓
124	              **P100-B33** ✅（产品健康审视 · S-035 + PRD 刷新 + P9-B81→B90 路线校准）
                    ↓
              **P100-B34** ▶️（方向待定：违纪闭环 或 P9-B81 主线恢复）
```

## 跳号记录

| 编号 | 原因 | 日期 |
|------|------|------|
| P100-B13 | P8 遗留技术债重编号为 B15 | 2026-07-06 |
| P9-B94 (原 P9-B95) | S-042/S-043 分流至 P100 治理 backlog（G21/G22），原编号作废 | 2026-07-16 |

## P100 紧急激活说明

**触发条件**：B28-B40 共 13 批 Dogfooding，发现的问题当场修了但零条登记到 pitfalls/lessons/backlog。
违反 §2（发现即待办）、§9（流程共建 — 同一错误 13 次未升级）、§10（讨论即登记）。
属于 §15（流程紧急修复）覆盖场景：持续造成知识资产流失。

**执行计划**：
- P100-B23：补登记 pitfalls + lessons + 违纪 V-019（7 files · ≤8 ✅）✅
- P100-B24：execution-checklist 防呆 + CLAUDE.md §15 新原则 + methodology.md 同步（8 files · ≤8 ✅）✅

**P100 紧急复归完成**（2026-07-09）。next_batch → P9-B41。

**新增原则**（P100-B24 落地）：
> 流程紧急修复不受「per-Phase 渐进消化」约束。满足以下任一条件 → 立即触发 P100 紧急批：
> 1. 同一规则违规 ≥3 次
> 2. 正在持续造成资产损失
> 3. 阻断后续 Phase 正常执行
> 紧急批 = 止血。per-Phase 消化 = 保养。

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
| P100 | P100-B1→B30 (B13 跳号) | 29 | ✅ B30 · ▶️ B31 系统健康 Sprint |
| **P10** | **P10-B1→B46** | **46** | ✅ B1-B46 · 议题 ①-⑧ 全部闭环 🎉 |
| **P9** | **P9-B1→B95** | **95** | 🔄 B1-B94 ✅ · B95+ 产品体验找茬 |

## 编号对照（旧→新）

| 旧格式 | 新格式 |
|--------|--------|
| Phase 2 Batch 1-4 | P2-B1→B4 |
| Phase 3 Batch 5-8 | P3-B1→B4 |
| Phase 4 Batch 7-11 | P4-B1→B5 |
| Phase 5 A1 + Batch 12-19 | P5-A1 + P5-B1→B9 |
| Phase 6 Batch 20-56 | P6-B1→B34 |
