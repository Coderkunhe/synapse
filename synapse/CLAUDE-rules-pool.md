# CLAUDE 规则池 — 完整条款参考

> 本文件是 `CLAUDE.md` §执行规则表的完整版本。只在规则被违反或需要查 Why 时读。
> 每条编号对应 CLAUDE.md if-then 表中的同一号码。

---

## 1. 粒度控制（≤8 文件红线）

**Why**：P4-B9 计划 8 文件 → 实际 15 文件（+87%），根因是没有文件数门禁。

**执行协议**：
1. Plan 阶段逐文件列出变更清单 + 计数
2. ≤8 → 放行。9-12 且全部机械变更（≤3 行/文件）→ 可申请豁免，须在 plan 中注明。>12 → 必须拆
3. 用户批准后文件清单锁定，发现新文件需要改 → 新 Batch

**同议题连续层合并豁免**：数据模型→Service→API 三层连续实现，满足以下条件可合并：
- 三层之间无跨议题接口依赖
- Schema/接口变更仅在本议题内传播
- 合并后总文件数 ≤8

> 背景：B28+B29+B30 拆为 3 个微型 Batch，每个产生 6-8 文件文档闭环。合并可减 67% 流程 commit。P100-B70 流程瓶颈修复。

**已知违反**：P11-B55(9), B56(9), B57(10), B88(10)

---

## 2. L5 拉通（每 2 批强制）

**Why**：跨批叙事一致性 + 文档新鲜度 + 状态遍历。累积 ≥2 批未拉通 → 必须先 L5 再开下批。

**执行协议**：
1. 新会话第一步：读 `.claude/l5-checkpoint.json` → `batchesSinceLastL5 >= 2` → 先 L5
2. L5 内容：requirements-log 补登记 + CLAUDE.md/roadmap/daily 同步 + 叙事一致性验证
3. 完成后：`bash tools/l5-reset.sh "Bx→By 拉通完成" --yes` 复位计数器
4. L5 commit message 含 `L5`/`拉通` → post-commit.sh 跳过计数递增
5. 机械门禁：`tools/l5-gate.sh` 接入 `.git/hooks/pre-commit` → batchesSinceLastL5 ≥ 2 硬阻断

**V-024 防呆**：不允许 commit 时才被动补救。新会话启动就检查。

**已知违反**：B101 commit 前未做 L5 自检（事后 P11-L5-B101 补票）

---

## 3. Scout 三问（编码前 · 不跳）

**Why**（B44 复盘）：
- `status=all` 正则不匹配 → 没看 API pattern
- `.shell max-width:960px` 与其他页不一致 → 没对比同类页面
- 卡片只搬字段不加工 → 没想用户看到什么

**三问**：
```
☐ 数据流拉通：API 参数约束（regex/pattern/enum）、返回字段、权限要求
☐ 同类参照：至少看一个类似页面/组件的实现，确认没有另辟蹊径
☐ 用户一句话：做完这个操作，用户看到什么、解决什么问题
```

**B44 教训**：B35-B44 连续 10 批返工率高——不做 Scout 就写代码。CLAUE.md §7.1 落地。

---

## 4. 自检四问（commit 前 · 不跳）

**Why**（B44 复盘）：
- "全部筛选 0 条"（边界状态没测）
- "卡片只显示 API 字段"（用户视角没验）

**四问**：
```
☐ 乐观路径：正常流程走通（有数据时页面正确渲染）
☐ 边界状态：空数据/加载中/错误/筛选切换 — 逐条件验证互斥
☐ 对比同类：和同类页面放一起看，风格/宽度/交互是否一致
☐ 变更口播：改了哪些文件、文件数 ≤8、是否有非预期文件混入
```

---

## 5. 文档闭环（每批三同步）

**Why**：需求→执行→验证→日志四步闭环。

**三文件**：
- `docs/roadmap.md` — 宏观进度
- `docs/requirements-log.md` — 微观交付记录（含 L1-L4）
- `docs/daily/YYYY-MM-DD.md` — 日报

---

## 6. 日报铁律

**Why**：从 GlassCortex 移植。没有日报 = 没有可追溯的工作记录。

**规则**：
- 同日追加 · 跨天新建 · 忘了从 git log 反推补写（注明「补」）
- 机械门禁：`tools/check-docs.sh` 检查昨天日报是否存在（缺失告警，不阻断）

---

## 7. Batch 启动门禁

**Why**：哪怕改 1 行也要走完整流程。V-005 防呆。

**机械载体**：`docs/execution-checklist.md` — 启动前/编码中/提交前/提交后/Phase 结束五段式。

---

## 8. 会话刷新（≥3 批 /clear）

**Why**（B44 复盘）：10 批塞在 12 小时内，后半段上下文膨胀、反复读文件、判断力下降。

**执行协议**：
- 同会话累积 3 批 → /clear 重开
- 第 3 批 commit 后主动提醒
- 例外：连续微型批（🟢 纯文档）可放宽至 5 批，需 commit message 注明
- /clear 前：约定暗号 → 写 memory/active/<topic>.md → 更新 MEMORY.md

---

## 9. 即时澄清

**Why**：AI 静默走错方向 10 步比开口问 1 句贵 100 倍。

**规则**：模糊点立刻问，不靠假设推进。

---

## 10. 发现即待办

**Why**："下次再说" = 遗忘。发现 = 待办。

**规则**：任何 ⚠️ 发现同一会话内必须 (a) 当场修复 or (b) 登记 roadmap backlog。

---

## 11. 流程共建（违纪体系）

**Why**：AI 不只是执行者，也是流程 owner。相同错误不超过 2 次。

**执行协议**：
- 每次违纪登记 V-NNN → `docs/process-violations.md`
- 同一规则累计 2 次 → 🔴 升级 + 必须落地机械防呆
- 机械门禁：`make check-violations` · 硬阻断：距上次违纪回顾 ≥5 批
- 复位：`bash tools/violations-review.sh "<描述>"`
- 防呆路线图：`docs/process-violations.md` §防呆可行性评估

---

## 12. 讨论即登记（Discussion → Backlog）

**Why**（P6 闭环发现）：4 个战略讨论蒸发，根因是「讨论→session memory→下个会话丢失颗粒度」。P100-B14 落地。

**触发句式**：「应该…」「以后要…」「最终…」「长期来看…」「理想情况下…」

**执行**：
1. 判定讨论类型 → 登记到对应目的地（backlog/pitfalls/lessons/P100）
2. session memory 中记录 D-ID（5 列格式：D-ID/摘要/目的地/目标ID/状态）
3. 不问"要不要登记"——默认登记

**路由矩阵**：
- 战略方向 → Phase Backlog (P{N}-XXX)
- 治理/工具链 → P100 (G-XXX)
- 技术踩坑 → pitfalls (P-NNN)
- 可迁移方法论 → lessons (LL#)
- 功能细节 → master-backlog P2 (S-XXX)

**机械门禁**：`tools/check-discussions.sh` 检测孤儿 D-ID。

---

## 13. Phase 治理（轨道路由）

**Why**（P11-B20 事故）：G-028 是治理基础设施，被当作 P11-B20 产品批执行，污染了 P11 track。

**判定**：
| 工作性质 | 正确轨道 |
|---------|:---:|
| 产品功能（PFL/API/前端/狗粮） | P1-P99 |
| 治理基础设施（工具链/门禁/防呆/技术债） | P100-P199 |

**执行**：治理工作被分配到 P1-P99 → 拒绝并建议切 P100。

---

## 14. 批次顺序校验

**Why**（P100-B13 跳号事故）：AI 跳过未完成的 B13 直接执行 B14。

**执行**：
1. 读 track 文件的 `last_batch` / `next_batch`
2. 用户指定的 Batch == next_batch → 放行 · 跳号 → 确认 · 重复 → 提示
3. 完成后更新 track 指针

---

## 15. Plan 分级制度

**Why**：不是所有变更都需要完整 EnterPlanMode。微型 Batch 的往返开销 > 编码开销。

| 级别 | 条件 | Plan 方式 |
|:---:|------|---------|
| 🟢 | ≤2 文件 + 无接口变更 | 口头 plan，不 EnterPlanMode |
| 🟡 | 3-4 文件 or 接口变更 | EnterPlanMode 精简 |
| 🔴 | ≥5 文件 or 架构变更 | EnterPlanMode 完整 |

**Scout→Execute 重评**：Scout 发现范围超过原分级 → stop + 重走 Plan 流程（不等 hook 拦截）。

---

## 16. 依赖升级纪律

**Why**：依赖升级是最常见的"看起来无害其实爆炸"的操作。

**规则**：pip/package.json 变更 → 立即 make check → 挂 → 回退。版本锁定在 requirements.txt。

---

## 17. 流程紧急修复

**Why**（B28-B40 事故）：13 批 Dogfooding 零条登记，流程缺陷持续造成知识蒸发。

**触发条件**（满足任一）：
1. 同规违规 ≥3 次
2. 持续资产损失
3. 阻断后续 Phase

**执行**：P100 紧急批 · 止血措施落地 + 防呆上线 · 不等 Phase 边界。

---

## 18. Commit 格式

**Why**：monorepo 中与 glasscortex 共享 git log，不加项目前缀无法追溯。

**格式**：`feat(synapse): Px-By — 简短描述`

**机械门禁**：`tools/check-commit-prefix.sh` → commit-msg hook。

---

## 19. 接头暗号（多窗口隔离）

**Why**：多窗口同时工作（landing/p11/p100），/clear 后新会话需秒级接上。

**五步**：
1. 确定 topic slug
2. 约定暗号（`继续 <topic> — <下一站>`）
3. 写 memory/active/<topic>.md（含 🧭 D-ID + 🔒 角色自审表）+ session checkpoint
4. 更新 MEMORY.md 🟢 Active Sessions 表
5. 新会话首条暗号 → 匹配 topic → 读 active 文件 → 接上

**机械防呆**：`tools/session-checkpoint.sh` 检查 checkpoint 存在+暗号+今日更新。

---

## 附录：五层自检金字塔

```
L1 结构层 — lint+typecheck+build
L2 引用层 — import·API·配置 key 真实存在
L3 契约层 — schema snapshot+消费者检查
L4 场景层 — E2E 测试+浏览器验证（后端可跳过浏览器）
L5 拉通层 — 叙事一致性+文档新鲜度（每 2 批执行）
```

**分级矩阵**：按变更类型选择性执行。纯文档跳过 L2-L4 · UI 只做 CSS L2 · 后端跳过 L4 浏览器。

详见 `docs/methodology.md` §4 五层分级矩阵。
