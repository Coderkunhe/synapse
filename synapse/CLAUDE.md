# 🚨 第零条：不得回避问题，要深入根因分析，彻底解决问题，要发挥 owner 精神。

# Synapse — 人机混合团队分布式协调平台
> 不存代码，只协调工作。最后更新：2026-08-08（L5 B36→B37 拉通 · P12-B37 ✅ PFL 消化波 1 · 3/13 PFL 闭环 · AP-B37 拆批违规已登记）

本文件是跨角色通用纪律。角色专属职责以 Protocol API `role_instructions` 为准。
完整条款（Why/案例/执行协议）→ [`CLAUDE-rules-pool.md`](CLAUDE-rules-pool.md)。

## 🚨 硬约束

- **God's-eye 不写 `src/` `frontend/src/`** — 发现 bug → VDD 循环（登记 PFL→创建 Task→Builder 修→O 验收）
  - 例外（God's-eye 直接改）：CLAUDE.md · memory · track · pitfalls/lessons/roadmap/reqlog/daily · settings.json · .env · Skill 文件
  - 狗粮期机械门禁：`touch synapse/.claude/dogfood-active` → pre-commit 阻断 `src/` 变更

## 📋 启动自检链（新会话第一步）

```
① 读 memory/active/<topic>.md（SessionStart hook 会告知 memory 路径）→ 确认当前目标 + 下一站
② 读 .claude/l5-checkpoint.json → batchesSinceLastL5 ≥ 2 → 先 L5 拉通
③ .git/hooks/post-commit 存在? → 否 → 告警「hooks 未安装，运行 make hooks」
④ 暗号中 Batch 编号 vs track.next_batch → 不匹配 → 确认
```

## ⚡ 执行规则（if-then）

| # | 触发条件 | 动作 |
|:--|:--------|:-----|
| 1 | commit 前 | `git diff --stat` → >8 src files 或 ≥3 个独立关注点（不同子系统/无依赖的 PFL）→ 拆批（9-12 且全部 ≤3 行机械变更可豁免）· "消化波""批量修复"命名即反模式信号 · 概念独立性优先于文件计数 |
| 2 | batchesSinceLastL5 ≥ 2 | 先 L5 拉通再开新批 → `bash tools/l5-reset.sh --yes "..."` 复位 · L5 一致性五关校验 → `bash tools/check-l5-consistency.sh`（roadmap↔reqlog↔commit↔checkpoint↔CLAUDE.md）|
| 3 | 编码前 | Scout 三问（数据流/同类参照/用户一句话）未答完 → 不写代码 |
| 4 | commit 前 | 自检四问（乐观路径/边界状态/对比同类/变更口播）未过 → 不 commit |
| 5 | 每批完成 | roadmap + reqlog + daily 三同步 |
| 6 | 每天 | daily/YYYY-MM-DD.md 存在? · 同日追加 · 跨天新建 · 忘了从 git log 补 |
| 7 | 新 Batch 启动 | 哪怕 1 行 → 建 Batch → 跑门禁 → 登记 roadmap → 动手 |
| 8 | 同会话 ≥3 批 | /clear 重开 · /clear 前约定暗号写 memory |
| 9 | 遇到模糊点 | 立刻问 · 猜 10 步比问 1 句贵 100 倍 |
| 10 | ⚠️ 发现问题 | 当场修 or 登记 roadmap · "下次再说" = 遗忘 |
| 11 | 同错 ≥2 次 | 提案防呆 · 违纪登记 V-NNN → `docs/process-violations.md` · ≥2 次 → 🔴 升级 |
| 12 | 用户说「应该/以后/最终/长期」 | 当场登记 D-ID → backlog · 不问"要不要登记" |
| 13 | 新批前 | 工作性质匹配 Phase 轨道? · 治理 → P100 · 产品 → P1-P99 |
| 14 | 新批前 | 读 track.next_batch · 跳号 → 确认 · 重复 → 提示已完成 |
| 15 | 变更前 | ≤2 文件+无接口变更 → 口头 plan · 3-4 文件 → EnterPlanMode 精简 · ≥5 → 完整 |
| 16 | pip/package.json 变更 | 立即 make check · 挂 → 回退 |
| 17 | 同规 ≥3 次违反 or 持续资产损失 | P100 紧急批 · 不等 Phase 边界 |
| 18 | commit message | `feat(synapse): Px-By — 描述` · 前缀必含 `synapse:` |
| 19 | /clear 前 | 更新 memory/active/<topic>.md + 更新 MEMORY.md 暗号行 · 含 🧭 D-ID + 🔒 角色自审 |

## 🚨 P12 启动约束（P11 3.25 复盘产物 · 不可跳过）

> P11 9→137 批膨胀 15× 的教训固化。每条约束对应 LL26 的一条教训。P12 全程生效。

| # | 约束 | 来源 |
|:--|:-----|:-----|
| P12-1 | **战略聚焦** — 每批 commit 前自问：「这批离 1O+2B 协作验证更近了吗？」答不上 → 不 commit | LL26 教训 4 |
| P12-2 | **测试同批交付** — `scripts/` 下任何 JS 变更 → 必须 staged 对应 test 文件 | LL26 教训 2 |
| P12-3 | **脚本化优先** — 新规则/约束不得仅存在于 prompt/模板层 → 必须有对应脚本或 hook | LL26 教训 3 |
| P12-4 | **狗粮节奏** — 每 ≤5 批必须跑一次狗粮验证 · batchesSinceLastDogfood ≥ 5 → 阻断下一批 | LL26 教训 1 |
| P12-5 | **范围防火墙** — PRD 范围外的功能蔓延 → P100 治理轨或新 Phase · 禁止混入 P12 | LL26 教训 4 |
| P12-6 | **God's-eye 退出** — 每批需减少一项 God's-eye 手动运维操作 · W1 是 P0 前提 | LL26 教训 6 |
| P12-7 | **「完成」四要素** — 代码 + 测试 + 自愈脚本 + 狗粮验证通过 · 缺一不可 | LL26 教训 5 |

> 详细复盘：`docs/lessons-learned.md` LL26 · `docs/roadmap.md` §Phase 11 未达成目标与根因分析

## 📁 项目结构

```
synapse/
├── CLAUDE.md · CLAUDE-rules-pool.md
├── README.md · PITCH.md · public-pitch.md · CONTRIBUTING.md
├── docs/
│   ├── prd.md · roadmap.md · requirements-log.md · methodology.md · methodology-reference.md
│   ├── data-model.md · data-model-entities.md · protocol.md · architecture.md
│   ├── security-model.md · security-model-appendix.md
│   ├── onboarding.md · onboarding-api-reference.md · glossary.md
│   ├── phase-criteria.md · execution-checklist.md · mvp-boundary.md
│   ├── pitfalls.md · process-violations.md · process-infrastructure.md
│   ├── lessons-learned.md · agent-comparison.md
│   ├── templates/ (L1 _protocol.md · L2 角色+约定 · synapse-client/SKILL.md)
│   ├── decisions/ · integrations/ · plans/ · archive/ · daily/
│   └── research/
├── src/ (FastAPI: models/ schemas/ api/ services/ utils/)
├── frontend/ (React + Vite + TypeScript)
├── tests/ (conftest.py + test_*.py)
├── tools/ (check-* l5-* violations-* post-commit session-* generate-skill)
├── alembic/ · alembic.ini · mypy.ini · pytest.ini
├── requirements.txt · Dockerfile · docker-compose.yml
└── .claude/ (settings.json · l5-checkpoint.json · violations-checkpoint.json)
```

## 📊 当前状态

> 完整历史：`docs/archive/CLAUDE-current-state-history.md`

| 轨道 | 最后 Batch | 下一 Batch |
|:---|:---|:---|
| **P11** | B137 ✅ P11 全量闭环 🎉 | **P12-B1** ✅ D1 Scout |
| **P12** | B37 ✅ PFL 消化波 1 · PFL-131/139/142 闭环 · 3/13 PFL · 701+189=890 tests | **P12-B38** 🔜 PFL 消化波 2
| 🎯 | **P12 目标：1O+2B 三 Worker 协作**（Claude Code / Codex CLI 混搭均可） | 不变 |
| **P100** | B116 ✅ 文档全量刷新 · 13 docs 日期同步 · L5 counter=0 | **P100-B117** 🔜 下一站 |
| **L5** | batchesSinceLastL5=0（B36+B37→L5 拉通完成）| 🟢 正常 |
