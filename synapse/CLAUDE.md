# 🚨 第零条：不得回避问题，要深入根因分析，彻底解决问题，要发挥 owner 精神。

# Synapse — 人机混合团队分布式协调平台
> 不存代码，只协调工作。最后更新：2026-08-03（B126 ✅）

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
| 1 | commit 前 | `git diff --stat` → >8 src files → 拆批（9-12 且全部 ≤3 行机械变更可豁免） |
| 2 | batchesSinceLastL5 ≥ 2 | 先 L5 拉通再开新批 → `bash tools/l5-reset.sh` 复位 |
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
| **P11** | B126 ✅ PFL-084 daemon 自动升级 + JS 指纹 | **B127** 🔜 PFL 收尾审计 |
| **P100** | B111 ✅ 治理波全量收尾 | — |
| **L5** | B124→B126 ✅ | batchesSinceLastL5=0 |
