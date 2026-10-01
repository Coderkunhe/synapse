# P17-B8 自检 — 人侧反馈最小闭环（S-020 反馈协议 v2）

> 批号: P17-B8 · 性质: 产品批（协作层 · 2 src 后端 + 4 frontend + 2 tests）· 日期: 2026-10-01
> 根因: 协作第一增量（人认领/读规范/同步）已闭环，但反向通道缺失——Builder 无法通过 UI 向 Orchestrator 发「澄清/阻塞/改进/提案」。后端 A2A 管道 80% 已就位（TaskWorkerConversation + message_type 枚举 + @mention 解析），缺口两块：① 前端零 UI（无页面/组件/API client 调 conversation 端点）② `create_message` 解析出被 @ 的 worker_id 列表但零 WS 投递（只存 mentions_json，team 广播因无人订阅 conversation.message.created 而落空）。

## 编码前 Scout（三问）

- [x] **数据流拉通** — `POST /v1/projects/{pid}/tasks/{tid}/messages`（body 必填 `task_id`/`message_type`/`body`）→ `conversation_service.create_message` 解析 @mention → `resolve_mentions` 得 worker_id 列表（worker.name ilike 匹配 / workflow role）→ 存 `mentions_json` → `event_store.record(CONVERSATION_MESSAGE_CREATED)` 返回 event；前端 `fetchTaskMessages` 走 `GET .../messages` 返回 `{task_id, messages[], next_cursor}`。WS 信封硬约束：前端 `ws.ts` `onmessage` 只认 `msg.type === 'event'`，所以投递必须 `{"type":"event","data":event_to_dict(event)}`。
- [x] **同类参照** — `notify_orchestrator`（tasks.py:934-950）的 `broadcast_to_actor` 循环（逐 worker 精确推送）是投递范式；`event_store._broadcast_event` 已构造 event_dict（抽 `event_to_dict` 复用）；前端 `ProjectOverview.tsx` 的 `useWebSocket` + `MESSAGE_EVENT_TYPES` 模块级常量（stableTopics 用 `topics.join(',')` 防重连）+ prepend 范式；Event Timeline 的 `styles.section/sectionTitle/count/noData` 是面板结构参照。
- [x] **用户一句话** — 人（Builder）打开任务详情页，能在「协作消息」区选类型（澄清/阻塞/改进/提案）发消息给 Orchestrator，实时看到线程刷新；被 @ 的 Orchestrator worker 通过 WS 收到精确推送而非全 team 广播。

## 编码后自检（四问）

- [x] **乐观路径** — 任务有 `project_id` → `loadMessages` 拉取线程 → 发一条 clarification → `createTaskMessage` POST 成功 → `loadMessages` 刷新 → 后端 `create_message` 解析 @worker:Claude → 对 test_worker_2 逐个 `broadcast_to_actor` → 前端 WS 收到 `conversation.message.created` 且 `payload.task_id === taskId` → refetch。
- [x] **边界状态** — 无消息 → `noMessages` 空态；`task.project_id` 未就绪 → `loadMessages` 提前 return（不崩）；无 @mention → `worker_ids` 空 → 循环不执行零额外广播（测试断言 `assert_not_called`）；`broadcast_to_actor` 无连接 → 静默 no-op；`message_type` 含 'comment'（notify 生成）→ `MESSAGE_TYPE_LABELS` fallback 显示原始 type。
- [x] **对比同类** — 面板复用 `styles.section`/`sectionTitle`/`count`/`noData`，发送按钮对齐 `btnPrimary`，CSS 全用 `--gm-*` token；信封与 `_broadcast_event` 完全一致（`type==='event'` + `data.event_type`）；投递用 `broadcast_to_actor`（无 topic 过滤）对齐 notify_orchestrator 而非 team 广播。
- [x] **变更清单口播** — 7 代码/测试文件（≤8 上限）：event_store.py（抽 event_to_dict 纯重构）· conversation_service.py（mention 投递 +6 行）· client.ts（2 函数 + 1 类型）· TaskDetail.tsx（面板 + composer + WS）· TaskDetail.module.css（样式）· translations.ts（双语 key）· test_conversation_service.py（+2 测试）。pytest 1023（1021+2）· tsc 0 新增（4 预存）· oxlint 0 新增。
