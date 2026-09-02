# P16-B9 自检 — active_task_id 收口（PFL-254 源头清理 + PFL-255 批量挂接）

> 批号: P16-B9 · 性质: 平台批（主会话直接改 src · 执行环调度层 · methodology §8 自举死锁例外）· 日期: 2026-09-02
> 根因: `worker.active_task_id` 生命周期不完整 —— B5 只给 claim/assign/start 单任务路径挂了 attach_active_task（批量路径漏），清理端 lease 过期白嫖「心跳会擦」这条已被 B5 删掉的副作用（源头漏）。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 写入端 attach_active_task 已覆盖 claim/assign/start，但 cooperation.py 的 claim_batch/assign_batch 循环里只 set owner 不挂指针 → state_router 无 active_task_id 可路由 execute；清理端 submit 已调 finish_current_task，但 lease_detector.release_expired_leases 清所有权不清指针 → 死指针残留（B5 路由层 resolve_workable_active_task 已兜底不路由，但 DB 字段仍脏）。
- [x] **同类参照** — worker_scheduler.py 已有 attach_active_task（幂等·不抢占）与 finish_current_task（无条件清空）；task_execution.py submit 用本地 `from src.services.worker_scheduler import finish_current_task` 的模式；get_next_task 已实现 FIFO 但 state_router 未用（留 B10）。结论：复用 attach/finish，新增「条件清空」helper。
- [x] **用户一句话** — 用户跑 headless worker 时，批量认领/分配的任务能路由到 execute 而不是死等 claim，租约回收后 Worker 不被死任务指针卡住、能干净回 idle 认领下一单。

## 编码后自检（四问）

- [x] **乐观路径** — idle Worker claim_batch 2 任务 → active_task_id = claimed_ids[0]、runtime_status=BUSY；claim t1 后 lease 过期 → release_expired_leases → release_active_task 清空指针、转 IDLE；test_claim_batch_attaches_active_task / test_lease_expiry_clears_active_task 覆盖。
- [x] **边界状态** — terminate/pause **不清**指针（保留 validate_task_active 检测 task_paused/task_cancelled 的信号，见 test_submit_and_scheduling.py::TestValidateTaskActive）；release_active_task 仅当 worker.active_task_id==task_id 才清（防误清其它活跃任务，test_lease_expiry_does_not_clear_other_active_task 覆盖）；worker_id=None/member 时 db.get(Worker,..) 返回 None 安全 no-op。
- [x] **对比同类** — 复用 attach_active_task/finish_current_task 既有入口，不重造状态机；release_active_task 是 finish_current_task 的保守变体，本地 import 对齐 task_execution 既有模式；mypy 零新增错误（claim_batch 用 db.get 重取拿非空类型）。
- [x] **变更清单口播** — 6 文件 ≤8 上限：worker_scheduler.py(+release_active_task) · cooperation.py(claim_batch/assign_batch 挂接) · lease_detector.py(条件清空) · task_execution.py(docstring 修正) · test_p16_b5_execution_loop.py(+2) · test_cooperation.py(+2) · 997 tests（993 基线 + 4 新增，零回归）。
