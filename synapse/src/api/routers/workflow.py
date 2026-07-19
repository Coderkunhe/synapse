"""Workflow + WorkflowRole API 路由 — CRUD 端点。

P10-B26: 议题 4 per-Workflow 角色 — API 路由层。

端点挂载在 ``/v1/admin/projects/{project_id}/workflows/...`` 下，
使用 team-level ``require_role("admin")`` 守卫（对标 admin.py 的 project role 端点）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.dependencies import ActorInfo, require_role

from src.services.workflow_role_service import (
    assign_workflow_role,
    complete_workflow,
    create_workflow,
    get_workflow,
    list_workflow_roles,
    list_workflows,
    revoke_workflow_role,
    update_workflow,
)

from .helpers import get_project_or_404

router = APIRouter()


# ── Inline request/response models ────────────────────────────────


class WorkflowCreateBody(BaseModel):
    """Request body for creating a Workflow."""
    name: str = Field(..., max_length=200)
    description: str | None = None
    status: str = Field(default="active")


class WorkflowUpdateBody(BaseModel):
    """Request body for updating a Workflow (all fields optional)."""
    name: str | None = Field(None, max_length=200)
    description: str | None = None
    status: str | None = None


class WorkflowResponse(BaseModel):
    """Response for a single Workflow."""
    id: str
    project_id: str
    name: str
    description: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


class WorkflowList(BaseModel):
    """Response wrapper for Workflow listing."""
    project_id: str
    workflows: list[WorkflowResponse]


class WorkflowRoleAssignBody(BaseModel):
    """Request body for assigning a Workflow role."""
    worker_id: str = Field(..., min_length=1, max_length=40)
    role: str = Field(..., min_length=1, max_length=20)


class WorkflowRoleEntry(BaseModel):
    """Response entry for a single WorkflowRole assignment."""
    worker_id: str
    worker_name: str
    role: str


class WorkflowRoleList(BaseModel):
    """Response wrapper for WorkflowRole listing."""
    workflow_id: str
    roles: list[WorkflowRoleEntry]


# ═══════════════════════════════════════════════════════════════
# Workflow CRUD
# ═══════════════════════════════════════════════════════════════


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=201,
)
async def create_workflow_endpoint(
    project_id: str,
    body: WorkflowCreateBody,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Workflow within a Project (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await create_workflow(
        db,
        project_id=project_id,
        name=body.name,
        description=body.description,
        status=body.status,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    return _wf_to_response(wf)


@router.get(
    "",
    response_model=WorkflowList,
)
async def list_workflows_endpoint(
    project_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all Workflows in a Project (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    workflows = await list_workflows(db, project_id)
    return WorkflowList(
        project_id=project_id,
        workflows=[_wf_to_response(w) for w in workflows],
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
)
async def get_workflow_endpoint(
    project_id: str,
    workflow_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single Workflow by ID (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await get_workflow(db, workflow_id)
    if wf is None or wf.project_id != project_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("workflow", workflow_id)

    return _wf_to_response(wf)


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowResponse,
)
async def update_workflow_endpoint(
    project_id: str,
    workflow_id: str,
    body: WorkflowUpdateBody,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a Workflow (team admin only). Only provided fields are changed."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await update_workflow(
        db,
        workflow_id=workflow_id,
        name=body.name,
        description=body.description,
        status=body.status,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if wf is None or wf.project_id != project_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("workflow", workflow_id)

    await db.commit()
    return _wf_to_response(wf)


@router.post(
    "/{workflow_id}/complete",
    response_model=WorkflowResponse,
)
async def complete_workflow_endpoint(
    project_id: str,
    workflow_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Mark a Workflow as completed (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await complete_workflow(
        db,
        workflow_id=workflow_id,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if wf is None or wf.project_id != project_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("workflow", workflow_id)

    await db.commit()
    return _wf_to_response(wf)


# ═══════════════════════════════════════════════════════════════
# WorkflowRole CRUD
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/{workflow_id}/roles",
    response_model=WorkflowRoleEntry,
    status_code=201,
)
async def assign_workflow_role_endpoint(
    project_id: str,
    workflow_id: str,
    body: WorkflowRoleAssignBody,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Assign a role to a Worker within a Workflow (team admin only).

    Upserts: if the worker already has a role, it is updated.
    """
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await get_workflow(db, workflow_id)
    if wf is None or wf.project_id != project_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("workflow", workflow_id)

    record = await assign_workflow_role(
        db,
        workflow_id=workflow_id,
        worker_id=body.worker_id,
        role=body.role,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()

    from src.models.worker import Worker
    worker = await db.get(Worker, body.worker_id)
    worker_name = worker.name if worker else body.worker_id

    return WorkflowRoleEntry(
        worker_id=body.worker_id,
        worker_name=worker_name,
        role=body.role,
    )


@router.get(
    "/{workflow_id}/roles",
    response_model=WorkflowRoleList,
)
async def list_workflow_roles_endpoint(
    project_id: str,
    workflow_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all Worker-role assignments in a Workflow (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await get_workflow(db, workflow_id)
    if wf is None or wf.project_id != project_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("workflow", workflow_id)

    entries = await list_workflow_roles(db, workflow_id)
    return WorkflowRoleList(
        workflow_id=workflow_id,
        roles=[
            WorkflowRoleEntry(
                worker_id=worker.id,
                worker_name=worker.name,
                role=role,
            )
            for worker, role in entries
        ],
    )


@router.delete(
    "/{workflow_id}/roles/{worker_id}",
    status_code=204,
)
async def revoke_workflow_role_endpoint(
    project_id: str,
    workflow_id: str,
    worker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a Worker's role in a Workflow (team admin only)."""
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("project", project_id)

    wf = await get_workflow(db, workflow_id)
    if wf is None or wf.project_id != project_id:
        from src.exceptions import NotFoundError
        raise NotFoundError("workflow", workflow_id)

    await revoke_workflow_role(
        db,
        workflow_id=workflow_id,
        worker_id=worker_id,
        team_id=actor.team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    await db.commit()


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _wf_to_response(wf) -> WorkflowResponse:
    """Convert ORM Workflow to WorkflowResponse."""
    return WorkflowResponse(
        id=wf.id,
        project_id=wf.project_id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        created_at=wf.created_at.isoformat() if wf.created_at else None,
        updated_at=wf.updated_at.isoformat() if wf.updated_at else None,
    )
