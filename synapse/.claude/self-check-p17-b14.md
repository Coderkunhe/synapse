# P17-B14 自检 — 前端 @mention 补全 UI

> 批号: P17-B14 · 性质: 产品批（协作层 · 0 src 后端 · 3 frontend）· 日期: 2026-10-02
> 根因: PFL-274 全量闭环后（B12 查询层 + B13 触发层），mention 的落库→未读查询→路由唤醒→协议消费链路已通，但人侧发消息仍要手敲 `@worker:<name>` 语法（零补全）。人脑承载 mention 语法是「human-as-context-bus」的又一残留——补全 UI 把「我能 @ 谁」从人脑卸载到 UI。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 语法正则 `_MENTION_RE = r"@(worker|role):(\S+)"`（conversation_service.py:38），name 无空白；`parse_mentions` 提取 `{type,value}` → `resolve_mentions` 用 `Worker.name ILIKE %name%` 解析为 worker_id。前端 composer 是裸 `<textarea>`（TaskDetail.tsx 原 985 行），`createTaskMessage` 只传 body，mention 靠手敲。worker 候选源已存在：`fetchWorkers(teamId, token, {status:'active'})` → `GET /teams/{team_id}/workers` 返回 `{items: WorkerSummary[], total}`（client.ts:607），`WorkerSummary.name/id/status/is_disabled` 齐备；`useAuth()` 已暴露 `teamId`。
- [x] **同类参照** — `WorkerSummary` 有 `is_disabled`/`status` 字段可过滤；`resolve_mentions` 的 `%name%` contains 语义 → 前端用 `name.toLowerCase().includes(q)` 对齐（非 startsWith）；`TaskDetail.module.css` 的 `--gm-*` token 是样式范式；下拉交互参照标准 combobox（listbox/option role + aria-selected）。
- [x] **用户一句话** — 人（Builder）在任务详情「协作消息」composer 里输入 `@`，弹出团队 active worker 候选，继续输入过滤，↑↓ 选、Enter/Tab 或点击插入 `@worker:<name>`（带尾空格），Esc 关闭；不记住 mention 语法、不靠猜 worker 名。

## 编码后自检（四问）

- [x] **乐观路径** — composer 输入 `@`（句首或空白后）→ `handleMessageChange` 检出 trigger → `mentionQuery=''` → `filteredMentions` = 全部 active 未禁用 worker → 下拉显示 → 输入 `cl` 过滤 → ↑↓ 移动高亮 → Enter 调 `insertMention('claude-builder')` → body 插入 `@worker:claude-builder ` 且光标置于尾空格后 → 下拉关闭 → 发送 `createTaskMessage` 正常提交，后端 `parse_mentions` 正确解析。
- [x] **边界状态** — `teamId`/`token` 为 null → effect 提前 return（不 fetch）；`@` 前面非空白（如 `foo@bar`）→ 不触发；`@` 后已含 `:` 或空白（已成形 mention / 半截空格）→ `activeMentionTrigger` 返回 -1 → 不弹；无匹配 worker → `filteredMentions` 空 → 下拉不渲染；`mentionOpen` 时按 Enter/Tab 选中而非换行/提交（preventDefault）；Esc 关闭；发送成功后 `setMentionOpen(false)` 复位；`fetchWorkers` 失败 → catch 静默（补全非关键，不阻断消息）。
- [x] **对比同类** — 样式全用 `--gm-*` token + `var(--gm-radius)`；`.composerInputWrap` 用 `position:relative` 包裹 textarea + 下拉（绝对定位），不破坏 `.composer` 原有 flex 布局；下拉用 `role="listbox"`/`option`/`aria-selected` 对齐无障碍；i18n 双语（EN/ZH）新增 `mentionSuggestions` key。
- [x] **变更清单口播** — 3 前端文件（≤8 上限，0 src 后端）：TaskDetail.tsx（composer @ 检测 + 下拉 + 键盘/点击 + 插入）+ TaskDetail.module.css（`.composerInputWrap` + `.mentionDropdown`/`.mentionOption`/`.mentionActive`）+ translations.ts（双语 `mentionSuggestions`）。pytest 1043 基线不变 · tsc 0 新增（4 预存：usePushNotification + translations 2×errorDefault + Approvals formatResource）· oxlint 0 新增（12 预存）。
