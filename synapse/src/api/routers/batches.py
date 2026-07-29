"""Batch and Verification API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, ActorType, VerificationStatus
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import ForbiddenError, NotFoundError
from src.permissions import require_permission
from src.schemas.batch import BatchAssignRequest, BatchCreate, BatchResponse
from src.schemas.verification import (
    VerificationBatchRequest,
    VerificationBatchResponse,
    VerificationResponse,
    VerificationVerifyRequest,
)
from src.schemas.common import CursorPage
from src.services.batch_service import (
    assign_batch as _assign_batch,
    batch_to_response,
    create_batch as _create_batch,
    get_batch as _get_batch,
    list_batches as _list_batches,
)
from src.services.verification_service import (
    execute_batch_verification,
    execute_verification,
    get_task_verifications as _get_task_verifications,
    verification_to_response,
)

from .helpers import get_project_or_404


def _normalize_verdict(status: str) -> str:
    """Map intuitive verdict values to internal status (P9-B63: F-B61-3)."""
    return {"approved": VerificationStatus.PASSED, "rejected": VerificationStatus.FAILED}.get(status, status)


async def _resolve_project_from_verification(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from verification_id in URL path parameters.

    Used by ``require_permission`` for the verify endpoint
    (``POST /verifications/{verification_id}/verify``) which doesn't have
    ``project_id`` in its URL path.
    """
    from src.models.task import Task
    from src.models.verification import Verification

    verification_id = request.path_params["verification_id"]
    ver = await db.get(Verification, verification_id)
    if ver is None:
        raise NotFoundError("verification", verification_id)
    task = await db.get(Task, ver.task_id)
    return task.project_id


async def _resolve_project_from_batch(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from batch_id in URL path parameters.

    Used by ``require_permission`` for the assign_batch endpoint
    (``POST /batches/{batch_id}/assign``) which doesn't have
    ``project_id`` in its URL path.
    """
    batch_id = request.path_params["batch_id"]
    batch = await _get_batch(db, batch_id)
    return batch.project_id


router = APIRouter()


# ── Batch ─────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/batches",
    response_model=BatchResponse,
    status_code=201,
)
async def create_batch(
    project_id: str,
    body: BatchCreate,
    actor: ActorInfo = Depends(require_permission("batch:create")),
    db: AsyncSession = Depends(get_db),
):
    """Create a batch in a project (requires admin, lead, or orchestrator role)."""
    project = await get_project_or_404(db, project_id)

    batch = await _create_batch(
        db,
        project_id=project_id,
        name=body.name,
        description=body.description,
        order=body.order,
        phase=body.phase,
        batch_number=body.batch_number,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return BatchResponse.model_validate(batch_to_response(batch))


@router.get(
    "/batches/{batch_id}",
    response_model=BatchResponse,
    responses={404: {"model": None}},
)
async def get_batch(
    batch_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    batch = await _get_batch(db, batch_id)

    project = await get_project_or_404(db, batch.project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("batch", batch_id)

    return BatchResponse.model_validate(batch_to_response(batch))


@router.get(
    "/projects/{project_id}/batches",
    response_model=CursorPage[BatchResponse],
)
async def list_batches(
    project_id: str,
    cursor: str | None = Query(None, max_length=40),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_or_404(db, project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("project", project_id)

    batches, next_cursor, total = await _list_batches(
        db, project_id, cursor=cursor, limit=limit
    )
    return CursorPage(
        items=[BatchResponse.model_validate(batch_to_response(b)) for b in batches],
        next_cursor=next_cursor,
        total=total,
    )


# ── P9-B57: Batch 分配 ────────────────────────────────────────────


@router.post(
    "/batches/{batch_id}/assign",
    response_model=BatchResponse,
    responses={404: {"model": None}, 409: {"model": None}},
)
async def assign_batch(
    batch_id: str,
    body: BatchAssignRequest,
    actor: ActorInfo = Depends(require_permission("task:assign", resolve_project_id=_resolve_project_from_batch)),
    db: AsyncSession = Depends(get_db),
):
    """将 Batch 分配给一个 Worker（P7-007 分配原子）。

    一个 Batch 只能分配给一个 Worker，分配后不拆分。
    只有 status=active 的 Worker 可以接受分配。
    """
    batch = await _get_batch(db, batch_id)
    # 跨 team 隔离
    project = await get_project_or_404(db, batch.project_id)
    if project.team_id != actor.team_id:
        raise NotFoundError("batch", batch_id)

    batch = await _assign_batch(
        db,
        batch_id=batch_id,
        worker_id=body.worker_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return BatchResponse.model_validate(batch_to_response(batch))


# ── Verification ──────────────────────────────────────────────────

@router.post(
    "/verifications/{verification_id}/verify",
    response_model=VerificationResponse,
)
async def verify(
    verification_id: str,
    body: VerificationVerifyRequest,
    actor: ActorInfo = Depends(require_permission("task:verify", resolve_project_id=_resolve_project_from_verification)),
    db: AsyncSession = Depends(get_db),
):
    ver, task = await execute_verification(
        db,
        verification_id,
        status=_normalize_verdict(body.status),
        comment=body.comment,
        evidence=body.evidence,
        rejection_reason=body.rejection_reason,
        expected_version=body.expected_version,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return VerificationResponse.model_validate(verification_to_response(ver))


# ── P8-B6: Batch verification ─────────────────────────────────────

@router.post(
    "/verifications/batch",
    response_model=VerificationBatchResponse,
)
async def batch_verify(
    body: VerificationBatchRequest,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Execute multiple verifications in a single batch.

    Supports two-tier verification (Claude初审 → human终审):
    - Set auto_approved=True when Claude performs the initial review.
    - Set review_flag=True on individual items for boundary cases
      that need human judgment.  Flagged items keep their parent
      task in IN_VERIFICATION until the human resolves them.

    Permission is checked inline (not via require_permission guard)
    because the project_id must be resolved from the first item
    in the request body AFTER Pydantic validation.
    """
    # ── P11-B97 (㉕): batch_verify is human-only — reject Workers explicitly ──
    if actor.actor_type == ActorType.WORKER:
        raise ForbiddenError(
            "FORBIDDEN_WORKER_CANNOT_PERFORM_THIS_ACTION",
            "Batch verification is a human-only operation. "
            "Workers should submit verification results via POST /tasks/{id}/verifications.",
        )

    # Resolve project_id from first verification and check permission
    from src.models.task import Task
    from src.models.verification import Verification
    from src.permissions import PERMISSION_MAP, _expand_roles
    from src.services.project_role_service import get_project_role

    if body.items:
        vid = body.items[0].verification_id
        ver = await db.get(Verification, vid)
        if ver is not None:
            task = await db.get(Task, ver.task_id)
            if task is not None:
                pid = task.project_id
                # Inline permission check (batch_verify is not Worker-facing,
                # so 403 is correct for unauthorized humans)
                allowed = PERMISSION_MAP.get("task:verify", set())
                expanded = _expand_roles(allowed)
                if not actor.is_super_admin:
                    role = await get_project_role(db, pid, actor.actor_id)
                    if not role or role not in expanded:
                        raise ForbiddenError(
                            "FORBIDDEN_INSUFFICIENT_PERMISSION",
                            f"Permission 'task:verify' requires one of: {', '.join(sorted(expanded))}. "
                            f"Your project role: {role or '(none)'}.",
                        )
    items = [
        {
            "verification_id": it.verification_id,
            "status": _normalize_verdict(it.status),
            "comment": it.comment,
            "rejection_reason": it.rejection_reason,
            "review_flag": it.review_flag,
            "expected_version": it.expected_version,
        }
        for it in body.items
    ]
    result = await execute_batch_verification(
        db,
        items=items,
        auto_approved=body.auto_approved,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        team_id=actor.team_id,
    )
    await db.commit()
    return VerificationBatchResponse(**result)


@router.get(
    "/tasks/{task_id}/verifications",
    response_model=list[VerificationResponse],
)
async def get_task_verifications(
    task_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    verifications = await _get_task_verifications(db, task_id)
    return [
        VerificationResponse.model_validate(verification_to_response(v))
        for v in verifications
    ]
