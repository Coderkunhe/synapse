"""个人工作台端点 — 「我的任务切片」聚合（P17-B29）。

薄路由层：认证在此完成，查询委托给 ``src.services.task_query.get_my_tasks``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.schemas.workbench import WorkbenchResponse
from src.services.task_query import get_my_tasks

workbench_router = APIRouter(prefix="/me")


@workbench_router.get("/tasks", response_model=WorkbenchResponse)
async def my_tasks(
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> WorkbenchResponse:
    """「我」名下所有任务 — 跨项目 · 任意状态 · 带 dependency_blocked 标志。"""
    tasks = await get_my_tasks(db, actor.team_id, actor)
    return WorkbenchResponse(tasks=tasks)
