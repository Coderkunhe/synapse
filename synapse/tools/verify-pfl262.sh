#!/usr/bin/env bash
# verify-pfl262.sh — P16-B7 PFL-262 独立校验（打印原始证据，不自动放行）
#
# 可靠性设计（为什么可信）：
#   1. 只调 git/pytest/grep/bash 这些被战验过的工具，不自算结论，不打印「✅ 通过」
#   2. 唯一脆弱的变异步骤带自检：锚点命中数必须 ==1，否则 assert 崩溃 + 还原源码
#   3. 退出码 = 「步骤跑完」，≠「修复正确」——结论由人读变异前后两份 pytest 输出之差
# 用途：一次性校验脚本，验完可删（锚点硬编码本批源码，不随代码演进）
set -uo pipefail

cd "$(dirname "$0")/.."

echo "═══ ① driver 语法（bash -n）═══"
bash -n tools/start-worker.sh && echo "  bash -n 通过" || { echo "  ❌ bash -n 失败"; exit 1; }

echo
echo "═══ ② 根因 CLAIM 独立复核 ═══"
echo "--- 后台调度列表（应无 failure_detector）---"
grep -n "asyncio.create_task" src/main.py
echo "--- run_all_detections 调用方（应只有 admin.py）---"
grep -rn "run_all_detections\|detect_heartbeat_failures" src/ --include='*.py' | grep -v 'failure_detector.py' || echo "  （无其它调用方）"

echo
echo "═══ ③ 红绿变异测试 ═══"
F=src/services/stale_task_detector.py
BAK=/tmp/stale_task_detector.py.bak
cp "$F" "$BAK"
trap 'cp "$BAK" "$F" 2>/dev/null' EXIT

python3 - "$F" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
needle = "    return last_hb >= datetime.now(timezone.utc) - timedelta(seconds=timeout)"
assert s.count(needle) == 1, f"锚点命中 {s.count(needle)} 次 → 脚本与当前源码不匹配，拒绝变异"
open(p, "w").write(s.replace(needle, "    return False  # MUTATED"))
PY
grep -q "MUTATED" "$F" || { echo "  ❌ 变异未生效，abort（源码已还原）"; exit 1; }

echo "--- 变异后 pytest（期望：2 个新测试变红）---"
.venv/bin/python -m pytest tests/test_stale_task_detector.py -q 2>&1 | tail -3

cp "$BAK" "$F"
echo "--- 还原后 pytest（期望：全绿）---"
.venv/bin/python -m pytest tests/test_stale_task_detector.py -q 2>&1 | tail -3

echo
echo "═══ ④ 人工审以下 diff（重点：断言是否被削弱）═══"
git diff -- src/services/stale_task_detector.py tests/test_stale_task_detector.py

echo
echo "═══ 完成。⑤ 完整门禁请手动跑：make check ═══"
