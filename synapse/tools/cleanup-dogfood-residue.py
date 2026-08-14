#!/usr/bin/env python3
"""DG-3 善后脚本化：清理狗粮测试残留的 task + worker + 关联数据。

补齐 P14 狗粮善后的最后一块短板（此前 Worker/Task 数据靠手动清理，见
b4-dogfood-teardown.sh step 6）。

删除目标（幂等 · 可重复运行）：
  1. 非终态 task（backlog / in_progress / in_verification / ready）
  2. 非 system worker（id != 'system'，含 active / pending / suspended）
  3. 上述实体直接关联的 FK 引用记录 + event 日志

保留：
  - completed / cancelled / rejected task（历史证据，不删不改）
  - id='system' 的 system actor worker（应用运行时依赖：auto-verify /
    escalation / authorization 使用 actor_id="system"）
  - --keep-worker 指定的 worker（按 id 或 name 匹配 · 如 human admin worker Hunter，避免误删真人账号）

用法：
  python3 tools/cleanup-dogfood-residue.py           # dry-run，仅预览
  python3 tools/cleanup-dogfood-residue.py --yes     # 执行（单事务提交）
  python3 tools/cleanup-dogfood-residue.py --keep-worker <id-or-name> [--keep-worker <id-or-name> ...]
                                                      # 白名单：保留指定 worker（及其关联数据）

前置：先备份 DB（本脚本不自带备份，避免误删后无法回滚）：
  sqlite3 data/synapse.db ".backup 'data/backups/synapse-$(date +%F)-before-cleanup.db'"
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "synapse.db"

NON_TERMINAL = "('backlog', 'in_progress', 'in_verification', 'ready')"


def _count(conn, sql: str) -> int:
    return conn.execute(sql).fetchone()[0]


def snapshot(conn) -> dict:
    """返回清理前的各表计数，用于 dry-run / 执行后对比。"""
    return {
        "task_non_terminal": _count(
            conn, f"SELECT COUNT(*) FROM task WHERE status IN {NON_TERMINAL}"
        ),
        "task_kept": _count(
            conn, f"SELECT COUNT(*) FROM task WHERE status NOT IN {NON_TERMINAL}"
        ),
        "worker_non_system": _count(
            conn, "SELECT COUNT(*) FROM worker WHERE id != 'system'"
        ),
        "worker_system": _count(
            conn, "SELECT COUNT(*) FROM worker WHERE id = 'system'"
        ),
        "event_total": _count(conn, "SELECT COUNT(*) FROM event"),
    }


def cleanup(conn, dry_run: bool, keep_workers: set[str] | None = None):
    # ── 目标 id ──────────────────────────────────────────────
    keep_workers = keep_workers or set()
    task_ids = [
        r[0]
        for r in conn.execute(
            f"SELECT id FROM task WHERE status IN {NON_TERMINAL}"
        ).fetchall()
    ]
    # --keep-worker 白名单按 id 或 name 匹配（如 `Hunter` 是 name，非 id）
    keep_list = sorted(keep_workers)
    if keep_list:
        keep_clause = ",".join("?" * len(keep_list))
        keep_params = tuple(keep_list) + tuple(keep_list)  # id + name 两处
        worker_rows = conn.execute(
            f"SELECT id FROM worker WHERE id != 'system' "
            f"AND id NOT IN ({keep_clause}) AND name NOT IN ({keep_clause})",
            keep_params,
        ).fetchall()
    else:
        worker_rows = conn.execute(
            "SELECT id FROM worker WHERE id != 'system'"
        ).fetchall()
    worker_ids = [r[0] for r in worker_rows]

    task_ph = ",".join("?" * len(task_ids)) if task_ids else "NULL"
    worker_ph = ",".join("?" * len(worker_ids)) if worker_ids else "NULL"
    tp = tuple(task_ids)
    wp = tuple(worker_ids)

    # 报告目标规模
    print(f"  非终态 task: {len(task_ids)} 条")
    print(f"  非 system worker: {len(worker_ids)} 条")
    if keep_workers:
        kept = sorted(keep_workers)
        print(f"  --keep-worker 白名单保留: {len(kept)} 条 ({', '.join(kept)})")
    if not task_ids and not worker_ids:
        print("  （无残留，无需清理）")
        return

    # ── 删除语句清单（顺序：子表 → 父表；event 软引用一并清理）──
    # 每项为 (描述, SQL, 参数)。参数用占位符避免注入/引号问题。
    steps = []

    if task_ids:
        steps += [
            ("event（target_id 指向被删 task）",
             f"DELETE FROM event WHERE target_id IN ({task_ph})", tp),
            ("verification", f"DELETE FROM verification WHERE task_id IN ({task_ph})", tp),
            ("task_worker_conversation",
             f"DELETE FROM task_worker_conversation WHERE task_id IN ({task_ph})", tp),
            ("token_usage（task_id）",
             f"DELETE FROM token_usage WHERE task_id IN ({task_ph})", tp),
            # 已完成 task 若有 parent 指向被删 task → 置空（避免悬空 parent）
            ("task.parent_task_id 置空",
             f"UPDATE task SET parent_task_id = NULL WHERE parent_task_id IN ({task_ph})", tp),
            # 保留 worker（system）若 active_task_id 指向被删 task → 置空
            ("worker.active_task_id 置空",
             f"UPDATE worker SET active_task_id = NULL WHERE active_task_id IN ({task_ph})", tp),
        ]

    if worker_ids:
        steps += [
            ("event（actor_id / target_id 指向被删 worker）",
             f"DELETE FROM event WHERE actor_id IN ({worker_ph}) OR target_id IN ({worker_ph})", wp + wp),
            ("capability", f"DELETE FROM capability WHERE worker_id IN ({worker_ph})", wp),
            ("team_members", f"DELETE FROM team_members WHERE worker_id IN ({worker_ph})", wp),
            ("project_actor_roles", f"DELETE FROM project_actor_roles WHERE worker_id IN ({worker_ph})", wp),
            ("authorization_requests",
             f"DELETE FROM authorization_requests WHERE worker_id IN ({worker_ph}) OR responded_by_worker_id IN ({worker_ph})", wp + wp),
            ("workflow_role", f"DELETE FROM workflow_role WHERE worker_id IN ({worker_ph})", wp),
            ("decision_audits", f"DELETE FROM decision_audits WHERE worker_id IN ({worker_ph})", wp),
            ("capability_audits", f"DELETE FROM capability_audits WHERE worker_id IN ({worker_ph})", wp),
            ("token_usage（worker_id）", f"DELETE FROM token_usage WHERE worker_id IN ({worker_ph})", wp),
            ("task_worker_conversation（sender/resolved）",
             f"DELETE FROM task_worker_conversation WHERE sender_worker_id IN ({worker_ph}) OR resolved_by_worker_id IN ({worker_ph})", wp + wp),
            # batch 的 assigned_worker_id → 置空（batch 本体不在本脚本范围）
            ("batch.assigned_worker_id 置空",
             f"UPDATE batch SET assigned_worker_id = NULL WHERE assigned_worker_id IN ({worker_ph})", wp),
            # worker 自引用 registered_by → 置空
            ("worker.registered_by 置空",
             f"UPDATE worker SET registered_by = NULL WHERE registered_by IN ({worker_ph})", wp),
        ]

    # ── 父表删除（最后） ──────────────────────────────────────
    if task_ids:
        steps.append(("task", f"DELETE FROM task WHERE id IN ({task_ph})", tp))
    if worker_ids:
        steps.append(("worker", f"DELETE FROM worker WHERE id IN ({worker_ph})", wp))

    # ── dry-run：只统计预览 ──────────────────────────────────
    if dry_run:
        print("\n  [dry-run] 将执行以下删除（不提交）：")
        for desc, sql, params in steps:
            # 用临时连接统计影响行数（不改变主连接状态）
            tmp = sqlite3.connect(DB_PATH)
            n = tmp.execute(sql, params).rowcount
            tmp.close()
            print(f"    {desc}: {n} 条")
        print("\n  → 加 --yes 执行。")
        return

    # ── 执行（单事务） ────────────────────────────────────────
    try:
        for desc, sql, params in steps:
            cur = conn.execute(sql, params)
            print(f"    {desc}: {cur.rowcount} 条")
        conn.commit()
        print("\n  ✅ 已提交")
    except Exception:
        conn.rollback()
        raise


def main():
    args = sys.argv[1:]
    dry_run = "--yes" not in args
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    # 解析 --keep-worker <id>（可重复）白名单
    keep_workers: set[str] = set()
    i = 0
    while i < len(args):
        if args[i] == "--keep-worker" and i + 1 < len(args):
            keep_workers.add(args[i + 1])
            i += 2
            continue
        i += 1

    if not DB_PATH.exists():
        print(f"❌ DB 不存在: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout = 5000")

    before = snapshot(conn)
    print("════════ 清理前 ════════")
    for k, v in before.items():
        print(f"  {k}: {v}")

    cleanup(conn, dry_run, keep_workers=keep_workers)

    if not dry_run:
        after = snapshot(conn)
        print("\n════════ 清理后 ════════")
        for k, v in after.items():
            delta = v - before[k]
            mark = f"{delta:+d}" if delta else "0"
            print(f"  {k}: {v}  ({mark})")

    conn.close()


if __name__ == "__main__":
    main()
