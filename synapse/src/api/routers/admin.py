"""Admin API routes — failure detection trigger (P8-B7) + super-admin guard (P10-B17)
+ project role management (P10-B18)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, require_role, require_super_admin
from src.services.failure_detector import run_all_detections
from src.services.project_role_service import (
    get_project_role,
    list_project_roles,
    remove_project_role,
    set_project_role,
)

from .helpers import get_project_or_404

router = APIRouter()


@router.post("/failure-detection/run")
async def run_failure_detection(
    actor: ActorInfo = Depends(require_role("admin", "lead")),
    db: AsyncSession = Depends(get_db),
):
    """Trigger all four failure detection lines (P8-B7).

    Returns a summary of agents failed, tasks released, and reviews overdue.
    """
    result = await run_all_detections(db)
    await db.commit()
    return result


@router.get("/system-info")
async def system_info(
    actor: ActorInfo = Depends(require_super_admin()),
):
    """Return system-level info — super-admin only (P10-B17).

    This endpoint is the first consumer of is_super_admin and serves as
    the test surface for require_super_admin().
    """
    return {
        "super_admin": True,
        "actor_id": actor.actor_id,
        "user_id": actor.user_id,
    }


# ── P10-B18: Project Actor Role Management ─────────────────────


class ProjectRoleAssign(BaseModel):
    """Request body for assigning a project role to a worker."""
    worker_id: str = Field(..., min_length=1, max_length=40)
    role: str = Field(..., min_length=1, max_length=20, pattern=r"^(builder|orchestrator|steward|admin)$")


class ProjectRoleEntry(BaseModel):
    """Response entry for a single project role assignment."""
    worker_id: str
    worker_name: str
    role: str


class ProjectRoleList(BaseModel):
    """Response wrapper for project role listing."""
    project_id: str
    roles: list[ProjectRoleEntry]


@router.post(
    "/projects/{project_id}/roles",
    response_model=ProjectRoleEntry,
    status_code=201,
)
async def assign_project_role(
    project_id: str,
    body: ProjectRoleAssign,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Assign a role to a worker within a project (team admin only).

    Upserts: if the worker already has a role in this project, it is updated.
    """
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    record = await set_project_role(
        db,
        project_id=project_id,
        worker_id=body.worker_id,
        role=body.role,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    # Fetch worker name for response
    from src.models.worker import Worker
    worker = await db.get(Worker, body.worker_id)
    worker_name = worker.name if worker else body.worker_id

    return ProjectRoleEntry(
        worker_id=body.worker_id,
        worker_name=worker_name,
        role=body.role,
    )


@router.delete(
    "/projects/{project_id}/roles/{worker_id}",
    status_code=204,
)
async def revoke_project_role(
    project_id: str,
    worker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a worker's role in a project (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    await remove_project_role(
        db,
        project_id=project_id,
        worker_id=worker_id,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()


@router.get(
    "/projects/{project_id}/roles",
    response_model=ProjectRoleList,
)
async def list_project_role_assignments(
    project_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all worker-role assignments in a project (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    entries = await list_project_roles(db, project_id)
    return ProjectRoleList(
        project_id=project_id,
        roles=[
            ProjectRoleEntry(
                worker_id=worker.id,
                worker_name=worker.name,
                role=role,
            )
            for worker, role in entries
        ],
    )
