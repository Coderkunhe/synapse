# Synapse 执行 Checklist

> 每个 Batch 启动时逐项确认，零例外。
> 最后更新：2026-08-07（P100-B116 文档全量刷新 · 机制持续有效 · 无需变更）
>
> 来源：CLAUDE.md §7 Batch 启动门禁 + 违纪 V-005/V-009/V-013/V-014/V-016/V-017/V-019 防呆

---

## 启动前（Batch Start）

- [ ] **V-005** — 即使是 ≤2 行改动，也必须走完整流程：Batch 编号 → Plan（按 §13 分级）→ TaskCreate → roadmap 登记 → 动手。**零例外。**
- [ ] **§4 粒度门禁** — 逐文件列变更清单，计数 ≤8。≥9 必须拆分。
- [ ] **§12 批次顺序** — 读 track 文件，确认 `next_batch` 匹配。跳号须用户显式确认。
- [ ] **§13 Plan 分级** — 微型(≤2文件)口头 Plan / 标准(3-4)精简 Plan / 大型(≥5)完整 Plan。V-003 防呆已上线。

## 编码中（During）

- [ ] **§1 五层自检** — 按变更类型选择性执行 L1-L4（参照五层分级矩阵）
- [ ] **逐文件验证** — 写完一个文件立刻验证，不等攒批
- [ ] **V-009** — 批量改名/统一命名前，先 grep 全项目引用理解语义上下文。同一名称在不同上下文中可能有不同含义，盲目统一会导致语义丢失。
- [ ] **V-019** — Dogfooding/调试/使用中发现的任何问题、踩坑、心得 → **当场登记**到 `docs/pitfalls.md`（技术踩坑）或 `docs/lessons-learned.md`（可迁移经验）。不得仅修复不登记。"修了就完了" = 知识蒸发。**零例外。**

## 提交前（Pre-Commit）

- [ ] `make check` — 完整门禁管道（自动阻断：L5 gate · schema audit · plan mode）
- [ ] **V-004** — Python 代码变更须通过 `make check-types`（mypy）
- [ ] `make check-frontend` — 前端代码变更须通过 oxlint + tsc
- [ ] **V-019** — 确认本批 Dogfooding/调试/使用期间的发现已全部登记到 `docs/pitfalls.md` 和 `docs/lessons-learned.md`。**漏一条 = 知识蒸发一条。**
- [ ] **V-016** — 本批含批量替换（`replace_all` / `sed` / IDE 重构）→ 用 `grep -n '<旧模式>' src/` 确认零残留，抽样验证 ≥20% 文件。
- [ ] **文档闭环** — `docs/roadmap.md` · `docs/requirements-log.md` · `docs/daily/YYYY-MM-DD.md`

## 提交后（Post-Commit）

- [ ] **🧬 Synapse 自举同步** — 本批的 Batch 标识和至少 1 个代表性 Task 追加到 `tools/seed-synapse-project.py` 的 `P9_BATCHES`/`P9_TASKS` 常量中。运行 `make seed-synapse` 同步到 DB。这是 P7-002「用 Synapse 管 Synapse」的持续性落地——种子脚本是活的，不是一次性播种。小批顺手加，不攒批。

- [ ] **Track 指针** — 更新 `tracks/synapse.md` 的 `last_batch` / `next_batch`
- [ ] **CLAUDE.md 状态** — 更新「当前状态」段
- [ ] **V-012** — 本会话 ≥2 Batch → 主动建议 `/clear`
- [ ] **V-013** — 交付后主动输出 L5 累积计数（当前 x/2）+ 上下文窗口预估 + 是否需要 /clear 的建议。不等用户问。
- [ ] **Session checkpoint** — 写 memory checkpoint + 更新 MEMORY.md 索引

## Phase 结束（Phase Close）

- [ ] **V-017** — Phase completion 量化验证：① 本 Phase 计划 Batch 数 __，已 commit __，完成率 __% ② 所有 Batch commit 已 push ✓ ③ `make check-docs` 文档新鲜度通过 ✓ ④ 未闭合的 S-XXX/P-XXX 已迁移到新 Phase backlog（不允许"完成后再说"）
- [ ] **V-014** — 本 Phase 主要返工/摩擦点回顾：是否有 ≥2 次重复模式可落地为规则/工具/checklist？如有，先登记再关 Phase（CLAUDE.md / methodology.md / 新工具脚本）
- [ ] **L5 拉通** — 每 2 批强制执行，运行 `l5-reset.sh` 复位计数器
- [ ] **违纪回顾** — 累积 5 批触发，运行 `violations-review.sh`

---

## 使用方式

1. **SessionStart hook 加载** — CLAUDE.md 在每会话启动时加载，§7 指向本文件
2. **AI 自检** — 每 Batch 启动前，AI 必须过一遍「启动前」段
3. **机械门禁** — `make check-execution-checklist` 验证本文件存在且格式完整
4. **Pre-commit 提醒** — pre-commit hook 输出 checklist 摘要行
