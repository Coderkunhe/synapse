# P12-B7 自检 — L5 拉通 + 狗粮验证

## Scout 三问

1. **数据流**：bootstrap-worker.sh (dry-run) → BOOT-1~7 step-by-step → Server health API → Task lifecycle API (create→ready→claim→submit→verify)
2. **同类参照**：B4 狗粮模式（daemon 存活 + Codex live）· B6 bootstrap 单文件
3. **用户一句话**："用 bootstrap-worker.sh 一键创建 Worker，跑通 Task 全生命周期"

## 自检四问

1. **乐观路径** ✅：bootstrap dry-run 通过 · Server 健康 200 · Task 生命周期 create→ready→claim→submit 全链路通过
2. **边界状态** ✅：自验证门禁 SELF_VERIFICATION_NOT_ALLOWED 按设计拒绝 · post-commit hook 幂等安装 · check-hooks.sh 3/3 验证
3. **对比同类** ✅：B4 狗粮 vs B7 狗粮 — B7 新增 bootstrap 自动化验证 + API 生命周期验证（B4 仅有 daemon 存活验证）
4. **变更口播**：docs (roadmap + reqlog + daily + track + CLAUDE.md) · 代码变更：0 src files（纯文档 + 治理批）

## 环境基线

| 指标 | 值 |
|:---|:---|
| tests | 678 passed · 0 failed |
| hooks | pre-commit ✅ · commit-msg ✅ · post-commit ✅ |
| server health | ok · ws_connections=2 · reapers all running |
| bootstrap | dry-run 7/7 BOOT steps |

## L5 Checklist

- [x] roadmap.md: B6+B7 登记 · header 日期刷新
- [x] requirements-log.md: B6+B7 登记
- [x] daily/2026-08-05.md: B6+B7 条目
- [x] track/synapse.md: last_batch=B7 · next_batch=B8
- [x] CLAUDE.md: P12 当前状态刷新
- [x] pitfalls.md: 无新增 PFL（本批纯治理+验证）
- [x] l5-reset.sh: 已执行

## P1 登记（→ B8）

- HK-3: SessionStart hook 沉默失败（R5 两个终端 hook 静默失败）
- Codex Worker 狗粮：B5 API 状态通道完成完整 Task
