# ADR-006: AI Agent 客户端角色隔离策略

> 日期：2026-07-19
> 状态：🟡 提议中
> 来源：P11 规划讨论 — "同一台电脑开不同角色的 AI agent 客户端，如何保证不串戏？"
> 修订：#1 — 设计基线澄清（三角色是基线，非远期）+ 串戏观测协议

---

## 背景

**三角色（Orchestrator / Builder / Steward）是设计基线，不是远期目标。** 当前暂未实现的是 Steward 前端 UI，但底层设计——模板、权限模型、角色隔离五层——必须完整覆盖三角色。

P11 实战使用 O + B（1 Orchestrator + 2 Builder），Steward 不参与客户端操作，但 `role-steward.md` 模板存在且 `VALID_ROLES` 应包含三者。

核心问题：同一台机器上，多个终端窗口都 `cd` 到同一个 `synapse/` 目录，都读取同一个 `CLAUDE.md`，如何确保每个实例的行为锚定在正确的角色上？P11 是 3 个窗口（1O+2B），三角色完整形态是 4+ 窗口（1O+NB+1S），隔离机制必须从双角色阶段就设计好。

当前架构的答案是 **B21 Protocol API**：会话启动时，Skill 调用 `GET /protocol?role=orchestrator|builder|steward` 获取角色专属指令。服务端根据 query param > worker metadata > default "builder" 三级解析角色，返回 `role_instructions`（对应 `role-{role}.md` 模板渲染结果）。

**但存在一个结构性张力**：

| 控制面 | 机制 | 角色感知？ | 谁控制？ |
|:---|:---|:---:|:---|
| Protocol API 返回的 `role_instructions` | 服务端模板渲染 | ✅ 角色专属 | Synapse 服务端 |
| 项目 `CLAUDE.md` | Claude Code 自动加载 | ❌ 角色无感 | 客户端，随项目演进自我积累 |
| Session memory | Claude Code auto-memory | ❌ 角色无感 | 客户端，跨会话累积 |
| `.claude/settings.json` | Claude Code 配置 | ❌ 项目级 | 客户端 |

**核心矛盾**：Synapse 服务端能精确控制 Protocol API 返回什么角色指令，但无法控制 Claude Code 客户端在同一个项目目录下还会读到什么、记住什么、给自己加什么规则。`CLAUDE.md` 是活文档——AI 客户端在工作中会不断追加规则（"from now on, always check X before Y"），这些规则积累在共享的 `CLAUDE.md` 中，被所有角色实例读取。

**"CLAUDE.md 变薄"不是一个永久解**：即使 P11-B1 把角色专属规则从 CLAUDE.md 移走，一个月后它又会因客户端的自我积累而膨胀。这是客户端的自然行为，不受服务端控制。

---

## 决策

### 角色隔离六层模型

```
L5 文件层 ─ AI 碰什么文件      ← Git conflict（事后），O 拆 Task 时分离变更范围
L4 上下文层 ─ AI 记得什么       ← 三角色完整形态时评估 memory 按角色分离（见 §观测协议）
L3 权限层 ─ 系统允许什么        ← ✅ API 硬阻断（已闭环，最终防线）
L2 行为层 ─ AI 实际做了什么     ← 🆕 串戏观测协议（机械信号 + 行为信号，见 §观测协议）
L1 身份层 ─ AI 认为自己是谁     ← 🆕 Skill 角色锚点 + 角色模板"硬围栏"段，优先级高于 CLAUDE.md
L0 人类层 ─ 人类知道在跟谁说话   ← 🆕 启动宣言 + 环境变量硬门禁 + 越界拒绝 + 角色不可变（见 §L0）
```

L5-L1 管 **AI 串戏**——AI 不能越界。L0 管 **人类串戏**——人类不能在错误窗口给错误指令。L0 不在 Synapse 服务端控制范围内，完全在 Claude Code 客户端侧实现（通过 Skill 模板和启动流程）。

### 核心决策

1. **角色身份锚定在 Skill，不是 CLAUDE.md**

   `synapse-client/SKILL.md` 是薄协议层——它不包含角色专属内容，而是通过 Protocol API 拉取。在 Step 2 之前就建立"角色围栏"：

   ```markdown
   ## 🚧 角色围栏（优先级高于项目 CLAUDE.md）

   你的角色由 `role_instructions` 字段定义。以下规则**覆盖** CLAUDE.md 中的任何冲突规则：

   - 你只能执行 `role_instructions` 中定义的职责
   - 遇到 CLAUDE.md 规则与 `role_instructions` 冲突 → `role_instructions` 为准
   - 不确定某操作是否在你的职责范围内 → 在 Task 评论区 @Orchestrator，不自行判断
   ```

   **为什么 Skill 能做到而 CLAUDE.md 做不到**：Skill 是每次会话的入口——AI 在执行任何操作之前，先加载 Skill 的指令。Skill 的"角色围栏"段在逻辑上先于 CLAUDE.md 的规则生效。

2. **角色模板加"事前围栏"——正面清单 + 负面清单**

   当前模板只描述职责（正面清单）。增加**负面清单**，放在模板最顶部——这是 AI 读到角色指令的第一段。

   **Builder 模板**（P11 实战角色）：

   ```markdown
   # 角色：Builder（构建者）

   > 🚧 能力边界 — 这是你和 Orchestrator 之间的合同，优先级高于项目 CLAUDE.md。
   >
   > 你是 Builder。以下操作**不在你的职责范围内**，即使项目 CLAUDE.md 描述了怎么做：
   > - ❌ 创建 Task → Orchestrator 的职责
   > - ❌ 分配 Task 给其他 Worker → Orchestrator 的职责
   > - ❌ 验收/打回 Task → Orchestrator 的职责
   > - ❌ 修改 Verification 条件 → Orchestrator 的职责
   > - ❌ 修改 Project 配置 → Admin 的职责
   >
   > 如果你认为需要做以上任何一件事 → **停下来** → 在 Task 评论区 @Orchestrator，附上理由。
   > 不要因为"CLAUDE.md 里有这条规则"就认为你应该执行它。CLAUDE.md 是给所有角色看的通用纪律。
   ```

   **Orchestrator 模板**（P11 实战角色，对称设计，为三角色 Steward 接入预留模式）：

   ```markdown
   # 角色：Orchestrator（编排者）

   > 🚧 能力边界 — 这是你和 Builder 之间的合同，优先级高于项目 CLAUDE.md。
   >
   > 你是 Orchestrator。以下操作**不在你的职责范围内**：
   > - ❌ 直接修改代码/写实现 → Builder 的职责
   > - ❌ 认领 Task 并执行 → Builder 的职责
   > - ❌ 提交 evidence → Builder 的职责
   >
   > 如果你认为某个 Task 需要你亲自写代码 → **停下来**。
   > 要么把 Task 拆得更细、写更清楚的 Verification，要么这个 Task 不该存在。
   > 你的代码是 Prompt 和 Verification 条件，不是实现。
   ```

3. **CLAUDE.md 的定位：跨角色通用纪律，不含角色专属指令**

   CLAUDE.md 顶部加定位声明：

   ```markdown
   > 本文件是**跨角色通用纪律**——所有角色共同遵守的工程规则。
   > 你的角色专属职责、工作流、能力边界 → 以 Protocol API 返回的
   > `role_instructions` 为准。当两处规则冲突时，`role_instructions` 优先。
   ```

   **接受 CLAUDE.md 会继续膨胀的现实**。不追求"变薄"，而是追求"边界清晰"——CLAUDE.md 膨胀的是通用纪律（lint 规则、commit 规范、文件命名），所有角色都需要。角色专属内容不进 CLAUDE.md。

4. **L3 服务端权限是最终防线，不是唯一防线**

   服务端 API 权限模型（`ProjectRole` → 端点守卫）已闭环。L1/L2 的事前围栏减少 403 的发生频率，L3 兜底。L2 的串戏观测协议（见下节）让"等待 403"变成"主动检测"。

5. **L0 人类层：人类操作者是串戏的最大变量**

   L5-L1 管的是 AI 不越界。但 P11 的实际操作场景是：**一个人坐在电脑前，面对 3 个外观完全相同的终端窗口。** 人在错误窗口输入了 Orchestrator 的指令，比 AI 主动越界更可能发生。

   L0 的五个缺口及修复：

   **G1 — 无启动角色宣言。** 三个终端窗口打开后没有任何视觉差异。人类可能把 Builder 窗口当成 Orchestrator 用。

   → 修复：Skill 启动流程的 Step 2（Protocol API 调用）之后，AI **必须先输出角色身份横幅**，再处理任何其他指令。不同角色用不同颜色标识（🟠 O / 🔵 B / ⚪ S）：

   ```markdown
   ## 启动时必须输出（第一条消息，在处理任何请求之前）

   在处理任何请求之前，你必须先输出以下角色身份横幅：

   """
   🟠 Synapse Worker 已连接
      角色: Orchestrator (wa_o_001)
      项目: synapse
      职责: 拆解 Task · 分配 Builder · 验收结果
      边界: 不写代码 · 不认领 Task · 不提交 evidence
   """

   Builder 变体用 🔵 前缀，职责显示「接 Task · 执行 · 收集 evidence · 提交验证」。
   Steward 变体用 ⚪ 前缀，职责显示「审查代码 · 安全检查 · 反馈意见」。
   ```

   **G2 — 无环境变量缺失处理。** 人类开了新终端但忘了设 `SYNAPSE_WORKER_ID` → AI 照样启动，读到 CLAUDE.md，进入未定义角色状态。

   → 修复：SKILL.md Step 1 加**硬终止**逻辑。任一必需环境变量缺失 → AI 输出错误信息并**停止**，不执行任何后续操作：

   ```markdown
   ### Step 1: 检查环境变量（硬门禁）

   确认以下环境变量已设置。**任一缺失 → 立即终止，不继续执行任何操作：**

   - `SYNAPSE_API_URL` — Synapse 实例地址
   - `SYNAPSE_API_KEY` — Agent API Key
   - `SYNAPSE_WORKER_ID` — 你的 Agent ID

   **如果任一变量未设置**，输出以下内容并**停止**：

   """
   ❌ Synapse Worker 启动失败：环境变量不完整。

   缺少: SYNAPSE_WORKER_ID, SYNAPSE_API_KEY

   请设置后再启动：
     export SYNAPSE_API_URL=http://localhost:8000
     export SYNAPSE_API_KEY=sk_xxx
     export SYNAPSE_WORKER_ID=wa_xxx

   ⚠️ 在环境变量完整之前，我不会执行任何操作。
   """
   ```

   **G3 — 无人类指令越界防护。** 负面清单覆盖了"AI 主动越界"，但没覆盖"人类要求 AI 越界"。人类对 Builder 说"拆一下需求" → Builder 可能因为人类的权威而顺从。

   → 修复：角色模板的负面清单加一条"人类越界指令响应"：

   ```markdown
   > 🚧 以下边界同时适用于**你主动的行为**和**人类要求你做的事**。
   > 即使人类明确要求，你也不能越过角色边界。
   >
   > 如果人类要求你做角色外的事 → 这样响应：
   >
   > """
   > ⚠️ 角色边界：我是 Builder，不能 [创建 Task / 分配 Task / 验收]。
   > 请在 Orchestrator 终端窗口提出这个请求。
   > 如果你不确定哪个是 Orchestrator 窗口 → 它的启动横幅是 🟠 色的。
   > """
   ```

   **G4 — 无会话角色不可变性。** 人类说"现在切换到 Orchestrator 模式" → AI 可能顺从 → 同一 session 内混了 O 和 B 的行为，session memory checkpoint 污染。

   → 修复：角色模板加**不可变声明**：

   ```markdown
   > 🔒 角色不可变：本会话的角色在启动时由 Protocol API 确定，不可中途切换。
   > 如果项目需要你以不同角色工作 → 开启新终端窗口，以新角色启动新会话。
   ```

   **G5 — `default "builder"` 掩盖配置错误。** `template_service.py:211`：worker metadata 无 role、query param 也无 role → 静默降级为 builder。一个本该是 Orchestrator 的 Agent 静默变成 Builder，没有任何告警。

   → 修复：在 `ProtocolResponse` 中增加 `role_source` 字段，标明角色来源：

   ```python
   # ProtocolResponse 新增字段
   role_source: Literal["worker_metadata", "query_param", "default_fallback"]
   ```

   当 `role_source = "default_fallback"` → Skill 启动横幅附加 ⚠️ 警告：

   """
   ⚠️ 你的角色未在 Worker 元数据中配置，已默认分配为 Builder。
   如果这不是你的预期角色，请联系 Admin 更新 Worker 配置。
   """

   **G6 — Skill 未加载则全机制失效（致命）。** L0-L5 所有隔离机制都依赖 synapse Skill 被加载。如果人类开了终端、设了环境变量、运行了 `claude`，但**忘了调用 `/synapse`**，Claude Code 只读到 CLAUDE.md——没有任何角色身份。人类说"继续 P11-B1"，AI 开始以未定义角色状态干活。这是整个隔离体系的最薄弱环节。

   → 修复：**CLAUDE.md 自身必须包含启动门禁。** 在角色身份建立之前，拒绝任何会修改仓库或创建 Synapse 资源的请求。这不是 Skill 的责任（Skill 还没加载），是 CLAUDE.md 的责任（它总是被加载）：

   ```markdown
   ## 🚧 会话启动门禁

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
   ```

   **为什么是 CLAUDE.md 而不是 Skill**：Skill 可能不会被加载。CLAUDE.md 一定会被 Claude Code 读取——它是启动时最先进入上下文的内容之一。将门禁放在 CLAUDE.md 中，即使 Skill 完全未被调用，AI 也会拒绝在无角色状态下执行敏感操作。

   **G7 — Protocol API 调用失败无降级（致命）。** 服务器未启动、网络不通 → Skill Step 2 的 HTTP 请求失败。当前 SKILL.md 对该步骤没有任何错误处理。AI 可能在 Protocol API 调用失败后继续工作——又进入了无角色状态。

   → 修复：SKILL.md Step 2 加**重试 + 硬失败**逻辑：

   ```markdown
   ### Step 2: 拉取项目上下文

   调用 Protocol API 获取角色指令。**如果调用失败 → 不允许继续：**

   1. 首次失败 → 等待 5 秒后重试一次
   2. 重试仍失败 → 输出以下内容并**停止**：

   """
   ❌ 无法连接到 Synapse 服务器 (http://localhost:8000)。

   可能原因：
   - 服务器未启动
   - 网络不通
   - SYNAPSE_API_URL 配置错误

   请确认服务器状态后重新加载 Skill。
   ⚠️ 在没有 Protocol API 响应之前，我不会执行任何操作。
   """
   ```

   **G8 — 观测数据源已存在但未在 ADR 中指定。** S1-S3 说"扫描 API 日志/EventStore"，但没有明确查询什么。验证结果：P10-B31 S-065 实现了 Worker 403 拦截器——当 Builder 访问 Orchestrator 专属端点时，`require_project_role` 抛出 `ForbiddenError` → 拦截器触发 `authorization_request.created` 事件写入 EventStore。**数据源已存在**，只需在观测协议中指定查询方式。

   → 修复：观测协议 S1-S3 的收集方式改为：

   ```text
   S1-S3 数据源: EventStore 表
   查询: SELECT * FROM events WHERE event_type = 'authorization_request.created'
   过滤: 按 actor_id（Worker）、request_type（端点模式）统计跨角色访问次数
   每次 Batch 提交前执行
   ```

   **G9 — 角色模板缺乏操作层 HOW（边界，非本 ADR 范围）。** 模板说 Orchestrator "监工"、Builder "查看可认领 Task"，但没说怎么做。轮询还是推事件？频率多少？这不是串戏问题，但会导致 AI 不知道如何实际执行角色——然后自己发明监控方式，可能产生非预期行为。

   → 不在此 ADR 中解决。属于 P11-B1 角色模板升级中"操作流程具体化"的工作项。ADR 只负责隔离边界。

   **G10 — 会话中后期人类忘记窗口角色（客户端限制）。** 终端滚动 200 行后，🟠 启动横幅早已不可见。人类在 Builder 窗口说"拆一下需求"→ L0/G3 拒绝模板触发，但①浪费了一轮对话 ②人类可能因被拒绝而困惑。理想的修复是终端 prompt 包含角色前缀（`[🔵 Builder] $`），但这需要 Claude Code 客户端配置，不在 Synapse 模板控制范围内。

   → Synapse 可控部分：角色模板的拒绝响应中带上"你是 Builder，请在 🟠 Orchestrator 窗口提出此请求"的提示。不可控部分：终端 prompt 自定义需要 Claude Code 客户端侧配置。

   ---

## 观测协议：如何判断"串戏了"

> "观察实际串戏频率再决定是否升级"不是可执行的承诺。以下定义具体的**串戏观测协议**，在 P11 每批结束后执行。

### 信号定义

| 信号 | 层 | 检测方式 | 含义 |
|:---|:--:|:---|:---|
| **S1** | L3 | Builder 的 API Key 命中 403，且端点是 O 专属（`POST /tasks` 创建、`POST /tasks/{id}/assign`、`POST /verifications/{id}/verify`） | Builder 尝试做 Orchestrator 的事 |
| **S2** | L3 | Orchestrator 的 API Key 命中 403，且端点是 B 专属（`POST /tasks/{id}/claim`、`POST /tasks/{id}/submit`） | Orchestrator 尝试做 Builder 的事 |
| **S3** | L2 | 同一 Worker 在一个 session 内混合了两种角色的 API 调用模式（如 B 调了 `assign` 又调了 `claim`） | 角色行为边界模糊 |
| **S4** | L1 | Builder 的 session checkpoint 🧭 段包含 O 行为描述（"拆解了 Task""创建了 Verification"等） | AI 在"思考"层面越界 |
| **S5** | L1 | Orchestrator 的 session checkpoint 🧭 段包含 B 行为描述（"修改了代码""实现了功能"等） | AI 在"思考"层面越界 |
| **S6** | L2 | Task 评论区出现跨角色指令（Builder 给另一个 Builder 分配 Task、Builder 修改 Verification 条件） | 通过平台 UI 的越界行为 |
| **S7** | L3 | Steward 的 API Key 命中 403，且端点是 O/B 专属（`POST /tasks`、`POST /tasks/{id}/claim` 等） | Steward 尝试做 O 或 B 的事 |
| **S8** | L1 | Steward 的 session checkpoint 🧭 段包含 O/B 行为描述 | AI 在"思考"层面越界 |

> S7-S8 为三角色完整覆盖预留。P11 实战无 Steward 客户端 → 这些信号在 P11 阶段始终为 N/A，不参与判定。

### 收集方式

| 信号 | 收集工具 | 频率 |
|:---|:---|:---|
| S1-S3, S7 | `tools/check-role-isolation.sh` — 查询 EventStore 中 `authorization_request.created` 事件，按 `actor_id` + `request_type` 过滤，统计跨角色访问次数（基于 P10-B31 S-065 Worker 403 拦截器已写入的授权请求事件） | 每批提交前 |
| S4-S5, S8 | Session checkpoint 模板增加"角色边界自审"段（P11-B1 随模板升级落地） | 每次会话 /clear 前 |
| S6 | 人工审查 Task 评论区（P11 阶段不做自动化） | 每批回顾时 |

### Session Checkpoint 角色边界自审模板

每个 session checkpoint 文件新增必填段。**按角色分三个版本**（模板渲染时根据 `role` 参数选择）：

```markdown
## 🔒 角色边界自审 — Builder

| 检查项 | 结果 |
|:---|:---:|
| 本会话是否尝试过创建 Task？（O 的职责，B 不应做） | ✅/❌ |
| 本会话是否尝试过分配 Task 给其他 Worker？（O 的职责） | ✅/❌ |
| 本会话是否尝试过验收/打回 Task？（O 的职责） | ✅/❌ |
| 本会话是否因权限不足收到过 403？ | ✅/❌（如❌，附 endpoint） |
| CLAUDE.md 中是否有规则与 role_instructions 冲突？ | ✅/❌（如❌，附具体规则） |
```

```markdown
## 🔒 角色边界自审 — Orchestrator

| 检查项 | 结果 |
|:---|:---:|
| 本会话是否直接修改了代码/写了实现？（B 的职责，O 不应做） | ✅/❌ |
| 本会话是否认领并执行了 Task？（B 的职责） | ✅/❌ |
| 本会话是否提交了 evidence？（B 的职责） | ✅/❌ |
| 本会话是否因权限不足收到过 403？ | ✅/❌（如❌，附 endpoint） |
| CLAUDE.md 中是否有规则与 role_instructions 冲突？ | ✅/❌（如❌，附具体规则） |
```

```markdown
## 🔒 角色边界自审 — Steward

| 检查项 | 结果 |
|:---|:---:|
| 本会话是否直接修改了代码/写了实现？（B 的职责，S 不应做） | ✅/❌ |
| 本会话是否创建/分配了 Task？（O 的职责，S 不应做） | ✅/❌ |
| 本会话是否因权限不足收到过 403？ | ✅/❌（如❌，附 endpoint） |
| CLAUDE.md 中是否有规则与 role_instructions 冲突？ | ✅/❌（如❌，附具体规则） |
```

> ✅ = 行为符合角色边界，❌ = 出现越界。Steward 版预留给三角色完整形态。

### 判定矩阵

| 等级 | 条件 | 动作 |
|:---:|:---|:---|
| 🟢 零串戏 | S1-S6 全部为零 | 无动作 |
| 🟡 轻微串戏 | S1+S2 ≤ 2 次/批，S3-S6 = 0 | 在 Batch 回顾中记录，不阻断。连续 2 批 🟡 → 升级为 🔴 |
| 🔴 严重串戏 | S1+S2 > 2 次/批，或 S3-S6 任一 > 0 | **阻断下一批**。必须：(a) 分析串戏根因，(b) 强化角色围栏措辞，(c) 评估是否需要 L4 memory 隔离 |

### 升级路径

```
🟢 → 继续
🟡 → 记录 + 观察
🟡🟡（连续 2 批）→ 自动升级为 🔴
🔴 → 阻断 + 根因分析 + 修复 + 修复批验证
```

### L4 memory 隔离的触发条件

双角色场景下，O 和 B 的 memory 有**天然的内容差异**——O 记录拆 Task/验收决策，B 记录执行中的技术细节。共享 memory 在双角色下风险较低。

**触发 memory 按角色分离的条件**（满足任一即触发）：
- 任一 🔴 串戏事件的根因被判定为"共享 memory 导致上下文污染"
- 或 Steward 前端实现完成、三角色完整形态投入实战时 —— Steward 的审查 memory 与 O/B 的执行 memory 混合可能产生混淆

在此之前，共享 memory 是合理的默认。但 memory 目录结构必须预留三角色命名空间（`memory/orchestrator/`、`memory/builder/`、`memory/steward/`），不在 P11 阶段创建。

---

## 方案对比

| 方案 | 机制 | 可持续性 | 侵入性 |
|:---|:---|:---:|:---:|
| **A. CLAUDE.md 变薄** | 一次性把角色专属规则从 CLAUDE.md 移走 | 🔴 低 — CLAUDE.md 会自然膨胀，治标不治本 | 低 |
| **B. Per-role CLAUDE.md 变体** | `CLAUDE-{role}.md`，通过环境变量/symlink 切换 | 🟡 中 — 维护成本高，多文件需同步通用规则 | 高 — 打破 Claude Code 默认行为 |
| **C. Skill 锚定 + 六层隔离 + 观测协议（本 ADR）** | Skill 建立角色围栏（L1），L0 加固人类操作层，`role_instructions` 优先级高于 CLAUDE.md，每批结束后跑观测协议 | 🟢 高 — 接受 CLAUDE.md 膨胀，围栏 + 观测形成闭环，L0 覆盖人类串戏 | 低 — 改模板内容 + SKILL.md + 新建观测脚本 + ProtocolResponse 加一个字段 |
| **D. 纯服务端强制执行** | 只靠 API 403 阻断，客户端不做角色区分 | 🔴 低 — 大量无效尝试，浪费 token | 无 |

**选 C**。A 不可持续。B 维护成本高且违背 Claude Code 的设计假设。D 是现状的退化版本。

---

## 影响

### 对 P11-B1 的影响

P11-B1 "Skill 架构落地 + 角色隔离基础设施"需要覆盖：

1. `CLAUDE.md` — 加"会话启动门禁"（G6，角色未建立前拒绝敏感操作）+ 定位声明
2. `synapse-client/SKILL.md` — 加"角色围栏"段 + 启动身份横幅 + 环境变量硬门禁 + Protocol API 失败降级（G7，重试+硬失败）
3. `role-builder.md` — 顶部加负面清单 + 人类越界拒绝 + 角色不可变声明（L0/L2）
4. `role-orchestrator.md` — 顶部加负面清单 + 人类越界拒绝 + 角色不可变声明（L0/L2，对称设计）
5. `role-steward.md` — 顶部加负面清单 + 人类越界拒绝 + 角色不可变声明（L0/L2，三角色完整覆盖）
6. `_protocol.md`（新建）— 加角色围栏概念 + L0 人类层概念
7. Session checkpoint 模板 — 增加"角色边界自审"段（O/B/S 三个版本）
8. `tools/check-role-isolation.sh`（新建）— 查询 EventStore `authorization_request.created` 事件，按 `actor_id` + `request_type` 过滤统计 S1-S3/S7（G8）
9. `src/services/template_service.py` — `VALID_ROLES` 补 `ProjectRole.STEWARD`
10. `src/schemas/protocol.py` — `ProtocolResponse` 加 `role_source` 字段（G5）

> P11-B1 开工前重排批次，此处不评估文件数。

### 对 P11-B2~B7 的影响

每批结束后执行观测协议：
- 跑 `check-role-isolation.sh`
- 审查 session checkpoint 的角色边界自审段
- 按判定矩阵分级处理

### 对服务端的影响

极小。`ProtocolResponse` 新增 `role_source: Literal["worker_metadata", "query_param", "default_fallback"]` 字段（G5 修复）。其余无变更。

---

## 未解决的问题（承认边界）

以下问题本 ADR **不解决**：

**Synapse 控制边界之外（客户端限制）：**

1. **Claude Code 的上下文组装顺序**：Synapse 无法控制 Claude Code 如何将 CLAUDE.md、Skill、system prompt 组装成最终上下文。Skill 的"角色围栏"是 prompt 层面的优先级设计，不是机械强制。
2. **AI 的指令遵循能力**：即使角色围栏写得再清楚，AI 仍可能在长对话中"忘记"自己的角色边界。这是 LLM 的固有局限性。观测协议（S1-S8）的作用是**把这种"忘记"从不可见变成可见**——不等人类发现，机械信号先告警。
3. **终端角色视觉标识（G10）**：理想方案是终端 prompt 显示角色前缀（`[🔵 Builder] $`），但这是 Claude Code 客户端配置，不在 Synapse 模板控制范围内。当前只能依赖启动横幅 + 越界拒绝模板中的窗口提示。

**Synapse 控制边界之内但不在本 ADR 范围：**

4. **角色模板操作层完整性（G9）**：模板描述了每个角色"做什么"（职责）但未详细说明"怎么做"（操作流程——轮询频率、WS 订阅、事件响应）。这不造成串戏，但会造成角色执行效率低下。属于 P11-B1 角色模板升级的工作项。

**已接受的风险：**

5. **CLAUDE.md 自我修改**：AI 客户端在工作中可能向 CLAUDE.md 追加规则，这些规则是角色无感的。Synapse 不阻止这个行为（它是 Claude Code 的正常功能），但角色围栏确保追加的通用规则不会覆盖角色边界。
6. **L0 全部机制依赖 prompt 遵循**：G1-G7 所有修复都是 prompt 层面的，没有机械强制。G6（启动门禁）是最接近机械效果的——它在 CLAUDE.md 中，Claude Code 总是加载 CLAUDE.md。但 AI 是否真的"拒绝"取决于它是否遵循指令。**L3 API 硬阻断是对 L0 失效的最终兜底。**

---

## 关联

| 文档 | 关联内容 |
|------|---------|
| `docs/archive/p11-multi-agent-connect.md` | P11 原始规划（已归档·ADR-006 重拆后路线见 track） |
| `docs/architecture.md` §4.5 | Agent 团队模型（三角色设计基线） |
| `docs/templates/role-orchestrator.md` | Orchestrator 角色模板（待加围栏段） |
| `docs/templates/role-builder.md` | Builder 角色模板（待加围栏段） |
| `docs/templates/synapse-client/SKILL.md` | 薄协议层 Skill（待加角色围栏段） |
| `src/services/template_service.py` | Protocol API 渲染逻辑（`resolve_role` 三级解析） |
| `src/schemas/protocol.py` | ProtocolResponse schema |
