"""仪表盘聚合服务 — 为 dashboard 端点提供只读聚合查询。

从 ``src/api/dashboard.py`` 提取内联 SQL，遵循 router→service→DB 分层约定。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import TaskStatus
from src.models.worker import Worker
from src.models.event import Event
from src.models.project import Project
from src.models.task import Task
from src.models.token_usage import TokenUsage

# ── 活跃任务状态（非终态）──────────────────────────────────────────

_ACTIVE_STATUSES = [TaskStatus.BACKLOG, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.IN_VERIFICATION]

# ── 所有任务状态（用于 breakdown 零值初始化）───────────────────────

_ALL_STATUSES = [TaskStatus.BACKLOG, TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.IN_VERIFICATION, TaskStatus.COMPLETED, TaskStatus.CANCELLED]


async def get_team_stats(db: AsyncSession, team_id: str) -> dict:
    """团队聚合统计 — Worker 数、活跃任务、项目、事件、Token 消耗。"""

    # Worker 数量
    worker_count = await db.scalar(
        select(func.count(Worker.id)).where(Worker.team_id == team_id)
    )

    # 活跃任务数（非终态）
    active_task_count = await db.scalar(
        select(func.count(Task.id)).where(
            Task.project_id.in_(
                select(Project.id).where(Project.team_id == team_id)
            ),
            Task.status.in_(_ACTIVE_STATUSES),
        )
    )

    # 项目数量
    project_count = await db.scalar(
        select(func.count(Project.id)).where(Project.team_id == team_id)
    )

    # 本日事件数
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_event_count = await db.scalar(
        select(func.count(Event.id)).where(
            Event.team_id == team_id,
            Event.created_at >= today_start,
        )
    )

    # Token 总消耗（本团队所有 worker）
    total_tokens = await db.scalar(
        select(
            func.coalesce(
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
            )
        ).where(
            TokenUsage.worker_id.in_(
                select(Worker.id).where(Worker.team_id == team_id)
            )
        )
    )

    # Token 请求总数
    total_token_requests = await db.scalar(
        select(func.count(TokenUsage.id)).where(
            TokenUsage.worker_id.in_(
                select(Worker.id).where(Worker.team_id == team_id)
            )
        )
    )

    # 本周 token 消耗
    week_start = today_start - timedelta(days=today_start.weekday())
    week_tokens = await db.scalar(
        select(
            func.coalesce(
                func.sum(TokenUsage.prompt_tokens + TokenUsage.completion_tokens), 0
            )
        ).where(
            TokenUsage.worker_id.in_(
                select(Worker.id).where(Worker.team_id == team_id)
            ),
            TokenUsage.recorded_at >= week_start,
        )
    )

    return {
        "team_id": team_id,
        "worker_count": worker_count or 0,
        "active_task_count": active_task_count or 0,
        "project_count": project_count or 0,
        "today_event_count": today_event_count or 0,
        "total_tokens": total_tokens or 0,
        "total_token_requests": total_token_requests or 0,
        "week_tokens": week_tokens or 0,
    }


async def get_projects_breakdown(db: AsyncSession, team_id: str) -> dict:
    """Per-project task breakdown — 按 project + status 聚合 task 数量。"""

    rows = await db.execute(
        select(
            Project.id,
            Project.name,
            Task.status,
            func.count(Task.id).label("cnt"),
        )
        .select_from(Project)
        .outerjoin(Task, Task.project_id == Project.id)
        .where(Project.team_id == team_id)
        .group_by(Project.id, Project.name, Task.status)
        .order_by(Project.name)
    )

    # 组装 per-project breakdown
    projects_map: dict[str, dict] = {}
    for row in rows:
        pid, pname, status, cnt = row
        if pid not in projects_map:
            projects_map[pid] = {
                "project_id": pid,
                "project_name": pname,
                "by_status": {s: 0 for s in _ALL_STATUSES},
            }
        if status is not None:
            projects_map[pid]["by_status"][status] = cnt or 0

    projects = []
    for p in projects_map.values():
        by_status = p["by_status"]
        total = sum(by_status.values())
        completed = by_status[TaskStatus.COMPLETED] + by_status[TaskStatus.CANCELLED]
        projects.append({
            "project_id": p["project_id"],
            "project_name": p["project_name"],
            "total_tasks": total,
            "completed_tasks": completed,
            "by_status": by_status,
        })

    return {"team_id": team_id, "projects": projects}
