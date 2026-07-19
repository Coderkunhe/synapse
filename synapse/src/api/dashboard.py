"""仪表盘聚合端点 — 为 React UI 提供轻量级统计数据。

薄路由层：认证 + 授权检查在此完成，聚合查询委托给 ``src.services.dashboard_service``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import NotFoundError
from src.services.dashboard_service import get_team_stats, get_projects_breakdown

dashboard_router = APIRouter(prefix="/dashboard")


@dashboard_router.get("/teams/{team_id}/stats")
async def team_stats(
    team_id: str = Path(...),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """仪表盘概览页面的聚合统计数据。"""
    if actor.team_id != team_id:
        raise NotFoundError("team", team_id)
    return await get_team_stats(db, team_id)


@dashboard_router.get("/teams/{team_id}/projects-breakdown")
async def projects_breakdown(
    team_id: str = Path(...),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Per-project task breakdown by status — PM 项目进度视图。"""
    if actor.team_id != team_id:
        raise NotFoundError("team", team_id)
    return await get_projects_breakdown(db, team_id)
