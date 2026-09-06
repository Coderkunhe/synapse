"""Worker info routes — state snapshot, protocol, error reporting, skill download."""

from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.auth import extract_bearer_token, hash_api_key, hash_project_key
from src.db import get_db
from src.dependencies import ActorInfo, get_current_actor
from src.exceptions import AuthenticationError, ForbiddenError, NotFoundError, SynapseError
from src.models.worker import Worker
from src.constants import ActorType, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, TaskStatus, WorkerActorType, WorkerStatus
from src.models.project import Project
from src.models.task import Task
from src.models.authorization_request import AuthorizationRequest
from src.models.event import Event
from src.permissions import require_permission
from src.schemas.worker import (
    API_KEY_WARNING,
    AuthRequestStateSummary,
    ErrorReportRequest,
    ErrorReportResponse,
    ErrorReportSummary,
    TaskStateSummary,
    WorkerProjectResponse,
    WorkerStateResponse,
)
from src.schemas.common import CursorPage
from src.schemas.protocol import ProtocolResponse
from src.services.worker_service import (
    worker_to_response,
    get_worker as _get_worker,
)
from src.services.event_store import event_store
from src.services.pitfall_service import create_pitfall
from src.services.project_role_service import get_worker_projects, get_project_role
from src.services.template_service import render_protocol, resolve_role, compute_template_versions

from .helpers import _parse_event_payload, _events_to_error_summaries, get_team_or_404
from src.utils.json_utils import safe_loads

logger = logging.getLogger(__name__)

router = APIRouter()
agents_router = APIRouter()  # backward compat, all routes deprecated

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

    # Resolve role — P16-B11 (PFL-253): 与 state-router 同源，优先 project 级
    # project_actor_roles，缺记录才回退 metadata 级 resolve_role。
    resolved_role = await get_project_role(db, project_id, worker.id)
    if resolved_role is None:
        resolved_role, _ = resolve_role(worker)

    # ── Query tasks by status ──
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    STALE_THRESHOLD_MINUTES = 15

    def _task_summary(t) -> TaskStateSummary:
        # P16-B11 (PFL-251/266): ``Task.depends_on`` 是 JSON 字符串列
        # （``[{"task_id": ..., "type": ...}]``），不是 list。直接塞给
        # ``list[str]`` 会在非空依赖时触发 ResponseValidationError → 500。
        # 这里解析后只提取 task_id 列表，供 Worker 定位依赖。
        deps = safe_loads(t.depends_on)
        depends_on_ids: list[str] = []
        if isinstance(deps, list):
            for d in deps:
                if isinstance(d, dict):
                    tid = d.get("task_id")
                    if isinstance(tid, str):
                        depends_on_ids.append(tid)

        return TaskStateSummary(
            id=t.id,
            title=t.title,
            status=t.status,
            owner_id=t.owner_id,
            owner_name=getattr(t, "owner_name", None),
            owner_type=getattr(t, "owner_type", None),
            priority=t.priority,
            batch_id=t.batch_id,
            depends_on=depends_on_ids,
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
# P14-B3: Error Report Listing（诊断查询入口）
# ═══════════════════════════════════════════════════════════════════


@router.get(
    "/workers/{worker_id}/error-reports",
    response_model=CursorPage[ErrorReportSummary],
)
async def list_worker_error_reports(
    worker_id: str,
    cursor: str | None = Query(None, description="复合游标（created_at,id）"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    severity: str | None = Query(None, pattern=r"^(🔴|🟡|🟢)$"),
    actor: ActorInfo = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
):
    """查询 Worker 的历史错误报告（P14-B3 诊断加固）。

    支持 cursor 分页（基于 (created_at, id) 复合游标）+ severity 筛选（SQL 层）。
    O 和 God's-eye 通过此端点快速定位 Builder 的故障历史。
    """
    worker = await _get_worker(db, worker_id)
    if worker.team_id != actor.team_id:
        raise NotFoundError("worker", worker_id)

    from sqlalchemy import and_, or_

    from src.constants import EventType as ET
    from src.models.event import Event as EventModel

    conditions = [
        EventModel.event_type == ET.WORKER_ERROR_REPORTED,
        EventModel.target_type == "worker",
        EventModel.target_id == worker_id,
    ]

    # ── severity 过滤（P14-B3.1 P1 修复：下推到 SQL 层）──
    if severity:
        # payload 以 JSON 字符串存储 → LIKE 模式匹配
        conditions.append(EventModel.payload.like(f'%"severity": "{severity}"%'))

    # ── cursor 分页（P14-B3.1 P2 修复：复合游标 (created_at, id)）──
    if cursor:
        parts = cursor.split(",", 1)
        cursor_ts = parts[0]
        cursor_id = parts[1] if len(parts) > 1 else None
        if cursor_id:
            conditions.append(
                or_(
                    EventModel.created_at < cursor_ts,
                    and_(
                        EventModel.created_at == cursor_ts,
                        EventModel.id < cursor_id,
                    ),
                )
            )
        else:
            conditions.append(EventModel.created_at < cursor_ts)

    query = (
        select(EventModel)
        .where(*conditions)
        .order_by(EventModel.created_at.desc(), EventModel.id.desc())
        .limit(limit + 1)
    )
    result = await db.execute(query)
    events = result.scalars().all()

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    items = _events_to_error_summaries(events)
    next_cursor = (
        f"{events[-1].created_at.isoformat()},{events[-1].id}"
        if has_more and items
        else None
    )

    return CursorPage(items=items, next_cursor=next_cursor, total=None)


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


