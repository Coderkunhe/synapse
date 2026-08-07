"""Project API routes — CRUD + archive + resolve-by-name."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor, require_role
from src.permissions import require_permission
from src.exceptions import ForbiddenError, NotFoundError
from src.schemas.common import CursorPage
from src.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectProtectionUpdate, ProjectResponse,
)
from src.services.project_role_service import get_project_role
from src.services.project_service import (
    archive_project as _archive_project,
    create_project as _create_project,
    delete_project as _delete_project,
    find_or_create_by_name as _find_or_create_by_name,
    get_project as _get_project,
    list_projects as _list_projects,
    project_to_response,
    toggle_protection as _toggle_protection,
    update_project as _update_project,
)

from .helpers import get_team_or_404, get_project_or_404

router = APIRouter()


@router.post(
    "/projects/resolve",
    response_model=ProjectResponse,
)
async def resolve_project(
    name: str = Query(..., min_length=1, max_length=200),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Find a project by name in the actor's team, or auto-create it.

    P9-B1: Task 入口放松 — Project 退化为可选标签。
    用户输入 project name → 前端调用此端点解析为 project_id。
    """
    # P12-B35: 防御 — 未加入 team 的 actor 无法创建 project
    if not actor.team_id:
        raise ForbiddenError(
            "NO_TEAM_MEMBERSHIP",
            "You must be a member of a team to create or resolve projects",
        )
    project = await _find_or_create_by_name(
        db,
        team_id=actor.team_id,
        name=name,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()
    return ProjectResponse.model_validate(project_to_response(project))


@router.post(
    "/teams/{team_id}/projects",
    response_model=ProjectResponse,
    status_code=201,
)
async def create_project(
    team_id: str,
    body: ProjectCreate,
    actor: ActorInfo = Depends(require_role("admin", "lead")),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    project = await _create_project(
        db,
        team_id=team_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        default_branch=body.default_branch,
        git_repo_url=body.git_repo_url,
        api_docs_url=body.api_docs_url,
        frontend_test_url=body.frontend_test_url,
        webhook_url=body.webhook_url,
        use_phase_mode=body.use_phase_mode,
        current_phase=body.current_phase,
        organization=body.organization,
        metadata=body.metadata,
        is_protected=body.is_protected,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()
    return ProjectResponse.model_validate(project_to_response(project))


@router.get(
    "/teams/{team_id}/projects",
    response_model=CursorPage[ProjectResponse],
)
async def list_projects(
    team_id: str,
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    projects, next_cursor, total = await _list_projects(
        db, team_id, cursor=cursor, limit=limit
    )
    return CursorPage(
        items=[ProjectResponse.model_validate(project_to_response(p)) for p in projects],
        next_cursor=next_cursor,
        total=total,
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    responses={404: {"model": None}},
)
async def get_project(
    project_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("project", project_id)
    return ProjectResponse.model_validate(project_to_response(project))


@router.get("/projects/{project_id}/my-role")
async def my_project_role(
    project_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Return the current actor's role in the specified project.

    P12-B18: Frontend uses this for canVerify/canEdit checks instead of
    the team-level role from AuthContext, which doesn't reflect project_actor_roles.
    Super admins get "admin" returned regardless of project role assignment.
    """
    if actor.is_super_admin:
        return {"role": "admin", "is_super_admin": True}
    role = await get_project_role(db, project_id, actor.actor_id)
    return {"role": role, "is_super_admin": False}


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    actor: ActorInfo = Depends(require_permission("project:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Update a project (requires admin role in this project)."""
    project = await get_project_or_404(db, project_id)

    project = await _update_project(
        db,
        project_id,
        name=body.name,
        description=body.description,
        default_branch=body.default_branch,
        git_repo_url=body.git_repo_url,
        api_docs_url=body.api_docs_url,
        frontend_test_url=body.frontend_test_url,
        webhook_url=body.webhook_url,
        use_phase_mode=body.use_phase_mode,
        current_phase=body.current_phase,
        organization=body.organization,
        metadata=body.metadata,
        is_protected=body.is_protected,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return ProjectResponse.model_validate(project_to_response(project))


@router.post(
    "/projects/{project_id}/archive",
    response_model=ProjectResponse,
)
async def archive_project(
    project_id: str,
    actor: ActorInfo = Depends(require_permission("project:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Archive a project (requires admin role in this project)."""
    project = await get_project_or_404(db, project_id)

    project = await _archive_project(
        db,
        project_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return ProjectResponse.model_validate(project_to_response(project))


@router.patch(
    "/projects/{project_id}/protection",
    response_model=ProjectResponse,
)
async def toggle_project_protection(
    project_id: str,
    body: ProjectProtectionUpdate,
    actor: ActorInfo = Depends(require_permission("project:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the ``is_protected`` flag on a project (admin only).

    Protected projects cannot be archived or deleted.
    """
    project = await get_project_or_404(db, project_id)

    project = await _toggle_protection(
        db,
        project_id,
        is_protected=body.is_protected,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return ProjectResponse.model_validate(project_to_response(project))


@router.delete(
    "/projects/{project_id}",
    status_code=204,
    responses={409: {"model": None}},
)
async def delete_project(
    project_id: str,
    actor: ActorInfo = Depends(require_permission("project:manage")),
    db: AsyncSession = Depends(get_db),
):
    """Hard-delete a project (admin only).

    Preconditions: archived, cooldown (7 days) passed, not protected.
    Automatically backs up the database before deletion.
    """
    project = await get_project_or_404(db, project_id)

    await _delete_project(
        db,
        project_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
