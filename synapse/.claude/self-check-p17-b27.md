# P17-B27 自检 — 团队级「态势」视图（跨项目聚合 · blocked 信号 + 钻取）

> 批号: P17-B27 · 性质: 产品批（协作层 · 人侧上下文卸载第二刀 · 1 src + 1 test + 5 frontend · 0 迁移）· 日期: 2026-10-14
> 根因: B5/B6 只做单项目态势，人要看全团队得逐个点开每个项目的「态势」tab；Dashboard 的 projects-breakdown 只有静态 status 计数，缺「哪个项目被依赖卡住」信号 + 钻取入口。blocked 语义若前端重算会重新裂开（P16-B5 PFL-248 刚收敛单一定义）。

## 编码前 Scout（三问）

- [x] **数据流拉通** — `get_projects_breakdown`（dashboard_service.py:110）按 project+status GROUP BY，ready 计数未过滤 blocked（沿用 PFL-248 病根——blocked 算进 ready）；`filter_dependency_blocked`（task_query.py:54）是「什么叫 blocked」单一定义，返回**未阻塞**任务；前端 `ProjectBreakdown` 类型（client.ts:305）无 blocked 字段；Dashboard `ProjectBreakdownSection`（Dashboard.tsx:169）渲染项目卡但项目名不可点、无 blocked 徽章；ProjectDetail tab 是本地 useState（ProjectDetail.tsx:78），非 URL 驱动，钻取需新增 `?tab=overview` 读取。
- [x] **同类参照** — `filter_dependency_blocked`（P16-B5 单一定义）· `projects-breakdown`（dashboard 聚合端点范式）· `ProjectOverview`（per-project 态势 = 钻取目标，零改动复用）· Dashboard `STATUS_CONFIG`/`statusChip`（blocked 徽章样式参照）· test_dependency_graph.py 的 `_create_project`/`_create_task` helper 范式。
- [x] **用户一句话** — 人打开团队视图一眼看到「每个项目什么状态、哪个被依赖卡住」，点项目名进去看全 DAG，不用脑子里记全团队。

## 编码后自检（四问）

- [x] **乐观路径** — 团队有 2 ready task（1 依赖未完成 blocked + 1 无依赖自由）→ breakdown 返回 `dependency_blocked==1` 且 `by_status.ready==2`（叠加）；前端渲染 `🔒 1 blocked` 徽章，点项目名跳 `/projects/:id?tab=overview` 落态势 tab。
- [x] **边界状态** — 依赖已 COMPLETED → blocked==0；无 ready → blocked==0（默认值非缺失）；无项目团队 → 空列表不崩；红绿变异（READY→BACKLOG）使 blocked 用例变红（测试非空转）；`filter_dependency_blocked` 内 `depends_on` 空/非 JSON 均安全（沿用其既有 `safe_loads` + `if not deps` 防御）。
- [x] **对比同类** — blocked 复用 `filter_dependency_blocked` 单一定义（非前端重算，避免 B7 N+1 重演）；返回 plain dict 无 pydantic schema（与 `get_projects_breakdown` 既有返回一致）；前端 blocked 徽章样式对齐 `statusChip`/`evtDanger`；i18n `blocked` key 双语（en `{count} blocked` / zh `{count} 阻塞`）。
- [x] **变更清单口播** — 7 文件（≤8 上限）：src/services/dashboard_service.py（+blocked 计算 + 字段）+ tests/test_dashboard.py（+3 用例）+ frontend client.ts（+类型）+ Dashboard.tsx（+徽章 + Link）+ Dashboard.module.css（+样式）+ translations.ts（+双语）+ ProjectDetail.tsx（+useSearchParams 读 tab）。pytest 1054（1051 基线 + 3）零回归 · tsc 0 新增 · oxlint 0 新增。
