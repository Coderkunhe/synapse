"""AuthorizationRequest 服务 — 异步授权请求的业务逻辑层。

P10-B21: 议题 3 授权管道后半段 — Service 层首次落地。

核心能力：
- create: 创建授权请求 + 流控（max_pending ≤ 5）
- respond: 人类审批/拒绝 pending 请求
- heartbeat: Worker 心跳续期（防过期）
- expire: 批量过期（定时任务调用）
- cancel: Worker 重启级联失效

调用方持有事务 — 本服务不 commit。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import (
    MAX_PENDING_AUTH_REQUESTS,
    ActorType,
    EventType,
)
from src.exceptions import ConflictError, ForbiddenError, InvalidStateTransition, NotFoundError
from src.models.authorization_request import AuthorizationRequest
from src.services.event_store import event_store
from src.utils.id_gen import generate_id


# ── 查询辅助 ──────────────────────────────────────────────────────


async def get_pending_count(
    db: AsyncSession,
    worker_id: str,
) -> int:
    """获取某 Worker 当前 pending 的授权请求数（流控用）。"""
    result = await db.execute(
        select(AuthorizationRequest).where(
            AuthorizationRequest.worker_id == worker_id,
            AuthorizationRequest.status == "pending",
        )
    )
    return len(result.scalars().all())


async def get_request(
    db: AsyncSession,
    request_id: str,
) -> AuthorizationRequest:
    """按 ID 获取授权请求，不存在则 raise NotFoundError。"""
    result = await db.execute(
        select(AuthorizationRequest).where(
            AuthorizationRequest.id == request_id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise NotFoundError("AuthorizationRequest", request_id)
    return record


# ── 写入 ──────────────────────────────────────────────────────────


async def create_authorization_request(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    request_type: str,
    # api_auth 字段组
    operation: str | None = None,
    target_resource_type: str | None = None,
    target_resource_id: str | None = None,
    # interactive_prompt 字段组
    prompt_type: str | None = None,
    prompt_message: str | None = None,
    prompt_choices: list[str] | None = None,
    # 配置
    ttl_seconds: int = 3600,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> AuthorizationRequest:
    """创建授权请求。

    业务校验：
    - api_auth: operation 必填
    - interactive_prompt: prompt_type + prompt_message 必填
    - 流控：同一个 Worker 最多 MAX_PENDING_AUTH_REQUESTS 个 pending 请求

    Raises:
        ForbiddenError: 缺少必填字段或超过流控上限
    """
    # ── 字段组校验 ──
    if request_type == "api_auth":
        if not operation:
            raise ForbiddenError(
                code="MISSING_REQUIRED_FIELD",
                message="api_auth 类型的授权请求必须提供 operation",
                details={"request_type": request_type, "missing_field": "operation"},
            )
    elif request_type == "interactive_prompt":
        if not prompt_type or not prompt_message:
            raise ForbiddenError(
                code="MISSING_REQUIRED_FIELD",
                message="interactive_prompt 类型的授权请求必须提供 prompt_type 和 prompt_message",
                details={"request_type": request_type, "missing_field": "prompt_type or prompt_message"},
            )

    # ── 流控 ──
    pending = await get_pending_count(db, worker_id)
    if pending >= MAX_PENDING_AUTH_REQUESTS:
        raise ConflictError(
            code="TOO_MANY_PENDING_REQUESTS",
            message=f"Worker {worker_id} 已有 {pending} 个 pending 授权请求（上限 {MAX_PENDING_AUTH_REQUESTS}）",
            details={
                "worker_id": worker_id,
                "pending_count": pending,
                "max_allowed": MAX_PENDING_AUTH_REQUESTS,
            },
        )

    now = datetime.now(timezone.utc)
    record = AuthorizationRequest(
        id=generate_id("authorization_request"),
        project_id=project_id,
        worker_id=worker_id,
        request_type=request_type,
        operation=operation,
        target_resource_type=target_resource_type,
        target_resource_id=target_resource_id,
        prompt_type=prompt_type,
        prompt_message=prompt_message,
        prompt_choices_json=_serialize_choices(prompt_choices),
        status="pending",
        expires_at=now + timedelta(seconds=ttl_seconds),
        last_heartbeat_at=now,
    )
    db.add(record)
    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.AUTHORIZATION_REQUEST_CREATED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="authorization_request",
        target_id=record.id,
        payload={
            "project_id": project_id,
            "worker_id": worker_id,
            "request_type": request_type,
            "operation": operation,
            "prompt_type": prompt_type,
        },
    )

    # P10-B33: Email notify project admins — fire-and-forget
    from src.services.notification_service import notify_project_admins
    await notify_project_admins(
        db,
        project_id=project_id,
        worker_id=worker_id,
        request_type=request_type,
        operation=operation,
        prompt_message=prompt_message,
    )

    # P10-B34: Webhook notify — fire-and-forget
    from src.services.notification_service import notify_webhook
    await notify_webhook(
        db,
        project_id=project_id,
        worker_id=worker_id,
        request_type=request_type,
        request_id=record.id,
        operation=operation,
        prompt_message=prompt_message,
    )

    # P10-B45: WebPush notify project admins — fire-and-forget
    from src.services.notification_service import notify_webpush
    await notify_webpush(
        db,
        project_id=project_id,
        worker_id=worker_id,
        request_type=request_type,
        operation=operation,
        prompt_message=prompt_message,
        request_id=record.id,
    )

    return record


async def respond_to_request(
    db: AsyncSession,
    *,
    request_id: str,
    responder_worker_id: str,
    status: str,
    response_note: str | None = None,
    response_data: str | None = None,
    # 事件元数据
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> AuthorizationRequest:
    """响应授权请求 — 批准或拒绝。

    只有 pending 状态的请求可以被响应。

    P10-B31 (S-065): api_auth 类型被批准时，自动为 Worker 授予
    project 的 member 角色，使 Worker 重试时能通过权限检查。

    Raises:
        NotFoundError: 请求不存在
        InvalidStateTransition: 请求不是 pending 状态
    """
    record = await get_request(db, request_id)

    if record.status != "pending":
        raise InvalidStateTransition(
            entity_type="AuthorizationRequest",
            entity_id=request_id,
            from_status=record.status,
            to_status=status,
        )

    now = datetime.now(timezone.utc)
    record.status = status
    record.responded_by_worker_id = responder_worker_id
    record.responded_at = now
    record.response_note = response_note
    record.response_data_json = response_data

    # ── P10-B31 (S-065): auto-grant member role on api_auth approval ──
    if status == "approved" and record.request_type == "api_auth":
        await _auto_grant_project_membership(
            db,
            project_id=record.project_id,
            worker_id=record.worker_id,
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    await db.flush()

    await event_store.record(
        db,
        event_type=EventType.AUTHORIZATION_REQUEST_RESPONDED,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="authorization_request",
        target_id=record.id,
        payload={
            "request_id": request_id,
            "status": status,
            "responder_worker_id": responder_worker_id,
            "response_note": response_note,
        },
    )

    # P10-B36: DecisionAudit — 记录审批决策
    from src.services.decision_audit_service import record_decision
    await record_decision(
        db,
        authorization_request_id=request_id,
        decision_type="approve" if status == "approved" else "deny",
        actor_type=actor_type,
        actor_id=actor_id,
        project_id=record.project_id,
        worker_id=record.worker_id,
        risk_level=_assess_risk_level(record),
        reason=response_note or (f"Authorization request {status} by {actor_type}:{actor_id}"),
        context={
            "request_type": record.request_type,
            "operation": record.operation,
            "responder_worker_id": responder_worker_id,
        },
        team_id=team_id,
    )

    return record


async def heartbeat(
    db: AsyncSession,
    request_id: str,
) -> AuthorizationRequest:
    """心跳续期 — Worker 定期调用以保持授权请求存活。

    更新 last_heartbeat_at 为当前时间。不记录事件（高频操作）。

    Raises:
        NotFoundError: 请求不存在
        InvalidStateTransition: 请求不是 pending 状态
    """
    record = await get_request(db, request_id)

    if record.status != "pending":
        raise InvalidStateTransition(
            entity_type="AuthorizationRequest",
            entity_id=request_id,
            from_status=record.status,
            to_status="heartbeat",
        )

    record.last_heartbeat_at = datetime.now(timezone.utc)
    await db.flush()

    return record


async def expire_stale_requests(
    db: AsyncSession,
) -> int:
    """批量过期 — 将所有 pending 且 expires_at < now 的请求标记为 expired。

    由定时任务/调度器调用。使用 SYSTEM actor 记录事件。
    P10-B34: 批量过期时 WS push 通知 Worker（订阅了 AUTHORIZATION_REQUEST_EXPIRED topic · L5 拉通补缺）。

    Returns:
        被过期的请求数量。
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(AuthorizationRequest).where(
            AuthorizationRequest.status == "pending",
            AuthorizationRequest.expires_at < now,
        )
    )
    stale = result.scalars().all()

    for record in stale:
        record.status = "expired"
        await event_store.record(
            db,
            event_type=EventType.AUTHORIZATION_REQUEST_EXPIRED,
            team_id="",  # 批量操作，跨 team
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            target_type="authorization_request",
            target_id=record.id,
            payload={
                "request_id": record.id,
                "worker_id": record.worker_id,
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            },
        )

        # P10-B36: DecisionAudit — 记录过期决策
        from src.services.decision_audit_service import record_decision
        await record_decision(
            db,
            authorization_request_id=record.id,
            decision_type="expire",
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            project_id=record.project_id,
            worker_id=record.worker_id,
            risk_level="low",
            reason="Authorization request expired",
            context={
                "request_type": record.request_type,
                "operation": record.operation,
                "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            },
            team_id="",
        )

        # P10-B34: WS push to Worker — notify of expiry (L5 拉通补缺)
        from src.services.ws_manager import ws_manager
        await ws_manager.broadcast_to_actor(
            record.worker_id,
            {
                "type": "event",
                "data": {
                    "event_type": EventType.AUTHORIZATION_REQUEST_EXPIRED,
                    "authorization_request_id": record.id,
                    "status": "expired",
                    "request_type": record.request_type,
                },
            },
        )

    if stale:
        await db.flush()

    return len(stale)


async def cancel_worker_requests(
    db: AsyncSession,
    *,
    worker_id: str,
) -> int:
    """Worker 重启级联失效 — 将该 Worker 所有 pending 请求标记为 cancelled。

    Worker 离线/重启时调用，防止孤儿 pending 请求永久阻塞。
    P10-B34: 级联取消时 WS push 通知 Worker（订阅了 AUTHORIZATION_REQUEST_CANCELLED topic · L5 拉通补缺）。

    Returns:
        被取消的请求数量。
    """
    result = await db.execute(
        select(AuthorizationRequest).where(
            AuthorizationRequest.worker_id == worker_id,
            AuthorizationRequest.status == "pending",
        )
    )
    pending = result.scalars().all()

    for record in pending:
        record.status = "cancelled"
        await event_store.record(
            db,
            event_type=EventType.AUTHORIZATION_REQUEST_CANCELLED,
            team_id="",  # 级联操作，从 Worker 级触发
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            target_type="authorization_request",
            target_id=record.id,
            payload={
                "request_id": record.id,
                "worker_id": worker_id,
                "reason": "worker_restart_cascade",
            },
        )

        # P10-B36: DecisionAudit — 记录取消决策
        from src.services.decision_audit_service import record_decision
        await record_decision(
            db,
            authorization_request_id=record.id,
            decision_type="cancel",
            actor_type=ActorType.SYSTEM,
            actor_id="system",
            project_id=record.project_id,
            worker_id=worker_id,
            risk_level="low",
            reason="Worker restart cascade — pending requests cancelled",
            context={
                "request_type": record.request_type,
                "operation": record.operation,
                "reason": "worker_restart_cascade",
            },
            team_id="",
        )

        # P10-B34: WS push to Worker — notify of cancellation (L5 拉通补缺)
        from src.services.ws_manager import ws_manager
        await ws_manager.broadcast_to_actor(
            worker_id,
            {
                "type": "event",
                "data": {
                    "event_type": EventType.AUTHORIZATION_REQUEST_CANCELLED,
                    "authorization_request_id": record.id,
                    "status": "cancelled",
                    "request_type": record.request_type,
                },
            },
        )

    if pending:
        await db.flush()

    return len(pending)


# ── P10-B31 (S-065): auto-grant on api_auth approval ──────────────────


async def _auto_grant_project_membership(
    db: AsyncSession,
    *,
    project_id: str,
    worker_id: str,
    team_id: str,
    actor_type: str,
    actor_id: str,
) -> None:
    """Grant the Worker a 'member' role in the project if they don't
    already have one.

    Called when an api_auth AuthorizationRequest is approved.
    If the Worker already has a role in the project, it is preserved
    (no downgrade). Otherwise, they are granted the minimal 'member'
    role so they can retry their original operation.
    """
    from src.services.project_role_service import get_project_role, set_project_role

    existing = await get_project_role(db, project_id, worker_id)
    if existing is not None:
        # Worker already has a role — don't downgrade
        return

    await set_project_role(
        db,
        project_id=project_id,
        worker_id=worker_id,
        role="member",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
    )

    # P10-B36: DecisionAudit — 记录自动授权决策
    from src.services.decision_audit_service import record_decision
    await record_decision(
        db,
        authorization_request_id=None,  # auto_grant 无关联的 auth request
        decision_type="auto_grant",
        actor_type=ActorType.SYSTEM,
        actor_id="system",
        project_id=project_id,
        worker_id=worker_id,
        risk_level="low",
        reason="Auto-granted member role on api_auth approval",
        context={
            "trigger": "api_auth_approved",
            "granted_role": "member",
        },
        team_id=team_id,
    )


# ── 内部辅助 ──────────────────────────────────────────────────────


def _assess_risk_level(record: AuthorizationRequest) -> str:
    """基于授权请求类型评估决策风险等级。

    P10-B36: 为 DecisionAudit 提供风险上下文。
    - api_auth 操作 "task.assign" → medium（涉及资源重分配）
    - interactive_prompt → low（人类在回路中）
    - 其他 → low
    """
    if record.request_type == "api_auth":
        if record.operation == "task.assign":
            return "medium"
    return "low"


def _serialize_choices(choices: list[str] | None) -> str | None:
    """将 prompt_choices 列表序列化为 JSON 字符串。"""
    if choices is None:
        return None
    import json
    return json.dumps(choices, ensure_ascii=False)
