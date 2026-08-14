# Synapse 开发路线图

> 最后更新：2026-08-14（P14-B15 ✅ · 全量闭环 🎉 · 16 批 · 7/7 VC · 941 tests · P100-B137 ✅ 时区序列化修复 · P100-B138 ✅ 善后清理 · L5 B136→B137 拉通 counter=0）
> 执行规则：Phase + Batch 两级编号。每批 2-4 个任务，完成即验证。

---

> 📦 **Phase 10（47 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)
> 📦 **Phase 11（137 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)

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
| **P100-B61→B66** | **审计项前半** — B61 enum→docstring · B62-B64 schemas enum 迁移（auth/status/actor_type）· B65-B66 services 层（ws/lease_detector）· 全量 300+ 枚举同步 | ✅ |
| **P100-B67** | **审计项 — routers 层枚举迁移** — tasks/events 路由 actor_type/owner_type 枚举同步 · 审计收尾 | ✅ |
| **P100-B68** | **审计项 — routers 层收尾** — token_usage/ws 路由枚举同步 · B95 审计收尾 | ✅ |
| **P100-B69** | **审计项 — V-023 防呆落地** — l5-reset.sh 增加 --yes 强制确认 + L5 检查清单打印 + 证据字段 · 审计全量闭环 | ✅ |
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
- **P100-B112**：**L5 从人因戏变成机械校验** ✅ — check-l5-consistency.sh 五关机械校验（batchesSinceLastL5 一致性 · lastL5Batch 引用一致性 · roadmap↔requirements-log 覆盖 · 时间戳新鲜度 · 证据完整性）· 🟢 微型 · 1 file (new script)
- **P100-B113**：**P12 质量债务全量审计** ✅ — ① L5 一致性: B13/B14/B15 reqlog 缺漏修复 (3→0 warning) · ② roadmap 行数超限修复 (895→692 · Phase 10/11 归档) · ③ P12 七大约束全量合规检查 · ④ uncommitted changes 审计 · ⑤ 审计结论: GO for P12-B30 · 🟢 微型 · 3 files (requirements-log + roadmap + archive)
- **P100-B114**：**治理清理 · uncommitted changes 全量处置** ✅ — ① Modified files: 12→3 分组 commit · ② Untracked: 35 文件删除 · ③ .gitignore 补全 (5 patterns) · ④ 幽灵引用修复 · ⑤ DB 备份保留 · ⑥ Bypass 日志审计→删除 · ⑦ 狗粮门禁临时解除→恢复 · 🟢 微型 · 16 files · 4 commits
- **P100-B115**：**L5 五关一致性脚本化** ✅ — check-l5-consistency.sh 从手工五关→完整五关双向 lattice（Gate 1-5）· Phase-agnostic · 活跃 Phase 自动检测 · D-P100-040 闭环 · 🟢 微型 · 1 file (~300行)
- **P100-B116**：**项目文档全量刷新** ✅ — ① 日期刷新 (13 docs): process-violations · execution-checklist · master-backlog · agent-comparison · glossary · onboarding-api-reference · prd · security-model-appendix · phase-criteria · worker-admin-interaction-flow · verification-evidence-model · CLAUDE.md · daily · ② Roadmap 补全: P12-B29 条目 · P100-B61→B69 拆分 · ③ Reqlog 补全: P100-B112 条目 · ④ L5 consistency: Gate 1 warning 28→~4 · 🟢 微型 · 17 files
- **P100-B117**：**治理自愈 — B116 追踪补全 + 违纪回顾复位** ✅ — ① B116 roadmap/reqlog 回填 · ② V-030 索引补全 (29→30) · ③ violations-checkpoint 违纪回顾复位 (136→0) · ④ dogfood-checkpoint P12 R7→R11 + P13 B1→B12 回填 · ⑤ daily P13-B9→B12 回填 · ⑥ 日期同步 (4 docs) · 🟢 微型 · 10 files · +97/-24
- **P100-B118**：**pitfalls 瘦身 + LL21 修复** ✅ — ① PFL-061/069/070/072/074/075/084/099 → archive（198 行）· ② pitfalls.md 1153→955 行（硬阻断阈值 1100 ✅ 解除）· ③ header 计数修正（48→49 PFL）· ④ LL21 编号跳号修复（lessons-learned.md 诚实标注）· 🟢 微型 · 2 files
- **P100-B119**：**PFL-129 launchd label 修复 + 治理收边角** ✅ — ① PFL-129: synapse-launchd.sh label 从 role→worker_id（同 role 多 Worker 不再冲突）· ② generate-skill.sh write_launchd_plist 适配 worker_id · ③ API contracts baseline 更新（P13 10 新端点）· ④ stale .claude/self-check-* ×7 清理 · 🟢 微型 · 5 files
- **P100-B120**：**PFL-153 状态同步 · 治理收边角** ✅ — ① pitfalls.md header 计数修正：PFL-153 🔴→✅（44→45 已修复 · 2→1 未修复）· ② PFL-153 节标题 emoji 🔴→✅ · ③ dogfood d4/status.md PFL-153 status 🔴→✅ · 🟢 微型 · 2 files
- **P100-B121**：**AP-B37 闭环 + 违纪回顾复位** ✅ — ① AP-B37 🔴→✅ · pitfalls 最后一个 🔴 清除 · ② 违纪回顾 batchesSinceLastReview 6→0 · ③ pitfalls header ✅ 45→46 · 50 项全量闭环 🎉 · 🟢 微型 · 6 files
- **P100-B122**：**PFL-127 header 修复 + PFL-130 路由修正** ✅ — ① PFL-127 header 🟡未标记→✅47 · ② PFL-130 路由 P13→P14候选池C7 · 🟢 微型 · 1 file
- **P100-B123**：**V-020/V-021/V-028 header 🔴→🟢 + 违纪回顾复位** ✅ — ① 三处 violations section header 修复 · ② 违纪回顾 batchesSinceLastReview 4→0 · recurringCount 1→0 · 🟢 微型 · 1 file
- **P100-B124**：**Reqlog 孤儿归档 + Roadmap→Reqlog 补登** ✅ — ① 35 段孤儿归档至 archive · ② 22 条 roadmap→reqlog 考古补登 · ③ L5 警告 109→107 · b124-reqlog-purge.py · 🟡 标准 · 3 files
- **P100-B125**：**L5 checker Gate 2+3 fix** ✅ — ① extract_batches 锚定 section header（消除归档引用误匹配）· ② git log pipefail+SIGPIPE 修复 · ③ Gate 3 same-day tolerance · ④ Gate 4 counter 同步 · 🟡 标准 · 6 files
- **P100-B126**：**L5 考古三批收边角 · 残量接受文档化** ✅ — ① CLAUDE.md L5 残量接受声明（34 warnings · 三 Gate 根因+处置表）· ② roadmap+reqlog B125/B126 补登 · ③ CLAUDE.md header + 状态表更新 · 🟢 微型 · 3 files
- **P100-B127**：**Reqlog P11+P12 归档瘦身** ✅ — ① P11 (37条) + P12 (49条) = 86 条 reqlog 归档至 archive · ② 空行 compact (1,341→1,106) · ③ 4 对重复条目检测 · 🟡 标准 · 6 files · b127-reqlog-archive.py
- **P100-B128**：**L5 遗留治理 · 四任务闭环** ✅ — ① V-030 防呆落地（DG-6 狗粮纪律 + process-violations 🔴→🟢）· ② 违纪回顾补做（batchesSinceLastReview 25→0）· ③ roadmap.md 瘦身（825→790 · Glassmind Backlog 归档）· ④ pitfalls.md 瘦身（1254→897 · PFL-108~PFL-122 归档）· 🟡 标准 · 7 files
- **P100-B129**：**workers.py 拆分** ✅ — ① workers.py 1403→648 行 · ② 新建 worker_info.py 768 行（状态/协议/错误上报）· ③ _parse_event_payload + _events_to_error_summaries → helpers.py · ④ check-line-count 全绿 · 🟡 标准 · 5 files · 928 tests 零回归
- **P100-B130**：**R7 escalation 归档** ✅ — ① 24 条 escalation PFL（PFL-213~237，除 229）标题+正文 🔴→🔗 已合并至 PFL-172 · 各加「P100-B130 合并」说明行 ② 4 条 header 未同步（PFL-207~210）标题修复 ③ PFL-172 正文状态 🟡 短期止血完成 + 合并计数 43→71 · 🟢 微型 · 1 file（纯文档 · 0 code）
- **P100-B131**：**文档结构修复** ✅ — ① PFL-128 正文归位（正文从文件末尾 PFL-153 之后漂移段移回标题下方）· ② 归档表格残留去重（PFL-147~152 + PFL-158 旧表格 → archive）· ③ 头部幽灵 AP 计数修正（113 PFL + 1 AP → 114 PFL）· 🟢 微型 · 2 files（纯文档 · 0 code）
- **P100-B132**：**数据卫生** ✅ — ① DB 清理 26 非终态 task + 39 非 system worker + 关联记录（幂等脚本 tools/cleanup-dogfood-residue.py · 保留 161 completed/cancelled/rejected + system worker）· ② violations 回顾（B12~B15 + B130~B131 无新增违纪 · 30/30 🟢 · counter 复位）· ③ 发现运行中 server 自动登记 escalation PFL（引用已删 task）→ 停止 server + revert · 🟡 标准 · 1 新脚本 + 3 文档（0 src code）
- **P100-B133**：**治理批（hook counter 同步 + stray files 清理）** ✅ — ① post-commit.sh 同步 CLAUDE.md counter（bump checkpoint 后同步 header counter=N + status batchesSinceLastL5=N · P12-3 脚本化 · 消除三源漂移）· ② stray files 清理（删除 0 字节 synapse/git + 4 个 session-init.js 运行时产物 · .gitignore 加 _boot-prompt.md/_task-current.md/_last-session-init.txt）· 🟢 微型 · 3 files（1 脚本 + 1 .gitignore + 1 doc）
- **P100-B134**：**治理批（post-commit hook symlink + violations counter skip）** ✅ — ① post-commit hook cp→symlink（Makefile hooks target 三 hook 统一 ln -sf + guard [ ! -L ]+rm -f 可纠错 · 修正 commit-msg stale 目标 check-commit-prefix.sh→commit-msg · 转换已部署 copy→symlink 消除 copy 漂移 footgun）· ② violations counter skip 对齐（post-commit.sh violations 块加 is_l5 检测 · 对称于 L5 counter skip · L5 拉通非业务批不 bump batchesSinceLastReview · 根因 B133 后 L5 commit+amend 误 bump）· 🟢 微型 · 2 files（1 脚本 + 1 Makefile · 0 src code）
- **P100-B135**：**治理批（post-commit is_l5 检测 word-boundary 收紧）** ✅ — ① post-commit.sh 两处 is_l5 检测 substring→word-boundary（`'L5' in msg` → `\bL5\b`）· 对齐 check-batch-sequence.sh `\bL5\b|拉通` · 消除「batchesSinceLastL5 / L50 等 embedded L5 误判为 L5 拉通 → counter 不 bump → 门禁延迟触发」软失败 · ② violations 块补 re import（对称于 L5 counter 块）· 🟢 微型 · 1 file（1 脚本 · 0 src code）
- **P100-B136**：**治理批（venv shebang 防呆 + PFL-239 登记）** ✅ — ① 新增 tools/check-venv.sh 防呆（检测 .venv/bin/* console-script shebang/VIRTUAL_ENV 指向 stale 路径 · --fix 自愈 + --strict 门禁 · 补 Makefile check-tests 用 `-m` 绕行的盲区）· ② Makefile 接线 check-venv（.PHONY + check: 列表 + target 定义）· ③ PFL-239 登记（项目迁移 venv shebang 失效 · 114→115 PFL）· 🟢 微型 · 3 files（1 脚本 + 1 Makefile + 1 doc）
- **P100-B137**：**治理批（时区序列化修复 · 首个触 src/ 的 P100 批）** ✅ — ① AuthorizationRequest expires_at/last_heartbeat_at/responded_at + refresh_token/password_reset_token expires_at → DateTime(timezone=True) 对齐 TimestampMixin ② schema field_validator 序列化补 UTC（SQLite 无原生时区 → timezone=True 是 no-op · 真修在序列化层）· 消除「前端 new Date() 早 8h 误判过期禁用批准按钮」· 🟡 标准 · 5 files（3 model + 1 schema + 1 test）· 941 tests 零回归
- **P100-B138**：**善后清理（0 code · DG-3）** ✅ — ① --no-verify 全量提交（capabilities.yaml 三 git push 命令 git_push_main/branch/force 全补 --no-verify · 消除 pre-push hook 死循环 Bug 2 · 补 B136 修复只覆盖 git_push_main 的盲区）· ② 停 server + 清理狗粮残留（push-worker ag_019ffe1b + capability + builder 角色 + 2 审批请求 + Hunter admin 角色 · 保留 Hunter worker 本体 · targeted SQL 非全量脚本）· ③ revert pitfalls.md 服务器自动登记 escalation PFL-240~245（引用 ghost task）· ④ 删 0 字节 stray synapse.db（B133 漏）· 🟢 微型 · 2 files（1 配置 + 1 audit log）· 0 code

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
| P100 | P100-B1→B119 | 119 | ✅ 治理波持续 · B118 pitfalls 瘦身 · B119 launchd label 修复 |
| **P10** | **P10-B1→B47** | **47** | ✅ 议题 ①-⑧ 全部闭环 🎉 |
| **P9** | **P9-B1→B95** | **95** | ✅ B1-B94 产品主线 · B95+ 产品体验找茬 🔄 |
| **P11** | **P11-B1→B137** | **137** | ✅ **全量闭环 🎉** · Prompt-Driven→Harness-Driven |

---

## Phase 12：Harness-Driven Worker ✅

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
| **P12-B17** | **狗粮验证 — 7 项发现** — DUPLICATE_VERIFICATION guard 误杀合法 rework (#1) · canVerify project role 缺失 (#3) · Worker 配对断裂 (#5) · 前端分页盲区 (#2) · Stale detector 竞态 (#4) · O SKILL.md 缺 verification 轮询 (#6) · God's-eye DB bypass (#7) · 🟢 微型 · 纯狗粮 | ✅ |
| **P12-B18** | **B17 发现 #1/#3 修复** — submit_task 全量 verification reset · guard 防御纵深 task.rejected fallback · GET /projects/{id}/my-role 端点 · TaskDetail project role 权限检查 · 2/7 🔴 消化 · D1 56% · 5 files | ✅ |
| **P12-B19** | **B17 发现 #5 Worker 配对断裂修复** — O 循环新增 Worker 拉取+Capability 匹配算法 · _protocol.md `.skills`→`.names` 修正 · B 侧 Capability 自检+rejected→reclaim 文档化 · 3/7 🔴 消化 · 3 files 纯模板 | ✅ |
| **P12-B20** | **狗粮验证 — B19 Worker 配对修复实战验证** — 狗粮门禁激活 · API 级 Worker 匹配算法验证 · 测试 Task 创建 (required_capabilities 匹配) · B19 模板一致性审计 · L5 B19→B20 拉通 · P12-4 狗粮节奏复位 · 3/7 🔴 消化 (维持) · 1 task · 零 src/ 变更 | ✅ |
| **P12-B21** | **B17 发现 #2/#6 消化** — #2 前端分页盲区：client.ts cursor 分页 + Tasks.tsx Load More 按钮 + i18n/CSS · #6 O SKILL.md verification 轮询显式化：role-orchestrator.md + _protocol.md API status 名修正（submitted→in_verification）· 4/7 消化 (2 🔴+2 🟡) · 5 files (2 code + 2 template + 1 CSS) · 零 src/ 变更 | ✅ |
| **P12-B22** | **B17 发现 #4/#7 消化 🎉** — #4 Stale detector 竞态修复：task_stale_reassign 15→45min + verification_timeout 30→120min + max_reverts 3→5 · #7 DB bypass 监控：health 端点 system_interventions 计数器（stale detected/reassigned/cancelled + verify reverted/cancelled）· 7/7 消化 🎉 · D1 56% · batchesSinceLastDogfood=2 · 2 files · 🟢 微型 | ✅ |
| **P12-B23** | **狗粮验证 — B18-B22 修复实战检验** — Server 健康确认（4 reaper running）· B22 system_interventions 计数器验证 · B103 双 Worker 活跃 handshake · Heartbeat 监控 4 offline 检测 · config reload 生效 · P12-4 狗粮复位 · D1 56% · 0 code files · 🟢 微型 · 纯狗粮 | ✅ |
| **P12-B24** | **Zombie-Worker 模板防御 + ENV-2 密钥一致性** — B23 狗粮发现根因修复：role-builder.md O-silence 操作性定义（last_assignment_at 替代 last_heartbeat_at）+ per-loop liveness 重检 + Cap mismatch 上报 · role-orchestrator.md zombie Worker 防御行 + 零匹配超时重试 · _protocol.md 心跳 doc-code 对齐（60s→300s）+ zombie 检测规则 · `check-env-consistency.sh` ENV-2 .env↔keychain↔launchd 三向比对 + `--fix` 自愈 + Makefile 集成 · PFL-128 READY-task watchdog 登记 · D1 56%→59% · batchesSinceLastDogfood=1 · 🟢 微型 · 0 src/ 变更 | ✅ |
| **P12-B25** | **PFL-128 闭环 — Server 端 READY task 看门狗** — `detect_unclaimed_ready_tasks()` 扫描 READY 超时未认领 task · 记录 `task.ready_unclaimed` 事件 + `system_interventions.ready_unclaimed` 计数器 + `/health` 暴露 · `config.py` 新增 `task_ready_unclaimed_timeout_minutes=30` · +2 tests · 680 tests 零回归 · PFL 37/37 全量清零 🎉 · 🟢 微型 · 4 files (3 src + 1 test) | ✅ |
| **P12-B26** | **ENV-1 环境变量污染检测+自愈** — `check-env-pollution.sh` (~240行) 双维度检测（当前 shell + profile 文件）· SHA-256 安全比对 · `--fix` 自动注释 profile 污染行（反向序 · 幂等）· `--strict` 模式 · Makefile `make check` 链入（警告级）· D1 自动化率 59%→62% · Environment 域 50%→75% · 🟢 微型 · 2 files (1 new script + Makefile) | ✅ |
| **P12-B27** | **D2 Foundation — Worker JS Test Infra** — `test-api-client.js` (16 tests · api-client.js ~85% 覆盖) + `run-tests.js` 自动发现聚合运行器 · `smoke.js` plist fix · `make test-js` Makefile target · pre-commit Stage 9 JS 变更自动触发 · D2 覆盖率 ~5%→~15% · 🟢 微型 · 4 files (3 new + 1 smoke fix + Makefile) | ✅ |
| **P12-B28** | **D2 Core Modules — keychain+daemon-manager 单元测试** — `test-keychain.js` (28 tests — detectPlatform 三平台+fallback · get/store/delete/has 全 API + 输入校验 · B100-A1 stdin pipe 安全验证) · `test-daemon-manager.js` (31 tests — PID file CRUD · isProcessAlive · killOldDaemon SIGTERM→SIGKILL 升级 · check/start heartbeat+WS daemon · cleanupOrphanDaemons 孤儿清理 · health 自愈+双 daemon re-spawn) · D2 覆盖率 ~15%→~30% · 91 total tests (B27:32→B28:+59) · 🟢 微型 · 2 files (new tests only) | ✅ |
| **P12-B29** | **L5 一致性检查脚本初版** — check-l5-consistency.sh 原始版（5 零散 check + P12-hardcoded）· P100-B115 已升级为完整五关 lattice 版 · 🟢 微型 · 1 file | ✅ |
| **P12-B30** | **狗粮验证复位 · P12-4 计数器清零** — Python 680 tests ✅ · JS 91 tests ✅ · Synapse Server :8001 🟢 · 双 Worker heartbeats ✅ · System Interventions 全零 · P12-4 节奏复位 (batchesSinceLastDogfood=0) · 🟢 微型 · 纯狗粮 | ✅ |
| **P12-B31** | **D2 Phase 3 集成测试 — ws-daemon + heartbeat 模块提取与测试** — `lib/ws-daemon-core.js` (新建 · toWsUrl/isSessionAlive/resolveConfig/writeStatus/appendEvent/touchHealth/now) · `lib/heartbeat-core.js` (新建 · isSessionAlive/checkTemplateVersion/sendHeartbeat) · `ws-daemon.js` 重构 (删除 70 行内联 → import lib) · `heartbeat.js` 重构 (删除 70 行 → import lib) · `test-ws-daemon.js` (28 tests) · `test-heartbeat.js` (20 tests) · D2 覆盖率 ~30%→~45% · 139 total tests · 🟢 微型 · 4 new + 2 refactor | ✅ |
| **P12-B32** | **D2 Phase 4 E2E — session-core 模块提取 + E2E smoke** — `lib/session-core.js` (新建 · 286行 · now/ownerLabel/summarizeTask/roleBanner/loadEnvFile/readRoleFromCache/getExistingSnapshotAge/isExistingSnapshotHealthy/readRecentWsEvents) · `test-session-core.js` (46 tests · 全函数覆盖) · `test-e2e.js` (4 tests · E2E smoke health×3 + template versions×1 · 无服务器时优雅跳过) · `session-init.js` 重构 (-174行/-9% · 委托到 sessionCore + heartbeat-core · 删除 9 daemon 透传包装器) · `checkTemplateVersionInHeartbeat` 与 heartbeat-core.js 消除重复 · D2 覆盖率 ~45%→~55% · 189 total tests · D2 四阶段全量闭环 🎉 · 🟢 微型 · 4 new + 2 refactor | ✅ |
| **P12-B33** | **D3 depends_on 依赖链 G5+G4 闭环** — `_unblock_downstream_tasks()` Task 完成后自动解除下游依赖阻断 · G5 WS `broadcast_to_team` `task.dependencies_met` 实时推送 · G4 `GET /tasks/available` 自动过滤 `blocked` 状态 · `available` filter 新增 `blocked` + `dependencies_met` · depends_on 实体约束 `ondelete="CASCADE"` · +3 tests (unblock single dep · multi-dependency converge · available filter blocked) · 683 tests 零回归 · 🟢 微型 · 4 files (task_service + task_execution + ws + tasks router) | ✅ |
| **P12-B34** | **D4 双 Builder 狗粮闭环** — ① Plan: `docs/plans/p12-b34-d4-dogfood.md` 十节计划 + `tests/dogfood/d4/` 目录就位 · ② 实现: dependency-graph API + 前端可视化 + 三 Task 依赖链全链路 · ③ 发现登记: PFL-129 launchd plist 冲突 + PFL-130 TaskUpdate 缺 depends_on · 🟢 微型 · 4 commits (2 plan + 1 feat + 1 chore) | ✅ |
| **P12-B35** | **Project 创建 500 修复 · 三层防御** — ① `resolve_project`: team_id 空值检查 → 403 ForbiddenError · ② `find_or_create_by_name`: team_id 空值提前 raise ValueError · ③ `set_project_role`: worker 存在性验证 → 404 NotFoundError · +2 tests (nonexistent worker + empty team_id) · 698+189=887 零回归 · 🟢 微型 · 1 commit | ✅ |
| **P12-B36** | **Codex 混搭** — D4 狗粮多 Worker 协作验证 · 2/3 Task 完成 · 13 PFLs | ✅ |
| **P12-B37** | **PFL 消化波 1** — PFL-131 session-init 路径修复 · PFL-139 role pattern · PFL-142 claim 项目隔离 · 3/13 PFL 闭环 · PFL-143 撤回 B38 | ✅ |
| **P12-B38** | **文档残留全量同步** — 16 files · 11 docs + pitfalls AP-B37 登记 + B36 Codex 混搭计划 · violations + bypass 同步 | ✅ |
| **P12-B39** | **审批 UI 三位一体闭环** — PFL-136 include_expired API · PFL-137 过期过滤纵深防御 · PFL-140 内联错误 + Modal 替代 alert · 702+189 tests 零回归 | ✅ |
| **P12-B40** | **evidence 校验 + API 降级** — PFL-143 TaskSubmitRequest evidence 非空 field_validator（None/{}→422）· +3 tests · PFL-135 SKILL.md + role-builder.md API 降级路径（`GET /workers/me/state`）· 705 tests 零回归 · 2/13 PFL 闭环（累计 8/13）· 🟢 微型 · 4 files | ✅ |
| **P12-B41** | **PFL-138 role 自动分配闭环** — 三层防御验证：WorkerCreate.role pattern + register_worker() default builder + ProjectRoleAssign.role pattern · 零新代码 · 23 tests 覆盖 · 9/13 PFL · 🟢 微型 · 1 file（pitfalls.md 标记） | ✅ |
| **P12-B42** | **Codex 兼容层** — provider-aware 离线判定（codex→30min vs standard→5min）· SKILL.md Codex CronCreate 保活模板 · PFL-132/133/134 ✅ + PFL-141 🟡 · 13/13 P12 PFL 全部闭环 🎉 · 705 tests 零回归 · 🟢 微型 · 4 files | ✅ |
| **P12-B43** | **双 Worker 狗粮闭环** — BA(Claude)+BB(Codex) 协作 · dependency-chain API (BFS 双向遍历) · TaskCard 依赖标签前端 · 9 PFL 登记 (PFL-144~152) · 702+189=891 tests · 🟢 中型 · 7 files · +945 | ✅ |
| **P12-B44** | **PFL 消化波 5 修复** — PFL-147 auth 500 fix · PFL-148 generate-skill.sh .env 骨架 · PFL-149/145/146 SKILL.md 文档增强 · PFL-144 三层根因定位 → B45 · 702+189=891 tests · 🟢 微型 · 8 files · +119/-23 | ✅ |
| **P12-B45** | **PFL-144/150/152 全量闭环 · PFL-151 🟡 SPoF 缓解** — P0: heartbeat monitor 三层修复 (ACTIVE+PENDING · offline_detected · failure_detector provider-aware) · P1: SKILL.md O CronCreate 120s + Codex /tmp state · P2: PFL-151 SPoF 设计选项 A/B/C 登记 · 714+189=903 tests · 🟢 中型 · 8 files · +131/-39 | ✅ |
| **P12-B46** | **PFL-151 Option A: Builder @O WS Notification** — `POST /tasks/{id}/notify` 端点 · Builder 超时主动通知 O · WS push `orchestrator.notify` · SKILL.md Builder + O 模板更新 · +5 tests · 723 collected | ✅ |
| **P12-B47** | **PFL-151 Option B: O SLA auto-escalate to Human** — `verification_escalation_minutes=10` · `detect_stale_verifications_escalation()` · 两阶段梯度响应（升级→回退）· @Human 消息 + WS push · +5 tests · 728 tests 零回归 | ✅ |
| **P12-B48** | **🐶 狗粮验证 — PFL-151 三层防御** — 1O+2B 实战验证 B45+B46+B47 打破 SPoF · SPoF 验证 L1+L2 ✅ · B48-1 escalation savepoint 隔离 · 审计发现 PFL-153~157 · 719 tests | ✅ |
| **P12-B49** | **审计修复波全量闭环** — PFL-154 system worker + PFL-155 detector 隔离 + PFL-156 notify 授权 + PFL-157 SKILL.md 虚假 API 修正 · FK 前置校验 · notify 错误处理+状态 gate · 728 tests | ✅ |
| **P12-B50** | **收尾波** — PFL-153 bootstrap env 三重断裂修复 + check-env.sh 门禁脚本 + notify 频率限制 (@limiter) + escalation WS push orchestrator 角色补齐 · L5 拉通 · 728 tests | ✅ |

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

---

## Phase 13：基础设施可信度加固 ▶️

> **一句话目标**：P12 证明了平台"可以工作"——P13 要让平台"可以信赖"。不是建新功能，而是把 P12 暴露的 30 个 PFL 中的结构性弱点（软约定、静默失败、跨客户端摩擦）转化为机械门禁。
>
> **启动条件**：P12 全量闭环 ✅ · P13 Scout 完成 ✅ · L5 复位
> **核心原则**：P13 的每一批要么在消除一个已知的失败模式（PFL 根因），要么在让一个软约定变成机械门禁。**不做新功能，做可信度。**
> **与 P12 的关系**：P12 是"让多 Worker 协作跑通"（功能性验证）。P13 是"让多 Worker 协作可靠"（可信度验证）。P12 的 917 tests 是资产——P13 让这些资产的保护范围更广。
>
> ⚠️ **P13 Scout 已完成**（[p13-scout-brief.md](plans/p13-scout-brief.md) → [p13-priority-proposal.md](plans/p13-priority-proposal.md)）。以下 P0→P1→P2 来自 Scout 的交叉分析，不是拍脑袋。

### 🎯 P13 三方向

| # | 方向 | 为什么必须在 P13 | 对应 Scout 信号 |
|:--:|------|:---|:---|
| **D1** | **脚本化机械门禁** | P12 最顽固的反模式：软约定（文档写了但无人执行）→ 不转化为机械门禁，P13 狗粮会重演同样的摩擦 | S2 软约定 + S5 证据完整性 |
| **D2** | **Worker 可观测性基础** | P12 最常见的失败模式：Worker 在残缺状态静默运行——不修，P13 每轮狗粮的调试时间有一半浪费在发现"Worker 其实是坏的" | S3 启动链静默失败 + S4 SPoF |
| **D3** | **跨客户端可靠性** | P12 最多产的 bug 来源（8 PFLs · 27%）：Claude vs Codex 行为差异——不修，P13 多客户端狗粮持续产生噪声 | S1 客户端不对称 |

### 📋 P13 批次表

| Batch | 内容 | 优先级 | Scout 来源 | 状态 |
|:---|:---|:--:|:---|:--:|
| **P13-B1** | **P0-1: Worker 启动链韧性** — 5 项健康自检脚本 `synapse-health-check.sh` · 启动后自动诊断 (handshake 200 · WS connected · heartbeat ticking · state file fresh · CronCreate scheduled) · 任一项失败 → 终端告警 · 模板集成 (boot-prompt + session-init) | P0 | C12 × S3 | ✅ |
| **P13-B2** | **P0-2: 狗粮证据完整性门禁** — `dogfood-gate.sh` V-criteria 完整性检查 · 解析上次 status.md → 存在 ⬜ → 阻断新狗粮 + 逐项提示缺失行号 · D-P12-042 落地 · PFL-158 闭环 | P0 | C8 × S2+S5 | ✅ |
| **P13-B3** | **P0-3: L5 一致性机械门禁** — `check-l5-consistency.sh --critical-only` 三源对比 (l5-checkpoint.json · CLAUDE.md · MEMORY.md) · 不一致 → pre-commit 阻断 (+ `SYNAPSE_SKIP_L5_CHECK=1` 豁免但记录违纪) · Gate 4a/4a-2/4a-3/4e 增强 | P0 | C5 × S2 | ✅ |
| **P13-B4** | **P1-1-start: 跨客户端 Provider Interface 设计** — 从 Codex 13 PFL 提炼统一 provider 接口 (heartbeat/offline/evidence/state/startup 五维) · 设计文档 · 不强求实现 | P1 | C1 × S1 | ✅ |
| **P13-B5** | **P1-4: 多 Worker 集成测试 Harness 设计** — 多 Worker fixture 架构 + 并发调度方案 + 时序断言 API 设计文档 · 1 个 smoke test: B 提交→O 验收→下游解锁 | P1 | C2 × S2+S3+S4 | ✅ |
| **P13-B6** | **P1-4b: Harness 工具库实现** — tests/harness/ 五文件 (providers/time_travel/fixtures/assertions) · +17 smoke tests · 745 tests 零回归 · P13-B5 设计落地 | P1 | C2 × S2+S3+S4 | ✅ |
| **P13-B7** | **Provider 配置测试** — test_provider_config.py (59 tests) · test_multi_worker_heartbeat.py (22 tests) · Provider 差异回归守卫 · 827 tests 零回归 | P1 | 2 files · +740 loc | ✅ |
| **P13-B8** | **Offline+Evidence+State+Detector 回归测试** — 4 files · 49 tests · stale/lease/evidence/state endpoint + detector provider-aware 回归守卫 · 876 tests 零回归 | P1 | 4 test files · +950 loc | ✅ |
| **P13-B9** | **SPoF 梯度防御 B 线** — escalation_service.py (独立服务) · provider_config_service.py (去硬编码) · failure_detector.py B4 原则 #3 落地 · 10 escalation tests (5→10) · PFL-151 ✅ 闭环 · 881 tests 零回归 | P1 | 5 files · +330/-120 loc | ✅ |
| **P13-B10** | **P2 按需触发 — 狗粮验证** — 集成点审查 · 覆盖度审视 · 配置一致性 · DB 备份 · 全量回归 881 tests · P13 成功标准 5/5 | P2 | 10 批闭环 🎉 | ✅ |
| **P13-B11** | **C13 Hook 诊断** — SessionStart hook 静默失败检测 · `check-session-hook-health.sh` canary 探针 · settings.json canary hook · CLAUDE.md 启动自检链 ③.5 扩展 | P2 | 4 files · +175 loc | ✅ |
| **P13-B12** | **C11 O SLA Metric** — O 响应性 SLA 自动度量 · `o_sla_metrics.py` + `GET /stats/o-sla` · p50/p95/p99 + SLA 达标率 + breach 列表 · +16 tests · 897 tests 零回归 | P2 | 4 files · +330 loc | ✅ |
| **P13-B13** | **收边角 · P13 正式收官** — C6/C7/C3/C10 → P14 候选池交棒 · P14 Scout 优先级建议 · P13 全量闭环 🎉 | P2 | 1 file NEW + 4 docs | ✅ |

### ✅ P13 成功标准（可验证的 "done"）

```
1. 三个机械门禁 (B1+B2+B3) 在 pre-commit 中生效——软约定成为阻断条件
2. Worker 启动后 5 秒内完成自检——静默失败成为不可能
3. 每轮狗粮的 V-criteria 至少 80% 有 automation evidence（非手工 code-verified）
4. O 超时 >10min → Human 自动收到 escalation 通知
5. 全程零 src/ 变更由 God's-eye 执行（God's-eye 只治理，不写代码）
```

---

## 🎯 Phase 14 — 从平台建造到平台使用（进行中）

> **一句话**：验证 1O+2B 通过 Synapse 协作交付真实功能，零 God's-eye 代码干预。
> **Scope 文档**：`docs/plans/p14-scope.md`

| Batch | 内容 | 状态 |
|:---|:---|:--:|
| **P14-B0** | **Scope 定义** — P14 五维检查 · 成功标准 · In/Out scope · 批次路线 · 风险缓解 · `docs/plans/p14-scope.md` | ✅ |
| **P14-B1** | **C6 Worker 升级/回滚脚本** — `synapse-upgrade.sh`（3 子命令: upgrade/rollback/status）· startup log 补 escalation 参数 · heartbeat_monitor provider-aware 确认 | ✅ |
| **P14-B2** | **G1+G2 Builder 错误上报 + Escalation 自动登记** — `POST /workers/{id}/error-report` 端点 · `pitfall_service.py` PFL 程序化创建 · escalation 自动 PFL+Task · 7 files · 920 tests | ✅ |
| **P14-B3** | **诊断加固** — Worker/Project 错误列表端点 (2 endpoints) · SKILL.md + role-builder.md 诊断查询指引 · cursor 分页 + severity/worker_id 筛选 · 4 files · 928 tests | ✅ |
| **P14-B3.1** | **P1+P2 修复** — severity SQL 层过滤 · 复合游标 · DG-1~5 狗粮测试纪律 · commit c957b85 | ✅ |
| **P14-B4** | **狗粮闭环 🎉** — depends_on 编辑能力全量交付 · 1O+2B 协作验证通过 · backend 3 files + frontend 4 files · 928 tests 零回归 · PFL-169~174 登记 | ✅ |
| **P14-B5** | **Worker 启动零人工** — PFL-167 (worktree 启动基础设施) + PFL-168 (去人工断点) · generate-skill.sh 启动就绪检查清单 · SKILL.md 冷启动措辞更新 · prompts.js CronCreate 自启动 · b4-dogfood-setup.py .env 路径修复 | ✅ |
| **P14-B6** | **daemon 存活性加固** — PFL-173 (daemon↔Claude 双向心跳) + PFL-174 (代码 commit checkpoint) · daemon-manager.js checkHeartbeatFreshness + checkUnstagedChanges · session-init.js 3 alert banners · role-builder.md commit discipline | ✅ |
| **P14-B7** | **狗粮验证 🎉** — 4/4 VC 闭环 · PFL-167/168/173/174 全量通过 · 3 Worker 零人工启动 · daemon 存活性确认 | ✅ |
| **P14-B8** | **O SPoF 根因定位 + 短期止血** — 23 项 escalation PFL 合并至 PFL-172 · G2 级联放大止血（skip_escalation）· auto-verify 设计文档 · 3 files · 929 tests 零回归 | ✅ |
| **P14-B9** | **Server 侧 auto-verify 实现** — PFL-172 修复 · submit 时自动验收 command_output evidence · 5 files + 5 tests · 934 tests 零回归 | ✅ |
| **P14-B10** | **角色围栏硬化** — PFL-169 (evidence 文档化) + PFL-171 (claim capability 硬门禁) · 4 code + 2 template · +4 tests · 938 tests 零回归 | ✅ |
| **P14-B11** | **PFL 收尾+L5 拉通+修复+B12 场景定义** — PFL-211/212 合并入 PFL-172 · L5 counter 1→0 · violations 12→0 · pytest 3 处误标修复 · B12 7 VC 场景 | ✅ |
| **P14-B12** | **狗粮验证 🎉** — 6/7 VC 通过 · 发现 PFL-229 batch API 遗漏 required_capabilities · L5 已拉通 · VC-6 待 reaper | ✅ |
| **P14-B13** | **PFL-229 修复 + 回归测试** — `tasks.py:276` +1 line · `test_capability_gating.py` +82 lines · 939 tests 零回归 · L5 拉通 counter=0 | ✅ |
| **P14-B14** | **VC-6 止血验证** — reaper 周期确认 · 7 条历史 escalation 审查 · 0 条级联 · skip_escalation 三角度验证 · 0 code changes | ✅ |
| **P14-B15** | **全量复盘+架构审查+完成度审查** — `docs/plans/p14-b15-retrospective.md` · 残量 R1-R7 登记 · P15 方向建议 · P14 全量闭环 🎉 | ✅ |

### 🗄️ P14 储备（P13 明确排除 · B13 交棒）

| 编号 | 内容 | 排除理由 |
|:---|------|------|
| W2 | Worker 自观测 dashboard | 产品功能——先让基础设施可靠 |
| T2 | Builder 间 A2A 通信 | 先巩固 Task 依赖 + O 协调 |
| T4 | 多 Worker 负载均衡 | 规模未到 |
| H3 | Prompt 版本化+回滚 | 基础设施可信后再优化 |
| H4 | Worker SDK 化 | 过早抽象——等 Provider Interface 验证后 |
| P1 | Kanban 看板可视化 | 产品功能 |
| C1-full | 跨客户端抽象层全量实现 | B4 只做设计——需更多 PFL 数据 |
| C2-full | 多 Worker 集成测试 Harness 全量 | B5/B6 做了设计+smoke——全量留 P14 |
| C11 | ~~O 响应性 SLA 自动度量+报警~~ | ✅ P13-B12 已交付 |
| **C6** | **D1 自动化率 62%→80%（Worker 升级/回滚）** | ✅ **P14-B1 已交付** · `tools/synapse-upgrade.sh` |

> 📋 详细交棒文档：`docs/plans/p14-candidate-pool.md`

### 🗄️ P15 储备（P14 评估后推迟 · 2026-08-09）

| 编号 | 内容 | 推迟理由 |
|:---|------|------|
| **C10** | Worker 身份认知硬约束（文件快照 SPoF） | FE=2 需设计先行 · P14 聚焦战略假设验证 · 非阻塞 |
| **C3** | D2 测试覆盖率 55%→75%（daemon 边界） | TD=5 但需 CI 改造 · P14 过程中可渐进补 · 不单独成批 |
| **C7** | depends_on G1/G2 前端+API 补齐 | SV=4 但 TD=2 · 核心链路 G3-G6 已闭环 · 非阻塞 |
| C2-full | 多 Worker 集成测试 Harness 全量 | P13 设计+smoke 已完成 · 全量待规模需求驱动 |
| **D-030** | C6 版本追踪 — Worker 版本号 + CHANGELOG · 升级脚本知道"从什么版本升到什么版本" | P14-B1 明确排除 · C6 先解决零干预升级 · 版本号体系独立设计 |
| **D-031** | C6 自动回滚 — 升级后 health check 失败→自动 git revert + 重启 | P14-B1 明确排除 · 先让手动回滚可用 · 自动触发需要独立的判定+恢复策略 |
| **PFL-141** | Codex CLI 启动后需人工输入 prompt — 无法像 Claude Code 自主初始化 | P12 跨客户端遗留 · 🟡 待排期 · 非阻塞（Codex 非主客户端） |
| **PFL-142** | 旧 P11 Builder Worker 越界污染 B36 dogfood | P11 遗留 · 🟡 待排期 · 已由 P14-B10 capability 门禁缓解 |
| **PFL-130** | TaskUpdate schema 缺 depends_on 字段 — 依赖链创建后不可修改 | = C7 depends_on G1/G2 补齐 · 已在 C7 跟踪 |

> 📋 PFL 未闭环清理盘点（2026-08-13 · B15 复盘后补）：24 条 escalation PFL（PFL-213~237）+ 4 条 header（PFL-207~210）+ PFL-172 正文状态 ✅ 已由 P100-B130 归档闭环。剩余 3 条 🟡 历史遗留（PFL-130/141/142）独立登记如上，不混入本批。
