"""Worker API routes — registration, lifecycle, handshake, heartbeat."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import extract_bearer_token, hash_api_key, hash_project_key
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor, require_role
from src.exceptions import AuthenticationError, ForbiddenError, NotFoundError, SynapseError
from src.models.worker import Worker
from src.constants import ActorType, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, TaskStatus, WorkerActorType, WorkerStatus
from src.models.project import Project
from src.models.task import Task
from src.models.authorization_request import AuthorizationRequest
from src.permissions import require_permission
from src.schemas.worker import (
    API_KEY_WARNING,
    AuthRequestStateSummary,
    ErrorReportRequest,
    ErrorReportResponse,
    ErrorReportSummary,
    TaskStateSummary,
    WorkerCreate,
    WorkerCreateResponse,
    WorkerHandshakeRequest,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerProjectResponse,
    WorkerResponse,
    WorkerStateResponse,
    OrchestratorStatusResponse,
)
from src.schemas.common import CursorPage
from src.schemas.protocol import ProtocolResponse
from src.services.worker_service import (
    worker_handshake as _worker_handshake,
    worker_heartbeat as _worker_heartbeat,
    worker_to_response,
    deactivate_worker,
    get_worker as _get_worker,
    hard_delete_worker,
    list_workers as _list_workers,
    register_worker as _register_worker,
    resume_worker as _resume_worker,
    suspend_worker as _suspend_worker,
    get_orchestrator_status,
)
from src.services.project_role_service import get_worker_projects
from src.services.worker_scheduler import start_task as _start_task

from src.services.template_service import render_protocol, resolve_role, compute_template_versions

from src.services.event_store import event_store
from src.services.pitfall_service import create_pitfall

from .helpers import get_team_or_404

logger = logging.getLogger(__name__)

router = APIRouter()
agents_router = APIRouter()  # backward compat, all routes deprecated


# ── Helpers ────────────────────────────────────────────────────────────


async def _resolve_human_worker_id(db: AsyncSession, actor: ActorInfo) -> str | None:
    """Return the human Worker ID for the current actor.

    P10-B7: actor_id is now a worker_id (derived from member_id via derive_id).
    For humans (actor_type=HUMAN, has role), actor_id IS the worker_id.
    For AI agents (actor_type=WORKER, no role), return None.
    """
    if actor.actor_type == ActorType.WORKER:
        return None  # AI agent — no human worker to resolve
    # Human actor — actor_id is already the worker_id (P10-B7).
    # Verify the Worker exists and return its id.
    worker = await db.get(Worker, actor.actor_id)
    return worker.id if worker else None


async def _resolve_project_from_task_query(request: Request, db: AsyncSession) -> str:
    """Resolve project_id from task_id in query parameters.

    Used by ``require_permission`` for the start-task endpoint where
    ``task_id`` is a query parameter (not a path parameter).
    """
    from src.services.task_service import get_task as _get_task_svc

    task_id = request.query_params.get("task_id")
    if not task_id:
        raise RuntimeError("Missing 'task_id' query parameter for project resolution")
    task = await _get_task_svc(db, task_id)
    return task.project_id


# ═══════════════════════════════════════════════════════════════════
# Project Discovery (P11-B9)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/me/projects",
    response_model=list[WorkerProjectResponse],
)
async def get_my_projects(
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """List all projects the current actor belongs to.

    For both human and worker actors, actor_id is the worker_id.
    Returns each project's basic info plus the actor's role in it.
    Used by Workers for project discovery — the first step after boot.
    """
    projects = await get_worker_projects(db, actor.actor_id)
    return [WorkerProjectResponse(**p) for p in projects]


# ═══════════════════════════════════════════════════════════════════
# P12-B5: Worker State Snapshot — Codex sandbox state channel
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/me/state",
    response_model=WorkerStateResponse,
)
async def get_worker_state(
    project_id: str = Query(..., description="Project ID to load state for"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """P12-B5: Return full Worker state snapshot.

    Replaces ``_task-current.md`` for Workers whose sandbox prevents
    local file writes (Codex CLI ``.agents/`` read-only).

    Returns identity, active tasks, pending auth requests, stale
    detection — everything the Worker AI needs to orient itself.
    """
    from datetime import datetime, timedelta, timezone

    worker = await _get_worker(db, actor.actor_id)

    # Verify project access
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    if project.team_id != worker.team_id:
        raise ForbiddenError(
            "FORBIDDEN_CROSS_TEAM",
            "Worker and project belong to different teams",
        )

    # Resolve role
    from src.services.template_service import resolve_role
    resolved_role, _role_source = resolve_role(worker)

    # ── Query tasks by status ──
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    STALE_THRESHOLD_MINUTES = 15

    def _task_summary(t) -> TaskStateSummary:
        return TaskStateSummary(
            id=t.id,
            title=t.title,
            status=t.status,
            owner_id=t.owner_id,
            owner_name=getattr(t, "owner_name", None),
            owner_type=getattr(t, "owner_type", None),
            priority=t.priority,
            batch_id=t.batch_id,
            depends_on=t.depends_on or [],
            updated_at=t.updated_at,
            created_at=t.created_at,
        )

    # in_progress
    in_progress_result = await db.execute(
        select(Task)
        .where(Task.project_id == project_id, Task.status == TaskStatus.IN_PROGRESS)
        .order_by(Task.updated_at.desc())
    )
    in_progress_tasks = [_task_summary(t) for t in in_progress_result.scalars().all()]

    # ready
    ready_result = await db.execute(
        select(Task)
        .where(Task.project_id == project_id, Task.status == TaskStatus.READY)
        .order_by(Task.created_at.asc())
    )
    ready_tasks = [_task_summary(t) for t in ready_result.scalars().all()]

    # in_verification (Orchestrator view)
    ver_result = await db.execute(
        select(Task)
        .where(Task.project_id == project_id, Task.status == TaskStatus.IN_VERIFICATION)
        .order_by(Task.updated_at.desc())
    )
    verification_tasks = [_task_summary(t) for t in ver_result.scalars().all()]

    # all active (non-completed, non-cancelled)
    all_active_result = await db.execute(
        select(Task)
        .where(
            Task.project_id == project_id,
            Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]),
        )
        .order_by(Task.updated_at.desc())
        .limit(50)
    )
    all_active_tasks = [_task_summary(t) for t in all_active_result.scalars().all()]

    active_task_count = len(all_active_tasks)

    # ── Pending authorization requests ──
    auth_result = await db.execute(
        select(AuthorizationRequest)
        .where(
            AuthorizationRequest.worker_id == actor.actor_id,
            AuthorizationRequest.status == "pending",
        )
        .order_by(AuthorizationRequest.created_at.desc())
    )
    pending_auth_requests = [
        AuthRequestStateSummary(
            id=ar.id,
            request_type=ar.request_type,
            status=ar.status,
            created_at=ar.created_at,
            capability_name=ar.operation if ar.request_type == "api_auth" else ar.prompt_type,
        )
        for ar in auth_result.scalars().all()
    ]

    # ── Stale detection: in_verification tasks stuck > 15 min ──
    stale_cutoff = now - timedelta(minutes=STALE_THRESHOLD_MINUTES)
    stale_vt = [t for t in verification_tasks
                if t.updated_at and t.updated_at < stale_cutoff]

    # ── P14-B2 G1: Recent error reports ──
    from src.constants import EventType as ET
    from src.models.event import Event as EventModel
    recent_errors_result = await db.execute(
        select(EventModel)
        .where(
            EventModel.event_type == ET.WORKER_ERROR_REPORTED,
            EventModel.actor_id == actor.actor_id,
        )
        .order_by(EventModel.created_at.desc())
        .limit(5)
    )
    import json as json_module
    recent_errors = []
    for evt in recent_errors_result.scalars().all():
        raw_payload = evt.payload or {}
        if isinstance(raw_payload, str):
            try:
                payload = json_module.loads(raw_payload)
            except (json_module.JSONDecodeError, TypeError):
                payload = {}
        else:
            payload = raw_payload
        recent_errors.append(ErrorReportSummary(
            id=evt.id,
            error_type=payload.get("error_type", "unknown"),
            task_id=payload.get("task_id"),
            summary=payload.get("summary", ""),
            severity=payload.get("severity", "🔴"),
            created_at=evt.created_at,
        ))

    # ── Assemble response ──
    return WorkerStateResponse(
        worker_id=worker.id,
        worker_name=worker.name,
        role=resolved_role,
        project_id=project_id,
        project_name=project.name,
        runtime_status=getattr(worker, "runtime_status", None),
        generated_at=now,
        in_progress_tasks=in_progress_tasks,
        ready_tasks=ready_tasks,
        verification_tasks=verification_tasks,
        all_active_tasks=all_active_tasks,
        active_task_count=active_task_count,
        pending_auth_requests=pending_auth_requests,
        stale_verification_count=len(stale_vt),
        stale_verification_task_ids=[t.id for t in stale_vt],
        recent_error_reports=recent_errors,
    )


# ═══════════════════════════════════════════════════════════════════
# P14-B2 G1: Builder Error Report
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/workers/{worker_id}/error-report",
    response_model=ErrorReportResponse,
    status_code=201,
)
async def report_error(
    worker_id: str,
    body: ErrorReportRequest,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Builder 结构化错误上报（P14-B2 G1）。

    Builder 通过此端点提交结构化错误上下文，
    替代非结构化的 conversation comment 模式。
    O 在 worker state 中可直接看到最近 5 条错误。

    severity=🔴 时自动触发 G2 通路：创建 PFL + escalation Task。
    """
    # ── 权限：只有 Worker 自身或 Admin 可上报 ──
    if actor.actor_id != worker_id and actor.actor_type not in (ActorType.HUMAN,):
        # Human admins can report on behalf of workers
        from src.models import ProjectActorRole
        is_admin = await db.execute(
            select(ProjectActorRole).where(
                ProjectActorRole.worker_id == actor.actor_id,
                ProjectActorRole.role.in_(["admin", "lead"]),
            )
        )
        if not is_admin.scalar():
            raise ForbiddenError(
                "FORBIDDEN_NOT_WORKER_OWNER",
                "Only the worker itself or an admin can report errors for this worker",
            )

    # ── 校验 worker 存在 ──
    worker = await _get_worker(db, worker_id)
    team_id = worker.team_id

    # ── 可选：校验 task 存在 ──
    project_id = ""
    if body.task_id:
        task = await db.get(Task, body.task_id)
        if task is None:
            raise NotFoundError("task", body.task_id)
        project_id = task.project_id

    # ── 记录 Event ──
    from datetime import datetime, timezone
    from uuid import uuid4
    from src.constants import EventType as ET

    now = datetime.now(timezone.utc)
    event = await event_store.record(
        db,
        event_type=ET.WORKER_ERROR_REPORTED,
        team_id=team_id,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        target_type="worker",
        target_id=worker_id,
        payload={
            "error_type": body.error_type,
            "task_id": body.task_id,
            "summary": body.summary,
            "detail": body.detail,
            "context": body.context or {},
            "severity": body.severity,
        },
    )

    # ── 如果关联 task，创建 conversation message ──
    if body.task_id and project_id:
        try:
            from src.services.conversation_service import create_message
            savepoint = await db.begin_nested()
            await create_message(
                db,
                task_id=body.task_id,
                workflow_id=None,
                message_type="blocking",
                body=(
                    f"🚨 **Builder 错误上报**\n\n"
                    f"- **Worker**: {worker.name} (`{worker_id}`)\n"
                    f"- **错误类型**: `{body.error_type}`\n"
                    f"- **严重度**: {body.severity}\n"
                    f"- **摘要**: {body.summary}\n"
                    + (f"\n**详情**:\n```\n{body.detail}\n```" if body.detail else "")
                ),
                in_reply_to_id=None,
                sender_worker_id=worker_id,
                team_id=team_id,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
            )
            await savepoint.commit()
        except Exception:
            logger.warning(
                "Failed to create error-report message for task %s (event still recorded)",
                body.task_id,
                exc_info=True,
            )

    # ── WS push 通知所有 Orchestrator ──
    try:
        from src.models import ProjectActorRole as PAR
        from src.services.ws_manager import ws_manager
        orch_result = await db.execute(
            select(PAR).where(
                PAR.project_id == project_id,
                PAR.role.in_(["orchestrator", "admin", "lead"]),
            )
        ) if project_id else None
        orch_roles = orch_result.scalars().all() if orch_result else []
        for orch_role in orch_roles:
            await ws_manager.broadcast_to_actor(
                orch_role.worker_id,
                {
                    "type": "worker.error_reported",
                    "data": {
                        "worker_id": worker_id,
                        "worker_name": worker.name,
                        "error_type": body.error_type,
                        "task_id": body.task_id,
                        "summary": body.summary,
                        "severity": body.severity,
                    },
                },
            )
    except Exception:
        logger.warning("WS push failed for error report", exc_info=True)

    # ── G2: severity=🔴 自动创建 PFL + Task ──
    pfl_id = None
    escalation_task_id = None
    if body.severity == "🔴":
        try:
            pfl_id = create_pitfall(
                title=f"[{body.error_type}] {body.summary}",
                description=(
                    f"Worker `{worker_id}` ({worker.name}) 上报严重错误。\n\n"
                    f"- **错误类型**: `{body.error_type}`\n"
                    + (f"- **关联 Task**: `{body.task_id}`\n" if body.task_id else "")
                    + f"- **详情**: {body.detail or '无'}"
                ),
                severity="🔴",
                cause=body.detail or "见 detail 字段",
                fix_direction="Builder 需诊断并修复 · 关联 escalation Task 跟踪",
                discovery_source="P14-B2 自动登记（Worker error report）",
            )
        except Exception:
            logger.warning("Failed to auto-create PFL for error report", exc_info=True)

        # 自动创建 escalation Task
        if project_id and pfl_id:
            try:
                from src.services.task_create import create_task as _create_task_svc
                escalation_task = await _create_task_svc(
                    db,
                    project_id=project_id,
                    title=f"[{pfl_id}] {body.summary[:100]}",
                    description=(
                        f"## Escalation Task（自动创建 · P14-B2 G2）\n\n"
                        f"- **来源**: Worker `{worker_id}` ({worker.name}) 错误上报\n"
                        f"- **PFL**: {pfl_id}\n"
                        f"- **错误类型**: `{body.error_type}`\n"
                        + (f"- **关联 Task**: `{body.task_id}`\n" if body.task_id else "")
                        + f"\n### 错误详情\n\n{body.detail or '无详情'}\n\n"
                        f"### 上下文\n\n```json\n{body.context or {}}\n```"
                    ),
                    priority="p1",
                    parent_task_id=None,
                    batch_id=None,
                    estimated_effort=None,
                    tags=None,
                    metadata=None,
                    deadline_at=None,
                    verifications=[],
                    actor_type=ActorType.SYSTEM,
                    actor_id="error_report_handler",
                    team_id=team_id,
                )
                escalation_task_id = escalation_task.id
            except Exception:
                logger.warning("Failed to auto-create escalation Task", exc_info=True)

    await db.commit()

    return ErrorReportResponse(
        id=str(uuid4()),
        worker_id=worker_id,
        error_type=body.error_type,
        task_id=body.task_id,
        summary=body.summary,
        event_id=event.id,
        pfl_id=pfl_id,
        escalation_task_id=escalation_task_id,
        severity=body.severity,
        created_at=now,
    )


# ═══════════════════════════════════════════════════════════════════
# Worker Registration
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/teams/{team_id}/workers",
    response_model=WorkerCreateResponse,
    status_code=201,
)
async def register_worker(
    team_id: str,
    body: WorkerCreate,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    worker, api_key = await _register_worker(
        db,
        team_id=team_id,
        name=body.name,
        provider=body.provider,
        provider_model=body.provider_model,
        system_prompt=body.system_prompt,
        metadata=body.metadata,
        registered_by=await _resolve_human_worker_id(db, actor),
        batch_size=body.batch_size,  # P9-B57
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        project_id=body.project_id,  # PFL-105 (B106)
        project_role=body.role,  # PFL-105 (B106)
    )
    await db.commit()

    return WorkerCreateResponse(
        worker=WorkerResponse.model_validate(worker_to_response(worker)),
        api_key=api_key,
        warning=API_KEY_WARNING,
    )


# ── Deprecated ──


@agents_router.post(
    "/teams/{team_id}/agents",
    response_model=WorkerCreateResponse,
    status_code=201,
    deprecated=True,
)
async def register_agent(
    team_id: str,
    body: WorkerCreate,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await register_worker(team_id=team_id, body=body, actor=actor, db=db)


# ═══════════════════════════════════════════════════════════════════
# Worker Listing
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/teams/{team_id}/workers",
    response_model=CursorPage[WorkerResponse],
)
async def list_workers(
    team_id: str,
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    status: str | None = Query(None, description="Filter: active | suspended | all"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    team = await get_team_or_404(db, team_id)
    if team.id != actor.team_id:
        raise NotFoundError("team", team_id)

    workers, next_cursor, total = await _list_workers(
        db, team_id, cursor=cursor, limit=limit, status=status
    )
    items = [WorkerResponse.model_validate(worker_to_response(w)) for w in workers]
    return CursorPage(items=items, next_cursor=next_cursor, total=total)


# ── Deprecated ──


@agents_router.get(
    "/teams/{team_id}/agents",
    response_model=CursorPage[WorkerResponse],
    deprecated=True,
)
async def list_agents(
    team_id: str,
    cursor: str | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    status: str | None = Query(None, description="Filter: active | suspended | all"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    return await list_workers(
        team_id=team_id, cursor=cursor, limit=limit, status=status, actor=actor, db=db
    )


# ═══════════════════════════════════════════════════════════════════
# Worker Detail
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/{worker_id}",
    response_model=WorkerResponse,
    responses={404: {"model": None}},
)
async def get_worker(
    worker_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    worker = await _get_worker(db, worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)
    return WorkerResponse.model_validate(worker_to_response(worker))


# ── Deprecated ──


@agents_router.get(
    "/agents/{agent_id}",
    response_model=WorkerResponse,
    deprecated=True,
)
async def get_agent(
    agent_id: str,
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    return await get_worker(worker_id=agent_id, actor=actor, db=db)


# ═══════════════════════════════════════════════════════════════════
# Worker Deletion
# ═══════════════════════════════════════════════════════════════════


@router.delete("/workers/{worker_id}", status_code=204)
async def remove_worker(
    worker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    worker = await _get_worker(db, worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)

    await hard_delete_worker(
        db, worker_id, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    await db.commit()
    return Response(status_code=204)


# ── Deprecated ──


@agents_router.delete("/agents/{agent_id}", status_code=204, deprecated=True)
async def remove_agent(
    agent_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await remove_worker(worker_id=agent_id, actor=actor, db=db)


# ═══════════════════════════════════════════════════════════════════
# Worker Suspend / Resume
# ═══════════════════════════════════════════════════════════════════


@router.post("/workers/{worker_id}/suspend", response_model=WorkerResponse)
async def suspend_worker(
    worker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    worker = await _get_worker(db, worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)

    worker = await _suspend_worker(
        db, worker_id, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    await db.commit()
    return WorkerResponse.model_validate(worker_to_response(worker))


# ── Deprecated ──


@agents_router.post("/agents/{agent_id}/suspend", response_model=WorkerResponse, deprecated=True)
async def suspend_agent(
    agent_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await suspend_worker(worker_id=agent_id, actor=actor, db=db)


@router.post("/workers/{worker_id}/resume", response_model=WorkerResponse)
async def resume_worker(
    worker_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    worker = await _get_worker(db, worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)

    worker = await _resume_worker(
        db, worker_id, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    await db.commit()
    return WorkerResponse.model_validate(worker_to_response(worker))


# ── Deprecated ──


@agents_router.post("/agents/{agent_id}/resume", response_model=WorkerResponse, deprecated=True)
async def resume_agent(
    agent_id: str,
    actor: ActorInfo = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await resume_worker(worker_id=agent_id, actor=actor, db=db)


# ═══════════════════════════════════════════════════════════════════
# Worker Handshake
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/workers/{worker_id}/handshake",
    response_model=WorkerResponse,
)
async def worker_handshake(
    worker_id: str,
    body: WorkerHandshakeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Worker handshake — manual API key validation (no get_current_actor).

    Accepts workers in pending or active status so newly registered
    workers can handshake to become active.
    """
    token = await extract_bearer_token(request)
    if not token:
        raise AuthenticationError("AUTH_MISSING_TOKEN", "Missing authentication token")

    key_hash = hash_api_key(token)
    result = await db.execute(
        select(Worker).where(
            Worker.id == worker_id,
            Worker.api_key_hash == key_hash,
        )
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        raise AuthenticationError("AUTH_INVALID_API_KEY", "Invalid API key")
    if worker.status not in (WorkerStatus.PENDING, WorkerStatus.ACTIVE):
        raise AuthenticationError(
            "AUTH_WORKER_NOT_ELIGIBLE_FOR_HANDSHAKE",
            "Worker is not eligible for handshake",
        )

    capabilities = [
        {
            "name": c.name,
            "description": c.description,
            "input_schema": c.input_schema,
            "output_schema": c.output_schema,
        }
        for c in body.capabilities
    ]

    worker = await _worker_handshake(
        db,
        worker_id=worker_id,
        worker_version=body.worker_version,
        capabilities=capabilities,
        supported_events=body.supported_events,
        preferred_channel=body.preferred_channel,
    )
    await db.commit()
    worker_data = worker_to_response(worker)
    # PFL-036: return WS URL so Worker knows where to connect
    parsed = request.url
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    worker_data["ws_url"] = f"{ws_scheme}://{parsed.netloc}/v1/ws"
    return WorkerResponse.model_validate(worker_data)


# ── Deprecated ──


@agents_router.post(
    "/agents/{agent_id}/handshake",
    response_model=WorkerResponse,
    deprecated=True,
)
async def agent_handshake(
    agent_id: str,
    body: WorkerHandshakeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await worker_handshake(worker_id=agent_id, body=body, request=request, db=db)


# ═══════════════════════════════════════════════════════════════════
# Worker Heartbeat
# ═══════════════════════════════════════════════════════════════════


@router.post("/workers/{worker_id}/heartbeat", status_code=200, response_model=WorkerHeartbeatResponse)
async def worker_heartbeat(
    worker_id: str,
    body: WorkerHeartbeatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Worker heartbeat — manual API key validation.

    P11-B94 (PFL-084): Response includes ``template_version`` so the Worker
    can detect template staleness on every heartbeat.  When ``resolve_role``
    falls back to the default "builder", ``role_warnings`` carries a hint.
    """
    token = await extract_bearer_token(request)
    if not token:
        raise AuthenticationError("AUTH_MISSING_TOKEN", "Missing authentication token")

    key_hash = hash_api_key(token)
    result = await db.execute(
        select(Worker).where(
            Worker.id == worker_id,
            Worker.api_key_hash == key_hash,
        )
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        raise AuthenticationError("AUTH_INVALID_API_KEY", "Invalid API key")
    if worker.status not in (WorkerStatus.PENDING, WorkerStatus.ACTIVE):
        raise AuthenticationError(
            "AUTH_WORKER_NOT_ACTIVE",
            "Worker is not active",
        )

    worker, recovery_event = await _worker_heartbeat(
        db,
        worker_id=worker_id,
        current_load=body.current_load,
        current_task_id=body.current_task_id,
    )
    await db.commit()

    # ── Template version (P11-B94 · PFL-084) ──
    versions = compute_template_versions()
    template_version: str | None = versions.get("version")

    # ── Role warnings (P11-B94 · B93 附属) ──
    role_warnings: list[str] = []
    _role, role_source = resolve_role(worker)
    if role_source == "default_fallback":
        role_warnings.append(
            "Worker metadata 中缺少 role 字段，已默认分配 builder 角色。"
            "请通过 POST /v1/projects/{pid}/workers/{wid}/roles 设置正确角色。"
        )

    return WorkerHeartbeatResponse(
        status="ok",
        runtime_status=worker.runtime_status,
        recovery_event=recovery_event,
        template_version=template_version,
        role_warnings=role_warnings,
    )


# ═══════════════════════════════════════════════════════════════════
# Template versions (P11-B94 · PFL-084)
# ═══════════════════════════════════════════════════════════════════


@router.get("/templates/versions")
async def get_template_versions():
    """Return current template version fingerprints.

    Worker clients call this at startup (--check-version) or during
    --upgrade to compare their local ``.claude/synapse-version.json``
    against the server.

    No auth required — template versions are not secret.
    """
    return compute_template_versions()


# ── Deprecated ──


@agents_router.post("/agents/{agent_id}/heartbeat", status_code=200, deprecated=True)
async def agent_heartbeat(
    agent_id: str,
    body: WorkerHeartbeatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    return await worker_heartbeat(worker_id=agent_id, body=body, request=request, db=db)


# ═══════════════════════════════════════════════════════════════════
# Task scheduling (P8-B5)
# ═══════════════════════════════════════════════════════════════════


@router.post(
    "/workers/{worker_id}/start-task",
)
async def start_task_endpoint(
    worker_id: str,
    task_id: str = Query(..., description="Task ID to start working on"),
    actor: ActorInfo = Depends(require_permission("task:start", resolve_project_id=_resolve_project_from_task_query)),
    db: AsyncSession = Depends(get_db),
):
    """Begin work on a task. Transitions REJECTED → IN_PROGRESS (P8-B5)."""
    worker = await _start_task(db, worker_id=worker_id, task_id=task_id)
    await db.commit()
    return {"status": "ok", "runtime_status": worker.runtime_status, "active_task_id": worker.active_task_id}


# ── Deprecated ──


@agents_router.post("/agents/{agent_id}/start-task", deprecated=True)
async def start_task_agent(
    agent_id: str,
    task_id: str = Query(..., description="Task ID to start working on"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    return await start_task_endpoint(worker_id=agent_id, task_id=task_id, actor=actor, db=db)


# ═══════════════════════════════════════════════════════════════════
# Protocol delivery (P9-B21)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/{worker_id}/protocol",
    response_model=ProtocolResponse,
)
async def get_worker_protocol(
    worker_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID to load context for"),
    role: str | None = Query(None, description="Override role (orchestrator|builder|steward)"),
    require_role: bool = Query(False, description="If true, refuse to serve protocol when role is default_fallback"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch rendered collaboration protocol for a worker.

    Authenticated via API Key or project_key (P11-B9).
    Returns project context, collaboration norms, role instructions,
    and env template with all ``{{VARIABLE}}`` placeholders filled from
    live DB data.
    """
    # ── Manual authentication ──
    token = await extract_bearer_token(request)
    if not token:
        raise AuthenticationError("AUTH_MISSING_TOKEN", "Missing authentication token")

    worker = None
    project = None

    # ① Try API key validation first
    key_hash = hash_api_key(token)
    result = await db.execute(
        select(Worker)
        .options(selectinload(Worker.team))
        .where(
            Worker.id == worker_id,
            Worker.api_key_hash == key_hash,
        )
    )
    worker = result.scalar_one_or_none()

    # ② API key failed → try project_key (P11-B9)
    if worker is None:
        proj_key_hash = hash_project_key(token)
        proj_result = await db.execute(
            select(Project).where(
                Project.project_key_hash == proj_key_hash,
            )
        )
        project_from_key = proj_result.scalar_one_or_none()

        if project_from_key is not None:
            # Load the worker and verify same-team membership
            worker = await db.get(Worker, worker_id)
            if worker is not None and worker.team_id == project_from_key.team_id:
                project = project_from_key  # use the key-authenticated project
            else:
                raise AuthenticationError(
                    "AUTH_WORKER_NOT_IN_PROJECT_TEAM",
                    "Worker does not belong to the same team as the project key",
                )

    if worker is None:
        raise AuthenticationError("AUTH_INVALID_API_KEY", "Invalid API key or project key")
    if worker.status not in (WorkerStatus.PENDING, WorkerStatus.ACTIVE):
        raise AuthenticationError(
            "AUTH_WORKER_NOT_ELIGIBLE",
            "Worker is not eligible for protocol access",
        )

    # ── Resolve role ──
    resolved_role, role_source = resolve_role(worker, role)

    # ── Hard-fail on default_fallback when require_role is set (P11-B97 · ㉔) ──
    if require_role is True and role_source == "default_fallback":
        raise SynapseError(
            status_code=422,
            code="WORKER_ROLE_NOT_CONFIGURED",
            message=(
                "Worker does not have a role configured in its metadata. "
                "Set the role via POST /v1/projects/{pid}/workers/{wid}/roles "
                "or add 'role' to the worker's metadata JSON. "
                "To bypass this check, omit the require_role query parameter."
            ),
        )

    # ── Load project (if not already loaded via project_key) ──
    if project is None:
        project = await db.get(Project, project_id)
        if project is None:
            raise NotFoundError("project", project_id)
        if project.team_id != worker.team_id:
            raise ForbiddenError(
                "FORBIDDEN_CROSS_TEAM",
                "Worker and project belong to different teams",
            )

    # ── Derive API base URL from request ──
    api_base_url = str(request.base_url).rstrip("/")

    # ── Render ──
    protocol = await render_protocol(
        worker,
        project,
        resolved_role,
        api_base_url=api_base_url,
        role_source=role_source,
    )

    return ProtocolResponse(**protocol)


# ── Deprecated ──


@agents_router.get(
    "/agents/{agent_id}/protocol",
    response_model=ProtocolResponse,
    deprecated=True,
)
async def get_agent_protocol(
    agent_id: str,
    request: Request,
    project_id: str = Query(..., description="Project ID to load context for"),
    role: str | None = Query(None, description="Override role (orchestrator|builder|steward)"),
    db: AsyncSession = Depends(get_db),
):
    return await get_worker_protocol(
        worker_id=agent_id, request=request, project_id=project_id, role=role, db=db, require_role=False
    )


# ═══════════════════════════════════════════════════════════════════
# Skill download (P9-B27)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/{worker_id}/skill/download",
    responses={404: {"model": None}, 403: {"model": None}},
)
async def download_skill(
    worker_id: str,
    project_id: str = Query(..., description="Project ID to load context for"),
    role: str | None = Query(None, description="Override role (orchestrator|builder|steward)"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Download a rendered SKILL.md file for a worker.

    Uses JWT auth (human users download Skills via the Web UI).
    Calls ``render_protocol()`` to resolve template variables from live DB
    data, then assembles the four rendered sections into a downloadable
    Markdown file with ``Content-Disposition: attachment``.
    """
    # ── Load worker with team relationship ──
    result = await db.execute(
        select(Worker)
        .options(selectinload(Worker.team))
        .where(Worker.id == worker_id)
    )
    worker = result.scalar_one_or_none()
    if worker is None:
        raise NotFoundError("worker", worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)

    # ── Load project ──
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFoundError("project", project_id)
    if project.team_id != actor.team_id:
        raise ForbiddenError(
            "FORBIDDEN_CROSS_TEAM",
            "Project belongs to a different team",
        )

    # ── Resolve role ──
    resolved_role, role_source = resolve_role(worker, role)

    # ── Render protocol sections ──
    protocol = await render_protocol(worker, project, resolved_role, role_source=role_source)

    # ── Assemble SKILL.md ──
    skill_md = f"""---
name: synapse
description: Synapse Worker — {worker.name} ({resolved_role})
---

# Synapse Worker — {worker.name}

> Role: **{resolved_role}** · Team: **{getattr(worker.team, 'name', 'Unknown')}** · Project: **{project.name}**

## 项目上下文

{protocol['project_context']}

---

## 协作纪律

{protocol['collaboration_norms']}

---

## 角色职责

{protocol['role_instructions']}

---

## 环境配置

{protocol['env_template']}
"""

    # ── Sanitize filename ──
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in worker.name).strip("-") or "worker"

    return Response(
        content=skill_md,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="synapse-skill-{safe_name}.md"',
        },
    )


# ── Deprecated ──


@agents_router.get(
    "/agents/{agent_id}/skill/download",
    responses={404: {"model": None}, 403: {"model": None}},
    deprecated=True,
)
async def download_skill_agent(
    agent_id: str,
    project_id: str = Query(..., description="Project ID to load context for"),
    role: str | None = Query(None, description="Override role (orchestrator|builder|steward)"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    return await download_skill(
        worker_id=agent_id, project_id=project_id, role=role, actor=actor, db=db
    )


# ═══════════════════════════════════════════════════════════════════
# Orchestrator Status (PFL-070 · B87)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/orchestrator-status",
    response_model=OrchestratorStatusResponse,
)
async def get_project_orchestrator_status(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """查询 Project 的 Orchestrator 心跳状态（PFL-070 · B87）。

    Builder Worker 在启动工作循环前调用此端点，确认 O 是否存活。
    支持 API Key 和 project_key 两种认证方式（与 protocol 端点一致）。

    返回 ``OrchestratorStatusResponse``：
    - ``online``: O 是否在线（last_heartbeat_at ≤ 120s）
    - ``worker_id`` / ``worker_name``: O 身份
    - ``last_heartbeat_at`` / ``heartbeat_age_seconds``: 心跳详情
    """
    # ── Manual authentication (same pattern as protocol endpoint) ──
    token = await extract_bearer_token(request)
    if not token:
        raise AuthenticationError("AUTH_MISSING_TOKEN", "Missing authentication token")

    key_hash = hash_api_key(token)
    result = await db.execute(
        select(Worker).where(
            Worker.api_key_hash == key_hash,
        )
    )
    worker = result.scalar_one_or_none()

    # project_key fallback
    if worker is None:
        proj_key_hash = hash_project_key(token)
        proj_result = await db.execute(
            select(Project).where(
                Project.project_key_hash == proj_key_hash,
            )
        )
        project_from_key = proj_result.scalar_one_or_none()
        if project_from_key is None or project_from_key.id != project_id:
            raise AuthenticationError(
                "AUTH_INVALID_TOKEN",
                "Invalid API key or project key for this project",
            )
    else:
        # Verify project exists and worker is in same team
        project = await db.get(Project, project_id)
        if project is None:
            raise NotFoundError("project", project_id)
        if project.team_id != worker.team_id:
            raise ForbiddenError(
                "FORBIDDEN_CROSS_TEAM",
                "Worker does not belong to the project's team",
            )

    status = await get_orchestrator_status(db, project_id)
    return OrchestratorStatusResponse(**status)
