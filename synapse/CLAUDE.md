# Synapse — 人机混合团队分布式协调平台
> 不存代码，只协调工作。Team = 人 + Worker，同等对待。最后更新：2026-07-20（P11-B15 ▶️ — PFL-034 + PFL-039 权限修复）

> 本文件是**跨角色通用纪律**——所有角色（Orchestrator / Builder / Steward）共同遵守的工程规则。
> 你的角色专属职责、工作流、能力边界 → 以 Synapse Protocol API 返回的
> `role_instructions` 为准。当两处规则冲突时，`role_instructions` 优先。
> 🔄 L5 P11-B1→B7 拉通完成（2026-07-19）— 4 项交叉引用修复 · 计数器复位

## 🚨 铁律：GlassCortex 只读

**glasscortex 目录（`../glasscortex/`）对本项目任何 Claude 会话是 READ-ONLY。**

Read/Grep/Glob ✅ — Write/Edit/Bash 修改 ❌

**为什么**：两个独立项目。Synapse "偷看" glasscortex 是为了学习开发流程经验，不是修改它。

误操作拒绝语：*"根据 synapse/CLAUDE.md 铁律，glasscortex 为只读。请切换到 glasscortex 主会话。"*

---

## 🚧 会话启动门禁（角色身份未建立前）

如果你尚未通过 Synapse Protocol API 建立角色身份（即你还没有在本次会话中
输出 🟠/🔵/⚪ 角色身份横幅），你必须拒绝以下类型的请求：

- 代码编写/修改
- 任务拆解/分配/验收
- Git 操作（commit/push）
- 任何会修改仓库文件或创建 Synapse 资源的操作

对这些请求，回复：

"""
⚠️ 本会话尚未在 Synapse 平台注册角色身份。

请先加载 Synapse Skill 并完成 Protocol API 握手。
如果你不确定怎么做 → 输入 /synapse 加载 Worker Skill。
"""

> **为什么是 CLAUDE.md 而不是 Skill**：Skill 可能不会被加载。CLAUDE.md 一定会被 Claude Code 读取——它是启动时最先进入上下文的内容之一。将门禁放在 CLAUDE.md 中，即使 Skill 完全未被调用，AI 也会拒绝在无角色状态下执行敏感操作。

---

## 工程规则

> 以下规则从 glasscortex 上百次返工中提炼，Synapse 第一天就移植。

### 1. 五层自检金字塔（每批强制）

```
L1 结构层    — 产物完整、格式正确（设计阶段：文档章节·术语·格式 / 代码阶段：lint+typecheck+build）
L2 引用层    — 引用的东西真实存在（设计阶段：交叉引用·文件路径 / 代码阶段：import·API·配置key）
L3 契约层    — 多产物间约定一致（设计阶段：PRD↔数据模型↔协议三方对齐 / 代码阶段：schema snapshot+消费者检查）
L4 场景层    — 真实使用场景走得通（设计阶段：用户故事逐步推演 / 代码阶段：端到端测试+浏览器验证）
L5 拉通层    — 全链路闭环，新人能看懂（每 2 批执行，叙事一致性+文档新鲜度+状态遍历）
```

- **五层分级矩阵**：不所有 Batch 跑全套 L1-L5。按变更类型选择性执行——纯文档 Batch 跳过 L2/L3/L4，UI 变更只做 CSS 专项 L2，后端变更跳过 L4 浏览器验证。详见 [`docs/methodology.md`](docs/methodology.md) §4 五层分级矩阵
- L1-L4 按矩阵选择性执行，结果写入 requirements-log
- L5 每 2 批强制执行，不等 Pre-flight 拦截。累积 ≥2 批未拉通 → 必须先 L5 再开下批
- L5 完成后运行 `bash tools/l5-reset.sh "Bx→By 拉通完成"` 复位计数器
- **L5 commit 不计入批次计数**：`post-commit.sh` 检测 commit message 含 `L5`/`拉通` → 跳过 `batchesSinceLastL5` 递增。L5 是同步点，不是"一批工作"——复位后的第一次递增应从下一个功能 Batch 开始
- **L5 机械门禁**：`tools/l5-gate.sh` 已接入 `.git/hooks/pre-commit`。`batchesSinceLastL5 ≥ 2` → commit 被硬阻断。操作流程：执行 L5 → `l5-reset.sh --yes` → 将复位后的 checkpoint 与功能变更 staged 在一起 → **单次 commit**（commit message 注明 L5 范围，不再拆分独立 L5 doc commit）
- **新会话启动 L5 自检（V-024 防呆）**：读到暗号/继续指令后第一步——读 `.claude/l5-checkpoint.json` → 若 `batchesSinceLastL5 >= 2` → **必须先 L5 拉通再开新 Batch**。不允许 commit 时才被动补救。MEMORY.md 暗号段应携带 L5 状态标记
- 详细检测手段和分层映射见 [`docs/methodology.md`](docs/methodology.md) §五层自检金字塔

### 2. 发现即待办

任何讨论/调研/审查中产出的 ⚠️ 发现，**同一会话内**必须：
- (a) 当场修复（小问题），或
- (b) 登记到 roadmap backlog 段（需要后续资源）

不得仅写文档不登记。"下次再说" = 遗忘。发现 = 待办。

### 3. Batch 隔离 + 会话刷新

- 每批完成后立即 commit
- **Commit 前缀必须包含项目名**：`feat(synapse): Phase N Batch M — 简短描述`。monorepo 中与 `glasscortex:` 共享 git log，不写前缀无法追溯。严禁裸 `feat(batch-N):` 或漏 Phase 编号
- 安装 commit-msg hook（从 synapse/ 目录执行）：`cp tools/check-commit-prefix.sh ../.git/hooks/commit-msg && chmod +x ../.git/hooks/commit-msg`
- 安装 post-commit hook：`cp tools/post-commit.sh ../.git/hooks/post-commit && chmod +x ../.git/hooks/post-commit`
- 下批开新会话，不在同一会话跨 Batch
- 本会话 ≥2 Batch → commit 后主动建议 `/clear` 重开
- `/clear` 前约定接头暗号，写入 memory，新会话秒级接上

### 4. 粒度控制（强制门禁）

**红线**：每批 ≤8 文件变更。不允许凭感觉估算。

**Plan 阶段机械门禁**（ExitPlanMode 前强制执行）：
1. 逐文件列出变更清单（新建/修改/删除）+ 计数
2. ≤8 → 放行。9-12 且全部机械变更（≤3 行/文件）→ 可申请豁免，须在 plan 中注明。>12 → 必须拆
3. 用户批准后文件清单锁定，发现新文件需要改 → 新 Batch

**同议题连续层合并豁免**：同一议题内的数据模型→Service→API 三层连续实现，若满足以下全部条件，应合并为一个 Batch 而非拆分为三个微型 Batch：
- 三层之间无跨议题接口依赖
- Schema/接口变更仅在本议题内传播
- 合并后总文件数 ≤8

> **Why**：B28(数据)+B29(Service)+B30(API) 拆为 3 个 🟢 微型 Batch，每个产生相同的 6-8 文件文档闭环 overhead。合并为一个 🟡 标准 Batch 可减少 67% 流程 commit。P100-B70 流程瓶颈修复。

> 背景：P4-B9 计划 8 文件 → 实际 15 文件（+87%），根因是缺此门禁。
> 详见 memory: [[batch-size-precommit-gate]]

### 5. 文档闭环

需求→执行→验证→日志，四步闭环。每批完成即时更新：
- `docs/roadmap.md` — 宏观进度
- `docs/requirements-log.md` — 微观交付记录（含 L1-L4 breakdown）
- `docs/daily/YYYY-MM-DD.md` — 日报（同日追加，跨天新建）

### 6. 日报铁律

- **同日追加**：同一天的工作追加到同一日报文件，不新建
- **跨天新建**：日期变更后创建 `docs/daily/YYYY-MM-DD.md`
- **忘了就补**：从 `git log` 反推，补写的日报注明「补」
- **机械门禁**：`tools/check-docs.sh` 检查昨天日报是否存在，缺失告警（不阻断，允许补写）
- **来源**：从 GlassCortex CLAUDE.md §6 移植

### 7. Batch 启动门禁

哪怕改 1 行：建 Batch → 跑门禁 → 登记 roadmap → 动手。零例外。

**机械载体**：[`docs/execution-checklist.md`](docs/execution-checklist.md) — 启动前/编码中/提交前/提交后/Phase 结束 五段式 checklist。V-005 防呆首项：「即使是 ≤2 行改动也必须走完整流程」。

### 8. 即时澄清

模糊点立刻问，不靠假设推进。AI 静默走错方向 10 步比开口问 1 句贵 100 倍。

### 9. 流程共建

相同错误不超过 2 次。发现流程漏洞/低效模式/重复返工 → 主动提案改进。AI 不只是执行者，也是流程 owner。
每次违纪登记到 `docs/process-violations.md`（V-NNN 编号 + 计数递增）。同一规则累计 2 次 → 🔴 升级 + 必须落地机械防呆。

**违纪闭环**（对标 L5 门禁）：
- **机械门禁**：`make check-violations`（已接入 `make check` 管道）。硬阻断：距上次违纪回顾 ≥5 批。软警告：复发 ≥3 项 / 待防呆 ≥10 项。
- **回顾触发**：Phase 结束 OR 累积 5 批 → 必须执行违纪回顾（逐项审查 V-NNN、评估防呆可行性）。
- **复位流程**：`bash tools/violations-review.sh "<描述>"` → checkpoint 复位 → commit。
- **防呆路线图**：见 `docs/process-violations.md` §防呆可行性评估（P0 本批 / P1 下批 / P2 中期）。
- **流程基建路线图**：见 `docs/process-infrastructure.md`（15 项 PI 能力，本地原型→分布式产品化）。发现新流程需求/分布式缺口时即时追加 PI 条目，每 Phase 结束 review PI 状态。本文档是活文档，不等"以后再说"。

### 10. 讨论即登记（Discussion → Backlog）

**用户说的每一句方向性讨论，都是未打磨的 PRD 条目。** 不登记的讨论 = 没发生过的讨论。

**触发句式**（非穷举）：
- 「应该…」「以后要…」「我们后面…」「最终…」「长期来看…」
- 「这个功能需要…」「理想情况下…」「XX 阶段应该…」
- 用户描述了一个当前没做但未来需要的功能/策略/机制

**AI 必须当场执行**：
1. 按[路由矩阵](#-路由矩阵)判断讨论类型 → 登记到对应目的地（backlog/pitfalls/lessons/P100）
2. 在 session memory 的「🧭 战略决策登记」段按标准格式记录
3. 不需要问用户「要不要登记」——默认登记，用户觉得不需要再删

**Session memory 🧭 段标准格式（5 列）**：每个 session checkpoint 文件必须包含：
```
## 🧭 战略决策登记
| D-ID | 内容摘要 | → 目的地 | 目标 ID | 状态 |
|------|---------|----------|---------|:--:|
| D-P7-001 | Project URL 字段需求 | Phase Backlog | P7-001 | ✅ |
```

**强制字段说明**：
- `D-ID`: 讨论编号，格式 `D-<Phase>-<序号>`（如 `D-P7-001`, `D-P8-003`）。历史遗留的 `D-XXX` 格式逐步迁移。
- `内容摘要`: 一句话（≤40 字），下个会话读到就能还原
- `→ 目的地`: 路由目标（Phase Backlog / P100 / pitfalls / lessons / P8 设计原则 / 远景设计）
- `目标 ID`: 在目的地中的实际 ID（如 P7-005, G-001, P-013, LL11），或 memory 文件名
- `状态`: ✅ 已登记 / 🟡 待分类 / 🔴 孤儿（目标不存在）/ ⬜ 未启动 / ❌ 已关闭

**路由矩阵**：不同类型的讨论去不同的地方。判定原则：当一条讨论同时匹配多个路由 → 选最接近执行层的那个。

| 讨论模式 | → 目的地 | ID 格式 | 判断关键词 |
|---|---|---|---|
| 战略方向/路线决策 | Phase Backlog (`docs/master-backlog.md`) | P{N}-XXX | "应该" "以后要" "最终" "长期" "XX阶段" |
| 治理/工具链/防呆 | P100 (`memory/synapse-p100-governance.md`) | G-XXX | "make check应该" "工具链需要" "门禁" "防呆" |
| 技术踩坑 | pitfalls (`docs/pitfalls.md`) | P-NNN | "刚才有个坑" "注意" "小心" "不要" |
| 可迁移方法论 | lessons (`docs/lessons-learned.md`) | LL# | "通用" "可迁移" "模式" "原则" |
| 功能细节/实现想法 | master-backlog P2 | S-XXX | "可以加" "支持" "优化" |
| 即时行动项 | Current Batch Task | Task ID | "别忘了" "记得" "补刀" "顺手" |

**机械门禁**：`tools/check-discussions.sh` 扫描所有 session memory 的 🧭 段，检测孤儿 D-ID 和未闭环条目。接入 `make check-discussions`（警告级，不阻断）。详见 P100 G-005。

**会话启动自检**：新会话读到 session memory 时，AI 必须检查所有 D-XXX 条目是否都有对应的 backlog 项。孤儿条目（有 D-ID 无 P-ID）→ 立即补登记。

> **Why**：P6 闭环后发现 4 个战略讨论蒸发（P7-001~004），根因是「讨论→session memory 摘要→下个会话丢失颗粒度」。代码扫描发现的 56 项全部清零，用户讨论反而漏了——因为只有「扫描→登记」管道，没有「讨论→登记」管道。
> **P100-B14**：G-005-a `check-discussions.sh` 实现机械孤儿检测，G-005-b 🧭 段模板标准化为 5 列 D4 格式。

### 11. Phase 治理（Phase Governance）

**Phase 是战略意图的容器，不是文件夹。** 新建 Phase 必须通过五维度检查（主题一致性/自然断点/规模阈值/工作性质/战略意图）。详见 [`docs/phase-criteria.md`](docs/phase-criteria.md)。

**编号规范**：
- 功能 Phase：P1-P99，Per-Phase 独立 Batch 编号（P8-B1, P8-B2, ...）
- 治理 Phase：P100-P199，持续开放不关闭（P100-B1, P100-B2, ...）
- 历史遗留的全局 Batch 编号（B1-B56）已归档，新 Phase 必须使用 Px-By 格式

**新会话自动加载**：CLAUDE.md 在 SessionStart hook 中自动加载 → Phase 标准随 CLAUDE.md 进入每个新会话。AI 在规划新 Phase 或新 Batch 时，必须先对照 `docs/phase-criteria.md` 五维度检查。

**门禁**：`make check-phase`（已接入 `make check`）在每次提交前验证 Phase 治理合规。

> **Why**：P7 建立时发现历史 Phase 划分混乱——P7 原定义（"Post-P6 补漏 + 战略方向落地"）不通过五维检查。Phase 标准正式化防止重蹈"把 Phase 当文件夹用"的覆辙。

### 12. 批次顺序前置校验（Batch Sequence Gate）

**批次必须顺序执行，跳号必须显式确认。** 这是 P100-B13 跳号事故的防呆补丁。

**轨道指针**：每条轨道在 `tracks/<project>.md` 的 frontmatter 中维护两个指针：

```yaml
last_batch: P100-B14    # 最后完成的 Batch
next_batch: P100-B15    # 下一个应执行的 Batch
```

**AI 执行协议**：当用户说「继续 Px-By」时，AI 必须：

1. **读 track 文件** — 读出 `last_batch` 和 `next_batch`
2. **顺序校验**：
   - `By == next_batch` → 直接执行 ✅
   - `By > next_batch`（跳号）→ **必须确认**：「⚠️ last_batch 是 {X}，下一批应为 {next_batch}。确认跳过 {跳过的批次} 直接做 {By}？」
   - `By <= last_batch`（重复）→ 提示该批已完成
3. **完成更新**：Batch 完成后，更新 track 的 `last_batch` 和 `next_batch`
4. **跳号登记**：如果用户确认跳号 → 跳过的编号永久作废 → 在 track 中标注跳号 → 剩余待办项重编号到 `next_batch` 之后

**会话启动自检**：新会话启动时，AI 读取 MEMORY.md 顶部的轨道表 → 找到对应 track → 读取 `last_batch`/`next_batch` → 确认自己的执行起点。如果用户未指定具体 Batch，AI 应从 `next_batch` 开始。

> **Why**：P100-B14 会话中，用户说「继续 P100-B14」，AI 直接执行了——跳过了尚未完成的 B13（P8 遗留技术债）。根因是没有机械指针校验：track 里没有 `last_batch`，AI 没有"下一批应该是哪个"的判断依据。编号一旦 commit 不可逆——B13 永久跳号，技术债被迫重编号为 B15。

### 13. Plan 分级制度（Plan Sizing）

**Plan 模式按变更规模分三级，不所有 Batch 一律 EnterPlanMode。**

| 级别 | 条件 | Plan 方式 | 预计轮数 |
|:---:|------|---------|:-------:|
| 🟢 微型 | ≤2 文件 + 无接口/协议变更 | inline 口头 Plan，1 轮确认，**不 EnterPlanMode** | 1 |
| 🟡 标准 | 3-4 文件 或 接口/协议变更 | EnterPlanMode → 精简 Plan（改哪些 + 影响谁） | 2 |
| 🔴 大型 | ≥5 文件 或 架构变更 | EnterPlanMode → 完整 Plan + 影响分析 + Risk Assessment | 3 |

**判断流程**：
1. Plan 阶段逐文件列变更清单（与 §4 文件计数共用）
2. 判断接口影响：有没有改 API schema / 数据模型 / 协议定义？
3. 匹配级别 → 执行对应 Plan 模式

**Scout→Execute 分级重评**：Plan 分级不是一次性判断。Scout（代码探索/依赖分析/影响评估）阶段可能发现变更范围远超预估。**发现范围超过原分级阈值 → 必须 stop + 重走 Plan 流程**（重新分级、重新 EnterPlanMode），不得将 Scout 发现的新增变更直接并入执行。

**重评触发信号**（满足任一即触发）：
- 文件数超过原分级阈值（🟢→≥3、🟡→≥5）
- 新增 P-XXX / S-XXX / LL / V-XXX 登记项 ≥3 条
- 发现需要修改原 plan 未覆盖的文件类别（如原 plan 只覆盖 doc，Scout 后发现需要改代码）
- 发现接口/协议/数据模型变更（原 plan 未覆盖）

**执行协议**：
1. Scout 结束后 → 逐文件列出实际变更清单（复用 §4 文件计数）
2. 对比初始 Plan 的分级阈值 → 判断是否跃迁
3. 跃迁 → **stop**，口头告知用户「⚠️ Scout 发现范围从 🟢/🟡 跃迁到 🔴，需要重新 EnterPlanMode」，然后重走 Plan 流程
4. 不跃迁 → 继续执行

**与 V-020 的关系**：V-020（Scope-shift 未重新分级）是本规则被违反时的违纪登记。`tools/check-plan-mode.sh` §V-020 段提供机械检测（staged 文件数 + 新增条目数），但机械检测是最后防线——AI 应在 Scout 阶段主动重评，不等 hook 拦截。

**与 §4 粒度控制的关系**：分级管「Plan 怎么画」，粒度控制管「Batch 拆多大」。两套正交：🔴 大型 Plan 仍需通过 ≤8 文件门禁（拆为多个 Batch 执行）。微型 Batch 的 EnterPlanMode 往返可能比编码本身更长——Plan 的核心价值是「想清楚再动手」，当变更简单到没有歧义时，Plan 形式简化，核心理念不省。Scout→Execute 重评是这两套机制之间的桥梁——Scout 发现规模跃迁时，分级先变，粒度再跟着拆。

**同议题合并自动升级**：按 §4 合并豁免将数据+Service+API 三层合并时，Plan 分级自动从 🟢→🟡（合并后文件数 ≥3 且含接口变更）。不额外增加 Plan 轮数——🟡 标准 Batch 的 2 轮 Plan 足以覆盖三层设计。

> **Why**：从 GlassCortex 审计（2026-07-06）移植。GlassCortex 跑了 ~190 Batch 后沉淀出分级标准——不是所有变更都需要完整的 EnterPlanMode 流程。Synapse 当前所有变更一律 EnterPlanMode，微型 Batch（修 typo/加日志/改常量）的 Plan 往返开销 > 编码开销。

### 14. 依赖升级纪律（Dependency Upgrade Discipline）

**`pip install` 或 `requirements.txt` 变更后，必须立即全量门禁重跑。** 不允许"只加了一个依赖，先不跑门禁"或"依赖没变代码，跳过 check"。

**执行协议**：
1. 任何 `pip install` / `requirements.txt` / `package.json` 变更 → 视为代码变更
2. 变更后立即 `make check`（Python 全量门禁）+ `make check-frontend`（前端门禁，如涉及）
3. 门禁 failure → 回退依赖变更或修复 breakage，不允许带病提交
4. 依赖版本锁定在 `requirements.txt`（Python），不依赖"最新版一切正常"的假设

> **Why**：从 GlassCortex CLAUDE.md 移植。依赖升级是最常见的"看起来无害其实爆炸"的操作——新版本可能改 API、改默认值、引入 breaking change。门禁是最后的防线，跳过它 = 裸奔。

### 15. 流程紧急修复（Process Emergency Fix）

**流程/治理缺陷满足以下任一条件时，不受「per-Phase 渐进消化」约束，应立即触发 P100 紧急批：**

1. **同一规则违规 ≥3 次**（超过 §9 的 2 次升级阈值）
2. **正在持续造成资产损失**（知识蒸发、数据丢失、重复返工）
3. **阻断后续 Phase 的正常执行**

紧急批编号为 P100-Bx。与 per-Phase 消化的区别：**前者止血，后者保养。**

**执行协议**：
- 任何会话中发现上述条件之一 → 立即在当前会话启动 P100 紧急批
- 紧急批不受 Phase 边界约束，优先级高于当前 Phase 产品批次
- 紧急批完成标准：止血措施落地 + 防呆门禁上线（不只是文档登记）
- 紧急批完成后，在 track 中复位 `next_batch` 回原 Phase

> **Why**：B28-B40 共 13 批 Dogfooding，零条 pitfalls/lessons 登记——流程缺陷正在持续造成知识资产蒸发。同一错误发生 13 次远超 §9 的 2 次阈值，但因为没有紧急修复机制，直到 13 批后才被发现。按 per-Phase 渐进消化意味着要等到 P9 结束才能修这个漏洞，期间还会产生更多蒸发。流程紧急修复机制让治理问题在发现时立即止血，不等 Phase 边界。

---

## 协作纪律

1. **逐文件验证** — 写完一个文件立刻验证，不等攒批
2. **上下文预估** — commit 后主动检查是否需要 /clear，不等用户感觉卡了才反应
3. **接头暗号（机械执行）** — /clear 前必须完成四步：
   - ① 约定简短暗号（格式：`继续 Synapse <下一站方向>`）
   - ② 写入 memory checkpoint 文件（`synapse-session-YYYY-MM-DD.md`），包含以下必填段：
     - 本次做了什么 + 下一站方向 + 暗号
     - 🧭 战略决策登记（按 §10 格式）
     - 🔒 角色边界自审（按当前角色选择对应模板）：

**Builder 版**：
| 检查项 | 结果 |
|:---|:---:|
| 本会话是否尝试过创建 Task？（O 的职责，B 不应做） | ✅/❌ |
| 本会话是否尝试过分配 Task 给其他 Worker？（O 的职责） | ✅/❌ |
| 本会话是否尝试过验收/打回 Task？（O 的职责） | ✅/❌ |
| 本会话是否因权限不足收到过 403？ | ✅/❌（如❌，附 endpoint） |
| CLAUDE.md 中是否有规则与 role_instructions 冲突？ | ✅/❌（如❌，附具体规则） |

**Orchestrator 版**：
| 检查项 | 结果 |
|:---|:---:|
| 本会话是否直接修改了代码/写了实现？（B 的职责，O 不应做） | ✅/❌ |
| 本会话是否认领并执行了 Task？（B 的职责） | ✅/❌ |
| 本会话是否提交了 evidence？（B 的职责） | ✅/❌ |
| 本会话是否因权限不足收到过 403？ | ✅/❌（如❌，附 endpoint） |
| CLAUDE.md 中是否有规则与 role_instructions 冲突？ | ✅/❌（如❌，附具体规则） |

**Steward 版**：
| 检查项 | 结果 |
|:---|:---:|
| 本会话是否直接修改了代码/写了实现？（B 的职责，S 不应做） | ✅/❌ |
| 本会话是否创建/分配了 Task？（O 的职责，S 不应做） | ✅/❌ |
| 本会话是否因权限不足收到过 403？ | ✅/❌（如❌，附 endpoint） |
| CLAUDE.md 中是否有规则与 role_instructions 冲突？ | ✅/❌（如❌，附具体规则） |

> ✅ = 行为符合角色边界，❌ = 出现越界
   - ③ 更新 MEMORY.md 顶部索引（暗号作为第一行，确保下个会话首条命中）
   - ④ 新会话首条说出暗号 → AI 读 memory → 秒级接上，免重新同步
   - **机械防呆**：`tools/session-checkpoint.sh` 检查 checkpoint 是否存在、是否含暗号、是否今天更新
4. **文档索引** — 新增 doc 文件必须更新 CLAUDE.md 项目结构段
5. **窗口主动评估** — 每次回复末尾评估上下文窗口剩余空间。跨 3+ 话题或产出了大量文件/讨论后 → 主动提醒"窗口可能不足，建议 checkpoint + /clear"。不等用户感觉卡了才反应。评估方法：估算本轮对话已消耗的 token 量级（文件读写数×平均行数 + 讨论轮次×估算），判断是否接近缓存边界（~5 分钟窗口）

---

## 项目结构

```
synapse/
├── CLAUDE.md              ← 本文件（AI 入口）
├── README.md              ← 人类入口
├── PITCH.md               ← 项目介绍（电梯/咖啡/晚餐分层 — 对外交流用）
├── CONTRIBUTING.md        ← 协作规范
├── docs/
│   ├── prd.md             ← 产品需求文档 ✅
│   ├── methodology.md     ← 开发工作流方法论（核心流程·文档闭环）✅
│   ├── methodology-reference.md ← 方法论参考附录（五层金字塔·反模式·SMG·迁移策略）🆕 P100-B75
│   ├── roadmap.md         ← 开发路线图（宏观）
│   ├── requirements-log.md← 需求日志（微观，每批 L1-L4）
│   ├── data-model.md      ← 核心数据模型（设计原则·ER·关系矩阵·决策）✅
│   ├── data-model-entities.md ← 实体定义（23 实体属性表·状态机·约束）🆕 P100-B74 · 🔄 P100-B78
│   ├── protocol.md        ← 人机协调协议 ✅
│   ├── architecture.md    ← 系统架构 + 技术选型 ✅
│   ├── security-model.md  ← 多租户权限模型 ✅
│   ├── security-model-appendix.md ← 安全模型附录（API Key蓝图·ADR·刷新·契约）🆕 P100-B77
│   ├── onboarding.md      ← 用户/Agent 接入指南 ✅
│   ├── onboarding-api-reference.md ← 接入指南附录（API详细参考·端点速查·FAQ·SDK）🆕 P100-B79
│   ├── glossary.md        ← 术语表 ✅
│   ├── lessons-learned.md ← 可迁移通用经验 ✅
│   ├── phase-criteria.md   ← Phase 划分标准（五维度+生命周期）✅
│   ├── execution-checklist.md ← 执行 Checklist（V-005 防呆）✅
│   ├── pitfalls.md        ← 技术踩坑注册表 ✅
│   ├── process-violations.md← 流程违纪登记（V-NNN·防呆状态）✅
│   ├── process-infrastructure.md← 流程基建路线图（本地原型→分布式）✅
│   ├── mvp-boundary.md    ← MVP 边界定义 ✅
│   ├── agent-comparison.md← Agent 效能对比追踪 ✅
│   ├── research/
│   │   └── glasscortex-audit.md ← GlassCortex 全盘审计 ✅
│   ├── decisions/         ← ADR（一条一文件）
│   ├── integrations/      ← 外部工具集成规范
│   ├── templates/         ← Worker Skill 模板源文件
│   │   ├── _protocol.md        ← L1 平台协议（启动流程·VDD·API·错误处理·授权通道）🆕 P11-B2
│   │   ├── _common.md          ← → _protocol.md 薄重定向（已废弃内容迁移至 _protocol.md）
│   │   ├── _project.md         ← 项目上下文 + 技术栈
│   │   ├── _env.md             ← 环境变量模板
│   │   ├── role-orchestrator.md← 编排者（规划/验收）
│   │   ├── role-builder.md     ← 构建者（编码/实现）
│   │   ├── role-steward.md     ← 协理（审查/安全/反馈）
│   │   ├── conventions-frontend.md ← L2b 前端编码约定 🆕 P11-B4
│   │   ├── conventions-backend.md  ← L2b 后端编码约定 🆕 P11-B4
│   │   ├── _task-current.md    ← 当前任务占位（二期动态生成）
│   │   └── synapse-client/     ← Claude Code 客户端 Skill（P9-B22）
│   │       └── SKILL.md        ← 薄协议层：Worker 协议 + 启动引导
│   ├── plans/             ← 详细批次设计
│   └── archive/           ← 历史归档
├── tests/                   ← E2E 测试 ✅
│   ├── conftest.py          ← 共享 fixtures
│   ├── test_worker_lifecycle.py
│   ├── test_analysis.py     ← AnalysisRecord E2E
│   ├── test_continuity.py
│   ├── test_error_cases.py
│   ├── test_oauth_flow.py   ← OAuth E2E
│   └── test_task_flow.py
├── tools/
│   ├── check-docs.sh           ← 文档门禁（新鲜度+验证覆盖+L5间隔）✅
│   ├── check-batch-numbers.sh  ← Batch 编号连续性检查 ✅
│   ├── check-lessons.sh        ← 经验编号连续性检查（LRN 防呆）✅
│   ├── check-comments.sh       ← 代码注释质量扫描 ✅
│   ├── check-contracts.sh      ← API schema 快照 + 变更分析 ✅
│   ├── check-line-count.sh     ← 文件行数上限拦截 ✅
│   ├── check-schema-audit.py   ← Schema AuditFields 继承检查 ✅
│   ├── check-schema-audit.sh   ← Schema audit 门禁（make check 接入）✅
│   ├── l5-gate.sh              ← L5 机械门禁（pre-commit hook）✅
│   ├── l5-reset.sh             ← L5 计数器复位 ✅
│   ├── l5-b47-b50-verify.py    ← L5 B47-B50 拉通验证脚本 ✅
│   ├── check-violations.sh     ← 违纪门禁（复发检测+防呆统计+回顾逾期阻断）✅
│   ├── violations-review.sh    ← 违纪回顾复位 ✅
│   ├── post-commit.sh          ← Batch 计数 + L5 同步 ✅
│   ├── session-checkpoint.sh   ← 会话 checkpoint 验证 ✅
│   ├── check-commit-prefix.sh  ← Commit 前缀门禁 ✅
│   ├── check-phase.sh          ← Phase 治理门禁（G-004）✅
│   ├── check-discussions.sh    ← 讨论→登记管道孤儿 D-ID 检测（G-005-a）✅
│   ├── check-plan-mode.sh      ← Plan Mode 入口检测（V-003 防呆）✅
│   ├── check-doc-curl.sh       ← Doc curl 块结构校验 + Live 模式 subprocess E2E（S-024b）✅
│   ├── db-backup.sh            ← 数据库备份（保留最近 20 个）✅
│   ├── db-restore.sh           ← 数据库恢复（恢复前自动备份）✅
│   ├── seed-synapse-project.py ← 首个 Project 播种（--dry-run / --sync）✅
│   ├── dev-login.py            ← 开发环境登录辅助 ✅
│   ├── cleanup-b24-agents.py   ← B24 残留 Agent 一次性清理 ✅
│   └── generate-skill.sh       ← Skill 包生成器（Claude + Codex 双客户端）✅
├── .claude/
│   ├── settings.json              ← SessionStart hook ✅
│   ├── l5-checkpoint.json         ← L5 追踪 ✅
│   └── violations-checkpoint.json ← 违纪回顾追踪 ✅
└── src/                    ← FastAPI 项目 ✅
│   ├── main.py             ← App factory + lifespan
│   ├── config.py           ← pydantic-settings
│   ├── db.py               ← SQLAlchemy async engine
│   ├── dependencies.py     ← FastAPI Depends
│   ├── auth.py             ← JWT + API Key + project_key
│   ├── permissions.py       ← 统一权限引擎（PERMISSION_MAP + require_permission）🆕 P11-B8
│   ├── exceptions.py       ← Structured errors
│   ├── models/             ← SQLAlchemy ORM (27 entities)
│   ├── schemas/            ← Pydantic request/response
│   ├── api/                ← REST endpoints (routers/)
│   ├── services/           ← Business logic (event_store + analysis)
│   └── utils/              ← ID generator + JSON helpers
├── frontend/               ← React 前端（Vite + TypeScript）✅
├── alembic/                ← Migration infrastructure ✅
├── alembic.ini             ← Alembic 配置 ✅
├── mypy.ini                ← mypy 类型检查配置（V-004 防呆）✅
├── pytest.ini              ← Pytest 配置 ✅
├── requirements.txt        ← Python deps ✅
├── Dockerfile              ← Python 3.12 image ✅
├── docker-compose.yml      ← Local dev setup ✅
├── .env.example            ← Dev env template ✅
├── .gitignore              ← Python + SQLite + IDE ✅
├── data/                   ← SQLite persistence (gitignored) ✅
```

---

## 当前状态

- P11-B10 ✅：模板适配 — SYNAPSE_AGENT_ID→SYNAPSE_WORKER_ID · 3 files · 纯机械替换
- P11-B12 ✅：阻断修复 — project_key + orchestrator + 角色绑定 + 模板修复 · 7 files · DB 验证通过
- P11-B13 ✅：环境搭建 — 双 Worker + Dogfood Task + Skill 生成 · 5 项发现闭环 · generate-skill.sh bugfix
- P11-B14 ✅：狗粮全链路验证 — Orchestrator + Builder 双终端 · Task 全生命周期走通 · 8 项摩擦点 + 2 项违纪 · Worker 名称富化上线
- P11-B15 ▶️：权限修复（PFL-034 + PFL-039） — assign_task + verify guard 从 require_role 切换到 require_permission · 3 code files + 2 doc · PFL-040 Swagger token 登记
- P11-B14a ✅：Bootstrap 端点 + 文档同步 — GET /v1/bootstrap (sh+json) · 3 new files + 3 modified · 18 tests · 623 passed 零回归
- P11-B9 ✅：接线 + 项目发现 — 2端点require_permission接线 + GET /workers/me/projects + Protocol project_key鉴权 · 5 files · 605 tests
- P11-B8 ✅：地基 — project_key + 权限引擎 + PENDING修复 · 5 files · 605 tests
- P11-B7 ✅：串联就绪审查 — 🚧停止点·7 维前置验证通过 · GO → B8 实战
- 🔄 **L5 P11-B8→B10 拉通 ✅** — roadmap.md P11 段 B8-B10 计划→实际同步 · 3 项交叉引用修复 · 计数器复位
- P11-B6 ✅：Skill 生成管道闭环 — conventions读取路径修复 + --from-api模式 + D-P11-010决策落地
- P11-B5 ✅：项目管理增强 — Projects始终可见+角色分配UI+约定配置 · 8 files
- P11-B4 ✅：L2b 约定层+生成管线适配 · L5 P11-B1→B4 全量拉通 🎉 — Skill 模块化前置 4 批全量闭环
- P11-B3 ✅：Skill 模板方法论升级 + architecture.md §4.1 修复 — 三角色操作法(拆解+Evidence+工具链) · ADR-006 G9 闭环
- P11-B2 ✅：ADR-006 L2/L3 观测 + 服务端 — _protocol.md + check-role-isolation.sh + Steward + role_source
- P11-B1 ✅：ADR-006 L0/L1 围栏落地 — 三角色负面清单 + SKILL.md 硬门禁 + CLAUDE.md G6 门禁
- P10：架构升级 B1-B47 ✅ · 🎉 **全部 8 议题闭环 · 47 批**
- P9：产品主线 B1-B100（100 批）✅ · 🎉 全量闭环
- P100：治理段 B1-B84 ✅ · 🎉 暂告段落

**最近批次**：
- **P11-B10**：模板适配 ✅ — SYNAPSE_AGENT_ID→SYNAPSE_WORKER_ID · 3 files · 纯机械替换 · 零残留
- **P11-B9**：接线 + 项目发现 ✅ — 2端点require_permission接线 · GET /workers/me/projects · Protocol project_key鉴权 · 5 files · 605 tests
- **P11-B8**：地基 ✅ — project_key + 权限引擎 + PENDING修复 · 5 files · 605 tests
- **P11-B15**：权限修复 ✅ — PFL-034 assign_task + PFL-039 verify guard require_role→require_permission · PFL-040 Swagger token 登记 · 1 new test
- **P11-B7**：串联就绪审查 ✅ — 🚧停止点·7维前置验证·全链路VAR管道·判定GO → B8实战
- **P11-B6**：Skill 生成管道闭环 ✅ — conventions读取路径修复 · generate-skill.sh --from-api · D-P11-010决策落地 · 3 files
- **P11-B5**：项目管理增强 ✅ — Projects始终可见+ProjecDetail(Info/Roles/Conventions)+role API接线 · 8 files
- **P11-B4**：L2b 约定层+生成管线 ✅ — conventions-frontend/backend.md 🆕 · generate-skill.sh L1/L2 适配 · architecture.md L2b 补全 · L5 P11-B1→B4 全量拉通 🎉
- **P11-B3**：Skill 模板方法论升级 ✅ — 三角色操作法(拆Task+Evidence+工具链) · architecture.md §4.1 L1/L2 架构图修正 · 4 files · ADR-006 G9 闭环
- **P11-B2**：ADR-006 L2/L3 观测 + 服务端 ✅ — _protocol.md 合并+check-role-isolation.sh+VALID_ROLES Steward+role_source · 4 files · ADR-006 G5/G8 闭环
- **P100-B81**：文档全局刷新 ✅ — master-backlog S-036✅+统计 · roadmap B61-B80补登记 · requirements-log B76-B80补 · daily B78-B80追 · 含 post-commit.sh L5豁免修复 · 7 files
- **P100-B80**：S-036 security-model 全量对齐审计 ✅ — 8 项 doc↔code drift 修复 · 60→59 事件类型 · §8 传输安全诚实化 · 3 files
- **P100-B79**：onboarding.md 拆分 ✅ — §3.1-3.8+§5+§6+Appendix→onboarding-api-reference.md · 751→273行 · 4 files
- **P100-B78**：data-model.md 实体补齐 ✅ — 议题⑤⑥ 4实体文档化 · 19→23实体 · S-060闭环 · 4 files
- **P100-B77**：security-model.md 拆分 ✅ — §6+§10-12→security-model-appendix.md · 595→499行 · S-062 ⬜→✅ · 6 files
- **P100-B76**：S-061 architecture.md 授权管道补齐 ✅ — §5.4 三层授权模型+AuthorizationRequest+Worker闭环 · v2.0→v2.1 · 6 files
- **P100-B75**：methodology.md 拆分 ✅ — 五层金字塔+SMG+反模式等→methodology-reference.md · 761→399 行 · check-docs.sh V-011 扩展 · 4 files
- **P100-B74**：data-model.md 拆分 ✅ — §3 实体→data-model-entities.md · 1032→285 行 · check-docs ERROR 清除 · 3 files
- **P100-B73**：Plan 清理 + 阈值升级 + Backlog 补日期 ✅ — 17 plan→archive · >800 WARNING→ERROR · S-060/S-061/S-062 补📅
- **P100-B72**：G25 文档膨胀治理 + G26 议题编号自洽校验 ✅ — methodology.md §5.6 文档生命周期 · check-docs.sh 文档行数扫描 · check-issue-numbers.sh 三方对齐校验 · tracks/synapse.md P10段头修复 · 5 files
- **P10-B46**：L5 拉通议题⑦ + P10 post-完成整理 ✅ — 6 L5发现修复 · architecture.md v2.0 · worker-admin-interaction-flow.md 四通道 · P10 全量闭环 🎉
- **P10-B45**：议题⑦ WebPush 前端+API ✅ — subscribe/unsubscribe 端点 · Service Worker · usePushNotification hook · authorization_service hook · 8 files · 议题⑦ 全链路闭环 🎉
- **P10-B44**：议题⑦ WebPush 后端 ✅ — UserPushSubscription 模型 + VAPID 配置 + notify_webpush() · 10 files · 604 tests 零回归
- **P10-B43**：议题⑧ 收尾 ✅ — L5 B41→B43 拉通 · data-model.md §3.5 补齐 · 议题⑧ 闭环 🎉 · 6 files · 604 tests 零回归
- **P10-B42**：议题⑧ 前端 Phase 编号显示 ✅ — 组合 "P10-B42" 徽章 + auto-fill · 4 files · 604 tests 零回归
- **P10-B41**：议题⑧ Phase 编号自动派生 ✅ — create_batch() auto-derive · 1 file · 604 tests
- **P10-B40**：议题⑧ Phase/Sprint 模式 ✅ — S-059 · use_phase_mode + current_phase · 8 files · 604 tests
- **P10-B37**：议题 ⑥ API 层 ✅ — 9 端点 (保护报告 CRUD+run · 熔断器查询+复位 · 决策审计查询) · schemas/protection.py · 3 新 router · 8 files · 604 tests 零回归 · 议题 ⑥ 全链路闭环 🎉
- **P10-B36**：议题 ⑥ Service 层 ✅ — protection_service + circuit_breaker_service + decision_audit_service · authorization_service DecisionAudit 集成 · 7 files · 602 tests (+45)
- **P10-B35**：议题 ⑥ 数据模型 ✅ — ProtectionReport + CircuitBreaker + DecisionAudit 三张新表 · 6 枚举 + 5 EventType · 3 ID 前缀 · 7 files · 559 tests · 议题 ⑥ 启动
- **P10-B34**：议题 ⑦ Webhook + L5 补缺 ✅ — Project.webhook_url · notify_webhook() · expire/cancel WS push 对称 · 7 files · 议题 ⑦ 🟡 3/4
- **P10-B33**：议题 ⑦ Email 通知 ✅ — notification_service.py + auth_request_notification 模板 · 4 files · 557 tests
- **P10-B32**：议题 7 通知通道 WS Push ✅ — authorization_service WS push · ws.py auto-subscribe · SKILL.md 双通道 · worker-admin-interaction-flow.md 新建 · 5 files · 557 tests · 议题 7 🟡 (WS Push done · Email/WebPush/Webhook ⬜)
- **P10-B31**：S-065 403 拦截器 + Agent 客户端授权闭环 ✅ — 6 files · 557 tests 零回归 · Worker 202→poll→approve→retry 全链路 · 议题 5 A2A 闭环 🎉
- **P100-B70**：流程瓶颈修复 ✅ — L5 单 commit 工作流 · 同议题连续层合并豁免 · PI-16 登记 · 7 files · 557 tests 零回归
- **P100-B71**：V-023 防呆 v2 + V-024 P1 ✅ — l5-reset.sh 证据质量门禁（长度+路径+动词 三关）· session-checkpoint.sh L5 状态输出 · V-023 🟢 闭环
- **P10-B29**：议题 5 A2A Service 层 ✅ — conversation_service.py · 消息 CRUD + @mention 解析 + handoff 管道 · 2 files · 559 tests (+34)
- **P10-B28**：议题 5 A2A 数据模型 ✅ — task_worker_conversation 表 + ConversationMessageType 枚举 + Schema + Migration · 8 files · 523 tests (+14)
- **P10-B27**：议题 4 收尾 ✅ — data-model.md §3.13-3.14 Workflow/WorkflowRole 实体补齐 · ER/关系矩阵/ID 表 · L5 B24→B27 拉通 · 5 files (+3 日期同步) · 511 tests 零回归 · 议题 4 完整闭环 🎉
- **P10-B26**：议题 4 API 路由层 ✅ — 8 端点 · require_role("admin") 守卫 · 3 files · 511 tests (+16) · 议题 4 全链路闭环 🎉
- **P10-B25**：议题 4 Schemas + Service 层 ✅ — Workflow CRUD + WorkflowRole CRUD + EventStore 集成 · 4 files · 493 tests (+18)
- **P10-B24**：议题 4 数据模型 ✅ — Workflow + WorkflowRole 表 · ProjectRole 枚举 · Migration · 8 files · 475 tests
- **P10-B23**：前端审批 UI ✅ — /approvals 跨 Project 聚合 + 审批卡片 + API client + i18n · 6 files · 议题 3 全链路闭环 🎉
- **P10-B22**：AuthorizationRequest API 端点 ✅ — POST/GET/PATCH/Heartbeat · 4 endpoints · 473 tests (+19)
- **P10-B21**：AuthorizationRequest Service 层 ✅ — create/respond/heartbeat/expire/cancel + 流控 + 级联失效 · 4 files · 456 tests (+26)
- **P10-B20**：AuthorizationRequest 数据模型 ✅ — 双类型单表 + Schema + Migration · 5 files · 442 tests (+18) · 议题 3 授权管道后半段启动
- **P10-B19**：require_project_role 端点接线 ✅ — 4 routers 接线 + 创建者自动 admin · 7 files · 396 tests (+3) · 议题 3 基础设施完成
- **P10-B18**：project_actor_roles 接线 ✅ — Service + require_project_role 依赖 + Admin CRUD 端点 · 6 files · 409 tests (+15)
- **P10-B17**：RBAC 基础层 ✅ — is_super_admin 首用 · JWT + ActorInfo + require_super_admin + require_role 超管绕过 · 7 files · 406 tests
- **P10-B16**：DB 宽列 migration ✅ — is_super_admin/force_password_change/created_by_admin · 4 files · 391 tests
- **P10-B13**：Password Reset 前端 ✅ — ForgotPassword.tsx + ResetPassword.tsx · 6 files · API client + routes + i18n
- **P10-B11**：前端 Email/Password 登录+注册 ✅ — 8 files · Login 表单 + Register 页面 + AuthContext email 方法 + i18n · 371 tests
- **P100-B68**：B95 审计收尾 ✅ — 3 files · docstring 枚举引用 + 零残留验证 · B95 🟡 全量闭环 🎉
- **P100-B67**：路由层枚举迁移 ✅ — 4 files · tasks+events+token_usage+ws · L5 B64→B67 🎉
- **P100-B66**：服务层(轻)枚举迁移 ✅ — 3 files · ws_manager+lease_detector+auth_service · ActorType 收尾
- **P100-B59**：B57 遗留 doc 提交 ✅ — 3 files · 7 项违纪 🟡→🟢 文档闭环
- **P9-B100**：S-051 Dashboard worker fetch 用户可见 + S-054 OAuth 欢迎名 + S-055 HistoryList completed_at ✅ — 4 files
- **P9-B99**：S-052 裸 ID→可读名 + S-056 Skills deprecate 确认弹窗 ✅ — 7 files
- **P9-B98**：S-050 console.error→用户可见 + S-053 Loading→Saving + S-057 description 校验 ✅ — 8 files
- **P100-B58**：G1 JWT httpOnly cookie ✅ — 8 files · P100 全量闭环 🎉

> 完整历史见 `tracks/synapse.md` 路线图 + `docs/archive/CLAUDE-current-state-history.md`
