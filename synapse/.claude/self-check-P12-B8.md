# P12-B8 自检 — SessionStart hook 诊断 + Codex Worker 狗粮

## Scout 三问

1. **数据流**：SessionStart hook → session-init.js main() → fs.writeFileSync(sentinel, timestamp) → Worker SKILL.md 第一步读取 → 判断 hook 健康状态
2. **同类参照**：PFL-127 B135（hook 失败存活）→ B8 升级为"hook 未触发的可观测性"
3. **用户一句话**："Worker 启动后能知道自己 hook 有没有触发，不用盲猜"

## 自检四问

1. **乐观路径** ✅：hook 触发 → sentinel 写入 → SKILL.md 检查「存在 + ≤5 分钟」→ 正常流程
2. **边界状态** ✅：hook 从未触发 → sentinel 不存在 → SKILL.md 显示「🔴」→ 手动运行 session-init.js
3. **对比同类** ✅：PFL-127 让 session-init.js 在 hook 失败时存活（不 crash），B8 让 Worker 知道 hook 是否真的触发了（可观测性）。互补。
4. **变更口播**：3 JS template files · 0 src/ files · 678 tests 零回归

## 变更清单

| 文件 | 变更 | 行数 |
|:---|:---|:--:|
| session-init.js | HOOK_SENTINEL 常量 + main() 第一行写入 | +9 |
| SKILL.md | 第一步新增 sentinel 健康诊断表 | +12 |
| prompts.js | CronCreate prompt 第①步 sentinel 检查 | +8/-4 |

## 环境基线

| 指标 | 值 |
|:---|:---|
| tests | 678 passed · 0 failed |
| server health | ok |
| hooks | 3/3 就位 |
| L5 | batchesSinceLastL5=0→1（B8 不触发 reset） |

## L5 Checklist

- [x] roadmap.md: B8 登记 · header 日期刷新
- [x] requirements-log.md: B8 登记
- [x] daily/2026-08-05.md: B8 条目
- [x] track/synapse.md: last_batch=B8 · next_batch=B9
- [x] CLAUDE.md: P12 当前状态刷新
- [x] L5: batchesSinceLastL5=1（B9 触发 reset）
