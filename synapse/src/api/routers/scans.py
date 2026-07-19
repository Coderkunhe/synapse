"""ComplianceScan API routes — trigger scan, list, and retrieve."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, ScanTarget
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import NotFoundError, SynapseError
from src.schemas.common import CursorPage
from src.schemas.scan import ScanResponse
from src.services.scan_service import (
    execute_scan as _execute_scan,
    get_scan as _get_scan,
    list_scans as _list_scans,
    scan_to_response,
)

router = APIRouter()


async def _resolve_team_id(
    db: AsyncSession, target_type: str, target_id: str
) -> str:
    """Resolve the team that owns the target entity for authorization."""
    from src.models.batch import Batch
    from src.models.project import Project
    from src.models.task import Task

    if target_type == ScanTarget.TASK:
        task = await db.get(Task, target_id)
        if task is None:
            raise NotFoundError("task", target_id)
        project = await db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("project", task.project_id)
        return project.team_id

    if target_type == ScanTarget.BATCH:
        batch = await db.get(Batch, target_id)
        if batch is None:
            raise NotFoundError("batch", target_id)
        project = await db.get(Project, batch.project_id)
        if project is None:
            raise NotFoundError("project", batch.project_id)
        return project.team_id

    raise SynapseError(
        400,
        "UNSUPPORTED_SCAN_TARGET",
        f"Cannot resolve team for target_type={target_type!r}",
    )


@router.post(
    "/scans/{target_type}/{target_id}",
    response_model=ScanResponse,
    status_code=201,
)
async def execute_scan(
    target_type: str,
    target_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Execute all applicable compliance rules against a target entity.

    Supported target types: ``task``, ``batch``.
    ``skill`` and ``agent`` are reserved for future use.
    """
    # Validate target_type
    valid_targets = {t.value for t in ScanTarget}
    if target_type not in valid_targets:
        raise SynapseError(
            400,
            "INVALID_SCAN_TARGET",
            f"target_type must be one of {sorted(valid_targets)}, got {target_type!r}",
        )

    # Team-scoped auth: resolve owning team from target
    team_id = await _resolve_team_id(db, target_type, target_id)
    if team_id != actor.team_id:
        raise NotFoundError(target_type, target_id)

    # Execute scan
    scan = await _execute_scan(
        db,
        target_type=target_type,
        target_id=target_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return ScanResponse.model_validate(scan_to_response(scan))


@router.get(
    "/teams/{team_id}/scans",
    response_model=CursorPage[ScanResponse],
)
async def list_scans(
    team_id: str,
    target_type: str | None = Query(None, pattern=r"^(task|batch)$"),
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List compliance scans for the team, newest first.

    Optionally filtered by ``target_type``.
    """
    from .helpers import get_team_or_404

    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    items, next_cursor, total = await _list_scans(
        db,
        team_id,
        target_type=target_type,
        cursor=cursor,
        limit=limit,
    )
    return CursorPage(
        items=[scan_to_response(s) for s in items],
        next_cursor=next_cursor,
        total=total,
    )


@router.get(
    "/scans/{scan_id}",
    response_model=ScanResponse,
)
async def get_scan(
    scan_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a single compliance scan by ID."""
    scan = await _get_scan(db, scan_id)
    if scan.team_id != actor.team_id:
        raise NotFoundError("scan", scan_id)
    return ScanResponse.model_validate(scan_to_response(scan))
