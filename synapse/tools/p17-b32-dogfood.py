#!/usr/bin/env python3
"""P17-B32 人侧上下文卸载链 dogfood（轻量 live 断言 · 0 claude -p 模型成本）。

验证 B27→B29「上下文卸载」链在真 server（:8000）上的端到端串联：
  ① B27 团队态势 — ``GET /v1/dashboard/teams/{team}/projects-breakdown`` 的
     ``dependency_blocked`` 正确标出「依赖未就绪的 ready 任务」。
  ② B29 个人工作台 — human 通过真 claim 认领任务后，``GET /v1/me/tasks`` 正确聚合
     到该 human 名下（claim 路径 owner_id = derived worker_id），dependency_blocked 标志正确。
  ③ mention 唤醒 no-regression — 一条 ``@worker:`` 唤醒 builder（复用 B24 已验证链路）。

为什么轻量：B28/B30 的 WS 实时化已由 e2e 覆盖（dashboard-rollup / workbench-realtime），
本批只补「真 server + 真数据」这一层；B27/B29 后端字段 pytest 已验，缺的是 live 串联。
owner 拍板：轻量 API 断言，零模型成本（P12-4 补 B31 豁免的狗粮）。

场景（seed `synapse` 项目 · 当前 ready=0 干净）：
  依赖任务 D（无依赖）→ 阻塞任务 A（depends_on D）。
  human claim D（真 API · task:claim）→ D 变 in_progress · A 仍 ready 但依赖未完成 → blocked。

Usage:
  cd synapse && .venv/bin/python tools/p17-b32-dogfood.py            # 跑断言（需 server :8000）
  cd synapse && .venv/bin/python tools/p17-b32-dogfood.py --cleanup  # 善后（删 p17-b32-* 残留）
"""
import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.auth import create_access_token
from src.constants import TaskStatus
from src.models.team import Team
from src.models.project import Project
from src.models.worker import Worker
from src.models.task import Task
from src.models.task_worker_conversation import (
    TaskWorkerConversation,
    TaskWorkerConversationMention,
)
from src.services.worker_service import register_worker
from src.services import task_service

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
API_BASE = "http://localhost:8000"
TEAM_SLUG = "synapse-core"
PROJECT_SLUG = "synapse"

BUILDER_NAME = "p17-b32-builder"
BUILDER_ROLE = "builder"

TASK_D_TITLE = "P17-B32 上下文卸载链 dogfood 依赖任务"
TASK_A_TITLE = "P17-B32 上下文卸载链 dogfood 阻塞任务"
TASK_SPEC = """# P17-B32 上下文卸载链 dogfood

D = 依赖任务（可认领）· A = 阻塞任务（depends_on D）。

验证：human claim D 后，D 落工作台（in_progress），A 因依赖未完成标 dependency_blocked。
"""


async def _claim(client: httpx.AsyncClient, token: str, task_id: str,
                 expected_version: int) -> httpx.Response:
    return await client.post(
        f"/v1/tasks/{task_id}/claim",
        json={"expected_version": expected_version},
        headers={"Authorization": f"Bearer {token}"},
    )


async def run() -> int:
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── 0. server 健康 ──
    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=5.0) as hc:
            await hc.get("/health")
    except httpx.HTTPError as e:
        print(f"❌ server 未就绪（:8000）: {e}")
        print("   先起后端：make run 或 uvicorn src.main:app --port 8000")
        return 2

    async with async_session() as db:
        # ── 1. 残留防呆 ──
        stale_w = (await db.execute(
            select(Worker).where(Worker.name.like("p17-b32-%"))
        )).scalars().all()
        stale_t = (await db.execute(
            select(Task).where(Task.title.like("P17-B32 %"))
        )).scalars().all()
        if stale_w or stale_t:
            print(f"❌ 残留未清：{len(stale_w)} worker / {len(stale_t)} task —— 先 --cleanup")
            await engine.dispose()
            return 2

        # ── 2. team / project / hunter ──
        team = (await db.execute(select(Team).where(Team.slug == TEAM_SLUG))).scalar_one()
        project = (await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )).scalar_one()
        hunter = (await db.execute(
            select(Worker).where(Worker.actor_type == "human", Worker.name == "Hunter")
        )).scalar_one()
        print(f"✅ Team: {team.name} · Project: {project.name} · Hunter: {hunter.id}")

        # ── 3. 注册 builder ──
        builder, builder_key = await register_worker(
            db, team_id=team.id, name=BUILDER_NAME, provider="claude",
            provider_model="sonnet", system_prompt=None,
            metadata={"worker_version": "0.0.0", "supported_events": []},
            registered_by="system", actor_type="agent", actor_id="system",
            batch_size=1, project_id=project.id, project_role=BUILDER_ROLE,
        )
        await db.commit()
        print(f"✅ Builder: {builder.name} ({builder.id}) · role={BUILDER_ROLE}")

        # ── 4. 建 D（依赖）+ A（depends_on D）──
        task_d = await task_service.create_task(
            db, project_id=project.id, title=TASK_D_TITLE, description=TASK_SPEC,
            priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
            tags=["dogfood", "p17-b32"], metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "human claim D → 工作台聚合"}],
            actor_type="system", actor_id="system", team_id=project.team_id,
        )
        task_a = await task_service.create_task(
            db, project_id=project.id, title=TASK_A_TITLE, description=TASK_SPEC,
            priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
            tags=["dogfood", "p17-b32"], metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "A 依赖 D → dependency_blocked"}],
            actor_type="system", actor_id="system", team_id=project.team_id,
            depends_on=[{"task_id": task_d.id}],
        )
        task_d.status = TaskStatus.READY
        task_a.status = TaskStatus.READY
        await db.commit()
        await db.refresh(task_d)
        d_version = task_d.version_no
        print(f"✅ Tasks: D={task_d.id} (ready · v{d_version}) · A={task_a.id} (ready · depends_on D)")

        # ── 5. Hunter JWT（显式 team_id · actor_id = hunter worker_id）──
        token = create_access_token(
            user_id=hunter.user_id, team_id=team.id, role="admin", actor_id=hunter.id,
        )

        async with httpx.AsyncClient(base_url=API_BASE, timeout=30.0) as client:
            # ── 6. 真 claim D（human · task:claim）──
            r = await _claim(client, token, task_d.id, d_version)
            if r.status_code != 200:
                print(f"❌ claim D 失败 HTTP {r.status_code}: {r.text[:300]}")
                await engine.dispose()
                return 1
            claimed = r.json()
            print(f"✅ claim D → owner_type={claimed.get('owner_type')} owner_id={claimed.get('owner_id')} status={claimed.get('status')}")

            # ── 7. 断言 ① B27 breakdown dependency_blocked ──
            r = await client.get(
                f"/v1/dashboard/teams/{team.id}/projects-breakdown",
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            proj_row = next(
                (p for p in r.json()["projects"] if p["project_id"] == project.id), None
            )
            if proj_row is None:
                print("❌ breakdown 未找到 synapse 项目")
                await engine.dispose()
                return 1
            blocked = proj_row.get("dependency_blocked", 0)
            ok1 = blocked >= 1
            print(f"\n  ① breakdown[ synapse ] dependency_blocked={blocked} ({'✅ ≥1' if ok1 else '❌ 期望 ≥1'})")
            print(f"     by_status: {proj_row.get('by_status')}")

            # ── 8. 断言 ② B29 工作台聚合 ──
            r = await client.get("/v1/me/tasks", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            my = {t["task_id"]: t for t in r.json()["tasks"]}
            d_row = my.get(task_d.id)
            ok2a = d_row is not None and d_row["status"] == "in_progress" and not d_row["dependency_blocked"]
            ok2b = task_a.id not in my  # A 未认领 → 不该在我名下
            print(f"  ② /me/tasks: D 在列且 in_progress+未阻塞 ({'✅' if ok2a else '❌'}) · A 不在列 ({'✅' if ok2b else '❌'})")
            if d_row:
                print(f"     D: status={d_row['status']} dependency_blocked={d_row['dependency_blocked']} project={d_row.get('project_name')}")

            # ── 9. 断言 ③ mention 唤醒 no-regression ──
            r = await client.post(
                f"/v1/projects/{project.id}/tasks/{task_d.id}/messages",
                json={
                    "task_id": task_d.id,
                    "message_type": "clarification",
                    "body": f"@worker:{builder.name} 请确认上下文卸载链 dogfood 触发（P17-B32）。",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            message_id = r.json()["id"]
            rows = (await db.execute(
                select(TaskWorkerConversationMention).where(
                    TaskWorkerConversationMention.conversation_id == message_id
                )
            )).scalars().all()
            mentioned = {row.worker_id for row in rows}
            hb = await client.post(
                f"/v1/workers/{builder.id}/heartbeat",
                json={"project_id": project.id},
                headers={"Authorization": f"Bearer {builder_key}"},
            )
            hb.raise_for_status()
            hb_json = hb.json()
            ok3 = (builder.id in mentioned
                   and hb_json.get("unread_mentions", 0) >= 1
                   and hb_json.get("next_action") == "respond_to_mention")
            print(f"  ③ @worker mention: 命中 builder ({'✅' if builder.id in mentioned else '❌'}) · "
                  f"unread={hb_json.get('unread_mentions')} · next_action={hb_json.get('next_action')} ({'✅' if ok3 else '❌'})")

    await engine.dispose()
    print()
    print("=" * 60)
    all_pass = ok1 and ok2a and ok2b and ok3
    if all_pass:
        print("🏁 P17-B32 上下文卸载链 dogfood — 全部断言 PASS ✅")
        print("   B27 团队态势 dependency_blocked ✅ · B29 工作台 claim 聚合 ✅ · mention 唤醒 ✅")
        return 0
    print("🔴 P17-B32 dogfood — 存在断言 FAIL，请排查")
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
    """精准删除 p17-b32-* worker + P17-B32 标题 task + 关联数据（幂等）。"""
    conn = _sqlite_db()

    worker_ids = [r[0] for r in conn.execute(
        "SELECT id FROM worker WHERE name LIKE 'p17-b32-%'"
    ).fetchall()]
    task_ids = [r[0] for r in conn.execute(
        "SELECT id FROM task WHERE title LIKE 'P17-B32 %'"
    ).fetchall()]

    print(f"  目标 worker: {len(worker_ids)} 条 · task: {len(task_ids)} 条")
    if not worker_ids and not task_ids:
        print("  （无 p17-b32 残留，无需清理）")
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
        print("\n  ✅ p17-b32 残留已清理")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P17-B32 上下文卸载链 dogfood（轻量 live 断言）")
    parser.add_argument("--cleanup", action="store_true", help="善后：删 p17-b32-* 残留")
    args = parser.parse_args()
    sys.exit(cleanup() if args.cleanup else asyncio.run(run()))
