#!/usr/bin/env python3
"""P17-B24 @role 团队点名 dogfood（轻量 API 断言 · 0 claude -p 模型成本）。

验证 B23 的 `@role:builder` 解析（project 级 · ProjectActorRole）：sender 发一条含
`@role:builder` 的消息 → project 内所有 builder worker 均收到：
  ① mention 关联行（task_worker_conversation_mention · 恰好 = builder 数）
  ② 未读（heartbeat unread_mentions ≥ 1）
  ③ 唤醒（heartbeat next_action == respond_to_mention）

负对照：sender 用 steward 角色（有 task:comment 权限但非 builder）→ 不应被
`@role:builder` 命中 → mention 关联行数恰好 = builder 数（不含 sender）。

为什么轻量：真回链路（claude -p 收到 respond_to_mention → GET mentions → 回复）
已在 B17/B18/B19 验 2/2；本批差异点只有「@role 解析到多 worker」，API 层即可完整
覆盖。owner 拍板轻量 API 断言，零模型成本。

Usage:
  cd synapse && .venv/bin/python tools/p17-b24-role-mention-dogfood.py            # 跑断言
  cd synapse && .venv/bin/python tools/p17-b24-role-mention-dogfood.py --cleanup  # 善后（删 p17-b24-* 残留）
"""
import argparse
import asyncio
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.services.worker_service import register_worker
from src.services import task_service
from src.models.team import Team
from src.models.project import Project
from src.models.worker import Worker
from src.models.task import Task
from src.models.task_worker_conversation import (
    TaskWorkerConversation,
    TaskWorkerConversationMention,
)

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
API_BASE = "http://localhost:8000"
TEAM_SLUG = "synapse-core"
PROJECT_SLUG = "synapse"

BUILDER_NAMES = ["p17-b24-builder-a", "p17-b24-builder-b", "p17-b24-builder-c"]
SENDER_PREFIX = "p17-b24-sender"
BUILDER_ROLE = "builder"
SENDER_ROLE = "steward"  # 有 task:comment 但非 builder → @role:builder 不命中（负对照）

TASK_TITLE = "P17-B24 @role 团队点名 dogfood 任务"
TASK_SPEC = """# P17-B24 @role 团队点名 dogfood 任务

这是 P17-B24（B23 @role 团队点名）的 dogfood 验证任务。验证 `@role:builder` 解析到
project 内所有 builder worker，并接入既有 mention 唤醒链路。

本任务为 in_progress + human-owned（非 ready），builder 无可认领 → 稳落 idle。
sender（steward）走 API 发 `@role:builder`，3 个 builder 靠 respond_to_mention 唤醒。
"""


async def _register(db: AsyncSession, team_id: str, project_id: str, name: str,
                    role: str) -> tuple[Worker, str]:
    """注册单个 worker（幂等），返回 (worker, api_key)。已存在则 key 返回 ""。"""
    worker = (await db.execute(
        select(Worker).where(Worker.name == name, Worker.team_id == team_id)
    )).scalar_one_or_none()
    if worker:
        print(f"⏭️  Worker exists: {worker.name} ({worker.id})")
        return worker, ""
    worker, api_key = await register_worker(
        db, team_id=team_id, name=name, provider="claude",
        provider_model="sonnet", system_prompt=None,
        metadata={"worker_version": "0.0.0", "supported_events": []},
        registered_by="system", actor_type="agent", actor_id="system",
        batch_size=1, project_id=project_id, project_role=role,
    )
    await db.commit()
    print(f"✅ Worker: {worker.name} ({worker.id}) · role={role}")
    return worker, api_key


async def _heartbeat(client: httpx.AsyncClient, worker_id: str, key: str,
                     project_id: str) -> dict:
    """调 heartbeat，返回 {next_action, unread_mentions}。"""
    r = await client.post(
        f"/v1/workers/{worker_id}/heartbeat",
        json={"project_id": project_id},
        headers={"Authorization": f"Bearer {key}"},
    )
    r.raise_for_status()
    return r.json()


async def run() -> int:
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # ── 0. 残留检查（防呆：builder 已存在 → 拿不到 key，先 --cleanup）──
        stale = (await db.execute(
            select(Worker).where(Worker.name.like("p17-b24-%"))
        )).scalars().all()
        if stale:
            print(f"❌ 检测到 {len(stale)} 个 p17-b24-* 残留 worker（重跑前未善后）")
            print("   先运行 --cleanup 清残留，再跑断言（worker key 只返回一次）。")
            await engine.dispose()
            return 2

        # ── 1. team / project ──
        team = (await db.execute(
            select(Team).where(Team.slug == TEAM_SLUG)
        )).scalar_one()
        project = (await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )).scalar_one()
        print(f"✅ Team: {team.name} · Project: {project.name} ({project.id})")

        # ── 2. 注册 3 builder + 1 sender（steward）──
        builders: list[tuple[Worker, str]] = []
        for name in BUILDER_NAMES:
            builders.append(await _register(db, team.id, project.id, name, BUILDER_ROLE))
        sender_name = f"{SENDER_PREFIX}-{uuid.uuid4().hex[:8]}"
        sender, sender_key = await _register(db, team.id, project.id, sender_name, SENDER_ROLE)

        if any(k == "" for _, k in builders) or not sender_key:
            print("❌ 有 worker 复用了已存在记录、未拿到 key —— 请先 --cleanup")
            await engine.dispose()
            return 2

        # ── 3. task（in_progress + human-owned · 非 ready 不被 claim）──
        hunter = (await db.execute(
            select(Worker).where(Worker.actor_type == "human", Worker.name == "Hunter")
        )).scalar_one()
        task = await task_service.create_task(
            db, project_id=project.id, title=TASK_TITLE, description=TASK_SPEC,
            priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
            tags=["dogfood", "p17-b24"], metadata=None, deadline_at=None,
            verifications=[{
                "type": "manual",
                "description": "@role:builder 命中 3 个 builder → 未读 + respond_to_mention 唤醒",
            }],
            actor_type="system", actor_id="system", team_id=project.team_id,
        )
        task.status = "in_progress"
        task.owner_type = "human"
        task.owner_id = hunter.id
        await db.commit()
        print(f"✅ Task: {task.title} ({task.id}) · in_progress · human-owned")

        # ── 4. sender 发 @role:builder 消息 ──
        async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
            r = await client.post(
                f"/v1/projects/{project.id}/tasks/{task.id}/messages",
                json={
                    "task_id": task.id,
                    "message_type": "clarification",
                    "body": "全员注意：@role:builder 请确认收到团队点名（P17-B24 dogfood）。",
                },
                headers={"Authorization": f"Bearer {sender_key}"},
            )
            r.raise_for_status()
            message_id = r.json()["id"]
            print(f"✅ Message: {message_id} · body 含 @role:builder")

            # ── 5. 断言 ① mention 关联行 = 恰好 3 builder ──
            rows = (await db.execute(
                select(TaskWorkerConversationMention).where(
                    TaskWorkerConversationMention.conversation_id == message_id
                )
            )).scalars().all()
            mentioned_ids = {row.worker_id for row in rows}
            builder_ids = {w.id for w, _ in builders}

            print(f"\n    mention 关联行: {len(rows)} 条 · 命中 worker = {sorted(mentioned_ids)}")

            ok1 = mentioned_ids == builder_ids
            ok1_msg = "✅" if ok1 else "❌"
            print(f"  ① mention 行恰好=3 builder（不含 steward sender）: {ok1_msg}")
            if not ok1:
                print(f"     期望 {sorted(builder_ids)} · 实际 {sorted(mentioned_ids)}")

            # ── 6. 断言 ② 未读 + ③ 唤醒（heartbeat 一次调用）──
            all_pass = ok1
            for w, key in builders:
                hb = await _heartbeat(client, w.id, key, project.id)
                unread = hb.get("unread_mentions", 0)
                nxt = hb.get("next_action")
                ok2 = unread >= 1
                ok3 = nxt == "respond_to_mention"
                all_pass = all_pass and ok2 and ok3
                print(f"     {w.name}: unread={unread} ({'✅' if ok2 else '❌'}) · "
                      f"next_action={nxt} ({'✅' if ok3 else '❌'})")

        # ── 7. 汇总 ──
        await engine.dispose()
        print()
        print("=" * 60)
        if all_pass:
            print("🏁 P17-B24 @role 团队点名 dogfood — 全部断言 PASS ✅")
            print("   @role:builder → 3 builder 均收 mention 行 + 未读 + respond_to_mention 唤醒")
            return 0
        print("🔴 P17-B24 dogfood — 存在断言 FAIL，请排查")
        return 1


def _sqlite_db() -> sqlite3.Connection:
    db_path = Path(__file__).resolve().parent.parent / "data" / "synapse.db"
    if not db_path.exists():
        print(f"❌ DB 不存在: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def cleanup() -> int:
    """精准删除 p17-b24-* 前缀 worker + P17-B24 标题 task + 关联数据（幂等）。

    不碰 e2e-* / 其他批次残留。删除顺序：子表 → 父表。
    """
    conn = _sqlite_db()

    worker_ids = [r[0] for r in conn.execute(
        "SELECT id FROM worker WHERE name LIKE 'p17-b24-%'"
    ).fetchall()]
    task_ids = [r[0] for r in conn.execute(
        "SELECT id FROM task WHERE title LIKE 'P17-B24 %'"
    ).fetchall()]

    print(f"  目标 worker: {len(worker_ids)} 条 · task: {len(task_ids)} 条")
    if not worker_ids and not task_ids:
        print("  （无 p17-b24 残留，无需清理）")
        conn.close()
        return 0

    wp = ",".join("?" * len(worker_ids)) if worker_ids else "NULL"
    tp = ",".join("?" * len(task_ids)) if task_ids else "NULL"
    wparams = tuple(worker_ids)
    tparams = tuple(task_ids)

    steps = []
    if task_ids:
        steps += [
            ("event（target_id→task）", f"DELETE FROM event WHERE target_id IN ({tp})", tparams),
            ("verification", f"DELETE FROM verification WHERE task_id IN ({tp})", tparams),
            ("mention 关联行", f"DELETE FROM task_worker_conversation_mention WHERE conversation_id IN (SELECT id FROM task_worker_conversation WHERE task_id IN ({tp}))", tparams),
            ("task_worker_conversation", f"DELETE FROM task_worker_conversation WHERE task_id IN ({tp})", tparams),
            ("token_usage（task）", f"DELETE FROM token_usage WHERE task_id IN ({tp})", tparams),
            ("task.parent 置空", f"UPDATE task SET parent_task_id = NULL WHERE parent_task_id IN ({tp})", tparams),
            ("worker.active_task_id 置空", f"UPDATE worker SET active_task_id = NULL WHERE active_task_id IN ({tp})", tparams),
        ]
    if worker_ids:
        steps += [
            ("event（actor/target→worker）", f"DELETE FROM event WHERE actor_id IN ({wp}) OR target_id IN ({wp})", wparams + wparams),
            ("capability", f"DELETE FROM capability WHERE worker_id IN ({wp})", wparams),
            ("team_members", f"DELETE FROM team_members WHERE worker_id IN ({wp})", wparams),
            ("project_actor_roles", f"DELETE FROM project_actor_roles WHERE worker_id IN ({wp})", wparams),
            ("authorization_requests", f"DELETE FROM authorization_requests WHERE worker_id IN ({wp}) OR responded_by_worker_id IN ({wp})", wparams + wparams),
            ("workflow_role", f"DELETE FROM workflow_role WHERE worker_id IN ({wp})", wparams),
            ("decision_audits", f"DELETE FROM decision_audits WHERE worker_id IN ({wp})", wparams),
            ("capability_audits", f"DELETE FROM capability_audits WHERE worker_id IN ({wp})", wparams),
            ("token_usage（worker）", f"DELETE FROM token_usage WHERE worker_id IN ({wp})", wparams),
            ("task_worker_conversation（sender/resolved）", f"DELETE FROM task_worker_conversation WHERE sender_worker_id IN ({wp}) OR resolved_by_worker_id IN ({wp})", wparams + wparams),
            ("batch.assigned_worker_id 置空", f"UPDATE batch SET assigned_worker_id = NULL WHERE assigned_worker_id IN ({wp})", wparams),
            ("worker.registered_by 置空", f"UPDATE worker SET registered_by = NULL WHERE registered_by IN ({wp})", wparams),
        ]

    if task_ids:
        steps.append(("task", f"DELETE FROM task WHERE id IN ({tp})", tparams))
    if worker_ids:
        steps.append(("worker", f"DELETE FROM worker WHERE id IN ({wp})", wparams))

    try:
        for desc, sql, params in steps:
            cur = conn.execute(sql, params)
            print(f"    {desc}: {cur.rowcount} 条")
        conn.commit()
        print("\n  ✅ p17-b24 残留已清理")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P17-B24 @role 团队点名 dogfood（轻量 API 断言）")
    parser.add_argument("--cleanup", action="store_true", help="善后：删 p17-b24-* 残留")
    args = parser.parse_args()
    sys.exit(cleanup() if args.cleanup else asyncio.run(run()))
