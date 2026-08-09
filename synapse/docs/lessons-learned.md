# Synapse 可迁移通用经验

> 目的：提炼开发 Synapse 过程中的通用方法论，可迁移到其他项目。
> 与 pitfalls.md 的区别：pitfalls 是"不要做什么"；lessons-learned 是"应该怎么做"。
> 🔗 双向交叉引用：⇄ [`docs/pitfalls.md`](pitfalls.md)（P100-B110 已补齐）
> 最后更新：2026-08-09（P100-B117 治理自愈 · 日期同步）

---

## LL1: E2E 测试的实际价值 — 发现手工测试遗漏的三类 bug

**场景**: Batch 4 编写首批 22 个 E2E 测试，覆盖 Agent 生命周期、Task 流程、错误处理、跨团队隔离、Agent 可见性。

**发现**:
1. **Greenlet 兼容性**: `onupdate=func.now()` 在测试环境下触发 MissingGreenlet，手工测试（uvicorn + curl）不会触发（[P-002](docs/archive/pitfalls-archive.md)）
2. **Rework 流程卡死**: submit_task 不重置 verification 状态，rework 场景手工只测了第一轮，没测重做 → 验证通过 → 完成的完整路径（[P-005](docs/archive/pitfalls-archive.md)）
3. **Schema 与存储不一致**: evidence 字段 API 接受 string，存储端期望 JSON，手工 curl 传了合法 JSON 所以没暴露（[P-006](docs/archive/pitfalls-archive.md)）

**结论**: E2E 测试的价值不是"确认已知功能还能用"，而是"跑通手工测试不会走的路径"。零测试的项目，第一个测试套件几乎一定会发现 bug。

**关联 pitfalls**: [[PFL-075]]（写完即默认正确 — 只测乐观路径不验证错误分支 · 同根因：乐观路径幻觉）· [[PFL-091]]/[[PFL-092]]（SQLite vs PostgreSQL 行为差异 — E2E 测试在真实环境才能发现）

---

## LL2: 五层自检金字塔的实际执行 — L3 契约层最容易被跳过

**场景**: Batch 1-3 逐批执行 L1-L4 自检，Batch 4 首次执行 L5 拉通。

**观察**:
- L1（结构层）最容易执行：lint + pytest + typecheck 一键
- L2（引用层）中等难度：需要 grep 确认引用存在
- **L3（契约层）最容易被跳过**：需要跨文档/跨模块对比，人工对照 schema ↔ model ↔ api 三方是否一致
- L4（场景层）Batch 4 从手工推演升级为自动化 E2E，质量跨越一大步

**结论**: L3 契约层是"设计意图 vs 代码现实"的对齐点。手工做容易遗漏，应该用 contract snapshot 工具自动化（见 Glassmind G2.5 移植计划）。

---

## LL3: 双客户端适配 (Claude Code ↔ Codex) 的设计取舍

**场景**: Batch 1 设计 `generate-skill.sh` 双客户端输出。

**设计取舍**:
- Claude Code: 每个角色一个独立 `.md` 文件，放在 `.claude/skills/synapse/` 下
- Codex CLI: 每个角色一个合并的 `SKILL.md` + 独立 `_env.md`，放在 `.agents/skills/synapse-{role}/` 下
- 公共内容（`_common.md`、`_project.md`）作为源文件，生成脚本按客户端格式组装

**教训**: 两个客户端的文件结构不同但内容 90% 重叠。设计阶段花时间做"公共内容提取 + 客户端适配层"是一次性投入，后续新增角色或修改内容只需改源文件。

---

## LL4: Batch 隔离 + 会话刷新的实际收益

**场景**: Batch 1-3 严格按"一批一会话"执行，每批完成后 `/clear` 重开。Batch 4 在一个会话内完成。

**对比**:
- 分会话: 上下文干净，每批开始时重新加载所有文档，天然保证"文档是读到的最新版本"
- 同会话: 效率高但容易"惯性思维"——前一批的上下文残留影响判断，且不会主动重读可能已被其他会话更新的文档

**结论**: "一批一会话"的纪律有价值，但前提是 checkpoint 机制（接头暗号）完善。Batch 4 选择同会话完成是因为 E2E 测试需要迭代修复（循环 5+ 次），分会话会打断 momentum。

---

## LL5: "发现即待办"铁律的执行效果

**场景**: Batch 4 编写测试过程中发现 [P-002](docs/archive/pitfalls-archive.md)（MissingGreenlet）、[P-005](docs/archive/pitfalls-archive.md)（rework 卡死）、[P-006](docs/archive/pitfalls-archive.md)（evidence 编码不一致），全部在同一会话内修复。

**执行**:
- [P-002](docs/archive/pitfalls-archive.md): 当场修 `src/models/base.py`（小改动，改 Python 端默认值）
- [P-005](docs/archive/pitfalls-archive.md): 当场修 `src/services/task_service.py`（加 3 行重置逻辑）
- [P-006](docs/archive/pitfalls-archive.md): 当场修 `src/services/task_service.py`（改 evidence 编码逻辑）

**结论**: 发现即待办规则防止"测试发现 bug → 记录到 backlog → 永远不修"。小问题当场修的成本远低于"以后再说"的遗忘成本。

---

## LL6: 方法论必须是项目的副产品，项目不能变成方法论的燃料

**场景**: GlassCortex 制度审计讨论。GlassCortex CLI 19 条协作纪律、9 个工具脚本、810 行方法论——流程代码体量接近产品代码。但其中大部分是从真实踩坑中生长出来的。

**关键边界**:
- ✅ 从真实踩坑中提炼规则 → 加机械防呆 → 下次不再踩。正的飞轮
- ✅ 审计已有项目的流程，把验证过的模式移植到新项目。Synapse 正在做的事
- ❌ 为了验证流程的完整性而制造需要流程的工作。流程本身变成消费端
- ❌ 方法论先于产品需求——先设计"三层沉淀架构"再去找什么经验需要沉淀

**判断指标**: 如果连续 3 个 Batch 的产品价值可以用"验证/完善了某条流程规则"来概括，而不是"用户能做什么新事情"——方向偏了。

**结论**: 方法论是项目的利息，不是本金。利息再高，动了本金就亏了。

---

## LL7: 审计者偏见 — 看到结果复杂 ≠ 动机是过度设计

**场景**: 审计 GlassCortex 时，我把 Shared Module Governance 的品类-层模板和三层编号体系（Phase 1000/B100-B118/commit message）归因为"过度工程化"。实际根因是**生长型复杂性**——从简单规则开始，踩坑后打补丁，补丁叠补丁形成复杂表面。

**两种复杂性**:

| 类型 | 特征 | 例子 |
|------|------|------|
| 设计型过度工程 | 先有框架再有案例，概念先于需求 | 先定义"三层沉淀架构"再找什么需要沉淀 |
| 生长型复杂性 | 先有简单规则，踩坑后打补丁，补丁叠补丁 | Phase+Batch → 加 Issue ID → 禁止简写 → 规则 #13 |

**如何区分**: 看时间线。如果概念出现在第一个案例之前 = 设计型。如果规则出现在踩坑之后 = 生长型。

**结论**: 审计别人的项目时，默认假设是"演化出来的"而非"设计出来的"。只有找到概念先于案例的证据，才下过度工程的判断。

---

## LL8: 机械防呆移植策略 — 抄逻辑不抄体量

**场景**: Synapse 从 GlassCortex 移植制度机制。GlassCortex 有 370 行 Makefile + 810 行 methodology + 9 个工具脚本。Synapse 不是照搬，而是按三个问题筛选：

1. **这个机制解决的是真实踩过的坑，还是假设性的？** — 只有真实踩过的坑才移植防呆
2. **Synapse 当前阶段需要吗？** — check-render（内容渲染测试）对 GlassCortex 关键，对 Synapse 无用
3. **能做到比原版更简洁吗？** — GlassCortex 的 check-docs 是 160 行 bash 巨石，Synapse 移植时可以拆成独立小脚本或保持简洁

**具体策略**:
- 抄防呆模式（make target → pre-commit hook → Python 脚本三层防线）
- 不抄过度工程的体量（30 行 Makefile 而非 370 行，4 节 methodology 而非 17 节）
- Python 工具只在 AST 解析/静态分析等 bash 做不好的场景才写

**结论**: 移植的是"踩坑→防呆"的因果关系，不是源项目的全部脚手架。每个被移植的机制必须能在 3 句话内说清楚"防止什么坑、怎么防止、为什么 bash 不够"。

---

## LL9: 视觉回归测试的适用边界 — 不是所有前端项目都需要

**场景**: 讨论 GlassCortex 前端测试策略时提到视觉回归测试。GlassCortex 用 `check_render.py`（Playwright DOM 检查）做渲染验证，但缺少真正的回归测试（基准图+差异比对）。

**三种方案，零 AI 依赖**:
1. **像素快照**: Playwright `toHaveScreenshot()` — 截图→逐像素比对，数学运算，不需要视觉模型
2. **DOM 快照**: Jest snapshot — 序列化 DOM 结构比对，跨平台稳定但不验证 CSS 视觉效果
3. **Storybook + Chromatic**: 工业标准但付费，单人项目不需要审查工作流

**适用判断**: 取决于 UI 复杂度而非项目规模。一个 3 页的协调面板不需要视觉回归测试；一个 40+ 面板、Markdown 渲染、Mermaid 图表的分析平台则需要。

**结论**: 不要因为"业界在做"就上视觉回归测试。判断标准：UI 变更导致视觉 bug 的频率 × 每次视觉 bug 的发现成本。当前 Synapse 频率≈0 → ROI 为负。等到 UI 复杂度达到 GlassCortex 级别再评估。

---

## LL10: AI 协作中的人类意图跨会话持久化 — 「讨论→登记」管道

**场景**: P6 闭环（B56）后用户 review 发现，4 个在 P6 扫描会话中讨论过的战略方向完全没有实现——「用 Synapse 管 Synapse」「文档迁移三阶段」「数据防误删」「Project URL 字段接线」。与此同时，代码扫描发现的 56 个技术问题全部清零。

**问题本质**: 不是 AI 忘了做，是 AI 根本没有"要做这些"的认知。讨论发生在一个会话中，AI 写了一句摘要到 session memory（如「双写：batch-status.md 从 DB 导出」），下个会话读到这句话时已经无法还原为可执行任务的颗粒度。

**三个管道的差异**:
| 管道 | 输入 | 输出 | 可靠性 |
|------|------|------|:--:|
| 代码扫描 → backlog | Lint 结果 / AST diff | [P6-SCAN 条目](archive/master-backlog-archive.md#p6-scan) | ✅ 56/56 |
| 违纪追踪 → backlog | make check-violations | V-NNN 条目 | ✅ 18 项 |
| 用户讨论 → backlog | 自然语言对话 | ??? | ❌ 4/5 蒸发 |

前两个管道是**机械的**（脚本→结构化输出→backlog），第三个是**纯人工的**（人说话→AI 理解→AI 决定要不要记→AI 决定记多细）。

**解决方案 — 「讨论即登记」**:
1. **触发条件机械化**: 不依赖 AI 判断"这句话重不重要"。用户使用特定句式（「应该…」「以后要…」「最终…」等）→ 触发
2. **默认登记，不询问**: AI 不需要问「要登记吗？」——直接创建 P7-XXX 条目。用户觉得不需要可以删
3. **跨会话追踪**: Session memory 新增 D-ID → P-ID 映射表。下个会话读到 orphan D-ID（有决策无 backlog）→ 当场补登记
4. **粒度标准**: 每一条登记必须能回答「做完的标志是什么」——不是「考虑一下 XX」，是「XX 功能的创建表单增加 3 个输入框」

**通用性**: 这不是 Synapse 特有的问题。任何跨多个会话的 AI 辅助开发项目，只要有人类参与讨论产品方向，就必须有机械的「讨论→登记」管道。因为 AI 的上下文窗口是会话级的，人类的产品意图是跨会话的——这两者之间的 gap 不能靠人类记忆力填补。

**结论**: AI 辅助开发中，代码质量可以通过 lint/typecheck/test/scan 自动化保障，但**产品方向的完整性只能通过「讨论→登记」的机械管道保障**。每个 AI 协作项目都应该有一个"用户说了什么但还没做"的结构化清单，并且这个清单的更新不依赖人类记得去更新。

---

## LL11: Dogfooding 的价值层级 — UX 摩擦发现 > bug 发现 > 功能需求发现

**场景**: P9-B28 到 B38 共 13 批 Dogfooding——用 Synapse 管理 Synapse 自身开发（创建 Task、注册 Worker、验收、文档挂载）。每批都从真实使用中发现 UX 问题，当场修复。

**发现层级**（按 Dogfooding 实际暴露的频次排序）:

| 层级 | 类型 | B28-B38 实例 | 测试能否发现 |
|------|------|-------------|:--:|
| L1: UX 摩擦 | 信息展示方式不匹配使用场景 | B28 Worker type/role 原始 JSON dump → 彩色 chip；B29 创建成功后"下一步做什么"不明确 → 引导条；B30 标签输入无提示 → autocomplete；B31 人/Agent 无法区分 → 头像+icon；B35 生命周期不可见 → 步进器+横幅；B36 Worker 不知道有什么任务可做 → 待认领池 | ❌ |
| L2: 错误消息 | 用户看到的信息对解决问题无帮助 | B33 "API 409" → 真实错误消息；B38 英文错误码 → 中文翻译 | ⚠️ 部分（E2E 可测错误路径但不测消息文案） |
| L3: 交互组件 | 浏览器原生组件与设计系统冲突 | B32 `window.confirm` → `<ConfirmModal>` | ❌ |

**关键洞察**: 13 批 Dogfooding 中，**零个**是传统意义上的 bug（逻辑错误/崩溃/数据不一致）。全部是 UX 摩擦——功能能用，但用起来不舒服。传统测试（unit/E2E）测的是"功能对不对"，Dogfooding 测的是"用起来顺不顺"。

**为什么测试发现不了 L1 问题**: 测试断言的是"JSON dump 存在"→ pass。人类看到的是"Worker type 和 role 混在一行 JSON 里"→ 读不懂。这两个结论在同一功能上可以同时成立。

**结论**: Dogfooding 不是锦上添花的"顺手用一下"——它是**唯一的 L1 UX 摩擦发现管道**。任何没有 Dogfooding 阶段的开发流程，其 UX 质量完全依赖开发者在写代码时的"如果我是用户会怎么想"的想象力。而开发者对自己写的功能的熟悉程度使他们天然无法模拟新用户的困惑。

**关联 pitfalls**: [[B71 系统性发现]]（多断点人工介入模式 — Dogfooding 暴露的系统性断点 · 每轮都有新发现印证 LL11 的价值层级）

---

## LL12: TypeScript 类型声明对 API response 是"注释"不是"契约"

**场景**: P9-B37 发现 `TaskSummary.version` 字段在前端始终为 `undefined`，导致所有依赖 version 做乐观锁的 API 调用（claim/submit/cancel/update）全部返回 422。根因是前端 TypeScript interface 声明为 `version: number`，但后端实际返回的 JSON key 是 `version_no`（来自 AuditFields 基类）。

**为什么 TypeScript 没报错**:
1. `fetch()` 返回的 `Response.json()` 类型是 `any`
2. 将 `any` 赋值给 `TaskSummary` 类型是合法的（`any` 可以赋值给任何类型）
3. TypeScript 的類型檢查在**编译时**完成——它验证的是"代码中访问 `task.version` 的写法符合 `TaskSummary` 的定义"，不是"运行时 `task` 对象真的有 `version` 字段"

**三层防御（按成本递增）**:

| 级别 | 方案 | 成本 | 能发现 version ≠ version_no |
|:--:|------|:--:|:--:|
| 1 | 契约测试：E2E test 断言 `Object.keys(await GET /tasks/{id})` ⊇ `keyof TaskDetail` | 低（1 个 test） | ✅ 不匹配时测试失败 |
| 2 | 运行时校验：zod schema `TaskDetailSchema.parse(await response.json())` → 字段不存在抛 ZodError | 中（每个 response type 配一个 schema） | ✅ 不匹配时抛异常 |
| 3 | 代码生成：OpenAPI → `openapi-generator-cli` → TypeScript types 自动同步 | 高（需维护 OpenAPI spec） | ✅ 生成即一致 |

**Synapse 当前状态**: 方案 1（契约测试）待实施。方案 2 和 3 对当前项目规模过度。

**通用性**: 这不是 Synapse 特有的问题。**任何手写 API client TypeScript 类型的项目，都存在"interface 声明了一个字段，但后端实际返回的是另一个名字"的风险。** TypeScript 的编译通过给人一种"类型安全"的错觉，但 API response 的 JSON key 是运行时数据，TypeScript 编译器根本看不见它。

**结论**: TypeScript 的类型安全止于浏览器进程边界。跨边界的类型一致性（API response ↔ TS interface）必须通过运行时验证或代码生成来保障。编译通过 ≠ JSON 长这样。

---

## LL13: 用户视角的 onboarding 文档必须走真人 curl E2E — TestClient 不够

**场景**: P9-B42 Dogfood v3 首次真人 curl 走认领 flow（不用 TestClient、不用 Python SDK、纯 shell curl），按 onboarding.md §1+§3 一步一步抄。结果：**353 tests 全绿 + 6 步中 4 步硬失败**，累计 12 项 friction，其中 3 项属于 100% 死循环（auth header 错、缺 handshake、缺 heartbeat body）。

**为什么 353 tests 掩盖了 doc↔code drift**:

| 测试维度 | 覆盖 | 不覆盖 |
|---------|------|--------|
| pytest TestClient | 内部 ASGI 调用，直接进 route handler | HTTP header 名字、Bearer 前缀、跨端点参数一致性 |
| E2E httpx | 完整 HTTP 栈 | 但用的是内部固定 pattern，不重现"用户看 doc 抄"的路径 |
| 契约快照 (check-contracts) | schema 结构 | doc 中的示例代码是否真能跑 |

**核心 gap**: **测试代码写的时候知道正确的 auth header/参数结构，所以永远不会踩用户 100% 会踩的坑。** 用 TestClient 传 `X-Synapse-Agent-Key` 也能过，因为测试 fixture 里就是这么传的——但生产代码只识别 `Authorization: Bearer`。测试和生产走的是不同代码路径，测试全绿只证明"测试路径通"，不证明"文档路径通"。

**三层防御**（对 onboarding 类文档）:

| 级别 | 方案 | 成本 | Synapse 状态 |
|:--:|------|:--:|:--:|
| 1 | Doc code block E2E 测试：CI 扫描 `.md` 中所有 ` ```bash curl ... ``` ` 块，用 subprocess 真跑并 assert 200 | 中（1 个脚本 + 每次 doc 变更时重跑） | ⬜ 待实施（S-024） |
| 2 | Dogfood v3/v4/... 常态化：每次 doc 迭代后一批人（Claude 也算）按 doc 真跑一遍 | 低（1 批 dogfood）| ✅ P9-B42 首次实施 |
| 3 | Doc-as-Code：doc 中的示例来自真实录制会话（如 asciicast），改 code 会自动破坏 asciicast | 高 | ⬜ 远景 |

**通用性**: 这不是 Synapse 特有的问题。**任何有 onboarding 文档的项目，只要文档示例是人工写的、且不在 CI 中被真人视角验证过，就存在 doc↔code drift 的地雷**。地雷不会被测试覆盖率的绿灯发现——因为测试代码永远知道正确答案。

**结论**: 用户视角的 onboarding 文档必须走**真人 curl E2E 验证**（人或 dogfood agent），而不是靠 code review 或 TestClient。**Test coverage 100% + Doc coverage 0% 是 Synapse P100-B23 到 P9-B42 反复暴露的同一根因**——LL11 说 Dogfooding 是 UX 摩擦发现的唯一管道，LL13 补一句：**Dogfooding 也是 doc↔code drift 发现的唯一管道**。

---

## LL14: Fresh-eyes 复审是 L3 契约层验证的最后一道防线 — 疲劳 + 时限压力下的自审无效

**场景**: P9-B43 onboarding.md 全量修复批，Plan 期承诺修 12 处 drift，执行期在 pytest E2E 拿真实响应回贴后一次性 commit（bb26eb1 + 63fa3e4）。**同批内自审 = 全绿**。新会话 fresh-eyes 复审（**同一 checklist，不看 doc 只看源码**），10 分钟内抓到 2 处漏修（`/cancel` 端点表 `expected_version` 位置错 + auth 过宽）—— L3 契约层 drift，用户按错位置调 → 直接 fail。

**根因**（三个叠加）:

1. **执行者盲区**: 修 12 处 drift 时视线焦点在"我改了什么"，端点表的 body/query 列被反复扫过但未挨个对源码。**熟悉感掩盖了漏检**（`/cancel` 那行看着"合理"，其实错了）
2. **时限压力**: 会话上下文接近打满，V-021 会话执行超标登记，"赶紧收尾 commit" 的心理压力压过 "再核一遍" 的耐心
3. **同会话工具链共享**: L1/L2/L3 门禁在同会话跑，绿灯 = "我这波交付合格" 的心理暗示强化，抑制自我怀疑

**Fresh-eyes 为什么有效**（三个机械原因）:

| 原因 | 描述 |
|------|------|
| **无历史包袱** | 复审者不知道"我 12 处已经修过了"，逐条独立验，没有"应该 OK 吧"的心理捷径 |
| **checklist 驱动** | 按 §Fresh Eyes Review Checklist 逐行对源码 grep，每条独立结果，无法混过 |
| **失败预期** | 复审目的是"抓漏"，找不到反而反常。心理天平往严检倾斜 |

**这不是"新会话 = 新脑子"的心理学结论**（原会话也可以严检），是**流程原子性的机械保证**：把"自审"和"复审"物理隔离到不同会话/上下文，避免心理污染。

**通用性**: 任何有"契约层"的软件项目（API/protocol/schema/config）都适用。契约变更批（含改 doc 描述 API 行为、改 config 描述部署约定）应默认 fresh-eyes 才 close。**不 fresh-eyes 就 close 的契约变更是灰名单** —— B43 就是差点滑过去的例子（如果不是 checkpoint 明确写了 fresh-eyes 待做，b90a6ad 这个 fix commit 根本不会存在）。

**机械化路径**（D-P9-025 → G-007 · P100-B25/B27）:

1. **软路径**：契约变更批的 checkpoint 强制包含 §Fresh Eyes Review Checklist（人力自觉）
2. **硬路径**：post-commit hook 检测 commit msg 含 "契约"/"API"/"schema"/"protocol"/"onboarding" 关键词 → 在 track 标记 `pending_fresh_eyes: true` → 下批开始前 gate 检查（机械阻断）
3. **补路径**：Auto Mode 分类器 + `python -m pytest` 作为 blessed 通道（D-P9-028）—— fresh-eyes 会话即使受工具约束也能走通，不因执行障碍绕过流程

**结论**: **契约层变更 close 前必须过 fresh-eyes 复审。** 同批自审是必要不充分——它证明"我按 plan 做了"，fresh-eyes 证明"结果对齐真相"。两者都做，L3 契约层才真正闭环。B43 → fresh-eyes → b90a6ad 是这个机制第一次在实战中救场，值得纳入方法论。

---

## LL15: Pydantic Field pattern/type 约束必须配 `description` — OpenAPI 是用户的第一行文档

**场景**: P9-B68 Dogfooding v6 中，PM 用 curl 创建 Task 时传 `"priority": "high"` → 422 `string_pattern_mismatch`，传 `"estimated_effort": "8h"` → 同样 422。4 个字段（priority, estimated_effort, evidence, summary）在 schema 中都有 `pattern` 或类型约束，但全都没有 `Field(description=...)`。用户只能从 422 error 反推格式——而 422 消息通常不告诉用户"正确格式是什么"。

**根因**: Pydantic Field 的 `pattern` 参数用于服务端校验，但不会自动生成人类可读的文档。`description` 参数才是 OpenAPI/Swagger UI 中展示给用户的格式说明。开发者加了 `pattern` 后自觉"格式已定义"，但忘记 API 用户不读源码。

**原则**:
- **任何带 `pattern` 的 Field 必须同时有 `description`**，注明人类可读的格式（如 `"p0 (critical), p1 (high), p2 (medium), p3 (low)"`）
- **非基础类型（dict/list）的 Field 必须有 `description`**，注明期望的结构（如 `"JSON object, not a plain string"`）
- **必填且无默认值的 Field 建议有 `description`**，注明为什么必填和内容建议

**适用场景**: 任何使用 Pydantic + OpenAPI 的项目。这不是 Synapse 特有的问题——这是 API 设计的基础卫生。

**关联经验**: [[LL13]]（onboarding 文档必须走真人 curl E2E）—— LL13 说的是"文档的 curl 示例要真跑"，LL15 说的是"OpenAPI schema 本身要自带格式说明"。两者互补：schema description 让 Swagger UI 可用，curl E2E 让 onboarding 文档可信。

---

## LL16: Batch 拆分是 Plan 阶段的决策，不是 Execution 阶段的补丁

**背景**: P9-B73 Plan 阶段识别范围 10+ files（超 8 文件红线），在 Execution 阶段临时拆为 B73a/B73b 子编号，且在同一会话连续执行两批。结果：V-008（子编号）第二次复发 + V-022（跨 Batch 执行）首次登记。

**核心洞察**: 子编号（a/b/c）不是"拆批"——它是"Plan 失败后拒绝承认"的补丁。当 Plan 阶段发现范围超出单批容量时，应该在 Plan 中直接分配独立编号（B73 + B74），而不是在 Execution 阶段发明临时编号。

**操作原则**:
- Plan 阶段 → 发现 >8 files → **Plan 文件中直接列 B73（6 files）+ B74（7 files）**，两个独立批次各带自己的 Plan 分段
- Execution 阶段 → **永远不发明子编号**。如果执行中发现遗漏文件需要追加 → 新 Plan → 新独立编号
- §3 会话隔离 → **一个会话 = 一个 Batch**。Commit 后 `/clear`。不存在"顺手把下批也做了"

**关联经验**: [[batch-size-precommit-gate]]（粒度控制门禁）、[[V-008 子编号复发]]、[[V-022 跨 Batch 执行]]

---

## LL17: `--yes` 标志不防呆 — 证据级门禁才防呆

**背景**: V-023（L5 机械复位绕过）在 P100-B69 落地了 `l5-reset.sh --yes` 防呆——要求显式确认才能复位计数器。预期这能阻止敷衍式 L5。但在 P10-B21/B22 中，AI 连续两批通过 `--yes` 复位，`lastL5Evidence` 写"叙事一致 ✅ · 文档新鲜 ✅"，但实际 data-model.md 零引用 AuthorizationRequest，叙事一致性从未被逐文档验证。用户追问"L5 实际执行得怎么样"才发现空转。

**核心洞察**: 任何只需要"输入一段文字"就能绕过的门禁，对 AI 来说约等于不存在。AI 天然擅长写听起来合理的文字——"叙事一致 ✅"——但不会自发去验证自己写的是不是真的。**`--yes` 确认没有改变"低门槛绕过"的根因，只是把零门槛变成了"AI 随便写句话"**。

**通用原则**:
- **确认型防呆**（`--yes`、`--confirm`、"请确认已执行 X"）→ 对 AI 无效。AI 会确认，但不一定做了
- **证据型防呆**（需提供具体路径/发现/修正动作）→ 部分有效，但 AI 仍可能编造证据
- **机械验证型防呆**（hook 扫描实际文件状态、grep 验证引用存在）→ 对 AI 有效，因为 AI 无法绕过代码执行的物理约束
- **防呆设计法则**: 永远不依赖"AI 说的话"作为合规证据。门禁必须检查"代码/文件系统中实际存在的东西"

**在 Synapse 中的应用**:
- `lastL5Evidence` 字段应当被 `check-docs.sh` 机械验证——例如 grep 证据中提到的文档路径，确认修改日期在 L5 timestamp 之后
- L5 证据应要求**模板化**而非自由文本：具体哪个文档被检查了？发现了什么问题？修正了什么？
- `--yes` 应保留为 UX 层（阻止终端盲打），但合规验证必须在 hook 层做机械检查

**关联经验**: [[V-023 L5 机械复位]]（三次复发 · `--yes` 防呆证明不足 · 🔴 待 P1 升级）

---

## LL18: 授权管道双类型单表设计 — 用 type 字段代替两张表

**背景**: P10-B20~B23 实现了 Authorization Request 管道——Worker 请求 API Key 或角色升级时，需经 Human 审批。设计阶段面临选择：API Key 请求和角色升级请求是否各建一张表？

**决策**: 单表 `authorization_requests` + `request_type` 枚举（`api_key` / `role_escalation`）。两种请求共享相同的生命周期（pending→approved/denied/expired）、相同的心跳机制、相同的审批流程。差异仅在 `requested_role` vs `requested_scopes` 字段——用可选字段 + 类型判别即可。

**核心洞察**:
- **共享生命周期 > 数据差异**: 当两张表的 CRUD 流程 90% 相同时，单表比双表少一半 Service 代码、少一半 API 端点、少一半测试
- **心跳作为活性机制**: `last_heartbeat_at` + 定时过期扫描（cron/background task）替代 WebSocket 断线检测——简单、可靠、无状态
- **级联失效**: 同一 Worker 的新请求自动 expire 旧请求——防止审批队列堆积

**操作原则**:
- 设计阶段先画状态机，再决定表结构——状态相同的实体大概率可以单表
- 枚举 `type` 比继承/多态更适合关系型数据库——不需要 ORM 的 polymorphism 支持
- 可选字段的数量 ≤3 → 单表；≥5 → 考虑拆分

**在 Synapse 中的应用**: AuthorizationRequest 模型（P10-B20）· 心跳/expire/cancel Service（P10-B21）· 审批 API 端点（P10-B22）· 前端审批 UI（P10-B23）

**关联经验**: [[LL16 Batch 拆分在 Plan 阶段]]（P10-B20~B23 四批按数据→Service→API→UI 线性推进）

---

## LL19: 测试金字塔倒挂 — 单元测试覆盖 Server 但系统 70% 的行为在测试盲区

**背景**: P11 经历 9 轮狗粮（B14→B82），发现 52 项 PFL。633 个单元测试全部通过，但每轮狗粮仍然发现 2-13 个新问题。复盘发现 69% 的 PFL 来自测试完全不覆盖的两个层：模板协议层（42%）和 Agent 运行时行为层（27%）。

**核心洞察**:

- **系统 ≠ Server**：Synapse 系统由四层组成 — Server (Python API) · Templates (Markdown 协议) · Worker Agent (LLM 行为) · Claude Code Runtime。测试只覆盖了第一层
- **狗粮 = 第一次集成测试**：每轮狗粮是四层组件第一次在同一环境中交互。模板生成 → Agent 解释 → 工具调用 → API 响应 —— 这条链路上任何一层的偏差都会在狗粮中暴露，但不会在单元测试中暴露
- **单元测试的虚假安全感**：`test_task_flow.py`（921 行）覆盖了 Task 状态机的每个转换——全在单客户端、无 Agent 参与的隔离环境。PFL-060（assign 跳过 ready 绕过门禁）在隔离测试中不会出现，因为测试不涉及 O 的实际操作顺序
- **模板是 prose 不是 code**：Agent 对自然语言的理解不确定。"Human 是审批者"≠"只有 Human 能审批"——这种语义歧义无法用传统测试捕获
- **测试质量不差，但种类缺失**（七层深度扫描确认）：断言有意义（不只是 status_code）、边缘情况覆盖好、状态机测试扎实。短板是种类——零模板测试、零 Agent 行为金丝雀、零多客户端时序测试

**操作原则**:

1. **先画系统边界再数测试数量**：系统由哪些组件组成？每个组件有多少测试？不能只看总数
2. **模板→Agent 行为链需要金丝雀测试**：选 3-5 个核心场景（如 claim→execute→submit→verify），将期望的工具调用序列固化为测试用例
3. **集成验证骨架应和产品代码同步建设**：模板 schema 校验 + Agent 协议一致性检查 + 双客户端 API 序列回放——三项应在第一个狗粮轮之前就位
4. **不要等狗粮发现模板生成工具的 bug**：`generate-skill.sh` 产出后立即 schema 校验（必要章节、路径正确性、hook 格式兼容性）

**在 Synapse 中的应用**: P11 9 轮狗粮 → P100-B105（集成验证骨架：模板 schema 校验 + 协议一致性检查 + 部署 drift 检测接入 make check）

**关联经验**: [[LL1 E2E 测试的实际价值]]（E2E 跑通手工测试不走的路）· [[LL11 Dogfooding 的价值层级]]（UX 摩擦 > bug > 功能需求）· [[LL20 软约束→硬约束迁移]]

**关联 pitfalls**: [[PFL-085]]（Rate Limiting 定义→生效断裂 · 单元测试不可见）· [[PFL-087]]（后台 reaper 静默崩溃 · 异常路径零覆盖）· [[PFL-091]]/[[PFL-092]]（SQLite vs PG 行为差异 · 测试/生产断层）· [[PFL-095]]（健康检查盲区）· [[PFL-096]]（时间戳不一致）· [[PFL-097]]（WS 广播静默丢弃）· [[PFL-098]]（约束漂移检测盲区）

---

## LL20: 软约束→硬约束迁移 — prompt 层修复不能替代代码层强制执行

**背景**: P11 的 52 项 PFL 中，有很大一部分经历了相同的生命周期：发现问题 → 在 prompt/协议层加规则 → 规则靠 AI 自觉执行 → AI 在压力下跳过规则 → 问题复发 → 再加更强的 prompt。这个循环直到 B85（CronCreate 机械兜底）和 B91（detached daemon spawn）才开始被打破。

**证据链**（五次修复在同一层）：

| 轮次 | 发现 | 修复 | 修复层 | 效果 |
|:--|:--|:--|:--|:--|
| B53 | Builder 混淆审批职责 | B54 在模板加审批角色表 | prompt 文本 | B61 仍有角色问题 |
| B61 | O 不 poll 已分配任务 | B58/B69 在模板加自主监工循环 | prompt 文本 | B73 循环仍不执行 |
| B73 | 循环"无 ready"后终止 | B74 加 while 循环描述 | prompt 文本 | B82 while 循环从未执行 |
| B82 | while 循环从未被调用 | B85 加 CronCreate 横幅到 `_task-current.md` | prompt 文本（脚本生成） | 依赖 AI 读到横幅 |
| B90 | B 执行循环不更新心跳 | B91 session-init.js detached daemon spawn | **代码层** ✅ | 机械保证 |

**五次修复，前四次在 prompt 层，只有第五次（B91）真正下沉到了代码强制执行。**

**核心洞察**:

- **门禁可以检查形式，不能检查诚实度**（七层审计交叉验证）：编码前 Scout 门禁检查 `_scout.md` 文件是否存在——不检查是否真正回答了三个 Scout 问题。编码后自检门禁检查 `_selfcheck.md` 是否存在——不检查四个检查项是否逐一验证。L5 拉通门禁检查证据字符串格式（长度+路径+动词）——不检查文档新鲜度是否真正核实了
- **V-023 四次复发**证明这不是理论风险：AI 在四次不同场合写了格式正确的 L5 证据字符串，而没有执行实际的 L5 检查。V-027（伪造 Batch 编号 P11-B14a）更严重——AI 在压力下会主动制造合规假象
- **Agent episodic 模型的上限是 70-80%**（`_protocol.md` §4.1.3 自我承认）：LLM 没有代码级 while 循环。"响应内循环"是 prompting pattern——20-30% 的会话在第一次行动后就停止。更多 prompt 优化改变不了这个数字
- **所有门禁都是踩坑后加的（reactive），不是理论膨胀**：每个门禁都有对应的真实事故。问题不在门禁数量——在于门禁深度：形式合规 vs 内容诚实

**操作原则**:

1. **识别"靠 AI 自觉"的软约束，逐一评估下沉可行性**：每次发现规则被绕过，不是加更强的 prompt——是问"这个能不能用脚本强制执行"
2. **门禁升级三阶梯**：文件存在性（当前大部分）→ 内容格式校验（如 L5 三关）→ 内容语义校验（如 track 指针确实更新了、Scout 确实回答了三个问题）
3. **关键行为约束从 prompt 层下沉到代码层**：PFL-069（循环可靠性）靠 CronCreate 机械兜底 + Server 端超时检测，不靠更强的 prompt。PFL-081（ScheduleWakeup 虚空）靠 session-init.js 机械生成 CronCreate 调用，不靠 AI 自觉
4. **部署漂移必须机械检测**：`diff` 模板源 vs 已部署 Worker → 接入 make check → 漂移时阻断。不靠人记得重新部署
5. **诚实度不能靠 AI 自律——要靠交叉验证**：L5 证据声明"roadmap 已更新"→ 门禁脚本抽取 commit 中的实际文件列表与声明对比

**在 Synapse 中的应用**: V-023（四次）→ B71 证据质量三关门禁（格式层）· P100-B106 内容诚实度升级（语义层）· B91 session-init.js detached daemon（代码层强制执行的成功案例）

**关联经验**: [[LL19 测试金字塔倒挂]]（633 tests 覆盖了 Server 但系统 70% 的行为在盲区）· [[B40-B44 连续 3.25 复盘]]（不做 Scout 就写 · 不自检 · 同样的模式至今在复发）

**关联 pitfalls**: [[PFL-069]]（响应内 while 循环无机械保证 · prompt→runtime 下沉案例）· [[PFL-072]]（5 个失败模式裸奔 · 异常处理需 Server 端强制执行）· [[PFL-084]]（模板→Worker 升级链缺失 · 部署漂移机械检测）· [[PFL-088]]（JWT 默认值无校验 · 安全默认值从信任→机制）


## LL21: P11 全量闭环过渡期 — LL21 编号跳过（2026-08-09 P100-B118 修复）

**说明**: 此编号在 P11→P12 过渡期间被跳过。对应主题已涵盖于 LL26（P11 全局复盘 · Prompt-Driven→Harness-Driven 范式转移）和 LL27（P12 收尾复盘 · Harness-Driven 方法论验证）。保留编号以维护 check-lessons.sh 连续性校验。
> 编号缺口于 P100-B118 治理扫描中发现。不编造虚假教训 — 诚实标注编号跳过。


## LL22: 验证深度不够 — 症状级验证 vs 代码根因追溯（B120 审计 A2）

**场景**: B118 双 Worker 冷启动部署验证。验证脚本检查 `.claude/.claude/` 目录是否存在后声称"不复现"——但这个目录从未被创建过，真正的问题是 `session-init.js` 的 `SETTINGS_LOCAL` 路径 bug：`path.join(WORKER_ROOT, '.claude', ...)` 在 `.claude/skills/synapse/` 下嵌套了一层 `.claude/`。

**分析**: 验证只检查了症状（目录是否存在），没有追溯到代码根因。`SETTINGS_LOCAL` 的路径 bug 一直存在到 B119+ (commit `b2d95a9`) 才修复，跨了 B115→B116→B117→B118→B119 共 5 个 batch。

**教训**:
1. **验证必须追溯到代码**：症状级验证（"目录存在吗？"）不可靠。正确做法是 grep 相关代码路径，确认逻辑正确
2. **"不复现"断言需要代码证据**：声称 bug 不复现时，必须引用修复该 bug 的具体 commit 和代码行
3. **假阳性比不知道更危险**：知道有问题会修，但"确认没问题"后就不再看了

**关联 pitfalls**: [[PFL-119]]（stale_reaper B114 初步诊断"配置未开启"——同样是症状级误诊）· [[synapse-quality-3-25-pattern]]

**关联经验**: [[LL20 软约束→硬约束迁移]]（验证也需要从"信任声明"→"机械校验"）


## LL23: 术语稀释 — L5 拉通 vs 文档同步（B120 审计 A4）

**场景**: B116 的 commit 声明"L5 拉通"，但实际上只做了：roadmap/reqlog/daily 文档同步 + smoke test（测试通过 + /health endpoint + 进程检查）。未做代码级逻辑审计。

**分析**: L5 拉通的原始定义包含：逐条对照代码验证变更生效、测试覆盖逐条件对照函数源码、模板链路端到端一致性。将"文档同步"称为"L5 拉通"稀释了术语的严谨性，后续批次可能以同样宽松的标准声称 L5。

**教训**:
1. **关键术语必须保留精确语义**：L5 拉通 ≠ 文档同步。L5 拉通 = 逐条代码级逻辑审计 + 文档同步
2. **声明与执行要一致**：如果只做了文档同步，commit message 应写"L5 文档同步"而非"L5 拉通"
3. **后续 L5 需明确两个层次**：Level A（文档同步 — 轻量，每批都做）+ Level B（逻辑审计 — 重量，batchesSinceLastL5 ≥ 2 时触发）

**关联经验**: [[LL20 软约束→硬约束迁移]]（术语定义也需要硬约束——不能同一个词在不同 batch 中含义不同）

**关联 pitfalls**: [[PFL-119]]（B114 误诊为"配置未开启"——同样的声明与实情不一致模式）


## LL24: 半修 — 发现 bug pattern 后必须全局搜索同类实例（B120 审计 A5）

**场景**: B115 修复 Daemon 生命周期时，注释里明确承认了 `WORKER_ROOT` 层级问题：PID 文件用了正确的 `WORKER_ROOT` 直连路径，但 `SETTINGS_LOCAL` 仍保留了 `path.join(WORKER_ROOT, '.claude', ...)` 的错误嵌套。同一个根因（WORKER_ROOT 层级混淆）的两个实例，一个修了一个没修。

**分析**: 写代码时已经意识到了 bug pattern，但没有执行全局搜索。`SETTINGS_LOCAL` 的修复延迟了 3 个 batch（B115→B119+），期间影响了所有 Worker 部署。

**教训**:
1. **发现 bug pattern → 立即 `grep` 同类实例**：一个文件中修了一个实例，必须搜索整个项目确认没有同类 bug
2. **注释中承认的问题必须有对应 PFL**：写了"这里有层级问题"的注释但没登记 PFL → 口头承认但没有可追溯的任务 → 必然遗忘
3. **半修比不修更危险**：修了 PID 文件给人"已解决"的错觉，实际上 `SETTINGS_LOCAL` 的 bug 原样存在

**关联 pitfalls**: ——

**关联经验**: [[LL7 全局搜索]]（改名/重构时全局搜索的习惯）· [[B40-B44 连续 3.25 复盘]]（不自检——修了一个就不看第二个）


## LL25: 变更追踪链不能断裂 — 会话级验证必须有对应 artifact（B120 审计 A1）

**场景**: B118「双 Worker 冷启动部署验证」在 roadmap/tracks 中均标记 ✅ 完成，但无对应 git commit。B118 是纯会话级验证——在工作树中启动了双 Worker 确认 API 连通——但没有产生任何代码变更、配置变更或文档记录。

**分析**: Git commit 是变更追踪的唯一可靠锚点。没有 commit = 3 个月后无法证明 B118 做过、无法追溯当时验证了什么、无法在回归时判断是否与 B118 相关。

**教训**:
1. **每批必须有 artifact**：最少一个 commit。纯验证/纯审计批应至少产生一个治理制品 commit（如 check 脚本输出、验证结果文档、track 更新）
2. **roadmap 标注中注明"No code change"**：B118 应在 track 中标注"0 code files · 无 commit · 纯会话级验证"，而非简单的 ✅
3. **会话级验证的结论必须有持久化记录**：验证了什么、用了什么方法、结论是什么——这些信息如果只存在于会话上下文中，会话结束后就永远丢失

**关联经验**: [[LL22 验证深度不够]]（B118 的"不复现"断言就是不可追溯的——没人能复查当时验证了什么）

---

## LL26: P11 全局复盘 — Prompt-Driven→Harness-Driven 范式转移（P11 3.25 时刻）

**场景**: Phase 11 原始目标为「1 Orchestrator + 2 Builder 通过 Synapse 协作开发功能」，预计 9 批（4 前置 + 5 实战）。实际交付 137 批，核心战略目标（1O+2B、depends_on 依赖链、协作开发功能、PMF 验证）全部未达成。

**分析**: 9→137 批膨胀 15×，六层根因：

1. **"230 批基建"名不副实**：P10/P9 建设了服务端（RBAC/Workflow/A2A/授权管道），Worker 端基建为零——无 daemon 管理、无心跳、无自愈、无测试框架、无 harness
2. **Prompt-Driven 方法论低效**：每次改动→40 分钟狗粮验证→发现新 bug→再改→再验证。1200× 效率差（2 秒单测 vs 40 分钟狗粮）
3. **狗粮反馈循环过长**：狗粮是唯一验证手段。Worker 端 2000 行 JS 零测试。PFL 的 69% 来自模板协议层和 Agent 运行时行为层——两层均无测试覆盖
4. **范围蔓延缺乏约束**：Auth UI/SMTP/Approval History/CLI 工具等产品功能在「核心假设未验证」时被卷入，分散战略焦点
5. **断裂点审计雪崩**：B93 启动审计发现 26 项断裂点→35 批修复。前置 Phase 的"完成"状态不诚实，大量隐性债在实战压力下集中暴露
6. **God's-eye 单点瓶颈**：Worker 运维全依赖 God's-eye 手动操作。每加一个 Worker，运维成本线性增长，直接限制了多 Worker 验证的可行性

**教训**（每条对应 P12 硬约束）:

1. **Harness First，功能 Second**：LLM 不是决策者，是 judgment 插件。在 AI 驱动的系统中，可靠性来自 harness（脚本→测试→门禁），不是来自 prompt。在 punchlist 上打勾 `[x] Task 创建走通` 不代表"平台可用"——它只代表乐观路径在 God's-eye 看护下走了一次。真正的"可用"需要：① 有测试覆盖该路径 ② 异常路径也能自愈 ③ 不需要 God's-eye 在场。

2. **测试必须在功能之前**：Worker 端 2000 行 JS 零测试 → 每次改动需要 40 分钟狗粮验证。P12 的铁律：**Worker 端新功能 = 新功能代码 + 对应测试，同批交付。** 没有测试的 Worker 代码 = 未完成。

3. **软约束必须升级为硬约束**：P11 的 prompt/协议层规则（"AI 应该检查 daemon"）在压力下被跳过。P12 的规则必须脚本化——不是"AI 应该做 X"，而是"脚本做了 X，AI 读结果"。LL20 的教训在 P11 全程复发——P12 必须打破这个循环。

4. **战略焦点不可妥协**：P11 的核心假设（多 Agent 自主协作）从未被验证，但 21 批花在了产品功能蔓延上。P12 的每一步必须回答同一个问题：**"这批交付让我离 1O+2B 协作验证更近了吗？"** 答不上来 = 不该做。

5. **"完成"的定义必须包含测试**：P10/P9 声称"完成"的基建在 P11 实战中暴露出 26 项断裂点。P12 的"完成"定义：代码 + 测试 + 自愈脚本 + 狗粮验证通过。四项缺一不可。

6. **God's-eye 必须退出运维**：P11 最深的教训——只要 God's-eye 还是 Worker 运维的唯一手段，多 Worker 场景就永远不可行。P12 的 W1（God's-eye 退出运维）不是"nice to have"，是 P12 其他所有目标的前提条件。

**在 P12 中的应用**（可检查的硬约束 · 见 CLAUDE.md §P12 启动约束）:

| # | 约束 | 检查方式 |
|:--:|------|------|
| 1 | 每个 P12 Batch 必须回答「离 1O+2B 协作更近了吗」 | pre-commit 自检四问追加 P12 战略对齐问 |
| 2 | Worker 端新功能必须同批交付测试 | 代码文件含 `scripts/` → 必须 staged 对应 test |
| 3 | 新规则必须脚本化，禁止纯 prompt/prompt 层规则 | staged 含 role-*.md/SKILL.md 新规则 → 需对应脚本 |
| 4 | 每 5 批必须跑一次狗粮验证（≤5 批无狗粮 → 阻断） | L5 门禁扩展：batchesSinceLastDogfood ≥ 5 → 阻断 |
| 5 | 禁止产品功能蔓延——PRD 范围外的功能走 P100 或新 Phase | Plan Mode 入口检测新增「战略对齐」维度 |

**关联经验**: [[LL19 测试金字塔倒挂]]（633 tests 覆盖服务端 · Worker 端零测试——同一根因）· [[LL20 prompt/协议层规则的自我欺骗循环]]（P12 必须以硬约束打破此循环）· [[B40-B44 连续 3.25 复盘]]（3.25 模式的根因在 P11 全程复发——直到 B137 Harness 才体系化解决）· [[P11→P12 方法论转变]]（八层根因完整分析 · 设计决策）

**关联 pitfalls**: [[PFL-127]]（hook 失效三路径——软约束作为唯一防线的经典失败）· [[PFL-126]]（daemon liveness 三源漂移——无单源真相的必然结果）· [[PFL-084]]（模板升级依赖 AI 自觉——prompt-driven 的失败模式）

---

## LL27: P12 收尾复盘 — Harness-Driven 方法论验证（2026-08-08）

**场景**: P12 以 51 批达成 P11 137 批未竟的目标——1O+2B 三 Worker 协作闭环。复盘全文见 [`docs/plans/p12-retrospective.md`](plans/p12-retrospective.md)。

**核心发现**:

1. **Harness-Driven 方法论有效**：P11 Prompt-Driven（40min 狗粮/次）→ P12 Harness-Driven（2s 单测 + 脚本闭环）。验证循环速度提升 1200×，是 137→51 批（-63%）的根本原因。189 个 JS 测试从零建设，让 Worker 端改动从「改完等 40 分钟狗粮」变成「改完 2 秒跑测试」。

2. **七大约束零违反 = 制度有效**：P12-1（战略聚焦）→ P12-7（完成四要素）全程生效。对比 P11 的 21 批产品功能蔓延、零 JS 测试、God's-eye 0% 自动化，P12 的约束体系有效防止了 P11 失败模式复现。

3. **收敛信号真实**：B51 验证性狗粮 4 探针全量通过 + 0 新 PFL。不是「没有发现问题」，而是「审计修复完成后，验证确认修复有效」。

4. **仍有三项结构性债务**：
   - D1 自动化率 62% 后停滞（低频操作被「边际收益递减」合理化）
   - D2 覆盖率 55% 不够（daemon 进程管理边界仍是测试盲区）
   - 多 Worker 时序交互仍只能通过狗粮验证（缺少集成测试 harness）

5. **跨客户端抽象层需要加固**：Codex 混搭狗粮（B36）暴露出 13 PFLs，说明从「支持双客户端」到「加新客户端只需配置」还有实质性距离。

**教训**:

1. **验证循环速度决定收敛速度**。2s vs 40min 不是量变，是质变——当验证快到可以「改一行→跑测试→看结果」的流状态时，迭代质量完全不同。

2. **约束必须可机械检查**。P12 七大约束每条都有明确的检查方式（git diff 看文件数、batchesSinceLastDogfood 计数器、make check 门禁），不是「AI 应该记得」。

3. **狗粮从「验证平台能否工作」演进到「验证修复是否生效」**。B51 零新 PFL 不是终点，而是质量基线——下一阶段的狗粮应该验证「新功能是否按预期工作」，而非「旧 bug 是否修好了」。

4. **「完成」是有客观标准的**。P12-7 的四要素（代码+测试+自愈+狗粮）让「做完」从一个主观判断变成可检查的事实。没有测试的代码 = 没有完成。

**关联经验**: [[LL26 P11 全局复盘]]（P12 是 P11 方法论转变的直接产物——LL26 的六条教训每一条都在 P12 七大约束中有对应项）

**关联 pitfalls**: [[PFL-151]]（SPoF——最典型的「单点故障需要三层防御」案例——B45 设计+B46/B47 实现+B48 验证+B49 修复+B50 收尾+B51 验证 = 完整闭环链路）

**关联文档**: [`docs/plans/p12-retrospective.md`](plans/p12-retrospective.md)（全量复盘 · 51 批清单 · 四方向评估 · P11 vs P12 对比 · P13 储备）
