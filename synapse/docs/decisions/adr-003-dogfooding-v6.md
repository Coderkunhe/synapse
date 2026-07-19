# ADR-003: Dogfooding v6 — PM 视角审计是产品迭代的核心引擎

- **Status**: Accepted
- **Date**: 2026-07-15
- **Deciders**: P9-B75
- **References**: P9-B68（审计） → B69 → B70 → B71 → B72 → B73 → B74（修复链）

## Context

Synapse 是面向人机混合团队的分布式协调平台。P9 产品主线从 B1 开始已经历 74 个 Batch，功能迭代速度快，但缺少系统性的"用自己产品"的反馈闭环。P9-B68 首次以 PM 视角做了一轮完整的 Dogfooding 审计——用假想项目 "Phoenix" 走完从项目创建、Worker 注册、Batch 创建、Task 分配到 claim→submit→verify 的完整生命周期。

B68 审计产出 **8 项 friction**（使用阻碍）和 **5 项 missing cap**（功能缺口），随后 B69→B74 用 7 个 Batch 在 ~24 小时内完成 12/13 项的闭环（仅 M-B68-N5 远期留存）。

## Decision

**Dogfooding 作为 Synapse P9 产品主线的持续迭代引擎，每 5-10 Batch 执行一轮 PM 视角全链路审计。**

### 产出分类标准

| 类别 | 定义 | 示例 |
|------|------|------|
| **Friction** | 已有功能但使用体验有阻碍 | priority 字段接受 p0-p3 但未文档化 → 422 |
| **Missing Cap** | 功能不存在，影响 PM 工作效率 | 无项目进度视图 → 需逐个项目手动统计 |

### 优先级路由

| 优先级 | 条件 | 目标 Batch 窗口 |
|:---:|------|:---:|
| **P0 Blocking** | 阻断完整工作流闭环 | 下一批（B69） |
| **P1 Doc/Schema** | 功能正常但缺少文档或格式约束未暴露 | 2 批内（B70） |
| **P2 Feature** | 新能力，非阻塞 | 3-5 批内（B71-B74） |

### 执行协议

1. **审计阶段**（1 Batch，0 代码变更）：以 PM 身份走完整链路，记录每个卡点
2. **分类阶段**（同 Batch 内）：friction vs missing cap + 严重度 + 优先级路由
3. **修复阶段**（n Batch）：按优先级顺序逐批闭环
4. **总结阶段**（1 Batch）：ADR 归档 + 方法论沉淀

## Consequences

### Positive

- **12/13 项 24h 内闭环**：7 friction + 4 missing cap 在 B69→B74 完成，验证了"发现→分类→修复"管道的效率
- **方法论沉淀**：LL15（schema Field pattern 必须配 description）+ LL16（Batch 拆分是 Plan 阶段决策，不是 Execution 补丁）直接源于本轮
- **S-032/033/034 全链路可追溯**：三个能力从 B68 发现 → B71/B72/B73+B74 交付的完整叙事链
- **零代码审计**：B68 本身不写代码，证明"先走一遍再用"的方法对产品方向校准有效

### Negative

- **V-008#2 子编号复发**：B73/B74 本应在 Plan 阶段就分配独立编号（B73 + B74），实际在 Execution 阶段临时发明 B73a/B73b。子编号是"Plan 失败后拒绝承认"的补丁
- **V-022 首次登记**：B73a commit 后未 `/clear`，同一会话直接继续执行 B73b。post-commit hook 的软建议被忽略，需升级为硬阻断

### Known Tech Debt

| 项 | 状态 | 计划 |
|----|------|------|
| V-022 防呆升级 | post-commit hook 软建议 → 硬阻断 (exit 1) | P100-B31 |
| M-B68-N5 跨项目任务视图 | 本轮唯一未闭环项 | 下一轮 Dogfooding 重评优先级 |
| S-016 Agent→Worker 数据模型层重命名 | 远期治理项 | P100 治理批 |

### Discovered Patterns

| 模式 | ID | 描述 |
|------|-----|------|
| Schema description 纪律 | LL15 | `Field(pattern=...)` 必须配 `description="..."`，否则 Swagger UI 看不到格式说明 |
| Plan 阶段拆分 | LL16 | Plan 阶段发现范围超 8 文件红线 → 必须在 Plan 中分配独立编号，不在 Execution 发明子编号 |
| 契约层 fresh-eyes | LL14 | 契约层变更在关闭前必须经 fresh-eyes 复审，同批自审 ≠ 充分 |

---

## B68→B74 修复链

```
B68: 审计发现（8 friction + 5 missing cap）
 │
 ├─ B69: P0 blocking — description required + verifications optional
 ├─ B70: P1 doc — priority/effort/evidence/summary Field descriptions
 ├─ B71: P2 feature — 项目进度 Dashboard（M-B68-N1）
 ├─ B72: P2 feature — 批量任务操作（M-B68-N3）
 ├─ B73: P2 feature — Worker 负载视图（M-B68-N4）
 └─ B74: P2 feature — deadline 提醒（M-B68-N2）
                        │
                        └─ M-B68-N5 远期留存（跨项目视图）
```

### Friction 全量闭环

| ID | 摩擦 | 严重度 | 修复 Batch |
|----|------|:---:|:---:|
| F-B68-N1 | priority 使用 p0-p3 而非标准格式 → 422 | 🟡 | B70 |
| F-B68-N2 | estimated_effort 有未文档化的格式约束 → 422 | 🟡 | B70 |
| F-B68-N3 | verifications 在 Task 创建时 REQUIRED | 🟠 | B69 |
| F-B68-N4 | 每次操作需要 expected_version → 需先 GET | 🟡 | B72 |
| F-B68-N5 | description 创建时可选但 ready 时拒绝 | 🟠 | B69 |
| F-B68-N6 | evidence 类型预期 dict 而非 string | 🟡 | B70 |
| F-B68-N7 | summary 在 submit 时 REQUIRED | 🟡 | B70 |
| F-B68-N8 | Verify expected_version 引用 task 版本 | 🟡 | B63 |

### Missing Cap 全量闭环

| ID | 能力 | 修复 Batch | Backlog |
|----|------|:---:|:---:|
| M-B68-N1 | 项目进度 Dashboard | B71 | S-032 |
| M-B68-N2 | deadline 提醒 + overdue | B74 | S-034 |
| M-B68-N3 | 批量任务操作 | B72 | S-033 |
| M-B68-N4 | Worker 负载视图 | B73 | — |
| M-B68-N5 | 跨项目任务视图 | 远期 | ⬜ |
