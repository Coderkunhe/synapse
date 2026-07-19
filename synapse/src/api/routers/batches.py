"""Batch and Verification API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, VerificationStatus
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor, require_project_role, require_role
from src.exceptions import NotFoundError
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
    actor: ActorInfo = Depends(require_project_role("admin", "lead", "orchestrator")),
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
    actor: ActorInfo = Depends(require_role("admin", "lead")),
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
    actor: ActorInfo = Depends(require_role("admin", "lead")),
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
    actor: ActorInfo = Depends(require_role("admin", "lead")),
    db: AsyncSession = Depends(get_db),
):
    """Execute multiple verifications in a single batch.

    Supports two-tier verification (Claude初审 → human终审):
    - Set auto_approved=True when Claude performs the initial review.
    - Set review_flag=True on individual items for boundary cases
      that need human judgment.  Flagged items keep their parent
      task in IN_VERIFICATION until the human resolves them.
    """
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
