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
    HeartbeatQueueState,
    TaskStateSummary,
    WorkerCreate,
    WorkerCreateResponse,
    WorkerHandshakeRequest,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerProjectResponse,
    WorkerHealthSummaryResponse,
    WorkerResponse,
    WorkerStateResponse,
    OrchestratorStatusResponse,
)
from src.schemas.common import CursorPage
from src.schemas.protocol import ProtocolResponse
from src.services.worker_service import (
    UNSET,
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
    get_worker_health_summary as _get_worker_health_summary,
)
from src.services.project_role_service import get_worker_projects
from src.services.worker_scheduler import start_task as _start_task
from src.services.state_router import compute_state_router

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
# Worker Health Summary (P16-B6 任务 B)
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/{worker_id}/health-summary",
    response_model=WorkerHealthSummaryResponse,
    responses={404: {"model": None}},
)
async def get_worker_health_summary_endpoint(
    worker_id: str,
    window_hours: int = Query(
        24,
        ge=1,
        le=720,
        description="统计窗口（小时），默认 24",
    ),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """Worker 心跳健康摘要 — 窗口内跳了多少次、多久一跳、现在还在不在线。

    数据源是任务 A 落库的 ``worker.heartbeat`` 事件。CLI 健康报告（任务 C）
    和人类排障靠它回答「这个 Worker 的心跳稳不稳」，而不只是「最后一跳是何时」。

    认证与本 router 其它端点一致（未认证 → 401）；Worker 不存在或跨 team → 404。
    """
    worker = await _get_worker(db, worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)

    summary = await _get_worker_health_summary(db, worker, window_hours=window_hours)
    return WorkerHealthSummaryResponse(**summary)


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

    # P16-B5 PFL-247: 只有请求体**显式**给了 current_task_id 才传下去。
    # 缺省 → 传 UNSET → 服务层保持现有 active_task_id（不再把 claim 挂上的
    # 活跃任务擦掉）。显式 null 的「清空」语义原样保留。
    worker, recovery_event = await _worker_heartbeat(
        db,
        worker_id=worker_id,
        current_load=body.current_load,
        current_task_id=(
            body.current_task_id
            if "current_task_id" in body.model_fields_set
            else UNSET
        ),
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

    # ── State-router (P16-B2) ──
    routing = await compute_state_router(db, worker, body.project_id)
    role_warnings.extend(routing["role_warnings"])

    return WorkerHeartbeatResponse(
        status="ok",
        runtime_status=worker.runtime_status,
        recovery_event=recovery_event,
        template_version=template_version,
        role_warnings=role_warnings,
        role=routing["role"],
        next_action=routing["next_action"],
        active_task_id=routing["active_task_id"],
        queue=HeartbeatQueueState(**routing["queue"]) if routing["queue"] else None,
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
