"""AnalysisRecord API routes — create + list + detail."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.permissions import require_permission
from src.exceptions import NotFoundError
from src.schemas.analysis import AnalysisCreate, AnalysisResponse
from src.schemas.common import CursorPage
from src.services.analysis_service import (
    analysis_to_response,
    create_analysis as _create_analysis,
    get_analysis as _get_analysis,
    list_analyses as _list_analyses,
)

from .helpers import get_project_or_404

router = APIRouter()


@router.post(
    "/projects/{project_id}/analyses",
    response_model=AnalysisResponse,
    status_code=201,
)
async def create_analysis(
    project_id: str,
    body: AnalysisCreate,
    actor: ActorInfo = Depends(require_permission("analysis:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create an analysis in a project (requires admin, lead, or orchestrator role)."""
    project = await get_project_or_404(db, project_id)

    analysis = await _create_analysis(
        db,
        project_id=project_id,
        title=body.title,
        content=body.content,
        analysis_type=body.analysis_type,
        source_batch_id=body.source_batch_id,
        metadata=body.metadata_,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return AnalysisResponse.model_validate(analysis_to_response(analysis))


@router.get(
    "/projects/{project_id}/analyses",
    response_model=CursorPage[AnalysisResponse],
)
async def list_analyses(
    project_id: str,
    analysis_type: str | None = Query(None, pattern=r"^(requirement|discussion|design)$"),
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("project", project_id)

    items, next_cursor, total = await _list_analyses(
        db,
        project_id,
        analysis_type=analysis_type,
        cursor=cursor,
        limit=limit,
    )
    return CursorPage(
        items=[AnalysisResponse.model_validate(analysis_to_response(a)) for a in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisResponse,
    responses={404: {"model": None}},
)
async def get_analysis(
    analysis_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    analysis = await _get_analysis(db, analysis_id)
    # Team-scoped: actor can only see analyses in their team's projects
    project = await get_project_or_404(db, analysis.project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("analysis", analysis_id)
    return AnalysisResponse.model_validate(analysis_to_response(analysis))
