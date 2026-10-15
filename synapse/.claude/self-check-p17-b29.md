# P17-B29 自检 — 个人工作台任务切片（我的任务 + 依赖阻塞）

> 批号: P17-B29 · 性质: 产品批（协作层 · 人侧上下文卸载第三刀 · 4 src + 1 test + 5 frontend · 0 迁移）· 日期: 2026-10-15
> 根因: B5/B6 项目态势 → B27/B28 团队态势都做了，但人侧「我的任务」仍得靠脑子记——`list_tasks` 是 project-scoped 无 team 级「我的任务」端点，Tasks 页「mine」tab 只认 worker（`filterWorkerId`）不认 human。战略锚「人脑卸载全团队上下文」的个人层还没落地。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 身份 = `ActorInfo.actor_id`（人 = `derive_id(member.id,"worker")` · JWT `actorId` claim 已核实）· Task 多态 owner 三条路径：claim 写 `owner_type=human`+`owner_id=derived worker_id`（B3），assign 写 `owner_type=member`+`owner_id=member.id`（P8-B3），worker 写 `worker`+`worker_id`；`filter_dependency_blocked`（task_query.py:54）是「什么叫 blocked」单一定义（B27 同源）；前端 `useAuth().memberId` 有身份但 Tasks「mine」tab 只 `owner_id===filterWorkerId` 匹配 worker。
- [x] **同类参照** — B27 `get_projects_breakdown` + `filter_dependency_blocked`（blocked 叠加 · 前端不重算）· `/workers/me/*` me 端点范式（worker_info.py）· Dashboard `STATUS_CONFIG`/`statusChip`/`blockedBadge` 视觉语言 · `get_current_actor` 统一 actor 鉴权（人/worker 同入口）。
- [x] **用户一句话** — 我登录后一眼看到：我认领了哪些任务、哪些被依赖卡住了、各自在哪个项目——不用脑子背全团队。

## 编码后自检（四问）

- [x] **乐观路径** — 人 claim 一任务（owner_type=human + owner_id=worker_id）→ `GET /v1/me/tasks` 返回该任务（含 project_name）· 前端 `/workbench` 列出（状态 chip + 项目名 + 点击跳 `/tasks/:id`）。
- [x] **边界状态** — assign 路径（owner_type=member + owner_id=member.id）经 `user_id` 反查 member.id 也命中 · 他人任务不出现（负对照）· ready+依赖未完成 → `dependency_blocked=true`，依赖已满足/in_progress → false · 空列表 → 前端 `workbench.empty` 提示 · 无 token → error 状态。
- [x] **对比同类** — blocked 复用 `filter_dependency_blocked` 单一定义（非前端重算）· 状态 chip/徽章样式对齐 Dashboard `STATUS_CONFIG`/`blockedBadge` · i18n 双语 · 端点薄路由（认证在此 · 查询委托 service）对齐 dashboard.py 范式。
- [x] **变更清单口播** — 11 文件：src/services/task_query.py（+get_my_tasks）+ src/api/workbench.py（新 router /me/tasks）+ src/schemas/workbench.py（新）+ src/api/router.py（+注册）+ tests/test_workbench.py（+5 用例）+ frontend client.ts（+类型/fetchMyTasks）+ Workbench.tsx（新页）+ Workbench.module.css（新）+ App.tsx（+路由）+ Layout.tsx（+nav）+ translations.ts（+双语）。pytest 1059（1054 基线 + 5）零回归 · tsc 0 新增 · oxlint 0 新增（12 预存）。
