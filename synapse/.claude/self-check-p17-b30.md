# P17-B30 自检 — 个人工作台 WS 实时化

> 批号: P17-B30 · 性质: 产品批（协作层 · 人侧上下文卸载第三刀实时化 · 6 前端 · 0 src 后端 · 0 迁移）· 日期: 2026-10-17
> 根因: B29 工作台页只在挂载拉一次 `fetchMyTasks`，之后静止；人停在工作台看不到「我的任务」随认领/状态变化跳动，仍是 human-as-context-bus。同时 `TASK_EVENT_TYPES` 已第 3 处消费方（ProjectOverview + Dashboard + Workbench），B28 注释声明的 rule-of-three 达成，不抽即明知故犯留第三份拷贝。

## 编码前 Scout（三问）

- [x] **数据流拉通** — `Workbench.tsx` mount `fetchMyTasks(token)` → `setTasks(res.tasks)` 一次即止；`useWebSocket`（api/ws.ts:49）返回 `{status, lastEvent}`，后端 auto-subscribe human 到 `task.*`；`fetchMyTasks`（client.ts:349）→ `GET /v1/me/tasks` team 级按 owner 聚合（claim human + assign member 双路径已 B29 落地）。`TASK_EVENT_TYPES` 现于 ProjectOverview.tsx:126 与 Dashboard.tsx:19 各一份拷贝。
- [x] **同类参照** — B28 `Dashboard.tsx` 完整范式（`useWebSocket` + `TASK_EVENT_TYPES` + 300ms debounced refetch + `.liveDot/.liveDotOn`）· B6 `ProjectOverview.tsx` 源头（含项目隔离，本批 team 级无需）· `PageHeader` children action 槽（components/PageHeader.tsx）· e2e `dashboard-rollup.spec.ts`（login→seed→goto→live dot→API claim→断言刷新）+ helpers（loginAsHunter/seedProjectAndTasks/cancelSeededTasks）。
- [x] **用户一句话** — 工作台「我的任务」在认领/状态变化时实时跳动，不用手动 F5。

## 编码后自检（四问）

- [x] **乐观路径** — 人打开 /workbench（live 绿点 = WS connected）→ 未认领任务不在列表 → API claim 该任务（owner 翻到 human）→ `task.claimed` WS 事件 → 300ms debounce → refetch → 卡片出现且 `data-status=in_progress`。
- [x] **边界状态** — 无 token → 沿用 B29 既有 setTokenHint 早退，WS 不连（token null）；事件非 `task.*` → `TASK_EVENT_TYPES.includes` 过滤不 refetch；refetch 失败 → catch 静默保留上次列表（非关键刷新）；unmount → cleanup 清 debounce timer 防泄漏；`TASK_EVENT_TYPES` 抽取后 module 级引用稳定（useWebSocket `useMemo(topics,[join])` 不抖）。
- [x] **对比同类** — `TASK_EVENT_TYPES` 抽到 `api/ws.ts` 消三份拷贝（rule of three 达成，与 B28 注释承诺一致）· refetch 逻辑逐行镜像 Dashboard:76-101 · live dot 样式逐字复制 Dashboard.module.css:26-39 · e2e 断言 `data-task-id`/`data-status` 对齐 dashboard-rollup 的 `data-project-id`/`data-status` 范式。
- [x] **变更清单口播** — 6 前端（≤8 上限）：api/ws.ts（+共享常量）+ ProjectOverview.tsx（-本地常量 +import）+ Dashboard.tsx（-本地常量 +import）+ Workbench.tsx（+useWebSocket +debounced refetch +live dot +data 属性）+ Workbench.module.css（+liveDot）+ workbench-realtime.spec.ts（+1 e2e）。tsc 0 新增 · oxlint 0 新增（12 预存）· e2e 14/14（13 基线 + 1 新）· pytest 1059 基线不变（0 src 后端）· 红绿变异已验（摘 refetch → e2e 变红）。
