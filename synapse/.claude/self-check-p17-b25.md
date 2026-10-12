# P17-B25 自检 — 尾随标点高亮修复（mention 正则收紧）

> 批号: P17-B25 · 性质: 产品批（协作层 bug 修复 · 1 src 后端 + 1 frontend + 1 test + 1 e2e）· 日期: 2026-10-12
> 根因: `@(worker|role):(\S+)` 的 `\S+` 贪婪匹配把尾随标点吞进 token —— `@role:builder,` 解析为 `builder,`（全角更糟：`@worker:alice，请协助。` 吞成 `alice，请协助。`）。后果 ① 「高亮范围 == 解析范围」契约（B15）破；② @role 精确匹配 `role.in_(["builder,"])` 静默失效 → role 点名不唤醒。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 后端 `parse_mentions`（conversation_service.py:41）用 `_MENTION_RE.finditer` 提取 token → `resolve_mentions` 对 @role 走 `ProjectActorRole.role.in_(role_names)` **精确匹配**（conversation_service.py:104），`builder,` ≠ `builder` → 静默不命中；前端 `renderMentionedBody`（TaskDetail.tsx:34）用 `body.matchAll(MENTION_RE)` 高亮，两处正则须逐字符一致才保「高亮范围==解析范围」。worker 名 charset 实测 `[A-Za-z0-9_.-]`（claude-builder / claude-builder_v2 / v1.2 / MentionTarget），无空白。
- [x] **同类参照** — B15 自检已挂账「尾随标点进高亮（后端 `\S+` 既有语义 · 对齐优先）」；B16 注释「尾随标点 name 未命中→不跳」；e2e `conversation-message-panel.spec.ts:104` 已有 `mention-highlight` 断言范式可复用。
- [x] **用户一句话** — 人发 `@role:builder, 请看一下` 后，`builder` 被正确高亮且逗号留在 span 外，role 点名不再因尾随逗号静默失效。

## 编码后自检（四问）

- [x] **乐观路径** — `@role:builder, 请协助` → 新正则 `[A-Za-z0-9_.-]*[A-Za-z0-9_]` 匹配 `builder`（逗号不进 token）→ 解析 `builder` → 高亮 span 精确 `@role:builder`。
- [x] **边界状态** — 半角逗号/句号、全角逗号/句号均剥离；名称内部点保留（`v1.2`）；连字符/下划线保留（`claude-builder_v2`）；句首/句中/句尾均正确；红绿变异证实旧 `\S+` 吞 `builder,`/`alice，请协助。`。
- [x] **对比同类** — 正则与后端逐字符一致（唯一 diff = JS 加 `g` flag）；注释同步更新指向对方文件:行；e2e 断言复用 `mention-highlight` testid + 精确 `toHaveText`。
- [x] **变更清单口播** — 4 文件（≤8 上限）：src/services/conversation_service.py（`_MENTION_RE` 收紧）+ frontend/src/pages/TaskDetail.tsx（`MENTION_RE` 同步）+ tests/test_conversation_service.py（+2 用例）+ frontend/e2e/conversation-message-panel.spec.ts（+1 用例）。pytest 1049（1047 基线 + 2）零回归 · tsc 0 新增（4 预存）· oxlint 0 新增（12 预存）· e2e conversation-message-panel 7/7 绿（6 基线 + 1 新）。
