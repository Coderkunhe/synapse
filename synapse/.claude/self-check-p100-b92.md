# Self-Check — P100-B92 · GAP-4 批次顺序机械校验

## 🔍 编码前 Scout（三问）

- [x] **数据流拉通**：commit-msg hook 接收 `$1`=commit message 文件路径 → `check-batch-sequence.sh` 解析 `P\d+-B\d+` → 对比 `tracks/synapse.md` HEAD `next_batch`(YAML+table) + staged pointers → 至少一个匹配→通过；零匹配→exit 1
- [x] **同类参照**：`check-commit-prefix.sh`(76行 commit-msg hook)、`check-quality-gate.sh`(140行 pre-commit gate)、`check-checkpoint-freshness.sh`(同类 gate)、pre-commit wrapper(93行 7-stage pipeline) — 风格一致：`set -euo pipefail`、red/green/yellow 着色函数、escape hatch 模式、git show :path 读取 staged 内容
- [x] **用户一句话**：commit 时若引用的 Batch 编号不匹配 track 文件中任何 next_batch → commit-msg hook 硬阻断，提示正确批次编号，防止 P100-B13 跳号事故重演

## ✅ 编码后自检（四问）

- [x] **乐观路径**：正确批次 (P100-B92/P11-B59) → 通过 · 无批次引用 → 跳过 · L5 commit → 跳过 · escape hatch → 通过
- [x] **边界状态**：跳号(P100-B99)→阻断 · 已完成(P100-B91)→阻断 · 未知 track(P99-B1)→阻断 · 多批次混合→至少一个匹配即通过 · 空 commit message→报错 · track 文件不存在→跳过
- [x] **对比同类**：脚本结构与 check-quality-gate.sh 一致 (flag parsing → detection → validation → error display) · macOS sed -E 兼容 · [[:space:]] 代替 \s · commit-msg wrapper 与 pre-commit wrapper 模式一致
- [x] **变更清单口播**：
  - `synapse/tools/check-batch-sequence.sh` (新建 · ~170行)
  - `synapse/tools/commit-msg` (新建 wrapper · ~30行)
  - `.git/hooks/commit-msg` (替换 copy→symlink)
  - `synapse/Makefile` (修改 · +3行)
  - `synapse/tracks/synapse.md` (修改 · track pointer)
  - `synapse/CLAUDE.md` (修改 · header/batches/summary)
  - `synapse/docs/daily/2026-07-26.md` (修改 · 追加)
  - `synapse/docs/requirements-log.md` (修改 · 登记)
  - **8 files · ≤8 ✅**
