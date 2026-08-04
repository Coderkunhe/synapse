"""Task API routes — CRUD, claim, assign, submit, cancel."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.constants import ActorType, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, OwnerType, ProjectStatus, VerificationStatus
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import ConflictError, ForbiddenError, NotFoundError, SynapseError
from src.models import ProjectActorRole
from src.permissions import require_permission
from src.schemas.common import CursorPage
from src.schemas.task import (
    BatchAssignRequest,
    BatchClaimResponse,
    BatchOperationError,
    BatchOperationResponse,
    BatchReadyRequest,
    BatchTaskCreateRequest,
    BatchUpdateRequest,
    BlockerReportRequest,
    TaskAssignRequest,
    TaskCancelRequest,
    TaskClaimRequest,
    TaskCreate,
    TaskReadyRequest,
    TaskSubmitRequest,
    TaskTerminateRequest,
    TaskUpdate,
    TaskResponse,
)
from src.services.batch_service import create_tasks_batch as _create_tasks_batch
from src.services.task_query import (
    get_available_tasks as _get_available_tasks,
    get_tasks as _get_tasks,
)
from src.services.task_service import (
    assign_batch as _assign_batch,
    assign_task as _assign_task,
    cancel_task as _cancel_task,
    claim_batch as _claim_batch,
    claim_task as _claim_task,
    create_task as _create_task,
    get_task as _get_task,
    ready_task as _ready_task,
    submit_task as _submit_task,
    task_to_response,
    terminate_task as _terminate_task,
    update_task as _update_task,
)

from .helpers import get_project_or_404


def _normalize_verdict(status: str) -> str:
    """Map intuitive verdict values to internal status (P9-B63: F-B61-3)."""
    return {"approved": VerificationStatus.PASSED, "rejected": VerificationStatus.FAILED}.get(status, status)


async def _worker_has_project_role(db: AsyncSession, worker_id: str, project_id: str) -> bool:
    """Check whether a Worker has an orchestrator/admin/lead role in a project.

    Workers with project-level management roles should have full visibility
    into all project tasks, not just the ones they own (PFL-032).
    """
    result = await db.execute(
        select(ProjectActorRole).where(
            ProjectActorRole.worker_id == worker_id,
            ProjectActorRole.project_id == project_id,
            ProjectActorRole.role.in_(["orchestrator", "admin", "lead"]),
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _resolve_project_from_task(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from task_id in URL path parameters.

    Used by ``require_permission`` for task_id-based routes (claim, submit,
    ready) that don't have ``project_id`` in their URL path.
    """
    task_id = request.path_params["task_id"]
    task = await _get_task(db, task_id)
    return task.project_id


async def _resolve_project_from_batch(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from batch_id in URL path parameters.

    Used by ``require_permission`` for batch_id-based routes (claim_batch)
    that don't have ``project_id`` in their URL path.
    """
    from src.services.batch_service import get_batch as _get_batch

    batch_id = request.path_params["batch_id"]
    batch = await _get_batch(db, batch_id)
    return batch.project_id


async def _resolve_project_from_task_ids_body(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from task_ids in the request body.

    Used by batch endpoints (batch-ready, batch-update, assign-batch) that
    receive ``task_ids`` in the request body rather than a single ID in the URL.

    Validates that all tasks belong to the same project.
    Starlette caches ``request.body()`` after the first read, so FastAPI's
    Pydantic body parsing still works after this resolver consumes the body.
    """
    body = await request.json()
    task_ids: list[str] = body.get("task_ids", [])
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required")
    first = await _get_task(db, task_ids[0])
    pid = first.project_id
    for tid in task_ids[1:]:
        t = await _get_task(db, tid)
        if t.project_id != pid:
            raise HTTPException(
                status_code=400,
                detail="All tasks in batch must belong to the same project",
            )
    return pid


router = APIRouter()


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=201,
)
async def create_task(
    project_id: str,
    body: TaskCreate,
    actor: ActorInfo = Depends(require_permission("task:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a task in a project (requires orchestrator role or above)."""
    project = await get_project_or_404(db, project_id)

    if project.status == ProjectStatus.ARCHIVED:
        raise ConflictError(
            "PROJECT_ARCHIVED",
            "Cannot create tasks in an archived project",
        )

    verifications = [
        {
            "type": v.type,
            "description": v.description,
            "criteria": v.criteria,
        }
        for v in body.verifications
    ]

    # P9-B6: serialize depends_on list[TaskDependency] → list[dict]
    depends_on = (
        [d.model_dump() for d in body.depends_on]
        if body.depends_on
        else None
    )

    task = await _create_task(
        db,
        project_id=project_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        parent_task_id=body.parent_task_id,
        batch_id=body.batch_id,
        estimated_effort=body.estimated_effort,
        tags=body.tags,
        required_capabilities=body.required_capabilities,
        metadata=body.metadata,
        deadline_at=body.deadline_at,
        verifications=verifications,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
        depends_on=depends_on,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.post(
    "/tasks/{task_id}/ready",
    response_model=TaskResponse,
)
async def ready_task(
    task_id: str,
    body: TaskReadyRequest | None = None,
    expected_version: int = Query(None, ge=1, description="Deprecated: use request body"),
    actor: ActorInfo = Depends(require_permission("task:ready", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    """Promote a task from BACKLOG to READY — makes it available for claiming (P100-B15 C2).

    Requires orchestrator role or above. Task must have a non-empty description
    and at least one verification.
    """
    version = body.expected_version if body else expected_version
    if version is None:
        raise SynapseError(status_code=422, code="MISSING_EXPECTED_VERSION", message="expected_version is required (use request body)")
    task = await _ready_task(
        db,
        task_id,
        expected_version=version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.post(
    "/projects/{project_id}/tasks/batch",
    response_model=list[TaskResponse],
    status_code=201,
)
async def create_tasks_batch(
    project_id: str,
    body: BatchTaskCreateRequest,
    actor: ActorInfo = Depends(require_permission("task:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create multiple tasks atomically (P8-B9, D-P7-023: Creator batch operations).

    All-or-nothing: if any task fails validation, the entire batch is rejected.
    Maximum 20 tasks per batch.
    Requires admin, lead, or orchestrator role in the project.
    """
    project = await get_project_or_404(db, project_id)

    if project.status == ProjectStatus.ARCHIVED:
        raise ConflictError(
            "PROJECT_ARCHIVED",
            "Cannot create tasks in an archived project",
        )

    task_dicts = []
    for task_create in body.tasks:
        verifications = [
            {"type": v.type, "description": v.description, "criteria": v.criteria}
            for v in task_create.verifications
        ]
        # P11-B60 G1: serialize depends_on (mirrors single-task create at :161-164)
        depends_on = (
            [d.model_dump() for d in task_create.depends_on]
            if task_create.depends_on
            else None
        )
        task_dicts.append({
            "title": task_create.title,
            "description": task_create.description,
            "priority": task_create.priority,
            "parent_task_id": task_create.parent_task_id,
            "batch_id": task_create.batch_id,
            "estimated_effort": task_create.estimated_effort,
            "tags": task_create.tags,
            "metadata": task_create.metadata,
            "deadline_at": task_create.deadline_at,
            "depends_on": depends_on,
            "verifications": verifications,
        })

    tasks = await _create_tasks_batch(
        db,
        project_id=project_id,
        tasks=task_dicts,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return [TaskResponse.model_validate(await task_to_response(t, db, current_actor_id=actor.actor_id)) for t in tasks]


@router.get(
    "/projects/{project_id}/tasks",
    response_model=CursorPage[TaskResponse],
)
async def list_tasks(
    project_id: str,
    status: str | None = Query(None, description="Filter by task status, or 'overdue' for deadline-passed tasks"),
    owner_id: str | None = Query(None, description="Filter by owner ID (worker or member)"),
    batch_id: str | None = Query(None, description="Filter by batch ID"),
    search: str | None = Query(None, description="Search in task title (ILIKE)"),
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List all tasks in a project, with optional filters and cursor pagination.

    Unlike ``/tasks/available``, this returns tasks in ALL statuses by default.
    """
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("project", project_id)

    tasks, next_cursor, total = await _get_tasks(
        db, project_id, status=status, owner_id=owner_id,
        batch_id=batch_id, search=search, cursor=cursor, limit=limit,
    )
    items = [TaskResponse.model_validate(await task_to_response(t, db, current_actor_id=actor.actor_id)) for t in tasks]
    return CursorPage(items=items, next_cursor=next_cursor, total=total)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses={404: {"model": None}},
)
async def get_task(
    task_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, task_id)

    project = await get_project_or_404(db, task.project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("task", task_id)

    # Worker visibility: workers only see tasks they own,
    # unless they hold a project management role (PFL-032).
    if actor.actor_type == ActorType.WORKER:
        has_project_role = await _worker_has_project_role(db, actor.actor_id, task.project_id)
        if not has_project_role:
            if task.owner_type != OwnerType.WORKER or task.owner_id != actor.actor_id:
                raise NotFoundError("task", task_id)

    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskResponse,
)
async def update_task(
    task_id: str,
    body: TaskUpdate,
    actor: ActorInfo = Depends(require_permission("task:update", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, task_id)
    project = await get_project_or_404(db, task.project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("task", task_id)

    task = await _update_task(
        db,
        task_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        estimated_effort=body.estimated_effort,
        tags=body.tags,
        required_capabilities=body.required_capabilities,
        metadata=body.metadata,
        deadline_at=body.deadline_at,
        expected_version=body.expected_version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.get(
    "/projects/{project_id}/tasks/available",
    response_model=CursorPage[TaskResponse],
)
async def get_available_tasks(
    project_id: str,
    capability: str | None = Query(None),
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("project", project_id)

    tasks, next_cursor, total = await _get_available_tasks(
        db, project_id, capability=capability, cursor=cursor, limit=limit
    )
    items = [TaskResponse.model_validate(await task_to_response(t, db, current_actor_id=actor.actor_id)) for t in tasks]
    return CursorPage(items=items, next_cursor=next_cursor, total=total)


@router.post(
    "/tasks/{task_id}/claim",
    response_model=TaskResponse,
)
async def claim_task(
    task_id: str,
    body: TaskClaimRequest | None = None,
    expected_version: int = Query(None, ge=1, description="Deprecated: use request body"),
    actor: ActorInfo = Depends(require_permission("task:claim", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    version = body.expected_version if body else expected_version
    if version is None:
        raise SynapseError(
            status_code=422,
            code="MISSING_EXPECTED_VERSION",
            message=f"expected_version is required. "
            f"Use GET /v1/projects/<project_id>/tasks or GET /v1/tasks/available "
            f"to obtain the current version from the task list, "
            f"then include it in your request body.",
        )

    task = await _claim_task(
        db, task_id, worker_id=actor.actor_id, worker_team_id=actor.team_id,
        expected_version=version, actor_type=actor.actor_type,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.post(
    "/batches/{batch_id}/claim",
    response_model=BatchClaimResponse,
    status_code=200,
)
async def claim_batch(
    batch_id: str,
    actor: ActorInfo = Depends(require_permission("task:claim", resolve_project_id=_resolve_project_from_batch)),
    db: AsyncSession = Depends(get_db),
):
    """Claim all READY tasks in a batch (P8-B3 pull mode)."""
    result = await _claim_batch(
        db, batch_id, worker_id=actor.actor_id, worker_team_id=actor.team_id,
        actor_type=actor.actor_type,
    )
    await db.commit()
    return BatchClaimResponse(**result)


@router.post(
    "/tasks/assign-batch",
    response_model=BatchClaimResponse,
    status_code=200,
)
async def assign_batch(
    body: BatchAssignRequest,
    actor: ActorInfo = Depends(require_permission("task:assign", resolve_project_id=_resolve_project_from_task_ids_body)),
    db: AsyncSession = Depends(get_db),
):
    """Assign multiple tasks to an owner at once (P8-B3 push mode, D-P7-023)."""
    result = await _assign_batch(
        db,
        task_ids=body.task_ids,
        owner_type=body.owner_type,
        owner_id=body.owner_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return BatchClaimResponse(**result)


@router.post(
    "/tasks/{task_id}/assign",
    response_model=TaskResponse,
)
async def assign_task(
    task_id: str,
    body: TaskAssignRequest,
    actor: ActorInfo = Depends(require_permission("task:assign", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    task = await _assign_task(
        db,
        task_id,
        owner_type=body.owner_type,
        owner_id=body.owner_id,
        expected_version=body.expected_version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.post(
    "/tasks/{task_id}/submit",
    response_model=TaskResponse,
)
async def submit_task(
    task_id: str,
    body: TaskSubmitRequest,
    actor: ActorInfo = Depends(require_permission("task:submit", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    verification_results = [
        {
            "verification_id": vr.verification_id,
            "status": _normalize_verdict(vr.status),
            "evidence": vr.evidence,
        }
        for vr in body.verification_results
    ]

    task = await _submit_task(
        db,
        task_id,
        summary=body.summary,
        evidence=body.evidence,
        verification_results=verification_results,
        expected_version=body.expected_version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskResponse,
)
async def cancel_task(
    task_id: str,
    body: TaskCancelRequest | None = None,
    expected_version: int = Query(None, ge=1, description="Deprecated: use request body"),
    actor: ActorInfo = Depends(require_permission("task:cancel", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    version = body.expected_version if body else expected_version
    if version is None:
        raise SynapseError(status_code=422, code="MISSING_EXPECTED_VERSION", message="expected_version is required (use request body)")
    task = await _cancel_task(
        db,
        task_id,
        expected_version=version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


@router.post(
    "/tasks/{task_id}/terminate",
    response_model=TaskResponse,
)
async def terminate_task(
    task_id: str,
    body: TaskTerminateRequest,
    actor: ActorInfo = Depends(require_permission("task:terminate", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    """Permanently terminate a task — cancel + release worker back to pool (P8-B9, I2).

    Differs from cancel: explicitly clears ownership fields (owner_type, owner_id)
    to release the worker. Valid from any pre-terminal state.
    """
    task = await _terminate_task(
        db,
        task_id,
        reason=body.reason,
        expected_version=body.expected_version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


# ── P8-B7: Blocker report ─────────────────────────────────────────


@router.post(
    "/tasks/{task_id}/blocker",
    response_model=TaskResponse,
)
async def report_blocker(
    task_id: str,
    body: BlockerReportRequest,
    actor: ActorInfo = Depends(require_permission("task:report_blocker", resolve_project_id=_resolve_project_from_task)),
    db: AsyncSession = Depends(get_db),
):
    """Worker reports a blocker on a task — task is released back to READY (P8-B7).

    Only the task owner (worker) can report a blocker.
    Does NOT increment redo_count — blockers are not the Worker's fault.
    """
    if actor.actor_type != ActorType.WORKER:
        raise ForbiddenError(
            "FORBIDDEN_ONLY_WORKERS_CAN_REPORT_BLOCKERS",
            "Only workers can report blockers",
        )

    from src.services.failure_detector import report_blocker as _report_blocker

    task = await _report_blocker(
        db,
        task_id,
        blocker_type=body.blocker_type,
        description=body.description,
        suggested_fix=body.suggested_fix,
        expected_version=body.expected_version,
        worker_id=actor.actor_id,
        worker_team_id=actor.team_id,
    )
    await db.commit()
    return TaskResponse.model_validate(await task_to_response(task, db, current_actor_id=actor.actor_id))


# ── P9-B72: Batch operations (S-033) ─────────────────────────────


@router.post(
    "/tasks/batch-ready",
    response_model=BatchOperationResponse,
    status_code=200,
)
async def batch_ready(
    body: BatchReadyRequest,
    actor: ActorInfo = Depends(require_permission("task:ready", resolve_project_id=_resolve_project_from_task_ids_body)),
    db: AsyncSession = Depends(get_db),
):
    """批量将 Task 从 BACKLOG 提升为 READY（P9-B72, S-033）。

    部分成功模式：每个 task 独立处理，失败的不影响其他。
    expected_version 由服务端内部获取，调用方不需要传。
    """
    updated_ids: list[str] = []
    errors: list[BatchOperationError] = []

    for task_id in body.task_ids:
        try:
            task = await _get_task(db, task_id)
        except NotFoundError:
            errors.append(BatchOperationError(task_id=task_id, error="NOT_FOUND"))
            continue

        try:
            await _ready_task(
                db,
                task_id,
                expected_version=task.version_no,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                team_id=actor.team_id,
            )
            updated_ids.append(task_id)
        except Exception as e:
            errors.append(BatchOperationError(
                task_id=task_id,
                error=getattr(e, "code", type(e).__name__),
            ))

    await db.commit()
    return BatchOperationResponse(
        updated_count=len(updated_ids),
        failed_count=len(errors),
        task_ids=updated_ids,
        errors=errors,
    )


@router.post(
    "/tasks/batch-update",
    response_model=BatchOperationResponse,
    status_code=200,
)
async def batch_update(
    body: BatchUpdateRequest,
    actor: ActorInfo = Depends(require_permission("task:update", resolve_project_id=_resolve_project_from_task_ids_body)),
    db: AsyncSession = Depends(get_db),
):
    """批量更新 Task 字段 — priority, effort, tags, deadline（P9-B72, S-033）。

    部分成功模式：每个 task 独立处理，失败的不影响其他。
    expected_version 由服务端内部获取，调用方不需要传。
    """
    updated_ids: list[str] = []
    errors: list[BatchOperationError] = []

    for task_id in body.task_ids:
        try:
            task = await _get_task(db, task_id)
        except NotFoundError:
            errors.append(BatchOperationError(task_id=task_id, error="NOT_FOUND"))
            continue

        try:
            await _update_task(
                db,
                task_id,
                title=None,
                description=None,
                priority=body.priority,
                estimated_effort=body.estimated_effort,
                tags=body.tags,
                required_capabilities=body.required_capabilities,
                metadata=None,
                deadline_at=body.deadline_at,
                expected_version=task.version_no,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                team_id=actor.team_id,
            )
            updated_ids.append(task_id)
        except Exception as e:
            errors.append(BatchOperationError(
                task_id=task_id,
                error=getattr(e, "code", type(e).__name__),
            ))

    await db.commit()
    return BatchOperationResponse(
        updated_count=len(updated_ids),
        failed_count=len(errors),
        task_ids=updated_ids,
        errors=errors,
    )
