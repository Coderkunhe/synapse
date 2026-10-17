#!/usr/bin/env python3
"""P17-B33 真人浏览器闭环狗粮 — 环境准备脚本（0 claude -p 模型成本）。

与 B32 的区别（owner 重判根因）：B32 用脚本直接 claim，验的是 pytest 已覆盖的
API 数据层；B33 补真正 P12-4 —— 把「认领」动作留给真人在浏览器里亲手做，
验证「上下文卸载」的人侧体验命题（B1 锚：把人从 human-as-context-bus 卸出来）。

本脚本只种场景，不 claim：
  D = 依赖任务（ready · 无依赖 · 留给 Hunter 浏览器认领）
  A = 阻塞任务（ready · depends_on D → Dashboard 标 🔒 dependency_blocked）
  builder = 第二 actor（可选 · 用于「别人动了我也看得到」的 WS 推送演示）

Usage:
  cd synapse && .venv/bin/python tools/p17-b33-dogfood-setup.py            # 种场景（需 server :8000）
  cd synapse && .venv/bin/python tools/p17-b33-dogfood-setup.py --cleanup  # 善后（删 p17-b33-* 残留）
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

from src.constants import TaskStatus
from src.models.team import Team
from src.models.project import Project
from src.models.worker import Worker
from src.models.task import Task
from src.services.worker_service import register_worker
from src.services import task_service

DB_URL = os.environ.get("SYNAPSE_DB_URL", "sqlite+aiosqlite:///./data/synapse.db")
API_BASE = "http://localhost:8000"
TEAM_SLUG = "synapse-core"
PROJECT_SLUG = "synapse"

BUILDER_NAME = "p17-b33-builder"
BUILDER_ROLE = "builder"

TASK_D_TITLE = "P17-B33 上下文卸载链狗粮 依赖任务"
TASK_A_TITLE = "P17-B33 上下文卸载链狗粮 阻塞任务"
TASK_SPEC = """# P17-B33 真人浏览器闭环狗粮

D = 依赖任务（可认领 · 留给 Hunter 浏览器认领）。
A = 阻塞任务（depends_on D · 依赖未完成 → Dashboard 标 dependency_blocked）。

验证：Hunter 登录 → 看 Dashboard/工作台 → 认领 D → 工作台 WS 实时聚合 → 亲口确认「卸载」。
"""


async def run() -> int:
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # ── 0. server 健康 ──
    try:
        async with httpx.AsyncClient(base_url=API_BASE, timeout=5.0) as hc:
            await hc.get("/health")
    except httpx.HTTPError as e:
        print(f"❌ server 未就绪（:8000）: {e}")
        print("   先起后端：.venv/bin/uvicorn src.main:app --port 8000")
        return 2

    async with async_session() as db:
        # ── 1. 残留防呆 ──
        stale_w = (await db.execute(
            select(Worker).where(Worker.name.like("p17-b33-%"))
        )).scalars().all()
        stale_t = (await db.execute(
            select(Task).where(Task.title.like("P17-B33 %"))
        )).scalars().all()
        if stale_w or stale_t:
            print(f"❌ 残留未清：{len(stale_w)} worker / {len(stale_t)} task —— 先 --cleanup")
            await engine.dispose()
            return 2

        # ── 2. team / project ──
        team = (await db.execute(select(Team).where(Team.slug == TEAM_SLUG))).scalar_one()
        project = (await db.execute(
            select(Project).where(Project.team_id == team.id, Project.slug == PROJECT_SLUG)
        )).scalar_one()
        print(f"✅ Team: {team.name} · Project: {project.name} ({project.id})")

        # ── 3. 注册 builder（第二 actor · 供 WS 推送演示）──
        builder, _builder_key = await register_worker(
            db, team_id=team.id, name=BUILDER_NAME, provider="claude",
            provider_model="sonnet", system_prompt=None,
            metadata={"worker_version": "0.0.0", "supported_events": []},
            registered_by="system", actor_type="agent", actor_id="system",
            batch_size=1, project_id=project.id, project_role=BUILDER_ROLE,
        )
        await db.commit()
        print(f"✅ Builder: {builder.name} ({builder.id}) · role={BUILDER_ROLE}")

        # ── 4. 建 D（依赖 · 无依赖）+ A（depends_on D）──
        task_d = await task_service.create_task(
            db, project_id=project.id, title=TASK_D_TITLE, description=TASK_SPEC,
            priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
            tags=["dogfood", "p17-b33"], metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "Hunter 浏览器认领 D → 工作台聚合"}],
            actor_type="system", actor_id="system", team_id=project.team_id,
        )
        task_a = await task_service.create_task(
            db, project_id=project.id, title=TASK_A_TITLE, description=TASK_SPEC,
            priority="p2", parent_task_id=None, batch_id=None, estimated_effort="s",
            tags=["dogfood", "p17-b33"], metadata=None, deadline_at=None,
            verifications=[{"type": "manual", "description": "A 依赖 D → Dashboard dependency_blocked"}],
            actor_type="system", actor_id="system", team_id=project.team_id,
            depends_on=[{"task_id": task_d.id}],
        )
        task_d.status = TaskStatus.READY
        task_a.status = TaskStatus.READY
        await db.commit()
        await db.refresh(task_d)
        await db.refresh(task_a)
        print(f"✅ Tasks: D={task_d.id} (ready) · A={task_a.id} (ready · depends_on D)")

    await engine.dispose()
    print()
    print("=" * 60)
    print("🏁 P17-B33 场景就绪 —— 未认领任何任务（留给 Hunter 浏览器）")
    print()
    print("   Hunter 登录后步骤：")
    print("   ① Dashboard → synapse 项目卡 🔒 1 阻塞（A blocked by D）")
    print("   ② 项目态势 → DAG: D ready / A blocked")
    print("   ③ 工作台 /workbench → 「我的任务」空")
    print("   ④ 认领 D（任务详情「认领」按钮）")
    print("   ⑤ 回工作台 → D 出现在「我的任务」in_progress（WS 绿点实时）")
    print("   ⑥ 亲口确认「上下文卸载」成立")
    print("=" * 60)
    return 0


def _sqlite_db() -> sqlite3.Connection:
    db_path = Path(__file__).resolve().parent.parent / "data" / "synapse.db"
    if not db_path.exists():
        print(f"❌ DB 不存在: {db_path}")
        sys.exit(1)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def cleanup() -> int:
    """精准删除 p17-b33-* worker + P17-B33 标题 task + 关联数据（幂等）。"""
    conn = _sqlite_db()

    worker_ids = [r[0] for r in conn.execute(
        "SELECT id FROM worker WHERE name LIKE 'p17-b33-%'"
    ).fetchall()]
    task_ids = [r[0] for r in conn.execute(
        "SELECT id FROM task WHERE title LIKE 'P17-B33 %'"
    ).fetchall()]

    print(f"  目标 worker: {len(worker_ids)} 条 · task: {len(task_ids)} 条")
    if not worker_ids and not task_ids:
        print("  （无 p17-b33 残留，无需清理）")
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
        print("\n  ✅ p17-b33 残留已清理")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="P17-B33 真人浏览器闭环狗粮 — 环境准备")
    parser.add_argument("--cleanup", action="store_true", help="善后：删 p17-b33-* 残留")
    args = parser.parse_args()
    sys.exit(cleanup() if args.cleanup else asyncio.run(run()))
