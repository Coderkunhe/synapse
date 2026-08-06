# P12-B18 自检 — B17 狗粮发现 #1/#3 修复

## Scout 三问（编码前）

- [x] **数据流拉通**：B17 狗粮发现 #1（DUPLICATE_VERIFICATION guard 阻断 rework）——数据流为 Worker submit → task_execution.submit_task → verification reset → O verify → _check_verify_idempotent guard。根因在 submit_task 只重置 verification_results 中列出的 verification，Worker 可能遗漏；且 guard 只看 verification.reset event，无 fallback。#3（canVerify）——数据流为 /auth/me → AuthContext.role（team role）→ TaskDetail canVerify。根因是用了 team role 而非 project_actor_roles 的 project role。
- [x] **同类代码参照**：task_execution.py 的 verification reset 逻辑在 B17 前只迭代 verification_results，其他服务（如 batch verification）无此问题。verification_service.py 的 guard 参照了 verification.reset event 检查模式。projects.py 的 /my-role 端点参照了 admin.py 中的 project role 管理端点风格。
- [x] **用户一句话描述**："B 重做后提交，O 再验证时被 DUPLICATE_VERIFICATION 挡住过不去；而且我有 project admin 但审批按钮不显示"

## 自检四问（编码后）

- [x] **乐观路径验证**：正常 rework 流程 — Worker submit → 全量 reset 所有非 PENDING verification → O verify → guard 通过（verification.reset event 存在 OR task.rejected fallback 命中）→ task 完成。前端 project role 正确返回 → canEdit/canVerify 为 true → 按钮显示。
- [x] **边界状态检查**：(1) verification_results 为空列表时，全量 reset 仍然触发。(2) 无 project_actor_roles 记录时，/my-role 返回 role=null，前端 fallback 到 team role。(3) verification.reset event 缺失但 task.rejected event 存在时，guard 的 fallback 生效。(4) 幂等窗口内同 actor 重复 verify 且无 rework 信号 → 仍然拒绝。
- [x] **对比同类变更**：与 P11-B76（stale detector + verify guard）相比，B18 的改动更保守——修改已有 guard 逻辑而非新增服务。与 P10-B18（project_actor_roles 首次接线）相比，B18 仅新增一个轻量查询端点，无 schema 变更。
- [x] **变更口播**："B18 修了两个 B17 狗粮发现的 bug — #1 verify guard 改为全量 reset + task.rejected fallback，#3 前端改用 project role 做权限检查。五文件，零 schema 变更，零新依赖。"

## 关联

- B17 狗粮 R6: docs/plans/p12-b17-dogfood-r6.md
- D1 Scout §12: docs/plans/p12-d1-scout.md
