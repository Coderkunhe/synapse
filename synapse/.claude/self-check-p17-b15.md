# P17-B15 自检 — 协作消息 @mention 渲染高亮

> 批号: P17-B15 · 性质: 产品批（协作层 · 0 src 后端 · 3 frontend/e2e）· 日期: 2026-10-02
> 根因: B14 只做了「插入」（composer 输入 @ 弹候选、插入 `@worker:<name>`），但消息面板里 mention 仍以裸文本渲染——人看不到「谁被 @」，@mention 的价值没在展示层兑现。本批把 mention token 在展示层可视化。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 渲染点唯一：`TaskDetail.tsx:1019` 的 `<span className={styles.messageText}>{msg.body}</span>`；语法正则与后端 `_MENTION_RE = r"@(worker|role):(\S+)"`（conversation_service.py:38）一致；`.messageText`（TaskDetail.module.css:564）`white-space: pre-wrap` 保留空白；`ConversationMessage.body` 是纯文本字符串（client.ts:944）。样式范式 `--gm-primary`/`--gm-font-mono`（同文件 mentionDropdown）。
- [x] **同类参照** — 后端 `parse_mentions` 用 `\S+` 非空白贪婪匹配（标点尾随语义同款）；B14 `insertMention` 插入 `@worker:<name> ` 带尾空格；React 分段渲染（非 dangerouslySetInnerHTML）是防 XSS 标准范式；e2e `conversation-message-panel.spec.ts:70` 已有 @mention 往返用例可加断言。
- [x] **用户一句话** — 人在任务详情「协作消息」面板看到正文里的 `@worker:claude-builder` / `@role:orchestrator` 以高亮样式（accent 色 + 半透明背景）渲染，一眼认出这是 mention；非 mention 正文保持原样。

## 编码后自检（四问）

- [x] **乐观路径** — body 含 `@worker:somebody please review` → `renderMentionedBody` 用 `matchAll` 切分 → `@worker:somebody` 包进 `.mentionHighlight` span（带 data-testid），`please review` 保持纯文本 → e2e 断言 `.mention-highlight` 可见。
- [x] **边界状态** — body 无 mention → 无匹配 → 纯文本数组；mention 在句首/句中/句尾均正确切分；多 mention（`@worker:a @worker:b`）各自独立高亮；`@worker:alice,` 尾随标点进高亮（与后端 `\S+` 语义一致 · 已知 cosmetic edge 挂账）；`m.index` 可能 undefined → `?? 0` 兜底。
- [x] **对比同类** — 样式用 `--gm-primary` + `--gm-font-mono` token（对齐 mentionDropdown）；`border-radius:3px` + `padding:0 2px` 内联徽章感；返回 `React.ReactNode[]`（同文件已用 `React.ChangeEvent` 命名空间）；不新增 i18n（无新用户可见文本）。
- [x] **变更清单口播** — 3 前端/e2e 文件（≤8 上限，0 src 后端）：TaskDetail.tsx（`renderMentionedBody` 纯函数 + 替换渲染点）+ TaskDetail.module.css（`.mentionHighlight`）+ conversation-message-panel.spec.ts（@mention 往返用例加高亮断言）。pytest 1043 基线不变 · tsc 0 新增（4 预存：usePushNotification + translations 2×errorDefault + Approvals formatResource）· oxlint 0 新增（12 预存）· e2e 4/4 绿。
