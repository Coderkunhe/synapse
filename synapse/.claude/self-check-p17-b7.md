# P17-B7 自检 — DependencyGraph N+1 修复（复用 /dependency-graph）

> 批号: P17-B7 · 性质: 产品批（协作层 · 纯 frontend · 0 src 后端）· 日期: 2026-09-30
> 根因: `DependencyGraph.tsx` 的 `buildGraph()` 对 `depends_on` 链做异步 BFS，每发现一个依赖节点就发一次 `fetchTask`（K 个依赖 = K 次 HTTP）。前端已有 `fetchProjectDependencyGraph`（单请求取整图）+ 后端已有 `/dependency-graph` 端点返回完整 `{nodes, edges}`，客户端本可本地算上游闭包，却在重复后端早已做好的整图遍历。

## 编码前 Scout（三问）

- [x] **数据流拉通** — `TaskDetail` 已有 `task.project_id`（:662 已用）→ 传给 `<DependencyGraph projectId>` → `fetchProjectDependencyGraph(projectId, token)`（client.ts:949 → `GET /v1/projects/{id}/tasks/dependency-graph`）返回 `{nodes:[{id,title,status}], edges:[{from,to,type}]}`，边方向 `from=依赖 → to=被依赖方`（与旧 buildGraph 及后端 tasks.py:437-441 一致）→ 本地 BFS 从 `currentTask.depends_on` 种子出发，沿 `edges` 反邻接（`to → 其依赖们`）展开，深度 3，占位符 `[Missing: …]` 保底。
- [x] **同类参照** — `ProjectOverview.tsx` 已用 `fetchProjectDependencyGraph` + 拓扑分层（:24-107）渲染整图；本组件是「单根 BFS」而非整图分层，但同源同 endpoint。后端另有 `/dependency-chain?direction=upstream`（扁平列表 · 丢 parent→child 边）→ 弃用，因它无法重建 layer/edge。
- [x] **用户一句话** — 打开一个带依赖链的任务详情页，DAG 照常画出传递依赖（含第 2/3 层），但网络面板从「N 次逐任务请求」变「1 次 dependency-graph」，页面更快。

## 编码后自检（四问）

- [x] **乐观路径** — 任务 C 依赖 B 依赖 A → `fetchProjectDependencyGraph` 一次返回 3 节点 2 边 → 本地 BFS 得 layer0=C / layer1=B / layer2=A，渲染 3 节点 + 2 边（E2E 断言 `DepNode-A` 传递闭包可见）。
- [x] **边界状态** — 依赖节点不在图内（已删/跨项目）→ `[Missing: …]` 占位符 status='cancelled'（旧行为保留）；空 `depends_on` → 空态分支不变；`priority/version_no` 图节点默认 `'p3'/0`（渲染从不使用这俩字段）。
- [x] **对比同类** — 边方向、`MAX_DEPTH=3`、占位符、layer 分组/排序逻辑全部与旧 `buildGraph` 一致；唯一差异 K 次 `fetchTask` → 1 次 `fetchProjectDependencyGraph`。
- [x] **变更清单口播** — 2 代码文件 + 1 e2e + 1 plan（≤8 上限）：DependencyGraph.tsx（重写 buildGraph，-25 行）· TaskDetail.tsx（+1 行 projectId）· e2e/task-detail-dependency-graph.spec.ts（新 · 网络计数断言）· docs/plans/p17-b7（新）。0 src 后端 · tsc 0 新增（4 预存基线）· oxlint 0 新增 · pytest 1017 基线不变 · E2E 3/3 绿。
