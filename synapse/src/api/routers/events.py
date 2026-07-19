"""Event API routes — team-level and project-level event streams."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.constants import ActorType, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.exceptions import ForbiddenError, NotFoundError
from src.models.task import Task
from src.models.event import Event
from src.schemas.common import CursorPage
from src.schemas.event import EventResponse
from src.services.event_store import event_store

from .helpers import event_to_response, get_team_or_404, get_project_or_404

router = APIRouter()


@router.get(
    "/teams/{team_id}/events",
    response_model=CursorPage[EventResponse],
)
async def get_team_events(
    team_id: str,
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    # Workers cannot access team event streams
    if actor.actor_type == ActorType.WORKER:
        raise ForbiddenError(
            "FORBIDDEN_WORKERS_CANNOT_ACCESS_TEAM_EVENTS",
            "Workers cannot access team event streams",
        )

    items, next_cursor, total = await event_store.query_team_events(
        db, team_id, cursor=cursor, limit=limit
    )
    return CursorPage(
        items=[EventResponse.model_validate(event_to_response(e)) for e in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get(
    "/projects/{project_id}/events",
    response_model=CursorPage[EventResponse],
)
async def get_project_events(
    project_id: str,
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("project", project_id)

    # Get all task IDs for this project
    task_ids_stmt = select(Task.id).where(Task.project_id == project_id)
    task_ids_result = await db.execute(task_ids_stmt)
    task_ids = [row[0] for row in task_ids_result.all()]

    items, next_cursor = await event_store.query_project_events(
        db,
        team_id=project.team_id,
        task_ids=task_ids,
        cursor=cursor,
        limit=limit,
    )
    if task_ids:
        count_stmt = select(func.count(Event.id)).where(
            Event.team_id == project.team_id,
            Event.target_id.in_(task_ids),
        )
        total = (await db.execute(count_stmt)).scalar()
    else:
        total = 0
    return CursorPage(
        items=[EventResponse.model_validate(event_to_response(e)) for e in items],
        next_cursor=next_cursor,
        total=total,
    )
