# Self-Check: P100-B91

## 🔍 编码前 Scout
- [x] 数据流拉通: GAP-2 检测 staged 代码文件 → 要求 .claude/self-check-*.md 存在 · GAP-3 检测 synapse/ 变更 → 要求 memory/active/*.md 今日更新
- [x] 同类参照: check-plan-mode.sh 模式 — staged 检测 + exit 1 硬阻断
- [x] 用户一句话: 提交代码时自动检查质量三板斧是否完成，未完成则阻断提交

## ✅ 编码后自检
- [x] 乐观路径: 无代码文件 → 跳过 · 有代码+有自检 → 通过 · 有代码+无自检 → 阻断
- [x] 边界状态: 空 staged → 跳过 · 自检文件不完整 → 警告 · skip flag → 绕过
- [x] 对比同类: 与 check-plan-mode.sh 结构一致（标志解析 + staged 检测 + 条件阻断）
- [x] 变更清单口播: 5 files — check-quality-gate.sh (new) + check-checkpoint-freshness.sh (new) + pre-commit (mod) + Makefile (mod) + self-check-P100-B91.md (new) · ≤8 ✅
