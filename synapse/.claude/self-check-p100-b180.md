# P100-B180 自检 — PFL-276 mention 关联表 FK 补 ON DELETE CASCADE

> 批号: P100-B180 · 性质: 治理批（后端 schema 债修复 · 1 src 后端 + 1 migration + 1 test）· 日期: 2026-10-12
> 根因: P17-B12 迁移 `p17_b12_mention_join` 建的 `task_worker_conversation_mention` 两处 FK（conversation_id / worker_id）都只写 `ForeignKeyConstraint` 未加 `ondelete`。mention 行「黏住」message 和 worker 双方——删任一方被 FK 阻断，且 mention 行无删除 API，形成无法清理的死角（P17-B16 e2e afterAll 删临时 worker 报 500 `FOREIGN KEY constraint failed`）。

## 编码前 Scout（三问）

- [x] **数据流拉通** — mention 行是 `create_message` 落库的派生索引行（`conversation_service.py` 落 `TaskWorkerConversationMention(conversation_id, worker_id)`）· worker 删除走 `hard_delete_worker`（`worker_service.py:545` 纯 `db.delete(worker)`，ORM 只 cascade capabilities，mention 无 relationship）· SQLite `PRAGMA foreign_keys=ON`（`db.py:22` event listener）已启用 → 无 CASCADE 的 FK 会硬阻断 delete，有 CASCADE 会级联删除。
- [x] **同类参照** — 全仓无任何 `ondelete=` 先例（`grep ondelete src/ alembic/` 全空）· 唯一 FK 相关迁移是 `p100_b107_make_event_team_id_nullable`（改 nullable 非 cascade）· SQLite 不支持 ALTER 已存在 FK 约束 → 需重建表。
- [x] **用户一句话** — 人（或 e2e）删一个被 @ 过的 worker，不再报 500 `FOREIGN KEY constraint failed`，其 mention 关联行随删除自动清理。

## 编码后自检（四问）

- [x] **乐观路径** — 删 worker / 删 conversation → `ON DELETE CASCADE` 级联删 mention 行 · pytest 2 级联用例绿。
- [x] **边界状态** — SQLite 不支持 ALTER FK → 跨方言「建新表→拷贝→删旧→改名」· 保 15 行既有 mention · 迁移 upgrade/downgrade round-trip 验证（schema + 数据全程保留）· 名称内部点/连字符不受影响（本批不动正则）。
- [x] **对比同类** — 不动 conversation 表本身（message 是历史记录，删 worker 不应级联删消息）· 只级联派生索引行（mention）· 语义正确。
- [x] **变更清单口播** — 3 文件：src/models/task_worker_conversation.py（两处 FK 加 `ondelete="CASCADE"`）+ alembic/versions/p100_b180_add_mention_fk_cascade.py（跨方言重建表）+ tests/test_conversation_service.py（2 级联用例）。pytest 1051（1049 基线 + 2）零回归 · 红绿（e2e teardown 曾报 FOREIGN KEY constraint failed → 现在级联删除）。
