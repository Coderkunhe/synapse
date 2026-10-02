# Synapse 开发路线图

> 最后更新：2026-10-02（**P17-B12 PFL-274 B1 查询层落地 ✅**（mention 关联表落 worker_id + 未读查询 + GET /workers/me/mentions · 6 src + 1 migration · +10 tests · 1040 tests 零回归）· **P100-B179 PFL-275 e2e 残留清理 ✅**（afterAll 补全 + bearer 鉴权 · 0 src code · e2e 7/7 绿）· **P17-B11 会话生命周期 dogfood ✅**（真人 @mention → agent 真回 → resolve 闭环 · 6/6 🟢 · 暴露 PFL-274 mention 实时投递 vs worker 轮询消费脱节 · 0 src code）· **P100-B178 PFL-273 e2e 基建修复 ✅**（429 提限 + WS 多连接根治 · 2 src + 7 tests · 1030 tests · e2e 7/7 绿）· **P17-B10 协作消息面板 reply/threading 收口 ✅**（后端 in_reply_to_id 早已就绪 · 前端回复按钮/banner/缩进 · 0 src 后端 · 4 frontend + e2e · 1023 tests 基线不变 · e2e 4/4 新增用例绿 · 全量套件 situation-view 撞 slowapi 限流 429 + WS 时序 flaky → 挂 PFL-273）· **P17-B9 协作消息面板 resolve 收口 + e2e 验证 ✅**（0 src 后端 · 4 frontend + e2e · 1023 tests 基线不变 · e2e 6/6 绿）· **P17-B8 人侧反馈最小闭环 ✅**（S-020 反馈协议 v2 · TaskDetail 协作消息面板 + mention 投递 · 2 src 后端 + 4 frontend + 2 tests · 1023 tests）· **P100-B176 PFL-269 coerce + PFL-272 事件流修复 ✅**（event_to_response coerce + /tasks/{id}/events 端点 · 2 src + 2 frontend + 4 tests · 1021 tests）· **P17-B7 DependencyGraph N+1 修复 ✅**（复用 /dependency-graph + 本地 BFS · 0 src 后端 · 2 frontend + e2e · E2E 3/3 绿 · 1017 tests 基线不变）· **P100-B174 Playwright E2E 基建 ✅**（devDependency + config + 双服务 webServer + 态势 #2/#3 实时断言 · 0 src 后端 · 2 frontend src + e2e）· **P17-B6 项目「态势」视图 WS 实时化 ✅**（DAG 实时 + 事件流 prepend · 0 src 后端 · 2 frontend · 1017 tests 基线不变）· **P17-B5 项目「态势」视图 ✅**（人侧上下文卸载最小版 · 0 src 后端 · 7 frontend · 1017 tests 基线不变）· **P100-B173 清陈旧提示 ✅**（删 synapse_token/synapse_team_id setItem 死文案 · 5 frontend · 1017 tests 基线不变）· **P100-B172 失败退登录（WS onclose 4001 → logout）✅**（ws.ts onclose 4001 判定 + Layout/Approvals 接 logout · 3 frontend · 1017 tests 基线不变）· **P100-B171 WS 鉴权迁 cookie 根修 ✅**（后端 cookie 回退 + 前端去 ?token= · 1 src + 1 frontend + 1 test · 1017 tests）· **P100-B170 check-batch-numbers full-scan 对齐 staged 模式 ✅**（正则统一 + SCAN_FILES 扩 · 0 src code）· **P100-B169 P17 资产切分 + PFL-241/242 封存 + check-batch-numbers 防呆补漏 ✅**（0 src code）· **P100-B168 report_execution InvalidStateTransition 传参修复 ✅**（entity_type/entity_id 缺参 → 正确定位 · 1 src + 1 test · 1014 tests）· **P100-B167 授权列表过期修复 ✅**（前端删 isExpired 残留 + 后端 respond 过期硬门禁 · 1 src + 1 frontend + 1 test · 1013 tests）· **P17-B3 人认领/读规范/同步最小闭环 ✅**（修 owner_type 混用 · 1 src + 1 test · 1012 tests）· **P17-B2 还 PFL-245 ✅**（lease 对 human owner 免死 · 2 src + 2 test · 1010 tests）· **P17-B1 战略定性（锚）🔄** — agent 能力层告一段落 · 主攻人机协作协调层 · **P100-B166 reqlog 旧 Phase 归档 ✅**（0 src code · 主 reqlog 5176→1673 行）· **P100-B165 Shared Module Governance 补课 ✅**（S-005 假闭环 · RA 全覆盖 77/77）· **P100-B164 PFL-268 能力声明动态化 ✅**（env 声明 + 409 自愈 · 0 src code）· **P100-B163 善后清理 + PFL-268 + B162 复盘 ✅**（DG-3 · 0 src code）· **P100-B162 跑狗粮 Phase 2 ✅**（自主 ✅ · 主判据 1-5 全达标）· **P100-B161 setup 脚本 dry-run 自检 ✅**（0 src code · --dry-run + ROLLBACK 无副作用）· **P100-B160 自主性重验证计划+环境 ✅**（0 src code · plan + setup 脚本）· **P100-B159 human admin 预置 ✅**（PFL-263 层3 · DG 脚本 · 0 src）· **P100-B158 心跳/进度硬故障释放定性收口 ✅**（PFL-267 manual-only by design · 0 src code）· **P100-B157 租约释放死代码根治 ✅**（PFL-267 · guard + clear-on-start + 接线 · 4 src + 2 test · 1008 tests）· **P100-B156 post-commit 治理复位识别 ✅**（violations-review 误 bump 双 counter 根治 · 1 tool）· **P100-B155 授权门禁颗粒度 ✅**（PFL-263 operation 维度 + cancel 接线 · 8 src + 1 test · 1005 tests）· **P100-B154 存量 500 根治 ✅**（PFL-265 recovery_event 类型 · 1 src + 1 test）· **P100-B153 门禁基建治理 ✅**（PFL-264 + $0 扫面 + 新鲜度模型 · 0 src）· **P16-B13 残留机制缺陷扫面 ✅** · **P16-B12 --bare 隔离 ✅** PFL-258 · session-init driver 补偿 · **P16-B11 API 缺陷三连 ✅** PFL-251/266/253 · 1001 tests · **P16-B10 路由回落 get_next_task ✅** PFL-257 孤儿兜底 · 998 tests · **P16-B9 active_task_id 收口 ✅** PFL-254/255 · 997 tests · **P16-B8 执行环 driver 收口 ✅** PFL-260/261 · **P16-B7 首刀 ✅** PFL-262 心跳/执行解耦 · **P16-B6 狗粮闭环 🎉** · 执行环零 human turn · 新登记 PFL-260~266 · PFL-258 ✅ 隔离闭环（--bare + session-init 补偿） · P100-B152 门禁隔离泄漏修复 ✅ PFL-259 · P16-B5 修执行环 claim→execute 断裂 ✅ · PFL-247/248/249/250 闭环 · 新登记 PFL-254/255 · P16-B4 狗粮第一轮 🔴 · P16-B3 driver ✅ · P16-B2 state-router ✅ · P16-B1 spike 🟢 放行 · P15 全量闭环 🎉 · P100 违纪回顾 ✅）
> 执行规则：Phase + Batch 两级编号。每批 2-4 个任务，完成即验证。

---

> 📦 **Phase 10（47 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)
> 📦 **Phase 11（137 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)
> 📦 **Phase 12（52 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)
> 📦 **Phase 13（13 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)
> 📦 **Phase 14（16 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)
> 📦 **Phase 15（4 批·全量闭环 🎉）** → [`docs/archive/roadmap-archive.md`](archive/roadmap-archive.md)

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
| **P100-B81** | **文档全局刷新** — master-backlog S-036✅+统计 · roadmap B61-B80 补登记 · requirements-log B76-B80 补 · daily B78-B80 追 · 含 post-commit.sh L5 豁免修复（原 B81·a） | ✅ |
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

## P16 路线图：机制级修自主性 ▶️

> **唯一目标**：消灭 human-as-message-bus —— 执行 loop（claim→execute→submit→verify）零 human turn 自主跑完
> **根因**：P15「自主 ❌」· 交互式 Claude 会话无自动 user turn · CronCreate session-only 不可靠
> **范围**：[`docs/plans/p16-scope.md`](plans/p16-scope.md) · 启动 2026-08-18

```
P16-B0 ✅ Scope 定义（本批）
  — 三决策：澄清=故障指示灯 · 确认不做状态机 · 可判定验收条件 master 判据
  — 机制：heartbeat state-router + headless worker driver
    │
P16-B1 ✅ spike — claude -p headless 工具面验证（唯一硬门槛 · 🟢 放行）
P16-B2 ✅ heartbeat state-router（next_action + active_task_id + queue 计数 · Server 侧）
P16-B3 ✅ headless worker driver（start-worker.sh · O+B 通用 · idle backoff）
P16-B4 🔴 狗粮第一轮 — 零 human turn 未达成 · 卡死 claim→execute · 7 发现（PFL-247~253）
  — ✅ 跑通：O 拆解（14min40s）· B claim · depends_on 拦截
  — 🔴 根因：claim 不挂 active_task_id + 心跳每跳擦掉它（双边断裂）
  — 🔴 方法学修正：worker 必须多客户端独立终端，不得作 God's-eye 子进程
    │
P16-B5 ✅ 修执行环断裂（F1/F2/F3/F4）
  — F1 active_task_id 双边（claim/assign 挂 + 心跳 UNSET 哨兵「缺省=保持」）
  — F2 dep-blocked 不计 ready + 陈旧 active_task_id 路由层收口防御
  — F3 driver 超时 360→900s + 失败指数退避 · F4 claim 端点文档 drift
  — 964 tests（+9 回归测试 · 旧代码下 6/9 变红自证）
    │
P16-B6 🎉 狗粮重跑闭环 — 执行环零 human turn 跑完 A→B→C（0 src code）
  — 主判据 1-5 全 🟢 · 假设 H 成立 · 3×3 verification 全 passed
  — A(心跳留痕)→B(端点)→C(CLI) depends_on 串行链全 completed · B4 死循环未复现
  — 交付在 p16/b6-dogfood 分支 worktree（commit 466ad72/8528dd6），非主仓
  — 七条发现 PFL-260~266：split 收口 / 超时标定 / 模型卡死→stale 误判 / 僵尸授权死锁
    / worktree L5 门禁 / 存量 recovery 500 / me-state 500 + 未认领 404
  — 复盘：docs/plans/p16-b6-retrospective.md
    │
P16-B7 ✅ PFL-262 心跳/执行解耦（平台批 · 993 tests）
  — driver keepalive 心跳与 claude -p 同步 wait 解耦 + stale 回收存活门禁
    │
P16-B8 ✅ 执行环 driver 收口 — PFL-260 split 收口 + PFL-261 超时标定（平台批）
  — PFL-260：拆解收口钉死（全部子任务 ready + 父容器 CANCELLED）· role-orchestrator.md + SKILL.md
  — PFL-261：driver 超时按 next_action 分档（split 1800 / execute 2400 / 轻 900）· start-worker.sh
  — 993 tests（纯模板/脚本 · 零 src 触碰 · 零回归）
    │
P16-B9 ✅ active_task_id 收口 — PFL-254 源头清理 + PFL-255 批量挂接（平台批 · 997 tests）
  — PFL-255：claim_batch/assign_batch 挂首个任务（attach_active_task）· cooperation.py
  — PFL-254：lease 过期新增 release_active_task 条件清空 · terminate/pause 保留指针（复核修正）+ docstring 修
  — 方向修正：原「三处源头清空」会破坏 validate_task_active 的暂停/取消检测 → 仅 lease 清空
    │
P16-B10 ✅ 路由回落 get_next_task — PFL-257 孤儿兜底（平台批 · 998 tests）
  — state_router 用 get_next_task（FIFO 活跃→IN_PROGRESS→REJECTED）取代 resolve_workable_active_task
  — get_next_task 规则 1 收敛到 resolve_workable_active_task（消 owner_type drift · PFL-256）
  — active_task_id 语义变更：回显指针 → 该干哪个任务（schemas/worker.py）
    │
P16-B11 ✅ API 缺陷三连 — PFL-251/266/253（平台批 · 1001 tests）
  — PFL-251/266a：/workers/me/state 的 depends_on JSON 字符串未解析 → 500（safe_loads 提取 task_id）
  — PFL-253：role 解析脑裂 — heartbeat 删 metadata 级 resolve_role 告警 + state role 改 get_project_role
  — PFL-266b：_protocol.md §4.2 + role-builder.md 依赖自检对齐 dependency-chain（替代逐项 GET 依赖 task）
P16-B12 ✅ --bare 隔离 — PFL-258（工具批 · 0 src code）
  — claude -p --bare 拦截 plugin 级 SessionStart hook（PUA）注入 + run_session_init() 补偿 session-init 被跳过
  — auth 副作用经机械探针证伪（--bare 仍读 settings env）→ 无需 auth 重注入
P16-B13 ✅ 残留机制缺陷扫面（侦察批 · 0 src code）
  — 确认 4 残留缺陷（PFL-263/264/265/267）全部 🔴 活跃 · 死代码/类型/未接线三扫面无新增
  — 正式登记 PFL-267 · P16 核心机制闭环 · 4 缺陷路由 P100 治理轨
  — 2026-09-26 标记升级：P16 全量闭环 🎉（残留 4 缺陷 PFL-263/264/265/267 已在 P100-B153~B158 全关）
```

## P17 路线图：人机协作协调层 🔄

> **战略重定向（2026-09-26 · owner 对齐）**：护城河从「智能层（让 agent 更自主）」切回「协作层（人机混合协调）」。基模/agent 产品升级会免费吃掉能力层，但「多个 agent + 人如何协作」（组织/状态/约束/上下文）基模解决不了——这才是 Synapse 的护城河。
>
> **锚**：agent 能力层告一段落，不再主攻「让 agent 更自主」；下一阶段主攻「人机协作协调层」。
>
> **跑偏轨迹（回归初心）**：P7/P8/P9 方向本就对（P7-D2 人机混合团队模型 · P8 整个 Phase 就叫「人机协调引擎」· P9 定调「Task 是入口，其余都是标签」）→ P10 拐进四实体基础设施 → P11 陷单 agent 稳定（137 批未达成 PMF）→ P12-P16 继续 agent 自主。方向从协调层滑到能力层，P7-D2「人机混合团队模型」从没落地。
>
> **上下文卸载是命门**：worker 只带「任务切片 + 依赖」，全貌按需查平台。这哲学是双向的，但只做了 agent 侧——人现在是 `human-as-context-bus`（脑子承载全团队全貌）。P16 消灭了 `human-as-message-bus`，没消灭这个。

### 收尾与治理分工（2026-09-27 owner 重判）

> **原则**：治理轨道（P100）做「不新增能力、不为新业务铺路的善后」；业务轨道（P17）做「新增能力，或直接为它铺路」。P11 憋 9 批膨胀 137 批是教训——增量迭代，不憋大招。

1. **战略定性（锚）** ✅ P17-B1 —— roadmap/PRD 落战略锚（前向战略决策，类 P7 D1-D5）。
2. **资产切分 → P100 治理** ✅ P100-B169 —— 继承协作层地基（Task 状态机 · depends_on · 授权门禁 · 租约 · verification · Event Store · O/B/Steward 角色协议）；封存能力层（headless driver · daemon · `--bare` · session-init · 心跳自愈 · Capability 声明）。
3. **债务清账 → 分轨** —— 能力层债（PFL-241/242 冷启动断点/daemon 自毁）封存不追 ✅ P100-B169；协作层债（PFL-244 GAP-10 / PFL-245 lease 误判 / PFL-246 pre-push 只护 master）必须还 → PFL-245 ✅ P17-B2 · PFL-244/246 → P100 backlog（挡「人 + agent 协作做外部功能」）。

### 协作第一增量（P17-B2）

- 让真人能像 agent 一样：**认领任务 · 读项目规范（skills）· 同步状态**——不再是「写需求 + 点批准」两个端点（P7-D2 落地最小版）。
- 前置：还协作层债 PFL-245（lease 对 human owner 免死）。PFL-244/246 是「人 + agent 协作做外部功能」的前置，不挡三件事本身 → 挂 P100 backlog。

| Batch | 内容 | 状态 |
|-------|------|:----:|
| P17-B1 | 战略定性（锚）— roadmap/PRD 落「能力层告一段落 · 主攻协作层」· 登记 P17 轨道 | ✅ |
| P17-B2 | 还 PFL-245（lease 对 human owner 免死）— 协作第一增量前置 | ✅ |
| P17-B3 | 人认领/读规范/同步 最小闭环（P7-D2 最小落地） | ✅ |
| P17-B4 | 人机闭环狗粮验证（真人 claim→读规范→同步→submit · 6/6 🟢）· 暴露+修复 2 gap（PFL-269 event actor_type 遗留值 · PFL-270 前端 submit 缺 evidence 采集） | ✅ |
| P17-B5 | 项目「态势」视图（人侧上下文卸载最小版 · 完整依赖 DAG + 项目事件流 · 0 src 后端 · 7 frontend） | ✅ |
| P17-B6 | 项目「态势」视图 WS 实时化（DAG 实时 + 事件流 prepend · 项目隔离 target_id∈dagNodeIds · 0 src 后端 · 2 frontend） | ✅ |
| P17-B7 | DependencyGraph N+1 修复（复用 /dependency-graph + 本地 BFS 上游闭包 · 0 src 后端 · 2 frontend + e2e） | ✅ |
| P17-B8 | 人侧反馈最小闭环（S-020 反馈协议 v2 · TaskDetail 协作消息面板 + mention 投递 · 2 src 后端 + 4 frontend + 2 tests） | ✅ |
| P17-B9 | 协作消息面板 resolve 收口 + e2e 验证（前端 resolve/reopen 按钮 + WS 订阅 resolved · 0 src 后端 · 4 frontend + e2e） | ✅ |
| P17-B10 | 协作消息面板 reply/threading 收口（后端 in_reply_to_id 早已就绪 · 前端回复按钮/banner/缩进/↩ 标识 · 0 src 后端 · 4 frontend + e2e） | ✅ |
| P17-B11 | 会话生命周期 dogfood（真人 @mention → agent 真回 → resolve 闭环 · 6/6 🟢 · 暴露 PFL-274 mention 实时投递 vs worker 轮询消费脱节 · 0 src code） | ✅ |
| P17-B12 | PFL-274 B1 查询层落地（mention 关联表落 worker_id + 未读查询 list/count_unread_mentions + GET /workers/me/mentions · 6 src + 1 migration · +10 tests） | ✅ |
| P100-B169 | 资产切分（继承协作层地基 7 项 / 封存能力层 6 项）+ PFL-241/242 封存不追 + check-batch-numbers 防呆补漏 | ✅ |

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
- **P100-B139**：**治理批（escalation PFL 自动登记根因 + 脚本白名单 + tracks 刷新）** ✅ — ① escalation detector 运行期自动写 PFL 根因：.env 加 PFL_AUTO_CREATE_ENABLED=false 止血 + PFL-240 登记（三层根因）· src/config.py:130 默认值 True→False 登记为 VDD 待办（交 Builder）· ② cleanup-dogfood-residue.py 加 --keep-worker 白名单（防误删 human worker）· ③ tracks/synapse.md frontmatter P13→P14 全量闭环 + 指针表补 P14 行 · 🟡 标准 · 6 files（1 pitfalls + 1 roadmap + 1 reqlog + 1 daily + 1 script + 1 track）
- **P100-B140**：**PFL-240 根治（escalation 运行期不再写治理文档 · 触 src/）** ✅ — ① src/config.py:130 `pfl_auto_create_enabled` 默认 True→False（PFL 自动登记改 opt-in）· ② escalation_service.py 移除 `_maybe_auto_create_pfl_and_task()`（`create_pitfall` 写 pitfalls.md + auto tracking Task）—— escalation 只记 event + @Human/WS push · ③ +1 test（escalation 不调 create_pitfall）+ config 默认值断言 · ④ PFL-240 状态 🔴→🟢 · 🟡 标准 · 2 src + 1 test + 3 doc · 942 tests 零回归
- **P100-B141**：**PFL-auto-create 孤儿 config 清理（死字段移除）** ✅ — B140 移除 `_maybe_auto_create_pfl_and_task()` 后，`pfl_auto_create_enabled` + `pfl_auto_create_cooldown_minutes` 两字段失去唯一消费方 → 一并删除（含 P14-B2 G2 段注释）· test 移除 `pfl_auto_create_enabled is False` 断言 · .env 删 stale `PFL_AUTO_CREATE_ENABLED`（本地 gitignored）· 🟢 微型 · 1 src + 1 test · 942 tests 零回归
- **P100-B142**：**死配置 + stray 清理 + 脚本修正（3 项 · 0 业务风险）** ✅ — ① 删 src/config.py `host`/`port` 死配置（全仓 0 引用 · `debug` 仍被 db.py/auth.py 消费）② 删 synapse/test.db 0 字节 stray（8月10 遗留 · gitignored）③ tools/violations-review.sh grep 过宽修正（对齐 check-violations.sh index-section 范围 · 已防呆 43→27 · unguardedCount 1→3）· 🟢 微型 · 1 src + 1 脚本 + 1 stray 删除 · 942 tests 零回归
- **P100-B143**：**conftest api_key_hash stale 注释清理（确认 P10-B8 已完成 nullable）** ✅ — 澄清「api_key_hash NULLABLE」账上待办实为 P10-B8 已完成（迁移 019f6ec74577 + 模型 worker.py:51 nullable=True + DB notnull:0）· 清理 conftest.py:141 过时 `TODO: make NULLABLE` 注释 + `""`→`None` 对齐生产 auth_service.py 模式 · 🟢 微型 · 1 test · 942 tests 零回归
- **P100-B144**：**3 个 worktree 门禁缺陷修复（0 src code · 纯工具/门禁）** ✅ — ① check-hooks.sh + pre-commit `$REPO_ROOT/.git/hooks` → `git rev-parse --path-format=absolute --git-path hooks`（worktree 中 `.git` 是文件非目录 → 消除「hooks 缺失」误报）· ② pre-commit GAP-10 正则 `(^|/)package\.json$` → `^synapse/requirements\.txt$|^synapse/frontend/package\.json$`（锚定 synapse 自身 manifest · 消除误伤嵌套独立项目 `snippet-vault/frontend/package.json`）· ③ 新增 tools/resolve-venv.sh 单源解析 venv + Makefile `$(PY)` 替换 9 处 + check-contracts.sh venv 解析（稀疏 worktree 无 .venv → 回退主仓 synapse/.venv）· 🟢 微型 · 5 files（4 改 + 1 新）· 0 src code · 942 tests 零回归 · 排期遗留：Makefile hooks 目标 + synapse-exec --install-hook 的安装期 `.git/hooks` 硬编码（非门禁期 · 留待后续）
- **P100-B145**：**安装期 `.git/hooks` 硬编码收口（0 src code · 纯工具/门禁）** ✅ — ① Makefile `hooks:` 目标 `../.git/hooks` → `git rev-parse --path-format=absolute --git-path hooks`（worktree 中 `.git` 是文件非目录 → `make hooks` 修复路径失效）② tools/synapse-exec `install_hook()` `${git_root}/.git/hooks` → 同款解析（`--install-hook` 修复路径失效）· 补 B144 只修「检查期」、漏「安装期」的盲区 · 🟢 微型 · 2 files（Makefile + synapse-exec）· 0 src code · 942 tests 零回归 · 排期遗留清零 · B146 候选登记：① commit-msg `HOOK_DIR` 静默绕过（prefix/batch-sequence 门禁不生效）② check-hooks.sh --fix fallback 只装 pre-push 不装 3 hooks
- **P100-B146**：**commit-msg 门禁静默绕过 + check-hooks --fix fallback 根治（0 src code · 纯工具/门禁）** ✅ — ① tools/commit-msg `HOOK_DIR` 用 `dirname $0`（=.git/hooks 非 synapse/tools）→ check-commit-prefix.sh / check-batch-sequence.sh `[ -x ]` false → prefix + batch-sequence 两门禁静默失效（影响每次 commit）· 修法对齐 pre-commit 范式 `$REPO_ROOT/synapse/tools/...` + 删死变量 `HOOK_DIR` ② tools/check-hooks.sh --fix fallback 到 `synapse-exec --install-hook` 只装 pre-push 不装 pre-commit/commit-msg/post-commit → 3 hook 缺失时装完仍 repair incomplete · 修法移除无效 fallback（`make hooks` 是唯一正确修复路径）· 🟢 微型 · 2 files（commit-msg + check-hooks.sh）· 0 src code · 942 tests 零回归 · 实证：无前缀 msg → exit 1 阻断 ✅ · 合法前缀 → exit 0 + GAP-4 通过 ✅ · 删 post-commit → --fix 真正修复 ✅
- **P100-B147**：**门禁脚本收尾（pre-commit 死变量 + stale 安装注释）** ✅ — ① tools/pre-commit `HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"` 死变量（B146 同款 footgun · 已全用 REPO_ROOT 零消费 · 留之则未来编辑者恢复使用即重新引入静默绕过）→ 删除 ② tools/check-commit-prefix.sh 头注释 stale `cp` 安装 + 误标「commit-msg hook」（实为 commit-msg 调用的 helper）+ tools/post-commit.sh 头注释 `cp` → `ln -sf`（对齐 B134 symlink 范式）· 🟢 微型 · 3 files（pre-commit + check-commit-prefix.sh + post-commit.sh）· 0 src code · bash -n 全绿 · 942 tests 零回归
- **P100-B148**：**SessionStart hook 孤儿化根治（0 src code · 纯工具/门禁）** ✅ — 根因: SessionStart hooks（canary + check-docs + reset-batch-counter）配在 `synapse/.claude/settings.json`（子目录），Claude Code 从项目根 `/ai-synapse` 启动只读根 `.claude/settings.json` → hooks 从 8/11 起静默失效（canary 6d stale）· 修法: ① 新建根 `.claude/settings.json` 迁移 3 hooks（相对路径 `tools/` → `synapse/tools/`）② 根 `.claude/settings.local.json` 补 3 条权限 allow ③ git rm 孤儿 `synapse/.claude/settings.json` ④ tools/check-session-hook-health.sh `SETTINGS_FILE` 指向根 settings + 恢复指引路径同步 · 🟢 微型 · 4 files（1 新 + 2 改 + 1 删）· 0 src code · 命令级等价验证（canary age=0s · check-session-hook-health --gate 恢复 HEALTHY）

- **P100-B149**：**pitfalls.md 文档债拆分归档（0 src code · 纯文档）** ✅ — 根因: pitfalls.md 2084 行超注册表硬阈值 1100（122 PFL 中 111 条已 🔗合并/✅修复 仍滞留活跃区）· 处置: 脚本化拆分（按 `### ` 边界 · 原文件分隔符不一致）— 归档 113 条（111 PFL + AP-B37 + B73 补充发现）到 docs/archive/pitfalls-archive.md（1905→3799 行）· 活跃区只留 11 条未闭环（PFL-246~241/238/172/142/141/130）· 头部计数 122→11 · 🟢 微型 · 2 files（pitfalls.md 2084→209 + pitfalls-archive.md）· 0 src code · check-docs.sh pitfalls 硬阻断清除（5 硬错误 → 4）· B150 候选: roadmap.md 846>800 + 3 stale-date 文档
- **P100-B150**：**roadmap.md 封闭 Phase 归档（0 src code · 纯文档）** ✅ — 根因: roadmap.md 848 行超硬阈值 800（Phase 12/13/14/15 全量闭环后完整批次表滞留活跃 roadmap · 与 Phase 10/11 已归档但 P12-P15 未随闭环归档的同类债务）· 处置: 归档 4 个全量闭环 Phase 批次表（P12 52 批 · P13 13 批 · P14 16 批 · P15 4 批）verbatim → docs/archive/roadmap-archive.md（292→539 行）· 头部补 4 条 📦 归档指针（对齐 Phase 10/11 范式）· Phase 历史表补 P12-P15 四行 · 🟢 微型 · 2 files（roadmap.md 848→613 + roadmap-archive.md 292→539）· 0 src code · check-docs.sh roadmap 硬阻断解除（4 硬错误 → 3）
- **P100-B151**：**3 stale-date 文档新鲜度诚实更新（0 src code · 纯文档）** ✅ — 根因: check-docs.sh 报 architecture/lessons-learned/methodology 三文档最新日期 08-10 落后需求日志 08-17（B150 归档后剩 3 硬错误）· 处置（诚实原则禁只 bump）: ① lessons-learned.md 新增 LL28~LL30（治理波 B130-B150 三条可迁移教训 — 脚本 footgun 三连 / 运行期副作用污染治理文档 / 检测基建自我漂移）② architecture.md §3.3 补 B137 时区序列化 note + 版本 v2.2→v2.3 ③ methodology.md §5.6 补「新鲜度诚实原则 — 禁只 bump 日期」+ 版本 v2.0→v2.1 · 🟢 微型 · 3 files · 0 src code · check-docs.sh 3 硬错误 → 0（✅ 文档门禁通过 · 8 警告非阻断）

- **P100-B152**：**门禁测试隔离泄漏修复（PFL-259）** ✅ — 触发: P16-B6 按规则 15 写了 `docs/plans/p16-b6-dogfood-plan.md`，`make check` 里 `test_v020_scope_shift` 两条突然变红，而该批**没碰过门禁代码** · 根因: `check-plan-mode.sh` 用 `$0` 硬推导 `PROJECT_DIR`，而 `run_gate()` 用绝对路径调脚本 → 传 `cwd=temp_repo` **只隔离得了 `git diff --cached`**，隔离不掉 `tracks/synapse.md` 与 `docs/plans/` · **绿是偶然的**: 真实仓库当前批此前恰好没有 plan 文件 → 走「无 plan」分支 → V-020 触发 → 断言碰巧成立；**任何一批只要按规矩写了 plan 就会踩红 = 门禁反向惩罚守规矩的行为** · A/B 实证: 移走 plan 文件 3 passed / 放回 2 failed · 处置: `PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"` + `run_gate()` 有 cwd 时同步设该变量（生产路径不设 → 行为完全一致）· 自证: 新增 `test_v020_reads_temp_repo_track_not_real_one` 钉住隔离本身，旧脚本下**变红** · 修复后 plan 在/不在**均 4 passed**（状态无关性成立）· 🟢 微型 · 3 files（1 tool + 2 tests）· 0 src code

- **P100-B153**：**门禁基建治理（PFL-264 worktree + $0 泄漏扫面 + 新鲜度模型）** ✅ — 三项门禁基建（0 src code）· ① PFL-264: `l5-gate.sh` + `check-l5-consistency.sh` 检测 worktree（`--git-dir`≠`--git-common-dir`）→ 治理计数器门禁只作用于主仓（Builder 不再被陈旧 checkpoint 副本卡 commit）② $0 泄漏扫面: 25 门禁脚本 `dirname "$0"`→`BASH_SOURCE[0]`（symlink 安全）+ `SYNAPSE_PROJECT_DIR` 覆盖（可测试 · PFL-259 同族）③ 新鲜度模型: `check-docs.sh` 拆两档——活跃日志（roadmap/pitfalls）ERROR vs reqlog · 参考文档（architecture/lessons/methodology/prd 等 9 份）90 天 WARN 不与 reqlog 比较（B151 只修症状未修模型）· 🟢 微型 · 27 files（0 src code）· 1001 tests 零回归 · 下一站 B154（PFL-265+PFL-263 直接根治）
- **P100-B154**：**存量 500 根治（PFL-265 recovery_event 类型）** ✅ — 触发: `WorkerHeartbeatResponse.recovery_event` 声明 `dict | None` 实返 `str`（`worker_service.py` 返回 `event_type`）→ 首次心跳必 500、第二次才 200 · 根因: 类型声明与实现不一致 + 缺 HTTP 层 response_model 回归测试（纯 service 单测走不到序列化层）· 处置: `schemas/worker.py:114` `dict | None`→`str | None` + 新增 HTTP 层测试 `test_heartbeat_recovery_event_serializes_as_str`（ASGI client · ERROR→IDLE 恢复路径）· 红绿实证: 旧 schema `Input should be a valid dictionary [input_value='worker.runtime.idle']` → 500，修复后 200 · 🟢 微型 · 2 files（1 src + 1 test）· 1002 tests 零回归 · 下一站 B155（PFL-263 授权门禁颗粒度 · 需完整 Scout+plan）
- **P100-B155**：**授权门禁颗粒度（PFL-263 operation 维度 + cancel 接线）** ✅ — 触发: `_check_no_pending_auth` 门禁只按 `(worker, task, pending)` 过滤、忽略 `operation` → 一条残留 `task.assign` 僵尸把毫不相干的 `verification.verify` 一起 409 锁死（PFL-263 三层根因）· 处置: ① `constants.py` 新增 `AuthorizationOperation(StrEnum)`（10 成员单源）② `_check_no_pending_auth` 加 `operation` 参数 + WHERE `operation ==`，9 mutation 调用点 + verify 各传常量 ③ `verification_service.py` 内联门禁 DRY 共享函数（消「同源复制」）④ 铸造侧 `conversation_service.py` + `authorization_service.py` `_assess_risk_level` 字面量→常量 ⑤ `worker_service.py` handshake OFFLINE→IDLE 分支接 `cancel_worker_requests`（层2 死代码接线）⑥ 补 3 回归测试（红绿实证：改动前 verify 抛 PENDING_AUTHORIZATION）· 层3（human admin 预置）转 DG 纪律 → B157 · 🟢 中型 · 8 src + 1 test · 1005 tests 零回归 · 下一站 B156（PFL-267 lease 死代码）
- **P100-B156**：**post-commit 治理复位识别补全（violations-review 误 bump 双 counter 根治）** ✅ — 触发: 违纪回顾 commit 被 post-commit 的 `is_l5` 检测（只认 `L5`/`拉通`）误当普通 batch → 双 counter 误 bump（`batchesSinceLastL5` 1→2 触发 L5 门禁 · `batchesSinceLastReview` 0→1 抵消复位）· 根因: 治理复位检测不完整——B134 只补了 violations 块的 L5 skip，未把「违纪回顾」识别为复位点 · 处置: `post-commit.sh` 检测变量 `is_l5`→`is_governance_reset`，条件加 `or ('违纪回顾' in commit_msg)`，两 counter 块共用 · 🟢 微型 · 1 tool（0 src code）· 下一站 B157（PFL-267 lease 死代码）
- **P100-B157**：**租约释放死代码根治（PFL-267 · guard + clear-on-start + 接线）** ✅ — 触发: `release_expired_leases` 唯一生产调用链是 admin 手动端点 `POST /failure-detection/run` → 「租约过期→释放」安全网生产侧死代码 · 根因（三层叠加）: ① `run_all_detections` 从未接入 main.py 后台循环 ② `release_expired_leases` 查询不查 worker 心跳新鲜度（PFL-245 同族，直接接线会误放卡门禁的活 builder）③ 租约只写不续（claim/assign/activate 写入，start_task 不清）· 处置: ① `owner_worker_alive`（原 `_owner_worker_alive` 公开重命名）复用为免死守卫，release 前跳过活 worker ② `worker_scheduler.start_task` 清 `lease_expires_at`（lease 语义收敛 claim→start 窗口）③ `_stale_task_reaper` 加第 6 个 detector（lease）+ `_system_intervention_lease_released` 计数器 · 心跳/进度硬故障释放（与 monitor OFFLINE 语义重叠）转 B158 · 🟢 中型 · 4 src + 2 test · 1008 tests 零回归 · 下一站 B158（心跳/进度硬故障释放 / PFL-263 层3 human admin 预置）
- **P100-B158**：**心跳/进度硬故障释放定性收口（PFL-267 manual-only by design）** ✅ — 触发: B157 根治 lease 线时把心跳/进度硬故障释放切出为「单独评估」；Scout 深化发现 `last_progress_at` 全仓仅 2 写入点（task 挂载/切换时间，非真实进度）→ naive 接 `detect_progress_failures` 会误伤 >T_PROG(300s) 合法长任务（PFL-245/262 同族）· 根因: PFL-262 已定调「回收以 worker 失联为准，不以 task 进度为准」→ 心跳/进度线 manual-only by design，非死代码 · 处置: `failure_detector.py` 模块 docstring 加「接线状态」块（4 条线接线状态写清）+ 3 函数 docstring 末加 manual-only 注记 + `pitfalls.md` PFL-267 尾句改写（「转 B158 单独评估」→「B158 定性收口」）· 🟢 微型 · 0 src code（comment-only）+ 1 doc · 1008 tests 零回归 · 下一站 B159（PFL-263 层3 human admin 预置）
- **P100-B159**：**human admin 预置（PFL-263 层3 · DG 脚本）** ✅ — 触发: PFL-263 层3「狗粮项目无 human admin」死锁根因（human-in-the-loop 门禁变成「等一个不存在的人」· B155 只收层1+2）· 根因: human User/Worker 只在登录后才存在 → 赋角色必须是 post-login 步骤，不能塞进 dogfood-setup 初始注册段 · 处置: 新建 `tools/provision-human-admin.py`（post-login 赋 admin · 复用 set_project_role + setup-hunter-password idiom · 幂等 upsert · --email/--name/--project-slug/--dry-run）+ `p16-b6-dogfood-setup.py` 结尾补 human admin 提示 + `pitfalls.md` PFL-263 层3 关闭 · 🟢 微型 · 0 src code（1 新 DG 脚本 + 2 doc）· 0 pytest（脚本）· 下一站 L5 拉通（B158+B159）+ 违纪回顾（review 5）
- **P100-B160**：**自主性重验证计划+环境搭建（Phase 1 · 0 src code）** ✅ — 触发: P15 判「主张 B 自主协作 = 部分成立（交付 ✅ + 自主 ❌）」时 4 机制 bug（PFL-263 授权颗粒度 / PFL-264 worktree 门禁 / PFL-265 recovery 500 / PFL-267 lease 死代码）已全闭环（B153~B159）+ P16 执行环 headless（B6 狗粮主判据 1-5 全 🟢）→ 判决依据失效，该重判 · 决策: 重验证不新开 Phase（phase-criteria 五维第 3 规模 + 第 4 性质不过关），定性 P100 治理轨狗粮验证批 · 处置: 新建 `docs/plans/p100-b160-autonomy-revalidation-plan.md`（scope/判据/环境/成功线 · 判据三层拆分防 Goodhart + API 面零 human 介入）+ `tools/p100-b160-dogfood-setup.py`（改自 p16-b6 · 注册 O+A+B + project · 默认 o,a · B 分步注册）· 🟢 微型 · 2 files（1 plan + 1 tool）· 0 src code · 下一站 B160 跑狗粮（Phase 2 · 需用户 3 终端）
- **P100-B161**：**setup 脚本 dry-run 自检（0 src code · 工具）** ✅ — 触发: B160 交付的 `tools/p100-b160-dogfood-setup.py` 只经 py_compile + import 解析验证、未真跑（mutation：注册 worker/project + 写 .env/skill），直接进 B162 有运行时 bug 风险 · 处置: 补 `--dry-run` flag（对齐 B159 `provision-human-admin.py` ROLLBACK 无副作用范式）——register_worker/create_project 事务内不 commit（session 关闭自动回滚）· .env/skill 写操作 dry-run 跳过并打印「would write」· 🟢 微型 · 1 tool · 0 src code · 验证: 本地 DB 干跑零异常（create_project 参数 + system worker FK + generate-skill.sh arg 契约全过）· 跑后 DB 无残留（非终态 task 0 · 非 system worker 仍 1 = Hunter · 零新 Event）· 下一站 L5 拉通（counter 2）→ B162 跑狗粮（Phase 2 · 需用户 3 终端）
- **P100-B162**：**跑狗粮 Phase 2（1O+2B 交付 Snippet Vault · 出「自主 ✅」结论）** ✅ — 触发: B160/B161 计划+环境+dry-run 就绪，用户 3 独立终端跑狗粮（1 O + 2 B 各 `start-worker.sh`）· 结果: 主判据 1-5 全达标——①零 human turn ②API 面零 human 介入（authorization_requests 表零记录 · PFL-263/B155+B159 修复生效）③冷启动自跑（O/A/B 31/39/20 次轮询）④depends_on 真实解锁（后端 completed → 前端 claim）⑤零 God's-eye 代码干预（主目录 git status 空）· 副判据 F6-a 进程独立 ✅ / F6-b 探测词零注入 ✅ / F6-c 判据不可见 ⚠️ 接受 · 发现: session-init.js 硬编码 handshake 能力无技术栈 → O split 技术栈任务时 A/B claim 409，worker 自主 re-handshake 恢复（登记 PFL-268 · 自主性强证据 + 模板缺陷）· 🟢 治理批 · 0 src code（狗粮运行 · 结论入 memory + 三同步）· 下一站 B163 善后清理（DG-3）+ PFL-268 + 复盘
- **P100-B163**：**善后清理（DG-3）+ 登记 PFL-268 + B162 复盘** ✅ — 触发: B162 出「自主 ✅」但环境未善后（worker 6 进程 + server :8000 + worktree A/B 仍在）· 处置: ①停 worker（用户各终端 Ctrl-C）②停 server（kill :8000）③删 worktree+branch（A/B · 未合并 Snippet Vault 代码经用户确认删除）④清 DB（cleanup-dogfood-residue.py --keep-worker Hunter · 删 3 dogfood worker + 741 event）⑤主目录 git status 空 · 登记 PFL-268（能力声明硬编码）· 复盘: B162「自主 ✅」替代 P15「自主 ❌」过期判决（CLAUDE.md P15 行 + p15-b2-retrospective.md 注记）· 🟢 治理批 · 0 src code（5+ doc）· 下一站 B164（候选: Shared Module Governance · PFL-268 能力声明动态化）
- **P100-B164**：**PFL-268 能力声明动态化（env 声明 + 409 自愈 · 0 src code · 模板）** ✅ — 触发: B162 狗粮暴露 `session-init.js` 硬编码 handshake 能力（code-generation/code-review 无技术栈）→ O split 技术栈任务时 worker claim 409 · 处置: Part A `lib/session-core.js` 新增纯函数 `buildCapabilityDeclarations` 读 `SYNAPSE_WORKER_CAPABILITIES` env（逗号分隔 + trim + 去重 · 未设回退通用集）+ `session-init.js` handshake 改调函数 · Part B `role-builder.md` 补「claim 409 自愈」指引（读 details 算并集 → 设 env 重 handshake → re-claim 一次 → 仍 409 才 @O · 安全边界只技术栈/语言维度，专有能力不得自声明）· 🟢 治理批 · 0 src code（3 模板/脚本 + 1 test + 1 协议 doc）· +3 tests · 验证: node 单测 49 passed（+3）· pytest 1008 零回归 · 下一站候选 Shared Module Governance 补课（S-005 假闭环）
- **P100-B165**：**Shared Module Governance 补课（S-005 假闭环 · RA 全覆盖 77/77）** ✅ — 触发: S-005 标 ✅ 但 Risk Assessment 只覆盖 4 模块（db/common/auth/config · 经 S-070/B83），checker 报 107 共享模块 103 未评估（73 High + 30 Medium）· 根因两层: ① checker 阈值比 methodology 严（High N≥3 vs 方法论 N≥5）虚增数字 ② `KNOWN_LAYERS` 只 11 模块，其余默认 K=1 → `constants.py`（94 消费者）被误判比 `db.py`（75c）低一档 · 处置: ① 修 `check_shared_modules.py`——阈值对齐 methodology（🔴 N≥10 / 🟠 N≥5 / 🟡 N≥3）· 分类按消费者数 N（K 层数降级为报告元数据，消除 flat-but-wide 误判）· `_has_risk_assessment` 指向新 RA 文件 + 品类覆盖 ② 新建 `docs/shared-module-risk-assessments.md`（28 Critical 逐条 + 14 High 精简 + 30 Medium 品类覆盖）③ methodology-reference §SMG 风险表 N-only 对齐 + master-backlog S-005 补注 · 🟢 治理批 · 0 src code（1 tool + 3 doc）· 验证: checker 77/77 已评估（0 Critical/0 High/0 Medium 未评估）
- **P100-B166**：**reqlog 旧 Phase 归档（0 src code · 纯文档迁移）** ✅ — 触发: reqlog 5176 行超活跃阈值 5000（B109/B127 声称「P9+P10+P11 已归档」但主文件仍滞留已闭环条目）· 根因: 归档单向操作、缺反向核对 → 假闭环（P11 只迁 B8-B55+B85-B95，B2-B7/B59-B84/B122-124 滞留；P9/P10 残片 + 旧 Phase P3-P8/P100 从未归档）· 处置: `tools/p100-b166-reqlog-archive.py` 按 heading 锚点 verbatim 迁档（边界断言 + 内容守恒）——旧债区 3503 行迁 archive + 误置在「考古补登」块的 P100-B128~B151 搬回活跃区 · 🟢 治理批 · 2 files（1 tool + 1 plan）· 0 src code · 验证: 主 reqlog 5176→1673 行 · archive 8062→11573 行 · check-docs 0 硬错误
- **P100-B167**：**授权列表过期修复（前端删 isExpired 残留 + 后端 respond 过期硬门禁）** ✅ — 触发: 过期审批请求仍显示批准/拒绝按钮（P12-B39 加后端过滤前的死代码）· 根因两层: ① 前端 `Approvals.tsx` 的 `isExpired` 死代码——Pending tab 的 "Expired" 标签 + 置灰批准/拒绝按钮 + 置灰 note input，且 modal（顶层 `AuthRequestModal`）引用嵌套在 `Approvals` 内的 `isExpired`（作用域不可达 · TS2304 · 点开历史条目即 ReferenceError）② 后端 `respond_to_request` 只查 `status != pending` 不查 `expires_at`（30s reaper 窗口内已过期仍 pending 可被 stale 客户端批准）· 处置: ① 删前端 `isExpired` 全部残留（Pending footer + modal + 函数 + AlertTriangle import）② 后端加 `expires_at < now` 硬门禁（时区归一 SQLite naive / PG aware · raise ConflictError AUTHORIZATION_REQUEST_EXPIRED）· 🟢 中型 · 1 src + 1 frontend + 1 test · 1013 tests 零回归 · 下一站 B168（P17 资产切分 + PFL-241/242 封存）
- **P100-B168**：**report_execution InvalidStateTransition 传参修复** ✅ — 触发: B167 顺带发现 `report_execution` 非 approved 分支的 `InvalidStateTransition` 调用传了签名外 kwarg（`request_id`/`message` · 缺 `entity_type`/`entity_id`）→ 命中即 TypeError（500 而非干净 400）· 根因: `InvalidStateTransition.__init__` 签名固定 `(entity_type, entity_id, from_status, to_status)`，此调用点抄错参数名 · 处置: 改回 `entity_type="AuthorizationRequest"` + `entity_id=request_id`（对齐 respond_to_request/heartbeat/protection_service 等 7 处正确调用）+ 补 test_report_non_approved_raises_invalid_transition（此前 report_execution 零测试覆盖 → 漏网根因）· 🟢 微型 · 1 src + 1 test · 1014 tests 零回归 · 下一站 L5 拉通（counter 2）+ B169（P17 资产切分 + PFL-241/242 封存）
- **P100-B169**：**P17 资产切分 + PFL-241/242 封存 + check-batch-numbers 防呆补漏** ✅ — ① 资产切分落地: roadmap「P100 候选 ⬜」→ 已执行（继承协作层地基 Task 状态机/depends_on/授权门禁/租约/verification/Event Store/O-B-Steward · 封存能力层 headless driver/daemon/--bare/session-init/心跳自愈/Capability 声明）② PFL-241/242 封存不追: pitfalls.md 状态 🟡已知 → 🟡封存不追（能力层 · 随基模淘汰不再投入）③ check-batch-numbers 防呆补漏: V-008 第3次复发根因（脚本只接 make check 未接 commit 门禁 + SCAN_FILES 缺 track/pitfalls/daily）→ 补「扫 staged 文档内容子编号」+ 接 pre-commit Stage 10 + process-violations.md V-008 防呆真落地 · 🟢 治理批 · 0 src code（2 doc + 1 tool + 1 hook + 1 违规文档 + 三同步）· 下一站 B170（常开待命）
- **P100-B170**：**check-batch-numbers full-scan 对齐 staged 模式** ✅ — 触发: B169 补 staged 门禁但 full-scan（make check）仍用旧窄 3 正则（缺裸 B<数字><字母>）+ 窄 SCAN_FILES（roadmap/reqlog/CLAUDE/plans）→ 与 commit 门禁两套判据、手动预检漏报。根因: 子编号正则 + 文件集在两处各自维护 → 漂移。处置: ① 抽单一来源 SUB_NUMBER_PATTERN（补裸 B<数字><字母> 第 4 支）staged/full-scan 共用 ② SCAN_FILES 扩 pitfalls/process-violations/lessons-learned/tracks/daily（archive/decisions 显式排除）③ 存量历史子编号引用（B2·a/B73·a/P11-B14·a 等）· 间隔号转写保真 · 🟢 治理批 · 0 src code（1 tool + 8 doc）· 意外收获: 裸模式一补即暴露全局 plans B153 草稿 B153·a/b/c 子编号（旧模式漏网）· 下一站 L5 拉通（counter 2）
- **P100-B171**：**WS 鉴权迁 cookie 根修（后端 cookie 回退 + 前端去 ?token=）** ✅ — 触发: P100-B58 把 JWT localStorage→httpOnly cookie 只迁了 HTTP 层漏了 WS 层 → 前端把哨兵 `'cookie'` 当 token 拼进 `ws://…/v1/ws?token=cookie`，后端 ws.py 只认 `?token=` 真 JWT → close 4001 → 前端「未连接」常驻。根因: WS 层鉴权未随 HTTP 层 cookie 迁移。处置: ① 后端 ws.py `token: Query(...)` → `Query(None)` 可选 + cookie 回退 `ws.cookies.get(access_token_cookie_name)`（对称 dependencies.py:47）+ 缺 token → close 4001 ② 前端 ws.ts 浏览器客户端不再拼 `?token=` 改走 cookie ③ 补 3 例测试（cookie 无 query → connected · query 回归 · 缺 token → 4001）。· 🟢 中型 · 1 src + 1 frontend + 1 test · 1017 tests 零回归 · 下一站 B172（失败退登录 · WS onclose 4001 → logout）
- **P100-B172**：**失败退登录（WS onclose 4001 → logout）** ✅ — 触发: B171 打通 WS 鉴权后，401 会话过期/无效凭据后端 close 4001，但前端 ws.ts onclose 仍按网络断开做指数退避重连，死循环重试 4001 不退登录。根因: onclose 未区分「鉴权失败 4001」与「普通断连」。处置: ① ws.ts onclose 捕获 `event.code`，`=== 4001` → 立即 `onTokenExpired()`（logout → ProtectedRoute 跳 /login），非 4001 走原有退避重连 ② Layout.tsx + Approvals.tsx 的 useWebSocket 调用点补 `onTokenExpired={logout}`（原先裸调用未接）。· 🟢 微型 · 3 frontend · 1017 tests 基线不变（无 Python 变更）· 下一站 B173（清陈旧提示 · 删 synapse_token setItem 死文案）
- **P100-B173**：**清陈旧提示（删 synapse_token/synapse_team_id setItem 死文案）** ✅ — 触发: B58 迁 JWT localStorage→httpOnly cookie 后，pre-B58 的 `localStorage.setItem('synapse_token')` / `'synapse_team_id'` 教学文案成死文案（全仓 0 处 getItem 读取）。根因: 陈旧提示残留误导用户手动设 token（实际已走 cookie）。处置: ① Dashboard.tsx / WorkerList.tsx 删硬编码 setItem 提示块 + 孤儿 `authHint` 键 ② translations.ts `setTokenHint` 文案改写（"Set synapse_token…in localStorage" → "Please sign in to continue." / ZH "请登录后继续。"）③ 删孤儿 `.hint` / `.hint code` CSS。· 🟢 微型 · 5 frontend · 1017 tests 基线不变（无 Python 变更）· 下一站 违纪回顾（violations 4→5 触阈值）→ B174
- **P100-B174**：**Playwright E2E 基建（devDependency + config + 双服务 webServer + 态势 #2/#3 实时断言）** ✅ — 触发: P17-B6 态势视图 WS 实时化已验证到「服务器广播层」（契约一致 + 运行时广播 + tsc/oxlint/pytest 全绿），但前端无测试 runner（仅 tsc/oxlint）→ React 实际渲染 DOM 无自动化判据。根因: 缺 E2E 基建。处置: ① `@playwright/test` devDependency + `playwright.config.ts`（双服务 webServer: uvicorn :8000 + vite :5173 · 本地复用已跑服务）+ `test:e2e` script ② ProjectDetail tab 按钮 / ProjectOverview live 圆点 / DAG 节点 / 事件行补 `data-testid`/`data-*`（只加属性不改逻辑）③ e2e: API 登录 Hunter 注入 access_token cookie（dev 自动登录使登录表单不可达）→ 自播 `e2e-smoke-*` 命名空间项目（A→B→C 链 + 隔离项目 X）→ 断言 live 绿点 + DAG 渲染 + claim→in_progress 实时变色（不手动刷新）+ 事件流 prepend + 跨项目隔离。· 🟢 中型 · 0 src 后端 · 2 frontend src + 3 e2e/config · 1017 tests 基线不变 · Playwright 2/2 绿 · 下一站 B175（常开待命）
- **P100-B176**：**PFL-269 coerce + PFL-272 事件流修复（/tasks/{id}/events 端点）** ✅ — 触发: P100-B175 Scout 发现 2 缺陷——① PFL-269 `event.actor_type` 遗留脏值（agent/member/SYSTEM）透传严格枚举 `EventResponse.actor_type` → 单条脏值整端点 500 → TaskDetail「加载失败」② PFL-272 TaskDetail 用 team 级 events（limit 20）+ 前端 `.filter(target_id)` → team 活跃时本 task 事件被挤掉/显示不全。根因: ① 改名迁移（B40/B10）漏迁 `event.actor_type` 字符串值 + 读取侧无容错 ② 实体级过滤未下推查询层（全仓无 `/tasks/{id}/events` 端点）。处置: ① `helpers.py` `event_to_response` 加 `_coerce_actor_type`（遗留 `agent→worker`/`member→human` 映射 + 未知值 fallback `system`）② `events.py` 新增 `GET /tasks/{id}/events`（复用 `query_project_events(task_ids=[task_id])` · SQL WHERE 下推 · 权限对齐 get_task 跨 team 404）③ 前端 `client.ts` 加 `fetchTaskEvents` + `TaskDetail.tsx` 换调删前端 `.filter(target_id).slice(0,30)` 死代码。· 🟢 中型 · 2 src + 2 frontend + 4 tests · 1021 tests 零回归 · 下一站 L5 拉通（B175+B176 · counter 2）→ B177
- **P100-B177**：**backlog G-xxx 回写 + G-034/PFL-246 封存** ✅ — 触发: master-backlog G-029~G-035 七条 hook-gap 门禁只「发现→登记」没「闭环→回写」，看板 stale。根因: 只登记不回写。处置: ① G-029/030/031/032/033/035 回写真实状态（→ ✅ P100-B88/B89/B90/B91/B92）② G-034（pre-push hook 逃逸通道硬化）+ PFL-246（pre-push 只保护 master）→ 封存不追（能力层 · pre-push 审批链路随能力层封存 · 重判 P17-B1「协作层债」分类）。· 🟢 治理批 · 0 src code（master-backlog 回写 + 封存注记）· 下一站 B178（常开待命）
- **P100-B178**：**PFL-273 e2e 基建修复（429 限流 + WS 多连接根治）** ✅ — 触发: P17-B10 全量 e2e 套件 situation-view 撞 slowapi 登录限流 429 + WS live-dot flaky（挂 PFL-273 · 挡 P17-B11 dogfood）。根因: ① 全量套件 3 spec 各 beforeAll+afterAll 登录 = 6 次/run > slowapi login 5/min → 429 ② **live-dot 真根因是 ws_manager 单连接-per-actor 缺陷**（`_connections: dict[actor_id → WSClient]`，前端每页 Layout + 页面组件各开一条 WS 同 actor，`connect()` 踢旧连接 + `disconnect(actor_id)` 按 actor 误删新连接 → 无限重连振荡，非 PFL 初判的「onopen 偶发超时」）。处置: ① `playwright.config.ts` 后端 webServer 注入 `RATE_LIMIT_LOGIN=999999/minute`（镜像 tests/conftest.py）+ 删 3 处死 afterAll 登录 ② `ws_manager` 改多连接-per-actor（connect 追加不踢 · disconnect(client) 按连接身份 · 新增 send_to_client 连接级响应 · broadcast_to_actor 广播该 actor 所有连接）+ `tests/test_ws_manager.py` 7 例。· 🟠 根修 · 2 src + 4 e2e/config + 7 tests · 1030 tests 零回归 · e2e 7/7 绿 · 下一站 B179（常开待命）
- **P100-B179**：**PFL-275 e2e 残留清理（afterAll 补全 + bearer 鉴权）** ✅ — 触发: B7-B10 Playwright e2e 创建测试 task 不清理，积压 owner=None ready 残留污染 ready 队列（P17-B11 手工清 91 个后，B178 旧 afterAll 仍失效继续残留）。根因: ① 3 spec 无 afterAll（conversation/daggraph）或 afterAll 不完整（situation-view 只 cancel 根 A/X）② 旧 afterAll 从未生效——Playwright `request` fixture 按 hook 隔离，beforeAll 登录 cookie 不共享到 afterAll，GET 401 → `if (!res.ok()) continue` 静默跳过。处置: `helpers.ts` 抽 `cancelSeededTasks(request, accessToken, project)` 遍历全任务 cancel + 显式 `Authorization: Bearer` 头 · 3 spec 补 afterAll（situation-view 扩为全任务）· 另清理存量 18 条残留（6 ready + 12 in_progress）。· 🟢 治理批 · 0 src code · 4 e2e · e2e 7/7 绿 · 下一站 B180（常开待命）

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
| **P12** | **P12-B1→B52** | **52** | ✅ **全量闭环 🎉** · Harness-Driven Worker · 1O+2B 协作验证 |
| **P13** | **P13-B1→B13** | **13** | ✅ **全量闭环 🎉** · 基础设施可信度加固 |
| **P14** | **P14-B0→B15** | **16** | ✅ **全量闭环 🎉** · 从平台建造到平台使用 |
| **P15** | **P15-B0→B3** | **4** | ✅ **全量闭环 🎉** · 战略验证 · 主张 B 部分成立 |
| **P16** | **P16-B1→B13** | **13** | ✅ **全量闭环 🎉** · 机制级修自主性 · 消灭 human-as-message-bus |
| **P17** | **P17-B1** | — | 🔄 人机协作协调层 · 战略重定向（护城河 = 协作层） |
